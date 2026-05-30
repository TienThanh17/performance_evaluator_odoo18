import logging
from datetime import datetime

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PerformanceEvaluation(models.Model):
    _name = "hr.performance.evaluation"
    _description = "Performance Evaluation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, end_date desc"

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
        "hr.kpi.template",
        string="KPI Template",
        required=False,
        domain="[('period_id', '=', period_id), ('department_id', '=', department_id)]",
        help="KPI template used to generate evaluation lines.",
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        string="KPI Period",
        compute="_compute_period_id",
        store=True,
        readonly=False,
        help="Canonical KPI period used by this evaluation.",
    )
    period_type = fields.Selection(
        related="period_id.period_type",
        string="Period Type",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("self_evaluation", "Self Evaluation"),
            ("manager_evaluating", "Manager Evaluating"),
            ("completed", "Completed"),
            ("cancel", "Canceled"),
        ],
        default="self_evaluation",
        string="State",
        help="Workflow stage of the evaluation (Self Evaluation → Manager Evaluating → Completed). Canceled evaluations are locked.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Set to false to archive the evaluation.",
    )
    start_date = fields.Date(
        string="Start Date", help="Start date of the evaluation period."
    )
    end_date = fields.Date(string="End Date", help="End date of the evaluation period.")
    deadline = fields.Date(
        string="Deadline", help="Deadline for submitting the self-evaluation."
    )
    period_status = fields.Selection(
        [
            ("upcoming", "Sắp diễn ra"),
            ("ongoing", "Đang diễn ra"),
            ("closed", "Đã kết thúc"),
        ],
        string="Period Status",
        compute="_compute_period_status",
        store=False,
    )
    evaluation_line_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "evaluation_id",
        string="Evaluation Lines",
        help="The KPI lines to be evaluated for this employee (generated from the KPI template and editable based on roles).",
    )
    name = fields.Char(string="Reference", readonly=True)
    performance_score = fields.Float(
        string="Individual KPI Score",
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
        string=_("Result"),
        compute="_compute_performance_level",
        store=True,
        help="Result level derived from the Average Score and the KPI thresholds configured in Settings.",
    )

    # Điểm cuối cùng: pha trộn performance_score cá nhân và dept_kpi_score phòng ban
    final_score = fields.Float(
        string=_("Final Bonus Score"),
        compute="_compute_final_score",
        store=True,
        digits=(6, 2),
        help=_(
            "The final score used for bonus calculation, blended from: "
            "(Department Score × Weight) + (Individual Score × Weight). "
        ),
        # "If Department data is missing, only the Individual Score is used to ensure fairness.",
    )
    final_level = fields.Selection(
        selection=[
            ("excellent", "Excellent"),
            ("pass", "Pass"),
            ("fail", "Fail"),
        ],
        string="Final Result",
        compute="_compute_final_level",
        store=True,
        help="Performance level derived from final_score using the same thresholds as performance_level.",
    )

    performance_badge_class = fields.Char(
        string="Performance Badge Class",
        compute="_compute_performance_badge_class",
        store=False,
        help="Technical field used by the UI to colorize the performance score/level.",
    )
    performance_report_id = fields.Many2one(
        "hr.performance.report",
        string="Performance Report",
        domain=[("active", "=", True)],
        required=False,
        help="Defines the active evaluation window (start/end/deadline) for the selected period.",
        ondelete="cascade",
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        string="Department Evaluation",
        domain="[('department_id', '=', department_id)]",
        required=False,
        ondelete="set null",
        help="Link to the department KPI evaluation for the same period. "
        "Used to blend dept_kpi_score into the individual final_score.",
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

    has_binary_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)

    performance_visual = fields.Html(compute="_compute_performance_visual")
    performance_score_progress_pct = fields.Float(
        string="Performance Progress %",
        compute="_compute_score_scale_display",
        store=False,
    )
    score_scale_suffix = fields.Char(
        string="Score Scale Suffix",
        compute="_compute_score_scale_display",
        store=False,
    )

    is_manager = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_hr = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_employee = fields.Boolean(
        compute="_compute_role",
        store=False,
    )
    is_current_user = fields.Boolean(compute="_compute_is_current_user", store=False)
    is_department_manager = fields.Boolean(
        compute="_compute_is_department_manager", store=False
    )

    @api.depends("kpi_id.period_id", "performance_report_id.period_id")
    def _compute_period_id(self):
        for rec in self:
            rec.period_id = rec.kpi_id.period_id or rec.performance_report_id.period_id

    @api.depends_context("uid")
    def _compute_role(self):
        is_manager = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_manager"
        )
        is_hr = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_hr"
        )
        is_employee = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_employee"
        )

        for rec in self:
            rec.is_manager = is_manager
            rec.is_hr = is_hr
            rec.is_employee = is_employee

    @api.depends("employee_id.user_id")
    def _compute_is_current_user(self):
        for rec in self:
            # So sánh user_id của nhân viên với user đang đăng nhập
            if rec.employee_id and rec.employee_id.user_id:
                rec.is_current_user = rec.employee_id.user_id == self.env.user
            else:
                rec.is_current_user = False

    @api.depends_context("uid")
    def _compute_is_department_manager(self):
        for rec in self:
            # Cách viết an toàn và sạch sẽ hơn trong Odoo 18
            manager_user = rec.department_id.manager_id.user_id
            if manager_user:
                # So sánh Recordset trực tiếp (Odoo tự hiểu là so sánh ID)
                rec.is_department_manager = manager_user == self.env.user
            else:
                rec.is_department_manager = False

    @api.depends("start_date", "end_date")
    def _compute_period_status(self):
        for rec in self:
            if not rec.start_date or not rec.end_date:
                rec.period_status = False
                continue
            today = fields.Date.context_today(rec)
            if today < rec.start_date:
                rec.period_status = "upcoming"
            elif today > rec.end_date:
                rec.period_status = "closed"
            else:
                rec.period_status = "ongoing"

    @api.depends("evaluation_line_ids.kpi_type")
    def _compute_kpi_types(self):
        for rec in self:
            kpi_types = rec.evaluation_line_ids.mapped("kpi_type")
            rec.has_binary_kpi = "binary" in kpi_types
            rec.has_rating_kpi = "rating" in kpi_types
            rec.has_score_kpi = "score" in kpi_types

    @api.depends("performance_score")
    def _compute_score_scale_display(self):
        scale = self.env["res.config.settings"].get_score_scale_info()
        base = scale.get("base") or 10.0
        for rec in self:
            rec.performance_score_progress_pct = max(
                0.0,
                min(100.0, ((rec.performance_score or 0.0) / base) * 100.0),
            )
            rec.score_scale_suffix = scale.get("suffix") or " / 10"

    def _get_thresholds_for_record(self):
        self.ensure_one()
        profile = self.kpi_id.scoring_profile_id
        if profile:
            return profile.get_thresholds()
        return self.env["res.config.settings"].get_thresholds()

    @api.depends("performance_score", "employee_id")
    def _compute_performance_visual(self):
        score_base = self.env["res.config.settings"].get_score_scale_base()
        for rec in self:
            # Quy đổi điểm theo score_base hiện tại sang phần trăm để vẽ vòng tròn.
            score_pct = max(
                0.0, min(100.0, ((rec.performance_score or 0) / score_base) * 100.0)
            )

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

    # @api.constrains("period", "performance_report_id")
    # def _check_period_active(self):
    #     for record in self:
    #         matching_alerts = self.env["hr.performance.report"].search(
    #             [("active", "=", True), ("period", "=", record.period)]
    #         )
    #         if not matching_alerts:
    #             raise ValidationError(
    #                 f"The selected period '{record.period}' is not valid for any active evaluation alert. "
    #                 f"Please ensure there is at least one active alert with this period."
    #             )

    # @api.model
    # def default_get(self, fields_list):
    #     defaults = super().default_get(fields_list)
    #     active_alert = self.env["hr.performance.report"].search(
    #         [("active", "=", True)], limit=1
    #     )
    #     if active_alert:
    #         defaults.update(
    #             {
    #                 "evaluation_alert_id": active_alert.id,
    #                 "start_date": active_alert.start_date,
    #                 "end_date": active_alert.end_date,
    #                 "deadline": active_alert.deadline,
    #                 "period": active_alert.period,
    #             }
    #         )
    #     return defaults

    def action_submit(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for record in self:
            if record.state != "self_evaluation":
                raise UserError(
                    _("You can only submit evaluations in self evaluation state.")
                )

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
                    _("Please answer all Binary KPI lines before submit.")
                )

            missing_rating = lines.filtered(
                lambda l: l.kpi_type == "rating" and not l.employee_rating_selection
            )
            if missing_rating:
                missing_rating.write({"employee_rating_selection": "0"})

            missing_score = lines.filtered(
                lambda l: l.kpi_type == "score" and l.employee_rating_score is None
            )
            if missing_score:
                raise ValidationError(
                    _(
                        "Please provide Employee Score for all Score KPI lines before submit."
                    )
                )

            record.state = "manager_evaluating"

            # =========================================================
            # GỬI THÔNG BÁO CHO QUẢN LÝ PHÒNG BAN
            # =========================================================
            # Lấy thông tin quản lý phòng ban (ưu tiên department_id trên record hoặc từ employee)
            department = record.employee_id.department_id
            manager = department.manager_id if department else False

            if manager and manager.user_id and manager.user_id.partner_id:
                partner_to = manager.user_id.partner_id

                # Tạo đường dẫn trực tiếp đến bản ghi hiện tại
                record_url = (
                    f"{base_url}/web#id={record.id}&model={record._name}&view_type=form"
                )

                # CSS cho nút nhấn để hiển thị tốt trên Email
                button_style = (
                    "padding: 8px 16px; "
                    "text-decoration: none; "
                    "color: #fff; "
                    "background-color: #875A7B; "
                    "border: 1px solid #875A7B; "
                    "border-radius: 3px; "
                    "font-weight: bold;"
                )

                body_html = Markup(
                    _(
                        "<p>Dear Manager,</p>"
                        "<p>The performance evaluation for <b>%(employee_name)s</b> has been submitted.</p>"
                        "<ul>"
                        "<li><b>Status:</b> Waiting for Manager Evaluation</li>"
                        "<li><b>Period:</b> %(period)s</li>"
                        "</ul>"
                        "<div style='margin: 16px 0;'>"
                        "    <a href='%(url)s' style='%(style)s'>View Evaluation</a>"
                        "</div>"
                        "<p>Please review and provide your manager ratings.</p>"
                    )
                ) % {
                    "employee_name": record.employee_id.name,
                    "period": record.period_id.name if record.period_id else "N/A",
                    "url": record_url,
                    "style": button_style,
                }

                # Post tin nhắn vào Chatter và tag (notify) quản lý
                record.message_post(
                    body=body_html,
                    subject=_("Action Required: Performance Evaluation Submitted"),
                    partner_ids=[partner_to.id],
                    message_type="comment",  # 'comment' sẽ kích hoạt gửi email/notification
                    subtype_xmlid="mail.mt_comment",
                )

    def action_approve(self):
        for record in self:
            if record.state != "manager_evaluating":
                raise UserError(
                    _("You can only approve evaluations in manager evaluating state.")
                )
            record.state = "completed"

    def action_cancel(self):
        for record in self:
            if record.state == "cancel":
                continue
            record.state = "cancel"

    @api.depends("evaluation_line_ids.final_rating", "evaluation_line_ids.weight")
    def _compute_performance_score(self):
        for record in self:
            scorable_lines = record.evaluation_line_ids.filtered(
                lambda l: not l.is_section
            )
            total_weighted_score_sum = sum(
                line.final_rating * line.weight for line in scorable_lines
            )
            total_weight_sum = sum(line.weight for line in scorable_lines)
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

    @api.depends("performance_score")
    def _compute_performance_badge_class(self):
        for rec in self:
            excellent, passed = rec._get_thresholds_for_record()
            score = rec.performance_score or 0.0
            if score >= excellent:
                rec.performance_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                rec.performance_badge_class = "o_kpi_badge_pass"
            else:
                rec.performance_badge_class = "o_kpi_badge_fail"

    @api.depends("performance_score")
    def _compute_performance_level(self):
        for rec in self:
            excellent, passed = rec._get_thresholds_for_record()
            score = rec.performance_score or 0.0
            if score >= excellent:
                rec.performance_level = "excellent"
            elif score >= passed:
                rec.performance_level = "pass"
            else:
                rec.performance_level = "fail"

    @api.depends(
        "performance_score",
        "dept_evaluation_id",
        "dept_evaluation_id.dept_kpi_score",
        "dept_evaluation_id.state",
        "dept_evaluation_id.department_kpi_id.dept_weight",
    )
    def _compute_final_score(self):
        """Tính điểm cuối cùng của cá nhân theo công thức:
        final_score = dept_kpi_score × dept_weight + performance_score × (1 - dept_weight)

        Quy tắc nghiệp vụ:
        - Chưa liên kết dept evaluation   → final_score = performance_score
        - dept evaluation bị hủy (cancel) → final_score = performance_score
        - draft / submitted / approved      → dùng dept_kpi_score tạm thời hoặc chính thức
        """
        for rec in self:
            dept_eval = rec.dept_evaluation_id

            # Fallback: không có dept evaluation → giữ nguyên performance_score
            if not dept_eval:
                rec.final_score = rec.performance_score
                continue

            # Lấy điểm KPI phòng ban qua method (trả 0.0 nếu state=cancel)
            dept_score = dept_eval.get_dept_kpi_score()

            # Fallback: dept bị hủy → không đưa vào công thức
            if dept_eval.state == "cancel":
                rec.final_score = rec.performance_score
                continue

            # Lấy trọng số từ template KPI phòng ban; mặc định 0.4 nếu chưa cấu hình
            dept_weight = (
                dept_eval.department_kpi_id.dept_weight
                if dept_eval.department_kpi_id
                else 0.4
            )
            individual_weight = (
                dept_eval.department_kpi_id.individual_weight
                if dept_eval.department_kpi_id
                else 0.6
            )

            # Công thức pha trộn
            rec.final_score = (dept_score * dept_weight) + (
                rec.performance_score * individual_weight
            )

    @api.depends("final_score")
    def _compute_final_level(self):
        """Xếp loại dựa trên final_score và ngưỡng cấu hình.

        Dùng cùng key param với _compute_performance_level để đảm bảo nhất quán.
        """
        for rec in self:
            threshold_excellent, threshold_pass = rec._get_thresholds_for_record()
            score = rec.final_score or 0.0
            if score >= threshold_excellent:
                rec.final_level = "excellent"
            elif score >= threshold_pass:
                rec.final_level = "pass"
            else:
                rec.final_level = "fail"

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
            vals["name"] = f"KPI/{sequence}/{year}"
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

    @api.onchange("employee_id", "period_id")
    def _onchange_employee_or_period_clear_kpi(self):
        """Xóa KPI đã chọn nếu nó không còn phù hợp với Nhân viên (Phòng ban) hoặc Chu kỳ mới."""
        if self.kpi_id:
            # Kiểm tra xem KPI hiện tại có khớp với Period và Department mới không
            if (self.kpi_id.period_id != self.period_id) or (
                self.kpi_id.department_id
                and self.kpi_id.department_id != self.department_id
            ):
                self.kpi_id = False

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _prepare_evaluation_line_commands_from_template(
        self, kpi, dept_eval_line_by_template_line=None
    ):
        """Build one2many commands for evaluation_line_ids from KPI template lines.

        - Preserves ordering via sequence.
        - Preserves section/note lines.
        """
        self.ensure_one()
        if not kpi:
            return []
        dept_eval_line_by_template_line = dept_eval_line_by_template_line or {}

        template_lines = kpi.kpi_line_ids.sorted(
            lambda l: (l.sequence or 0, l._origin.id or 0, l.id or 0)
        )

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
                            "target": 0.0,
                            "unit": False,
                            "weight": 0.0,
                            "is_auto": False,
                        }
                    )
                )
                continue

            parent_dept_line = line.parent_dept_line_id
            commands.append(
                fields.Command.create(
                    {
                        "kpi_line_id": line.id,
                        "parent_dept_line_id": parent_dept_line.id,
                        "parent_dept_evaluation_line_id": dept_eval_line_by_template_line.get(
                            parent_dept_line.id
                        ),
                        "sequence": line.sequence,
                        "key_performance_area": line.key_performance_area,
                        "description": getattr(line, "description", False),
                        "kpi_type": line.kpi_type,
                        "target": line.target,
                        "unit": line.unit.id or False,
                        "weight": line.weight,
                        "is_auto": bool(line.is_auto),
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
                self._prepare_evaluation_line_commands_from_template(self.kpi_id)
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
                # Evaluation line carries the template data_source/unit for auto-compute.
                vals = {}

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

        # 1. Khởi tạo domain cơ bản (Chỉ quét những phiếu đang ở trạng thái cần tính toán)
        base_domain = [("state", "not in", ["completed", "cancel"])]
        domain = base_domain.copy()

        while True:
            # 2. TRUYỀN BIẾN DOMAIN VÀO ĐÂY
            evaluations = self.sudo().search(domain, limit=batch_size, order="id asc")
            if not evaluations:
                break

            # Process record-by-record so one failure doesn't block the rest.
            for ev in evaluations:
                try:
                    ev.action_compute_auto_kpi()
                    ev._compute_performance_score()
                except Exception as e:
                    _logger.exception(
                        "Auto KPI cron failed for evaluation id=%s (employee=%s): %s",
                        ev.id,
                        ev.employee_id.id if ev.employee_id else None,
                        str(e),
                    )

            # 3. Cập nhật lại domain cho vòng lặp tiếp theo
            last_id = evaluations[-1].id
            domain = base_domain + [("id", ">", last_id)]

            # 4. (Tùy chọn) Commit sau mỗi batch để giải phóng bộ nhớ và tránh lock DB quá lâu
            # Lưu ý: Chỉ bật lên nếu batch của bạn thực sự rất lớn và chạy tốn nhiều thời gian
            # self.env.cr.commit()

        return True

    # ------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------
    def get_dashboard_data(self):
        """Return all data needed to render the individual KPI dashboard.

        Called from JS via orm.call().  Returns a plain dict so it can be
        serialised to JSON by the RPC layer.
        """
        self.ensure_one()
        evaluation = self

        perf_key = evaluation.performance_level or "fail"

        # 2. Lấy mapping các tuỳ chọn của Selection đã ĐƯỢC DỊCH theo context ngôn ngữ hiện tại
        # Lệnh này sẽ trả về dạng {'excellent': 'Xuất sắc', 'fail': 'Không đạt', ...}
        selection_dict = dict(
            self._fields["performance_level"]._description_selection(self.env)
        )

        # 3. Lấy ra nhãn (label) đã dịch tương ứng với key
        perf_label = selection_dict.get(perf_key, perf_key)

        final_key = evaluation.final_level or "fail"
        # Employees can open their own individual dashboard, but they do not
        # have read access to department evaluations. Read only the linked
        # department score/weight with sudo so the dashboard can show the
        # already-computed final KPI breakdown without exposing the model.
        dept_eval = evaluation.sudo().dept_evaluation_id.sudo()
        dept_score = dept_eval.get_dept_kpi_score() if dept_eval else 0.0
        has_dept_evaluation = bool(dept_eval and dept_eval.state != "cancel")
        dept_kpi = dept_eval.department_kpi_id.sudo() if has_dept_evaluation else False
        dept_weight = dept_kpi.dept_weight if has_dept_evaluation and dept_kpi else 0.0
        individual_weight = 1.0 - dept_weight
        settings = self.env["res.config.settings"]
        score_scale = settings.get_score_scale_info()
        threshold_excellent, threshold_pass = evaluation._get_thresholds_for_record()
        widget_model = self.env["hr.kpi.dashboard.widget"]
        chart_service = self.env["hr.kpi.dashboard.chart.service"]
        widgets = widget_model.get_dashboard_widgets("individual")

        result = {
            "evaluation_id": evaluation.id,
            "score_scale": score_scale,
            "widgets": widgets,
            "widget_map": {widget["code"]: widget for widget in widgets},
            "thresholds": {
                "excellent": threshold_excellent,
                "pass": threshold_pass,
            },
            "employee_name": evaluation.employee_id.name or "",
            "period_id": evaluation.period_id.id if evaluation.period_id else False,
            "period_name": evaluation.period_id.name if evaluation.period_id else "",
            "period_type": evaluation.period_type or "",
            "start_date": str(evaluation.start_date) if evaluation.start_date else "",
            "end_date": str(evaluation.end_date) if evaluation.end_date else "",
            "performance_score": round(float(evaluation.performance_score or 0.0), 2),
            "dept_kpi_score": round(float(dept_score), 2),
            "dept_weight": round(float(dept_weight), 4),
            "individual_weight": round(float(individual_weight), 4),
            "has_dept_evaluation": has_dept_evaluation,
            "final_score": round(float(evaluation.final_score or 0.0), 2),
            "final_level": final_key,
            "final_level_label": selection_dict.get(final_key, final_key),
            # Keep raw key for CSS class logic (levelClass)
            "performance_level": perf_key,
            # Translated label for display
            "performance_level_label": perf_label,
            "spider_web": self._get_spider_web_data(evaluation),
            "quantitative_table": self._get_quantitative_table_data(evaluation),
            "dynamic_charts": chart_service.build_dynamic_charts(evaluation),
        }
        return result

    # ------------------------------------------------------------------
    # Spider Web – non-quantitative KPIs
    # ------------------------------------------------------------------
    def _get_spider_web_data(self, evaluation):
        lines = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.kpi_type != "quantitative"
        )
        labels = []
        scores = []
        max_val = self.env["res.config.settings"].get_score_scale_base()

        for line in lines:
            labels.append(line.key_performance_area or "KPI")
            scores.append(round(float(line.final_rating or 0.0), 2))

        return {
            "labels": labels,
            "scores": scores,
            "max": max_val,
        }

    # ------------------------------------------------------------------
    # Quantitative Table
    # ------------------------------------------------------------------
    def _get_quantitative_table_data(self, evaluation):
        lines = evaluation.evaluation_line_ids.filtered(
            lambda l: (
                not l.is_section
                and l.kpi_type == "quantitative"
            )
        )
        rows = []
        for line in lines:
            target = float(line.target or 0.0)
            actual = float(line.actual or 0.0)
            final = float(line.final_rating or 0.0)

            if target != 0:
                variance_pct = round((actual - target) / abs(target) * 100, 1)
            else:
                variance_pct = 0.0

            if line.unit and line.unit.code == "percent":
                target_text = f"{target:g}%"
                actual_text = f"{actual:g}%"
            else:
                unit_name = line.unit.name if line.unit else ""
                target_text = f"{target:g} {unit_name}" if unit_name else f"{target:g}"
                actual_text = f"{actual:g} {unit_name}" if unit_name else f"{actual:g}"
            formula = line.kpi_line_id.get_effective_formula() if line.kpi_line_id else False
            rows.append(
                {
                    "name": line.key_performance_area or "",
                    "target": target_text,
                    "actual": actual_text,
                    "variance": variance_pct,
                    "final_score": round(final, 2),
                    "linear_direction": (
                        formula.linear_direction
                        if formula
                        and formula.formula_type == "linear"
                        and formula.linear_direction
                        else "higher_better"
                    ),
                }
            )
        return rows
