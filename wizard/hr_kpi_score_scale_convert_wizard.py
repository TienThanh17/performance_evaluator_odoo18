from odoo import _, fields, models
from odoo.exceptions import UserError


class HrKpiScoreScaleConvertWizard(models.TransientModel):
    _name = "hr.kpi.score.scale.convert.wizard"
    _description = "KPI Score Scale Conversion Wizard"

    from_scale = fields.Selection(
        selection=[("10", "10 điểm"), ("100", "100 điểm")],
        string="Current Scale",
        required=True,
        readonly=True,
        default=lambda self: str(
            int(self.env["res.config.settings"].get_score_scale_base())
        ),
    )
    to_scale = fields.Selection(
        selection=[("10", "10 điểm"), ("100", "100 điểm")],
        string="Target Scale",
        required=True,
        default=lambda self: "100"
        if self.env["res.config.settings"].get_score_scale_base() == 10.0
        else "10",
    )

    def _convert_table_fields(self, table, fields_to_convert, factor):
        """Nhân/chia trực tiếp các cột điểm đã lưu để không phụ thuộc recompute trigger."""
        set_clause = ", ".join(
            f"{field_name} = CASE WHEN {field_name} IS NULL THEN NULL ELSE {field_name} * %s END"
            for field_name in fields_to_convert
        )
        params = [factor] * len(fields_to_convert)
        self.env.cr.execute(f"UPDATE {table} SET {set_clause}", params)

    def _convert_child_average_targets(self, from_base, to_base, factor):
        """Chỉ đổi target/actual của KPI bottom-up vì đây là điểm, không phải số lượng nghiệp vụ."""
        if to_base > from_base:
            target_condition = "target <= %s"
            params = [factor, from_base]
        else:
            target_condition = "target > %s"
            params = [factor, to_base]

        self.env.cr.execute(
            f"""
            UPDATE hr_department_kpi_line
               SET target = target * %s
             WHERE data_source = 'child_kpi_average'
               AND target IS NOT NULL
               AND {target_condition}
            """,
            params,
        )
        self.env.cr.execute(
            f"""
            UPDATE hr_department_evaluation_line
               SET target = CASE
                       WHEN target IS NOT NULL AND {target_condition} THEN target * %s
                       ELSE target
                   END,
                   actual = CASE WHEN actual IS NULL THEN NULL ELSE actual * %s END
             WHERE data_source = 'child_kpi_average'
            """,
            [params[-1], factor, factor],
        )

    def action_convert(self):
        self.ensure_one()
        from_base = 100.0 if self.from_scale == "100" else 10.0
        to_base = 100.0 if self.to_scale == "100" else 10.0
        if from_base == to_base:
            raise UserError(_("Please choose a different target score scale."))

        factor = to_base / from_base
        self._convert_table_fields(
            "hr_performance_evaluation_line",
            [
                "system_score",
                "final_rating",
                "employee_rating_score",
                "manager_rating_score",
                "employee_rating_value",
                "manager_rating_value",
            ],
            factor,
        )
        self._convert_table_fields(
            "hr_department_evaluation_line",
            ["system_score", "final_score", "manager_rating_score"],
            factor,
        )
        self._convert_table_fields(
            "hr_performance_evaluation",
            ["performance_score", "final_score"],
            factor,
        )
        self._convert_table_fields(
            "hr_department_performance_evaluation",
            ["dept_kpi_score"],
            factor,
        )
        self._convert_child_average_targets(from_base, to_base, factor)

        settings = self.env["res.config.settings"]
        icp = self.env["ir.config_parameter"].sudo()
        excellent = float(
            icp.get_param(
                "custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent",
                default="9",
            )
            or 9.0
        )
        passed = float(
            icp.get_param(
                "custom_adecsol_hr_performance_evaluator.kpi_threshold_pass",
                default="5",
            )
            or 5.0
        )
        icp.set_param(
            "custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent",
            settings.convert_score(excellent, from_base, to_base),
        )
        icp.set_param(
            "custom_adecsol_hr_performance_evaluator.kpi_threshold_pass",
            settings.convert_score(passed, from_base, to_base),
        )
        icp.set_param(
            "custom_adecsol_hr_performance_evaluator.kpi_score_scale",
            self.to_scale,
        )

        self.env.invalidate_all()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("KPI score scale converted"),
                "message": _("Existing KPI scores and thresholds were converted successfully."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
