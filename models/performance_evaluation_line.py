import logging

from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class PerformanceEvaluationLine(models.Model):
    _name = "hr.performance.evaluation.line"
    _description = "Performance Evaluation Line"
    _order = "sequence, id"
    _CHATTER_TRACK_FIELD_ORDER = (
        "key_performance_area",
        "kpi_type",
        "target",
        "unit",
        "weight",
        "actual",
        "scoring_formula_id",
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
        "employee_comment",
        "manager_comment",
    )
    _CHATTER_COMMENT_FIELDS = {"employee_comment", "manager_comment"}

    # Optional: keep a backlink to the KPI template line that generated this evaluation line.
    # This makes the mapping explicit and allows future sync/update.
    kpi_line_id = fields.Many2one(
        "hr.kpi.template.line",
        string="KPI Template Line",
        ondelete="set null",
        index=True,
        help="The KPI template line this evaluation line comes from (for traceability).",
    )
    parent_dept_line_id = fields.Many2one(
        "hr.department.kpi.template.line",
        string="Parent Department KPI Template",
        ondelete="set null",
        index=True,
        help="The department KPI template line linked to this employee KPI line.",
    )
    parent_dept_evaluation_line_id = fields.Many2one(
        "hr.department.evaluation.line",
        string="Parent Department KPI",
        ondelete="set null",
        index=True,
        help="The department evaluation line generated for the same period.",
    )

    evaluation_id = fields.Many2one(
        "hr.performance.evaluation",
        string="Performance Evaluation",
        ondelete="cascade",
        help="The evaluation record that this line belongs to.",
    )
    evaluation_state = fields.Selection(
        related="evaluation_id.state",
        string="Evaluation State",
        store=False,
        help="Current workflow state of the parent evaluation.",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        related="evaluation_id.employee_id",
        store=False,
    )
    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
        help="The KPI title (or the section header name if this is a Section).",
    )
    kpi_type = fields.Selection(
        selection=[
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ],
        string="KPI Type",
        default="quantitative",
        required=True,
        help="How this KPI line is evaluated: Quantitative (Target vs Actual), Binary (Yes/No), Rating (0–5), or direct Score.",
    )

    target = fields.Float(
        string="Target",
        default=0.0,
        help="Target value to be achieved for Quantitative KPIs.",
    )
    unit = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="restrict",
        help="Display unit for Target/Actual, e.g. %, tasks, days, score.",
    )
    weight = fields.Float(
        string="Weight",
        default=0.0,
        help="Weight of this KPI in the overall evaluation (higher weight has more impact).",
    )

    is_auto = fields.Boolean(
        string="Auto Compute",
        default=False,
        compute="_compute_auto",
        store=True,
        help="Enable to let the system automatically compute Actual values from the selected Data Source.",
    )
    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        related="kpi_line_id.data_source_id",
        string="Data Source",
        store=True,
        readonly=True,
    )
    formula_type = fields.Selection(
        related="kpi_line_id.formula_type",
        string="Scoring Formula",
        store=True,
        readonly=True,
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        related="kpi_line_id.scoring_formula_id",
        string="Scoring Formula",
        store=True,
        readonly=True,
    )
    step_table_json = fields.Text(
        related="kpi_line_id.step_table_json",
        string="Step Table JSON",
        store=True,
        readonly=True,
    )

    # ------------------------------------------------------------
    # Auto KPI metrics from detail-capable data sources
    # ------------------------------------------------------------
    attendance_worked_days = fields.Float(
        string="Worked Days",
        default=0.0,
        help="Number of distinct days with at least one check-in.",
    )
    attendance_expected_days = fields.Float(
        string="Expected Work Days",
        default=0.0,
        help="Expected work days from the employee working schedule.",
    )
    attendance_unpaid_leave_days = fields.Float(
        string="Unpaid Leave Days",
        default=0.0,
        help="Expected days minus worked days.",
    )
    attendance_approved_leave_days = fields.Float(
        string="Approved Leave Days",
        default=0.0,
        help="Validated leave days overlapping the evaluation period.",
    )
    attendance_has_unpaid_leave = fields.Boolean(
        string="Has Unpaid Leave",
        default=False,
        help="True when unpaid leave exceeds approved leave days.",
    )

    # actual: giá trị canonical dùng để tính system_score
    #   - kpi_type=quantitative: công thức hiệu lực quyết định cách so sánh target/actual
    #   - unit.code='percent' quyết định giá trị là phần trăm 0-100
    actual = fields.Float(
        string="Actual",
        help="Actual value input/collected for Quantitative KPIs. Compared against Target to compute the System Score.",
        digits=(16, 2),
    )

    target_display = fields.Char(
        string="Target",
        compute="_compute_display",
        store=False,
        help="Formatted Target value for display (shows % when Target Type is Percentage).",
    )
    actual_display = fields.Char(
        string="Actual",
        compute="_compute_display",
        store=False,
        help="Formatted Actual value for display (shows % when Target Type is Percentage).",
    )

    system_score = fields.Float(
        string="System Score",
        compute="_compute_system_score",
        store=True,
        digits=(16, 1),
        help="System-calculated score based on rules for the selected KPI type and configured score scale.",
    )
    # Technical flag: True when scoring uses a custom rule (not Target vs Actual ratio).
    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=True,
        help="Technical flag: True when scoring uses a custom rule (not Target vs Actual ratio).",
    )

    # ------------------------------------------------------------
    # Self vs Manager rating
    # ------------------------------------------------------------
    # Quantitative: (optional) employee_rating_value/manager_rating_value are kept for future UX,
    # but final_rating is driven by system_score per requirement.
    employee_rating_value = fields.Float(
        string="Employee Rating (Value)",
        digits=(16, 2),
        help="Optional employee rating for Quantitative KPIs (not used in final scoring if System Score is applied).",
    )
    manager_rating_value = fields.Float(
        string="Manager Rating (Value)",
        digits=(16, 2),
        help="Optional manager rating for Quantitative KPIs (not used in final scoring if System Score is applied).",
    )

    # Binary: use these fields for self vs manager.
    _BINARY_YN = [("yes", "Yes"), ("no", "No")]
    employee_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Employee Rating (Binary)",
        help="Employee self-assessment for Binary KPIs (Yes/No).",
        default="yes"
    )
    manager_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Manager Rating (Binary)",
        help="Manager assessment for Binary KPIs (Yes/No).",
        default="yes"
    )

    # Rating: 0..5 selection.
    _RATING_0_5 = [
        ("0", "0"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ]
    employee_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Employee Rating (0-5)",
        help="Employee self-assessment for Rating KPIs (0–5).",
        default="0",
    )
    manager_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Manager Rating (0-5)",
        help="Manager assessment for Rating KPIs (0–5).",
        default="0",
    )

    # Score KPI: employee self score and manager final score theo thang điểm cấu hình.
    employee_rating_score = fields.Float(
        string="Employee Rating (Score)",
        default=0,
        digits=(16, 2),
        help="Employee self-assessment score for Score KPIs, based on the configured KPI score scale.",
    )
    manager_rating_score = fields.Float(
        string="Manager Rating (Score)",
        default=0,
        digits=(16, 2),
        help="Manager score for Score KPIs, based on the configured KPI score scale.",
    )

    employee_comment = fields.Html(
        string="Employee Comment",
        sanitize=True,
        help="Employee notes or justification for the self-assessment.",
    )
    manager_comment = fields.Html(
        string="Manager Comment",
        sanitize=True,
        help="Manager notes, feedback, or justification for the final assessment.",
    )

    final_rating = fields.Float(
        string="Final Rating",
        compute="_compute_final_rating",
        store=True,
        digits=(16, 1),
        help="Final rating used in the evaluation summary, based on the configured KPI score scale.",
    )

    # Always-formatted text for UI badge rendering (keeps 0.0 visible).
    final_rating_badge_text = fields.Char(
        string="Final Rating",
        compute="_compute_final_rating_badge_text",
        store=False,
    )

    final_rating_badge_class = fields.Char(
        string="Final Rating Badge Class",
        compute="_compute_final_rating_badge_class",
        store=False,
        help="Technical field used by the UI to colorize final_rating as a badge.",
    )

    manager_edited = fields.Boolean(
        string="Manager Edited",
        compute="_compute_manager_edited",
        store=True,
        help="Technical flag: True when manager rating differs from employee rating (or was set when employee rating is empty).",
    )
    description = fields.Html(
        string="Description",
        sanitize=True,
        help="Additional details or guidance for this evaluation line.",
    )

    is_manager = fields.Boolean(related="evaluation_id.is_manager", store=False)
    is_hr = fields.Boolean(related="evaluation_id.is_hr", store=False)
    is_employee = fields.Boolean(related="evaluation_id.is_employee", store=False)
    is_current_user = fields.Boolean(
        related="evaluation_id.is_current_user", store=False
    )
    is_department_manager = fields.Boolean(
        related="evaluation_id.is_department_manager", store=False
    )

    is_section = fields.Boolean(default=False)
    display_type = fields.Selection(
        selection=[
            ("line_section", "Section"),
            ("line_note", "Note"),
        ],
        default=False,
        compute="_compute_display_type",
        store=True,
        readonly=False,
        help="Technical field for section/note lines. Derived from is_section.",
    )
    sequence = fields.Integer(
        default=10,
        help="Controls the order of lines in the evaluation (drag & drop).",
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

            line_label = line.key_performance_area or line.display_name or _("KPI line")
            body = Markup("<p>KPI line <b>%s</b> was updated.</p><ul>%s</ul>") % (
                escape(line_label),
                Markup("").join(detail_items),
            )
            parent.message_post(body=body, subtype_xmlid="mail.mt_note")

    @api.depends("kpi_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(
                rec.kpi_type == "quantitative" and rec.data_source_id
            )

    @api.depends(
        "kpi_type",
        "formula_type",
        "scoring_formula_id",
        "scoring_formula_id.formula_type",
    )
    def _compute_is_special_scoring(self):
        for rec in self:
            effective_formula_type = (
                rec.scoring_formula_id.formula_type
                if rec.scoring_formula_id
                else rec.formula_type
            )

            rec.is_special_scoring = bool(
                rec.kpi_type == "quantitative"
                and effective_formula_type != "linear"
            )

    @api.depends("is_section")
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = "line_section" if rec.is_section else False

    @api.depends(
        "kpi_type",
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    def _compute_manager_edited(self):
        for line in self:
            if line.kpi_type == "binary":
                line.manager_edited = bool(line.manager_rating_binary) and (
                    line.manager_rating_binary != line.employee_rating_binary
                )
            elif line.kpi_type == "rating":
                line.manager_edited = bool(line.manager_rating_selection) and (
                    line.manager_rating_selection != line.employee_rating_selection
                )
            elif line.kpi_type == "score":
                # If employee score is 0/default but manager changed it to something else, this becomes True.
                line.manager_edited = (line.manager_rating_score is not None) and (
                    line.manager_rating_score != (line.employee_rating_score or 0)
                )
            else:
                # quantitative: manager doesn't rate in current logic
                line.manager_edited = False

    def _is_percent_unit(self):
        """Đơn vị percent là nguồn sự thật để nhận diện KPI phần trăm."""
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    def _get_score_base(self):
        """Thang điểm KPI được cấu hình theo từng khách hàng/database."""
        return self.env["res.config.settings"].get_score_scale_base()

    @api.depends("target", "actual", "kpi_type", "unit", "unit.code", "unit.name")
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != "quantitative":
                rec.target_display = ""
                rec.actual_display = ""
                continue

            if rec._is_percent_unit():
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
                rec.actual_display = f"{(rec.actual or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                actual = f"{(rec.actual or 0.0):g}"
                unit_name = rec.unit.name if rec.unit else ""
                rec.target_display = (
                    f"{target} {unit_name}" if unit_name else target
                )
                rec.actual_display = (
                    f"{actual} {unit_name}" if unit_name else actual
                )

    # ------------------------------------------------------------------
    # COMPUTE system_score: depends vào actual + các field liên quan
    # ------------------------------------------------------------------
    def _compute_system_score_for_line(self, line, actual, target, score_base=None):
        score_base = float(score_base or self._get_score_base() or 0.0)
        formula = line.kpi_line_id.get_effective_formula() if line.kpi_line_id else False
        if not formula:
            return 0.0
        try:
            score = formula.compute_score(actual or 0.0, target or 0.0, max_score=score_base)
        except Exception as exc:
            _logger.warning(
                "Failed computing KPI formula '%s' for evaluation line %s: %s",
                formula.display_name if formula else "n/a",
                line.id or "new",
                exc,
            )
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
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
        "formula_type",
        "step_table_json",
        "scoring_formula_id",
        "scoring_formula_id.formula_type",
        "scoring_formula_id.linear_direction",
        "scoring_formula_id.linear_allow_exceed",
        "scoring_formula_id.step_table_json",
        "scoring_formula_id.step_out_of_range",
        "scoring_formula_id.penalty_base_score",
        "scoring_formula_id.penalty_deduct_per_unit",
        "scoring_formula_id.penalty_floor",
        "scoring_formula_id.expression_code",
    )
    def _compute_system_score(self):
        """
        Tính system_score theo thang điểm cấu hình (10 hoặc 100):

        quantitative:
          score = scoring_formula.compute_score(actual, target, score_base)

        rating:
          actual = 0–5 (từ rating_value)
          → score = (actual / 5) * score_base

        binary:
          actual = target (achieved) hoặc 0 (not achieved)
          → score = score_base nếu đạt, ngược lại = 0
        """
        score_base = self._get_score_base()
        for line in self:
            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            if line.kpi_type == "quantitative":
                line.system_score = line._compute_system_score_for_line(
                    line,
                    actual,
                    target,
                    score_base=score_base,
                )
                continue

            elif line.kpi_type == "rating":
                # Ưu tiên manager nếu đã có, fallback về employee
                raw = (
                    line.manager_rating_selection
                    or line.employee_rating_selection
                    or "0"
                )
                rating = float(raw)
                score = (rating / 5.0) * score_base

            elif line.kpi_type == "binary":
                # Tương tự cho binary
                val = line.manager_rating_binary or line.employee_rating_binary
                score = score_base if val == "yes" else 0.0

            elif line.kpi_type == "score":
                # Tương tự cho score
                val = line.manager_rating_score or line.employee_rating_score or 0
                score = float(val)

            line.system_score = round(max(0.0, min(score, score_base)), 2)

    # ------------------------------------------------------------------
    # COMPUTE final_rating depends on kpi_type
    # ------------------------------------------------------------------
    @api.depends(
        "kpi_type",
        "system_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    def _compute_final_rating(self):
        score_base = self._get_score_base()
        for line in self:
            if line.kpi_type == "quantitative":
                # system_score đã đúng, dùng thẳng
                line.final_rating = round(
                    min(max(line.system_score or 0.0, 0.0), score_base), 2
                )
            else:
                # Với binary/rating/score: final_rating = system_score (manager đã được ưu tiên trong system_score)
                line.final_rating = round(
                    min(max(line.system_score or 0.0, 0.0), score_base), 2
                )

    @api.depends("final_rating")
    def _compute_final_rating_badge_class(self):
        excellent, passed = self.env["res.config.settings"].get_thresholds()
        for line in self:
            score = line.final_rating or 0.0
            if score >= excellent:
                line.final_rating_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                line.final_rating_badge_class = "o_kpi_badge_pass"
            else:
                line.final_rating_badge_class = "o_kpi_badge_fail"

    @api.depends("final_rating")
    def _compute_final_rating_badge_text(self):
        score_base = self._get_score_base()
        for line in self:
            rating = line.final_rating
            if rating == 0:
                line.final_rating_badge_text = "0"
            elif rating == score_base or rating % 1 == 0:
                line.final_rating_badge_text = f"{int(rating)}"
            else:
                line.final_rating_badge_text = f"{rating:.1f}"

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------
    # @api.onchange('kpi_type')
    # def _onchange_kpi_type(self):
    #     if self.kpi_line_id:
    #         return
    #
    #     self.actual = 0.0
    #     self.employee_rating_value = 0.0
    #     self.manager_rating_value = 0.0
    #     self.employee_rating_binary = False
    #     self.manager_rating_binary = False
    #     self.employee_rating_selection = False
    #     self.manager_rating_selection = False
    #     self.employee_rating_score = 0
    #     self.manager_rating_score = 0

    @api.onchange(
        "employee_rating_binary", "employee_rating_selection", "employee_rating_score"
    )
    def _onchange_employee_rating_autofill_manager(self):
        """In self evaluation state, mirror employee self-rating into manager rating.

        Purpose: allow employees to see current final_rating and the evaluation average in real time,
        without waiting for the Submit action.

        Notes:
        - This is an onchange-only UX helper. Real security is enforced in write().
        - We only mirror while the parent evaluation is in self evaluation.
        """
        # New (unsaved) one2many lines might not have evaluation_id yet in some cases.
        if self.evaluation_id and self.evaluation_id.state != "self_evaluation":
            return

        for line in self:
            if line.kpi_type == "binary" and line.employee_rating_binary:
                line.manager_rating_binary = line.employee_rating_binary
            elif line.kpi_type == "rating" and line.employee_rating_selection:
                line.manager_rating_selection = line.employee_rating_selection
            elif line.kpi_type == "score" and line.employee_rating_score is not None:
                line.manager_rating_score = line.employee_rating_score

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("manager_rating_selection", "kpi_type")
    def _check_manager_rating_selection_range(self):
        for rec in self:
            if rec.kpi_type == "rating":
                if (
                    rec.manager_rating_selection
                    and rec.manager_rating_selection not in dict(self._RATING_0_5)
                ):
                    raise ValidationError(
                        "Manager rating selection must be between 0 and 5."
                    )

    @api.constrains("employee_rating_score", "manager_rating_score", "kpi_type")
    def _check_score_range(self):
        score_base = self._get_score_base()
        for rec in self:
            if rec.kpi_type == "score":
                if not 0 <= (rec.employee_rating_score or 0) <= score_base:
                    raise ValidationError(
                        _("Employee score must be between 0 and %(max_score)s.")
                        % {"max_score": f"{score_base:g}"}
                    )
                if not 0 <= (rec.manager_rating_score or 0) <= score_base:
                    raise ValidationError(
                        _("Manager score must be between 0 and %(max_score)s.")
                        % {"max_score": f"{score_base:g}"}
                    )

    @api.constrains("employee_rating_value", "manager_rating_value")
    def _check_value_ratings_range(self):
        score_base = self._get_score_base()
        for rec in self:
            if (
                rec.employee_rating_value is not None
                and not 0.0 <= rec.employee_rating_value <= score_base
            ):
                raise ValidationError(
                    _("Employee rating value must be between 0 and %(max_score)s.")
                    % {"max_score": f"{score_base:g}"}
                )
            if (
                rec.manager_rating_value is not None
                and not 0.0 <= rec.manager_rating_value <= score_base
            ):
                raise ValidationError(
                    _("Manager rating value must be between 0 and %(max_score)s.")
                    % {"max_score": f"{score_base:g}"}
                )

    def _mirror_employee_to_manager_vals(self, vals, vals_before=None):
        """Mirror employee self-rating into manager rating on self evaluation evaluations.

        Onchange only updates in memory; without this, manager fields revert after save/reload.
        """
        vals = dict(vals or {})
        vals_before = dict(vals_before or vals)
        for line in self:
            if line.evaluation_id and line.evaluation_id.state != "self_evaluation":
                continue
            if line.kpi_type == "binary" and "employee_rating_binary" in vals_before:
                vals.setdefault(
                    "manager_rating_binary", vals_before.get("employee_rating_binary")
                )
            elif (
                line.kpi_type == "rating" and "employee_rating_selection" in vals_before
            ):
                vals.setdefault(
                    "manager_rating_selection",
                    vals_before.get("employee_rating_selection"),
                )
            elif line.kpi_type == "score" and "employee_rating_score" in vals_before:
                vals.setdefault(
                    "manager_rating_score", vals_before.get("employee_rating_score")
                )
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        """Keep section consistency and append new lines by sequence when not provided."""
        seq_step = 10

        eval_ids = {
            vals.get("evaluation_id") for vals in vals_list if vals.get("evaluation_id")
        }
        max_seq_by_eval = {}
        if eval_ids:
            lines = self.search_read(
                [("evaluation_id", "in", list(eval_ids))],
                ["evaluation_id", "sequence"],
                order="sequence desc",
            )
            for l in lines:
                eid = l["evaluation_id"][0] if l.get("evaluation_id") else False
                if eid and eid not in max_seq_by_eval:
                    max_seq_by_eval[eid] = l.get("sequence") or 0

        for vals in vals_list:
            if vals.get("display_type") and "is_section" not in vals:
                vals["is_section"] = True

            evaluation_id = vals.get("evaluation_id")
            if evaluation_id and not vals.get("sequence"):
                current_max = max_seq_by_eval.get(evaluation_id)
                if current_max is None:
                    current_max = 0
                vals["sequence"] = current_max + seq_step
                max_seq_by_eval[evaluation_id] = vals["sequence"]

            # Add: mirror employee->manager at create time too
            kpi_type = vals.get("kpi_type")
            if kpi_type == "binary" and "employee_rating_binary" in vals:
                vals.setdefault(
                    "manager_rating_binary", vals.get("employee_rating_binary")
                )
            elif kpi_type == "rating" and "employee_rating_selection" in vals:
                vals.setdefault(
                    "manager_rating_selection", vals.get("employee_rating_selection")
                )
            elif kpi_type == "score" and "employee_rating_score" in vals:
                vals.setdefault(
                    "manager_rating_score", vals.get("employee_rating_score")
                )

        return super().create(vals_list)

    def write(self, vals):
        # 1. Đảm bảo tính nhất quán cho các dòng Section
        if vals.get("display_type") and "is_section" not in vals:
            vals = dict(vals, is_section=True)

        # Lưu lại bản sao dữ liệu GỐC trước khi bị mirror can thiệp
        vals_before = dict(vals or {})
        tracked_fields = self._get_chatter_tracked_fields(vals_before)
        snapshot_by_line = (
            self._snapshot_chatter_tracked_values(tracked_fields)
            if tracked_fields
            else {}
        )

        # Hàm mirror sẽ tự động copy điểm từ employee sang manager (nếu có)
        vals = self._mirror_employee_to_manager_vals(vals, vals_before=vals_before)

        is_superuser = self.env.is_superuser()

        if not is_superuser:
            user = self.env.user

            # Chặn toàn bộ hành động sửa trên phiếu đã bị hủy
            if any(line.evaluation_id.state in ["cancel", "completed"] for line in self):
                raise UserError(
                    _("You cannot modify lines of a canceled or completed evaluation.")
                )

            # Các cờ (flags) định danh
            is_manager_group = user.has_group(
                "custom_adecsol_hr_performance_evaluator.group_manager"
            )
            is_own_evaluation = all(
                line.evaluation_id.employee_id.user_id == user for line in self
            )

            # Phân loại các trường dữ liệu
            manager_fields = {
                "manager_rating_value",
                "manager_rating_binary",
                "manager_rating_selection",
                "manager_rating_score",
                "manager_comment",
            }
            employee_fields = {
                "employee_rating_value",
                "employee_rating_binary",
                "employee_rating_selection",
                "employee_rating_score",
                "employee_comment",
            }

            # Xác định xem người dùng đang CHỦ ĐỘNG sửa nhóm trường nào trên giao diện (kiểm tra từ vals_before)
            editing_employee_fields = bool(
                employee_fields.intersection(vals_before.keys())
            )
            editing_manager_fields = bool(
                manager_fields.intersection(vals_before.keys())
            )

            # =====================================================================
            # LOGIC 1: NẾU NGƯỜI DÙNG SỬA CÁC TRƯỜNG CỦA EMPLOYEE
            # =====================================================================
            if editing_employee_fields:
                if not is_own_evaluation:
                    raise UserError(
                        _(
                            "Only the employee being evaluated can edit self-rating and comments."
                        )
                    )

                if any(line.evaluation_id.state != "self_evaluation" for line in self):
                    raise UserError(
                        _(
                            "Employee fields can only be edited in the Self Evaluation state."
                        )
                    )

            # =====================================================================
            # LOGIC 2: NẾU NGƯỜI DÙNG SỬA CÁC TRƯỜNG CỦA MANAGER
            # =====================================================================
            if editing_manager_fields:
                if not is_manager_group:
                    raise UserError(
                        _(
                            "You do not have the required Manager access to edit manager fields."
                        )
                    )

                if any(line.evaluation_id.state != "manager_evaluating" for line in self):
                    raise UserError(
                        _(
                            "Manager rating is only editable in the Manager Evaluating state."
                        )
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
            "res_model": "hr.performance.evaluation.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_performance_evaluation_line_form_popup"
            ).id,
            "target": "new",
        }
