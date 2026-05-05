from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta


class HrDepartmentKpiGenerateWizard(models.TransientModel):
    _name = 'hr.department.kpi.generate.wizard'
    _description = 'Generate Department Performance Evaluations'

    department_kpi_id = fields.Many2one(
        'hr.department.kpi',
        string='Department KPI Template',
        required=True,
        default=lambda self: self.env.context.get('default_department_kpi_id'),
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='department_kpi_id.department_id',
        readonly=True,
    )
    kpi_template_id = fields.Many2one(
        'hr.kpi',
        string='Employee KPI Template',
        help='KPI template to use for generating individual employee evaluations.',
    )

    period = fields.Selection(
        related='department_kpi_id.period',
        string='Period',
        store=True,
        readonly=False,
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    deadline = fields.Date(string='Deadline', required=True)

    @api.onchange('department_kpi_id')
    def _onchange_department_kpi_id(self):
        if self.department_kpi_id and self.department_id and self.period:
            # Map periods if they differ slightly between hr.kpi and hr.department.kpi
            period_map = {
                'monthly': 'monthly',
                'quarterly': 'quarterly',
                'biannual': 'half_yearly',
                'annual': 'yearly'
            }
            mapped_period = period_map.get(self.period, self.period)
            
            kpi = self.env['hr.kpi'].search([
                ('department_id', '=', self.department_id.id),
                ('period', '=', mapped_period)
            ], limit=1)
            self.kpi_template_id = kpi

    @api.onchange('period')
    def _onchange_period_set_dates(self):
        if not self.period:
            return

        today = date.today()
        
        if self.period == 'monthly':
            start = today.replace(day=1)
            end = start + relativedelta(months=1, days=-1)
            deadline_days = 5

        elif self.period == 'quarterly':
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            start = today.replace(month=quarter_month, day=1)
            end = start + relativedelta(months=3, days=-1)
            deadline_days = 10

        elif self.period in ('half_yearly', 'biannual'):
            half_month = 1 if today.month <= 6 else 7
            start = today.replace(month=half_month, day=1)
            end = start + relativedelta(months=6, days=-1)
            deadline_days = 15

        elif self.period in ('yearly', 'annual'):
            start = today.replace(month=1, day=1)
            end = today.replace(month=12, day=31)
            deadline_days = 20

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
        return False

    def action_generate(self):
        self.ensure_one()

        if not self.department_kpi_id:
            raise ValidationError('Please select a Department KPI Template.')
        if not self.department_id:
            raise ValidationError('The Department KPI Template must have a Department assigned.')

        dom = [('active', '=', True), ('department_id', '=', self.department_id.id)]
        employees = self.env['hr.employee'].search(dom)
        
        if not employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'No active employees found in this department.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # 1. Check if department evaluation already exists
        DeptEvaluation = self.env['hr.department.performance.evaluation']
        exists_dept_eval = DeptEvaluation.search([
            ('department_id', '=', self.department_id.id),
            ('department_kpi_id', '=', self.department_kpi_id.id),
            ('start_date', '=', self.start_date),
            ('end_date', '=', self.end_date),
        ], limit=1)

        if exists_dept_eval:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No new data',
                    'message': 'A department performance evaluation already exists for this period.',
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # 2. Tạo record cho hr.performance.report
        report = self.env['hr.performance.report'].sudo().create({
            'period': self.period,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'deadline': self.deadline,
            'department_id': self.department_id.id,
            'employee_id': [(6, 0, employees.ids)],
        })

        # 3. Tạo record cho hr.department.performance.evaluation
        scratch_dept = DeptEvaluation.new({'department_kpi_id': self.department_kpi_id.id})
        dept_line_cmds = scratch_dept._prepare_evaluation_line_commands_from_template(self.department_kpi_id)
        
        dept_eval = DeptEvaluation.create({
            'department_id': self.department_id.id,
            'department_kpi_id': self.department_kpi_id.id,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'deadline': self.deadline,
            'performance_report_id': report.id,
            'evaluation_line_ids': dept_line_cmds,
        })

        # 4. Chạy vòng lặp tạo Evaluations cho các employee (nếu có kpi_template_id)
        count = 0
        if self.kpi_template_id:
            Evaluation = self.env['hr.performance.evaluation']
            valid_employees = self.env['hr.employee']
            
            for emp in employees:
                if self._employee_matches_kpi(emp, self.kpi_template_id):
                    # Check if evaluation exists
                    exists = Evaluation.search([
                        ('employee_id', '=', emp.id),
                        ('kpi_id', '=', self.kpi_template_id.id),
                        ('start_date', '=', self.start_date),
                        ('end_date', '=', self.end_date),
                    ], limit=1)
                    if not exists:
                        valid_employees |= emp

            for emp in valid_employees:
                # the period in hr.performance.evaluation should match hr.kpi
                emp_period = self.kpi_template_id.period
                scratch = Evaluation.new({'kpi_id': self.kpi_template_id.id, 'period': emp_period})
                line_cmds = scratch._prepare_evaluation_line_commands_from_template(self.kpi_template_id)

                evaluation = Evaluation.create({
                    'employee_id': emp.id,
                    'kpi_id': self.kpi_template_id.id,
                    'period': emp_period,
                    'start_date': self.start_date,
                    'end_date': self.end_date,
                    'deadline': self.deadline,
                    'evaluation_line_ids': line_cmds,
                    'performance_report_id': report.id,
                })
                self.send_notification(emp, evaluation)
                count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã tạo 1 Department Evaluation và {count} Individual Evaluations cho kỳ {self.period}.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def send_notification(self, emp, evaluation):
        if emp.user_id and emp.user_id.partner_id:
            period_str = self.period
            start_str = self.start_date.strftime('%d/%m/%Y')
            end_str = self.end_date.strftime('%d/%m/%Y')

            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record_url = f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"

            msg_body = _(
                """
                <div style="margin: 0; padding: 0;">
                    <p>Hello <b>%s</b>,</p>
                    <p>A new KPI evaluation has been created for you in the system.</p>
                    <ul>
                        <li><b>Evaluation Period:</b> %s</li>
                        <li><b>Standard Time:</b> From %s to %s</li>
                    </ul>
                    <p>Please click the button below to view details and complete your self-assessment (if applicable).</p>

                    <div style="margin-top: 20px; margin-bottom: 20px;">
                        <a href="%s" 
                           style="background-color: #714B67; padding: 10px 20px; color: #FFFFFF; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            View Evaluation
                        </a>
                    </div>
                </div>
                """
            ) % (emp.name, period_str, start_str, end_str, record_url)

            emp.message_post(
                body=Markup(msg_body),
                subject=_("[Notification] You have a new KPI evaluation"),
                partner_ids=[emp.user_id.partner_id.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
