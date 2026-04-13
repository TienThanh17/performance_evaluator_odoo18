from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PerformanceEvaluationLine(models.Model):
    _name = 'hr.performance.evaluation.line'
    _description = 'Performance Evaluation Line'
    _order = 'sequence, id'

    # ------------------------------------------------------------
    # Section / ordering (to work with kpi_one2many widget)
    # ------------------------------------------------------------
    is_section = fields.Boolean(
        string="Is Section",
        default=False,
        help="Enable this to make the line a Section header. Sections are used for grouping and do not affect scoring.",
    )
    display_type = fields.Selection(
        selection=[
            ('line_section', 'Section'),
            ('line_note', 'Note'),
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

    # Optional: keep a backlink to the KPI template line that generated this evaluation line.
    # This makes the mapping explicit and allows future sync/update.
    kpi_line_id = fields.Many2one(
        'hr.kpi.line',
        string='KPI Template Line',
        ondelete='set null',
        index=True,
        help="The KPI template line this evaluation line comes from (for traceability).",
    )

    evaluation_id = fields.Many2one(
        'hr.performance.evaluation',
        string="Performance Evaluation",
        ondelete='cascade',
        help="The evaluation record that this line belongs to.",
    )
    evaluation_state = fields.Selection(
        related='evaluation_id.state',
        string='Evaluation State',
        store=False,
        help="Current workflow state of the parent evaluation.",
    )
    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
        help="The KPI title (or the section header name if this is a Section).",
    )
    kpi_type = fields.Selection(
        selection=[
            ('quantitative', 'Quantitative'),
            ('binary', 'Binary'),
            ('rating', 'Rating'),
            ('score', 'Score'),
        ],
        string='KPI Type',
        default='quantitative',
        required=True,
        help="How this KPI line is evaluated: Quantitative (Target vs Actual), Binary (Yes/No), Rating (0–5), or Score (0–10).",
    )

    target_type = fields.Selection(
        selection=[
            ('value', 'Value'),
            ('percentage', 'Percentage'),
        ],
        string='Target Type',
        required=True,
        default='value',
        help="Controls the unit for Target/Actual. If Percentage, values are 0–100.",
    )
    direction = fields.Selection(
        selection=[
            ('higher_better', 'Higher is Better'),
            ('lower_better', 'Lower is Better'),
        ],
        string='Direction',
        default='higher_better',
        required=True,
        help="For Quantitative KPIs: choose whether a higher actual value is better or a lower actual value is better.",
    )
    target = fields.Float(
        string='Target',
        default=0.0,
        help="Target value to be achieved for Quantitative KPIs.",
    )
    weight = fields.Float(
        string="Weight",
        default=0.0,
        help="Weight of this KPI in the overall evaluation (higher weight has more impact).",
    )

    is_auto = fields.Boolean(
        string='Auto Compute',
        default=False,
        help="Enable to let the system compute the Actual value automatically from the selected Data Source.",
    )

    data_source = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('task_on_time', 'Task On Time'),
            ('late_days', 'Late Days'),
            ('attendance_full', 'Attendance Full'),
        ],
        string='Data Source',
        default='manual',
        required=True,
        help="Copied from KPI template line when generating evaluation lines.",
    )

    # ------------------------------------------------------------
    # Auto KPI: attendance_full metrics (used for special scoring)
    # ------------------------------------------------------------
    attendance_worked_days = fields.Float(
        string="Worked Days",
        default=0.0,
        help="Attendance Full metric: number of distinct days with at least one check-in.",
    )
    attendance_expected_days = fields.Float(
        string="Expected Work Days",
        default=0.0,
        help="Attendance Full metric: expected work days from working schedule.",
    )
    attendance_leave_days = fields.Float(
        string="Leave Days",
        default=0.0,
        help="Attendance Full metric: expected days minus worked days (clamped at 0).",
    )
    attendance_approved_leave_days = fields.Float(
        string="Approved Leave Days",
        default=0.0,
        help="Attendance Full metric: validated leave days overlapping the evaluation period.",
    )
    attendance_has_unpaid_leave = fields.Boolean(
        string="Has Unpaid Leave",
        default=False,
        help="Attendance Full metric: True if leave days exceed approved leave days.",
    )

    # actual: giá trị canonical dùng để tính system_score
    #   - kpi_type=quantitative: so sánh target vs actual theo direction
    #   - target_type quyết định đơn vị (value vs percentage 0–100)
    actual = fields.Float(
        string="Actual",
        help="Actual value input/collected for Quantitative KPIs. Compared against Target to compute the System Score.",
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
        help="System-calculated score (0–10) based on rules for the selected KPI type.",
    )

    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=False,
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
    _BINARY_YN = [('yes', 'Yes'), ('no', 'No')]
    employee_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Employee Rating (Binary)",
        help="Employee self-assessment for Binary KPIs (Yes/No).",
    )
    manager_rating_binary = fields.Selection(
        selection=_BINARY_YN,
        string="Manager Rating (Binary)",
        help="Manager assessment for Binary KPIs (Yes/No).",
    )

    # Rating: 0..5 selection.
    _RATING_0_5 = [('0', '0'), ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')]
    employee_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Employee Rating (0-5)",
        help="Employee self-assessment for Rating KPIs (0–5).",
    )
    manager_rating_selection = fields.Selection(
        selection=_RATING_0_5,
        string="Manager Rating (0-5)",
        help="Manager assessment for Rating KPIs (0–5).",
    )

    # Score KPI: employee self score and manager final score (0..10)
    employee_rating_score = fields.Integer(
        string="Employee Rating (Score)",
        default=0,
        help="Employee self-assessment score for Score KPIs (0–10).",
    )
    manager_rating_score = fields.Integer(
        string="Manager Rating (Score)",
        default=0,
        help="Manager score for Score KPIs (0–10).",
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
        string="Final Rating", compute='_compute_final_rating', store=True, digits=(16, 1)
        , help="Final rating (0–10) used in the evaluation summary.",
    )

    final_rating_badge_text = fields.Char(
        string="Final Rating",
        compute="_compute_final_rating_badge_text",
        store=False,
        help="Always-formatted text for UI badge rendering (keeps 0.0 visible).",
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

    # ------------------------------------------------------------
    # UX helper: identify current user's role (manager group)
    # ------------------------------------------------------------
    is_evaluation_manager = fields.Boolean(
        string="Is Evaluation Manager",
        compute="_compute_is_evaluation_manager",
        store=False,
        help="Technical helper used by the UI to apply role-based readonly rules.",
    )

    @api.depends_context('uid')
    def _compute_is_evaluation_manager(self):
        is_manager = self.env.user.has_group('custom_adecsol_hr_performance_evaluator.group_evaluation_manager')
        for rec in self:
            rec.is_evaluation_manager = is_manager

    @api.depends('kpi_type', 'data_source')
    def _compute_is_special_scoring(self):
        special_sources = {'late_days', 'attendance_full'}
        for rec in self:
            rec.is_special_scoring = bool(
                rec.kpi_type == 'quantitative' and (rec.data_source in special_sources)
            )

    @api.depends('is_section')
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = 'line_section' if rec.is_section else False

    @api.depends(
        'kpi_type',
        'employee_rating_binary', 'employee_rating_selection', 'employee_rating_score',
        'manager_rating_binary', 'manager_rating_selection', 'manager_rating_score',
    )
    def _compute_manager_edited(self):
        for line in self:
            if line.kpi_type == 'binary':
                line.manager_edited = bool(line.manager_rating_binary) and (
                            line.manager_rating_binary != line.employee_rating_binary)
            elif line.kpi_type == 'rating':
                line.manager_edited = bool(line.manager_rating_selection) and (
                            line.manager_rating_selection != line.employee_rating_selection)
            elif line.kpi_type == 'score':
                # If employee score is 0/default but manager changed it to something else, this becomes True.
                line.manager_edited = (line.manager_rating_score is not None) and (
                            line.manager_rating_score != (line.employee_rating_score or 0))
            else:
                # quantitative: manager doesn't rate in current logic
                line.manager_edited = False

    @api.depends('target', 'actual', 'target_type', 'kpi_type')
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != 'quantitative':
                rec.target_display = ''
                rec.actual_display = ''
                continue

            if rec.target_type == 'percentage':
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
                rec.actual_display = f"{(rec.actual or 0.0):g}%"
            else:
                rec.target_display = f"{(rec.target or 0.0):g}"
                rec.actual_display = f"{(rec.actual or 0.0):g}"

    # @api.onchange('target_type')
    # def _onchange_target_type(self):
    #     for rec in self:
    #         if rec._origin.target_type and rec._origin.target_type != rec.target_type:
    #             rec.target = 0.0

    # ------------------------------------------------------------------
    # COMPUTE system_score: depends vào actual + các field liên quan
    # ------------------------------------------------------------------
    @api.depends(
        'actual', 'target', 'kpi_type', 'direction',
        'employee_rating_binary', 'employee_rating_selection', 'employee_rating_score',
        'manager_rating_binary', 'manager_rating_selection', 'manager_rating_score',
        'data_source',
        'attendance_has_unpaid_leave', 'attendance_leave_days',
    )
    def _compute_system_score(self):
        """
        Tính system_score (thang 0–10) theo từng kpi_type:

        quantitative:
          higher_better: score = (actual / target) * 10
          lower_better:  score = (target / actual) * 10

        rating:
          actual = 0–5 (từ rating_value)
          → score = (actual / 5) * 10

        binary:
          actual = target (achieved) hoặc 0 (not achieved)
          → score = 10 nếu actual >= target > 0, ngược lại = 0
        """
        for line in self:
            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            if line.kpi_type == 'quantitative':
                # Special case: attendance late days KPI uses a penalty-based scoring.
                # - 0 late days -> 10
                # - each late day -> -2
                # - >5 late days -> 0
                if (line.data_source or 'manual') == 'late_days':
                    late_days = int(round(actual)) if actual else 0
                    if late_days > 5:
                        score = 0.0
                    else:
                        score = 10.0 - (late_days * 2.0)
                        score = max(0.0, score)
                    line.system_score = round(max(0.0, min(score, 10.0)), 2)
                    continue

                # Special case: attendance full KPI uses leave-days based scoring.
                # Rule:
                #   unpaid leave -> 0
                #   0 leave days -> 10
                #   1 -> 9, 2 -> 8, 3 -> 7, 4 -> 6, 5 -> 5, else 0
                if (line.data_source or 'manual') == 'attendance_full':
                    if line.attendance_has_unpaid_leave:
                        score = 0.0
                    else:
                        leave_days = int(round(line.attendance_leave_days or 0.0))
                        if leave_days <= 0:
                            score = 10.0
                        elif leave_days == 1:
                            score = 9.0
                        elif leave_days == 2:
                            score = 8.0
                        elif leave_days == 3:
                            score = 7.0
                        elif leave_days == 4:
                            score = 6.0
                        elif leave_days == 5:
                            score = 5.0
                        else:
                            score = 0.0
                    line.system_score = round(max(0.0, min(score, 10.0)), 2)
                    continue

                # Target vs Actual scoring, works for both value and percentage (same unit).
                if target <= 0:
                    line.system_score = 0.0
                    continue

                if line.direction == 'higher_better':
                    score_ratio = actual / target
                else:
                    score_ratio = (target / actual) if actual > 0 else 0.0

                score = min(score_ratio * 10.0, 10.0)

            elif line.kpi_type == 'rating':
                # ✅ Ưu tiên manager nếu đã có, fallback về employee
                raw = line.manager_rating_selection or line.employee_rating_selection or '0'
                rating = float(raw)
                score = (rating / 5.0) * 10.0

            elif line.kpi_type == 'binary':
                # ✅ Tương tự cho binary
                val = line.manager_rating_binary or line.employee_rating_binary
                score = 10.0 if val == 'yes' else 0.0

            elif line.kpi_type == 'score':
                # ✅ Tương tự cho score
                val = line.manager_rating_score or line.employee_rating_score or 0
                score = float(val)

            line.system_score = round(max(0.0, min(score, 10.0)), 2)

    # ------------------------------------------------------------------
    # COMPUTE final_rating depends on kpi_type
    # ------------------------------------------------------------------
    @api.depends('kpi_type', 'system_score', 'manager_rating_binary', 'manager_rating_selection',
                 'manager_rating_score')
    def _compute_final_rating(self):
        for line in self:
            if line.kpi_type == 'quantitative':
                line.final_rating = round(max(0.0, min(line.system_score or 0.0, 10.0)), 2)
            elif line.kpi_type == 'binary':
                line.final_rating = 10.0 if (line.manager_rating_binary == 'yes') else 0.0
            elif line.kpi_type == 'rating':
                sel = float(line.manager_rating_selection or '0')
                line.final_rating = round((sel / 5.0) * 10.0, 2)
            else:
                # score (and any future non-quantitative types): fallback to system_score
                line.final_rating = round(max(0.0, min(line.system_score or 0.0, 10.0)), 2)

    def _get_thresholds(self):
        """Fetch KPI thresholds from system parameters."""
        icp = self.env['ir.config_parameter'].sudo()
        excellent = float(
            icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent', default='9') or 9.0)
        passed = float(icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_pass', default='5') or 5.0)
        return excellent, passed

    @api.depends('final_rating')
    def _compute_final_rating_badge_class(self):
        excellent, passed = self._get_thresholds()
        for line in self:
            score = line.final_rating or 0.0
            if score >= excellent:
                line.final_rating_badge_class = 'o_kpi_badge_excellent'
            elif score >= passed:
                line.final_rating_badge_class = 'o_kpi_badge_pass'
            else:
                line.final_rating_badge_class = 'o_kpi_badge_fail'

    @api.depends('final_rating')
    def _compute_final_rating_badge_text(self):
        for line in self:
            # Always show a value, including 0.0, with exactly 1 decimal.
            line.final_rating_badge_text = f"{(line.final_rating or 0.0):.1f}"

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

    @api.onchange('employee_rating_binary', 'employee_rating_selection', 'employee_rating_score')
    def _onchange_employee_rating_autofill_manager(self):
        """In draft state, mirror employee self-rating into manager rating.

        Purpose: allow employees to see current final_rating and the evaluation average in real time,
        without waiting for the Submit action.

        Notes:
        - This is an onchange-only UX helper. Real security is enforced in write().
        - We only mirror while the parent evaluation is in draft.
        """
        # New (unsaved) one2many lines might not have evaluation_id yet in some cases.
        if self.evaluation_id and self.evaluation_id.state != 'draft':
            return

        for line in self:
            if line.kpi_type == 'binary' and line.employee_rating_binary:
                line.manager_rating_binary = line.employee_rating_binary
            elif line.kpi_type == 'rating' and line.employee_rating_selection:
                line.manager_rating_selection = line.employee_rating_selection
            elif line.kpi_type == 'score' and line.employee_rating_score is not None:
                line.manager_rating_score = line.employee_rating_score

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('actual', 'target_type')
    def _check_actual_matches_target_type(self):
        for rec in self:
            if rec.target_type == 'percentage':
                if (rec.actual or 0.0) < 0 or (rec.actual or 0.0) > 100:
                    raise ValidationError("Actual must be between 0 and 100 for percentage KPIs")

    @api.constrains('manager_rating_selection', 'kpi_type')
    def _check_manager_rating_selection_range(self):
        for rec in self:
            if rec.kpi_type == 'rating':
                if rec.manager_rating_selection and rec.manager_rating_selection not in dict(self._RATING_0_5):
                    raise ValidationError("Manager rating selection must be between 0 and 5.")

    @api.constrains('employee_rating_score', 'manager_rating_score', 'kpi_type')
    def _check_score_range(self):
        for rec in self:
            if rec.kpi_type == 'score':
                if not 0 <= (rec.employee_rating_score or 0) <= 10:
                    raise ValidationError("Employee score must be between 0 and 10.")
                if not 0 <= (rec.manager_rating_score or 0) <= 10:
                    raise ValidationError("Manager score must be between 0 and 10.")

    @api.constrains('employee_rating_value', 'manager_rating_value')
    def _check_value_ratings_range(self):
        for rec in self:
            if rec.employee_rating_value is not None and not 0.0 <= rec.employee_rating_value <= 10.0:
                raise ValidationError("Employee rating value must be between 0 and 10.")
            if rec.manager_rating_value is not None and not 0.0 <= rec.manager_rating_value <= 10.0:
                raise ValidationError("Manager rating value must be between 0 and 10.")

    def _mirror_employee_to_manager_vals(self, vals, vals_before=None):
        """Mirror employee self-rating into manager rating on draft evaluations.

        Onchange only updates in memory; without this, manager fields revert after save/reload.
        """
        vals = dict(vals or {})
        vals_before = dict(vals_before or vals)
        for line in self:
            if line.evaluation_id and line.evaluation_id.state != 'draft':
                continue
            if line.kpi_type == 'binary' and 'employee_rating_binary' in vals_before:
                vals.setdefault('manager_rating_binary', vals_before.get('employee_rating_binary'))
            elif line.kpi_type == 'rating' and 'employee_rating_selection' in vals_before:
                vals.setdefault('manager_rating_selection', vals_before.get('employee_rating_selection'))
            elif line.kpi_type == 'score' and 'employee_rating_score' in vals_before:
                vals.setdefault('manager_rating_score', vals_before.get('employee_rating_score'))
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        """Keep section consistency and append new lines by sequence when not provided."""
        seq_step = 10

        eval_ids = {vals.get('evaluation_id') for vals in vals_list if vals.get('evaluation_id')}
        max_seq_by_eval = {}
        if eval_ids:
            lines = self.search_read(
                [('evaluation_id', 'in', list(eval_ids))],
                ['evaluation_id', 'sequence'],
                order='sequence desc',
            )
            for l in lines:
                eid = l['evaluation_id'][0] if l.get('evaluation_id') else False
                if eid and eid not in max_seq_by_eval:
                    max_seq_by_eval[eid] = l.get('sequence') or 0

        for vals in vals_list:
            if vals.get('display_type') and 'is_section' not in vals:
                vals['is_section'] = True

            evaluation_id = vals.get('evaluation_id')
            if evaluation_id and not vals.get('sequence'):
                current_max = max_seq_by_eval.get(evaluation_id)
                if current_max is None:
                    current_max = 0
                vals['sequence'] = current_max + seq_step
                max_seq_by_eval[evaluation_id] = vals['sequence']

            # Add: mirror employee->manager at create time too
            kpi_type = vals.get('kpi_type')
            if kpi_type == 'binary' and 'employee_rating_binary' in vals:
                vals.setdefault('manager_rating_binary', vals.get('employee_rating_binary'))
            elif kpi_type == 'rating' and 'employee_rating_selection' in vals:
                vals.setdefault('manager_rating_selection', vals.get('employee_rating_selection'))
            elif kpi_type == 'score' and 'employee_rating_score' in vals:
                vals.setdefault('manager_rating_score', vals.get('employee_rating_score'))

        return super().create(vals_list)

    def write(self, vals):
        # Keep section consistency
        if vals.get('display_type') and 'is_section' not in vals:
            vals = dict(vals, is_section=True)

        vals_before = dict(vals or {})
        vals = self._mirror_employee_to_manager_vals(vals, vals_before=vals_before)

        # If called in sudo/superuser context, skip custom field-level restrictions.
        if self.env.is_superuser():
            return super().write(vals)

        user = self.env.user

        # Prevent edits on canceled evaluations for everybody.
        if any(line.evaluation_id.state == 'cancel' for line in self):
            raise UserError("You cannot modify lines of a canceled evaluation.")

        is_manager = user.has_group('custom_adecsol_hr_performance_evaluator.group_evaluation_manager')
        is_employee = user.has_group('custom_adecsol_hr_performance_evaluator.group_evaluation_user')

        # Employee cannot edit manager fields (except mirrored ones in draft).
        if is_employee and not is_manager:
            forbidden = {
                'manager_rating_value', 'manager_rating_binary', 'manager_rating_selection', 'manager_rating_score',
                'manager_comment',
            }
            allowed_manager_fields = set()
            if any(line.evaluation_id and line.evaluation_id.state == 'draft' for line in self):
                if 'employee_rating_binary' in vals_before:
                    allowed_manager_fields.add('manager_rating_binary')
                if 'employee_rating_selection' in vals_before:
                    allowed_manager_fields.add('manager_rating_selection')
                if 'employee_rating_score' in vals_before:
                    allowed_manager_fields.add('manager_rating_score')

            effective_forbidden = forbidden.intersection(vals.keys()) - allowed_manager_fields
            if effective_forbidden:
                raise UserError("You are not allowed to edit manager fields.")

            # Employee can only edit in Draft.
            if any(line.evaluation_id.state != 'draft' for line in self):
                raise UserError("You can only edit your evaluation in Draft state.")

        # Manager should not change employee self fields.
        if is_manager and not is_employee:
            if {
                'employee_rating_value', 'employee_rating_binary', 'employee_rating_selection',
                'employee_rating_score', 'employee_comment',
            }.intersection(vals.keys()):
                raise UserError("Managers are not allowed to edit employee self-rating/comments.")

            # Manager rating only in Submitted.
            if any(line.evaluation_id.state != 'submitted' for line in self):
                if {
                    'manager_rating_value', 'manager_rating_binary', 'manager_rating_selection',
                    'manager_rating_score', 'manager_comment',
                }.intersection(vals.keys()):
                    raise UserError("Manager rating is only editable in Submitted state.")

        return super().write(vals)
