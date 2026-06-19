import logging

from markupsafe import Markup, escape
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

from .kpi_type_utils import (
    KPI_TYPE_SELECTION,
    MANUAL_SCORING_TYPE_SELECTION,
    NORMALIZED_3P_PILLAR_CODES,
    get_manual_scoring_type_required_message,
)

_logger = logging.getLogger(__name__)


class PerformanceEvaluationLine(models.Model):
    _name = "hr.performance.evaluation.line"
    _description = "Performance Evaluation Line"
    _order = "sequence, id"
    _rec_name = "key_performance_area"

    _CHATTER_TRACK_FIELD_ORDER = (
        "key_performance_area",
        "kpi_type",
        "manual_scoring_type",
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
    parent_template_line_id = fields.Many2one(
        "hr.kpi.template.line",
        string="Parent Template Line",
        ondelete="set null",
        index=True,
        help="Template parent used to rebuild the hierarchy on generated evaluation lines.",
    )
    parent_line_id = fields.Many2one(
        "hr.performance.evaluation.line",
        string="Parent Line",
        ondelete="set null",
        index=True,
        domain="[('evaluation_id', '=', evaluation_id), ('pillar_id', '=', pillar_id), ('id', '!=', id), ('is_section', '=', True)]",
    )
    child_line_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "parent_line_id",
        string="Child Lines",
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
        compute_sudo=True,
    )
    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
        help="The KPI title (or the section header name if this is a Section).",
    )
    kpi_type = fields.Selection(
        selection=KPI_TYPE_SELECTION,
        string="KPI Type",
        default="auto",
        required=True,
        help="How this KPI line is evaluated: Auto compares Target vs Actual, while Manual uses a selected manual scoring type.",
    )
    manual_scoring_type = fields.Selection(
        selection=MANUAL_SCORING_TYPE_SELECTION,
        string="Manual Scoring Type",
        help="Select how manual KPI lines are scored: Binary, Rating, or Score.",
    )

    target = fields.Float(
        string="Target",
        default=0.0,
        help="Target value to be achieved for Auto KPI lines.",
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
    wipeout_if_child_zero = fields.Boolean(
        string="Wipeout If Child Zero",
        default=False,
        help="Stored snapshot of the template wipeout rule so historical evaluations do not change when the template is updated later.",
    )
    score_max_display = fields.Char(
        string="Max Score",
        compute="_compute_score_max_display",
        store=False,
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
        string="Data Source",
        ondelete="set null",
        help="Stored snapshot of the template data source used by this historical evaluation line.",
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        string="Scoring Formula",
        ondelete="set null",
        help="Stored snapshot of the template scoring formula used by this historical evaluation line.",
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

    # actual: canonical value used for auto KPI scoring.
    actual = fields.Float(
        string="Actual",
        help="Actual value input or collected for Auto KPI lines. Compared against Target to compute the System Score.",
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
        help="System-calculated score based on rules for the selected KPI type and the 100-point KPI scale.",
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

    # Binary: use these fields for self vs manager.
    _BINARY_YN = [("yes", "Yes"), ("no", "No")]
    employee_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Self Rating (Binary)",
        help="Employee self-assessment for Binary KPIs (Yes/No).",
        default="yes",
    )
    manager_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Manager Rating (Binary)",
        help="Manager assessment for Binary KPIs (Yes/No).",
        default="yes",
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
        string="Self Rating (0-5)",
        help="Employee self-assessment for Rating KPIs (0–5).",
        default="5",
    )
    manager_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Manager Rating (0-5)",
        help="Manager assessment for Rating KPIs (0–5).",
        default="5",
    )

    # Score manual KPI: employee self score and manager final score on the fixed 100-point scale.
    employee_rating_score = fields.Float(
        string="Self Rating (Score)",
        default=100,
        digits=(16, 2),
        help="Employee self-assessment score for Score KPIs, based on the 100-point KPI scale.",
    )
    manager_rating_score = fields.Float(
        string="Manager Rating (Score)",
        default=100,
        digits=(16, 2),
        help="Manager score for Score KPIs, based on the 100-point KPI scale.",
    )

    employee_comment = fields.Html(
        string="Self Comment",
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
        help="Final rating used in the evaluation summary, based on the 100-point KPI scale.",
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
    is_admin = fields.Boolean(related="evaluation_id.is_admin", store=False)
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

    # Compute whether the evaluation line can auto-fill its actual value.
    @api.depends("kpi_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(rec.kpi_type == "auto" and rec.data_source_id)

    # Hiển thị nhãn thang điểm cố định cho manual score KPI.
    @api.depends("kpi_type", "manual_scoring_type")
    def _compute_score_max_display(self):
        for rec in self:
            rec.score_max_display = (
                "/ 100 pts"
                if rec.kpi_type == "manual"
                and rec.manual_scoring_type == "score"
                else ""
            )

    @api.depends(
        "kpi_type",
        "scoring_formula_id",
        "scoring_formula_id.formula_type",
    )
    # Flag evaluation lines that use non-linear auto scoring formulas.
    def _compute_is_special_scoring(self):
        for rec in self:
            effective_formula_type = (
                rec.scoring_formula_id.formula_type if rec.scoring_formula_id else False
            )
            rec.is_special_scoring = bool(
                rec.kpi_type == "auto"
                and effective_formula_type
                and effective_formula_type != "linear"
            )

    @api.depends("is_section")
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = "line_section" if rec.is_section else False

    @api.depends(
        "kpi_type",
        "manual_scoring_type",
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    # Detect whether the manager changed the manual rating compared with the employee input.
    def _compute_manager_edited(self):
        for line in self:
            if line.kpi_type != "manual":
                line.manager_edited = False
            elif line.manual_scoring_type == "binary":
                line.manager_edited = bool(line.manager_rating_binary) and (
                    line.manager_rating_binary != line.employee_rating_binary
                )
            elif line.manual_scoring_type == "rating":
                line.manager_edited = bool(line.manager_rating_selection) and (
                    line.manager_rating_selection != line.employee_rating_selection
                )
            elif line.manual_scoring_type == "score":
                # If employee score is 0/default but manager changed it to something else, this becomes True.
                line.manager_edited = (line.manager_rating_score is not None) and (
                    line.manager_rating_score != (line.employee_rating_score or 0)
                )
            else:
                line.manager_edited = False

    def _is_percent_unit(self):
        """Use the unit code as the source of truth for percentage KPI lines."""
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    # Trả về thang điểm chuẩn duy nhất của dòng KPI.
    def _get_score_base(self):
        self.ensure_one()
        return self.env["res.config.settings"].get_score_scale_base()

    # Lấy ngưỡng pass/excellent theo thang điểm chuẩn 100.
    def _get_score_thresholds(self):
        self.ensure_one()
        return self.env["res.config.settings"].get_thresholds()

    # Detect whether the line belongs to the normalized 3P tree.
    def _is_normalized_3p_line(self):
        self.ensure_one()
        return self.pillar_code in NORMALIZED_3P_PILLAR_CODES

    # Return the direct children that participate in score roll-up.
    def _get_direct_scoring_children(self):
        self.ensure_one()
        return self.child_line_ids.sorted(lambda line: (line.sequence or 0, line.id or 0))

    # Đọc bộ field snapshot từ template line để lưu cứng vào evaluation line khi khởi tạo.
    def _build_template_snapshot_vals(self, template_line):
        # Với section row, vẫn snapshot nội dung hiển thị nhưng giữ manual subtype rỗng để tránh noise kỹ thuật.
        if template_line.is_section:
            return {
                "key_performance_area": template_line.key_performance_area,
                "pillar_id": template_line.pillar_id.id,
                "description": template_line.description or False,
                "kpi_type": "auto",
                "manual_scoring_type": False,
                "target": 0.0,
                "unit": False,
                "weight": template_line.weight,
                "wipeout_if_child_zero": bool(template_line.wipeout_if_child_zero),
                "data_source_id": False,
                "scoring_formula_id": False,
                "is_auto": False,
            }

        # Với KPI leaf, snapshot toàn bộ cấu hình nghiệp vụ cốt lõi từ template line.
        return {
            "key_performance_area": template_line.key_performance_area,
            "pillar_id": template_line.pillar_id.id,
            "description": template_line.description or False,
            "kpi_type": template_line.kpi_type,
            "manual_scoring_type": template_line.manual_scoring_type,
            "target": template_line.target,
            "unit": template_line.unit.id or False,
            "weight": template_line.weight,
            "wipeout_if_child_zero": bool(template_line.wipeout_if_child_zero),
            "data_source_id": template_line.data_source_id.id or False,
            "scoring_formula_id": template_line.scoring_formula_id.id or False,
            "is_auto": bool(template_line.is_auto),
        }

    # Bổ sung snapshot mặc định từ template line để mọi luồng create đều giữ dữ liệu lịch sử ổn định.
    @api.model
    def _apply_template_snapshot_defaults(self, vals):
        normalized_vals = dict(vals or {})
        template_line_id = normalized_vals.get("kpi_line_id")
        if not template_line_id:
            return normalized_vals

        # Chỉ snapshot khi template line còn tồn tại và caller chưa chủ động ghi đè field tương ứng.
        template_line = (
            self.env["hr.kpi.template.line"].browse(template_line_id).exists()
        )
        if not template_line:
            return normalized_vals

        snapshot_vals = self._build_template_snapshot_vals(template_line)
        for field_name, field_value in snapshot_vals.items():
            normalized_vals.setdefault(field_name, field_value)

        # Giữ thêm template parent link để rebuild hierarchy nội bộ mà không làm evaluation line phụ thuộc động.
        normalized_vals.setdefault(
            "parent_template_line_id",
            template_line.parent_line_id.id or False,
        )
        return normalized_vals

    # Kiểm tra đệ quy xem section hiện tại có bất kỳ KPI leaf hậu duệ nào đang bằng 0 hay không.
    def _has_zero_score_descendant_leaf(self):
        self.ensure_one()

        # Chỉ section có con mới cần quét cây hậu duệ cho rule wipeout mới.
        if not self.is_section or not self.child_line_ids:
            return False

        # Duyệt toàn bộ con trực tiếp theo đúng thứ tự hiển thị để kiểm tra cả cây KPI.
        for child in self._get_direct_scoring_children():
            if child.child_line_ids and child._has_zero_score_descendant_leaf():
                return True
            if not child.child_line_ids and not child.is_section:
                if (child.final_rating or 0.0) <= 0.0:
                    return True
        return False

    # Collect the edited lines and every ancestor whose score depends on them.
    def _get_score_recompute_lines(self):
        lines_to_recompute = self.env["hr.performance.evaluation.line"]
        frontier = self
        while frontier:
            frontier = frontier - lines_to_recompute
            if not frontier:
                break
            lines_to_recompute |= frontier
            frontier = frontier.mapped("parent_line_id")
        return lines_to_recompute

    # Tính lại cây điểm theo thứ tự từ lá lên gốc để parent line cập nhật ngay trong cùng lần lưu.
    def _recompute_score_tree(self):
        if self.env.context.get("skip_score_tree_recompute"):
            return

        lines_to_recompute = self._get_score_recompute_lines()
        if not lines_to_recompute:
            return

        # Guard stored computed-field writes from re-entering this recompute flow.
        guarded_lines = lines_to_recompute.with_context(
            skip_score_tree_recompute=True
        )

        def _depth(line):
            depth = 0
            current = line.parent_line_id
            while current:
                depth += 1
                current = current.parent_line_id
            return depth

        # Recompute deepest lines first so each parent reads the newest child score.
        ordered_lines = guarded_lines.sorted(
            lambda line: (-_depth(line), line.sequence or 0, line.id or 0)
        )
        for line in ordered_lines:
            line._compute_system_score()
            line._compute_final_rating()

        for evaluation in ordered_lines.mapped("evaluation_id"):
            evaluation._compute_pillar_totals()
            evaluation._compute_performance_level()

    def _get_child_score_aggregate(self):
        self.ensure_one()
        child_lines = self._get_direct_scoring_children()
        if not child_lines:
            return False
        total_weight = sum(child_lines.mapped("weight"))
        if total_weight > 0:
            return (
                sum(child.final_rating * child.weight for child in child_lines)
                / total_weight
            )
        return sum(child_lines.mapped("final_rating")) / len(child_lines)

    # Trả về độ sâu hierarchy của evaluation line để roll-up weight section từ lá lên gốc.
    def _get_hierarchy_depth(self):
        self.ensure_one()
        depth = 0
        current = self.parent_line_id
        while current:
            depth += 1
            current = current.parent_line_id
        return depth

    # Tính lại weight cho mọi section line của các phiếu cá nhân bị ảnh hưởng dựa trên direct child hiện tại.
    def _recompute_section_weights(self):
        if self.env.context.get("skip_section_weight_rollup"):
            return

        evaluations = self.mapped("evaluation_id")
        for evaluation in evaluations:
            section_lines = evaluation.evaluation_line_ids.filtered("is_section").sorted(
                lambda line: (
                    -line._get_hierarchy_depth(),
                    line.sequence or 0,
                    line.id or 0,
                )
            )

            # Roll-up section sâu nhất trước để section cha luôn nhìn thấy weight mới nhất của con.
            for section in section_lines:
                direct_children = section.child_line_ids.filtered(
                    lambda line: line.evaluation_id == evaluation
                    and line.pillar_id == section.pillar_id
                )
                child_weight_total = sum(direct_children.mapped("weight"))

                # Ghi nội bộ bằng super write để tránh re-enter luồng refresh và score recompute.
                super(
                    PerformanceEvaluationLine,
                    section.with_context(
                        skip_section_weight_rollup=True,
                        skip_score_tree_recompute=True,
                    ),
                ).write({"weight": child_weight_total})

    # Chỉ giữ ràng buộc không cho weight âm trên evaluation line.
    def _validate_non_negative_weight(self):
        evaluations = self.mapped("evaluation_id")
        for evaluation in evaluations:
            negative_weight_line = evaluation.evaluation_line_ids.filtered(
                lambda line: line.weight < 0.0
            )[:1]
            if negative_weight_line:
                raise ValidationError(_("Weight cannot be negative for KPI lines."))

    # Đồng bộ weight section và validate weight âm cho toàn bộ phiếu cá nhân liên quan.
    def _refresh_weight_structure(self):
        self._recompute_section_weights()
        self._validate_non_negative_weight()

    # Format the target and actual previews only for auto KPI lines.
    @api.depends("target", "actual", "kpi_type", "unit", "unit.code", "unit.name")
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != "auto":
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
                rec.target_display = f"{target} {unit_name}" if unit_name else target
                rec.actual_display = f"{actual} {unit_name}" if unit_name else actual

    # ------------------------------------------------------------------
    # Compute the auto KPI score from Actual, Target, and the effective scoring formula.
    # ------------------------------------------------------------------
    def _compute_system_score_for_line(self, line, actual, target, score_base=None):
        score_base = float(score_base or self._get_score_base() or 0.0)
        formula = line.scoring_formula_id
        if not formula:
            return 0.0
        try:
            score = formula.compute_score(
                actual or 0.0, target or 0.0, max_score=score_base
            )
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
        "manual_scoring_type",
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
        "child_line_ids",
        "child_line_ids.parent_line_id",
        "child_line_ids.final_rating",
        "child_line_ids.weight",
        "wipeout_if_child_zero",
        "scoring_formula_id",
        "scoring_formula_id.formula_type",
        "scoring_formula_id.linear_direction",
        "scoring_formula_id.linear_allow_exceed",
        "scoring_formula_id.step_table_json",
        "scoring_formula_id.step_out_of_range",
        "scoring_formula_id.penalty_deduct_per_unit",
        "scoring_formula_id.penalty_floor",
        "scoring_formula_id.expression_code",
    )
    # Tính điểm dòng KPI theo leaf/manual/auto và áp rule wipeout mới ở section parent khi cần.
    def _compute_system_score(self):
        """
        Compute system_score on the fixed 100-point score scale:

        auto:
          score = scoring_formula.compute_score(actual, target, score_base)

        manual rating:
          score = (rating / 5) * score_base

        manual binary:
          score = score_base when the answer is Yes, otherwise 0
        """
        for line in self:
            if line.evaluation_id.state in ['cancel', 'completed']:
                continue
            score_base = line._get_score_base()
            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            # Nếu section được cấu hình wipeout và có leaf hậu duệ bằng 0 thì ép cả nhánh về 0.
            if line.wipeout_if_child_zero and line._has_zero_score_descendant_leaf():
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

            if line.kpi_type == "auto":
                line.system_score = line._compute_system_score_for_line(
                    line,
                    actual,
                    target,
                    score_base=score_base,
                )
                continue

            elif line.kpi_type == "manual" and line.manual_scoring_type == "rating":
                # Ưu tiên manager nếu đã có, fallback về employee
                raw = (
                    line.manager_rating_selection
                    or line.employee_rating_selection
                    or "0"
                )
                rating = float(raw)
                score = (rating / 5.0) * score_base

            elif line.kpi_type == "manual" and line.manual_scoring_type == "binary":
                # Apply the same score selection rule for manual binary KPI lines.
                val = line.manager_rating_binary or line.employee_rating_binary
                score = score_base if val == "yes" else 0.0

            elif line.kpi_type == "manual" and line.manual_scoring_type == "score":
                # Float 0 is a valid manager score, so do not fall back with `or`.
                val = line.employee_rating_binary if line.manager_rating_score is False else line.manager_rating_score
                score = float(val)

            line.system_score = round(max(0.0, min(score, score_base)), 2)

    # ------------------------------------------------------------------
    # COMPUTE final_rating depends on kpi_type
    # ------------------------------------------------------------------
    @api.depends(
        "kpi_type",
        "manual_scoring_type",
        "system_score",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    # Clamp the final rating to the configured score base after scoring is computed.
    def _compute_final_rating(self):
        for line in self:
            if line.evaluation_id.state in ['cancel', 'completed']:
                continue
            score_base = line._get_score_base()
            line.final_rating = round(
                min(max(line.system_score or 0.0, 0.0), score_base), 2
            )

    @api.depends("final_rating")
    def _compute_final_rating_badge_class(self):
        for line in self:
            excellent, passed = line._get_score_thresholds()
            score = line.final_rating or 0.0
            if score >= excellent:
                line.final_rating_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                line.final_rating_badge_class = "o_kpi_badge_pass"
            else:
                line.final_rating_badge_class = "o_kpi_badge_fail"

    @api.depends("final_rating")
    def _compute_final_rating_badge_text(self):
        for line in self:
            score_base = line._get_score_base()
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
    #     self.employee_rating_binary = False
    #     self.manager_rating_binary = False
    #     self.employee_rating_selection = False
    #     self.manager_rating_selection = False
    #     self.employee_rating_score = 0
    #     self.manager_rating_score = 0

    @api.onchange(
        "employee_rating_binary",
        "employee_rating_selection",
        "employee_rating_score",
        "manual_scoring_type",
    )
    # Mirror the employee manual rating into manager fields during self evaluation.
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
            self._recompute_score_tree()
            return

        for line in self:
            if (
                line.kpi_type == "manual"
                and line.manual_scoring_type == "binary"
                and line.employee_rating_binary
            ):
                line.manager_rating_binary = line.employee_rating_binary
            elif (
                line.kpi_type == "manual"
                and line.manual_scoring_type == "rating"
                and line.employee_rating_selection
            ):
                line.manager_rating_selection = line.employee_rating_selection
            elif (
                line.kpi_type == "manual"
                and line.manual_scoring_type == "score"
                and line.employee_rating_score is not None
            ):
                line.manager_rating_score = line.employee_rating_score
        self._recompute_score_tree()

    @api.onchange(
        "actual",
        "target",
        "weight",
        "parent_line_id",
        "kpi_type",
        "manual_scoring_type",
        "manager_rating_binary",
        "manager_rating_selection",
        "manager_rating_score",
    )
    # Recompute the score tree in-memory so parent rows update on the first edit.
    def _onchange_recompute_score_tree(self):
        self._recompute_score_tree()

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    # Keep manual subtype required for manual lines and empty for auto lines.
    @api.constrains("kpi_type", "manual_scoring_type")
    def _check_manual_scoring_type(self):
        for rec in self:
            if rec.is_section or rec.display_type:
                continue
            if rec.kpi_type == "manual" and not rec.manual_scoring_type:
                raise ValidationError(get_manual_scoring_type_required_message())
            if rec.kpi_type == "auto" and rec.manual_scoring_type:
                raise ValidationError(
                    _("Manual scoring type must be empty for auto KPI lines.")
                )

    # Validate the manager rating selection only for rating-based manual KPI lines.
    @api.constrains("manager_rating_selection", "kpi_type", "manual_scoring_type")
    def _check_manager_rating_selection_range(self):
        for rec in self:
            if rec.kpi_type == "manual" and rec.manual_scoring_type == "rating":
                if (
                    rec.manager_rating_selection
                    and rec.manager_rating_selection not in dict(self._RATING_0_5)
                ):
                    raise ValidationError(
                        _("Manager rating selection must be between 0 and 5.")
                    )

    # Validate manual score inputs against the configured score base.
    @api.constrains(
        "employee_rating_score",
        "manager_rating_score",
        "kpi_type",
        "manual_scoring_type",
    )
    def _check_manual_score_range(self):
        for rec in self:
            if rec.kpi_type != "manual" or rec.manual_scoring_type != "score":
                continue

            score_base = rec._get_score_base()
            if not 0 <= (rec.employee_rating_score or 0.0) <= score_base:
                raise ValidationError(
                    _("Employee score must be between 0 and %(max_score)s.")
                    % {"max_score": f"{score_base:g}"}
                )
            if not 0 <= (rec.manager_rating_score or 0.0) <= score_base:
                raise ValidationError(
                    _("Manager score must be between 0 and %(max_score)s.")
                    % {"max_score": f"{score_base:g}"}
                )

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
                raise ValidationError(_("Recursive KPI line hierarchy is not allowed."))

    # Mirror employee manual ratings into manager fields during self evaluation saves.
    def _mirror_employee_to_manager_vals(self, vals, vals_before=None):
        """Mirror employee self-rating into manager rating on self evaluation evaluations.

        Onchange only updates in memory; without this, manager fields revert after save/reload.
        """
        vals = dict(vals or {})
        vals_before = dict(vals_before or vals)
        for line in self:
            if line.evaluation_id and line.evaluation_id.state != "self_evaluation":
                continue
            effective_kpi_type = vals.get("kpi_type", line.kpi_type)
            effective_manual_type = vals.get(
                "manual_scoring_type", line.manual_scoring_type
            )
            if (
                effective_kpi_type == "manual"
                and effective_manual_type == "binary"
                and "employee_rating_binary" in vals_before
            ):
                vals.setdefault(
                    "manager_rating_binary", vals_before.get("employee_rating_binary")
                )
            elif (
                effective_kpi_type == "manual"
                and effective_manual_type == "rating"
                and "employee_rating_selection" in vals_before
            ):
                vals.setdefault(
                    "manager_rating_selection",
                    vals_before.get("employee_rating_selection"),
                )
            elif (
                effective_kpi_type == "manual"
                and effective_manual_type == "score"
                and "employee_rating_score" in vals_before
            ):
                vals.setdefault(
                    "manager_rating_score", vals_before.get("employee_rating_score")
                )
        return vals

    # Keep section consistency, normalize KPI type values, and append new lines by sequence.
    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            normalized_vals_list.append(self._apply_template_snapshot_defaults(vals))
        vals_list = normalized_vals_list

        seq_step = 10
        default_pillar_code = self.env.context.get("default_pillar_code")
        default_pillar = False
        if default_pillar_code:
            default_pillar = self.env["hr.evaluation.pillar"].sudo().search(
                [("code", "=", default_pillar_code)],
                limit=1,
            )

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
            if default_pillar and not vals.get("pillar_id"):
                vals["pillar_id"] = default_pillar.id
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
            manual_scoring_type = vals.get("manual_scoring_type")
            if (
                kpi_type == "manual"
                and manual_scoring_type == "binary"
                and "employee_rating_binary" in vals
            ):
                vals.setdefault(
                    "manager_rating_binary", vals.get("employee_rating_binary")
                )
            elif (
                kpi_type == "manual"
                and manual_scoring_type == "rating"
                and "employee_rating_selection" in vals
            ):
                vals.setdefault(
                    "manager_rating_selection", vals.get("employee_rating_selection")
                )
            elif (
                kpi_type == "manual"
                and manual_scoring_type == "score"
                and "employee_rating_score" in vals
            ):
                vals.setdefault(
                    "manager_rating_score", vals.get("employee_rating_score")
                )

        records = super().create(vals_list)
        affected_lines = records | records.mapped("parent_line_id")
        affected_lines._refresh_weight_structure()
        affected_lines._recompute_score_tree()
        return records

    # Normalize KPI type values, keep section consistency, and protect writes by role/state.
    def write(self, vals):
        # Internal stored computed-field writes must not restart the score tree.
        if self.env.context.get("skip_score_tree_recompute"):
            return super().write(vals)

        # Keep section rows technically consistent even when only display_type is changed.
        if vals.get("display_type") and "is_section" not in vals:
            vals = dict(vals, is_section=True)

        evaluations_before = self.mapped("evaluation_id")
        parent_lines_before = self.mapped("parent_line_id")

        # Capture the original values before any self-rating mirror logic modifies them.
        vals_before = dict(vals or {})
        tracked_fields = self._get_chatter_tracked_fields(vals_before)
        snapshot_by_line = (
            self._snapshot_chatter_tracked_values(tracked_fields)
            if tracked_fields
            else {}
        )

        # Mirror employee manual ratings into manager fields during self evaluation saves.
        vals = self._mirror_employee_to_manager_vals(vals, vals_before=vals_before)

        res = super().write(vals)
        affected_lines = self | parent_lines_before | self.mapped("parent_line_id")
        affected_lines._refresh_weight_structure()
        affected_lines._recompute_score_tree()

        # Refresh an old evaluation when a line is moved to another evaluation.
        old_evaluations = evaluations_before - self.mapped("evaluation_id")
        for evaluation in old_evaluations:
            evaluation._compute_pillar_totals()
            evaluation._compute_performance_level()
        if snapshot_by_line:
            self._post_parent_chatter_audit(tracked_fields, snapshot_by_line)
        return res

    # Đồng bộ lại weight section và score tree sau khi xóa line khỏi phiếu cá nhân.
    def unlink(self):
        evaluations = self.mapped("evaluation_id")
        parent_lines = self.mapped("parent_line_id")
        res = super().unlink()
        affected_lines = evaluations.mapped("evaluation_line_ids") | parent_lines
        if affected_lines:
            affected_lines._refresh_weight_structure()
            affected_lines._recompute_score_tree()
        else:
            evaluations._compute_pillar_totals()
            evaluations._compute_performance_level()
        return res

    def action_open_popup(self):
        self.ensure_one()
        return {
            "name": _("KPI Line Detail"),
            "type": "ir.actions.act_window",
            "res_model": "hr.performance.evaluation.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_performance_evaluation_line_form_popup"
            ).id,
            "target": "new",
        }
