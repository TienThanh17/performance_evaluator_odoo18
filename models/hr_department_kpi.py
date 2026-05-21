from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrDepartmentKpi(models.Model):
    _name = "hr.department.kpi"
    _description = "Department KPI Template"

    name = fields.Char(required=True)
    department_id = fields.Many2one("hr.department", ondelete="cascade")
    period = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("biannual", "Biannual"),
            ("annual", "Annual"),
        ],
        required=True,
    )

    # ── NEW: dept_weight for individual final_score formula ───────────────────
    dept_weight = fields.Float(
        string=_("Department Bonus Weight"),
        default=0.4,
        help="The contribution rate of the department's KPI to the employee's final score. "
        "Example: 0.4 means final_score = dept×40% + individual×60%. "
        "Must be in the range (0%, 100%).",
        required=True,
    )

    individual_weight = fields.Float(
        string=_("Individual Bonus Weight"),
        default=0.6,
        help="The contribution rate of the individual's KPI to the final score. "
        "Example: 0.6 means final_score = dept×40% + individual×60%. "
        "Must be in the range (0%, 100%).",
        required=True,
    )

    kpi_line_ids = fields.One2many("hr.department.kpi.line", "department_kpi_id")

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains("dept_weight", "individual_weight")
    def _check_weights(self):
        for rec in self:
            if not (0.0 < rec.dept_weight < 1.0):
                raise ValidationError(
                    _(
                        "Department Bonus Weight must be greater than 0% and less than 100%."
                    )
                )
            if not (0.0 < rec.individual_weight < 1.0):
                raise ValidationError(
                    _(
                        "Individual Bonus Weight must be greater than 0% and less than 100%."
                    )
                )
            if abs(rec.dept_weight + rec.individual_weight - 1.0) > 0.0001:
                raise ValidationError(
                    _(
                        "The sum of Department Bonus Weight and Individual Bonus Weight must be exactly 100%."
                    )
                )

    # ── Onchanges ─────────────────────────────────────────────────────────────
    @api.onchange("dept_weight")
    def _onchange_dept_weight(self):
        for rec in self:
            rec.individual_weight = 1.0 - rec.dept_weight

    @api.onchange("individual_weight")
    def _onchange_individual_weight(self):
        for rec in self:
            rec.dept_weight = 1.0 - rec.individual_weight

    # ── Copy ──────────────────────────────────────────────────────────────────
    def copy(self, default=None):
        # 1. Initialize default dictionary
        default = default or {}

        # 2. Add specific fields to update during copy
        default["name"] = self.name + " (Copy)"

        # 3. Call super to create the new parent record
        new_parent = super(HrDepartmentKpi, self).copy(default)

        # 4. Iterate over original lines and copy them
        for line in self.kpi_line_ids:
            line.copy({"department_kpi_id": new_parent.id})

        return new_parent
