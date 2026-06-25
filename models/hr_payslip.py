from odoo import api, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # Map mã input payroll sang field đã được kế toán/chuyên môn nhập trên dòng tổng hợp 3P.
    PAYROLL_3P_INPUT_FIELD_MAP = {
        "P1_BASE": "p1_base_salary",
        "P1_ALLOW": "p1_allowance",
        "P21_SCORE": "p2_1_score_raw",
        "P22_SCORE": "p2_2_score_raw",
        "P31_SCORE": "p3_1_score",
        "P32_REVENUE": "p3_2_revenue",
    }

    # Tìm dòng 3P phù hợp nhất cho nhân viên và kỳ lương hiện tại để bơm input vào payroll.
    @api.model
    def _get_matching_3p_summary_line(self, contract, date_from, date_to):
        summary_line_model = self.env["hr.evaluation.3p.summary.line"]
        employee_domain = [("employee_id", "=", contract.employee_id.id)]
        exact_period_domain = [
            ("summary_id.start_date", "<=", date_from),
            ("summary_id.end_date", ">=", date_to),
        ]

        # Ưu tiên bản aggregate đã chốt xong và phủ đúng kỳ payslip để dữ liệu lương bám đúng tháng.
        summary_line = summary_line_model.search(
            employee_domain
            + [("summary_id.state", "=", "done")]
            + exact_period_domain,
            order="id desc",
            limit=1,
        )
        if summary_line:
            return summary_line

        # Nếu chưa done nhưng đã có summary đúng kỳ thì vẫn dùng để hỗ trợ demo và luồng nhập liệu thực tế.
        summary_line = summary_line_model.search(
            employee_domain + exact_period_domain,
            order="id desc",
            limit=1,
        )
        if summary_line:
            return summary_line

        # Fallback cuối cùng là lấy bản done mới nhất của nhân viên để payslip vẫn có dữ liệu tham chiếu.
        summary_line = summary_line_model.search(
            employee_domain + [("summary_id.state", "=", "done")],
            order="id desc",
            limit=1,
        )
        if summary_line:
            return summary_line

        # Khi chưa có summary done, lấy bản mới nhất bất kể trạng thái để tránh để input trống hoàn toàn.
        return summary_line_model.search(employee_domain, order="id desc", limit=1)

    # Quy đổi dòng 3P tìm được thành dict input code -> amount để payroll rule có thể đọc trực tiếp.
    @api.model
    def _get_3p_input_amounts(self, contract, date_from, date_to):
        summary_line = self._get_matching_3p_summary_line(contract, date_from, date_to)
        if not summary_line:
            return {}

        # Chỉ expose các field lương 3P đã được business chốt để tránh lẫn dữ liệu không phục vụ payroll.
        return {
            input_code: float(getattr(summary_line, field_name, 0.0) or 0.0)
            for input_code, field_name in self.PAYROLL_3P_INPUT_FIELD_MAP.items()
        }

    # Bổ sung amount cho payroll inputs từ summary 3P để salary rules OCA payroll tính lương được ngay.
    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        input_lines = super().get_inputs(contracts, date_from, date_to)
        if not input_lines:
            return input_lines

        # Tính trước bộ amount theo từng contract để không search lặp lại cho từng input code.
        contract_amounts_map = {}
        for contract in contracts:
            contract_amounts_map[contract.id] = self._get_3p_input_amounts(
                contract, date_from, date_to
            )

        # Gắn amount vào đúng input code mà structure hiện tại đang yêu cầu.
        for input_line in input_lines:
            contract_amounts = contract_amounts_map.get(input_line.get("contract_id"), {})
            if input_line.get("code") in contract_amounts:
                input_line["amount"] = contract_amounts[input_line["code"]]

        return input_lines
