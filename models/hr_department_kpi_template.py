from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    dept_weight = fields.Float(
        string=_("Department Bonus Weight"),
        default=0.4,
        required=True,
    )
    individual_weight = fields.Float(
        string=_("Individual Bonus Weight"),
        default=0.6,
        required=True,
    )
    kpi_line_ids = fields.One2many(
        "hr.department.kpi.template.line", "department_kpi_id"
    )

    @api.constrains("dept_weight", "individual_weight")
    def _check_weights(self):
        for rec in self:
            if not (0.0 < rec.dept_weight < 1.0):
                raise ValidationError(
                    _(
                        "Department Bonus Weight must be greater than 0%% and less than 100%%."
                    )
                )
            if not (0.0 < rec.individual_weight < 1.0):
                raise ValidationError(
                    _(
                        "Individual Bonus Weight must be greater than 0%% and less than 100%%."
                    )
                )
            if abs(rec.dept_weight + rec.individual_weight - 1.0) > 0.0001:
                raise ValidationError(
                    _(
                        "The sum of Department Bonus Weight and Individual Bonus Weight must be exactly 100%%."
                    )
                )

    @api.onchange("dept_weight")
    def _onchange_dept_weight(self):
        for rec in self:
            rec.individual_weight = 1.0 - rec.dept_weight

    @api.onchange("individual_weight")
    def _onchange_individual_weight(self):
        for rec in self:
            rec.dept_weight = 1.0 - rec.individual_weight

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"department_kpi_id": new_parent.id})
        return new_parent
