from odoo import api, fields, models
from odoo.exceptions import ValidationError


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
        readonly=True,
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    deadline = fields.Date(string='Deadline', required=True)

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
            return {'type': 'ir.actions.act_window_close'}

        Evaluation = self.env['hr.performance.evaluation']
        created_evaluations = self.env['hr.performance.evaluation']
        
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
            return {'type': 'ir.actions.act_window_close'}

        # 2. Tạo 1 record cho hr.performance.report TRƯỚC
        alert = self.env['hr.performance.report'].create({
            'period': self.period,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'deadline': self.deadline,
            'department_id': self.department_id.id if not self.all_departments else False,
            'employee_id': [(6, 0, valid_employees.ids)],
        })

        # 3. Chạy vòng lặp tạo Evaluations và gắn alert_id
        for emp in valid_employees:
            scratch = Evaluation.new({'kpi_id': self.kpi_id.id, 'period': self.period})
            line_cmds = scratch._prepare_evaluation_line_commands_from_template(self.kpi_id)

            evaluation = Evaluation.create({
                'employee_id': emp.id,
                'kpi_id': self.kpi_id.id,
                'period': self.period,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'evaluation_line_ids': line_cmds,
                'performance_report_id': alert.id, # Gắn trực tiếp để thỏa mãn DB Constraint
            })
            
            created_evaluations |= evaluation

            # Tự động gửi thông báo đến Inbox trong Odoo của Nhân viên
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

                msg_body = f"""
                <div style="margin: 0; padding: 0;">
                    <p>Xin chào <b>{emp.name}</b>,</p>
                    <p>Bạn vừa có một bảng đánh giá KPI mới được tạo trên hệ thống.</p>
                    <ul>
                        <li><b>Kỳ đánh giá:</b> {period_str}</li>
                        <li><b>Thời gian chuẩn:</b> Từ {start_str} đến {end_str}</li>
                    </ul>
                    <p>Vui lòng đăng nhập vào hệ thống, truy cập menu <b>Performance Evaluation</b> để xem chi tiết và hoàn thành phần tự đánh giá (nếu có).</p>
                </div>
                """
                
                emp.message_post(
                    body=msg_body,
                    subject="[Thông báo] Bạn có bảng đánh giá KPI mới",
                    partner_ids=[emp.user_id.partner_id.id],
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )

        return {'type': 'ir.actions.act_window_close'}
