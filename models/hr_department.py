from odoo import models, fields, api


class HrDepartment(models.Model):
    _inherit = "hr.department"

    # ── DEPRECATED: department_score — điểm tổng hợp kiểu cũ (α×dept + β×avg_individual) ──
    # Giữ trong DB để backward compatible. Ẩn khỏi mọi view.
    department_score = fields.Float(
        compute="_compute_department_score_custom",
        string="Department KPI Score (latest period)",
        deprecated=True,
        groups="base.group_no_one",
    )

    # ── DEPRECATED: department_level — xếp loại dựa trên department_score cũ ──
    department_level = fields.Selection(
        [("excellent", "Excellent"), ("pass", "Pass"), ("fail", "Fail")],
        compute="_compute_department_score_custom",
        string="Performance Level",
        deprecated=True,
        groups="base.group_no_one",
    )

    # ── MỚI: avg_final_score — trung bình final_score cá nhân của phòng ban ──
    # Không store=True vì đây là summary realtime, không cần lưu DB.
    # Dùng để BGĐ so sánh tổng thể giữa các phòng ban.
    avg_final_score = fields.Float(
        string="Average Final Score",
        compute="_compute_avg_final_score",
        help="Average final_score of all employees in this department "
        "whose evaluations are in completed state. "
        "Used to compare overall performance across departments.",
    )

    def _compute_department_score_custom(self):
        """Giữ nguyên logic cũ để không break dữ liệu đang lưu trong DB.
        Các field này đã được đánh dấu deprecated và ẩn khỏi UI.
        """
        for rec in self:
            eval_record = self.env["hr.department.performance.evaluation"].search(
                [("department_id", "=", rec.id), ("state", "=", "approved")],
                order="end_date desc",
                limit=1,
            )

            if eval_record:
                rec.department_score = eval_record.department_score
                rec.department_level = eval_record.department_level
            else:
                rec.department_score = 0.0
                rec.department_level = False

    @api.depends_context("company")
    def _compute_avg_final_score(self):
        """Tính trung bình final_score của tất cả nhân viên trong phòng ban
        có evaluation ở trạng thái 'completed' và final_score > 0.

        Không lọc theo kỳ cụ thể — lấy tất cả completed evaluations
        để phản ánh toàn bộ lịch sử đánh giá.
        """
        for dept in self:
            # Lấy tất cả evaluations completed của nhân viên trong phòng
            # State hợp lệ của hr.performance.evaluation: 'completed' (không có 'approved')
            evals = (
                self.env["hr.performance.evaluation"]
                .sudo()
                .search(
                    [
                        ("employee_id.department_id", "=", dept.id),
                        ("state", "=", "completed"),
                        ("final_score", ">", 0),
                    ]
                )
            )
            if evals:
                dept.avg_final_score = sum(evals.mapped("final_score")) / len(evals)
            else:
                dept.avg_final_score = 0.0
