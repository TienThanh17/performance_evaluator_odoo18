from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestHrKpiEngineAttendance(TransactionCase):
    # Chuẩn bị dữ liệu tối thiểu để test routing compute() và các helper attendance.
    def setUp(self):
        super().setUp()
        self.Engine = self.env["hr.kpi.engine"]
        self.Employee = self.env["hr.employee"]
        self.Evaluation = self.env["hr.performance.evaluation"]
        self.Line = self.env["hr.performance.evaluation.line"]
        self.KpiTemplate = self.env["hr.kpi.template"]
        self.Pillar = self.env["hr.evaluation.pillar"]

        # Tạo nhân viên không có calendar để dễ test các nhánh zero-safe.
        self.employee = self.Employee.create({"name": "Attendance Engine Employee"})
        self.date_from = fields.Date.from_string("2026-06-01")
        self.date_to = fields.Date.from_string("2026-06-30")

        # Dùng pillar P3 có sẵn hoặc tạo mới để line auto KPI hợp lệ.
        self.pillar = self.Pillar.search([("code", "=", "p3_individual")], limit=1)
        if not self.pillar:
            self.pillar = self.Pillar.create(
                {
                    "name": "P3 Individual",
                    "code": "p3_individual",
                }
            )

        # Tạo KPI template tối thiểu để action_compute_auto_kpi không bị skip vì thiếu kpi_id.
        self.kpi_template = self.KpiTemplate.create(
            {
                "name": "Attendance KPI Template",
                "period_type": "monthly",
            }
        )
        self.evaluation = self.Evaluation.create(
            {
                "employee_id": self.employee.id,
                "kpi_id": self.kpi_template.id,
                "start_date": self.date_from,
                "end_date": self.date_to,
            }
        )

        # Lấy data source system đã seed để test đúng route thật của engine.
        self.present_source = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.source_attendance_present_days"
        )
        self.unpaid_source = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.source_attendance_unpaid_leave_days"
        )
        self.late_source = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.source_attendance_late_days"
        )

        self.fake_metrics = {
            "expected_work_days": 22.0,
            "worked_days": 19.0,
            "approved_leave_days": 2.0,
            "public_holiday_days": 1.0,
            "unpaid_leave_days": 1.0,
            "has_unpaid_leave": True,
        }

    # Tạo line auto KPI theo đúng data source cần test.
    def _create_auto_line(self, source):
        return self.Line.create(
            {
                "evaluation_id": self.evaluation.id,
                "key_performance_area": "Attendance KPI",
                "kpi_type": "auto",
                "pillar_id": self.pillar.id,
                "weight": 100.0,
                "data_source_id": source.id,
                "unit": source.unit_id.id,
            }
        )

    # Khóa contract compute() của data source attendance_present_days phải trả worked_days.
    def test_compute_returns_worked_days_for_present_source(self):
        line = self._create_auto_line(self.present_source)

        # Stub metrics helper để test đúng routing mà không cần dựng attendance thật.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            value = self.Engine.compute(
                self.employee, line, self.date_from, self.date_to
            )

        self.assertEqual(value, self.fake_metrics["worked_days"])

    # Khóa wrapper attendance present chỉ trả raw worked_days từ metrics helper.
    def test_compute_attendance_period_value_with_metrics_returns_worked_days(self):
        line = self._create_auto_line(self.present_source)

        # Dùng cùng fake metrics để đảm bảo wrapper không tự tính logic riêng.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            value = self.Engine.compute_attendance_period_value_with_metrics(
                self.employee, line, self.date_from, self.date_to
            )

        self.assertEqual(value, self.fake_metrics["worked_days"])

    # Khóa contract compute() của data source unpaid leave phải trả unpaid_leave_days.
    def test_compute_returns_unpaid_leave_days_for_unpaid_source(self):
        line = self._create_auto_line(self.unpaid_source)

        # Stub metrics helper để assert compute() route đúng bucket unpaid leave.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            value = self.Engine.compute(
                self.employee, line, self.date_from, self.date_to
            )

        self.assertEqual(value, self.fake_metrics["unpaid_leave_days"])

    # Khóa wrapper unpaid leave chỉ trả raw unpaid_leave_days từ helper dùng chung.
    def test_compute_attendance_unpaid_leave_days_value_returns_unpaid_days(self):
        line = self._create_auto_line(self.unpaid_source)

        # Dùng fake metrics để kiểm tra method mới không phát sinh logic riêng.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            value = self.Engine.compute_attendance_unpaid_leave_days_value(
                self.employee, line, self.date_from, self.date_to
            )

        self.assertEqual(value, self.fake_metrics["unpaid_leave_days"])

    # Đảm bảo dashboard/report vẫn nhận đủ metrics và value bám theo compute().
    def test_get_attendance_period_metrics_keeps_breakdown_and_compute_value(self):
        present_line = self._create_auto_line(self.present_source)
        unpaid_line = self._create_auto_line(self.unpaid_source)

        # Stub metrics helper để so sánh value giữa 2 data source trên cùng breakdown.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            present_metrics = self.Engine.get_attendance_period_metrics(
                self.employee, present_line, self.date_from, self.date_to
            )
            unpaid_metrics = self.Engine.get_attendance_period_metrics(
                self.employee, unpaid_line, self.date_from, self.date_to
            )

        for key, expected in self.fake_metrics.items():
            self.assertIn(key, present_metrics)
            self.assertIn(key, unpaid_metrics)
            self.assertEqual(present_metrics[key], expected)
            self.assertEqual(unpaid_metrics[key], expected)

        self.assertEqual(present_metrics["value"], self.fake_metrics["worked_days"])
        self.assertEqual(
            unpaid_metrics["value"], self.fake_metrics["unpaid_leave_days"]
        )

    # Đảm bảo các input thiếu hoặc không hợp lệ luôn trả zero-safe thay vì lỗi.
    def test_attendance_methods_return_zero_safely_for_invalid_inputs(self):
        line = self._create_auto_line(self.present_source)
        zero_metrics = dict(
            expected_work_days=0.0,
            worked_days=0.0,
            approved_leave_days=0.0,
            public_holiday_days=0.0,
            unpaid_leave_days=0.0,
            has_unpaid_leave=False,
            value=0.0,
        )

        # Thiếu employee hoặc thiếu line phải trả 0 ngay từ entrypoint compute().
        self.assertEqual(
            self.Engine.compute(False, line, self.date_from, self.date_to), 0.0
        )
        self.assertEqual(
            self.Engine.compute(self.employee, False, self.date_from, self.date_to),
            0.0,
        )

        # Date range ngược hoặc employee không có calendar phải trả raw value bằng 0.
        self.assertEqual(
            self.Engine.compute_attendance_period_value_with_metrics(
                self.employee, line, self.date_to, self.date_from
            ),
            0.0,
        )
        self.assertEqual(
            self.Engine.compute_attendance_unpaid_leave_days_value(
                self.employee, line, self.date_from, self.date_to
            ),
            0.0,
        )

        # Breakdown metrics cũng phải trả đủ key zero-safe khi input không hợp lệ.
        self.assertEqual(
            self.Engine.get_attendance_period_metrics(
                self.employee, False, self.date_from, self.date_to
            ),
            zero_metrics,
        )
        self.assertEqual(
            self.Engine.get_attendance_period_metrics(
                self.employee, line, self.date_to, self.date_from
            ),
            zero_metrics,
        )

    # Đảm bảo action_compute_auto_kpi ghi actual theo compute() sau refactor.
    def test_action_compute_auto_kpi_uses_compute_entrypoint(self):
        line = self._create_auto_line(self.unpaid_source)

        # Stub helper để action_compute_auto_kpi nhận actual từ compute() mới.
        with patch.object(
            type(self.Engine),
            "_get_attendance_period_metrics_data",
            return_value=dict(self.fake_metrics),
        ):
            self.evaluation.action_compute_auto_kpi()

        self.assertEqual(
            line.actual,
            self.fake_metrics["unpaid_leave_days"],
        )

    # Đảm bảo route system khác như late days không bị ảnh hưởng bởi refactor attendance.
    def test_compute_keeps_late_days_system_route(self):
        line = self._create_auto_line(self.late_source)

        # Stub late method riêng để xác nhận compute() vẫn route đúng nhánh cũ.
        with patch.object(
            type(self.Engine),
            "compute_late_arrival_value",
            return_value=3.0,
        ):
            value = self.Engine.compute(
                self.employee, line, self.date_from, self.date_to
            )

        self.assertEqual(value, 3.0)
