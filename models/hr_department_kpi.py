from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrDepartmentKpi(models.Model):
    _name = 'hr.department.kpi'
    _description = 'Department KPI Template'

    name = fields.Char(required=True)
    department_id = fields.Many2one('hr.department', ondelete='cascade')
    period = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('biannual', 'Biannual'),
        ('annual', 'Annual'),
    ], required=True)

    alpha = fields.Float(
        string='Department KPI Weight (α)',
        default=0.5,
        help='Weight applied to the department’s specific KPI score. The sum of α + β must be 1.0.'
    )
    beta = fields.Float(
        string='Average Individual Weight (β)',
        default=0.5,
        help='Weight applied to the average performance score of all employees. The sum of α + β must be 1.0.'
    )

    kpi_line_ids = fields.One2many('hr.department.kpi.line', 'department_kpi_id')

    @api.constrains('alpha', 'beta')
    def _check_weights(self):
        for rec in self:
            if abs(rec.alpha + rec.beta - 1.0) > 1e-6:
                raise ValidationError('α + β must equal 1.0 (For example: 0.5 and 0.5)')

    def copy(self, default=None):
        # 1. Initialize default dictionary
        default = default or {}

        # 2. Add specific fields to update during copy
        default['name'] = self.name + ' (Copy)'

        # 3. Call super to create the new parent record
        new_parent = super(HrDepartmentKpi, self).copy(default)

        # 4. Iterate over original lines and copy them
        for line in self.kpi_line_ids:
            line.copy({'department_kpi_id': new_parent.id})

        return new_parent
