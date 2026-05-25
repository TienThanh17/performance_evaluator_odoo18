from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    kpi_score_scale = fields.Selection(
        selection=[
            ("10", "10 điểm"),
            ("100", "100 điểm"),
        ],
        string="KPI Score Scale",
        default="10",
        config_parameter="custom_adecsol_hr_performance_evaluator.kpi_score_scale",
        help="Choose the score scale used for storing, computing, thresholding, and displaying KPI scores.",
    )
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

    def get_score_scale_base(self):
        """Trả về thang điểm đang cấu hình; mặc định 10 để tương thích dữ liệu cũ."""
        scale = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "custom_adecsol_hr_performance_evaluator.kpi_score_scale",
                default="10",
            )
            or "10"
        )
        return 100.0 if str(scale) == "100" else 10.0

    def get_score_scale_info(self):
        """Metadata dùng chung cho backend/frontend khi format điểm KPI."""
        base = self.get_score_scale_base()
        return {
            "base": base,
            "display_multiplier": 1,
            "suffix": f" / {int(base)}",
        }

    def convert_score(self, value, from_base, to_base):
        """Quy đổi điểm giữa hai thang điểm, dùng cho wizard/migration."""
        if value in (False, None):
            return 0.0
        from_base = float(from_base or 10.0)
        to_base = float(to_base or 10.0)
        if from_base <= 0:
            return float(value or 0.0)
        return float(value or 0.0) * to_base / from_base

    def get_thresholds(self):
        """Fetch KPI thresholds from system parameters on the configured score scale."""
        icp = self.env['ir.config_parameter'].sudo()
        excellent = float(
            icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent', default='9') or 9.0)
        passed = float(icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_pass', default='5') or 5.0)
        return excellent, passed

    def _has_existing_kpi_score_data(self):
        """Có dữ liệu điểm rồi thì không đổi scale trực tiếp để tránh hiểu sai điểm cũ."""
        models_to_check = [
            "hr.performance.evaluation.line",
            "hr.department.evaluation.line",
            "hr.performance.evaluation",
            "hr.department.performance.evaluation",
        ]
        for model_name in models_to_check:
            if model_name in self.env.registry and self.env[model_name].sudo().search([], limit=1):
                return True
        return False

    def set_values(self):
        icp = self.env["ir.config_parameter"].sudo()
        old_scale = icp.get_param(
            "custom_adecsol_hr_performance_evaluator.kpi_score_scale",
            default="10",
        ) or "10"
        new_scale = self.kpi_score_scale or "10"
        scale_changed = str(old_scale) != str(new_scale)
        old_base = 100.0 if str(old_scale) == "100" else 10.0
        new_base = 100.0 if str(new_scale) == "100" else 10.0
        has_score_data = self._has_existing_kpi_score_data()

        if (
            scale_changed
            and has_score_data
            and not self.env.context.get("allow_kpi_score_scale_change")
        ):
            raise UserError(
                _(
                    "Cannot change KPI score scale directly because KPI score data already exists. "
                    "Please use the KPI Score Scale Conversion wizard so existing scores and thresholds are converted safely."
                )
            )

        if scale_changed:
            # Nếu người dùng chỉ đổi scale mà chưa nhập threshold mới, tự quy đổi ngưỡng hiện tại.
            if new_base > old_base:
                if (self.kpi_threshold_excellent or 0.0) <= old_base:
                    self.kpi_threshold_excellent = self.convert_score(
                        self.kpi_threshold_excellent, old_base, new_base
                    )
                if (self.kpi_threshold_pass or 0.0) <= old_base:
                    self.kpi_threshold_pass = self.convert_score(
                        self.kpi_threshold_pass, old_base, new_base
                    )
            elif new_base < old_base:
                if (self.kpi_threshold_excellent or 0.0) > new_base:
                    self.kpi_threshold_excellent = self.convert_score(
                        self.kpi_threshold_excellent, old_base, new_base
                    )
                if (self.kpi_threshold_pass or 0.0) > new_base:
                    self.kpi_threshold_pass = self.convert_score(
                        self.kpi_threshold_pass, old_base, new_base
                    )

        # Gọi super để Odoo thực hiện các logic mặc định trước
        super(ResConfigSettings, self).set_values()
        
        # Ép buộc ghi giá trị '0' vào System Parameters nếu người dùng nhập 0
        # Vì config_parameter lưu dưới dạng String, nên ta ép kiểu về str
        self.env['ir.config_parameter'].sudo().set_param(
            'custom_adecsol_hr_performance_evaluator.late_grace_minutes', 
            str(self.late_grace_minutes)
        )

        if (
            scale_changed
            and not has_score_data
            and "hr.department.kpi.template.line" in self.env.registry
        ):
            factor = new_base / old_base if old_base else 1.0
            if new_base > old_base:
                target_condition = "target <= %s"
                params = [factor, old_base]
            else:
                target_condition = "target > %s"
                params = [factor, new_base]
            # Chưa có phiếu đánh giá thì được phép chỉnh template bottom-up về target theo score scale mới.
            self.env.cr.execute(
                f"""
                UPDATE hr_department_kpi_template_line
                   SET target = target * %s
                 WHERE dept_source_type = 'child_kpi_average'
                   AND target IS NOT NULL
                   AND {target_condition}
                """,
                params,
            )

