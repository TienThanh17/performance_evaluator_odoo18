from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrKpiTemplate(models.Model):
    _name = "hr.kpi.template"
    _description = "Employee KPI Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string=_("Name"), required=True, tracking=True)
    kpi_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        help="The KPI lines included in this KPI template.",
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        help="Apply this KPI template to employees in the selected job position.",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        help="Apply this KPI template to employees in the selected department.",
    )
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
    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string=_("Parent Department KPI Template"),
        domain="[('department_id', '=', department_id), ('period_type', '=', period_type)]",
        ondelete="set null",
    )

    # @api.constrains("kpi_line_ids")
    # def _check_total_weight(self):
    #     for kpi in self:
    #         valid_lines = kpi.kpi_line_ids.filtered(lambda l: not l.is_section)
    #         total_weight = sum(valid_lines.mapped("weight"))
    #         if valid_lines and abs(total_weight - 100.0) > 0.1:
    #             raise ValidationError(
    #                 _(
    #                     "The total weight of all KPI lines must equal exactly 100. The current total is %s."
    #                 )
    #                 % round(total_weight, 2)
    #             )

    @api.constrains("department_kpi_id", "kpi_line_ids")
    def _check_kpi_line_parent_dept_lines(self):
        for kpi in self:
            kpi.kpi_line_ids._validate_parent_dept_line_consistency(
                parent_kpi=kpi.department_kpi_id
            )

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"kpi_id": new_parent.id})
        return new_parent
