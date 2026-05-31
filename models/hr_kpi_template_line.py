from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrKpiTemplateLine(models.Model):
    _name = "hr.kpi.template.line"
    _description = "Employee KPI Template Line"
    _order = "sequence, id"
    _rec_name = "key_performance_area"

    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
    )
    kpi_type = fields.Selection(
        [
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ],
        string="KPI Type",
        default="quantitative",
        required=True,
    )
    target = fields.Float(string="Target", default=0.0)
    target_display = fields.Char(string="Target", compute="_compute_display")
    unit = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="restrict",
    )
    weight = fields.Float(string="Weight", default=10.0)
    kpi_id = fields.Many2one(
        "hr.kpi.template",
        string="KPI Template",
        required=True,
        ondelete="cascade",
    )
    parent_dept_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string="Parent Department KPI Template",
        related="kpi_id.department_kpi_id",
        store=False,
    )
    parent_dept_line_id = fields.Many2one(
        "hr.department.kpi.template.line",
        string="Parent KPI",
        help="Department KPI template line.",
    )
    description = fields.Html(string="Description", sanitize=True)

    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        string="Data Source",
        ondelete="set null",
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        string="Scoring Formula",
        ondelete="restrict",
        help="Field canonical de HR chon cong thuc tinh diem. De trong thi dung fallback legacy.",
    )
    formula_type = fields.Selection(
        [
            ("linear", "Tuyến tính"),
            ("step_table", "Bảng bậc thang"),
            ("lower_zero", "Trừ điểm"),
        ],
        string="Scoring Formula",
        default="linear",
        required=True,
    )
    step_table_json = fields.Text()
    scoring_formula_type = fields.Selection(
        related="scoring_formula_id.formula_type",
        string="Scoring Formula Type",
        store=False,
        readonly=True,
    )
    is_auto = fields.Boolean(
        string="Auto Compute",
        compute="_compute_auto",
        store=True,
    )
    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=False,
    )
    is_section = fields.Boolean(default=False)
    display_type = fields.Selection(
        [
            ("line_section", "Section"),
            ("line_note", "Note"),
        ],
        default=False,
        compute="_compute_display_type",
        store=True,
        readonly=False,
    )
    sequence = fields.Integer(default=10)

    @api.depends("kpi_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(rec.kpi_type == "quantitative" and rec.data_source_id)

    @api.depends("kpi_type", "formula_type", "scoring_formula_id", "scoring_formula_id.formula_type")
    def _compute_is_special_scoring(self):
        for rec in self:
            effective_formula_type = rec.formula_type
            if rec.scoring_formula_id:
                effective_formula_type = rec.scoring_formula_id.formula_type

            rec.is_special_scoring = bool(
                rec.kpi_type == "quantitative" and effective_formula_type != "linear"
            )

    def _get_unit_by_code(self, code):
        return self.env["hr.kpi.unit"].search([("code", "=", code)], limit=1)

    def _is_percent_unit(self):
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    def _get_default_unit(self):
        self.ensure_one()
        code = self.data_source_id.get_unit_id() if self.data_source_id else False
        return self._get_unit_by_code(code) if code else False

    @api.onchange("data_source_id")
    def _onchange_unit(self):
        for rec in self:
            if rec.data_source_id:
                rec.unit = rec._get_default_unit()

    def _build_legacy_step_table_formula(self):
        self.ensure_one()
        return self.env["hr.kpi.scoring.formula"].new(
            {
                "name": "%s (legacy)" % (self.key_performance_area or "Legacy Step Table"),
                "formula_type": "step_table",
                "step_table_json": self.step_table_json or "[]",
                "step_out_of_range": "zero",
            }
        )

    def get_effective_formula(self):
        self.ensure_one()
        if self.scoring_formula_id:
            return self.scoring_formula_id

        xml_id = False

        if self.formula_type == "linear":
            xml_id = "custom_adecsol_hr_performance_evaluator.formula_linear_higher"
        elif self.formula_type == "lower_zero":
            xml_id = "custom_adecsol_hr_performance_evaluator.formula_penalty_1pt"
        elif self.formula_type == "step_table" and self.step_table_json:
            return self._build_legacy_step_table_formula()

        if xml_id:
            formula = self.env.ref(xml_id, raise_if_not_found=False)
            if formula:
                return formula
        return False

    @api.depends("target", "kpi_type", "unit", "unit.code", "unit.name")
    def _compute_display(self):
        for rec in self:
            if rec.display_type or rec.is_section or rec.kpi_type != "quantitative":
                rec.target_display = ""
                continue
            if rec._is_percent_unit():
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                unit_name = rec.unit.name if rec.unit else ""
                rec.target_display = f"{target} {unit_name}" if unit_name else target

    @api.depends("is_section")
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = "line_section" if rec.is_section else False

    @api.constrains("kpi_type", "target")
    def _check_numeric_target(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                continue
            if rec.kpi_type == "quantitative" and (rec.target or 0.0) < 0.0:
                raise ValidationError(
                    _(
                        "For Quantitative KPI type, Target must be greater than or equal 0."
                    )
                )

    @api.constrains("parent_dept_line_id", "kpi_id", "is_section")
    def _check_parent_dept_line(self):
        self._validate_parent_dept_line_consistency()

    def _validate_parent_dept_line_consistency(self, parent_kpi=None):
        for rec in self:
            parent_line = rec.parent_dept_line_id
            if not parent_line:
                continue
            if rec.is_section:
                raise ValidationError(
                    _("Section lines cannot be linked to department KPI lines.")
                )
            if parent_line.is_section:
                raise ValidationError(
                    _("Please select a KPI item, not a department section.")
                )

            parent_dept_kpi = parent_kpi or rec.kpi_id.department_kpi_id
            if not parent_dept_kpi:
                raise ValidationError(
                    _(
                        "Please select a parent Department KPI Template before linking department KPI lines."
                    )
                )
            if parent_line.department_kpi_id != parent_dept_kpi:
                raise ValidationError(
                    _(
                        "The selected department KPI line must belong to the parent Department KPI Template."
                    )
                )

    def write(self, vals):
        if vals.get("display_type") and "is_section" not in vals:
            vals = dict(vals, is_section=True)
        return super().write(vals)

    def action_open_popup(self):
        self.ensure_one()
        return {
            "name": _("Edit KPI Line"),
            "type": "ir.actions.act_window",
            "res_model": "hr.kpi.template.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_kpi_line_form_popup"
            ).id,
            "target": "new",
        }
