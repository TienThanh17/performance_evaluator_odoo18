import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrDepartmentKpiTemplateLine(models.Model):
    _name = "hr.department.kpi.template.line"
    _description = "Department KPI Template Line"

    name = fields.Char(string="Tên Tiêu Chí", required=True)
    kpi_type = fields.Selection(
        [
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ],
        required=True,
        default="quantitative",
    )
    description = fields.Html(string="Description", sanitize=True)
    target = fields.Float(default=0.0)
    weight = fields.Float(default=1.0)
    is_auto = fields.Boolean(
        compute="_compute_auto",
        store=True,
    )
    target_display = fields.Char(string="Target", compute="_compute_display")
    unit = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="restrict",
    )
    dept_source_type = fields.Selection(
        [
            ("manual", "Nhập thủ công"),
            ("child_kpi_average", "Tự động tổng hợp từ KPI con"),
            ("data_source", "Nguồn dữ liệu tự động"),
        ],
        string="Department Source Type",
        default="manual",
        required=True,
    )
    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        string="Data Source",
        ondelete="set null",
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        string="Scoring Formula",
        ondelete="restrict",
        help="Công thức chấm điểm dùng để tính điểm cho KPI định lượng.",
    )
    is_section = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template", ondelete="cascade"
    )
    child_template_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "parent_dept_line_id",
        string="Child KPI Template Lines",
        readonly=True,
    )
    child_template_line_count = fields.Integer(
        string="Child KPI Template Count",
        compute="_compute_child_template_line_trace",
    )
    child_template_rows_json = fields.Text(
        string="Child KPI Template Rows JSON",
        compute="_compute_child_template_line_trace",
    )

    @api.depends(
        "child_template_line_ids",
        "child_template_line_ids.kpi_id",
        "child_template_line_ids.kpi_id.name",
        "child_template_line_ids.kpi_id.job_id",
        "child_template_line_ids.kpi_id.job_id.name",
        "child_template_line_ids.key_performance_area",
        "child_template_line_ids.weight",
        "child_template_line_ids.target",
        "child_template_line_ids.unit",
        "child_template_line_ids.unit.code",
        "child_template_line_ids.unit.name",
        "child_template_line_ids.is_section",
    )
    def _compute_child_template_line_trace(self):
        for line in self:
            child_lines = line.child_template_line_ids.filtered(
                lambda child: not child.is_section
            ).sorted(
                key=lambda child: (
                    child.kpi_id.name or "",
                    child.sequence or 0,
                    child.key_performance_area or "",
                    child.id or 0,
                )
            )
            line.child_template_line_count = len(child_lines)
            if not child_lines:
                line.child_template_rows_json = "[]"
                continue

            child_rows = []
            for child_line in child_lines:
                kpi_template = child_line.kpi_id
                job = kpi_template.job_id
                child_rows.append(
                    {
                        "kpi_template_id": kpi_template.id or False,
                        "kpi_template": kpi_template.name or "",
                        "job_name": job.name or "",
                        "child_kpi_id": child_line.id or False,
                        "child_kpi": child_line.key_performance_area or "",
                        "weight": child_line.weight or 0.0,
                        "target_display": child_line.target_display or "",
                    }
                )
            line.child_template_rows_json = json.dumps(child_rows, ensure_ascii=False)

    @api.constrains("kpi_type", "target")
    def _check_numeric_target(self):
        for rec in self:
            if rec.is_section:
                continue
            if rec.kpi_type == "quantitative" and (rec.target or 0.0) < 0.0:
                raise ValidationError(
                    _("For Quantitative KPI type, Target must be greater than or equal 0.")
                )

    @api.constrains("is_section", "kpi_type", "scoring_formula_id")
    def _check_scoring_formula(self):
        for rec in self:
            if rec.is_section:
                continue
            if rec.kpi_type == "quantitative" and not rec.scoring_formula_id:
                raise ValidationError(
                    _("Please select a scoring formula for quantitative department KPIs.")
                )

    def _get_unit_by_code(self, code):
        return self.env["hr.kpi.unit"].search([("code", "=", code)], limit=1)

    def _is_percent_unit(self):
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    def _get_default_unit(self):
        self.ensure_one()
        if self.dept_source_type == "child_kpi_average":
            code = "score"
        elif self.dept_source_type == "data_source" and self.data_source_id:
            code = self.data_source_id.get_unit_id()
        else:
            code = False
        return self._get_unit_by_code(code) if code else False

    @api.onchange("dept_source_type", "data_source_id")
    def _onchange_unit(self):
        score_base = self.env["res.config.settings"].get_score_scale_base()
        for rec in self:
            rec.unit = rec._get_default_unit()
            if rec.dept_source_type == "child_kpi_average":
                rec.target = score_base

    def get_effective_formula(self):
        self.ensure_one()
        return self.scoring_formula_id

    @api.depends("target", "kpi_type", "unit", "unit.code", "unit.name")
    def _compute_display(self):
        for rec in self:
            if rec.is_section or rec.kpi_type != "quantitative":
                rec.target_display = ""
                continue
            if rec._is_percent_unit():
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                unit_name = rec.unit.name if rec.unit else ""
                rec.target_display = f"{target} {unit_name}" if unit_name else target

    @api.depends("kpi_type", "dept_source_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(
                rec.kpi_type == "quantitative"
                and rec.dept_source_type in ("child_kpi_average", "data_source")
                and (
                    rec.dept_source_type == "child_kpi_average"
                    or rec.data_source_id
                )
            )
