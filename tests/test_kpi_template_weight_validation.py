from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestKpiTemplateWeightValidation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.KpiTemplate = self.env["hr.kpi.template"]
        self.KpiLine = self.env["hr.kpi.template.line"]
        self.Pillar = self.env["hr.evaluation.pillar"]
        self.p3_individual = self._get_pillar("p3_individual", "P3 Individual")

    # Lấy pillar normalized để test đúng rule weight của flow employee template.
    def _get_pillar(self, code, default_name):
        pillar = self.Pillar.search([("code", "=", code)], limit=1)
        if not pillar:
            pillar = self.Pillar.create({"name": default_name, "code": code})
        return pillar

    # Tạo employee KPI template tối thiểu để test tập trung vào deferred validation.
    def _create_template(self, name="Weight Validation Template"):
        return self.KpiTemplate.create({"name": name, "period_type": "monthly"})

    # Tạo line manual để tránh side effects từ auto formula trong test validation.
    def _line_vals(self, template, title, weight, parent=False):
        return {
            "kpi_id": template.id,
            "key_performance_area": title,
            "pillar_id": self.p3_individual.id,
            "kpi_type": "manual",
            "manual_scoring_type": "score",
            "weight": weight,
            "parent_line_id": parent.id if parent else False,
        }

    # Dựng cây normalized hợp lệ 100 -> 60/40 để các test chỉ thay đổi đúng phần cần verify.
    def _create_valid_section_tree(self, name="Tree Template"):
        template = self._create_template(name)
        root = self.KpiLine.create(self._line_vals(template, "Section", 100.0))
        child_a, child_b = self.KpiLine.create(
            [
                self._line_vals(template, "Child A", 60.0, parent=root),
                self._line_vals(template, "Child B", 40.0, parent=root),
            ]
        )
        return template, root, child_a, child_b

    # Parent write phải nhìn thấy toàn bộ sibling updates ở trạng thái cuối cùng.
    def test_parent_write_validates_sibling_weight_updates_once(self):
        template, _, child_a, child_b = self._create_valid_section_tree(
            "Sibling Update Template"
        )

        template.write(
            {
                "kpi_line_ids": [
                    (1, child_a.id, {"weight": 70.0}),
                    (1, child_b.id, {"weight": 30.0}),
                ]
            }
        )

        self.assertEqual(child_a.weight, 70.0)
        self.assertEqual(child_b.weight, 30.0)

    # Parent write vẫn phải chặn nếu tổng cuối cùng của sibling không khớp parent weight.
    def test_parent_write_raises_for_invalid_final_child_total(self):
        template, _, child_a, child_b = self._create_valid_section_tree(
            "Invalid Child Total Template"
        )

        with self.assertRaises(ValidationError):
            template.write(
                {
                    "kpi_line_ids": [
                        (1, child_a.id, {"weight": 70.0}),
                        (1, child_b.id, {"weight": 40.0}),
                    ]
                }
            )

    # Parent write phải bỏ qua ghost child vừa bị xóa và chỉ tính snapshot cuối cùng.
    def test_parent_write_ignores_deleted_child_when_replacing_it(self):
        template, root, child_a, child_b = self._create_valid_section_tree(
            "Delete Create Template"
        )

        template.write(
            {
                "kpi_line_ids": [
                    (2, child_b.id, 0),
                    (0, 0, self._line_vals(template, "Child C", 40.0, parent=root)),
                    (1, child_a.id, {"weight": 60.0}),
                ]
            }
        )

        self.assertEqual(
            template.kpi_line_ids.filtered(lambda line: line.parent_line_id == root).mapped(
                "key_performance_area"
            ),
            ["Child A", "Child C"],
        )
        self.assertEqual(
            sum(root.child_line_ids.filtered(lambda line: line.id).mapped("weight")),
            100.0,
        )

    # Root total cuối cùng vẫn phải bị chặn nếu parent form lưu về trạng thái không bằng 100.
    def test_parent_write_raises_for_invalid_final_root_total(self):
        template = self._create_template("Invalid Root Total Template")
        root_a, root_b = self.KpiLine.create(
            [
                self._line_vals(template, "Root A", 50.0),
                self._line_vals(template, "Root B", 50.0),
            ]
        )

        with self.assertRaises(ValidationError):
            template.write(
                {
                    "kpi_line_ids": [
                        (1, root_a.id, {"weight": 60.0}),
                        (1, root_b.id, {"weight": 30.0}),
                    ]
                }
            )

    # Direct line writes không còn bắn normalized validation giữa chừng nữa.
    def test_direct_line_write_no_longer_triggers_normalized_validation(self):
        _, _, child_a, _ = self._create_valid_section_tree("Direct Line Write Template")

        child_a.write({"weight": 70.0})

        self.assertEqual(child_a.weight, 70.0)

    # Direct line create vẫn giữ sequence cleanup nhưng không còn ép normalized validation ngay.
    def test_direct_line_create_no_longer_triggers_normalized_validation(self):
        template = self._create_template("Direct Line Create Template")

        root = self.KpiLine.create(self._line_vals(template, "Section", 100.0))
        created_child = self.KpiLine.create(
            self._line_vals(template, "Only Child", 70.0, parent=root)
        )

        self.assertTrue(created_child.id)
        self.assertEqual(created_child.parent_line_id, root)
