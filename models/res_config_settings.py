from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kpi_threshold_excellent = fields.Float(
        string="KPI Excellent Threshold",
        default=9.0,
        config_parameter='custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent',
        help="Score >= this value is considered Excellent.",
    )
    kpi_threshold_pass = fields.Float(
        string="KPI Pass Threshold",
        default=5.0,
        config_parameter='custom_adecsol_hr_performance_evaluator.kpi_threshold_pass',
        help="Score >= this value (and < Excellent) is considered Pass.",
    )
    late_grace_minutes = fields.Integer(
        string="Late Grace Minutes",
        default=30,
        config_parameter='custom_adecsol_hr_performance_evaluator.late_grace_minutes',
        help="Number of minutes an employee is allowed to be late without being marked as late or penalized. For example, if set to 30, arriving at 8:30 for an 8:00 shift is still considered on time.",
    )
