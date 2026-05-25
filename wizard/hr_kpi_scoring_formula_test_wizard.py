from odoo import api, fields, models


class HrKpiScoringFormulaTestWizard(models.TransientModel):
    _name = "hr.kpi.scoring.formula.test.wizard"
    _description = "Test KPI Scoring Formula"

    formula_id = fields.Many2one("hr.kpi.scoring.formula", required=True)
    test_actual = fields.Float(string="Actual (thu nghiem)", default=80.0)
    test_target = fields.Float(string="Target (thu nghiem)", default=100.0)
    test_result = fields.Float(string="Ket qua diem", readonly=True)
    result_computed = fields.Boolean(default=False)
    threshold_pass = fields.Float(compute="_compute_thresholds")
    threshold_excellent = fields.Float(compute="_compute_thresholds")
    result_status = fields.Selection(
        [
            ("fail", "Fail"),
            ("pass", "Pass"),
            ("excellent", "Excellent"),
        ],
        compute="_compute_result_status",
        string="Trang thai ket qua",
    )

    @api.depends()
    def _compute_thresholds(self):
        threshold_excellent, threshold_pass = (
            self.env["res.config.settings"].get_thresholds()
        )
        for rec in self:
            rec.threshold_pass = threshold_pass
            rec.threshold_excellent = threshold_excellent

    @api.depends("result_computed", "test_result", "threshold_pass", "threshold_excellent")
    def _compute_result_status(self):
        for rec in self:
            if not rec.result_computed:
                rec.result_status = False
            elif (rec.test_result or 0.0) >= (rec.threshold_excellent or 0.0):
                rec.result_status = "excellent"
            elif (rec.test_result or 0.0) >= (rec.threshold_pass or 0.0):
                rec.result_status = "pass"
            else:
                rec.result_status = "fail"

    def action_compute(self):
        self.ensure_one()
        self.test_result = self.formula_id.compute_score(
            self.test_actual,
            self.test_target,
        )
        self.result_computed = True
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
