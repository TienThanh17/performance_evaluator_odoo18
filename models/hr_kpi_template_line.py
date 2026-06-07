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
    pillar_id = fields.Many2one(
        "hr.evaluation.pillar",
        string="Pillar",
        ondelete="restrict",
    )
    pillar_code = fields.Char(
        related="pillar_id.code",
        string="Pillar Code",
        store=True,
        readonly=True,
    )
    category_id = fields.Many2one(
        "hr.evaluation.category",
        string="Category",
        ondelete="restrict",
    )
    parent_line_id = fields.Many2one(
        "hr.kpi.template.line",
        string="Parent Line",
        ondelete="set null",
        index=True,
    )
    child_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "parent_line_id",
        string="Child Lines",
    )
    score_scale_base_override = fields.Float(
        string="Score Scale Base Override",
        help="Optional native score scale for this line, for example 100, 10, or 5. Leave empty to use the global KPI score scale.",
    )
    score_max_display = fields.Char(
        string="Max Score",
        compute="_compute_score_max_display",
        store=False,
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
        help="Công thức tính điểm được áp dụng cho KPI này.",
    )
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

    # Resolve the pillar configured by the current tab context.
    def _get_default_pillar_from_context(self):
        pillar_code = (self.env.context.get("default_pillar_code") or "").strip().lower()
        if not pillar_code:
            return self.env["hr.evaluation.pillar"]
        return self.env["hr.evaluation.pillar"].search(
            [("code", "=", pillar_code)],
            limit=1,
        )

    # Prefill pillar_id so popup and inline creation inherit the tab pillar.
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if defaults.get("pillar_id"):
            return defaults

        default_pillar = self._get_default_pillar_from_context()
        if default_pillar:
            defaults["pillar_id"] = default_pillar.id
        return defaults

    @api.depends("kpi_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(rec.kpi_type == "quantitative" and rec.data_source_id)

    # Compute the score scale hint shown next to score-based KPI inputs.
    @api.depends("kpi_type", "score_scale_base_override")
    def _compute_score_max_display(self):
        for rec in self:
            if rec.kpi_type == "score" and rec.score_scale_base_override > 0:
                rec.score_max_display = f"/ {rec.score_scale_base_override:g} pts"
            else:
                rec.score_max_display = ""

    @api.depends("kpi_type", "scoring_formula_id", "scoring_formula_id.formula_type")
    def _compute_is_special_scoring(self):
        for rec in self:
            effective_formula_type = rec.scoring_formula_id.formula_type if rec.scoring_formula_id else False
            rec.is_special_scoring = bool(
                rec.kpi_type == "quantitative" and effective_formula_type and effective_formula_type != "linear"
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

    def get_effective_formula(self):
        self.ensure_one()
        return self.scoring_formula_id or False

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

    @api.constrains("category_id", "pillar_id")
    def _check_category_pillar(self):
        for rec in self:
            if rec.category_id and rec.pillar_id and rec.category_id.pillar_id != rec.pillar_id:
                raise ValidationError(
                    _("The selected category must belong to the selected pillar.")
                )

    @api.constrains("parent_line_id", "kpi_id")
    def _check_parent_line(self):
        for rec in self:
            parent = rec.parent_line_id
            if not parent:
                continue
            if parent == rec:
                raise ValidationError(_("A KPI line cannot be its own parent."))
            if parent.kpi_id != rec.kpi_id:
                raise ValidationError(
                    _("The parent KPI line must belong to the same KPI template.")
                )
            if parent.is_section:
                raise ValidationError(
                    _("A section line cannot be selected as a parent KPI line.")
                )
            if parent.parent_line_id == rec:
                raise ValidationError(
                    _("Recursive KPI line hierarchy is not allowed.")
                )

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

    # Enforce the tab pillar on create as a backend fallback when UI defaults are missing.
    @api.model_create_multi
    def create(self, vals_list):
        default_pillar = self._get_default_pillar_from_context()
        for vals in vals_list:
            if vals.get("display_type") and "is_section" not in vals:
                vals["is_section"] = True
            if default_pillar and not vals.get("pillar_id"):
                vals["pillar_id"] = default_pillar.id
        return super().create(vals_list)

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
