import json

from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

from .kpi_type_utils import (
    KPI_TYPE_SELECTION,
    MANUAL_SCORING_TYPE_SELECTION,
    P3_PILLAR_CODES,
    get_manual_scoring_type_required_message,
)


class HrDepartmentEvaluationLine(models.Model):
    _name = "hr.department.evaluation.line"
    _description = "Department Evaluation Line"
    _CHATTER_TRACK_FIELD_ORDER = (
        "name",
        "kpi_type",
        "manual_scoring_type",
        "target",
        "unit",
        "weight",
        "actual",
        "scoring_formula_id",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
        "manager_comment",
    )
    _CHATTER_COMMENT_FIELDS = {"manager_comment"}

    evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation", ondelete="cascade"
    )
    department_kpi_line_id = fields.Many2one("hr.department.kpi.template.line")
    parent_template_line_id = fields.Many2one(
        "hr.department.kpi.template.line",
        string="Parent Template Line",
        ondelete="set null",
        index=True,
        help="Template parent used to rebuild the hierarchy on generated department evaluation lines.",
    )
    parent_line_id = fields.Many2one(
        "hr.department.evaluation.line",
        string="Parent Line",
        ondelete="set null",
        index=True,
    )
    child_line_ids = fields.One2many(
        "hr.department.evaluation.line",
        "parent_line_id",
        string="Child Lines",
    )

    name = fields.Char()
    pillar_id = fields.Many2one(
        "hr.evaluation.pillar",
        string="Pillar",
        ondelete="restrict",
    )
    pillar_code = fields.Selection(
        related="pillar_id.code",
        string="Pillar Code",
        store=True,
        readonly=True,
    )
    kpi_type = fields.Selection(
        KPI_TYPE_SELECTION,
        string="KPI Type",
    )
    manual_scoring_type = fields.Selection(
        MANUAL_SCORING_TYPE_SELECTION,
        string="Manual Scoring Type",
    )
    target = fields.Float()
    actual = fields.Float()
    unit = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="restrict",
        help="Display unit for Target/Actual, e.g. %, tasks, days, score.",
    )
    weight = fields.Float()
    score_scale_base_override = fields.Float(
        string="Score Scale Base Override",
        help="Optional native score scale for this line, for example 100, 10, or 5. Leave empty to use the global KPI score scale.",
    )
    violation_threshold = fields.Integer(
        string="Violation Threshold",
        default=0,
        help="For P3 KPI lines, a violation count above this threshold triggers wipeout for the whole branch.",
    )
    is_auto = fields.Boolean()
    dept_source_type = fields.Selection(
        related="department_kpi_line_id.dept_source_type",
        string="Department Source Type",
        store=True,
        readonly=True,
    )
    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        related="department_kpi_line_id.data_source_id",
        string="Data Source",
        store=True,
        readonly=True,
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        related="department_kpi_line_id.scoring_formula_id",
        string="Scoring Formula",
        store=True,
        readonly=True,
    )
    is_section = fields.Boolean()
    description = fields.Html(
        string="Description",
        sanitize=True,
    )
    sequence = fields.Integer(default=10)

    system_score = fields.Float(compute="_compute_system_score", store=True)
    final_score = fields.Float(compute="_compute_final_score", store=True)
    # Technical field used by the UI to colorize final_score as a badge.
    final_score_badge_class = fields.Char(
        string="Final Rating Badge Class",
        compute="_compute_final_score_badge_class",
        store=False,
    )
    # Always-formatted text for UI badge rendering (keeps 0.0 visible).
    final_score_badge_text = fields.Char(
        string="Final Rating",
        compute="_compute_final_score_badge_text",
        store=False,
    )

    _BINARY_YN = [("yes", "Yes"), ("no", "No")]
    manager_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Manager Rating (Binary)",
    )

    _RATING_0_5 = [
        ("0", "0"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ]
    manager_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Manager Rating (0-5)",
        default="0",
    )

    manager_rating_score = fields.Float(
        string="Manager Rating (Score)",
        default=0,
        digits=(16, 2),
    )

    manager_comment = fields.Text()

    # Formatted Target value for display(shows % when Target Type is Percentage).
    target_display = fields.Char(
        string="Target",
        compute="_compute_display",
        store=False,
    )
    # Formatted Actual value for display(shows % when Target Type is Percentage).
    actual_display = fields.Char(
        string="Actual",
        compute="_compute_display",
        store=False,
    )
    is_severe_violation = fields.Boolean(
        string="Severe Violation",
        default=False,
        help="For P3 KPI lines, enable this when the KPI line has a severe violation that wipes out the whole branch.",
    )
    violation_count = fields.Integer(
        string="Violation Count",
        default=0,
        help="For P3 KPI lines, this stores the counted number of violations for wipeout checks.",
    )
    is_wipeout_triggered = fields.Boolean(
        string="Wipeout Triggered",
        compute="_compute_is_wipeout_triggered",
        store=True,
        help="Technical flag: True when this KPI branch is wiped out because a severe violation exists in the branch.",
    )
    
    # link to individual evaluation line
    child_evaluation_line_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "parent_dept_evaluation_line_id",
        string="Child KPI Lines",
        readonly=True,
    )
    child_evaluation_line_count = fields.Integer(
        string="Child KPI Count",
        compute="_compute_child_line_trace",
        store=False,
    )
    child_line_rows_json = fields.Text(
        string="Child KPI Rows JSON",
        compute="_compute_child_line_trace",
        store=False,
    )

    def _get_chatter_tracked_fields(self, vals):
        return [
            field_name
            for field_name in self._CHATTER_TRACK_FIELD_ORDER
            if field_name in vals
        ]

    def _snapshot_chatter_tracked_values(self, field_names):
        return {
            line.id: {field_name: line[field_name] for field_name in field_names}
            for line in self
        }

    def _format_chatter_preview(self, value):
        preview = html2plaintext(value or "")
        preview = " ".join(preview.split())
        if len(preview) > 120:
            preview = f"{preview[:117]}..."
        return preview

    def _format_chatter_value(self, field_name, value):
        field = self._fields[field_name]
        empty_value = _("Empty")

        if field.type == "many2one":
            return value.display_name if value else empty_value
        if field.type == "selection":
            selection = dict(field._description_selection(self.env))
            return selection.get(value, value or empty_value)
        if field.type in {"float", "integer", "monetary"}:
            if value in (False, None):
                return empty_value
            return f"{value:g}"
        if field.type == "date":
            return fields.Date.to_string(value) if value else empty_value
        if field.type == "datetime":
            return fields.Datetime.to_string(value) if value else empty_value
        if field.type == "boolean":
            return _("Yes") if value else _("No")
        if field.type in {"char", "text", "html"}:
            return self._format_chatter_preview(value) or empty_value
        return str(value) if value not in (False, None, "") else empty_value

    def _post_parent_chatter_audit(self, tracked_fields, snapshot_by_line):
        if self.env.context.get("skip_line_chatter_audit"):
            return

        for line in self:
            parent = line.evaluation_id
            before_values = snapshot_by_line.get(line.id) or {}
            if not parent or not before_values:
                continue

            detail_items = []
            for field_name in tracked_fields:
                if field_name not in before_values:
                    continue

                old_value = before_values[field_name]
                new_value = line[field_name]
                if new_value == old_value or (not new_value and not old_value):
                    continue

                field_label = escape(line._fields[field_name].string)
                if field_name in line._CHATTER_COMMENT_FIELDS:
                    preview = line._format_chatter_preview(new_value)
                    preview_markup = (
                        Markup(": <i>%s</i>") % escape(preview)
                        if preview
                        else Markup("")
                    )
                    detail_items.append(
                        Markup("<li><b>%s</b> updated%s</li>")
                        % (field_label, preview_markup)
                    )
                    continue

                old_display = escape(line._format_chatter_value(field_name, old_value))
                new_display = escape(line._format_chatter_value(field_name, new_value))
                detail_items.append(
                    Markup("<li><b>%s</b>: %s &rarr; %s</li>")
                    % (field_label, old_display, new_display)
                )

            if not detail_items:
                continue

            line_label = line.name or line.display_name or _("KPI line")
            body = Markup("<p>KPI line <b>%s</b> was updated.</p><ul>%s</ul>") % (
                escape(line_label),
                Markup("").join(detail_items),
            )
            parent.message_post(body=body, subtype_xmlid="mail.mt_note")

    @api.depends(
        "child_evaluation_line_ids",
        "child_evaluation_line_ids.kpi_line_id",
        "child_evaluation_line_ids.key_performance_area",
        "child_evaluation_line_ids.final_rating",
        "child_evaluation_line_ids.weight",
        "child_evaluation_line_ids.evaluation_id",
        "child_evaluation_line_ids.evaluation_id.name",
        "child_evaluation_line_ids.evaluation_id.employee_id",
        "child_evaluation_line_ids.evaluation_id.employee_id.name",
    )
    def _compute_child_line_trace(self):
        for line in self:
            child_lines = line.child_evaluation_line_ids.filtered(
                lambda l: not l.is_section
            ).sorted(
                key=lambda l: (
                    l.key_performance_area or "",
                    l.evaluation_id.employee_id.name or "",
                    l.sequence or 0,
                    l.id or 0,
                )
            )
            line.child_evaluation_line_count = len(child_lines)
            if not child_lines:
                line.child_line_rows_json = "[]"
                continue
            child_rows = []
            for child_line in child_lines:
                evaluation = child_line.evaluation_id
                employee = evaluation.employee_id
                child_rows.append(
                    {
                        "employee": employee.name or "",
                        "employee_id": employee.id or False,
                        "child_kpi": child_line.key_performance_area or "",
                        "child_kpi_id": child_line.kpi_line_id.id or False,
                        "weight": child_line.weight or 0.0,
                        "final_rating": child_line.final_rating or 0.0,
                        "evaluation": evaluation.display_name or evaluation.name or "",
                        "evaluation_id": evaluation.id or False,
                    }
                )
            line.child_line_rows_json = json.dumps(child_rows, ensure_ascii=False)

    def _get_score_base(self):
        self.ensure_one()
        if self.score_scale_base_override and self.score_scale_base_override > 0:
            return self.score_scale_base_override
        return self.env["res.config.settings"].get_score_scale_base()

    # Convert the global pass/excellent thresholds to the line score base.
    def _get_score_thresholds(self):
        self.ensure_one()
        settings = self.env["res.config.settings"]
        excellent, passed = settings.get_thresholds()
        configured_base = settings.get_score_scale_base() or 10.0
        target_base = self._get_score_base()
        if configured_base and target_base and configured_base != target_base:
            excellent = settings.convert_score(excellent, configured_base, target_base)
            passed = settings.convert_score(passed, configured_base, target_base)
        return excellent, passed

    # Detect whether the line belongs to a P3 pillar that supports wipeout rules.
    def _is_p3_line(self):
        self.ensure_one()
        return self.pillar_code in P3_PILLAR_CODES

    # Return the direct children that participate in score roll-up.
    def _get_direct_scoring_children(self):
        self.ensure_one()
        return self.child_line_ids.sorted(lambda line: (line.sequence or 0, line.id or 0))

    def _get_child_score_aggregate(self):
        self.ensure_one()
        child_lines = self._get_direct_scoring_children()
        if not child_lines:
            return False
        total_weight = sum(child_lines.mapped("weight"))
        if total_weight > 0:
            return sum(
                child.final_score * child.weight for child in child_lines
            ) / total_weight
        return sum(child_lines.mapped("final_score")) / len(child_lines)

    # Compute the branch wipeout flag used by normalized P3 scoring.
    @api.depends(
        "pillar_code",
        "is_section",
        "is_severe_violation",
        "violation_count",
        "violation_threshold",
        "child_line_ids",
        "child_line_ids.parent_line_id",
        "child_line_ids.is_wipeout_triggered",
    )
    def _compute_is_wipeout_triggered(self):
        for line in self:
            if not line._is_p3_line():
                line.is_wipeout_triggered = False
                continue

            child_lines = line._get_direct_scoring_children()
            if child_lines:
                line.is_wipeout_triggered = any(
                    child.is_wipeout_triggered for child in child_lines
                )
                continue

            line.is_wipeout_triggered = bool(
                line.is_severe_violation
                or (line.violation_count or 0) > (line.violation_threshold or 0)
            )

    def _compute_system_score_for_line(self, line, actual, target, score_base=None):
        score_base = float(
            score_base or line._get_score_base() or 0.0
        )
        formula = (
            line.department_kpi_line_id.get_effective_formula()
            if line.department_kpi_line_id
            else False
        )
        if not formula:
            return 0.0
        try:
            score = formula.compute_score(actual or 0.0, target or 0.0, max_score=score_base)
        except Exception:
            return 0.0

        if getattr(formula, "formula_type", False) == "linear" and getattr(
            formula, "linear_allow_exceed", False
        ):
            return round(max(score, 0.0), 2)
        return round(max(0.0, min(score, score_base)), 2)

    @api.depends(
        "actual",
        "target",
        "kpi_type",
        "manual_scoring_type",
        "score_scale_base_override",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
        "child_line_ids",
        "child_line_ids.parent_line_id",
        "child_line_ids.final_score",
        "child_line_ids.weight",
        "child_line_ids.is_wipeout_triggered",
        "is_wipeout_triggered",
        "scoring_formula_id",
        "scoring_formula_id.formula_type",
        "scoring_formula_id.linear_direction",
        "scoring_formula_id.linear_allow_exceed",
        "scoring_formula_id.step_out_of_range",
        "scoring_formula_id.penalty_base_score",
        "scoring_formula_id.penalty_deduct_per_unit",
        "scoring_formula_id.penalty_floor",
        "scoring_formula_id.expression_code",
    )
    # Compute the department line score from either auto formulas or manual scoring inputs.
    def _compute_system_score(self):
        for line in self:
            score_base = line._get_score_base()
            if line.is_wipeout_triggered:
                line.system_score = 0.0
                continue
            child_score = line._get_child_score_aggregate()
            if child_score is not False:
                line.system_score = round(
                    max(0.0, min(child_score, score_base)),
                    2,
                )
                continue

            # Section rows without children remain non-scorable placeholders.
            if line.is_section:
                line.system_score = 0.0
                continue

            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            if line.kpi_type == "auto":
                score = line._compute_system_score_for_line(
                    line,
                    actual,
                    target,
                    score_base=score_base,
                )
            elif line.kpi_type == "manual" and line.manual_scoring_type == "binary":
                val = line.manager_rating_binary
                score = score_base if val == "yes" else 0.0
            elif line.kpi_type == "manual" and line.manual_scoring_type == "rating":
                raw = line.manager_rating_selection or "0"
                rating = float(raw)
                score = (rating / 5.0) * score_base
            elif line.kpi_type == "manual" and line.manual_scoring_type == "score":
                val = line.manager_rating_score or 0
                score = float(val)

            line.system_score = max(0.0, min(score, score_base))

    @api.depends("system_score")
    def _compute_final_score(self):
        for line in self:
            score_base = line._get_score_base()
            line.final_score = round(max(0.0, min(line.system_score or 0.0, score_base)), 2)

    # Thay thế hàm hiện tại bằng đoạn code này:
    def _is_percent_unit(self):
        """Use the unit code as the source of truth for percentage KPI lines."""
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    # Format the target and actual previews only for auto department KPI lines.
    @api.depends("target", "actual", "kpi_type", "unit", "unit.code", "unit.name")
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != "auto":
                rec.target_display = ""
                rec.actual_display = ""
                continue

            # Format 2 chữ số thập phân, cắt bỏ số 0 và dấu chấm thừa ở đuôi
            target_str = f"{(rec.target or 0.0):.2f}".rstrip("0").rstrip(".")
            actual_str = f"{(rec.actual or 0.0):.2f}".rstrip("0").rstrip(".")

            if rec._is_percent_unit():
                rec.target_display = f"{target_str}%"
                rec.actual_display = f"{actual_str}%"
            else:
                unit_name = rec.unit.name if rec.unit else ""
                rec.target_display = (
                    f"{target_str} {unit_name}" if unit_name else target_str
                )
                rec.actual_display = (
                    f"{actual_str} {unit_name}" if unit_name else actual_str
                )

    @api.depends("final_score", "score_scale_base_override")
    def _compute_final_score_badge_class(self):
        for line in self:
            excellent, passed = line._get_score_thresholds()
            score = line.final_score or 0.0
            if score >= excellent:
                line.final_score_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                line.final_score_badge_class = "o_kpi_badge_pass"
            else:
                line.final_score_badge_class = "o_kpi_badge_fail"

    @api.depends("final_score")
    def _compute_final_score_badge_text(self):
        for line in self:
            score = line.final_score or 0.0

            # An toàn: Làm tròn score về 2 chữ số trước khi xét để tránh lỗi floating point
            rounded_score = round(score, 2)

            # Nếu là số nguyên (ví dụ 0.0, 10.0, 8.0) thì in ra số nguyên cho gọn
            if rounded_score.is_integer():
                line.final_score_badge_text = str(int(rounded_score))
            # Nếu có phần lẻ (ví dụ 8.5) thì in ra kèm phần thập phân
            else:
                line.final_score_badge_text = f"{rounded_score:.2f}".rstrip("0").rstrip(
                    "."
                )

    # Keep manual subtype required for manual lines and empty for auto lines.
    @api.constrains("kpi_type", "manual_scoring_type")
    def _check_manual_scoring_type(self):
        for rec in self:
            if rec.is_section:
                continue
            if rec.kpi_type == "manual" and not rec.manual_scoring_type:
                raise ValidationError(get_manual_scoring_type_required_message())
            if rec.kpi_type == "auto" and rec.manual_scoring_type:
                raise ValidationError(
                    _("Manual scoring type must be empty for auto KPI lines.")
                )

    # Validate manual score inputs against the configured score base.
    @api.constrains("manager_rating_score", "kpi_type", "manual_scoring_type")
    def _check_manager_rating_score_range(self):
        for rec in self:
            score_base = rec._get_score_base()
            if (
                rec.kpi_type == "manual"
                and rec.manual_scoring_type == "score"
                and not 0 <= (rec.manager_rating_score or 0.0) <= score_base
            ):
                raise ValidationError(
                    _("Manager score must be between 0 and %(max_score)s.")
                    % {"max_score": f"{score_base:g}"}
                )

    # Keep P3 wipeout inputs non-negative.
    @api.constrains("violation_threshold", "violation_count")
    def _check_violation_values(self):
        for rec in self:
            if (rec.violation_threshold or 0) < 0:
                raise ValidationError(_("Violation threshold cannot be negative."))
            if (rec.violation_count or 0) < 0:
                raise ValidationError(_("Violation count cannot be negative."))

    @api.constrains("parent_line_id", "evaluation_id")
    def _check_parent_line(self):
        for rec in self:
            parent = rec.parent_line_id
            if not parent:
                continue
            if parent == rec:
                raise ValidationError(_("A KPI line cannot be its own parent."))
            if parent.evaluation_id != rec.evaluation_id:
                raise ValidationError(
                    _("The parent line must belong to the same evaluation.")
                )
            # Allow section parents because aggregate section rows own the child KPI tree.
            if parent.parent_line_id == rec:
                raise ValidationError(
                    _("Recursive KPI line hierarchy is not allowed.")
                )

    def write(self, vals):
        tracked_fields = self._get_chatter_tracked_fields(vals or {})
        snapshot_by_line = (
            self._snapshot_chatter_tracked_values(tracked_fields)
            if tracked_fields
            else {}
        )

        res = super().write(vals)
        if snapshot_by_line:
            self._post_parent_chatter_audit(tracked_fields, snapshot_by_line)
        return res

    def action_open_popup(self):
        self.ensure_one()
        return {
            "name": _("Edit KPI Line"),
            "type": "ir.actions.act_window",
            "res_model": "hr.department.evaluation.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_department_evaluation_line_form_popup"
            ).id,
            "target": "new",
        }
