from odoo import _, api, fields, models


class HrKpiScoringProfile(models.Model):
    _name = "hr.kpi.scoring.profile"
    _description = "KPI Scoring Profile"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    threshold_excellent = fields.Float(default=85.0, digits=(5, 2))
    threshold_pass = fields.Float(default=60.0, digits=(5, 2))
    active = fields.Boolean(default=True)
    template_count = fields.Integer(compute="_compute_template_count")

    def _compute_template_count(self):
        employee_templates = self.env["hr.kpi.template"].with_context(active_test=False)
        department_templates = self.env["hr.department.kpi.template"].with_context(
            active_test=False
        )
        for rec in self:
            rec.template_count = employee_templates.search_count(
                [("scoring_profile_id", "=", rec.id)]
            ) + department_templates.search_count(
                [("scoring_profile_id", "=", rec.id)]
            )

    def get_thresholds(self):
        self.ensure_one()
        return (
            float(self.threshold_excellent or 0.0),
            float(self.threshold_pass or 0.0),
        )
