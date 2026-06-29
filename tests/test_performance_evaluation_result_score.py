from odoo.tests.common import TransactionCase


class TestPerformanceEvaluationResultScore(TransactionCase):
    # Chuẩn bị summary 3P thật để test đúng luồng đồng bộ result_score từ summary line sang evaluation.
    def setUp(self):
        super().setUp()
        self.DepartmentEvaluation = self.env["hr.department.performance.evaluation"]
        self.Summary = self.env["hr.evaluation.3p.summary"]
        self.SummaryLine = self.env["hr.evaluation.3p.summary.line"]
        self.settings = self.env["res.config.settings"]

        # Dùng một phiếu KPI phòng ban đang hoạt động rồi aggregate để có summary line thật.
        self.department_evaluation = self.DepartmentEvaluation.search(
            [("state", "!=", "cancel")],
            order="id asc",
            limit=1,
        )
        self.assertTrue(
            self.department_evaluation,
            "Expected at least one active department evaluation from seeded data.",
        )
        self.summary = self.Summary.get_or_create_summary_for_department_evaluation(
            self.department_evaluation
        )
        self.summary.action_aggregate()

        # Ưu tiên evaluation có điểm KPI thô đang pass để test rõ rằng fail list không còn dựa vào total_p3_individual.
        candidate_lines = self.summary.line_ids.filtered(
            lambda line: line.evaluation_id and float(line.evaluation_id.total_p3_individual or 0.0) >= 50.0
        )
        self.summary_line = (
            candidate_lines[:1]
            or self.summary.line_ids.filtered("evaluation_id")[:1]
        )
        self.assertTrue(
            self.summary_line,
            "Expected aggregate to produce at least one summary line linked to an evaluation.",
        )
        self.evaluation = self.summary_line.evaluation_id

    # Ghi score kết quả trên line summary rồi đọc lại evaluation để assert giá trị đã đồng bộ.
    def _set_summary_result_score(self, score):
        self.summary_line.write({"p3_1_score": score})
        self.env.invalidate_all()
        return self.evaluation.browse(self.evaluation.id)

    # Đảm bảo performance_level map đúng theo p3_1_score của summary line thay vì total_p3_individual.
    def test_summary_line_score_drives_result_level(self):
        for score, expected_level in (
            (100.0, "excellent"),
            (80.0, "pass"),
            (70.0, "pass"),
            (50.0, "pass"),
            (0.0, "fail"),
        ):
            evaluation = self._set_summary_result_score(score)
            self.assertAlmostEqual(evaluation.result_score, score, places=2)
            self.assertEqual(evaluation.performance_level, expected_level)

    # Nếu phiếu không còn summary line thì result_score phải rơi về 0 và level mặc định là fail.
    def test_missing_summary_line_defaults_to_fail(self):
        self.SummaryLine.search([("evaluation_id", "=", self.evaluation.id)]).unlink()

        evaluation = self.evaluation.browse(self.evaluation.id)
        self.assertAlmostEqual(evaluation.result_score, 0.0, places=2)
        self.assertEqual(evaluation.performance_level, "fail")

    # Dashboard phòng ban phải đưa phiếu vào fail list theo result_score mới thay vì KPI thô.
    def test_department_dashboard_failed_list_uses_result_score(self):
        _threshold_excellent, threshold_pass = self.settings.get_thresholds()
        self.assertGreaterEqual(float(self.evaluation.total_p3_individual or 0.0), threshold_pass)

        self._set_summary_result_score(0.0)
        payload = self.department_evaluation.get_dashboard_data()
        failed_line = next(
            (
                line
                for line in payload.get("failed_evaluation_lines", [])
                if line.get("record_model") == "hr.performance.evaluation"
                and line.get("record_id") == self.evaluation.id
            ),
            None,
        )

        self.assertTrue(failed_line, "Expected the evaluation to appear in failed_evaluation_lines.")
        self.assertEqual(failed_line["level"], "fail")
        self.assertEqual(failed_line["score_label"], "P3.1 result")
        self.assertAlmostEqual(float(failed_line["score"]), 0.0, places=2)
