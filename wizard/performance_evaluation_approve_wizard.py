from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


class PerformanceEvaluationApproveWizard(models.TransientModel):
    _name = "performance.evaluation.approve.wizard"
    _description = "Approve Performance Evaluation Wizard"

    evaluation_id = fields.Many2one(
        "hr.performance.evaluation",
        string="Evaluation",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_evaluation_id"),
    )
    notify_user_ids = fields.Many2many(
        "res.users",
        string="Notify Users",
        domain=[("active", "=", True), ("share", "=", False)],
        help="Select the users who should receive the approval notification.",
    )
    notification_message = fields.Html(
        string="Notification Message",
        sanitize=False,
        help="Review and edit the approval notification before sending it.",
    )

    # Tự động điền người nhận mặc định để quản lý chỉ cần chỉnh lại khi cần.
    def default_get(self, fields_list):
        values = super().default_get(fields_list)

        # Lấy phiếu đánh giá từ context để xác định người nhận mặc định hợp lý.
        evaluation = self.env["hr.performance.evaluation"].browse(
            self.env.context.get("default_evaluation_id")
        )
        if evaluation.exists():
            # Điền sẵn danh sách người nhận phổ biến để người duyệt chỉ cần tinh chỉnh nếu cần.
            default_users = (
                evaluation.employee_id.user_id | evaluation.manager_id.user_id
            ).filtered(lambda user: user.active and not user.share)
            values["notify_user_ids"] = [(6, 0, default_users.ids)]

            # Đổ sẵn nội dung notify mặc định lên wizard để người dùng có thể xem và chỉnh sửa.
            values["notification_message"] = (
                evaluation._get_approval_notification_body_html()
            )

        return values

    # Approve phiếu và gửi thông báo cho danh sách user được chọn trong wizard.
    def action_confirm(self):
        self.ensure_one()

        # Bảo vệ luồng xử lý khi context không truyền đúng phiếu cần approve.
        if not self.evaluation_id:
            raise UserError(_("The evaluation to approve could not be found."))

        # Thực hiện approve theo business logic chính của model.
        self.evaluation_id.action_approve()

        # Gửi notify nếu wizard có người nhận hợp lệ được chọn.
        if self.notify_user_ids:
            # Ưu tiên nội dung người dùng đã chỉnh trong wizard; nếu trống thì dùng mẫu mặc định.
            notification_message = (
                Markup(self.notification_message)
                if self.notification_message
                else self.evaluation_id._get_approval_notification_body_html()
            )
            self.evaluation_id._send_approval_notification(
                self.notify_user_ids,
                body_html=notification_message,
            )

        # Đóng wizard sau khi hoàn tất thao tác.
        return {"type": "ir.actions.act_window_close"}
