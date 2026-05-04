from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrDepartmentKpiLine(models.Model):
    _name = 'hr.department.kpi.line'
    _description = 'Department KPI Line'

    name = fields.Char(string='Tên Tiêu Chí', required=True)
    kpi_type = fields.Selection([
        ('quantitative', 'Quantitative'),
        ('binary', 'Binary'),
        ('rating', 'Rating'),
        ('score', 'Score'),
    ], required=True, default='quantitative')
    description = fields.Html(
        string="Description",
        sanitize=True,
        help="Additional guidance for employees/managers about how this KPI should be evaluated.",
    )

    target = fields.Float(default=0.0)
    target_type = fields.Selection([('value', 'Value'), ('percentage', 'Percentage')], default='value')
    direction = fields.Selection([('higher_better', 'Higher is better'), ('lower_better', 'Lower is better')],
                                 default='higher_better')
    weight = fields.Float(default=1.0)
    is_auto = fields.Boolean(default=False)
    target_display = fields.Char(string="Target", compute="_compute_display", store=False)

    data_source = fields.Selection([
        ('manual', 'Manual'),
        ('dept_task_completion', 'Tỷ lệ hoàn thành task phòng ban'),
        ('dept_attendance_rate', 'Tỷ lệ chuyên cần phòng ban'),
        ('dept_avg_individual', 'TB điểm cá nhân (auto-aggregated)'),
    ], default='manual')

    is_section = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    department_kpi_id = fields.Many2one('hr.department.kpi', ondelete='cascade')

    @api.constrains('kpi_type', 'target')
    def _check_numeric_target(self):
        for rec in self:
            if rec.is_section:
                continue
            if rec.kpi_type == 'quantitative' and (rec.target or 0.0) < 0.0:
                raise ValidationError("For Quantitative KPI type, Target must be greater than or equal 0.")

    @api.depends('target', 'target_type', 'kpi_type')
    def _compute_display(self):
        for rec in self:
            if rec.is_section:
                rec.target_display = ''
                continue
            if rec.kpi_type != 'quantitative':
                rec.target_display = ''
                continue

            if rec.target_type == 'percentage':
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                rec.target_display = f"{(rec.target or 0.0):g}"
