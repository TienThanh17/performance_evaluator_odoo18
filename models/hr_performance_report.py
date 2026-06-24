import io
import re
import base64
import pytz
import xlsxwriter
import html
from markupsafe import Markup
from datetime import datetime, time, timedelta

from odoo import fields, models, api, _


class HrPerformanceReport(models.Model):
    _name = "hr.performance.report"
    _description = "Performance Report"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, end_date desc"
    # _rec_name = 'department_name'

    # Fields
    period_id = fields.Many2one(
        "hr.kpi.period",
        string="KPI Period",
        required=True,
        ondelete="restrict",
    )
    period_type = fields.Selection(
        related="period_id.period_type",
        string="Period Type",
        store=True,
        readonly=True,
    )

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    deadline = fields.Date(string="Deadline", required=True)
    period_status = fields.Selection(
        [
            ("upcoming", "Sắp diễn ra"),
            ("ongoing", "Đang diễn ra"),
            ("closed", "Đã kết thúc"),
        ],
        string="Period Status",
        compute="_compute_period_status",
        store=False,
    )
    active = fields.Boolean(string="Active", default=True)
    evaluation_ids = fields.One2many(
        "hr.performance.evaluation",
        "performance_report_id",
        string="Performance Evaluations",
        readonly=True,
    )
    department_id = fields.Many2one("hr.department", string="Department")
    department_name = fields.Char(related="department_id.name")

    employee_id = fields.Many2many("hr.employee", string="Employees", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    body = fields.Html(string="Body of Email")
    subject = fields.Char(string="Subject")
    email_to = fields.Char(compute="_compute_email_to", string="Email To", store=True)
    employee_name = fields.Char(
        string="Employee Name", compute="_compute_employee_name"
    )

    dept_evaluation_ids = fields.One2many(
        "hr.department.performance.evaluation",
        "performance_report_id",
        string="Department Evaluations",
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

    @api.depends("department_id.name", "start_date", "end_date")
    def _compute_display_name(self):
        for rec in self:
            # Lấy tên phòng ban hoặc mặc định nếu chưa chọn
            name = rec.department_name or "Performance Report"

            if rec.start_date and rec.end_date:
                # Định dạng: Department Name (2026-01-01 - 2026-01-31)
                rec.display_name = f"{name} ({rec.start_date} - {rec.end_date})"
            else:
                rec.display_name = name

    def action_generate_department_evaluations(self):
        score_base = self.env["res.config.settings"].get_score_scale_base()
        score_unit = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.kpi_unit_score",
            raise_if_not_found=False,
        )
        for report in self:
            kpis = self.env["hr.department.kpi.template"].search(
                [("period_id", "=", report.period_id.id)]
            )
            for kpi in kpis:
                # 1. Kiểm tra đã tồn tại
                existing = self.env["hr.department.performance.evaluation"].search(
                    [
                        ("department_id", "=", kpi.department_id.id),
                        ("performance_report_id", "=", report.id),
                    ],
                    limit=1,
                )

                if existing:
                    continue

                # 2. Tạo evaluation
                eval_vals = {
                    "department_id": kpi.department_id.id,
                    "department_kpi_id": kpi.id,
                    "performance_report_id": report.id,
                    "start_date": report.start_date,
                    "end_date": report.end_date,
                    "deadline": report.deadline,
                }
                new_eval = self.env["hr.department.performance.evaluation"].create(
                    eval_vals
                )

                # 3. Populate lines
                if kpi.department_id and new_eval:
                    for line in kpi.kpi_line_ids:
                        self.env["hr.department.evaluation.line"].create(
                            {
                                "evaluation_id": new_eval.id,
                                "department_kpi_line_id": line.id,
                                "name": line.name,
                                "kpi_type": line.kpi_type,
                                "manual_scoring_type": line.manual_scoring_type,
                                "target": line.target,
                                "weight": line.weight,
                                "unit": line.unit.id if line.unit else False,
                                "is_auto": line.is_auto,
                                "is_section": line.is_section,
                            }
                        )

                    # 4. Compute if auto
                    new_eval.action_compute_auto_kpi()

    @api.depends("employee_id")
    def _compute_email_to(self):
        """Compute a comma-separated list of emails for the employees."""
        for record in self:
            emails = [e.work_email for e in record.employee_id if e.work_email]
            record.email_to = ", ".join(emails)

    @api.depends("employee_id")
    def _compute_employee_name(self):
        """Compute a comma-separated list of employee names."""
        for record in self:
            names = [e.name for e in record.employee_id if e.name]
            record.employee_name = ", ".join(names)

    @api.model
    def _cron_send_deadline_reminder(self):
        """Send a reminder to employees before the deadline."""
        today = fields.Date.context_today(self)

        # Send reminders for upcoming deadlines
        reminder_days_str = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "custom_adecsol_hr_performance_evaluator.deadline_reminder_days", 3
            )
        )
        try:
            reminder_days = int(reminder_days_str)
        except ValueError:
            reminder_days = 3

        target_date = today + timedelta(days=reminder_days)
        reports = self.search([("active", "=", True), ("deadline", "=", target_date)])

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")

        for report in reports:
            # Iterate through each evaluation to send individual links
            for evaluation in report.evaluation_ids:
                # Bỏ qua nếu phiếu đánh giá đã hoàn thành hoặc bị hủy
                if evaluation.state in ["completed", "cancel"]:
                    continue

                emp = evaluation.employee_id

                # 1. Lấy Partner ID của nhân viên
                emp_partner_id = emp.work_contact_id.id or (
                    emp.user_id.partner_id.id if emp.user_id else False
                )

                # 2. Lấy Partner ID của Quản lý phòng ban (Manager)
                manager_partner_id = False
                department_manager = emp.department_id.manager_id
                if department_manager:
                    manager_partner_id = department_manager.work_contact_id.id or (
                        department_manager.user_id.partner_id.id
                        if department_manager.user_id
                        else False
                    )

                # 3. Gom danh sách người nhận DỰA THEO STATE
                partner_ids_to_notify = []

                # Nếu đang ở bước Tự đánh giá -> Gửi cho cả Nhân viên và Quản lý
                if evaluation.state == "self_evaluation":
                    if emp_partner_id:
                        partner_ids_to_notify.append(emp_partner_id)
                    if (
                        manager_partner_id
                        and manager_partner_id not in partner_ids_to_notify
                    ):
                        partner_ids_to_notify.append(manager_partner_id)

                # Nếu đang ở bước Quản lý đánh giá -> CHỈ gửi cho Quản lý
                elif evaluation.state == "manager_evaluating":
                    if manager_partner_id:
                        partner_ids_to_notify.append(manager_partner_id)

                # Bỏ qua nếu không tìm thấy ai để gửi (tránh lỗi)
                if not partner_ids_to_notify:
                    continue

                record_url = f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"

                # Bạn có thể tùy biến lại nội dung tin nhắn cho phù hợp với người nhận nếu muốn
                msg_body = _(
                    """
                    <strong>Announcement:</strong> The deadline for this evaluation report will end in %s days (%s). Please complete it on time.

                    <div style="margin-top: 20px; margin-bottom: 20px;">
                        <a href="%s" 
                            style="background-color: #714B67; padding: 10px 20px; color: #FFFFFF; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            View Your Evaluation
                        </a>
                    </div>
                    """
                ) % (reminder_days, report.deadline.strftime("%d/%m/%Y"), record_url)

                # 4. Gửi thông báo tới danh sách đã phân loại
                evaluation.message_post(
                    body=Markup(msg_body),
                    subject="Review deadline reminder",
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                    partner_ids=partner_ids_to_notify,
                )

    def write(self, vals):
        res = super(HrPerformanceReport, self).write(vals)
        # Fields to sync down to each linked hr.performance.evaluation
        employee_sync_fields = {
            "active",
            "period_id",
            "start_date",
            "end_date",
            "deadline",
        }
        employee_sync_vals = {k: vals[k] for k in employee_sync_fields if k in vals}
        dept_sync_fields = {"active", "period_id", "start_date", "end_date", "deadline"}
        dept_sync_vals = {k: vals[k] for k in dept_sync_fields if k in vals}
        if employee_sync_vals or dept_sync_vals:
            for record in self.with_context(active_test=False):
                if employee_sync_vals:
                    record.evaluation_ids.with_context(active_test=False).write(
                        employee_sync_vals
                    )
                if dept_sync_vals and not self.env.context.get(
                    "skip_department_active_sync"
                ):
                    record.dept_evaluation_ids.with_context(
                        active_test=False,
                        skip_report_active_sync=True,
                    ).write(dept_sync_vals)
        return res

    def action_export_excel_report(self):
        self.ensure_one()

        # Khởi tạo buffer và workbook
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Báo cáo công việc")

        # Định dạng style
        base_style = {"font_name": "Times New Roman", "border": 1, "font_size": 12}

        title_style = workbook.add_format(
            {
                **base_style,
                "bold": True,
                "align": "center",
                "border": 0,
                "font_color": "red",
            }
        )
        header_style = workbook.add_format(
            {
                **base_style,
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "bg_color": "#f2f2f2",
                "text_wrap": True,
            }
        )
        cell_style = workbook.add_format(
            {**base_style, "valign": "vcenter", "text_wrap": True}
        )
        center_style = workbook.add_format(
            {**base_style, "align": "center", "valign": "vcenter"}
        )
        # Format riêng cho cột Ngày: merge, căn giữa và định dạng dd/mm/yyyy
        date_style = workbook.add_format(
            {
                **base_style,
                "num_format": "DD/MM/YYYY",
                "align": "center",
                "valign": "vcenter",
            }
        )
        yellow_style = workbook.add_format({**base_style, "bg_color": "#FFFF00"})

        # Xử lý Tiêu đề
        dept_name = self.department_id.name.upper() if self.department_id else "IT"
        sheet.merge_range(
            "A3:H3", f"BÁO CÁO CÔNG VIỆC NHÂN VIÊN PHÒNG {dept_name}", title_style
        )

        # Cấu hình độ rộng cột
        sheet.set_column("A:A", 5)  # STT
        sheet.set_column("B:B", 30)  # Họ và Tên
        sheet.set_column("C:C", 30)  # Chức vụ
        sheet.set_column("D:D", 20)  # Ngày/Tháng/Năm
        sheet.set_column("E:E", 100)  # Công việc
        sheet.set_column("F:G", 12)  # Thời gian
        sheet.set_column("H:H", 20)  # Ghi chú

        # In Header
        headers = [
            "STT",
            "Họ và Tên",
            "Chức vụ",
            "Ngày/Tháng/Năm",
            "Công việc",
            "Thời gian bắt đầu",
            "Thời gian kết thúc",
            "Ghi chú",
        ]
        for col, head in enumerate(headers):
            sheet.write(5, col, head, header_style)

        # Cài đặt Timezone
        user_tz = pytz.timezone(self.env.user.tz or "Asia/Ho_Chi_Minh")
        current_date = self.start_date
        row = 6
        num_emp = len(self.employee_id)

        # Lặp qua từng ngày trong kỳ đánh giá
        while current_date <= self.end_date:
            is_sunday = current_date.weekday() == 6

            # Xử lý Merge ô cho cột Ngày/Tháng/Năm (Cột index 3)
            # Merge từ dòng hiện tại đến dòng của nhân viên cuối cùng trong ngày đó
            if num_emp > 1:
                sheet.merge_range(
                    row, 3, row + num_emp - 1, 3, current_date, date_style
                )
            else:
                sheet.write(row, 3, current_date, date_style)

            # Giới hạn Datetime từ 00:00:00 đến 23:59:59 của ngày hiện tại (chuyển sang UTC để query DB)
            local_start_dt = user_tz.localize(datetime.combine(current_date, time.min))
            local_end_dt = user_tz.localize(datetime.combine(current_date, time.max))
            utc_start_dt = local_start_dt.astimezone(pytz.UTC).replace(tzinfo=None)
            utc_end_dt = local_end_dt.astimezone(pytz.UTC).replace(tzinfo=None)

            stt = 1
            for emp in self.employee_id:
                # Ghi STT, Tên, Chức vụ
                sheet.write(row, 0, stt, center_style)
                sheet.write(row, 1, emp.name, cell_style)
                sheet.write(row, 2, emp.job_id.name or "", center_style)

                # Lấy partner_id của nhân viên để truy vấn vào Calendar
                # Odoo 17/18 thường dùng work_contact_id hoặc user_id.partner_id
                partner_id = emp.work_contact_id.id or (
                    emp.user_id.partner_id.id if emp.user_id else False
                )

                if partner_id:
                    events = self.env["calendar.event"].search(
                        [
                            ("start", "<=", utc_end_dt),
                            ("stop", ">=", utc_start_dt),
                            (
                                "partner_ids",
                                "in",
                                [partner_id],
                            ),  # Truy vấn theo người tham dự
                        ],
                        order="start asc",
                    )
                else:
                    # Nếu nhân viên chưa được gắn thẻ đối tác/người dùng, sẽ không có lịch
                    events = self.env["calendar.event"].browse()

                task_str = ""
                start_time_str = ""
                end_time_str = ""

                if is_sunday:
                    task_str = "CN"
                elif events:
                    task_lines = []
                    for event in events:
                        # 1. Thêm tên công việc (Bullet point cha)
                        task_lines.append(f"- {event.name}")

                        # 2. Xử lý nội dung mô tả (Giữ nguyên cấu trúc dòng & list)
                        if event.description:
                            raw_desc = event.description

                            # Bước A: Xóa bỏ thẻ hình ảnh <img>
                            raw_desc = re.sub(
                                r"<img[^>]*>", "", raw_desc, flags=re.IGNORECASE
                            )

                            # Bước B: Map các thẻ kết thúc dòng/block thành \n
                            # FIX TẠI ĐÂY: Thêm </li> để xử lý Bullet point sinh ra từ editor của Odoo
                            raw_desc = re.sub(
                                r"<br\s*/?>", "\n", raw_desc, flags=re.IGNORECASE
                            )
                            raw_desc = re.sub(
                                r"</p>|</div>|</li>",
                                "\n",
                                raw_desc,
                                flags=re.IGNORECASE,
                            )

                            # Bước C: Dọn sạch mọi thẻ HTML còn sót lại (<ul>, <ol>, <li>, <b>, <i>...)
                            clean_desc = re.sub(r"<[^>]+>", "", raw_desc)

                            # Bước D: Giải mã ký tự HTML (&nbsp;, &amp;...)
                            clean_desc = html.unescape(clean_desc)

                            # Bước E: Duyệt từng dòng
                            for line in clean_desc.split("\n"):
                                stripped_line = line.strip()

                                if stripped_line:
                                    # Nếu người dùng đã tự gõ ký hiệu list (- hoặc *) thì chỉ thụt lề
                                    if stripped_line.startswith(("-", "*", "•")):
                                        task_lines.append(f"    {stripped_line}")
                                    else:
                                        # Nếu là dòng chữ bình thường hoặc <li> đã bị xóa thẻ, thêm bullet con
                                        task_lines.append(f"    • {stripped_line}")
                                # else:
                                # Giữ nguyên dòng trống để Excel hiển thị cách đoạn
                                # task_lines.append("")

                    # Dọn dẹp các dòng trống dư thừa ở cuối Event để ô Excel không bị khoảng trắng thừa phía dưới
                    while task_lines and task_lines[-1] == "":
                        task_lines.pop()

                    # Ghép tất cả lại bằng dấu xuống dòng cho Excel
                    task_str = "\n".join(task_lines)
                    # Lấy giờ bắt đầu sớm nhất và giờ kết thúc trễ nhất
                    min_start = pytz.utc.localize(events[0].start).astimezone(user_tz)
                    max_stop = pytz.utc.localize(events[-1].stop).astimezone(user_tz)

                    start_time_str = f"{min_start.hour}h"
                    end_time_str = f"{max_stop.hour}h"

                # Ghi dữ liệu Công việc và Thời gian
                sheet.write(row, 4, task_str, cell_style)
                sheet.write(row, 5, start_time_str, center_style)
                sheet.write(row, 6, end_time_str, center_style)
                sheet.write(row, 7, "", cell_style)  # Ghi chú để trống

                stt += 1
                row += 1

            # Thêm 1 dòng trống giữa các ngày và tô màu vàng từ cột A đến H (index 0 đến 7)
            for col_idx in range(8):
                sheet.write(row, col_idx, "", yellow_style)
            # Thêm 1 dòng trống giữa các ngày giống như file mẫu
            row += 1
            current_date += timedelta(days=1)

        # Đóng workbook và xuất file
        workbook.close()
        output.seek(0)

        file_name = f"Bao_Cao_Cong_Viec_{self.period_type}_{self.start_date}_to_{self.end_date}.xlsx"
        attachment = self.env["ir.attachment"].create(
            {
                "name": file_name,
                "type": "binary",
                "datas": base64.b64encode(output.read()),
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

