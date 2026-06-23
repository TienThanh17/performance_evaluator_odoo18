from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PerformanceEvaluationApproveAllWizard(models.TransientModel):
    _name = "performance.evaluation.approve.all.wizard"
    _description = "Approve All Performance Evaluations Wizard"

    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        readonly=True,
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        string="Department Evaluation",
        readonly=True,
    )
    evaluation_ids = fields.Many2many(
        "hr.performance.evaluation",
        string="Evaluations",
        relation="perf_eval_approve_all_rel",
        readonly=True,
    )
    notify_user_ids = fields.Many2many(
        "res.users",
        string="Notify Users",
        domain=[("active", "=", True), ("share", "=", False)],
        help="Select the users who should receive the approval notification.",
    )
    evaluation_count = fields.Integer(
        string="Evaluation Count",
        compute="_compute_evaluation_count",
        readonly=True,
    )

    # Tự động nạp danh sách phiếu cùng phòng ban đã được action server truyền vào context.
    def default_get(self, fields_list):
        values = super().default_get(fields_list)

        # Đọc danh sách evaluation id từ context để wizard hiển thị đúng batch cần xác nhận.
        evaluation_ids = self.env.context.get("default_evaluation_ids") or []
        if evaluation_ids:
            values["evaluation_ids"] = [(6, 0, evaluation_ids)]

            # Gom danh sách người nhận mặc định từ toàn bộ phiếu trong batch để người dùng có thể tinh chỉnh.
            evaluations = self.env["hr.performance.evaluation"].browse(evaluation_ids).exists()
            default_users = self.env["res.users"]
            for evaluation in evaluations:
                # Gộp dần người nhận mặc định của từng phiếu vì mapped() không gọi được method name.
                default_users |= evaluation._get_default_approval_notification_users()
            values["notify_user_ids"] = [(6, 0, default_users.ids)]

        # Giữ lại phòng ban để người dùng xác nhận đúng phạm vi approve.
        department_id = self.env.context.get("default_department_id")
        if department_id:
            values["department_id"] = department_id

        # Giữ lại department evaluation để người dùng thấy đúng đợt đánh giá đang được approve.
        dept_evaluation_id = self.env.context.get("default_dept_evaluation_id")
        if dept_evaluation_id:
            values["dept_evaluation_id"] = dept_evaluation_id

        return values

    # Tính nhanh số lượng phiếu trong batch để hiển thị rõ cho người dùng trước khi xác nhận.
    @api.depends("evaluation_ids")
    def _compute_evaluation_count(self):
        for wizard in self:
            # Đếm số record hiện còn gắn với wizard sau khi context/default đã được resolve.
            wizard.evaluation_count = len(wizard.evaluation_ids)

    # Approve toàn bộ phiếu trong batch và gửi thông báo mặc định cho từng phiếu sau khi hoàn tất.
    def action_confirm(self):
        self.ensure_one()

        # Chặn xác nhận khi wizard không còn phiếu hợp lệ nào để xử lý.
        evaluations = self.evaluation_ids.exists()
        if not evaluations:
            raise UserError(_("No evaluations were found to approve."))

        # Chạy validate + chuyển trạng thái hoàn tất cho toàn bộ batch trước khi gửi notify.
        evaluations.action_approve_batch()

        # Chỉ gửi notify khi người dùng đã chọn ít nhất một người nhận trong wizard.
        if self.notify_user_ids:
            for evaluation in evaluations:
                # Dùng cùng một danh sách người nhận đã chọn cho toàn bộ phiếu trong batch approve.
                evaluation._send_approval_notification(self.notify_user_ids)

        # Đóng wizard và báo về client rằng batch approve đã chạy xong để giao diện quyết định có reload hay không.
        return {
            "type": "ir.actions.act_window_close",
            "infos": {"approved": True},
        }
