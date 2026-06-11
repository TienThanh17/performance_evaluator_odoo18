from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kpi_threshold_excellent = fields.Float(
        string="KPI Excellent Threshold",
        default=90.0,
        config_parameter='custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent',
        help="Score >= this value is considered Excellent.",
    )
    kpi_threshold_pass = fields.Float(
        string="KPI Pass Threshold",
        default=50.0,
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

    # Trả về thang điểm KPI chuẩn duy nhất của module.
    def get_score_scale_base(self):
        return 100.0

    # Trả metadata dùng chung cho backend/frontend khi format điểm KPI.
    def get_score_scale_info(self):
        base = self.get_score_scale_base()
        return {
            "base": base,
            "display_multiplier": 1,
            "suffix": f" / {int(base)}",
        }

    # Lấy ngưỡng KPI từ system parameters theo thang điểm chuẩn 100.
    def get_thresholds(self):
        icp = self.env['ir.config_parameter'].sudo()
        excellent = float(
            icp.get_param(
                'custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent',
                default='90',
            )
            or 90.0
        )
        passed = float(
            icp.get_param(
                'custom_adecsol_hr_performance_evaluator.kpi_threshold_pass',
                default='50',
            )
            or 50.0
        )
        return excellent, passed

    # Lưu thêm các system parameter số nguyên để giữ nguyên cả trường hợp nhập 0.
    def set_values(self):
        super(ResConfigSettings, self).set_values()

        # Ép buộc ghi giá trị '0' vào System Parameters nếu người dùng nhập 0.
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_adecsol_hr_performance_evaluator.late_grace_minutes',
            str(self.late_grace_minutes)
        )

