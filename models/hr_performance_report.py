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

    def _build_report_chart_item(
        self,
        key,
        sequence,
        measure_field,
        default_title,
        badge,
        badge_tone,
        dot_tone,
    ):
        return {
            "section_type": "chart_item",
            "widget_id": 0,
            "key": key,
            "sequence": sequence,
            "measure_field": measure_field,
            "title": default_title,
            "badge": badge,
            "badge_tone": badge_tone,
            "dot_tone": dot_tone,
        }

    def _build_report_chart_row(self, items, layout):
        active_items = [item for item in items if item]
        if not active_items:
            return False
        return {
            "section_type": "chart_row",
            "layout": layout,
            "sequence": min(item["sequence"] for item in active_items),
            "key": "report_row_%s" % "_".join(item["key"] for item in active_items),
            "items": active_items,
        }

    def _build_report_sections(self, context_data):
        sections = []

        sections_row_top = self._build_report_chart_row(
            [
                self._build_report_chart_item(
                    "report_score_bar",
                    120,
                    "report_score_bar",
                    _("Individual KPI Score by Employee"),
                    "Bar",
                    "blue",
                    "blue",
                ),
                self._build_report_chart_item(
                    "report_task_summary",
                    130,
                    "report_task_summary",
                    _("Completed Tasks by Employee"),
                    _("Stacked Bar"),
                    "green",
                    "green",
                ),
            ],
            "2col",
        )
        if sections_row_top:
            sections.append(sections_row_top)

        sections_row_bottom = self._build_report_chart_row(
            [
                self._build_report_chart_item(
                    "report_attendance",
                    140,
                    "report_attendance",
                    _("Attendance — Days Present"),
                    "Doughnut",
                    "blue",
                    "blue",
                ),
                self._build_report_chart_item(
                    "report_late_summary",
                    150,
                    "report_late_summary",
                    _("Punctuality — Late Count by Employee"),
                    "Line",
                    "red",
                    "red",
                ),
            ],
            "13col",
        )
        if sections_row_bottom:
            sections.append(sections_row_bottom)

        if context_data["qualitative_charts"]:
            sections.append(
                {
                    "section_type": "qualitative_grid",
                    "widget_id": 0,
                    "key": "report_qualitative",
                    "sequence": 160,
                    "measure_field": "report_qualitative",
                    "title": _("Qualitative KPIs — Employee Comparison"),
                    "charts": context_data["qualitative_charts"],
                }
            )

        return sorted(
            sections,
            key=lambda section: (
                section.get("sequence", 0),
                section.get("widget_id", 0),
                section.get("key", ""),
            ),
        )

    def get_report_dashboard_data(self):
        """Chuẩn bị toàn bộ data cho PerformanceDashboard charts.

        Returns dict:
            employees           list[dict]  — [{id, name, score, level}]
            task_summary        dict        — {names, total_tasks, done_tasks} per employee
            attendance_summary  dict        — {names, worked_days} per employee
            late_summary        dict        — {names, late_count} per employee
            qualitative_charts  list[dict]  — mỗi KPI định tính = 1 dict {kpi_name, labels, scores}
        """
        self.ensure_one()

        evalids = self.with_context(active_test=False).evaluation_ids.ids
        settings = self.env["res.config.settings"]
        score_scale = settings.get_score_scale_info()
        threshold_excellent, threshold_pass = settings.get_thresholds()
        report_meta = {
            "report_id": self.id,
            "department_id": self.department_id.id if self.department_id else False,
            "department_name": self.department_name or "",
            "period_id": self.period_id.id if self.period_id else False,
            "period_name": self.period_id.name if self.period_id else "",
            "period_type": self.period_type or "",
            "start_date": str(self.start_date) if self.start_date else False,
            "end_date": str(self.end_date) if self.end_date else False,
            "deadline": str(self.deadline) if self.deadline else False,
            "active": bool(self.active),
        }
        period_label = (
            self.period_id.name
            if self.period_id
            else (str(self.start_date) if self.start_date else "")
        )
        if not evalids:
            report_sections = self._build_report_sections(
                {
                    "avg_score": 0.0,
                    "pass_count": 0,
                    "total_employees": 0,
                    "period_label": period_label,
                    "evaluations": [],
                    "qualitative_charts": [],
                },
            )
            return {
                **report_meta,
                "score_scale": score_scale,
                "thresholds": {
                    "excellent": threshold_excellent,
                    "pass": threshold_pass,
                },
                "total_employees": 0,
                "avg_score": 0.0,
                "pass_count": 0,
                "employees": [],
                "evaluations": [],
                "task_summary": {},
                "attendance_summary": {},
                "late_summary": {},
                "qualitative_charts": [],
                "report_sections": report_sections,
            }

        evaluations = self.env["hr.performance.evaluation"].sudo().browse(evalids)

        # ── 1. Base employee list ──────────────────────────────────────────────
        employees = []
        evaluation_rows = []
        for ev in evaluations:
            employees.append(
                {
                    "id": ev.employee_id.id if ev.employee_id else 0,
                    "name": ev.employee_id.name if ev.employee_id else "?",
                    "score": round(float(ev.total_p3_individual or 0.0), 2),
                    "level": ev.performance_level or "fail",
                    "eval_id": ev.id,
                }
            )
            evaluation_rows.append(
                {
                    "id": ev.id,
                    "employee_id": (
                        [ev.employee_id.id, ev.employee_id.name]
                        if ev.employee_id
                        else False
                    ),
                    "job_id": [ev.job_id.id, ev.job_id.name] if ev.job_id else False,
                    "total_p3_individual": round(
                        float(ev.total_p3_individual or 0.0), 2
                    ),
                    "performance_level": ev.performance_level or False,
                    "state": ev.state or False,
                    "name": ev.name or "",
                    # Dùng cùng một rule với popup để roster và chi tiết luôn khớp nhau.
                    "comment_count": ev.get_comment_count(),
                }
            )

        emp_names = [e["name"] for e in employees]
        total_employees = len(evaluations)
        avg_score = (
            round(
                sum(float(ev.total_p3_individual or 0.0) for ev in evaluations)
                / total_employees,
                2,
            )
            if total_employees
            else 0.0
        )
        pass_count = sum(
            1 for ev in evaluations if ev.performance_level in ("pass", "excellent")
        )

        # ── 2. Task summary ────────────────────────────────────────────────────
        task_summary = {"names": emp_names, "total_tasks": [], "done_tasks": []}
        for ev in evaluations:
            line = ev.evaluation_line_ids.filtered(
                lambda l: not l.is_section and l.kpi_type == "auto"
            )
            if not line or not ev.employee_id or not ev.start_date or not ev.end_date:
                task_summary["total_tasks"].append(0)
                task_summary["done_tasks"].append(0)
                continue

            user = ev.employee_id.user_id
            if not user:
                task_summary["total_tasks"].append(0)
                task_summary["done_tasks"].append(0)
                continue

            Task = self.env["project.task"].sudo()
            base_domain = [
                ("user_ids", "in", user.id),
                ("date_deadline", ">=", ev.start_date),
                ("date_deadline", "<=", ev.end_date),
                ("project_id", "!=", False),
            ]
            total = Task.search_count(base_domain)
            done = Task.search_count(
                base_domain + [("stage_id.is_done_stage", "=", True)]
            )
            task_summary["total_tasks"].append(total)
            task_summary["done_tasks"].append(done)

        # ── 3. Attendance summary ──────────────────────────────────────────────
        attendance_summary = {
            "names": emp_names,
            "worked_days": [],
            "expected_work_days": 0,
        }
        for ev in evaluations:
            line = ev.evaluation_line_ids.filtered(
                lambda l: not l.is_section and l.kpi_type == "auto"
            )
            if not line or not ev.start_date or not ev.end_date:
                attendance_summary["worked_days"].append(0)
                continue

            engine = self.env["hr.kpi.engine"]
            metrics = engine.get_attendance_period_metrics(
                ev.employee_id, line[0], ev.start_date, ev.end_date
            )
            metrics = metrics or {}
            worked = float(metrics.get("worked_days", 0))
            attendance_summary["worked_days"].append(worked)

            # expected_work_days giống nhau cho mọi nhân viên trong cùng kỳ
            # chỉ cần lấy 1 lần
            if not attendance_summary["expected_work_days"]:
                attendance_summary["expected_work_days"] = float(
                    metrics.get("expected_work_days", 0)
                )

        # ── 4. Late summary ────────────────────────────────────────────────────
        late_summary = {"names": emp_names, "late_count": []}
        for ev in evaluations:
            line = ev.evaluation_line_ids.filtered(
                lambda l: not l.is_section and l.kpi_type == "auto"
            )
            if not line or not ev.start_date or not ev.end_date:
                late_summary["late_count"].append(0)
                continue

            engine = self.env["hr.kpi.engine"]
            val = engine.compute(ev.employee_id, line[0], ev.start_date, ev.end_date)
            late_summary["late_count"].append(int(val or 0))

        # ── 5. Manual qualitative charts ──────────────────────────────────────
        # Group all manual KPI lines by key performance area.
        qual_map = {}  # {kpi_name: {emp_name: score}}
        for ev in evaluations:
            emp_name = ev.employee_id.name if ev.employee_id else "?"
            rating_lines = ev.evaluation_line_ids.filtered(
                lambda l: not l.is_section and l.kpi_type == "manual"
            )
            for line in rating_lines:
                kname = line.key_performance_area or line.name or "KPI"
                if kname not in qual_map:
                    qual_map[kname] = {}
                qual_map[kname][emp_name] = round(float(line.final_rating or 0.0), 2)

        qualitative_charts = []
        for kname, emp_scores in qual_map.items():
            qualitative_charts.append(
                {
                    "kpi_name": kname,
                    "labels": list(emp_scores.keys()),
                    "scores": list(emp_scores.values()),
                }
            )

        report_sections = self._build_report_sections(
            {
                "avg_score": avg_score,
                "pass_count": pass_count,
                "total_employees": total_employees,
                "period_label": period_label,
                "evaluations": evaluation_rows,
                "qualitative_charts": qualitative_charts,
            },
        )

        return {
            **report_meta,
            "score_scale": score_scale,
            "thresholds": {
                "excellent": threshold_excellent,
                "pass": threshold_pass,
            },
            "total_employees": total_employees,
            "avg_score": avg_score,
            "pass_count": pass_count,
            "employees": employees,
            "evaluations": evaluation_rows,
            "task_summary": task_summary,
            "attendance_summary": attendance_summary,
            "late_summary": late_summary,
            "qualitative_charts": qualitative_charts,
            "report_sections": report_sections,
        }
