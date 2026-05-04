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
    period = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("half_yearly", "Half-Yearly"),
            ("yearly", "Yearly"),
        ],
        string="Evaluation Period",
        required=True,
        default="monthly",
        help="The evaluation cycle for this KPI template.",
    )
