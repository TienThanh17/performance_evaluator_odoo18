from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    P3_INDIVIDUAL_WEIGHT_DEFAULT = 60
    P3_DEPARTMENT_WEIGHT_DEFAULT = 40

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
    p3_individual_weight_percent = fields.Integer(
        string="P3.1.1 Weight",
        default=P3_INDIVIDUAL_WEIGHT_DEFAULT,
        config_parameter='custom_adecsol_hr_performance_evaluator.p3_individual_weight_percent',
        help="Percentage weight assigned to the P3.1.1 individual KPI score in the 3P summary total.",
    )
    p3_department_weight_percent = fields.Integer(
        string="P3.1.2 Weight",
        default=P3_DEPARTMENT_WEIGHT_DEFAULT,
        config_parameter='custom_adecsol_hr_performance_evaluator.p3_department_weight_percent',
        help="Percentage weight assigned to the P3.1.2 department KPI score in the 3P summary total.",
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

    # Chuẩn hóa và trả về bộ trọng số P3 dùng cho màn tổng hợp 3P.
    def get_p3_summary_weights(self):
        icp = self.env['ir.config_parameter'].sudo()

        # Đọc từng system parameter theo kiểu an toàn để các database cũ hoặc dữ
        # liệu sửa tay sai định dạng vẫn rơi về bộ mặc định hợp lệ.
        try:
            individual_weight = int(
                float(
                    icp.get_param(
                        'custom_adecsol_hr_performance_evaluator.p3_individual_weight_percent',
                        default=str(self.P3_INDIVIDUAL_WEIGHT_DEFAULT),
                    )
                    or self.P3_INDIVIDUAL_WEIGHT_DEFAULT
                )
            )
        except (TypeError, ValueError):
            individual_weight = self.P3_INDIVIDUAL_WEIGHT_DEFAULT

        try:
            department_weight = int(
                float(
                    icp.get_param(
                        'custom_adecsol_hr_performance_evaluator.p3_department_weight_percent',
                        default=str(self.P3_DEPARTMENT_WEIGHT_DEFAULT),
                    )
                    or self.P3_DEPARTMENT_WEIGHT_DEFAULT
                )
            )
        except (TypeError, ValueError):
            department_weight = self.P3_DEPARTMENT_WEIGHT_DEFAULT

        # Nếu cấu hình đang ở trạng thái ngoài phạm vi hoặc tổng khác 100 thì
        # backend sẽ quay về bộ 60/40 an toàn thay vì làm sai công thức tổng hợp.
        if (
            individual_weight < 0
            or individual_weight > 100
            or department_weight < 0
            or department_weight > 100
            or individual_weight + department_weight != 100
        ):
            return (
                self.P3_INDIVIDUAL_WEIGHT_DEFAULT,
                self.P3_DEPARTMENT_WEIGHT_DEFAULT,
            )
        return individual_weight, department_weight

    # Chặn người dùng lưu wizard settings với bộ trọng số P3 không hợp lệ.
    @api.constrains(
        'p3_individual_weight_percent',
        'p3_department_weight_percent',
    )
    def _check_p3_summary_weights(self):
        for rec in self:
            # Mỗi trọng số phải là phần trăm hợp lệ trong khoảng 0..100.
            if rec.p3_individual_weight_percent < 0 or rec.p3_individual_weight_percent > 100:
                raise ValidationError(
                    "P3.1.1 weight must be between 0% and 100%."
                )
            if rec.p3_department_weight_percent < 0 or rec.p3_department_weight_percent > 100:
                raise ValidationError(
                    "P3.1.2 weight must be between 0% and 100%."
                )

            # Bộ trọng số dùng để chấm tổng phải luôn khép kín đúng 100%.
            if (
                rec.p3_individual_weight_percent
                + rec.p3_department_weight_percent
                != 100
            ):
                raise ValidationError(
                    "P3.1.1 and P3.1.2 weights must total exactly 100%."
                )

    # Lưu thêm các system parameter số nguyên để giữ nguyên cả trường hợp nhập 0.
    def set_values(self):
        super(ResConfigSettings, self).set_values()

        # Ép buộc ghi giá trị '0' vào System Parameters nếu người dùng nhập 0.
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_adecsol_hr_performance_evaluator.late_grace_minutes',
            str(self.late_grace_minutes)
        )

        # Ghi tường minh các trọng số P3 để cả trường hợp 0/100 hoặc 100/0 vẫn
        # được lưu nguyên vẹn thay vì phụ thuộc hoàn toàn vào cơ chế mặc định.
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_adecsol_hr_performance_evaluator.p3_individual_weight_percent',
            str(self.p3_individual_weight_percent)
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_adecsol_hr_performance_evaluator.p3_department_weight_percent',
            str(self.p3_department_weight_percent)
        )
