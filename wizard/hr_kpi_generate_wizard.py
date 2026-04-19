from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta


class HrKpiGenerateWizard(models.TransientModel):
    _name = 'hr.kpi.generate.wizard'
    _description = 'Generate Performance Evaluations From KPI'

    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI Template',
        required=True,
        default=lambda self: self.env.context.get('default_kpi_id'),
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        help='Generate evaluations for employees in this department (unless All Departments is enabled).',
    )
    all_departments = fields.Boolean(string='All Departments', default=False)

    period = fields.Selection(
        related='kpi_id.period',
        string='Period',
        store=True,
        readonly=False,
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    deadline = fields.Date(string='Deadline', required=True)

    @api.onchange('period')
    def _onchange_period_set_dates(self):
        if not self.period:
            return

        today = date.today()
        
        if self.period == 'monthly':
            # Đầu tháng và cuối tháng hiện tại
            start = today.replace(day=1)
            end = start + relativedelta(months=1, days=-1)
            deadline_days = 5

        elif self.period == 'quarterly':
            # Tính quý hiện tại: Q1 (tháng 1), Q2 (tháng 4), Q3 (tháng 7), Q4 (tháng 10)
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            start = today.replace(month=quarter_month, day=1)
            end = start + relativedelta(months=3, days=-1)
            deadline_days = 10 # Quý thường cần nhiều thời gian đánh giá hơn

        elif self.period == 'half_yearly':
            # Hiệp 1 (tháng 1-6) hoặc Hiệp 2 (tháng 7-12)
            half_month = 1 if today.month <= 6 else 7
            start = today.replace(month=half_month, day=1)
            end = start + relativedelta(months=6, days=-1)
            deadline_days = 15

        elif self.period == 'yearly':
            # Từ 01/01 đến 31/12 của năm hiện tại
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            deadline_days = 20 # Tổng kết năm cần thời gian dài hơn

        self.start_date = start
        self.end_date = end
        self.deadline = end + relativedelta(days=deadline_days)

    @api.constrains('start_date', 'end_date')
    def _check_date_range(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date > rec.end_date:
                raise ValidationError('Start Date must be before or equal to End Date.')

    def _employee_matches_kpi(self, employee, kpi):
        """Return True if the KPI template is applicable to the employee (department/job)."""
        if not kpi:
            return False
        if kpi.department_id:
            return bool(employee.department_id and employee.department_id == kpi.department_id)
        # if kpi.job_id:
        #     return bool(employee.job_id and employee.job_id == kpi.job_id)
        return False

    def action_generate(self):
        self.ensure_one()

        if not self.kpi_id:
            raise ValidationError('Please select a KPI Template.')

        dom = [('active', '=', True)]
        if not self.all_departments:
            if not self.department_id:
                raise ValidationError('Please select a Department or enable All Departments.')
            dom.append(('department_id', '=', self.department_id.id))

        employees = self.env['hr.employee'].search(dom)
        if not employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thông báo',
                    'message': 'Không tìm thấy nhân viên nào thuộc phòng ban đã chọn hoặc nhân viên không còn hoạt động.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        Evaluation = self.env['hr.performance.evaluation']
        # created_evaluations = self.env['hr.performance.evaluation']
        
        # 1. Prepare list of applicable employees
        valid_employees = self.env['hr.employee']
        for emp in employees:
            if self._employee_matches_kpi(emp, self.kpi_id):
                # Optionally check if evaluation exists
                exists = Evaluation.search([
                    ('employee_id', '=', emp.id),
                    ('kpi_id', '=', self.kpi_id.id),
                    ('period', '=', self.period),
                    ('start_date', '=', self.start_date),
                    ('end_date', '=', self.end_date),
                ], limit=1)
                if not exists:
                    valid_employees |= emp

        if not valid_employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Không có dữ liệu mới',
                    'message': 'Tất cả nhân viên được chọn đều đã có bản đánh giá cho kỳ này',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # 2. Tạo 1 record cho hr.performance.report TRƯỚC
        report = self.env['hr.performance.report'].sudo().create({
            'period': self.period,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'deadline': self.deadline,
            'department_id': self.department_id.id if not self.all_departments else False,
            'employee_id': [(6, 0, valid_employees.ids)],
        })

        # 3. Chạy vòng lặp tạo Evaluations và gắn performance_report_id
        count = 0
        for emp in valid_employees:
            scratch = Evaluation.new({'kpi_id': self.kpi_id.id, 'period': self.period})
            line_cmds = scratch._prepare_evaluation_line_commands_from_template(self.kpi_id)

            evaluation = Evaluation.create({
                'employee_id': emp.id,
                'kpi_id': self.kpi_id.id,
                'period': self.period,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'deadline': self.deadline,
                'evaluation_line_ids': line_cmds,
                'performance_report_id': report.id,
            })
            self.send_notification(emp, evaluation)
            count += 1
            # created_evaluations |= evaluation

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã khởi tạo thành công {count} bản đánh giá hiệu suất cho kỳ {self.period}.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def send_notification(self, emp, evaluation):
        # Tự động gửi thông báo đến Inbox hoặc Email của Nhân viên
        if emp.user_id and emp.user_id.partner_id:
            periods_vi = {
                'monthly': 'Hàng tháng',
                'quarterly': 'Hàng quý',
                'half_yearly': 'Bán niên',
                'yearly': 'Hàng năm'
            }
            period_str = periods_vi.get(self.period, self.period)
            start_str = self.start_date.strftime('%d/%m/%Y')
            end_str = self.end_date.strftime('%d/%m/%Y')

            # 1. Lấy URL gốc của hệ thống và tạo Link trực tiếp đến bản ghi này
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            # Lưu ý: Thay self.id bằng object_evaluation.id nếu hàm này nằm ở file Wizard
            record_url = f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"


            # 2. Xây dựng nội dung HTML (Thêm nút bấm Action Button)
            msg_body = f"""
                <div style="margin: 0; padding: 0;">
                    <p>Xin chào <b>{emp.name}</b>,</p>
                    <p>Bạn vừa có một bảng đánh giá KPI mới được tạo trên hệ thống.</p>
                    <ul>
                        <li><b>Kỳ đánh giá:</b> {period_str}</li>
                        <li><b>Thời gian chuẩn:</b> Từ {start_str} đến {end_str}</li>
                    </ul>
                    <p>Vui lòng click vào nút bên dưới để xem chi tiết và hoàn thành phần tự đánh giá của bạn (nếu có).</p>
                    
                    <div style="margin-top: 20px; margin-bottom: 20px;">
                        <a href="{record_url}" 
                           style="background-color: #714B67; padding: 10px 20px; color: #FFFFFF; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            Xem Bảng Đánh Giá
                        </a>
                    </div>
                </div>
            """

            # 3. Sử dụng Markup() để Odoo render đúng HTML
            emp.message_post(
                body=Markup(msg_body),
                subject="[Thông báo] Bạn có bảng đánh giá KPI mới",
                partner_ids=[emp.user_id.partner_id.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
