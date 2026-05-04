from odoo import models, fields, api


class HrDepartmentEvaluationLine(models.Model):
    _name = "hr.department.evaluation.line"
    _description = "Department Evaluation Line"

    evaluation_id = fields.Many2one(
        "hr.department.performance.evaluation", ondelete="cascade"
    )
    department_kpi_line_id = fields.Many2one("hr.department.kpi.line")

    name = fields.Char()
    kpi_type = fields.Selection(
        [
            ("quantitative", "Quantitative"),
            ("binary", "Binary"),
            ("rating", "Rating"),
            ("score", "Score"),
        ]
    )
    target = fields.Float()
    target_type = fields.Selection([("value", "Value"), ("percentage", "Percentage")])
    direction = fields.Selection(
        [("higher_better", "Higher is better"), ("lower_better", "Lower is better")]
    )
    actual = fields.Float()
    weight = fields.Float()
    is_auto = fields.Boolean()
    data_source = fields.Selection(
        [
            ("manual", "Manual"),
            # ('task_on_time', 'Task on time (cá nhân)'),
            # ('late_days', 'Late days (cá nhân)'),
            # ('attendance_full', 'Attendance full (cá nhân)'),
            ("dept_task_completion", "Tỷ lệ hoàn thành task phòng ban"),
            ("dept_attendance_rate", "Tỷ lệ chuyên cần phòng ban"),
            ("dept_avg_individual", "TB điểm cá nhân (auto-aggregated)"),
        ]
    )
    is_section = fields.Boolean()
    description = fields.Html(
        string="Description",
        sanitize=True,
    )
    sequence = fields.Integer(default=10)

    system_score = fields.Float(compute="_compute_system_score", store=True)
    final_score = fields.Float(compute="_compute_final_score", store=True)

    manager_score_override = fields.Float()
    use_override = fields.Boolean(default=False)
    manager_comment = fields.Text()

    # Formatted Target value for display(shows % when Target Type is Percentage).
    target_display = fields.Char(
        string="Target",
        compute="_compute_display",
        store=False,
    )
    # Formatted Actual value for display(shows % when Target Type is Percentage).
    actual_display = fields.Char(
        string="Actual",
        compute="_compute_display",
        store=False,
    )

    @api.depends("actual", "target", "kpi_type", "direction", "target_type")
    def _compute_system_score(self):
        for line in self:
            if line.is_section:
                line.system_score = 0.0
                continue

            score = 0.0
            actual = line.actual or 0.0
            target = line.target or 0.0

            if line.kpi_type == "quantitative":
                if target <= 0:
                    score = 0.0
                else:
                    if line.direction == "higher_better":
                        score = (actual / target) * 10.0
                    else:
                        score = (target / actual) * 10.0 if actual > 0 else 0.0
            elif line.kpi_type == "binary":
                score = 10.0 if actual >= target else 0.0
            elif line.kpi_type in ("rating", "score"):
                score = actual

            line.system_score = max(0.0, min(score, 10.0))

    @api.depends("system_score", "use_override", "manager_score_override")
    def _compute_final_score(self):
        for line in self:
            if line.use_override:
                line.final_score = max(
                    0.0, min(line.manager_score_override or 0.0, 10.0)
                )
            else:
                line.final_score = line.system_score

    @api.depends("target", "actual", "target_type", "kpi_type")
    def _compute_display(self):
        for rec in self:
            if rec.kpi_type != "quantitative":
                rec.target_display = ""
                rec.actual_display = ""
                continue

            if rec.target_type == "percentage":
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
                rec.actual_display = f"{(rec.actual or 0.0):g}%"
            else:
                rec.target_display = f"{(rec.target or 0.0):g}"
                rec.actual_display = f"{(rec.actual or 0.0):g}"

    def action_open_popup(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.department.evaluation.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_department_evaluation_line_form_popup"
            ).id,
            "target": "new",
        }
