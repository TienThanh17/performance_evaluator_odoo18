from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class PerformanceEvaluation(models.Model):
    _name = "hr.performance.evaluation"
    _description = "Performance Evaluation"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        help="The user who created this evaluation record.",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        help="The employee being evaluated.",
    )
    kpi_id = fields.Many2one(
        "hr.kpi",
        string="KPI",
        required=False,
        domain="[('period', '=', period), ('department_id', '=', department_id)]",
        help="KPI template used to generate evaluation lines.",
    )
    period = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("half_yearly", "Half-Yearly"),
            ("yearly", "Yearly"),
        ],
        string="Evaluation Period",
        required=True,
        help="Select the evaluation cycle. The KPI template lines enabled for this period will be added to the evaluation.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("cancel", "Canceled"),
        ],
        default="draft",
        string="State",
        help="Workflow stage of the evaluation (Draft → Submitted → Approved). Canceled evaluations are locked.",
    )
    start_date = fields.Date(
        string="Start Date", help="Start date of the evaluation period."
    )
    end_date = fields.Date(string="End Date", help="End date of the evaluation period.")
    deadline = fields.Date(
        string="Deadline", help="Deadline for submitting the self-evaluation."
    )
    evaluation_line_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "evaluation_id",
        string="Evaluation Lines",
        help="The KPI lines to be evaluated for this employee (generated from the KPI template and editable based on roles).",
    )
    name = fields.Char(string="Reference", readonly=True)
    performance_score = fields.Float(
        string="Average Score",
        compute="_compute_performance_score",
        store=True,
        aggregator="avg",
        digits=(16, 1),
        help="Overall score of the evaluation (weighted average of all KPI line final ratings).",
    )

    performance_level = fields.Selection(
        selection=[
            ("excellent", "Excellent"),
            ("pass", "Pass"),
            ("fail", "Fail"),
        ],
        string="Result",
        compute="_compute_performance_level",
        store=True,
        help="Result level derived from the Average Score and the KPI thresholds configured in Settings.",
    )

    performance_badge_class = fields.Char(
        string="Performance Badge Class",
        compute="_compute_performance_badge_class",
        store=False,
        help="Technical field used by the UI to colorize the performance score/level.",
    )
    evaluation_alert_id = fields.Many2one(
        "evaluation.alert",
        string="Evaluation Alert",
        domain=[("active", "=", True)],
        required=True,
        help="Defines the active evaluation window (start/end/deadline) for the selected period.",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        compute="_compute_employee_info",
        store=True,
        readonly=True,
        help="The employee's department (filled automatically).",
    )
    manager_id = fields.Many2one(
        "hr.employee",
        string="Manager",
        compute="_compute_employee_info",
        store=True,
        readonly=True,
        help="The employee's manager (filled automatically).",
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        compute="_compute_employee_info",
        store=True,
        readonly=True,
        help="The employee's job position (filled automatically).",
    )

    performance_visual = fields.Html(compute="_compute_performance_visual")

    @api.depends("performance_score", "employee_id")
    def _compute_performance_visual(self):
        for rec in self:
            # Giả sử điểm tối đa là 10, quy đổi ra % (1-100)
            score_pct = (rec.performance_score or 0) * 10

            # Lấy URL ảnh nhân viên
            img_url = (
                f"/web/image/hr.employee/{rec.employee_id.id}/image_128"
                if rec.employee_id
                else "/custom_adecsol_hr_performance_evaluator/static/description/default-avatar.png"
            )

            # Tạo HTML string với các class CSS mới để hỗ trợ responsive thay vì fixed width
            rec.performance_visual = f"""
                    <div class="d-flex flex-column align-items-center justify-content-center p-3 w-100">
                        <div class="o_performance_visual_wrapper" style="background: conic-gradient(#0056b3 {score_pct}%, #e9ecef 0);">
                            <div class="o_performance_visual_inner">
                                <img src="{img_url}" alt="Employee Avatar"/>
                            </div>
                        </div>
                    </div>
                """

    @api.constrains("period", "evaluation_alert_id")
    def _check_period_active(self):
        for record in self:
            matching_alerts = self.env["evaluation.alert"].search(
                [("active", "=", True), ("period", "=", record.period)]
            )
            if not matching_alerts:
                raise ValidationError(
                    f"The selected period '{record.period}' is not valid for any active evaluation alert. "
                    f"Please ensure there is at least one active alert with this period."
                )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_alert = self.env["evaluation.alert"].search(
            [("active", "=", True)], limit=1
        )
        if active_alert:
            defaults.update(
                {
                    "evaluation_alert_id": active_alert.id,
                    "start_date": active_alert.start_date,
                    "end_date": active_alert.end_date,
                    "deadline": active_alert.deadline,
                    "period": active_alert.period,
                }
            )
        return defaults

    def action_submit(self):
        for record in self:
            if record.state != "draft":
                raise UserError("You can only submit evaluations in draft state.")

            lines = record.evaluation_line_ids.filtered(
                lambda l: (
                    (l.kpi_type != "quantitative")
                    and (not l.is_auto)
                    and (not l.is_section)
                )
            )

            # Validate self input before submit for non-quantitative manual KPIs
            missing_binary = lines.filtered(
                lambda l: l.kpi_type == "binary" and not l.employee_rating_binary
            )
            if missing_binary:
                raise ValidationError(
                    "Please answer all Binary KPI lines before submit."
                )

            missing_rating = lines.filtered(
                lambda l: l.kpi_type == "rating" and not l.employee_rating_selection
            )
            if missing_rating:
                missing_rating.write({'employee_rating_selection': '0'})

            missing_score = lines.filtered(
                lambda l: l.kpi_type == "score" and l.employee_rating_score is None
            )
            if missing_score:
                raise ValidationError(
                    "Please provide Employee Score for all Score KPI lines before submit."
                )

            record.state = "submitted"

    def action_approve(self):
        for record in self:
            if record.state != "submitted":
                raise UserError("You can only approve evaluations in submitted state.")
            record.state = "approved"

    def action_cancel(self):
        for record in self:
            if record.state == "cancel":
                continue
            record.state = "cancel"

    @api.depends("evaluation_line_ids.final_rating", "evaluation_line_ids.weight")
    def _compute_performance_score(self):
        for record in self:
            total_weighted_score_sum = sum(
                line.final_rating * line.weight for line in record.evaluation_line_ids
            )
            total_weight_sum = sum(line.weight for line in record.evaluation_line_ids)
            record.performance_score = (
                total_weighted_score_sum / total_weight_sum if total_weight_sum else 0.0
            )

    def action_recompute_performance_score(self):
        """Manual refresh for performance_score to reflect current evaluation lines.

        Useful after adding/removing lines so users can refresh the summary on demand.
        """
        # Recompute from python side and write stored value.
        for rec in self:
            rec._compute_performance_score()
        return True

    def _get_thresholds(self):
        """Fetch KPI thresholds from system parameters."""
        icp = self.env["ir.config_parameter"].sudo()
        excellent = float(
            icp.get_param(
                "custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent",
                default="9",
            )
            or 9.0
        )
        passed = float(
            icp.get_param(
                "custom_adecsol_hr_performance_evaluator.kpi_threshold_pass",
                default="5",
            )
            or 5.0
        )
        return excellent, passed

    @api.depends("performance_score")
    def _compute_performance_badge_class(self):
        excellent, passed = self._get_thresholds()
        for rec in self:
            score = rec.performance_score or 0.0
            if score >= excellent:
                rec.performance_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                rec.performance_badge_class = "o_kpi_badge_pass"
            else:
                rec.performance_badge_class = "o_kpi_badge_fail"

    @api.depends("performance_score")
    def _compute_performance_level(self):
        excellent, passed = self._get_thresholds()
        for rec in self:
            score = rec.performance_score or 0.0
            if score >= excellent:
                rec.performance_level = "excellent"
            elif score >= passed:
                rec.performance_level = "pass"
            else:
                rec.performance_level = "fail"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            start_date = vals.get("start_date")
            if start_date:
                # start_date can be either a string (from JSON/RPC) or a datetime.date
                if isinstance(start_date, str):
                    year = datetime.strptime(start_date, "%Y-%m-%d").year
                else:
                    year = start_date.year
            else:
                year = datetime.now().year
            sequence = (
                self.env["ir.sequence"].next_by_code("performance.evaluation.sequence")
                or "0001"
            )
            vals["name"] = f"PE/{sequence}/{year}"
        return super().create(vals_list)

    @api.depends("employee_id")
    def _compute_employee_info(self):
        for record in self:
            if record.employee_id:
                record.job_id = record.employee_id.job_id
                record.manager_id = record.employee_id.parent_id
                record.department_id = record.employee_id.department_id
            else:
                record.job_id = False
                record.manager_id = False
                record.department_id = False

    @api.onchange("employee_id", "period")
    def _onchange_employee_or_period_clear_kpi(self):
        """Xóa KPI đã chọn nếu nó không còn phù hợp với Nhân viên (Phòng ban) hoặc Chu kỳ mới."""
        if self.kpi_id:
            # Kiểm tra xem KPI hiện tại có khớp với Period và Department mới không
            if (self.kpi_id.period != self.period) or (
                self.kpi_id.department_id
                and self.kpi_id.department_id != self.department_id
            ):
                self.kpi_id = False

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _prepare_evaluation_line_commands_from_template(self, kpi):
        """Build one2many commands for evaluation_line_ids from KPI template lines.

        - Preserves ordering via sequence.
        - Preserves section/note lines.
        """
        self.ensure_one()
        if not kpi:
            return []

        template_lines = kpi.kpi_line_ids.sorted(lambda l: (l.sequence or 0, l._origin.id or 0, l.id or 0))

        # Sử dụng : list[tuple] để Type Checker không hiểu lầm là danh sách chỉ chứa tuple 3 số nguyên.
        # fields.Command.clear() tương đương với lệnh (5, 0, 0) để xóa sạch các dòng cũ trước khi thêm mới.
        commands: list[tuple] = [fields.Command.clear()]
        for line in template_lines:
            # Kiểm tra nếu dòng hiện tại là một Section (tiêu đề nhóm) dựa trên thuộc tính hoặc display_type.
            is_section = bool(
                getattr(line, "is_section", False)
                or getattr(line, "display_type", False)
            )
            if is_section:
                # fields.Command.create({...}) tương đương với lệnh (0, 0, {...}) để tạo mới một dòng.
                commands.append(
                    fields.Command.create(
                        {
                            "kpi_line_id": line.id,
                            "sequence": line.sequence,
                            "is_section": True,
                            "display_type": (line.display_type or "line_section"),
                            "key_performance_area": line.key_performance_area,
                            "description": False,
                            # Safe defaults for required KPI fields on section rows
                            "kpi_type": "quantitative",
                            "target_type": "value",
                            "direction": "higher_better",
                            "target": 0.0,
                            "weight": 0.0,
                            "is_auto": False,
                            "data_source": "manual",
                        }
                    )
                )
                continue

            commands.append(
                fields.Command.create(
                    {
                        "kpi_line_id": line.id,
                        "sequence": line.sequence,
                        "key_performance_area": line.key_performance_area,
                        "description": getattr(line, "description", False),
                        "kpi_type": line.kpi_type,
                        "target_type": line.target_type,
                        "direction": line.direction,
                        "target": line.target,
                        "weight": line.weight,
                        "is_auto": bool(line.is_auto),
                        "data_source": line.data_source,
                    }
                )
            )
        return commands

    @api.onchange("kpi_id")
    def _onchange_kpi_id(self):
        # if not self.kpi_id:
        #     return
        #
        #     # GUARD: Chỉ rebuild khi kpi_id thực sự được user thay đổi.
        #     # _origin.kpi_id là giá trị đang lưu trong DB.
        #     # Nếu bằng nhau → onchange đang fire spuriously (lúc save/reload) → bỏ qua.
        # if self._origin.kpi_id and self._origin.kpi_id.id == self.kpi_id.id:
        #     return

        if self.kpi_id:
            self.evaluation_line_ids = (
                self._prepare_evaluation_line_commands_from_template(
                    self.kpi_id
                )
            )

    def action_compute_auto_kpi(self):
        """Compute Actual for auto KPI lines based on their template data source."""
        engine = self.env["hr.kpi.engine"]
        for evaluation in self:
            if not evaluation.employee_id:
                continue
            if not evaluation.kpi_id:
                continue
            date_from = evaluation.start_date
            date_to = evaluation.end_date
            for line in evaluation.evaluation_line_ids:
                if not line.is_auto:
                    continue
                # evaluation line carries data_source/target_type copied from template
                vals = {}

                if (line.data_source or "manual") == "attendance_full":
                    value, metrics = engine.compute_with_metrics(
                        evaluation.employee_id, line, date_from, date_to
                    )
                    vals["actual"] = value
                    vals.update(
                        {
                            "attendance_worked_days": metrics.get("worked_days", 0.0),
                            "attendance_expected_days": metrics.get(
                                "expected_work_days", 0.0
                            ),
                            "attendance_unpaid_leave_days": metrics.get(
                                "unpaid_leave_days", 0.0
                            ),
                            "attendance_approved_leave_days": metrics.get(
                                "approved_leave_days", 0.0
                            ),
                            "attendance_has_unpaid_leave": metrics.get(
                                "has_unpaid_leave", False
                            ),
                        }
                    )

                else:
                    vals["actual"] = engine.compute(
                        evaluation.employee_id, line, date_from, date_to
                    )

                line.write(vals)

    # ------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------
    @api.model
    def _cron_compute_auto_kpi(self, batch_size=200):
        """Cron: compute auto KPI actuals for submitted evaluations."""
        while True:
            evaluations = self.sudo().search([], limit=batch_size, order="id asc")
            if not evaluations:
                break

            # Process record-by-record so one failure doesn't block the rest.
            for ev in evaluations:
                try:
                    # Only quantitative lines are affected by action_compute_auto_kpi.
                    # (The method itself checks is_auto.)
                    ev.action_compute_auto_kpi()
                    # Ensure summary reflects any updated final_ratings.
                    ev._compute_performance_score()
                except Exception:
                    _logger.exception(
                        "Auto KPI cron failed for evaluation id=%s (employee=%s)",
                        ev.id,
                        ev.employee_id.id if ev.employee_id else None,
                    )

            # Avoid infinite loop: move forward with an offset using last id.
            last_id = evaluations[-1].id
            domain = domain + [("id", ">", last_id)]

        return True
