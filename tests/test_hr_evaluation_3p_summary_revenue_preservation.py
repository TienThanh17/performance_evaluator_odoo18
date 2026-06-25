from odoo.tests.common import TransactionCase


class TestHrEvaluation3PSummaryRevenuePreservation(TransactionCase):
    # Chuẩn bị một summary thật từ dữ liệu seed để test đi qua đúng flow aggregate đang chạy ở production.
    def setUp(self):
        super().setUp()
        self.DepartmentEvaluation = self.env["hr.department.performance.evaluation"]
        self.Summary = self.env["hr.evaluation.3p.summary"]
        self.SummaryLine = self.env["hr.evaluation.3p.summary.line"]

        # Dùng một phiếu KPI phòng ban đang hoạt động để aggregate sinh line thật từ dữ liệu seed.
        self.department_evaluation = self.DepartmentEvaluation.search(
            [("state", "!=", "cancel")],
            order="id asc",
            limit=1,
        )
        self.assertTrue(
            self.department_evaluation,
            "Expected at least one active department evaluation from seeded data.",
        )

        # Tạo hoặc lấy summary hiện hữu rồi aggregate lại để mỗi test luôn bắt đầu từ snapshot mới nhất.
        self.summary = self.Summary.get_or_create_summary_for_department_evaluation(
            self.department_evaluation
        )
        self.summary.action_aggregate()
        self.assertTrue(
            self.summary.line_ids,
            "Expected aggregate to create at least one 3P summary line.",
        )

    # Lấy một line mục tiêu ổn định để các test thao tác trên cùng kiểu dữ liệu thật.
    def _get_target_line(self):
        # Re-browse summary trước khi đọc line để tránh dùng cache cũ sau các lần aggregate.
        summary = self.Summary.browse(self.summary.id)
        return summary.line_ids.sorted(lambda line: (line.employee_id.id, line.id))[:1]

    # Đọc lại toàn bộ line của một nhân viên trong summary hiện tại để assert sau aggregate.
    def _get_employee_lines(self, employee):
        # Query lại trực tiếp từ model line để chắc chắn đang nhìn dữ liệu đã được write xong.
        return self.SummaryLine.search(
            [
                ("summary_id", "=", self.summary.id),
                ("employee_id", "=", employee.id),
            ],
            order="id asc",
        )

    # Đảm bảo aggregate chỉ recompute field hệ thống và không đụng manual input trên line hiện hữu.
    def test_action_aggregate_preserves_manual_inputs_on_existing_line(self):
        target_line = self._get_target_line()

        # Mô phỏng kế toán nhập tay nhiều field rồi bấm aggregate lại trên cùng summary.
        target_line.write(
            {
                "p1_base_salary": 111.0,
                "p1_allowance": 222.0,
                "p2_1_base_amount": 333.0,
                "p2_2_base_amount": 444.0,
                "p3_1_base_amount": 555.0,
                "p3_2_base_amount": 666.0,
                "p3_2_revenue": 777.0,
            }
        )
        self.summary.action_aggregate()

        # Đọc lại đúng line cũ để xác nhận aggregate chỉ làm mới KPI score chứ không wipe input tay.
        refreshed_line = self.SummaryLine.browse(target_line.id)
        self.assertEqual(refreshed_line.p1_base_salary, 111.0)
        self.assertEqual(refreshed_line.p1_allowance, 222.0)
        self.assertEqual(refreshed_line.p2_1_base_amount, 333.0)
        self.assertEqual(refreshed_line.p2_2_base_amount, 444.0)
        self.assertEqual(refreshed_line.p3_1_base_amount, 555.0)
        self.assertEqual(refreshed_line.p3_2_base_amount, 666.0)
        self.assertEqual(refreshed_line.p3_2_revenue, 777.0)

    # Đảm bảo aggregate không copy revenue sang line mới khi cùng nhân viên có thêm evaluation khác.
    def test_action_aggregate_does_not_copy_p3_2_revenue_to_new_line(self):
        target_line = self._get_target_line()
        original_evaluation = target_line.evaluation_id

        # Nhân bản evaluation để ép aggregate đi qua nhánh phải tạo thêm line mới cho cùng nhân viên.
        duplicate_evaluation = original_evaluation.copy({"name": False})

        # Ghi revenue tay trên line hiện tại trước khi aggregate để kiểm tra line mới không bị copy theo.
        target_line.write({"p3_2_revenue": 345.0})
        self.summary.action_aggregate()

        # Lấy lại toàn bộ line của cùng nhân viên để xác nhận line cũ giữ nguyên revenue,
        # còn line mới dùng default của model vì aggregate không được đụng tới field này.
        employee_lines = self._get_employee_lines(target_line.employee_id)
        self.assertEqual(len(employee_lines), 2)
        revenues_by_evaluation = {
            line.evaluation_id.id: line.p3_2_revenue for line in employee_lines
        }
        self.assertEqual(revenues_by_evaluation[original_evaluation.id], 345.0)
        self.assertEqual(revenues_by_evaluation[duplicate_evaluation.id], 0.0)
        self.assertEqual(
            set(employee_lines.mapped("evaluation_id").ids),
            {original_evaluation.id, duplicate_evaluation.id},
        )
