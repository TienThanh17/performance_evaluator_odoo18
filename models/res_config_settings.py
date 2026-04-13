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
