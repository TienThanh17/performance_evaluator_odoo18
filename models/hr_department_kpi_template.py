from odoo import fields, models


class HrDepartmentKpiTemplate(models.Model):
    _name = "hr.department.kpi.template"
    _description = "Department KPI Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    department_id = fields.Many2one("hr.department", ondelete="cascade")
    period_type = fields.Selection(
        [
            ("monthly", "Hàng tháng"),
            ("quarterly", "Hàng quý"),
            ("biannual", "Nửa năm"),
            ("yearly", "Hàng năm"),
        ],
        string="Tần suất đánh giá",
        required=True,
        default="monthly",
        tracking=True,
        help="Quy định tần suất sử dụng bản mẫu này."
    )
    scoring_profile_id = fields.Many2one(
        "hr.kpi.scoring.profile",
        string="Scoring Profile",
        ondelete="set null",
    )
    kpi_line_ids = fields.One2many(
        "hr.department.kpi.template.line", "department_kpi_id"
    )

    # Khai báo các field chứa tên động của từng Pillar
    pillar_p3_dept_name = fields.Char(compute="_compute_dynamic_pillar_names", string="Tên Pillar P3")

    def _compute_dynamic_pillar_names(self):
        pillars = self.env['hr.evaluation.pillar'].sudo().search([
            ('code', 'in', ['p3_department'])
        ])
        self.pillar_p3_dept_name = pillars.name or "P3.1.2 KPI Phòng Ban"

    # Trả về department KPI lines theo flat preorder để các màn generate giữ đúng cây template.
    def get_hierarchy_ordered_lines(self):
        self.ensure_one()
        if not self.kpi_line_ids:
            return self.env["hr.department.kpi.template.line"]

        # Tái sử dụng helper ở line model để giữ nguyên thứ tự root, child và grandchild.
        return self.kpi_line_ids[:1]._get_hierarchy_ordered_lines(
            scope_lines=self.kpi_line_ids
        )

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"department_kpi_id": new_parent.id})
        return new_parent
