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
    deadline_reminder_days = fields.Integer(
        string="Deadline Reminder Days",
        default=3,
        config_parameter='custom_adecsol_hr_performance_evaluator.deadline_reminder_days',
        help="Number of days before the deadline to send a reminder notification to employees.",
    )

    def get_thresholds(self):
        """Fetch KPI thresholds from system parameters."""
        icp = self.env['ir.config_parameter'].sudo()
        excellent = float(
            icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent', default='9') or 9.0)
        passed = float(icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_pass', default='5') or 5.0)
        return excellent, passed
