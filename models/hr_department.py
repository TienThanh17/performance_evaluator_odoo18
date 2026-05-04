from odoo import models, fields, api

class HrDepartment(models.Model):
    _inherit = 'hr.department'

    department_score = fields.Float(
        compute='_compute_department_score_custom',
        string='Điểm KPI phòng ban (kỳ gần nhất)',
    )
    department_level = fields.Selection(
        [('excellent', 'Excellent'), ('pass', 'Pass'), ('fail', 'Fail')],
        compute='_compute_department_score_custom',
        string='Mức độ'
    )

    def _compute_department_score_custom(self):
        for rec in self:
            eval_record = self.env['hr.department.performance.evaluation'].search([
                ('department_id', '=', rec.id),
                ('state', '=', 'approved')
            ], order='end_date desc', limit=1)

            if eval_record:
                rec.department_score = eval_record.department_score
                rec.department_level = eval_record.department_level
            else:
                rec.department_score = 0.0
                rec.department_level = False
