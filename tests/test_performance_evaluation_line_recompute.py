from odoo.tests.common import TransactionCase


class TestPerformanceEvaluationLineRecompute(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Employee = self.env["hr.employee"]
        self.Evaluation = self.env["hr.performance.evaluation"]
        self.Line = self.env["hr.performance.evaluation.line"]
        self.Pillar = self.env["hr.evaluation.pillar"]

        self.p3_individual_pillar = self.Pillar.search(
            [("code", "=", "p3_individual")], limit=1
        )
        if not self.p3_individual_pillar:
            self.p3_individual_pillar = self.Pillar.create(
                {
                    "name": "P3 Individual",
                    "code": "p3_individual",
                }
            )

        # Reuse an existing evaluation to support databases with legacy required columns.
        self.evaluation = self.Evaluation.search([], limit=1)
        if not self.evaluation:
            self.employee = self.Employee.create({"name": "KPI Recompute Employee"})
            self.evaluation = self.Evaluation.create(
                {
                    "employee_id": self.employee.id,
                }
            )
        self.parent_line = self.Line.create(
            {
                "evaluation_id": self.evaluation.id,
                "key_performance_area": "Parent KPI",
                "kpi_type": "auto",
                "pillar_id": self.p3_individual_pillar.id,
                "weight": 100.0,
            }
        )
        self.child_line_1 = self.Line.create(
            {
                "evaluation_id": self.evaluation.id,
                "parent_line_id": self.parent_line.id,
                "key_performance_area": "Child KPI 1",
                "kpi_type": "manual",
                "manual_scoring_type": "score",
                "pillar_id": self.p3_individual_pillar.id,
                "weight": 50.0,
                "employee_rating_score": 60.0,
                "manager_rating_score": 60.0,
            }
        )
        self.child_line_2 = self.Line.create(
            {
                "evaluation_id": self.evaluation.id,
                "parent_line_id": self.parent_line.id,
                "key_performance_area": "Child KPI 2",
                "kpi_type": "manual",
                "manual_scoring_type": "score",
                "pillar_id": self.p3_individual_pillar.id,
                "weight": 50.0,
                "employee_rating_score": 80.0,
                "manager_rating_score": 80.0,
            }
        )

    def test_child_score_write_updates_parent_immediately(self):
        parent = self.Line.browse(self.parent_line.id)
        evaluation = self.Evaluation.browse(self.evaluation.id)

        self.assertAlmostEqual(parent.final_rating, 70.0, places=2)
        self.assertAlmostEqual(evaluation.total_p3_individual, 70.0, places=2)

        self.child_line_1.write({"employee_rating_score": 90.0})

        parent = self.Line.browse(self.parent_line.id)
        child_line_1 = self.Line.browse(self.child_line_1.id)
        evaluation = self.Evaluation.browse(self.evaluation.id)

        self.assertAlmostEqual(child_line_1.manager_rating_score, 90.0, places=2)
        self.assertAlmostEqual(parent.final_rating, 85.0, places=2)
        self.assertAlmostEqual(evaluation.total_p3_individual, 85.0, places=2)
        self.assertAlmostEqual(evaluation.result_score, 0.0, places=2)
        self.assertEqual(
            evaluation.performance_level,
            evaluation._get_level_from_score(evaluation.result_score),
        )
