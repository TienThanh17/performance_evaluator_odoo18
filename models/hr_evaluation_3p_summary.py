import io
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
            raise UserError(
                "Vui lòng cài đặt thư viện xlsxwriter (pip install xlsxwriter)."
            )

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Kết Quả Đánh Giá 3P")

        # ==========================================
        # 1. ĐỊNH DẠNG (FORMATS)
        # ==========================================
        # Font chữ tiêu chuẩn
        font_name = "Arial"

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

        # Header formats với màu nền đặc trưng phân biệt các phần 3P
        header_base = {
            "font_name": font_name,
            "bold": True,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
        }

        header_main = workbook.add_format(
            {**header_base, "bg_color": "#D9D9D9"}
        )  # Xám nhạt
        header_p1 = workbook.add_format(
            {**header_base, "bg_color": "#BDD7EE"}
        )  # Xanh dương nhạt
        header_p2 = workbook.add_format(
            {**header_base, "bg_color": "#E2EFDA"}
        )  # Xanh lá nhạt
        header_p3 = workbook.add_format(
            {**header_base, "bg_color": "#F8CBAD"}
        )  # Cam nhạt

        # Cell formats
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
        sheet.set_column("E:F", 15)  # P1.1, P1.2
        sheet.set_column("G:K", 6)  # P2.1 TC1-TC5
        sheet.set_column("L:L", 8)  # P2.1 Hệ số
        sheet.set_column("M:AB", 5)  # P2.2 TC1-TC16
        sheet.set_column("AC:AC", 8)  # P2.2 Hệ số
        sheet.set_column("AD:AJ", 10)  # P3.1 Điểm, Trọng số...
        sheet.set_column("AK:AK", 8)  # Hệ số tổng KPI
        sheet.set_column("AL:AM", 15)  # Xếp loại, Ghi chú

        # Đóng băng dòng header
        sheet.freeze_panes(14, 4)

        # ==========================================
        # 3. PHẦN THÔNG TIN CHUNG (HEADER BÁO CÁO)
        # ==========================================
        sheet.merge_range("C2:H3", "BẢNG ĐÁNH GIÁ THEO PHƯƠNG PHÁP 3P", title_format)

        doc_info = "No. IT. 022025\nDate: 31/03/2026\nPage: 01/01"
        sheet.merge_range("AK2:AM4", doc_info, doc_info_format)

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
        # 4. VẼ BẢNG HEADER 3 TẦNG (ROWS 13, 14, 15)
        # ==========================================
        row_h1 = 13  # Excel Row 14 (Tầng 1)
        row_h2 = 14  # Excel Row 15 (Tầng 2)
        row_h3 = 15  # Excel Row 16 (Tầng 3)

        # Cột chung (Merge 3 dòng dọc)
        sheet.merge_range(row_h1, 0, row_h3, 0, "STT", header_main)
        sheet.merge_range(row_h1, 1, row_h3, 1, "Mã nhân viên", header_main)
        sheet.merge_range(row_h1, 2, row_h3, 2, "Họ và tên", header_main)
        sheet.merge_range(row_h1, 3, row_h3, 3, "Chức vụ", header_main)

        # Tầng 1 (Nhóm tiêu chí lớn)
        sheet.merge_range(
            row_h1, 4, row_h1, 5, "TIÊU CHÍ P1\n(lương theo vị trí)", header_p1
        )
        sheet.merge_range(
            row_h1, 6, row_h1, 28, "TIÊU CHÍ P2\n(lương theo năng lực)", header_p2
        )
        sheet.merge_range(
            row_h1,
            29,
            row_h1,
            36,
            "TIÊU CHÍ P3\n(lương theo hiệu quả công việc)",
            header_p3,
        )
        sheet.merge_range(row_h1, 37, row_h3, 37, "XẾP LOẠI", header_main)
        sheet.merge_range(row_h1, 38, row_h3, 38, "Ghi chú", header_main)

        # Tầng 2 (Nhóm phụ)
        sheet.write(row_h2, 4, "P1.1", header_p1)
        sheet.write(row_h2, 5, "P1.2", header_p1)
        sheet.merge_range(row_h2, 6, row_h2, 11, "P2.1 (Kiến thức)", header_p2)
        sheet.merge_range(row_h2, 12, row_h2, 28, "P2.2 (Kỹ năng, thái độ)", header_p2)
        sheet.merge_range(row_h2, 29, row_h2, 31, "P3.1.1 (KPI Cá nhân)", header_p3)
        sheet.merge_range(row_h2, 32, row_h2, 34, "P3.1.2 (KPI Phòng ban)", header_p3)
        sheet.merge_range(row_h2, 35, row_h2, 36, "Tổng KPI (P3.1)", header_p3)

        # Tầng 3 (Chi tiết TC)
        sheet.write(row_h3, 4, "Lương Cơ bản", header_p1)
        sheet.write(row_h3, 5, "Phụ cấp", header_p1)

        # P2.1 (TC1 -> TC5)
        p21_cols = ["TC1", "TC2", "TC3", "TC4", "TC5", "Hệ Số"]
        for i, text in enumerate(p21_cols):
            sheet.write(row_h3, 6 + i, text, header_p2)

        # P2.2 (TC1 -> TC16)
        p22_cols = [f"TC{i}" for i in range(1, 17)] + ["Hệ Số"]
        for i, text in enumerate(p22_cols):
            sheet.write(row_h3, 12 + i, text, header_p2)

        # P3.1.1 & P3.1.2
        p3_cols = [
            "Điểm thưởng\nbị trừ",
            "Điểm",
            "Trọng số",
            "Điểm thưởng\nbị trừ",
            "Điểm",
            "Trọng số",
            "Tổng trọng số",
            "Hệ số",
        ]
        for i, text in enumerate(p3_cols):
            sheet.write(row_h3, 29 + i, text, header_p3)

        # ==========================================
        # 5. DUMMY DATA LẤY TỪ MẪU CỦA BẠN
        # ==========================================
        dummy_data = [
            {
                "stt": 1,
                "ma_nv": "E802",
                "ten": "Phạm Tommy",
                "chuc_vu": "Leader",
                "p11": "Dành cho KT",
                "p12": "Dành cho KT",
                "p21": [33, 27, 15, 5, 3],
                "p21_hs": 0.83,
                "p22": [6, 5, 5, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 4, 3, 4],
                "p22_hs": 0.91,
                "p311": [0.2, 0.8, 0.48],
                "p312": [0, 1, 0.4],
                "p3_tong": [0.88, 0.7],
                "xep_loai": "",
                "ghi_chu": "Dành cho kế toán",
            },
            {
                "stt": 2,
                "ma_nv": "E804",
                "ten": "Huỳnh Trọng Đại",
                "chuc_vu": "Nhân Viên",
                "p11": "Dành cho KT",
                "p12": "Dành cho KT",
                "p21": [29, 27, 15, 4, 3],
                "p21_hs": 0.78,
                "p22": [6, 5, 5, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 4, 3, 4],
                "p22_hs": 0.91,
                "p311": [0, 1, 0.6],
                "p312": [0, 1, 0.4],
                "p3_tong": [1, 1],
                "xep_loai": "",
                "ghi_chu": "Dành cho kế toán",
            },
            {
                "stt": 3,
                "ma_nv": "E809",
                "ten": "Đỗ Minh Đường",
                "chuc_vu": "Nhân Viên (Thử việc)",
                "p11": "",
                "p12": "",
                "p21": ["", "", "", "", ""],
                "p21_hs": "",
                "p22": ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
                "p22_hs": "",
                "p311": ["", "", ""],
                "p312": ["", "", ""],
                "p3_tong": ["", ""],
                "xep_loai": "",
                "ghi_chu": "",
            },
        ]

        # In dữ liệu
        row = 16
        for d in dummy_data:
            sheet.write(row, 0, d["stt"], cell_center)
            sheet.write(row, 1, d["ma_nv"], cell_center)
            sheet.write(row, 2, d["ten"], cell_left)
            sheet.write(row, 3, d["chuc_vu"], cell_left)
            sheet.write(row, 4, d["p11"], cell_center)
            sheet.write(row, 5, d["p12"], cell_center)

            # Đổ dữ liệu P2.1 (TC1-TC5)
            for i, val in enumerate(d["p21"]):
                sheet.write(row, 6 + i, val, cell_num)
            sheet.write(row, 11, d["p21_hs"], cell_num)

            # Đổ dữ liệu P2.2 (TC1-TC16)
            for i, val in enumerate(d["p22"]):
                sheet.write(row, 12 + i, val, cell_num)
            sheet.write(row, 28, d["p22_hs"], cell_num)

            # Đổ dữ liệu P3
            sheet.write(row, 29, d["p311"][0], cell_num)
            sheet.write(row, 30, d["p311"][1], cell_num)
            sheet.write(row, 31, d["p311"][2], cell_num)

            sheet.write(row, 32, d["p312"][0], cell_num)
            sheet.write(row, 33, d["p312"][1], cell_num)
            sheet.write(row, 34, d["p312"][2], cell_num)

            sheet.write(row, 35, d["p3_tong"][0], cell_num)
            sheet.write(row, 36, d["p3_tong"][1], cell_num)

            sheet.write(row, 37, d["xep_loai"], cell_center)
            sheet.write(row, 38, d["ghi_chu"], cell_left)

            row += 1

       # --- III. ĐÁNH GIÁ & Ý KIẾN CỦA TBP/ NGƯỜI ĐÁNH GIÁ ---
        # Chuyển xuống dưới bảng kết quả một khoảng cách nhỏ
        start_row = row + 2 
        
        # Tiêu đề mục III
        sheet.write(start_row, 0, 'III', section_format)
        sheet.write(start_row, 1, 'ĐÁNH GIÁ & Ý KIẾN CỦA TBP/ NGƯỜI ĐÁNH GIÁ', section_format)

        # Header bảng III
        table_header = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter', 
            'border': 1, 'bg_color': '#D9D9D9', 'text_wrap': True
        })
        
        # Thiết lập độ rộng cột cho bảng III
        sheet.set_column('A:A', 5)   # STT
        sheet.set_column('B:C', 20)  # Họ và tên, Chức vụ
        sheet.set_column('D:D', 50)  # Đánh giá (để rộng để dễ viết)

        # Ghi header cột
        sheet.write(start_row + 1, 0, 'STT', table_header)
        sheet.write(start_row + 1, 1, 'Họ và tên', table_header)
        sheet.write(start_row + 1, 2, 'Chức vụ', table_header)
        sheet.write(start_row + 1, 3, 'Đánh giá và ý kiến trưởng bộ phận', table_header)
        
        # Đổ dữ liệu nhân viên vào bảng III
        table_cell_center = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
        table_cell_left = workbook.add_format({'align': 'left', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})

        current_row = start_row + 2
        for idx, line in enumerate(self.line_ids, start=1):
            sheet.write(current_row, 0, idx, table_cell_center)
            sheet.write(current_row, 1, line.employee_id.name or '', table_cell_left)
            sheet.write(current_row, 2, line.job_id.name or '', table_cell_left)
            # Ô trống để TBP điền tay hoặc để bạn nhập dữ liệu từ Odoo vào nếu có trường note
            sheet.write(current_row, 3, '', table_cell_left) 
            sheet.set_row(current_row, 40) # Tăng chiều cao dòng cho ô ý kiến
            current_row += 1

        workbook.close()
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
