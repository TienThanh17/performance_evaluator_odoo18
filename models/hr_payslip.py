from odoo import api, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # Map mã input payroll sang field đã được kế toán/chuyên môn nhập trên dòng tổng hợp 3P.
    PAYROLL_3P_INPUT_FIELD_MAP = {
        "P1_BASE": "p1_base_salary",
        "P1_ALLOW": "p1_allowance",
        "P21_AMOUNT": "p2_1_base_amount",
        "P21_SCORE": "p2_1_score_raw",
        "P22_AMOUNT": "p2_2_base_amount",
        "P22_SCORE": "p2_2_score_raw",
        "P31_AMOUNT": "p3_1_base_amount",
        "P31_SCORE": "p3_1_score",
        "P32_AMOUNT": "p3_2_base_amount",
        "P32_REVENUE": "p3_2_revenue",
    }

    # Quy đổi điểm P3.1 thang 100 trên summary line về hệ số payroll cuối cùng.
    @api.model
    def _compute_p3_1_payroll_coefficient(self, p3_1_score):
        # Summary line lưu P3.1 ở thang 100 nên payroll chỉ cần đưa về hệ số 0..1.
        return float(p3_1_score or 0.0) / 100.0

    # Quy đổi tỷ lệ P3.2 nội bộ của percentage widget sang percent cho payroll rate.
    @api.model
    def _compute_p3_2_payroll_rate(self, p3_2_revenue):
        # Percentage widget lưu 120% dưới dạng 1.2, trong khi payroll rate cần 120 để total = amount * 120 / 100.
        return float(p3_2_revenue or 0.0) * 100.0

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
        amounts = {
            input_code: float(getattr(summary_line, field_name, 0.0) or 0.0)
            for input_code, field_name in self.PAYROLL_3P_INPUT_FIELD_MAP.items()
        }
        # Quy đổi riêng P3.1 về hệ số payroll vì field hiển thị trên Odoo đang giữ theo thang 100.
        amounts["P31_SCORE"] = self._compute_p3_1_payroll_coefficient(
            summary_line.p3_1_score
        )
        # Đưa P3.2 về percent để salary rule result_rate đọc đúng ngữ nghĩa 120 = 120%.
        amounts["P32_REVENUE"] = self._compute_p3_2_payroll_rate(
            summary_line.p3_2_revenue
        )
        return amounts

    # Rebuild worked days and payroll inputs before recomputing lines so repeated compute_sheet stays fresh.
    def _refresh_payslip_sources_before_compute(self):
        for payslip in self:
            # Skip records that are no longer supposed to be recomputed by business rule.
            if payslip.state in ("done", "cancel"):
                continue

            # Resolve contracts exactly like payroll line computation does, so refreshed inputs match the next compute.
            contracts = payslip._get_employee_contracts()
            if not contracts:
                continue

            # Regenerate worked days from the current dates to keep quantity-dependent rules up to date.
            worked_day_vals_list = payslip.get_worked_day_lines(
                contracts, payslip.date_from, payslip.date_to
            )
            payslip.write(
                {
                    "worked_days_line_ids": [(5, 0, 0)]
                    + [(0, 0, worked_day_vals) for worked_day_vals in worked_day_vals_list]
                }
            )

            # Regenerate payroll inputs from the latest 3P summary so rate/amount can be recomputed on every click.
            input_vals_list = payslip.get_inputs(contracts, payslip.date_from, payslip.date_to)
            payslip.write(
                {
                    "input_line_ids": [(5, 0, 0)]
                    + [(0, 0, input_vals) for input_vals in input_vals_list]
                }
            )

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

    # Force compute_sheet to always refresh payroll sources before rebuilding payslip lines.
    def compute_sheet(self):
        # Only recompute editable payslips; done/cancel slips must remain immutable.
        recomputable_slips = self.filtered(lambda payslip: payslip.state not in ("done", "cancel"))
        locked_slips = self - recomputable_slips

        # Refresh dynamic worked days and 3P inputs so repeated compute_sheet clicks always recalculate rate and amount.
        if recomputable_slips:
            recomputable_slips._refresh_payslip_sources_before_compute()
            super(HrPayslip, recomputable_slips).compute_sheet()

        # Preserve the base method contract by returning True even when every slip is locked.
        if locked_slips:
            return True
        return True
