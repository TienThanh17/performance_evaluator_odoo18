from odoo import fields, models, api


class HrPerformanceReport(models.Model):
    _name = 'hr.performance.report'
    _description = 'Performance Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']

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
    evaluation_ids = fields.One2many('hr.performance.evaluation', 'performance_report_id', string="Performance Evaluations", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department")
    department_name = fields.Char(related='department_id.name')
    
    employee_id = fields.Many2many('hr.employee', string="Employees", required=True,
                                   default=lambda self: self._default_employees())
    company_id = fields.Many2one('res.company', string="Company", required=True,
                                 default=lambda self: self.env.company)
    body = fields.Html(string="Body of Email")
    subject = fields.Char(string="Subject")
    email_to = fields.Char(compute='_compute_email_to', string="Email To", store=True)
    employee_name = fields.Char(string="Employee Name", compute="_compute_employee_name")

    def action_send_email(self):
        # Ensure the template exists
        mail_template = self.env.ref('custom_adecsol_hr_performance_evaluator.email_template_evaluation_alert', raise_if_not_found=False)
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

    @api.model
    def _default_employees(self):
        """Get all employees in the user's company."""
        return self.env['hr.employee'].search([('company_id', '=', self.env.company.id)])

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

    def write(self, vals):
        res = super(HrPerformanceReport, self).write(vals)
        # Fields to sync down to each linked hr.performance.evaluation
        sync_fields = {'active', 'period', 'start_date', 'end_date', 'deadline'}
        sync_vals = {k: vals[k] for k in sync_fields if k in vals}
        if sync_vals:
            for record in self:
                record.evaluation_ids.with_context(active_test=False).write(sync_vals)
        return res
