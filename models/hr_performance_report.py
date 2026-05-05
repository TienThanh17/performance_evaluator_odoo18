import io
import base64
import pytz
import xlsxwriter
from markupsafe import Markup
from datetime import datetime, time, timedelta

from odoo import fields, models, api, _


class HrPerformanceReport(models.Model):
    _name = 'hr.performance.report'
    _description = 'Performance Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    # _rec_name = 'department_name'

    # Fields
    period = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('half_yearly', 'Half-Yearly'),
        ('yearly', 'Yearly'),
    ], string="Evaluation Period", required=True)

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    deadline = fields.Date(string="Deadline", required=True)
    active = fields.Boolean(string="Active", default=True)
    evaluation_ids = fields.One2many('hr.performance.evaluation', 'performance_report_id',
                                     string="Performance Evaluations", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department")
    department_name = fields.Char(related='department_id.name')

    employee_id = fields.Many2many('hr.employee', string="Employees", required=True)
    company_id = fields.Many2one('res.company', string="Company", required=True,
                                 default=lambda self: self.env.company)
    body = fields.Html(string="Body of Email")
    subject = fields.Char(string="Subject")
    email_to = fields.Char(compute='_compute_email_to', string="Email To", store=True)
    employee_name = fields.Char(string="Employee Name", compute="_compute_employee_name")

    dept_evaluation_ids = fields.One2many(
        'hr.department.performance.evaluation', 'performance_report_id',
        string='Department Evaluations'
    )

    @api.depends('department_id.name', 'start_date', 'end_date')
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
        for report in self:
            kpis = self.env['hr.department.kpi'].search([('period', '=', report.period)])
            for kpi in kpis:
                # 1. Kiểm tra đã tồn tại
                existing = self.env['hr.department.performance.evaluation'].search([
                    ('department_id', '=', kpi.department_id.id),
                    ('performance_report_id', '=', report.id)
                ], limit=1)
                
                if existing:
                    continue
                
                # 2. Tạo evaluation
                eval_vals = {
                    'department_id': kpi.department_id.id,
                    'department_kpi_id': kpi.id,
                    'performance_report_id': report.id,
                    'start_date': report.start_date,
                    'end_date': report.end_date,
                    'deadline': report.deadline,
                }
                new_eval = self.env['hr.department.performance.evaluation'].create(eval_vals)
                
                # 3. Populate lines
                if kpi.department_id and new_eval:
                    for line in kpi.kpi_line_ids:
                        self.env['hr.department.evaluation.line'].create({
                            'evaluation_id': new_eval.id,
                            'department_kpi_line_id': line.id,
                            'name': line.name,
                            'kpi_type': line.kpi_type,
                            'target': line.target,
                            'target_type': line.target_type,
                            'direction': line.direction,
                            'weight': line.weight,
                            'is_auto': line.is_auto,
                            'data_source': line.data_source,
                            'is_section': line.is_section,
                        })
                        
                    # 4. Compute if auto
                    new_eval.action_compute_auto_kpi()

    def action_send_email(self):
        # Ensure the template exists
        mail_template = self.env.ref('custom_adecsol_hr_performance_evaluator.email_template_evaluation_alert',
                                     raise_if_not_found=False)
        if mail_template:
            for employee in self.employee_id:
                # Create a specific context for the employee
                ctx = {
                    'default_model': 'hr.performance.report',
                    'default_res_id': self.id,
                    'default_use_template': True,
                    'default_template_id': mail_template.id,
                    'force_send': True,
                    'email_to': employee.work_email,
                    'employee_name': employee.name,
                }
                # Send the email with the specific context
                mail_template.with_context(ctx).send_mail(self.id, force_send=True)

    @api.depends('employee_id')
    def _compute_email_to(self):
        """Compute a comma-separated list of emails for the employees."""
        for record in self:
            emails = [e.work_email for e in record.employee_id if e.work_email]
            record.email_to = ', '.join(emails)

    @api.depends('employee_id')
    def _compute_employee_name(self):
        """Compute a comma-separated list of employee names."""
        for record in self:
            names = [e.name for e in record.employee_id if e.name]
            record.employee_name = ', '.join(names)

    @api.model
    def _cron_send_deadline_reminder(self):
        """Send a reminder to employees before the deadline."""
        today = fields.Date.context_today(self)
        
        # 1. Deactivate reports where the deadline has passed
        expired_reports = self.search([
            ('active', '=', True),
            ('deadline', '<', today)
        ])
        expired_reports.write({'active': False})

        # 2. Send reminders for upcoming deadlines
        reminder_days_str = self.env['ir.config_parameter'].sudo().get_param(
            'custom_adecsol_hr_performance_evaluator.deadline_reminder_days', 3)
        try:
            reminder_days = int(reminder_days_str)
        except ValueError:
            reminder_days = 3

        target_date = today + timedelta(days=reminder_days)
        reports = self.search([
            ('active', '=', True),
            ('deadline', '=', target_date)
        ])

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        for report in reports:
            # Send email
            # report.action_send_email()

            # Iterate through each evaluation to send individual links
            for evaluation in report.evaluation_ids:
                partner = evaluation.employee_id.user_id.partner_id
                if not partner:
                    continue

                record_url = f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"
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
                ) % (
                               reminder_days,
                               report.deadline.strftime('%d/%m/%Y'),
                               record_url
                           )

                evaluation.message_post(
                    body=Markup(msg_body),
                    subject="Review deadline reminder",
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                    partner_ids=[partner.id],
                )

    def write(self, vals):
        res = super(HrPerformanceReport, self).write(vals)
        # Fields to sync down to each linked hr.performance.evaluation
        sync_fields = {'active', 'period', 'start_date', 'end_date', 'deadline'}
        sync_vals = {k: vals[k] for k in sync_fields if k in vals}
        if sync_vals:
            for record in self:
                record.evaluation_ids.with_context(active_test=False).write(sync_vals)
        return res

    def action_export_excel_report(self):
        self.ensure_one()

        # Khởi tạo buffer và workbook
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Báo cáo công việc')

        # Định dạng style
        base_style = {'font_name': 'Times New Roman', 'border': 1, 'font_size': 12}

        title_style = workbook.add_format({
            **base_style, 'bold': True, 'align': 'center', 'border': 0, 'font_color': 'red'
        })
        header_style = workbook.add_format({
            **base_style, 'bold': True, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#f2f2f2', 'text_wrap': True
        })
        cell_style = workbook.add_format({
            **base_style, 'valign': 'vcenter', 'text_wrap': True
        })
        center_style = workbook.add_format({
            **base_style, 'align': 'center', 'valign': 'vcenter'
        })
        # Format riêng cho cột Ngày: merge, căn giữa và định dạng dd/mm/yyyy
        date_style = workbook.add_format({
            **base_style, 'num_format': 'DD/MM/YYYY', 'align': 'center', 'valign': 'vcenter'
        })
        yellow_style = workbook.add_format({
            **base_style, 'bg_color': '#FFFF00'
        })

        # Xử lý Tiêu đề
        dept_name = self.department_id.name.upper() if self.department_id else 'IT'
        sheet.merge_range('A3:H3', f'BÁO CÁO CÔNG VIỆC NHÂN VIÊN PHÒNG {dept_name}', title_style)

        # Cấu hình độ rộng cột
        sheet.set_column('A:A', 5)  # STT
        sheet.set_column('B:B', 30)  # Họ và Tên
        sheet.set_column('C:C', 30)  # Chức vụ
        sheet.set_column('D:D', 20)  # Ngày/Tháng/Năm
        sheet.set_column('E:E', 100)  # Công việc
        sheet.set_column('F:G', 12)  # Thời gian
        sheet.set_column('H:H', 20)  # Ghi chú

        # In Header
        headers = ['STT', 'Họ và Tên', 'Chức vụ', 'Ngày/Tháng/Năm', 'Công việc', 'Thời gian bắt đầu',
                   'Thời gian kết thúc', 'Ghi chú']
        for col, head in enumerate(headers):
            sheet.write(5, col, head, header_style)

        # Cài đặt Timezone
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Ho_Chi_Minh')
        current_date = self.start_date
        row = 6
        num_emp = len(self.employee_id)

        # Lặp qua từng ngày trong kỳ đánh giá
        while current_date <= self.end_date:
            is_sunday = current_date.weekday() == 6

            # Xử lý Merge ô cho cột Ngày/Tháng/Năm (Cột index 3)
            # Merge từ dòng hiện tại đến dòng của nhân viên cuối cùng trong ngày đó
            if num_emp > 1:
                sheet.merge_range(row, 3, row + num_emp - 1, 3, current_date, date_style)
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
                sheet.write(row, 2, emp.job_id.name or '', center_style)

                # Lấy partner_id của nhân viên để truy vấn vào Calendar
                # Odoo 17/18 thường dùng work_contact_id hoặc user_id.partner_id
                partner_id = emp.work_contact_id.id or (emp.user_id.partner_id.id if emp.user_id else False)

                if partner_id:
                    events = self.env['calendar.event'].search([
                        ('start', '<=', utc_end_dt),
                        ('stop', '>=', utc_start_dt),
                        ('partner_ids', 'in', [partner_id])  # Truy vấn theo người tham dự
                    ], order='start asc')
                else:
                    # Nếu nhân viên chưa được gắn thẻ đối tác/người dùng, sẽ không có lịch
                    events = self.env['calendar.event'].browse()

                task_str = ""
                start_time_str = ""
                end_time_str = ""

                if is_sunday:
                    task_str = "CN"
                elif events:
                    # Tạo bullet point cho các công việc
                    task_str = "\n".join([f"- {event.name}" for event in events])

                    # Lấy giờ bắt đầu sớm nhất và giờ kết thúc trễ nhất
                    min_start = pytz.utc.localize(events[0].start).astimezone(user_tz)
                    max_stop = pytz.utc.localize(events[-1].stop).astimezone(user_tz)

                    start_time_str = f"{min_start.hour}h"
                    end_time_str = f"{max_stop.hour}h"

                # Ghi dữ liệu Công việc và Thời gian
                sheet.write(row, 4, task_str, cell_style)
                sheet.write(row, 5, start_time_str, center_style)
                sheet.write(row, 6, end_time_str, center_style)
                sheet.write(row, 7, '', cell_style)  # Ghi chú để trống

                stt += 1
                row += 1

            # Thêm 1 dòng trống giữa các ngày và tô màu vàng từ cột A đến H (index 0 đến 7)
            for col_idx in range(8):
                sheet.write(row, col_idx, '', yellow_style)
            # Thêm 1 dòng trống giữa các ngày giống như file mẫu
            row += 1
            current_date += timedelta(days=1)

        # Đóng workbook và xuất file
        workbook.close()
        output.seek(0)

        file_name = f'Bao_Cao_Cong_Viec_{self.period}_{self.start_date}_to_{self.end_date}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
