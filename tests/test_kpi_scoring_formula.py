from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestKpiScoringFormula(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Formula = self.env["hr.kpi.scoring.formula"]
        self.Period = self.env["hr.kpi.period"]
        self.KpiTemplate = self.env["hr.kpi.template"]
        self.KpiLine = self.env["hr.kpi.template.line"]
        self.period = self.Period.create(
            {
                "name": "2026-01",
                "period_type": "monthly",
                "date_start": "2026-01-01",
                "date_end": "2026-01-31",
            }
        )

    def test_linear_higher_better_normal(self):
        formula = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.formula_linear_higher"
        )
        self.assertEqual(formula.compute_score(80, 100, max_score=10), 8.0)

    def test_linear_higher_better_bonus(self):
        formula = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.formula_linear_higher_bonus"
        )
        self.assertEqual(formula.compute_score(120, 100, max_score=10), 12.0)

    def test_step_table_matched(self):
        formula = self.Formula.create(
            {
                "name": "Step Table Formula",
                "formula_type": "step_table",
                "step_table_json": (
                    '[{"from": 0, "to": 50, "score": 0}, '
                    '{"from": 50, "to": 80, "score": 5}, '
                    '{"from": 80, "to": null, "score": 10}]'
                ),
            }
        )
        self.assertEqual(formula.compute_score(75, 100, max_score=10), 5.0)
        self.assertEqual(formula.compute_score(90, 100, max_score=10), 10.0)

    def test_penalty_floor(self):
        formula = self.Formula.create(
            {
                "name": "Penalty Formula",
                "formula_type": "penalty",
                "penalty_base_score": 0.0,
                "penalty_deduct_per_unit": 1.0,
                "penalty_floor": 0.0,
            }
        )
        self.assertEqual(formula.compute_score(3, 100, max_score=10), 7.0)
        self.assertEqual(formula.compute_score(15, 100, max_score=10), 0.0)

    def test_expression_blocked_keyword(self):
        with self.assertRaises(ValidationError):
            self.Formula.create(
                {
                    "name": "Unsafe Expression",
                    "formula_type": "expression",
                    "expression_code": "env['res.users']",
                }
            )

    def test_builtin_cannot_delete(self):
        formula = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.formula_linear_higher"
        )
        with self.assertRaises(UserError):
            formula.unlink()

    def test_get_effective_formula_fallback(self):
        template = self.KpiTemplate.create(
            {
                "name": "Template A",
                "period_id": self.period.id,
            }
        )
        line = self.KpiLine.create(
            {
                "kpi_id": template.id,
                "key_performance_area": "Task completion",
                "kpi_type": "quantitative",
                "direction": "higher_better",
                "formula_type": "linear",
            }
        )
        formula = line.get_effective_formula()
        self.assertTrue(formula)
        self.assertEqual(
            formula,
            self.env.ref(
                "custom_adecsol_hr_performance_evaluator.formula_linear_higher"
            ),
        )

    def test_get_effective_formula_legacy_step_table(self):
        template = self.KpiTemplate.create(
            {
                "name": "Template B",
                "period_id": self.period.id,
            }
        )
        line = self.KpiLine.create(
            {
                "kpi_id": template.id,
                "key_performance_area": "Legacy step",
                "kpi_type": "quantitative",
                "formula_type": "step_table",
                "step_table_json": (
                    '[{"from": 0, "to": 50, "score": 0}, '
                    '{"from": 50, "to": null, "score": 10}]'
                ),
            }
        )
        formula = line.get_effective_formula()
        self.assertTrue(formula)
        self.assertEqual(formula.formula_type, "step_table")
        self.assertEqual(formula.compute_score(60, 0, max_score=10), 10.0)
