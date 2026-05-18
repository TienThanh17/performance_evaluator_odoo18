from odoo import models, fields, api, _
from datetime import datetime

class HREmployee(models.Model):
    _inherit = 'hr.employee'

    performance_score = fields.Float(
        string="Performance Score",
        compute='_compute_performance_score',
        # store=True
    )

    # 1. Thêm trường One2many để Odoo có thể theo dõi dữ liệu thay đổi
    evaluation_ids = fields.One2many(
        'hr.performance.evaluation',
        'employee_id',
        string="Evaluations"
    )

    # 2. Khai báo @api.depends dựa trên trường One2many
    @api.depends('evaluation_ids.performance_score', 'evaluation_ids.deadline', 'evaluation_ids.start_date')
    def _compute_performance_score(self):
        for employee in self:
            # Fetch the most recent performance evaluation for this employee
            evaluation = self.env['hr.performance.evaluation'].search([
                ('employee_id', '=', employee.id)
            ], order='start_date desc', limit=1)

            if evaluation:
                # Check if the evaluation deadline has passed
                if evaluation.deadline and evaluation.deadline >= fields.Date.today():
                    # Only update score if deadline is in the future
                    employee.performance_score = evaluation.performance_score
                else:
                    # If the deadline has passed, do not show the score
                    employee.performance_score = 0.0
            else:
                # If no evaluation found, set score to 0.0
                employee.performance_score = 0.0

    def action_score_view(self):
        """Opens a view to list all documents related to the current employee."""
        self.ensure_one()
        return {
            'name': _('Score'),
            'domain': [('employee_id', '=', self.id)],
            'res_model': 'hr.performance.evaluation',
            'type': 'ir.actions.act_window',
            'view_id': False,
            'view_mode': 'list,form',
            'help': _('''<p class="oe_view_nocontent_create">
                            Click to create a new performance evaluation.
                         </p>'''),
            'limit': 80,
            'context': "{'default_employee_id': %s}" % self.id
        }
