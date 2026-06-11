from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestKpiTemplateUiTour(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KpiTemplate = cls.env["hr.kpi.template"]
        cls.KpiLine = cls.env["hr.kpi.template.line"]
        cls.DepartmentKpiTemplate = cls.env["hr.department.kpi.template"]
        cls.DepartmentKpiLine = cls.env["hr.department.kpi.template.line"]
        cls.Pillar = cls.env["hr.evaluation.pillar"]
        cls.ScoringFormula = cls.env["hr.kpi.scoring.formula"]

        cls.p3_individual = cls.Pillar.search(
            [("code", "=", "p3_individual")],
            limit=1,
        )
        if not cls.p3_individual:
            cls.p3_individual = cls.Pillar.create(
                {
                    "name": "P3 Individual",
                    "code": "p3_individual",
                }
            )
        cls.p3_department = cls.Pillar.search(
            [("code", "=", "p3_department")],
            limit=1,
        )
        if not cls.p3_department:
            cls.p3_department = cls.Pillar.create(
                {
                    "name": "P3 Department",
                    "code": "p3_department",
                }
            )

        cls.ui_formula = cls.ScoringFormula.create(
            {
                "name": "UI Regression Formula",
                "formula_type": "linear",
                "linear_direction": "higher_better",
                "linear_allow_exceed": False,
            }
        )
        cls.ui_department_formula = cls.ScoringFormula.create(
            {
                "name": "UI Department Regression Formula",
                "formula_type": "linear",
                "linear_direction": "higher_better",
                "linear_allow_exceed": False,
            }
        )

        cls.template = cls.KpiTemplate.create(
            {
                "name": "UI Pending Delete Regression Template",
                "period_type": "monthly",
            }
        )

        root_lines = cls.KpiLine.create(
            [
                {
                    "kpi_id": cls.template.id,
                    "key_performance_area": "TC1 - An Toàn",
                    "pillar_id": cls.p3_individual.id,
                    "is_section": True,
                    "weight": 10.0,
                    "sequence": 10,
                },
                {
                    "kpi_id": cls.template.id,
                    "key_performance_area": "Other Root",
                    "pillar_id": cls.p3_individual.id,
                    "kpi_type": "manual",
                    "manual_scoring_type": "score",
                    "weight": 90.0,
                    "sequence": 30,
                },
            ]
        )
        cls.section_line = root_lines.filtered(
            lambda line: line.key_performance_area == "TC1 - An Toàn"
        )
        cls.KpiLine.create(
            {
                "kpi_id": cls.template.id,
                "key_performance_area": "Old Child",
                "pillar_id": cls.p3_individual.id,
                "parent_line_id": cls.section_line.id,
                "kpi_type": "manual",
                "manual_scoring_type": "score",
                "weight": 10.0,
                "sequence": 20,
            }
        )

        cls.action = cls.env.ref(
            "custom_adecsol_hr_performance_evaluator.hr_kpi_action"
        )
        cls.department_template = cls.DepartmentKpiTemplate.create(
            {
                "name": "UI Department Pending Sync Regression Template",
                "period_type": "monthly",
            }
        )
        department_root_lines = cls.DepartmentKpiLine.create(
            [
                {
                    "department_kpi_id": cls.department_template.id,
                    "name": "TC1 - An Toàn",
                    "pillar_id": cls.p3_department.id,
                    "is_section": True,
                    "weight": 10.0,
                    "sequence": 10,
                },
                {
                    "department_kpi_id": cls.department_template.id,
                    "name": "Other Department Root",
                    "pillar_id": cls.p3_department.id,
                    "is_section": True,
                    "weight": 90.0,
                    "sequence": 100,
                },
            ]
        )
        cls.department_section_line = department_root_lines.filtered(
            lambda line: line.name == "TC1 - An Toàn"
        )
        cls.DepartmentKpiLine.create(
            [
                {
                    "department_kpi_id": cls.department_template.id,
                    "name": f"Dept Old Child {index}",
                    "pillar_id": cls.p3_department.id,
                    "parent_line_id": cls.department_section_line.id,
                    "kpi_type": "auto",
                    "scoring_formula_id": cls.ui_department_formula.id,
                    "weight": 2.0,
                    "sequence": 10 + (index * 10),
                }
                for index in range(1, 6)
            ]
        )
        cls.department_action = cls.env.ref(
            "custom_adecsol_hr_performance_evaluator.action_hr_department_kpi"
        )

    # Bảo vệ luồng popup create của KPI cá nhân khỏi việc còn tính child line đã xóa cục bộ.
    def test_pending_deleted_child_not_counted_when_popup_creates_new_child(self):
        url = (
            f"/odoo#action={self.action.id}"
            f"&id={self.template.id}"
            "&model=hr.kpi.template"
            "&view_type=form"
        )
        self.start_tour(
            url,
            "kpi_template_pending_delete_regression",
            login="admin",
        )

    # Bảo vệ luồng popup create của KPI phòng ban khỏi snapshot one2many cũ chưa được ghi xuống server.
    def test_department_popup_create_uses_latest_local_child_state(self):
        url = (
            f"/odoo#action={self.department_action.id}"
            f"&id={self.department_template.id}"
            "&model=hr.department.kpi.template"
            "&view_type=form"
        )
        self.start_tour(
            url,
            "department_kpi_template_popup_sync_regression",
            login="admin",
        )
