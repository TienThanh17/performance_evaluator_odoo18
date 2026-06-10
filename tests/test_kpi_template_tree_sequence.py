from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestEmployeeKpiTemplateTreeSequence(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Employee = self.env["hr.employee"]
        self.Evaluation = self.env["hr.performance.evaluation"]
        self.KpiTemplate = self.env["hr.kpi.template"]
        self.KpiLine = self.env["hr.kpi.template.line"]
        self.Pillar = self.env["hr.evaluation.pillar"]

        self.employee = self.Employee.create({"name": "Template Order Employee"})
        self.p2_1 = self._get_pillar("p2_1", "P2.1")
        self.p2_2 = self._get_pillar("p2_2", "P2.2")

    # Lấy pillar theo code để test dùng đúng scope hierarchy của template screen.
    def _get_pillar(self, code, default_name):
        pillar = self.Pillar.search([("code", "=", code)], limit=1)
        if not pillar:
            pillar = self.Pillar.create({"name": default_name, "code": code})
        return pillar

    # Tạo employee KPI template tối thiểu để các line tests tập trung vào hierarchy order.
    def _create_template(self, name="Employee Template"):
        return self.KpiTemplate.create({"name": name, "period_type": "monthly"})

    # Tạo một employee KPI line manual để tránh side effects của auto formula trong test tree order.
    def _employee_line_vals(self, template, title, pillar, weight, parent=False):
        return {
            "kpi_id": template.id,
            "key_performance_area": title,
            "pillar_id": pillar.id,
            "kpi_type": "manual",
            "manual_scoring_type": "score",
            "weight": weight,
            "parent_line_id": parent.id if parent else False,
        }

    # Đọc thứ tự hiển thị cuối cùng bằng flat sequence đã được normalize.
    def _ordered_titles(self, template):
        return template.kpi_line_ids.sorted(
            lambda line: (line.sequence or 0, line.id or 0)
        ).mapped("key_performance_area")

    # Đọc title từ command list để verify phần generate evaluation giữ nguyên preorder.
    def _command_titles(self, commands):
        return [command[2]["key_performance_area"] for command in commands[1:]]

    # Line con mới phải chèn sau toàn bộ block hậu duệ hiện có của parent.
    def test_employee_child_create_appends_after_parent_subtree(self):
        template = self._create_template()
        root = self.KpiLine.create(
            self._employee_line_vals(template, "Root", self.p2_1, 100.0)
        )
        child_a, sub_parent = self.KpiLine.create(
            [
                self._employee_line_vals(
                    template, "Child A", self.p2_1, 60.0, parent=root
                ),
                self._employee_line_vals(
                    template, "Sub Parent", self.p2_1, 40.0, parent=root
                ),
            ]
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "Grandchild", self.p2_1, 40.0, parent=sub_parent
            )
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "New Child", self.p2_1, 0.0, parent=root
            )
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root", "Child A", "Sub Parent", "Grandchild", "New Child"],
        )

    # Child đầu tiên của section phải chèn ngay sau parent thay vì rơi xuống cuối scope.
    def test_employee_first_child_create_stays_inside_empty_parent_block(self):
        template = self._create_template()
        root, trailing_root = self.KpiLine.create(
            [
                self._employee_line_vals(template, "Root", self.p2_1, 100.0),
                self._employee_line_vals(template, "Trailing Root", self.p2_1, 0.0),
            ]
        )

        self.KpiLine.create(
            self._employee_line_vals(
                template, "First Child", self.p2_1, 100.0, parent=root
            )
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root", "First Child", "Trailing Root"],
        )

    # Grandchild mới phải nằm ở cuối subtree của sub-parent thay vì bật ra scope khác.
    def test_employee_grandchild_create_appends_after_sub_parent_descendant_block(self):
        template = self._create_template()
        root = self.KpiLine.create(
            self._employee_line_vals(template, "Root", self.p2_1, 100.0)
        )
        sub_parent = self.KpiLine.create(
            self._employee_line_vals(template, "Sub Parent", self.p2_1, 100.0, parent=root)
        )
        self.KpiLine.create(
            [
                self._employee_line_vals(
                    template, "Grandchild A", self.p2_1, 60.0, parent=sub_parent
                ),
                self._employee_line_vals(
                    template, "Grandchild B", self.p2_1, 40.0, parent=sub_parent
                ),
            ]
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "Grandchild C", self.p2_1, 0.0, parent=sub_parent
            )
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root", "Sub Parent", "Grandchild A", "Grandchild B", "Grandchild C"],
        )

    # Reparent leaf phải tự động dời leaf tới cuối block của parent mới.
    def test_employee_reparent_leaf_moves_to_new_parent_end(self):
        template = self._create_template()
        root_a, root_b = self.KpiLine.create(
            [
                self._employee_line_vals(template, "Root A", self.p2_1, 100.0),
                self._employee_line_vals(template, "Root B", self.p2_1, 0.0),
            ]
        )
        child_main, leaf_to_move = self.KpiLine.create(
            [
                self._employee_line_vals(
                    template, "Child Main", self.p2_1, 100.0, parent=root_a
                ),
                self._employee_line_vals(
                    template, "Leaf To Move", self.p2_1, 0.0, parent=root_a
                ),
            ]
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "Root B Child", self.p2_1, 0.0, parent=root_b
            )
        )

        leaf_to_move.write({"parent_line_id": root_b.id})

        self.assertEqual(
            self._ordered_titles(template),
            ["Root A", "Child Main", "Root B", "Root B Child", "Leaf To Move"],
        )

    # Reparent subtree root phải kéo theo toàn bộ descendants của nó như một block.
    def test_employee_reparent_subtree_moves_whole_block(self):
        template = self._create_template()
        root_a, root_b = self.KpiLine.create(
            [
                self._employee_line_vals(template, "Root A", self.p2_1, 100.0),
                self._employee_line_vals(template, "Root B", self.p2_1, 0.0),
            ]
        )
        child_main, subtree_root = self.KpiLine.create(
            [
                self._employee_line_vals(
                    template, "Child Main", self.p2_1, 100.0, parent=root_a
                ),
                self._employee_line_vals(
                    template, "Subtree Root", self.p2_1, 0.0, parent=root_a
                ),
            ]
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "Grandchild", self.p2_1, 0.0, parent=subtree_root
            )
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "Root B Child", self.p2_1, 0.0, parent=root_b
            )
        )

        subtree_root.write({"parent_line_id": root_b.id})

        self.assertEqual(
            self._ordered_titles(template),
            ["Root A", "Child Main", "Root B", "Root B Child", "Subtree Root", "Grandchild"],
        )
        self.assertEqual(child_main.parent_line_id, root_a)

    # Cấm deep cycle để user không thể đưa ancestor xuống dưới chính hậu duệ của nó.
    def test_employee_recursive_parenting_rejected_deeply(self):
        template = self._create_template()
        root = self.KpiLine.create(
            self._employee_line_vals(template, "Root", self.p2_1, 100.0)
        )
        child = self.KpiLine.create(
            self._employee_line_vals(template, "Child", self.p2_1, 100.0, parent=root)
        )
        grandchild = self.KpiLine.create(
            self._employee_line_vals(
                template, "Grandchild", self.p2_1, 100.0, parent=child
            )
        )

        with self.assertRaises(ValidationError):
            root.write({"parent_line_id": grandchild.id})

    # Parent và child phải cùng pillar để tránh cây bị bắc cầu qua tab khác.
    def test_employee_cross_pillar_parenting_rejected(self):
        template = self._create_template()
        root_p2_1 = self.KpiLine.create(
            self._employee_line_vals(template, "P2.1 Root", self.p2_1, 100.0)
        )
        root_p2_2 = self.KpiLine.create(
            self._employee_line_vals(template, "P2.2 Root", self.p2_2, 100.0)
        )

        with self.assertRaises(ValidationError):
            root_p2_2.write({"parent_line_id": root_p2_1.id})

    # Generate evaluation phải copy template theo preorder mới, không dùng raw sequence cũ.
    def test_employee_template_generation_preserves_preorder(self):
        template = self._create_template()
        root = self.KpiLine.create(
            self._employee_line_vals(template, "P2.1 Root", self.p2_1, 100.0)
        )
        _, sub_parent = self.KpiLine.create(
            [
                self._employee_line_vals(
                    template, "P2.1 Child", self.p2_1, 60.0, parent=root
                ),
                self._employee_line_vals(
                    template, "P2.1 Sub Parent", self.p2_1, 40.0, parent=root
                ),
            ]
        )
        self.KpiLine.create(
            self._employee_line_vals(
                template, "P2.1 Grandchild", self.p2_1, 40.0, parent=sub_parent
            )
        )
        self.KpiLine.create(
            self._employee_line_vals(template, "P2.2 Root", self.p2_2, 100.0)
        )

        evaluation = self.Evaluation.new({"employee_id": self.employee.id})
        commands = evaluation._prepare_evaluation_line_commands_from_template(template)

        self.assertEqual(
            self._command_titles(commands),
            [
                "P2.1 Root",
                "P2.1 Child",
                "P2.1 Sub Parent",
                "P2.1 Grandchild",
                "P2.2 Root",
            ],
        )


