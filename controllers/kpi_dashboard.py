import json
import logging
from datetime import date, timedelta, datetime, time

import pytz

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KpiDashboardController(http.Controller):
    """JSON endpoint supplying all data for the KPI dashboard page."""

    @http.route("/kpi/dashboard/data", type="http", auth="user", methods=["GET"])
    def get_dashboard_data(self, evaluation_id=None, **kwargs):
        if not evaluation_id:
            return request.make_response(
                json.dumps({"error": "evaluation_id is required"}, default=str),
                headers=[("Content-Type", "application/json")],
            )

        evaluation = request.env["hr.performance.evaluation"].browse(int(evaluation_id))
        if not evaluation.exists():
            return request.make_response(
                json.dumps({"error": "Evaluation not found"}, default=str),
                headers=[("Content-Type", "application/json")],
            )

        # Check access
        try:
            evaluation.check_access_rights("read")
            evaluation.check_access_rule("read")
        except Exception:
            return request.make_response(
                json.dumps({"error": "Access denied"}, default=str),
                headers=[("Content-Type", "application/json")],
            )

        result = {
            "evaluation_id": evaluation.id,
            "employee_name": evaluation.employee_id.name or "",
            "period": evaluation.period or "",
            "start_date": str(evaluation.start_date) if evaluation.start_date else "",
            "end_date": str(evaluation.end_date) if evaluation.end_date else "",
            "performance_score": evaluation.performance_score or 0.0,
            "performance_level": evaluation.performance_level or "",
            "task_completion": self._get_task_completion_data(evaluation),
            "punctuality_log": self._get_punctuality_log_data(evaluation),
            'attendance_full': self._get_attendance_full_data(evaluation),
            "spider_web": self._get_spider_web_data(evaluation),
            "quantitative_table": self._get_quantitative_table_data(evaluation),
        }
        return request.make_response(
            json.dumps(result, default=str),
            headers=[("Content-Type", "application/json")],
        )

    # ------------------------------------------------------------------
    # Task Completion – daily on-time task rate (data_source=task_on_time)
    # ------------------------------------------------------------------
    # def _get_task_completion_data(self, evaluation):
    #     """
    #     Returns per-day % of tasks completed on time.
    #     y-axis unit: % (0-100)
    #     """
    #     line = evaluation.evaluation_line_ids.filtered(
    #         lambda l: not l.is_section and l.data_source == "task_on_time"
    #     )
    #     if not line:
    #         return {"labels": [], "data": [], "target": 0.0}

    #     line = line[0]
    #     employee = evaluation.employee_id
    #     user = employee.user_id
    #     if not user or not evaluation.start_date or not evaluation.end_date:
    #         return {"labels": [], "data": [], "target": float(line.target or 0.0)}

    #     # Build per-day data
    #     start = evaluation.start_date
    #     end = evaluation.end_date
    #     days = (end - start).days + 1

    #     Task = request.env["project.task"].sudo()
    #     user_tz = pytz.timezone(request.env.user.tz or "UTC")

    #     labels = []
    #     data = []

    #     for i in range(days):
    #         day = start + timedelta(days=i)
    #         labels.append(f"Day {i + 1}")

    #         # Tasks with deadline on this day assigned to employee and done
    #         tasks = Task.search(
    #             [
    #                 ("user_ids", "in", user.id),
    #                 ("stage_id.is_done_stage", "=", True),
    #                 ("date_deadline", ">=", day),
    #                 ("date_deadline", "<=", day),
    #                 ("project_id", "!=", False),
    #             ]
    #         )

    #         if not tasks:
    #             data.append(None)
    #             continue

    #         on_time = 0
    #         total = 0
    #         for t in tasks:
    #             if not t.done_date or not t.date_deadline:
    #                 continue
    #             total += 1
    #             done_local = t.done_date.replace(tzinfo=pytz.UTC).astimezone(user_tz)
    #             deadline_local = (
    #                 t.date_deadline.replace(tzinfo=pytz.UTC).astimezone(user_tz)
    #                 if hasattr(t.date_deadline, "replace")
    #                 else None
    #             )
    #             if not deadline_local:
    #                 # date only: treat as end of day
    #                 from datetime import datetime as dt, time as tm

    #                 deadline_dt = dt.combine(t.date_deadline, tm(23, 59, 59)).replace(
    #                     tzinfo=user_tz
    #                 )
    #                 deadline_local = deadline_dt
    #             if done_local <= deadline_local:
    #                 on_time += 1

    #         rate = round((on_time / total * 100) if total > 0 else 0.0, 1)
    #         data.append(rate)

    #     return {
    #         "labels": labels,
    #         "data": data,
    #         "target": float(line.target or 100.0),
    #     }

    def _get_task_completion_data(self, evaluation):
        line = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.data_source == "task_on_time"
        )
        if not line or not evaluation.start_date or not evaluation.end_date:
            return {"labels": [], "data": [], "target": 0.0}

        line = line[0]
        engine = request.env["hr.kpi.engine"]
        per_day = engine.get_task_on_time_by_day(
            evaluation.employee_id,
            line,
            evaluation.start_date,
            evaluation.end_date,
        )
        days = (evaluation.end_date - evaluation.start_date).days + 1
        return {
            "labels": [f"Day {i + 1}" for i in range(days)],
            "data": per_day,
            "target": float(line.target or 100.0),
        }

    # ------------------------------------------------------------------
    # Punctuality Log – first check-in hour per day (data_source=late_days)
    # ------------------------------------------------------------------
    # def _get_punctuality_log_data(self, evaluation):
    #     """
    #     Returns first check-in hour per working day (decimal hour, e.g. 8.5 = 8:30).
    #     y-axis: hour 0-24 (displayed as 7h, 8h, 9h, …)
    #     """
    #     line = evaluation.evaluation_line_ids.filtered(
    #         lambda l: not l.is_section and l.data_source == "late_days"
    #     )
    #     if not line:
    #         return {"labels": [], "data": [], "expected_hour": 8.0}

    #     line = line[0]
    #     employee = evaluation.employee_id
    #     if not evaluation.start_date or not evaluation.end_date:
    #         return {"labels": [], "data": [], "expected_hour": 8.0}

    #     start = evaluation.start_date
    #     end = evaluation.end_date
    #     days = (end - start).days + 1

    #     tz_name = (
    #         employee.resource_calendar_id.tz
    #         or employee.tz
    #         or request.env.user.tz
    #         or "UTC"
    #     )
    #     tz = pytz.timezone(tz_name)

    #     dt_start_utc = datetime.combine(start, time.min)
    #     dt_end_utc = datetime.combine(end + timedelta(days=1), time.min)

    #     Attendance = request.env["hr.attendance"].sudo()
    #     attendances = Attendance.search(
    #         [
    #             ("employee_id", "=", employee.id),
    #             ("check_in", ">=", dt_start_utc),
    #             ("check_in", "<", dt_end_utc),
    #         ],
    #         order="check_in asc",
    #     )

    #     # Build first check-in per local date
    #     first_ci_by_date = {}
    #     for att in attendances:
    #         if not att.check_in:
    #             continue
    #         ci_utc = att.check_in.replace(tzinfo=pytz.UTC)
    #         ci_local = ci_utc.astimezone(tz)
    #         day = ci_local.date()
    #         if day not in first_ci_by_date:
    #             first_ci_by_date[day] = ci_local.hour + ci_local.minute / 60.0

    #     # Determine expected start hour from calendar
    #     calendar = employee.resource_calendar_id
    #     expected_hour = 8.0
    #     if calendar:
    #         # Get earliest hour_from for Mon-Fri
    #         hours = calendar.attendance_ids.filtered(
    #             lambda a: not a.display_type and a.day_period != "lunch"
    #         ).mapped("hour_from")
    #         if hours:
    #             expected_hour = min(hours)

    #     labels = []
    #     data = []
    #     for i in range(days):
    #         day = start + timedelta(days=i)
    #         labels.append(f"Day {i + 1}")
    #         ci_hour = first_ci_by_date.get(day)
    #         data.append(round(ci_hour, 2) if ci_hour is not None else None)

    #     return {
    #         "labels": labels,
    #         "data": data,
    #         "expected_hour": round(expected_hour, 2),
    #     }
    def _get_punctuality_log_data(self, evaluation):
        """Per-day first check-in hour cho biểu đồ punctuality.
 
        Thay vì tự tính, gọi engine để đảm bảo nhất quán với điểm KPI thực tế:
        - Cùng timezone resolution
        - Cùng cách xác định first check-in per day
        - expected_hour phản ánh đúng giờ làm việc danh nghĩa trên calendar
 
        Grace period KHÔNG được cộng vào expected_hour ở đây — đó là ngưỡng
        tính "trễ" nội bộ trong engine, không phải giờ hiển thị cho người dùng.
 
        Returns dict:
            labels        list[str]         — ["Day 1", "Day 2", ...]
            data          list[float|None]  — giờ check-in decimal, None nếu vắng
            expected_hour float             — giờ bắt đầu từ calendar (ví dụ 8.0)
            grace_minutes int               — grace period đang cấu hình (hiển thị
                                              thêm trên UI nếu muốn)
        """
        line = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.data_source == 'late_days'
        )
        if not line or not evaluation.start_date or not evaluation.end_date:
            return {'labels': [], 'data': [], 'expected_hour': 8.0, 'grace_minutes': 0}
 
        line = line[0]
        employee = evaluation.employee_id
        engine = request.env['hr.kpi.engine']
 
        # Per-day check-in hours — cùng logic với _compute_late_days
        per_day = engine.get_late_days_by_day(
            employee, line,
            evaluation.start_date, evaluation.end_date,
        )
 
        # Giờ bắt đầu danh nghĩa từ calendar (chưa cộng grace)
        expected_hour = engine.get_expected_start_hour(employee)
 
        # Grace period hiện tại — để dashboard có thể vẽ thêm đường ngưỡng nếu cần
        grace_minutes = engine._get_late_grace_minutes()
 
        days = (evaluation.end_date - evaluation.start_date).days + 1
        labels = [f"Day {i + 1}" for i in range(days)]
 
        return {
            'labels': labels,
            'data': per_day,
            'expected_hour': expected_hour,
            'grace_minutes': grace_minutes,
        }
 
    # ------------------------------------------------------------------
    # Attendance Full — data_source = attendance_full
    # ------------------------------------------------------------------
    def _get_attendance_full_data(self, evaluation):
        """Dữ liệu tổng hợp cho widget attendance_full trên dashboard.
 
        Trả về 2 phần:
          summary   — các con số tổng hợp (worked/expected/leave days, v.v.)
                      để render progress bar / số liệu tóm tắt.
          calendar  — per-day status list để render calendar heatmap.
 
        Tất cả tính toán đều uỷ quyền cho engine — dashboard chỉ format.
 
        Returns dict:
            summary:
                value               float  — KPI actual (unpaid_leave_days hoặc %)
                expected_work_days  float
                worked_days         float
                approved_leave_days float
                public_holiday_days float
                unpaid_leave_days   float
                has_unpaid_leave    bool
                target              float  — từ kpi line
                target_type         str    — 'value' | 'percentage'
            calendar:
                list[{'date': 'YYYY-MM-DD', 'status': str}]
                status ∈ {'present', 'approved_leave', 'public_holiday', 'absent'}
        """
        empty = {
            'summary': {
                'value': 0.0,
                'expected_work_days': 0.0,
                'worked_days': 0.0,
                'approved_leave_days': 0.0,
                'public_holiday_days': 0.0,
                'unpaid_leave_days': 0.0,
                'has_unpaid_leave': False,
                'target': 0.0,
                'target_type': 'value',
            },
            'calendar': [],
        }
 
        line = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.data_source == 'attendance_full'
        )
        if not line or not evaluation.start_date or not evaluation.end_date:
            return empty
 
        line = line[0]
        employee = evaluation.employee_id
        engine = request.env['hr.kpi.engine']
 
        # ── Summary metrics (tái sử dụng _compute_attendance_full_with_metrics) ──
        metrics = engine.get_attendance_full_period_metrics(
            employee, line,
            evaluation.start_date, evaluation.end_date,
        )
        summary = dict(metrics)
        summary['target'] = float(line.target or 0.0)
        summary['target_type'] = line.target_type or 'value'
 
        # ── Per-day calendar data ─────────────────────────────────────────────
        calendar_data = engine.get_attendance_worked_dates(
            employee,
            evaluation.start_date, evaluation.end_date,
        )
 
        return {
            'summary': summary,
            'calendar': calendar_data,
        }

    # ------------------------------------------------------------------
    # Spider Web – non-quantitative KPIs
    # ------------------------------------------------------------------
    def _get_spider_web_data(self, evaluation):
        lines = evaluation.evaluation_line_ids.filtered(
            lambda l: not l.is_section and l.kpi_type != "quantitative"
        )
        labels = []
        scores = []
        max_val = 10.0

        for line in lines:
            labels.append(line.key_performance_area or "KPI")
            scores.append(round(float(line.final_rating or 0.0), 2))

        return {
            "labels": labels,
            "scores": scores,
            "max": max_val,
        }

    # ------------------------------------------------------------------
    # Quantitative Table
    # ------------------------------------------------------------------
    def _get_quantitative_table_data(self, evaluation):
        lines = evaluation.evaluation_line_ids.filtered(
            lambda l: (
                not l.is_section
                and l.kpi_type == "quantitative"
                and l.data_source not in ("task_on_time", "late_days")
            )
        )
        rows = []
        for line in lines:
            target = float(line.target or 0.0)
            actual = float(line.actual or 0.0)
            final = float(line.final_rating or 0.0)

            if target != 0:
                variance_pct = round((actual - target) / abs(target) * 100, 1)
            else:
                variance_pct = 0.0

            unit = "%" if (line.target_type == "percentage") else ""
            rows.append(
                {
                    "name": line.key_performance_area or "",
                    "target": f"{target:g}{unit}",
                    "actual": f"{actual:g}{unit}",
                    "variance": variance_pct,
                    "final_score": round(final, 2),
                    "direction": line.direction or "higher_better",
                }
            )
        return rows
