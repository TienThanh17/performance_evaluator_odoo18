import logging
from datetime import datetime

from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html2plaintext

from .kpi_type_utils import NORMALIZED_3P_PILLAR_CODES

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
        tracking=True,
        help="The employee being evaluated.",
    )
    kpi_id = fields.Many2one(
        "hr.kpi.template",
        string="KPI Template",
        required=False,
        domain="[('period_type', '=', period_type), ('department_id', '=', department_id), '|', ('job_id', '=', False), ('job_id', 'in', [job_id])]",
        tracking=True,
        help="KPI template used to generate evaluation lines.",
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        string="KPI Period",
        compute="_compute_period_id",
        store=True,
        readonly=False,
        tracking=True,
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
        tracking=True,
        help="Workflow stage of the evaluation (Self Evaluation → Manager Evaluating → Completed). Canceled evaluations are locked.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
        help="Set to false to archive the evaluation.",
    )
    start_date = fields.Date(
        string="Start Date",
        tracking=True,
        help="Start date of the evaluation period.",
    )
    end_date = fields.Date(
        string="End Date",
        tracking=True,
        help="End date of the evaluation period.",
    )
    deadline = fields.Date(
        string="Deadline",
        tracking=True,
        help="Deadline for submitting the self-evaluation.",
    )
    period_status = fields.Selection(
        [
            ("upcoming", "Upcoming"),
            ("ongoing", "Ongoing"),
            ("closed", "Closed"),
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
    evaluation_line_p2_1_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "evaluation_id",
        domain=[("pillar_code", "=", "p2_1")],
        string="P2.1 Evaluation Lines",
        help="Evaluation lines that belong to the P2.1 pillar.",
    )
    evaluation_line_p2_2_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "evaluation_id",
        domain=[("pillar_code", "=", "p2_2")],
        string="P2.2 Evaluation Lines",
        help="Evaluation lines that belong to the P2.2 pillar.",
    )
    evaluation_line_p3_individual_ids = fields.One2many(
        "hr.performance.evaluation.line",
        "evaluation_id",
        domain=[("pillar_code", "=", "p3_individual")],
        string="P3 Individual Evaluation Lines",
        help="Evaluation lines that belong to the P3 individual pillar.",
    )
    name = fields.Char(string="Reference", readonly=True)
    total_p2_1 = fields.Float(
        string="P2.1 Total",
        compute="_compute_pillar_totals",
        store=True,
        digits=(16, 1),
        help="Stored total score of the P2.1 pillar.",
    )
    total_p2_2 = fields.Float(
        string="P2.2 Total",
        compute="_compute_pillar_totals",
        store=True,
        digits=(16, 1),
        help="Stored total score of the P2.2 pillar.",
    )
    total_p3_individual = fields.Float(
        string="Individual KPI Score",
        compute="_compute_pillar_totals",
        store=True,
        aggregator="avg",
        digits=(16, 1),
        help="Stored total score of the P3 individual pillar.",
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
        tracking=True,
        help="Defines the active evaluation window (start/end/deadline) for the selected period.",
        ondelete="cascade",
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        string="Department Evaluation",
        domain="[('department_id', '=', department_id)]",
        required=False,
        ondelete="set null",
        tracking=True,
        help="Link to the department KPI evaluation for the same period.",
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
        string="Direct Manager",
        compute="_compute_employee_info",
        store=True,
        readonly=True,
        help="The employee's direct manager (filled automatically).",
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
    # Per-pillar KPI type flags (used by individual pillar tabs)
    has_binary_kpi_p2_1 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi_p2_1 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi_p2_1 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_binary_kpi_p2_2 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi_p2_2 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi_p2_2 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_binary_kpi_p3 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi_p3 = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi_p3 = fields.Boolean(compute="_compute_kpi_types", store=False)

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

    is_employee = fields.Boolean(
        compute="_compute_role",
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
    is_admin = fields.Boolean(
        compute="_compute_role",
        store=False,
    )

    is_current_user = fields.Boolean(compute="_compute_is_current_user", store=False)
    is_department_manager = fields.Boolean(
        compute="_compute_is_department_manager", store=False
    )
    can_approve_all = fields.Boolean(
        compute="_compute_can_approve_all",
        store=False,
    )

    # Khai báo các field chứa tên động của từng Pillar
    pillar_p2_1_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Pillar P2.1 Name"
    )
    pillar_p2_2_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Pillar P2.2 Name"
    )
    pillar_p3_ind_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Pillar P3.1.1 Name"
    )

    def _compute_dynamic_pillar_names(self):
        # Truy vấn database một lần để lấy tất cả các pillar cần thiết (Tối ưu hiệu suất)
        # Giả định model hr.evaluation.pillar của bạn có trường 'code' để nhận diện
        pillars = (
            self.env["hr.evaluation.pillar"]
            .sudo()
            .search([("code", "in", ["p2_1", "p2_2", "p3_individual"])])
        )

        # Tạo một dictionary { 'p2_1': 'Kiến Thức', 'p2_2': 'Kỹ năng chuyên môn', ... }
        pillar_dict = {p.code: p.name for p in pillars}

        for rec in self:
            # Gán tên từ database, nếu không tìm thấy thì dùng tên mặc định
            rec.pillar_p2_1_name = pillar_dict.get("p2_1", "P2.1")
            rec.pillar_p2_2_name = pillar_dict.get("p2_2", "P2.2")
            rec.pillar_p3_ind_name = pillar_dict.get("p3_individual", "P3 Individual")

    @api.depends("performance_report_id.period_id")
    def _compute_period_id(self):
        for rec in self:
            rec.period_id = rec.performance_report_id.period_id

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
        is_admin = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_admin"
        )

        for rec in self:
            rec.is_manager = is_manager
            rec.is_hr = is_hr
            rec.is_employee = is_employee
            rec.is_admin = is_admin

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

    # Xác định có nên hiển thị nút duyệt hàng loạt theo phòng ban cho người dùng hiện tại hay không.
    @api.depends("dept_evaluation_id")
    @api.depends_context("uid")
    def _compute_can_approve_all(self):
        # Chỉ nhóm quản lý hoặc admin mới cần thấy nút approve hàng loạt.
        can_manage_approval = self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_manager"
        ) or self.env.user.has_group(
            "custom_adecsol_hr_performance_evaluator.group_admin"
        )

        for rec in self:
            # Ẩn nút ngay nếu record chưa gắn department evaluation hoặc user không có quyền duyệt.
            if not can_manage_approval or not rec.dept_evaluation_id:
                rec.can_approve_all = False
                continue

            # Kiểm tra trong cùng department evaluation còn phiếu nào đang chờ manager duyệt hay không.
            rec.can_approve_all = bool(
                self.search_count(
                    [
                        ("dept_evaluation_id", "=", rec.dept_evaluation_id.id),
                        ("state", "=", "manager_evaluating"),
                    ]
                )
            )

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

    # Detect which manual scoring widgets must stay visible in the evaluation grid.
    @api.depends(
        "evaluation_line_ids.kpi_type",
        "evaluation_line_ids.manual_scoring_type",
        "evaluation_line_ids.pillar_code",
    )
    def _compute_kpi_types(self):
        def _types_for(lines):
            manual = lines.filtered(lambda l: l.kpi_type == "manual")
            types = manual.mapped("manual_scoring_type")
            return "binary" in types, "rating" in types, "score" in types

        for rec in self:
            # Generic — used by the "All Lines" tab (all pillars combined)
            (
                rec.has_binary_kpi,
                rec.has_rating_kpi,
                rec.has_score_kpi,
            ) = _types_for(rec.evaluation_line_ids)

            # Per-pillar — used by individual pillar tabs
            (
                rec.has_binary_kpi_p2_1,
                rec.has_rating_kpi_p2_1,
                rec.has_score_kpi_p2_1,
            ) = _types_for(
                rec.evaluation_line_ids.filtered(lambda l: l.pillar_code == "p2_1")
            )
            (
                rec.has_binary_kpi_p2_2,
                rec.has_rating_kpi_p2_2,
                rec.has_score_kpi_p2_2,
            ) = _types_for(
                rec.evaluation_line_ids.filtered(lambda l: l.pillar_code == "p2_2")
            )
            (
                rec.has_binary_kpi_p3,
                rec.has_rating_kpi_p3,
                rec.has_score_kpi_p3,
            ) = _types_for(
                rec.evaluation_line_ids.filtered(
                    lambda l: l.pillar_code == "p3_individual"
                )
            )

    @api.depends("total_p3_individual")
    def _compute_score_scale_display(self):
        for rec in self:
            base = rec._get_evaluation_score_base()
            rec.performance_score_progress_pct = max(
                0.0,
                min(100.0, ((rec.total_p3_individual or 0.0) / base) * 100.0),
            )
            rec.score_scale_suffix = f" / {int(base)}"

    # Trả về thang điểm chuẩn duy nhất của phiếu đánh giá.
    def _get_evaluation_score_base(self):
        self.ensure_one()
        return self.env["res.config.settings"].get_score_scale_base()

    # Lấy threshold hiệu lực của phiếu đánh giá theo thang điểm chuẩn 100.
    def _get_thresholds_for_record(self):
        self.ensure_one()
        profile = self.kpi_id.scoring_profile_id
        settings = self.env["res.config.settings"]
        if profile:
            return profile.get_thresholds()
        return settings.get_thresholds()

    @api.depends("total_p3_individual", "employee_id")
    def _compute_performance_visual(self):
        for rec in self:
            score_base = rec._get_evaluation_score_base()
            # Quy đổi điểm theo score_base hiện tại sang phần trăm để vẽ vòng tròn.
            score_pct = max(
                0.0,
                min(100.0, ((rec.total_p3_individual or 0) / score_base) * 100.0),
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

    def action_submit(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for record in self:
            if record.state != "self_evaluation":
                raise UserError(
                    _("You can only submit evaluations in self evaluation state.")
                )

            lines = record.evaluation_line_ids.filtered(
                lambda l: l.kpi_type == "manual" and not l.is_section
            )

            # Validate self input before submit for manual KPI lines.
            missing_binary = lines.filtered(
                lambda l: (
                    l.manual_scoring_type == "binary" and not l.employee_rating_binary
                )
            )
            if missing_binary:
                raise ValidationError(
                    _("Please answer all Binary KPI lines before submit.")
                )

            missing_rating = lines.filtered(
                lambda l: (
                    l.manual_scoring_type == "rating"
                    and not l.employee_rating_selection
                )
            )
            if missing_rating:
                missing_rating.write({"employee_rating_selection": "0"})

            missing_score = lines.filtered(
                lambda l: (
                    l.manual_scoring_type == "score" and l.employee_rating_score is None
                )
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
        # Hoàn tất một phiếu đánh giá bằng cách tái sử dụng logic approve hàng loạt để đồng nhất validation.
        self.ensure_one()
        self.action_approve_batch()
        return True

    # Hoàn tất nhiều phiếu đánh giá cùng lúc sau khi xác thực tất cả vẫn còn ở bước manager evaluating.
    def action_approve_batch(self):
        # Chặn gọi rỗng để tránh trả về thành công giả khi wizard/context bị thiếu dữ liệu.
        if not self:
            raise UserError(_("No evaluations were found to approve."))

        # Thu thập các phiếu không còn hợp lệ để fail fast trước khi ghi trạng thái.
        invalid_records = self.filtered(
            lambda record: record.state != "manager_evaluating"
        )
        if invalid_records:
            # Hiển thị một danh sách ngắn tên phiếu để người dùng biết bản ghi nào đã đổi trạng thái.
            invalid_names = ", ".join(invalid_records.mapped("display_name")[:5])
            raise UserError(
                _(
                    "These evaluations can no longer be approved because they are no longer in manager evaluating state: %s"
                )
                % invalid_names
            )

        # Chỉ khi toàn bộ record hợp lệ mới chuyển đồng loạt sang completed.
        self.write({"state": "completed"})
        return True

    # Mở wizard để người duyệt chọn danh sách người nhận thông báo trước khi hoàn tất phiếu.
    def action_open_approve_wizard(self):
        self.ensure_one()

        # Chặn mở wizard nếu phiếu không còn ở bước manager evaluating.
        if self.state != "manager_evaluating":
            raise UserError(
                _("You can only approve evaluations in manager evaluating state.")
            )

        # Mở popup wizard và truyền phiếu hiện tại qua context để wizard xử lý tiếp.
        return {
            "type": "ir.actions.act_window",
            "name": _("Approve Evaluation"),
            "res_model": "performance.evaluation.approve.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_evaluation_id": self.id,
            },
        }

    # Trả về danh sách phiếu cùng department evaluation đang chờ manager duyệt dựa trên phiếu hiện tại.
    def _get_department_approvable_evaluations(self):
        self.ensure_one()

        # Nếu phiếu hiện tại chưa gắn department evaluation thì không thể suy ra scope approve hàng loạt.
        if not self.dept_evaluation_id:
            return self.browse()

        # Gom toàn bộ phiếu của cùng department evaluation đang ở bước manager evaluating.
        return self.search(
            [
                ("dept_evaluation_id", "=", self.dept_evaluation_id.id),
                ("state", "=", "manager_evaluating"),
            ]
        )

    # Dựng action mở wizard approve hàng loạt để form view và OWL dashboard cùng tái sử dụng một flow.
    @api.model
    def _build_approve_all_wizard_action(self, evaluations, dept_evaluation):
        # Bảo vệ luồng nếu caller truyền lên danh sách rỗng hoặc department evaluation không còn tồn tại.
        if not evaluations or not dept_evaluation:
            raise UserError(
                _("No manager evaluations were found for this department evaluation.")
            )

        # Lấy form view cụ thể của wizard để action client có đủ metadata khi mở popup từ OWL.
        wizard_view = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.view_performance_evaluation_approve_all_wizard_form"
        )

        # Mở wizard batch và truyền toàn bộ evaluation id qua context để wizard hiển thị và xác nhận.
        return {
            "type": "ir.actions.act_window",
            "name": _("Approve Evaluations"),
            "res_model": "performance.evaluation.approve.all.wizard",
            "view_mode": "form",
            "view_id": wizard_view.id,
            "views": [(wizard_view.id, "form")],
            "target": "new",
            "context": {
                "default_department_id": dept_evaluation.department_id.id,
                "default_dept_evaluation_id": dept_evaluation.id,
                "default_evaluation_ids": evaluations.ids,
            },
        }

    # Mở wizard approve hàng loạt từ form phiếu hiện tại theo phòng ban của phiếu đó.
    def action_open_approve_all_wizard(self):
        self.ensure_one()

        # Lấy toàn bộ phiếu cùng department evaluation còn ở bước manager evaluating để đưa vào wizard.
        evaluations = self._get_department_approvable_evaluations()
        if not evaluations:
            raise UserError(
                _("No manager evaluations were found for this department evaluation.")
            )

        # Tái sử dụng cùng action builder để đảm bảo form và OWL luôn mở cùng một wizard.
        return self._build_approve_all_wizard_action(
            evaluations, self.dept_evaluation_id
        )

    # Mở wizard approve hàng loạt từ OWL dashboard dựa trên department evaluation đang được chọn.
    @api.model
    def action_open_approve_all_wizard_by_dept_evaluation(self, dept_evaluation_id):
        # Chặn request thiếu department evaluation để trả lỗi business rõ ràng cho giao diện OWL.
        if not dept_evaluation_id:
            raise UserError(
                _("Please select a department evaluation before approving.")
            )

        # Kiểm tra department evaluation còn tồn tại rồi mới tìm batch evaluations.
        dept_evaluation = (
            self.env["hr.department.performance.evaluation"]
            .browse(dept_evaluation_id)
            .exists()
        )
        if not dept_evaluation:
            raise UserError(_("The selected department evaluation could not be found."))

        # Tìm toàn bộ phiếu trong cùng department evaluation đang chờ manager duyệt.
        evaluations = self.search(
            [
                ("dept_evaluation_id", "=", dept_evaluation.id),
                ("state", "=", "manager_evaluating"),
            ]
        )
        if not evaluations:
            raise UserError(
                _("No manager evaluations were found for this department evaluation.")
            )

        # Trả về đúng wizard batch dùng chung với form view.
        return self._build_approve_all_wizard_action(evaluations, dept_evaluation)

    # Tạo subject mặc định cho thông báo hoàn tất đánh giá để các luồng có thể tái sử dụng thống nhất.
    def _get_approval_notification_subject(self):
        self.ensure_one()
        return _("Performance Evaluation Approved")

    # Tạo nội dung HTML mặc định cho thông báo hoàn tất đánh giá và hiển thị trên wizard để người dùng chỉnh sửa.
    def _get_approval_notification_body_html(self):
        self.ensure_one()

        # Tạo link trực tiếp đến phiếu đánh giá để người nhận mở nhanh từ thông báo hoặc email.
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        record_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"

        # Dựng sẵn nội dung mặc định theo ngữ cảnh phiếu đã được duyệt hoàn tất.
        return Markup(
            _(
                "<p>Hello,</p>"
                "<p>The performance evaluation for <b>%(employee_name)s</b> has been approved.</p>"
                "<ul>"
                "<li><b>Status:</b> Completed</li>"
                "<li><b>Period:</b> %(period)s</li>"
                "</ul>"
                "<div style='margin-top: 20px;'>"
                "<a href='%(url)s' "
                "style='background-color: #714B67; padding: 8px 16px; color: #FFFFFF; "
                "text-decoration: none; border-radius: 4px; font-weight: bold; "
                "display: inline-block;'>View Evaluation</a>"
                "</div>"
            )
        ) % {
            "employee_name": self.employee_id.name,
            "period": self.period_id.name if self.period_id else "N/A",
            "url": record_url,
        }

    # Trả về danh sách user mặc định cần nhận thông báo khi phiếu được duyệt hoàn tất.
    def _get_default_approval_notification_users(self):
        self.ensure_one()

        # Gộp nhân viên được đánh giá và quản lý trực tiếp để tái sử dụng đồng nhất cho single và batch approve.
        return (self.employee_id.user_id | self.manager_id.user_id).filtered(
            lambda user: user.active and not user.share
        )

    # Gửi thông báo hoàn tất đánh giá đến các đối tượng được chọn từ wizard.
    def _send_approval_notification(self, users, body_html=None, subject=None):
        for record in self:
            # Chỉ giữ lại các user có partner để hệ thống có thể tạo notification/email.
            partner_ids = users.mapped("partner_id").ids
            if not partner_ids:
                continue

            # Nếu caller không truyền nội dung/tiêu đề tùy biến thì dùng mẫu mặc định của hệ thống.
            notification_body = (
                body_html or record._get_approval_notification_body_html()
            )
            notification_subject = (
                subject or record._get_approval_notification_subject()
            )

            # Post vào chatter để vừa lưu lịch sử vừa gửi notify cho người nhận đã chọn.
            record.message_post(
                body=notification_body,
                subject=notification_subject,
                partner_ids=partner_ids,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

    def action_cancel(self):
        for record in self:
            if record.state == "cancel":
                continue
            record.state = "cancel"

    # Chuẩn bị bộ giá trị tạo mới phiếu đánh giá từ cùng seed data ban đầu để phục vụ reset an toàn.
    def _prepare_reset_evaluation_vals(self):
        self.ensure_one()

        # KPI template phải còn tồn tại để hệ thống có thể dựng lại line tree như lúc khởi tạo ban đầu.
        if not self.kpi_id:
            raise UserError(
                _("The KPI template is missing, so the evaluation cannot be recreated.")
            )

        # Chặn reset nếu template hiện tại không còn khớp với scope nhân viên sau các thay đổi cơ cấu.
        if not self.kpi_id.matches_employee(self.employee_id):
            raise UserError(
                _(
                    "The selected KPI template no longer matches the employee's department or job position scope."
                )
            )

        # Chặn reset nếu chu kỳ của template không còn đồng bộ với chu kỳ đang lưu trên phiếu.
        if self.period_type and self.kpi_id.period_type != self.period_type:
            raise UserError(
                _("The KPI template period type no longer matches this evaluation.")
            )

        # Dùng cùng helper generate line tree để bảo toàn cấu trúc section, parent-child và scoring metadata.
        line_cmds = self._prepare_evaluation_line_commands_from_template(self.kpi_id)

        # Giữ lại toàn bộ seed data cốt lõi của phiếu cũ nhưng không mang theo các điểm/chú thích đã chấm nhầm.
        return {
            "employee_id": self.employee_id.id,
            "kpi_id": self.kpi_id.id,
            "period_id": self.period_id.id if self.period_id else False,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "deadline": self.deadline,
            "performance_report_id": self.performance_report_id.id or False,
            "dept_evaluation_id": self.dept_evaluation_id.id or False,
            "evaluation_line_ids": line_cmds,
        }

    # Xóa cứng phiếu hiện tại và tạo lại phiếu mới tinh cho chính nhân viên trong kỳ đang diễn ra.
    def action_reset_evaluation(self):
        self.ensure_one()

        # Chỉ cho phép reset khi phiếu vẫn còn ở bước tự đánh giá để tránh làm lệch luồng manager review.
        if self.state != "self_evaluation":
            raise UserError(
                _("You can only reset evaluations in self evaluation state.")
            )

        # Chỉ cho phép reset trong kỳ đang diễn ra đúng theo yêu cầu nghiệp vụ.
        if self.period_status != "ongoing":
            raise UserError(_("You can only reset evaluations in an ongoing period."))

        # Chỉ chính nhân viên sở hữu phiếu mới được tự reset phiếu của mình.
        # if not self.is_current_user:
        #     raise UserError(_("You can only reset your own evaluation."))

        # Chuẩn bị trước toàn bộ dữ liệu tạo mới; nếu bước này lỗi thì phiếu cũ vẫn còn nguyên.
        new_evaluation_vals = self._prepare_reset_evaluation_vals()

        # Tạo mới trước để đảm bảo chỉ xóa phiếu cũ khi việc recreate đã thành công hoàn toàn.
        new_evaluation = (
            self.env["hr.performance.evaluation"].sudo().create(new_evaluation_vals)
        )

        # Xóa cứng phiếu cũ bằng sudo có kiểm soát vì nhân viên không có quyền unlink trực tiếp.
        self.sudo().unlink()

        # Mở ngay form của phiếu mới để người dùng tiếp tục chấm lại mà không cần tìm kiếm thủ công.
        return {
            "type": "ir.actions.act_window",
            "name": _("Performance Evaluation"),
            "res_model": "hr.performance.evaluation",
            "res_id": new_evaluation.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.depends(
        "evaluation_line_ids",
        "evaluation_line_ids.final_rating",
        "evaluation_line_ids.weight",
        "evaluation_line_ids.parent_line_id",
        "evaluation_line_ids.pillar_code",
    )
    def _compute_pillar_totals(self):
        for record in self:
            record.total_p2_1 = record.get_weighted_score_by_pillar_code("p2_1")
            record.total_p2_2 = record.get_weighted_score_by_pillar_code("p2_2")
            record.total_p3_individual = record.get_weighted_score_by_pillar_code(
                "p3_individual"
            )

    # Return the root scoring nodes used by normalized 3P and legacy KPI trees.
    def _get_top_level_scorable_lines(self, pillar_code=None):
        self.ensure_one()
        lines = self.evaluation_line_ids.filtered(
            lambda line: (
                not line.parent_line_id
                and (
                    line.pillar_code in NORMALIZED_3P_PILLAR_CODES
                    or not line.is_section
                )
            )
        )
        if pillar_code:
            lines = lines.filtered(lambda line: line.pillar_code == pillar_code)
        return lines

    def _compute_weighted_score_from_lines(self, lines):
        self.ensure_one()
        if not lines:
            return 0.0
        total_weight_sum = sum(lines.mapped("weight"))
        if total_weight_sum > 0:
            return (
                sum(line.final_rating * line.weight for line in lines)
                / total_weight_sum
            )
        return sum(lines.mapped("final_rating")) / len(lines)

    def get_weighted_score_by_pillar_code(self, pillar_code):
        self.ensure_one()
        return self._compute_weighted_score_from_lines(
            self._get_top_level_scorable_lines(pillar_code)
        )

    # Đồng bộ weight section và chỉ giữ lại validate weight âm cho evaluation line.
    def _refresh_evaluation_line_weight_structure(self):
        line_records = self.mapped("evaluation_line_ids")
        if line_records:
            line_records._refresh_weight_structure()

    def _get_level_from_score(self, score):
        self.ensure_one()
        excellent, passed = self._get_thresholds_for_record()
        score = float(score or 0.0)
        if score >= excellent:
            return "excellent"
        if score >= passed:
            return "pass"
        return "fail"

    def action_recompute_pillar_totals(self):
        """Manual refresh for stored pillar totals and derived performance level."""
        for rec in self:
            rec._compute_pillar_totals()
            rec._compute_performance_level()
        return True

    @api.depends("total_p3_individual")
    def _compute_performance_badge_class(self):
        for rec in self:
            excellent, passed = rec._get_thresholds_for_record()
            score = rec.total_p3_individual or 0.0
            if score >= excellent:
                rec.performance_badge_class = "o_kpi_badge_excellent"
            elif score >= passed:
                rec.performance_badge_class = "o_kpi_badge_pass"
            else:
                rec.performance_badge_class = "o_kpi_badge_fail"

    @api.depends("total_p3_individual")
    def _compute_performance_level(self):
        for rec in self:
            excellent, passed = rec._get_thresholds_for_record()
            score = rec.total_p3_individual or 0.0
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
            vals["name"] = f"KPI/{sequence}/{year}"

        records = super(
            PerformanceEvaluation,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).create(vals_list)
        records._rebuild_line_hierarchy_from_template()
        records._refresh_evaluation_line_weight_structure()
        records._recompute_line_scores_after_hierarchy_rebuild()
        return records

    def write(self, vals):
        if "evaluation_line_ids" in vals and not self.env.context.get(
            "skip_normalized_3p_weight_validation"
        ):
            res = super(
                PerformanceEvaluation,
                self.with_context(skip_normalized_3p_weight_validation=True),
            ).write(vals)
            self._rebuild_line_hierarchy_from_template()
            self._refresh_evaluation_line_weight_structure()
            self._recompute_line_scores_after_hierarchy_rebuild()
            return res
        return super().write(vals)

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

    # Đảm bảo KPI template được chọn luôn khớp với phòng ban và vị trí hiện tại của nhân viên.
    @api.constrains("employee_id", "kpi_id")
    def _check_kpi_matches_employee_scope(self):
        for record in self:
            if not record.employee_id or not record.kpi_id:
                continue

            # Chặn việc gán template của phòng ban/vị trí khác để bản đánh giá không sai scope nghiệp vụ.
            if not record.kpi_id.matches_employee(record.employee_id):
                raise ValidationError(
                    _(
                        "The selected KPI template does not match the employee's department or job position scope."
                    )
                )

    # Tự bỏ KPI đang chọn nếu nhân viên hoặc kỳ đánh giá đổi sang scope không còn phù hợp.
    @api.onchange("employee_id", "period_id")
    def _onchange_employee_or_period_clear_kpi(self):
        """Xóa KPI đã chọn nếu nó không còn phù hợp với Nhân viên (Phòng ban/Vị trí) hoặc Chu kỳ mới."""
        if self.kpi_id:
            # Kiểm tra kỳ đánh giá trước để tránh giữ lại template của chu kỳ khác.
            kpi_matches_period = self.kpi_id.period_type == self.period_type

            # Kiểm tra đồng thời phòng ban và vị trí thông qua helper dùng chung của template.
            kpi_matches_employee = bool(
                self.employee_id and self.kpi_id.matches_employee(self.employee_id)
            )

            # Nếu một trong hai điều kiện không còn đúng thì phải bỏ template hiện tại.
            if not kpi_matches_period or not kpi_matches_employee:
                self.kpi_id = False

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    # Tính target khởi tạo cho evaluation line dựa trên template line và context kỳ đánh giá hiện tại.
    def _resolve_template_line_target(self, template_line):
        self.ensure_one()

        # Chỉ override target cho KPI attendance present vì target phải bám số ngày làm việc kỳ vọng của kỳ.
        source = getattr(template_line, "data_source_id", False)
        if not source or source.code != "attendance_present_days":
            return template_line.target

        # Nếu phiếu chưa có đủ ngữ cảnh nhân viên hoặc thời gian thì giữ target từ template để tránh target rỗng.
        if not self.employee_id or not self.start_date or not self.end_date:
            return template_line.target

        # Dùng cùng engine metrics để target luôn khớp expected_work_days của kỳ đánh giá thực tế.
        expected_work_days = self.env["hr.kpi.engine"].get_attendance_expected_work_days(
            self.employee_id,
            template_line,
            self.start_date,
            self.end_date,
        )
        return expected_work_days

    # Build one2many commands từ template line sang evaluation line và resolve target theo nghiệp vụ.
    def _prepare_evaluation_line_commands_from_template(self, kpi):
        """Build one2many commands for evaluation_line_ids from KPI template lines.

        - Preserves hierarchy preorder from the template tree.
        - Preserves section/note lines.
        """
        self.ensure_one()
        if not kpi:
            return []

        # Lấy template lines theo preorder đã chuẩn hoá để evaluation tree giữ nguyên hình dạng.
        template_lines = kpi.get_hierarchy_ordered_lines()

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
                            "parent_template_line_id": line.parent_line_id.id,
                            "sequence": line.sequence,
                            "is_section": True,
                            "display_type": (line.display_type or "line_section"),
                            "key_performance_area": line.key_performance_area,
                            "pillar_id": line.pillar_id.id,
                            "description": getattr(line, "description", False),
                            # Safe defaults for required KPI fields on section rows
                            "kpi_type": "auto",
                            "manual_scoring_type": False,
                            "target": 0.0,
                            "unit": False,
                            "weight": line.weight,
                            "wipeout_if_child_zero": bool(line.wipeout_if_child_zero),
                            "data_source_id": False,
                            "scoring_formula_id": False,
                            "is_auto": False,
                        }
                    )
                )
                continue

            # Resolve target động cho các KPI attendance cần target phụ thuộc vào kỳ đánh giá cụ thể.
            resolved_target = self._resolve_template_line_target(line)
            commands.append(
                fields.Command.create(
                    {
                        "kpi_line_id": line.id,
                        "parent_template_line_id": line.parent_line_id.id,
                        "sequence": line.sequence,
                        "pillar_id": line.pillar_id.id,
                        "key_performance_area": line.key_performance_area,
                        "description": getattr(line, "description", False),
                        "kpi_type": line.kpi_type,
                        "manual_scoring_type": line.manual_scoring_type,
                        "target": resolved_target,
                        "unit": line.unit.id or False,
                        "weight": line.weight,
                        "wipeout_if_child_zero": bool(line.wipeout_if_child_zero),
                        "data_source_id": line.data_source_id.id or False,
                        "scoring_formula_id": line.scoring_formula_id.id or False,
                        "is_auto": bool(line.is_auto),
                    }
                )
            )
        return commands

    def _rebuild_line_hierarchy_from_template(self):
        for evaluation in self:
            line_by_template = {
                line.kpi_line_id.id: line
                for line in evaluation.evaluation_line_ids
                if line.kpi_line_id
            }
            for line in evaluation.evaluation_line_ids:
                parent_line = (
                    line_by_template.get(line.parent_template_line_id.id)
                    if line.parent_template_line_id
                    else False
                )
                if line.parent_line_id != parent_line:
                    line.with_context(
                        skip_line_chatter_audit=True,
                        skip_score_tree_recompute=True,
                    ).write(
                        {"parent_line_id": parent_line.id if parent_line else False}
                    )

    # Recompute the KPI tree bottom-up so section lines receive scores immediately after generation.
    def _recompute_line_scores_after_hierarchy_rebuild(self):
        for evaluation in self:
            if evaluation.evaluation_line_ids:
                evaluation.evaluation_line_ids._recompute_score_tree()
                continue
            evaluation._compute_pillar_totals()
            evaluation._compute_performance_level()

    @api.onchange("kpi_id")
    def _onchange_kpi_id(self):
        if self.kpi_id:
            self.evaluation_line_ids = (
                self._prepare_evaluation_line_commands_from_template(self.kpi_id)
            )

    def action_compute_auto_kpi(self):
        """Compute Actual for auto KPI lines based on their template data source."""
        engine = self.env["hr.kpi.engine"]
        for evaluation in self:
            if evaluation.state in ["cancel", "completed"]:
                continue
            if not evaluation.employee_id:
                continue
            if not evaluation.kpi_id:
                continue
            date_from = evaluation.start_date
            date_to = evaluation.end_date
            for line in evaluation.evaluation_line_ids:
                if not line.is_auto or line.child_line_ids:
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
                    ev.with_context(
                        skip_line_chatter_audit=True
                    ).action_compute_auto_kpi()
                    ev._compute_pillar_totals()
                    ev._compute_performance_level()
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
    def action_open_kpi_dashboard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "kpi_individual_dashboard",
            "name": _("KPI Dashboard"),
            "context": {
                "default_employee_id": self.employee_id.id,
                "default_evaluation_id": self.id,
            },
        }

    # Chuẩn hóa HTML comment về plain text để dashboard có thể đếm và hiển thị ổn định.
    def _normalize_comment_text(self, value):
        # Chuyển HTML về text và gom khoảng trắng để bỏ qua các markup rỗng.
        plain_text = html2plaintext(value or "")
        return " ".join(plain_text.split()).strip()

    # Kiểm tra một evaluation line có comment ở phía employee hoặc manager hay không.
    def _line_has_dashboard_comment(self, line):
        self.ensure_one()

        # Chỉ giữ các line có nội dung comment thật sự sau khi loại bỏ HTML rỗng.
        employee_comment = self._normalize_comment_text(line.employee_comment)
        manager_comment = self._normalize_comment_text(line.manager_comment)
        return bool(employee_comment or manager_comment)

    # Tính tổng số comment employee + manager để roster dashboard hiển thị một con số duy nhất.
    def get_comment_count(self):
        self.ensure_one()
        comment_count = 0

        # Mỗi phía comment có nội dung được tính là một đơn vị độc lập.
        for line in self.evaluation_line_ids.filtered(lambda rec: not rec.is_section):
            if self._normalize_comment_text(line.employee_comment):
                comment_count += 1
            if self._normalize_comment_text(line.manager_comment):
                comment_count += 1

        return comment_count

    # Trả về danh sách KPI line có comment để popup dashboard phòng ban có thể render trực tiếp.
    def get_comment_popup_rows(self):
        self.ensure_one()
        rows = []

        # Giữ đúng thứ tự sequence của phiếu để popup phản ánh cùng cấu trúc với form đánh giá.
        comment_lines = self.evaluation_line_ids.filtered(
            lambda line: not line.is_section and self._line_has_dashboard_comment(line)
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

        # Serialize sang dict plain data để OWL popup dùng ngay qua RPC.
        for line in comment_lines:
            rows.append(
                {
                    "id": line.id,
                    "kpi_title": line.key_performance_area
                    or line.display_name
                    or _("KPI"),
                    "employee_comment": self._normalize_comment_text(
                        line.employee_comment
                    ),
                    "manager_comment": self._normalize_comment_text(
                        line.manager_comment
                    ),
                }
            )

        return {
            "evaluation_id": self.id,
            "evaluation_name": self.name or "",
            "employee_name": self.employee_id.name or "",
            "rows": rows,
        }

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

        # Employees can open their own individual dashboard, but they do not
        # have read access to department evaluations. Read only the linked
        # department score with sudo so the dashboard can show the related
        # department KPI without exposing the model.
        dept_eval = evaluation.sudo().dept_evaluation_id.sudo()
        dept_score = dept_eval.get_dept_kpi_score() if dept_eval else 0.0
        has_dept_evaluation = bool(dept_eval and dept_eval.state != "cancel")
        settings = self.env["res.config.settings"]
        score_scale = settings.get_score_scale_info()
        threshold_excellent, threshold_pass = evaluation._get_thresholds_for_record()
        chart_service = self.env["hr.kpi.dashboard.chart.service"]

        result = {
            "evaluation_id": evaluation.id,
            "score_scale": {
                **score_scale,
                "base": evaluation._get_evaluation_score_base(),
                "suffix": f" / {int(evaluation._get_evaluation_score_base())}",
            },
            "thresholds": {
                "excellent": threshold_excellent,
                "pass": threshold_pass,
            },
            "employee_name": evaluation.employee_id.name or "",
            "pillar_p2_1_name": evaluation.pillar_p2_1_name or "P2.1",
            "pillar_p2_2_name": evaluation.pillar_p2_2_name or "P2.2",
            "pillar_p3_ind_name": evaluation.pillar_p3_ind_name or "P3 Individual",
            "pillar_p3_dept_name": (dept_eval.pillar_p3_dept_name or "P3 Department")
            if dept_eval
            else "P3 Department",
            "period_id": evaluation.period_id.id if evaluation.period_id else False,
            "period_name": evaluation.period_id.name if evaluation.period_id else "",
            "period_type": evaluation.period_type or "",
            "start_date": str(evaluation.start_date) if evaluation.start_date else "",
            "end_date": str(evaluation.end_date) if evaluation.end_date else "",
            "total_p2_1": round(float(evaluation.total_p2_1 or 0.0), 2),
            "total_p2_2": round(float(evaluation.total_p2_2 or 0.0), 2),
            "total_p3_individual": round(
                float(evaluation.total_p3_individual or 0.0), 2
            ),
            "dept_kpi_score": round(float(dept_score), 2),
            "has_dept_evaluation": has_dept_evaluation,
            # Keep raw key for CSS class logic (levelClass)
            "performance_level": perf_key,
            # Translated label for display
            "performance_level_label": perf_label,
            "quantitative_table": self._get_quantitative_table_data(evaluation),
            # Keep every dashboard chart payload, including radar and detail charts, in one list.
            "charts": chart_service.build_dynamic_charts(
                evaluation, dashboard_kind="individual"
            ),
        }
        return result

    # ------------------------------------------------------------------
    # Quantitative Table
    # ------------------------------------------------------------------
    # Trả toàn bộ dòng KPI auto có dữ liệu định lượng để bảng log không bỏ sót các line con dưới section.
    # Chuẩn bị dữ liệu bảng KPI định lượng cho dashboard, tách riêng đơn vị đo thành một cột độc lập.
    def _get_quantitative_table_data(self, evaluation):
        # Chỉ bỏ section/note; các KPI auto là line con vẫn phải xuất hiện trong bảng chi tiết.
        lines = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.kpi_type == "auto"
        ).sorted(key=lambda l: (l.sequence or 0, l.id or 0))
        rows = []
        for line in lines:
            # Chuẩn hóa số liệu gốc trước khi format để variance và final score dùng cùng một nguồn.
            target = float(line.target or 0.0)
            actual = float(line.actual or 0.0)
            final = float(line.final_rating or 0.0)

            unit_text = line.unit.name if line.unit else ""
            # Giữ target/actual ở dạng số đã format gọn để frontend render trực tiếp.
            target_text = f"{target:g}"
            actual_text = f"{actual:g}"

            rows.append(
                {
                    "name": line.key_performance_area or "",
                    "unit_measure": unit_text,
                    "target": target_text,
                    "actual": actual_text,
                    "final_score": round(final, 2),
                }
            )
        return rows
