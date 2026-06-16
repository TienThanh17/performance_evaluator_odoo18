import io
import xlsxwriter
import base64
from odoo import _, api, fields, models
from datetime import date


class HrEvaluation3PSummary(models.Model):
    _name = "hr.evaluation.3p.summary"
    _description = "Department 3P Summary"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_id desc, department_id, id desc"

    name = fields.Char(required=True, tracking=True, default="New")
    department_id = fields.Many2one(
        "hr.department",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    period_id = fields.Many2one(
        "hr.kpi.period",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    start_date = fields.Date(tracking=True)
    end_date = fields.Date(tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")],
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many(
        "hr.evaluation.3p.summary.line",
        "summary_id",
        string="Summary Lines",
    )
    line_count = fields.Integer(compute="_compute_line_count")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.onchange("period_id")
    def _onchange_period_id(self):
        for rec in self:
            if rec.period_id:
                rec.start_date = rec.period_id.date_start
                rec.end_date = rec.period_id.date_end

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("period_id") and not vals.get("start_date"):
                period = self.env["hr.kpi.period"].browse(vals["period_id"])
                vals.setdefault("start_date", period.date_start)
                vals.setdefault("end_date", period.date_end)
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = self._build_default_name(
                    vals.get("department_id"), vals.get("period_id")
                )
        return super().create(vals_list)

    @api.model
    def _build_default_name(self, department_id, period_id):
        department = (
            self.env["hr.department"].browse(department_id) if department_id else False
        )
        period = self.env["hr.kpi.period"].browse(period_id) if period_id else False
        if department and period:
            return _("3P Summary - %(department)s - %(period)s") % {
                "department": department.display_name,
                "period": period.display_name,
            }
        return _("3P Summary")

    def action_set_draft(self):
        self.write({"state": "draft"})
        return True

    # Find or create the summary header for a department and KPI period.
    @api.model
    def get_or_create_summary(self, department, period):
        department_id = department.id if hasattr(department, "id") else department
        period_id = period.id if hasattr(period, "id") else period
        summary = self.search(
            [
                ("department_id", "=", department_id),
                ("period_id", "=", period_id),
            ],
            order="id desc",
            limit=1,
        )
        if summary:
            return summary

        period_record = (
            period
            if hasattr(period, "date_start")
            else self.env["hr.kpi.period"].browse(period_id)
        )
        return self.create(
            {
                "department_id": department_id,
                "period_id": period_id,
                "start_date": period_record.date_start,
                "end_date": period_record.date_end,
            }
        )

    # Ensure the summary exists and refresh its lines from current evaluations.
    @api.model
    def ensure_summary_for_period(self, department, period):
        summary = self.get_or_create_summary(department, period)
        summary.action_aggregate()
        return summary

    def _get_department_evaluation(self):
        self.ensure_one()
        dept_eval = self.env["hr.department.performance.evaluation"].search(
            [
                ("department_id", "=", self.department_id.id),
                ("period_id", "=", self.period_id.id),
                ("state", "not in", ["draft", "cancel"]),
            ],
            order="id desc",
            limit=1,
        )
        return dept_eval

    # Chuẩn bị dữ liệu một dòng tổng hợp 3P và chốt snapshot điểm P3 theo cấu hình hiện tại.
    def _prepare_summary_line_vals(
        self,
        evaluation,
        dept_evaluation,
        p3_individual_weight,
        p3_department_weight,
    ):
        linked_dept_eval = evaluation.dept_evaluation_id or dept_evaluation

        # Lấy điểm thành phần của từng pillar trực tiếp từ phiếu KPI cá nhân hiện tại.
        p2_1_score = evaluation.get_weighted_score_by_pillar_code("p2_1")
        p2_2_score = evaluation.get_weighted_score_by_pillar_code("p2_2")
        p3_individual_score = evaluation.get_weighted_score_by_pillar_code(
            "p3_individual"
        )

        # Điểm KPI phòng ban dùng từ phiếu liên kết nếu có, ngược lại rơi về 0.
        p3_department_score = (
            linked_dept_eval.dept_kpi_score if linked_dept_eval else 0.0
        )
        p3_1_score = (
            (p3_individual_score * p3_individual_weight)
            + (p3_department_score * p3_department_weight)
        ) / 100

        # Trả về snapshot hoàn chỉnh để summary line không bị đổi khi Settings đổi sau đó.
        return {
            "employee_id": evaluation.employee_id.id,
            "job_id": evaluation.job_id.id,
            "evaluation_id": evaluation.id,
            "dept_evaluation_id": linked_dept_eval.id if linked_dept_eval else False,
            "p1_base_salary": 0.0,
            "p1_allowance": 0.0,
            "p2_1_score_raw": p2_1_score,
            "p2_2_score_raw": p2_2_score,
            "p3_individual_score": p3_individual_score,
            "p3_department_score": p3_department_score,
            "p3_1_score": p3_1_score,
        }

    # Tổng hợp lại summary lines và chốt snapshot điểm P3 theo bộ trọng số Settings hiện tại.
    def action_aggregate(self):
        settings = self.env["res.config.settings"]
        p3_individual_weight, p3_department_weight = settings.get_p3_summary_weights()

        for summary in self:
            # Lấy phiếu KPI phòng ban của kỳ hiện tại để làm nguồn fallback chung.
            dept_evaluation = summary._get_department_evaluation()
            evaluations = self.env["hr.performance.evaluation"].search(
                [
                    ("department_id", "=", summary.department_id.id),
                    ("period_id", "=", summary.period_id.id),
                    ("state", "!=", "cancel"),
                ],
                order="employee_id, id",
            )

            # Rebuild toàn bộ line để giữ dữ liệu summary đồng bộ với snapshot mới nhất.
            commands = [fields.Command.clear()]
            for evaluation in evaluations:
                linked_dept_evaluation = (
                    evaluation.dept_evaluation_id or dept_evaluation
                )
                commands.append(
                    fields.Command.create(
                        summary._prepare_summary_line_vals(
                            evaluation,
                            linked_dept_evaluation,
                            p3_individual_weight,
                            p3_department_weight,
                        )
                    )
                )

            # Ghi trạng thái done cùng batch line mới để summary phản ánh đúng lần aggregate này.
            summary.write(
                {
                    "line_ids": commands,
                    "state": "done",
                }
            )
        return True

    def action_export_excel(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            from odoo.exceptions import UserError

            raise UserError(
                "Vui lòng cài đặt thư viện xlsxwriter (pip install xlsxwriter)."
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Kết Quả Đánh Giá 3P")

        # ==========================================
        # 1. ĐỊNH DẠNG (FORMATS)
        # ==========================================
        font_name = "Times New Roman"

        title_format = workbook.add_format(
            {
                "font_name": font_name,
                "bold": True,
                "font_size": 16,
                "align": "center",
                "valign": "vcenter",
            }
        )
        doc_info_format = workbook.add_format(
            {
                "font_name": font_name,
                "font_size": 10,
                "align": "right",
                "valign": "top",
                "text_wrap": True,
            }
        )
        section_format = workbook.add_format(
            {"font_name": font_name, "bold": True, "font_size": 11, "valign": "vcenter"}
        )
        label_format = workbook.add_format(
            {"font_name": font_name, "font_size": 11, "valign": "vcenter"}
        )
        note_format = workbook.add_format(
            {
                "font_name": font_name,
                "font_size": 10,
                "italic": True,
                "valign": "vcenter",
                "font_color": "red",
            }
        )

        header_base = {
            "font_name": font_name,
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        }
        header_main = workbook.add_format({**header_base, "bg_color": "#D9D9D9"})

        # --- CÁC MÃ MÀU MỚI CHO HEADER ---
        format_p1 = workbook.add_format(
            {**header_base, "bg_color": "#FAD9D6"}
        )  # Tiêu chí P1
        format_p2 = workbook.add_format(
            {**header_base, "bg_color": "#FEF1CC"}
        )  # Tiêu chí P2
        format_p3 = workbook.add_format(
            {**header_base, "bg_color": "#D2F1DA"}
        )  # Tiêu chí P3

        format_white = workbook.add_format(
            {**header_base, "bg_color": "#FFFFFF"}
        )  # Các cell P2.1, P2.2, P3.1...
        format_gray = workbook.add_format(
            {**header_base, "bg_color": "#D8D8D8"}
        )  # P1.1, P1.2, P3.2 và con của nó
        format_t4_blue = workbook.add_format(
            {**header_base, "bg_color": "#D9F1F3"}
        )  # Từ TC1 đến Hệ số Tổng KPI

        # --- MÃ MÀU CHO CÁC CELL DATA BÊN DƯỚI CỘT HỆ SỐ ---
        # (Dùng chữ trắng để nổi bật trên nền xanh lá đậm #34A853)
        cell_heso_data = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "bg_color": "#34A853",
                "font_color": "#FFFFFF",
                "bold": True,
            }
        )

        cell_center = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }
        )
        cell_left = workbook.add_format(
            {"font_name": font_name, "align": "left", "valign": "vcenter", "border": 1}
        )
        cell_num = workbook.add_format(
            {
                "font_name": font_name,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
            }
        )

        # ==========================================
        # 2. CẤU HÌNH CỘT (COLUMN WIDTH)
        # ==========================================
        sheet.set_column("A:A", 5)  # STT
        sheet.set_column("B:B", 12)  # Mã NV
        sheet.set_column("C:C", 22)  # Họ Tên
        sheet.set_column("D:D", 18)  # Chức vụ
        sheet.set_column("E:F", 18)  # P1.1, P1.2 (Mức lương)
        sheet.set_column("G:L", 7)  # P2.1 (TC1-TC5 + Hệ số)
        sheet.set_column("M:AB", 7)  # P2.2 (TC1-TC16)
        sheet.set_column("AC:AC", 8)  # P2.2 Hệ số

        # Cấu hình độ rộng cho toàn bộ các cột con của Tiêu chí P3
        sheet.set_column("AD:AL", 18)  # Từ cột P3.1.1 cho tới Hệ số của P3.2

        # SỬA Ở ĐÂY: Tăng width cho cột "Đánh giá..." (Cột AM) và bỏ cột Xếp loại
        sheet.set_column("AM:AM", 20)

        # Đóng băng dòng header
        sheet.freeze_panes(0, 4)

        # ==========================================
        # 3. PHẦN THÔNG TIN CHUNG (HEADER BÁO CÁO)
        # ==========================================
        sheet.merge_range("C2:H3", "BẢNG ĐÁNH GIÁ THEO PHƯƠNG PHÁP 3P", title_format)
        doc_info = "No. IT. 022025\nDate: 31/03/2026\nPage: 01/01"
        sheet.merge_range("AG2:AI4", doc_info, doc_info_format)

        sheet.write("A6", "I", section_format)
        sheet.write("B6", "THÔNG TIN CHUNG", section_format)
        sheet.write("C7", "Bộ phận được đánh giá:", label_format)
        sheet.write("D7", "Công nghệ thông tin (IT)", label_format)
        sheet.write("C8", "Tháng đánh giá:", label_format)
        sheet.write("D8", "04/2026", label_format)
        sheet.write("C9", "Người đánh giá:", label_format)
        sheet.write("D9", "Võ Văn Trọng", label_format)
        sheet.write("C10", "Tiêu chí đánh giá:", label_format)
        sheet.write("D10", "Phương pháp 3P với trọng số", label_format)

        note_text = "Chú ý: đây là bảng tổng hợp Lương 3P của nhân viên phòng ban. Cuối mỗi tháng, trưởng bộ phận sẽ đánh giá nhân viên các tiêu chí P2.1; P2.2; P3.1.1; P3.1.2 tại các sheet tương ứng"
        sheet.merge_range("A11:M11", note_text, note_format)

        sheet.write("A12", "II", section_format)
        sheet.write("B12", "BẢNG TỔNG HỢP KẾT QUẢ", section_format)

        # ==========================================
        # 4. VẼ BẢNG HEADER 4 TẦNG (ROWS 14, 15, 16, 17)
        # ==========================================
        row_h1 = 13  # Excel Row 14 (Tầng 1 - Nhóm Tiêu chí chính)
        row_h2 = 14  # Excel Row 15 (Tầng 2 - Thành phần P)
        row_h3 = 15  # Excel Row 16 (Tầng 3 - Tên KPI / Chỉ số)
        row_h4 = 16  # Excel Row 17 (Tầng 4 - Chi tiết thành phần con)

        # THÊM MỚI Ở ĐÂY: Tăng chiều cao (height) của các dòng header để thấy đủ chữ bị rớt dòng
        sheet.set_row(row_h1, 40)
        sheet.set_row(row_h2, 30)
        sheet.set_row(row_h3, 40)
        sheet.set_row(row_h4, 40)

        # Cột chung kéo dài dọc qua cả 4 tầng header
        sheet.merge_range(row_h1, 0, row_h4, 0, "STT", header_main)
        sheet.merge_range(row_h1, 1, row_h4, 1, "Mã nhân viên", header_main)
        sheet.merge_range(row_h1, 2, row_h4, 2, "Họ và tên", header_main)
        sheet.merge_range(row_h1, 3, row_h4, 3, "Chức vụ", header_main)

        # --- TẦNG 1 ---
        sheet.merge_range(
            row_h1, 4, row_h1, 5, "TIÊU CHÍ P1\n(lương theo vị trí)", format_p1
        )
        sheet.merge_range(
            row_h1, 6, row_h1, 28, "TIÊU CHÍ P2\n(lương theo năng lực)", format_p2
        )
        sheet.merge_range(
            row_h1,
            29,
            row_h1,
            37,
            "TIÊU CHÍ P3\n(lương theo hiệu quả công việc)",
            format_p3,
        )

        sheet.merge_range(
            row_h1, 38, row_h4, 38, "Đánh giá", header_main
        )

        # --- TIÊU CHÍ P1 ---
        sheet.merge_range(row_h2, 4, row_h3, 4, "P1.1", format_gray)
        sheet.write(row_h4, 4, "Mức lương", format_gray)

        sheet.merge_range(row_h2, 5, row_h3, 5, "P1.2", format_gray)
        sheet.write(row_h4, 5, "Mức lương", format_gray)

        # --- TIÊU CHÍ P2 ---
        sheet.merge_range(row_h2, 6, row_h3, 11, "P2.1", format_white)
        for i, col in enumerate(range(6, 11)):
            sheet.write(row_h4, col, f"TC{i + 1}", format_t4_blue)
        sheet.write(row_h4, 11, "Hệ số", format_t4_blue)

        sheet.merge_range(row_h2, 12, row_h3, 28, "P2.2", format_white)
        for i, col in enumerate(range(12, 28)):
            sheet.write(row_h4, col, f"TC{i + 1}", format_t4_blue)
        sheet.write(row_h4, 28, "Hệ số", format_t4_blue)

        # --- TIÊU CHÍ P3 ---
        # Tầng 2
        sheet.merge_range(row_h2, 29, row_h2, 36, "P3.1", format_white)
        sheet.merge_range(row_h2, 37, row_h3, 37, "P3.2\n(theo doanh thu)", format_gray)
        sheet.write(row_h4, 37, "Hệ số", format_gray)

        # Tầng 3
        sheet.merge_range(row_h3, 29, row_h3, 31, "P3.1.1\n(KPI Cá nhân)", format_white)
        sheet.merge_range(
            row_h3, 32, row_h3, 34, "P3.1.2\n(KPI Phòng ban)", format_white
        )
        sheet.merge_range(row_h3, 35, row_h3, 36, "Tổng KPI\n(P3.1)", format_white)

        # Tầng 4
        # Dưới P3.1.1
        sheet.write(row_h4, 29, "Điểm thưởng\nbị trừ", format_t4_blue)
        sheet.write(row_h4, 30, "Điểm", format_t4_blue)
        sheet.write(row_h4, 31, "Trọng số", format_t4_blue)
        # Dưới P3.1.2
        sheet.write(row_h4, 32, "Điểm thưởng\nbị trừ", format_t4_blue)
        sheet.write(row_h4, 33, "Điểm", format_t4_blue)
        sheet.write(row_h4, 34, "Trọng số", format_t4_blue)
        # Dưới Tổng KPI (P3.1)
        sheet.write(row_h4, 35, "Tổng trọng số", format_t4_blue)
        sheet.write(row_h4, 36, "Hệ số", format_t4_blue)

        # ==========================================
        # 5. DỮ LIỆU MẪU (DUMMY DATA)
        # ==========================================
        dummy_data = [
            [
                1,
                "E802",
                "Phạm Tommy",
                "Leader",
                "dành cho kế toán",
                "dành cho kế toán",
                5,
                4,
                5,
                4,
                5,
                1.0,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                4,
                1.0,
                0.2,
                85,
                0.8,
                0,
                90,
                1.0,
                0.48,
                0.88,
                "dành cho kế toán",
                "",
            ],
            [
                2,
                "E804",
                "Huỳnh Trọng Đại",
                "Nhân Viên",
                "dành cho kế toán",
                "dành cho kế toán",
                4,
                4,
                4,
                4,
                4,
                0.9,
                4,
                3,
                4,
                3,
                4,
                3,
                4,
                3,
                4,
                3,
                4,
                3,
                4,
                3,
                4,
                3,
                0.8,
                0,
                75,
                1.0,
                0,
                80,
                1.0,
                0.4,
                1.0,
                "dành cho kế toán",
                "",
            ],
        ]

        row = 17
        for line in dummy_data:
            sheet.write(row, 0, line[0], cell_center)
            sheet.write(row, 1, line[1], cell_center)
            sheet.write(row, 2, line[2], cell_left)
            sheet.write(row, 3, line[3], cell_left)

            # SỬA Ở ĐÂY: Giảm vòng lặp đi 1 cột (từ 40 xuống 39)
            for col_idx in range(4, 39):
                val = line[col_idx]
                
                # SỬA Ở ĐÂY: Nếu là các cột Hệ số (index: 11, 28, 36, 37) thì đổ màu nền #34A853
                if col_idx in [11, 28, 36, 37]:
                    sheet.write(row, col_idx, val, cell_heso_data)
                elif isinstance(val, (int, float)):
                    sheet.write(row, col_idx, val, cell_num)
                else:
                    align_format = cell_left if col_idx == 38 else cell_center
                    sheet.write(row, col_idx, val, align_format)
            row += 1

        # --- III. ĐÁNH GIÁ & Ý KIẾN CỦA TBP/ NGƯỜI ĐÁNH GIÁ ---
        # Chuyển xuống dưới bảng kết quả một khoảng cách nhỏ
        start_row = row + 2

        # Tiêu đề mục III
        sheet.write(start_row, 0, "III", section_format)
        sheet.write(
            start_row, 1, "ĐÁNH GIÁ & Ý KIẾN CỦA TBP/ NGƯỜI ĐÁNH GIÁ", section_format
        )

        # Header bảng III
        table_header = workbook.add_format(
            {
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "bg_color": "#D9D9D9",
                "text_wrap": True,
            }
        )

        # Ghi header cột và merge cell theo đúng cấu trúc của bảng trên
        sheet.set_row(start_row + 1, 30)  # Chiều cao dòng header
        sheet.write(start_row + 1, 0, "STT", table_header)
        sheet.write(start_row + 1, 1, "Mã nhân viên", table_header)

        # Merge cột C và D cho "Họ và tên" (để lấp đầy khoảng trống của cột Chức vụ bảng trên)
        sheet.merge_range(start_row + 1, 2, start_row + 1, 3, "Họ và tên", table_header)

        # Merge từ cột E (index 4 - bắt đầu Tiêu chí P1) đến cột AC (index 28 - kết thúc Tiêu chí P2)
        sheet.merge_range(
            start_row + 1,
            4,
            start_row + 1,
            28,
            "Đánh giá và ý kiến trưởng bộ phận",
            table_header,
        )

        # Đổ dữ liệu nhân viên vào bảng III từ dummy_data
        table_cell_center = workbook.add_format(
            {"align": "center", "valign": "vcenter", "border": 1}
        )
        table_cell_left = workbook.add_format(
            {"align": "left", "valign": "vcenter", "border": 1, "text_wrap": True}
        )

        current_row = start_row + 2
        for line in dummy_data:
            sheet.set_row(current_row, 40)  # Tăng chiều cao dòng cho ô ý kiến

            sheet.write(current_row, 0, line[0], table_cell_center)  # STT
            sheet.write(current_row, 1, line[1], table_cell_center)  # Mã NV

            # Merge cột C và D ghi Họ tên
            sheet.merge_range(current_row, 2, current_row, 3, line[2], table_cell_left)

            # Merge cột từ E đến AC ghi Ý kiến đánh giá (Lấy từ phần tử cuối cùng của dummy_data)
            sheet.merge_range(
                current_row, 4, current_row, 28, line[-1], table_cell_left
            )

            current_row += 1

        workbook.close()

        # Phần code return base64/action url lưu file bạn tiếp tục giữ theo logic hiện tại
        output.seek(0)
        file_data = output.read()
        output.close()

        # Tạo file đính kèm để tải xuống
        attachment = self.env["ir.attachment"].create(
            {
                "name": "Mau_Bang_Tong_Hop_3P_Dummy.xlsx",
                "type": "binary",
                "datas": base64.b64encode(file_data),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


class HrEvaluation3PSummaryLine(models.Model):
    _name = "hr.evaluation.3p.summary.line"
    _description = "Department 3P Summary Line"
    _order = "employee_id, id"

    summary_id = fields.Many2one(
        "hr.evaluation.3p.summary",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
    )
    job_id = fields.Many2one(
        "hr.job",
        ondelete="set null",
    )
    evaluation_id = fields.Many2one(
        "hr.performance.evaluation",
        ondelete="set null",
    )
    dept_evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation",
        ondelete="set null",
    )
    p1_base_salary = fields.Float(
        string="P1.1 - Position Salary",
        digits=(16, 0),
        default=0.0,
        help="Base salary for the employee's position. Filled by accounting.",
    )
    p1_allowance = fields.Float(
        string="P1.2 - Title or Professional Allowance",
        digits=(16, 0),
        default=0.0,
        help="Responsibility or professional allowance. Filled by accounting.",
    )
    p2_1_score_raw = fields.Float(string="P2.1")
    p2_2_score_raw = fields.Float(string="P2.2")
    p3_individual_score = fields.Float(string="P3.1.1")
    p3_department_score = fields.Float(string="P3.1.2")
    p3_1_score = fields.Float(string="P3.1", default=0.0)
