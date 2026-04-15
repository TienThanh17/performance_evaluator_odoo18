from odoo import models, fields, api
from odoo.exceptions import ValidationError

class KPI(models.Model):
    _name = 'hr.kpi'
    _description = 'KPI for Department'

    name = fields.Char(string='KPI Template', required=True)
    kpi_line_ids = fields.One2many(
        'hr.kpi.line',
        'kpi_id',
        help="The KPI lines included in this KPI template (sections and KPI items).",
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        help="Apply this KPI template to employees in the selected job position.",
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        help="Apply this KPI template to employees in the selected department.",
    )

    @api.onchange('job_id')
    def _onchange_job_id(self):
        # Choose ONLY one between job and department
        if self.job_id:
            self.department_id = False

    @api.onchange('department_id')
    def _onchange_department_id(self):
        # Choose ONLY one between job and department
        if self.department_id:
            self.job_id = False

    @api.constrains('job_id', 'department_id')
    def _check_job_or_department(self):
        for rec in self:
            if rec.job_id and rec.department_id:
                raise ValidationError("You can only select either Job Position or Department, not both.")
            if not rec.job_id and not rec.department_id:
                raise ValidationError("You must select either a Job Position or a Department.")