class TestDepartmentKpiTemplateTreeSequence(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Department = self.env["hr.department"]
        self.DepartmentEvaluation = self.env["hr.department.performance.evaluation"]
        self.DepartmentTemplate = self.env["hr.department.kpi.template"]
        self.DepartmentLine = self.env["hr.department.kpi.template.line"]
        self.Pillar = self.env["hr.evaluation.pillar"]

        self.department = self.Department.create({"name": "Template Order Department"})
        self.p3_department = self._get_pillar("p3_department", "P3 Department")

    # Lấy pillar theo code để test dùng đúng scope hierarchy của department template screen.
    def _get_pillar(self, code, default_name):
        pillar = self.Pillar.search([("code", "=", code)], limit=1)
        if not pillar:
            pillar = self.Pillar.create({"name": default_name, "code": code})
        return pillar

    # Tạo department KPI template tối thiểu để các line tests tập trung vào hierarchy order.
    def _create_template(self, name="Department Template"):
        return self.DepartmentTemplate.create(
            {
                "name": name,
                "department_id": self.department.id,
                "period_type": "monthly",
            }
        )

    # Tạo một department KPI line manual để tránh side effects của auto formula trong test tree order.
    def _department_line_vals(self, template, title, weight, parent=False):
        return {
            "department_kpi_id": template.id,
            "name": title,
            "pillar_id": self.p3_department.id,
            "kpi_type": "manual",
            "manual_scoring_type": "score",
            "weight": weight,
            "parent_line_id": parent.id if parent else False,
        }

    # Đọc thứ tự hiển thị cuối cùng bằng flat sequence đã được normalize.
    def _ordered_titles(self, template):
        return template.kpi_line_ids.sorted(
            lambda line: (line.sequence or 0, line.id or 0)
        ).mapped("name")

    # Đọc title từ command list để verify phần generate evaluation giữ nguyên preorder.
    def _command_titles(self, commands):
        return [command[2]["name"] for command in commands[1:]]

    # Root mới phải chèn sau subtree cuối cùng của các root hiện có.
    def test_department_root_create_appends_after_last_root_subtree(self):
        template = self._create_template()
        root_a, root_b = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Root A", 100.0),
                self._department_line_vals(template, "Root B", 0.0),
            ]
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Child A", 100.0, parent=root_a)
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Root C", 0.0)
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root A", "Child A", "Root B", "Root C"],
        )

    # Line con mới phải chèn sau toàn bộ block hậu duệ hiện có của parent.
    def test_department_child_create_appends_after_parent_subtree(self):
        template = self._create_template()
        root = self.DepartmentLine.create(
            self._department_line_vals(template, "Root", 100.0)
        )
        _, sub_parent = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Child A", 60.0, parent=root),
                self._department_line_vals(template, "Sub Parent", 40.0, parent=root),
            ]
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Grandchild", 40.0, parent=sub_parent)
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "New Child", 0.0, parent=root)
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root", "Child A", "Sub Parent", "Grandchild", "New Child"],
        )

    # Child đầu tiên của section phải chèn ngay sau parent thay vì rơi xuống cuối scope.
    def test_department_first_child_create_stays_inside_empty_parent_block(self):
        template = self._create_template()
        root, trailing_root = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Root", 100.0),
                self._department_line_vals(template, "Trailing Root", 0.0),
            ]
        )

        self.DepartmentLine.create(
            self._department_line_vals(template, "First Child", 100.0, parent=root)
        )

        self.assertEqual(
            self._ordered_titles(template),
            ["Root", "First Child", "Trailing Root"],
        )

    # Reparent subtree root phải kéo theo toàn bộ descendants của nó như một block.
    def test_department_reparent_subtree_moves_whole_block(self):
        template = self._create_template()
        root_a, root_b = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Root A", 100.0),
                self._department_line_vals(template, "Root B", 0.0),
            ]
        )
        _, subtree_root = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Child Main", 100.0, parent=root_a),
                self._department_line_vals(template, "Subtree Root", 0.0, parent=root_a),
            ]
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Grandchild", 0.0, parent=subtree_root)
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Root B Child", 0.0, parent=root_b)
        )

        subtree_root.write({"parent_line_id": root_b.id})

        self.assertEqual(
            self._ordered_titles(template),
            ["Root A", "Child Main", "Root B", "Root B Child", "Subtree Root", "Grandchild"],
        )

    # Cấm deep cycle để user không thể đưa ancestor xuống dưới chính hậu duệ của nó.
    def test_department_recursive_parenting_rejected_deeply(self):
        template = self._create_template()
        root = self.DepartmentLine.create(
            self._department_line_vals(template, "Root", 100.0)
        )
        child = self.DepartmentLine.create(
            self._department_line_vals(template, "Child", 100.0, parent=root)
        )
        grandchild = self.DepartmentLine.create(
            self._department_line_vals(template, "Grandchild", 100.0, parent=child)
        )

        with self.assertRaises(ValidationError):
            root.write({"parent_line_id": grandchild.id})

    # Generate department evaluation phải copy template theo preorder mới.
    def test_department_template_generation_preserves_preorder(self):
        template = self._create_template()
        root = self.DepartmentLine.create(
            self._department_line_vals(template, "Root", 100.0)
        )
        _, sub_parent = self.DepartmentLine.create(
            [
                self._department_line_vals(template, "Child A", 60.0, parent=root),
                self._department_line_vals(template, "Sub Parent", 40.0, parent=root),
            ]
        )
        self.DepartmentLine.create(
            self._department_line_vals(template, "Grandchild", 40.0, parent=sub_parent)
        )

        evaluation = self.DepartmentEvaluation.new({"department_id": self.department.id})
        commands = evaluation._prepare_evaluation_line_commands_from_template(template)

        self.assertEqual(
            self._command_titles(commands),
            ["Root", "Child A", "Sub Parent", "Grandchild"],
        )
