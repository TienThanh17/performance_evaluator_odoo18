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
        selection=[
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('half_yearly', 'Half-Yearly'),
            ('yearly', 'Yearly'),
        ],
        string='Period',
        required=True,
        default='monthly',
    )
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)

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

        for emp in employees:
            if not self._employee_matches_kpi(emp, self.kpi_id):
                continue

            exists = Evaluation.search([
                ('employee_id', '=', emp.id),
                ('kpi_id', '=', self.kpi_id.id),
                ('period', '=', self.period),
                ('start_date', '=', self.start_date),
                ('end_date', '=', self.end_date),
            ], limit=1)
            if exists:
                continue

            # Build evaluation lines from template filtered by period.
            # Use a scratch record to reuse the helper (no DB write yet).
            scratch = Evaluation.new({'kpi_id': self.kpi_id.id, 'period': self.period})
            line_cmds = scratch._prepare_evaluation_line_commands_from_template(self.kpi_id, self.period)

            Evaluation.create({
                'employee_id': emp.id,
                'kpi_id': self.kpi_id.id,
                'period': self.period,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'evaluation_line_ids': line_cmds,
            })

        return {'type': 'ir.actions.act_window_close'}
