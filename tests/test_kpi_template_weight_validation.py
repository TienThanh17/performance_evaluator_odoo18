from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestKpiTemplateWeightValidation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.KpiTemplate = self.env["hr.kpi.template"]
        self.KpiLine = self.env["hr.kpi.template.line"]
        self.Pillar = self.env["hr.evaluation.pillar"]
        self.Evaluation = self.env["hr.performance.evaluation"]
        self.DepartmentTemplate = self.env["hr.department.kpi.template"]
        self.DepartmentLine = self.env["hr.department.kpi.template.line"]
        self.DepartmentEvaluation = self.env["hr.department.performance.evaluation"]
        self.Employee = self.env["hr.employee"]
        self.Department = self.env["hr.department"]
        self.p3_individual = self._get_pillar("p3_individual", "P3 Individual")
        self.p3_department = self._get_pillar("p3_department", "P3 Department")
        self.department = self.Department.create({"name": "Weight Test Department"})
        self.employee = self.Employee.create(
            {
                "name": "Weight Test Employee",
                "department_id": self.department.id,
            }
        )

    # Lấy pillar cần dùng cho test; nếu DB test chưa có thì tạo tối thiểu một lần.
    def _get_pillar(self, code, default_name):
        pillar = self.Pillar.search([("code", "=", code)], limit=1)
        if not pillar:
            pillar = self.Pillar.create({"name": default_name, "code": code})
        return pillar

    # Tạo employee KPI template tối thiểu để test tập trung vào logic weight tree.
    def _create_template(self, name="Weight Validation Template"):
        return self.KpiTemplate.create(
            {
                "name": name,
                "period_type": "monthly",
                "department_id": self.department.id,
            }
        )

    # Tạo department KPI template tối thiểu để test flow phòng ban.
    def _create_department_template(self, name="Department Weight Template"):
        return self.DepartmentTemplate.create(
            {
                "name": name,
                "period_type": "monthly",
                "department_id": self.department.id,
            }
        )

    # Trả về vals cho section employee line để weight được hệ thống tự roll-up.
    def _employee_section_vals(self, template, title, parent=False):
        return {
            "kpi_id": template.id,
            "key_performance_area": title,
            "pillar_id": self.p3_individual.id,
            "is_section": True,
            "display_type": "line_section",
            "parent_line_id": parent.id if parent else False,
        }

    # Trả về vals cho leaf employee KPI line có weight do user nhập.
    def _employee_leaf_vals(self, template, title, weight, parent=False):
        return {
            "kpi_id": template.id,
            "key_performance_area": title,
            "pillar_id": self.p3_individual.id,
            "kpi_type": "manual",
            "manual_scoring_type": "score",
            "weight": weight,
            "parent_line_id": parent.id if parent else False,
        }

    # Trả về vals cho section department line để weight được hệ thống tự roll-up.
    def _department_section_vals(self, template, title, parent=False):
        return {
            "department_kpi_id": template.id,
            "name": title,
            "pillar_id": self.p3_department.id,
            "is_section": True,
            "display_type": "line_section",
            "parent_line_id": parent.id if parent else False,
        }

    # Trả về vals cho leaf department KPI line có weight do user nhập.
    def _department_leaf_vals(self, template, title, weight, parent=False):
        return {
            "department_kpi_id": template.id,
            "name": title,
            "pillar_id": self.p3_department.id,
            "kpi_type": "manual",
            "manual_scoring_type": "score",
            "weight": weight,
            "parent_line_id": parent.id if parent else False,
        }

    # Section phải tự cộng weight từ toàn bộ direct leaf child của nó.
    def test_employee_section_weight_rolls_up_from_direct_children(self):
        template = self._create_template("Employee Rollup Template")
        section = self.KpiLine.create(
            self._employee_section_vals(template, "Main Section")
        )

        self.KpiLine.create(
            [
                self._employee_leaf_vals(template, "Leaf A", 70.0, parent=section),
                self._employee_leaf_vals(template, "Leaf B", 30.0, parent=section),
            ]
        )

        self.assertEqual(section.weight, 100.0)

    # Section cha phải cộng cả leaf direct child và section direct child theo cây lồng nhau.
    def test_employee_nested_section_weight_rolls_up_with_mixed_direct_children(self):
        template = self._create_template("Nested Rollup Template")
        root = self.KpiLine.create(self._employee_section_vals(template, "Root"))
        child_section = self.KpiLine.create(
            self._employee_section_vals(template, "Child Section", parent=root)
        )

        self.KpiLine.create(
            [
                self._employee_leaf_vals(template, "Root Leaf", 20.0, parent=root),
                self._employee_leaf_vals(
                    template, "Nested Leaf", 80.0, parent=child_section
                ),
            ]
        )

        self.assertEqual(child_section.weight, 80.0)
        self.assertEqual(root.weight, 100.0)

    # Root-level leaf KPI được phép có tổng weight bất kỳ, không còn bị ép bằng 100.
    def test_employee_root_leaf_totals_no_longer_must_equal_one_hundred(self):
        template = self._create_template("Free Root Total Template")

        leaf_a, leaf_b = self.KpiLine.create(
            [
                self._employee_leaf_vals(template, "Leaf A", 60.0),
                self._employee_leaf_vals(template, "Leaf B", 30.0),
            ]
        )

        self.assertEqual(leaf_a.weight, 60.0)
        self.assertEqual(leaf_b.weight, 30.0)
        self.assertEqual(sum(template.kpi_line_ids.mapped("weight")), 90.0)

    # Chỉ còn ràng buộc không cho weight âm trên leaf line.
    def test_employee_negative_weight_is_still_rejected(self):
        template = self._create_template("Negative Weight Template")

        with self.assertRaises(ValidationError):
            self.KpiLine.create(self._employee_leaf_vals(template, "Bad Leaf", -1.0))

    # Khi sửa weight của leaf, toàn bộ section ancestor phải tự cập nhật ngay.
    def test_employee_leaf_weight_edit_updates_ancestor_sections(self):
        template = self._create_template("Leaf Edit Rollup Template")
        root = self.KpiLine.create(self._employee_section_vals(template, "Root"))
        child_section = self.KpiLine.create(
            self._employee_section_vals(template, "Child Section", parent=root)
        )
        leaf = self.KpiLine.create(
            self._employee_leaf_vals(template, "Leaf", 40.0, parent=child_section)
        )

        leaf.write({"weight": 55.0})

        self.assertEqual(child_section.weight, 55.0)
        self.assertEqual(root.weight, 55.0)

    # Khi đổi parent của leaf, weight của cả nhánh cũ và nhánh mới phải được đồng bộ lại.
    def test_employee_reparenting_updates_old_and_new_section_totals(self):
        template = self._create_template("Reparent Rollup Template")
        root_a, root_b = self.KpiLine.create(
            [
                self._employee_section_vals(template, "Root A"),
                self._employee_section_vals(template, "Root B"),
            ]
        )
        leaf = self.KpiLine.create(
            self._employee_leaf_vals(template, "Movable Leaf", 25.0, parent=root_a)
        )

        leaf.write({"parent_line_id": root_b.id})

        self.assertEqual(root_a.weight, 0.0)
        self.assertEqual(root_b.weight, 25.0)

    # Khi xóa leaf, section cha phải giảm weight tương ứng trên state cuối.
    def test_employee_leaf_delete_updates_section_total(self):
        template = self._create_template("Delete Rollup Template")
        section = self.KpiLine.create(self._employee_section_vals(template, "Section"))
        leaf_a, leaf_b = self.KpiLine.create(
            [
                self._employee_leaf_vals(template, "Leaf A", 60.0, parent=section),
                self._employee_leaf_vals(template, "Leaf B", 40.0, parent=section),
            ]
        )

        leaf_b.unlink()

        self.assertEqual(section.weight, 60.0)
        self.assertEqual(leaf_a.weight, 60.0)

    # Generate evaluation phải snapshot section weight sau khi template đã được roll-up hoàn chỉnh.
    def test_employee_evaluation_generation_inherits_computed_section_weight(self):
        template = self._create_template("Employee Evaluation Snapshot Template")
        section = self.KpiLine.create(self._employee_section_vals(template, "Section"))
        self.KpiLine.create(
            self._employee_leaf_vals(template, "Leaf", 35.0, parent=section)
        )

        evaluation = self.Evaluation.new({"employee_id": self.employee.id})
        commands = evaluation._prepare_evaluation_line_commands_from_template(template)
        section_command = next(
            command
            for command in commands
            if isinstance(command[2], dict) and command[2].get("is_section")
        )

        self.assertEqual(section.weight, 35.0)
        self.assertEqual(section_command[2]["weight"], 35.0)

    # Generate department evaluation cũng phải snapshot section weight sau khi department template đã roll-up xong.
    def test_department_evaluation_generation_inherits_computed_section_weight(self):
        template = self._create_department_template(
            "Department Evaluation Snapshot Template"
        )
        section = self.DepartmentLine.create(
            self._department_section_vals(template, "Department Section")
        )
        self.DepartmentLine.create(
            self._department_leaf_vals(
                template, "Department Leaf", 22.0, parent=section
            )
        )

        evaluation = self.DepartmentEvaluation.new({"department_id": self.department.id})
        commands = evaluation._prepare_evaluation_line_commands_from_template(template)
        section_command = next(
            command
            for command in commands
            if isinstance(command[2], dict) and command[2].get("is_section")
        )

        self.assertEqual(section.weight, 22.0)
        self.assertEqual(section_command[2]["weight"], 22.0)
