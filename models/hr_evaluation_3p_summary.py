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

        # Khởi tạo luồng ghi file
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Kết Quả Đánh Giá 3P")  # [cite: 1]

        # --- ĐỊNH DẠNG (FORMATS) ---
        title_format = workbook.add_format(
            {"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"}
        )
        section_format = workbook.add_format(
            {"bold": True, "font_size": 11, "valign": "vcenter"}
        )
        info_format = workbook.add_format({"font_size": 11, "valign": "vcenter"})
        header_format = workbook.add_format(
            {
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "text_wrap": True,
                "bg_color": "#D9D9D9",
            }
        )
        cell_center = workbook.add_format(
            {"align": "center", "valign": "vcenter", "border": 1}
        )
        cell_left = workbook.add_format(
            {"align": "left", "valign": "vcenter", "border": 1}
        )
        cell_num = workbook.add_format(
            {
                "align": "right",
                "valign": "vcenter",
                "border": 1,
                "num_format": "#,##0.00",
            }
        )

        # --- THIẾT LẬP CHIỀU RỘNG CỘT ---
        sheet.set_column("A:A", 5)  # STT
        sheet.set_column("B:B", 15)  # Mã nhân viên
        sheet.set_column("C:C", 25)  # Họ và tên
        sheet.set_column("D:D", 20)  # Chức vụ
        sheet.set_column("E:H", 15)  # P1, P2
        sheet.set_column("I:K", 15)  # P3

        # --- THÔNG TIN GÓC PHẢI ---
        # [cite: 1]
        sheet.write(
            "J1", f"Date: {date.today().strftime('%d/%m/%Y')}\nPage: 01/01", info_format
        )

        # --- TIÊU ĐỀ CHÍNH ---
        sheet.merge_range(
            "A2:K3", "BẢNG ĐÁNH GIÁ THEO PHƯƠNG PHÁP 3P", title_format
        )  # [cite: 1]

        # --- I. THÔNG TIN CHUNG ---
        sheet.write("A5", "I", section_format)  # [cite: 1]
        sheet.write("B5", "THÔNG TIN CHUNG", section_format)  # [cite: 1]

        sheet.write("C6", "Bộ phận được đánh giá:", info_format)  # [cite: 1]
        sheet.write("D6", self.department_id.name if self.department_id else "")

        sheet.write("C7", "Kỳ đánh giá:", info_format)  # [cite: 1]
        sheet.write("D7", self.period_id.name if self.period_id else "")

        sheet.write("C8", "Tiêu chí đánh giá:", info_format)  # [cite: 1]
        sheet.write("D8", "Phương pháp 3P với trọng số")  # [cite: 1]

        # --- II. BẢNG TỔNG HỢP KẾT QUẢ ---
        sheet.write("A10", "II", section_format)  # [cite: 1]
        sheet.write("B10", "BẢNG TỔNG HỢP KẾT QUẢ", section_format)  # [cite: 1]

        # Header Dòng 1 (Gộp ô)
        sheet.merge_range("A11:A12", "STT", header_format)  # [cite: 1]
        sheet.merge_range("B11:B12", "Mã nhân viên", header_format)  # [cite: 1]
        sheet.merge_range("C11:C12", "Họ và tên", header_format)  # [cite: 1]
        sheet.merge_range("D11:D12", "Chức vụ", header_format)  # [cite: 1]

        sheet.merge_range(
            "E11:F11", "TIÊU CHÍ P1\n(lương theo vị trí)", header_format
        )  # [cite: 1]
        sheet.merge_range(
            "G11:H11", "TIÊU CHÍ P2\n(lương theo năng lực)", header_format
        )  # [cite: 1]
        sheet.merge_range(
            "I11:K11", "TIÊU CHÍ P3\n(lương theo hiệu quả công việc)", header_format
        )  #

        # Header Dòng 2 (Chi tiết)
        sheet.write("E12", "P1.1\n(Lương cơ bản)", header_format)  #
        sheet.write("F12", "P1.2\n(Phụ cấp)", header_format)  #
        sheet.write("G12", "P2.1\n(Kiến thức)", header_format)  #
        sheet.write("H12", "P2.2\n(Kỹ năng)", header_format)  #
        sheet.write("I12", "P3.1.1\nKPI Cá nhân", header_format)  #
        sheet.write("J12", "P3.1.2\nKPI Phòng ban", header_format)  #
        sheet.write("K12", "P3.1\nTổng KPI", header_format)  #

        # --- ĐỔ DỮ LIỆU ---
        row = 12
        for idx, line in enumerate(self.line_ids, start=1):
            # Cố gắng lấy mã nhân viên nếu có (Odoo thường dùng barcode, registration_number, hoặc tự custom)
            # Ở đây để tạm là id nếu không có trường chuyên biệt
            emp_code = getattr(line.employee_id, "barcode", "") or getattr(
                line.employee_id, "registration_number", str(line.employee_id.id)
            )

            sheet.write(row, 0, idx, cell_center)
            sheet.write(row, 1, emp_code, cell_center)
            sheet.write(
                row, 2, line.employee_id.name if line.employee_id else "", cell_left
            )
            sheet.write(row, 3, line.job_id.name if line.job_id else "", cell_left)

            sheet.write(row, 4, line.p1_base_salary, cell_num)
            sheet.write(row, 5, line.p1_allowance, cell_num)
            sheet.write(row, 6, line.p2_1_score_raw, cell_num)
            sheet.write(row, 7, line.p2_2_score_raw, cell_num)
            sheet.write(row, 8, line.p3_individual_score, cell_num)
            sheet.write(row, 9, line.p3_department_score, cell_num)
            sheet.write(row, 10, line.p3_1_score, cell_num)

            row += 1

        workbook.close()
        output.seek(0)
        file_data = output.read()
        output.close()

        # Tạo file đính kèm và trả về action tải xuống
        safe_dept_name = (
            self.department_id.name.replace("/", "_") if self.department_id else "Dept"
        )
        file_name = f"Ket_Qua_3P_{safe_dept_name}.xlsx"

        attachment = self.env["ir.attachment"].create(
            {
                "name": file_name,
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
