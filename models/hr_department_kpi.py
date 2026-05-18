from odoo import models, fields, api
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

    # ── DEPRECATED: alpha / beta (old dept-score blending mechanism) ──────────
    # Kept in DB for backward compatibility. Hidden from all UI views.
    alpha = fields.Float(
        string="Department KPI Weight (α)",
        default=0.5,
        deprecated=True,
        groups="base.group_no_one",
        help="[DEPRECATED] Replaced by dept_weight. "
        "Weight applied to the department KPI score. α + β must equal 1.0.",
    )
    beta = fields.Float(
        string="Average Individual Weight (β)",
        default=0.5,
        deprecated=True,
        groups="base.group_no_one",
        help="[DEPRECATED] Replaced by dept_weight. "
        "Weight applied to the average employee performance score. α + β must equal 1.0.",
    )
    # ─────────────────────────────────────────────────────────────────────────

    # ── NEW: dept_weight for individual final_score formula ───────────────────
    dept_weight = fields.Float(
        string="Trọng số KPI phòng ban",
        default=0.4,
        help="Tỷ lệ đóng góp của KPI phòng ban vào điểm cuối cùng của nhân viên. "
        "Ví dụ: 0.4 nghĩa là final_score = dept×40% + cá_nhân×60%. "
        "Phải nằm trong khoảng (0.0, 1.0).",
    )

    individual_weight = fields.Float(
        string="Trọng số cá nhân",
        compute="_compute_individual_weight",
    )
    # ─────────────────────────────────────────────────────────────────────────

    kpi_line_ids = fields.One2many("hr.department.kpi.line", "department_kpi_id")

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains("dept_weight")
    def _check_dept_weight(self):
        for rec in self:
            if not (0.0 < rec.dept_weight < 1.0):
                raise ValidationError(
                    "Trọng số KPI phòng ban phải lớn hơn 0 và nhỏ hơn 1."
                )

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends("dept_weight")
    def _compute_individual_weight(self):
        for rec in self:
            rec.individual_weight = 1.0 - rec.dept_weight

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
