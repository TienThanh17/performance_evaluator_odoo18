import datetime
import logging
import math

import pytz

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class HrKpiDashboardChartService(models.AbstractModel):
    _name = "hr.kpi.dashboard.chart.service"
    _description = "KPI Dashboard Chart Service"

    @api.model
    def build_dynamic_charts(self, evaluation):
        evaluation = evaluation.sudo()
        if not evaluation:
            return []

        charts = []
        for line in evaluation.evaluation_line_ids.filtered(self._is_dashboard_line):
            chart = self._build_chart_for_line(evaluation, line)
            if chart:
                charts.append(chart)
        return charts

    def _provider_registry(self):
        return {
            "generic_target_actual_bar": {
                "builder": self._build_generic_target_actual_bar,
                "default_chart_type": "bar",
                "allowed_chart_types": {"bar", "doughnut"},
                "is_special_case": False,
                "special_case_source": False,
            },
            "generic_domain_daily_series": {
                "builder": self._build_generic_domain_daily_series,
                "default_chart_type": "line",
                "allowed_chart_types": {"line", "bar"},
                "is_special_case": False,
                "special_case_source": False,
            },
            "special_engine_punctuality": {
                "builder": self._build_special_engine_punctuality,
                "default_chart_type": "line",
                "allowed_chart_types": {"line"},
                "is_special_case": True,
                "special_case_source": "models/hr_kpi_engine.py",
            },
            "special_engine_attendance_overview": {
                "builder": self._build_special_engine_attendance_overview,
                "default_chart_type": "doughnut",
                "allowed_chart_types": {"doughnut"},
                "is_special_case": True,
                "special_case_source": "models/hr_kpi_engine.py",
            },
        }

    def _is_dashboard_line(self, line):
        source = line.data_source_id
        return bool(
            not line.is_section
            and line.kpi_type == "quantitative"
            and source
            and source.dashboard_enabled
            and source.dashboard_provider_key
            and source.dashboard_chart_type
        )

    def _build_chart_for_line(self, evaluation, line):
        source = line.data_source_id.sudo()
        registry = self._provider_registry()
        provider_key = source.dashboard_provider_key
        provider = registry.get(provider_key)
        if not provider:
            return False

        chart_type = source.dashboard_chart_type or provider["default_chart_type"]
        if chart_type not in provider["allowed_chart_types"]:
            _logger.warning(
                "Skipping dashboard chart for source '%s': chart type '%s' is not compatible with provider '%s'.",
                source.code,
                chart_type,
                provider_key,
            )
            return False

        payload = provider["builder"](evaluation, line, source, chart_type)
        if not payload:
            return False

        title = line.key_performance_area or source.name or _("KPI Chart")
        subtitle = source.name if source.name and source.name != title else ""

        return {
            "key": "chart_eval_line_%s" % line.id,
            "title": title,
            "subtitle": subtitle,
            "chart_type": chart_type,
            "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
            "chart_meta": payload.get("chart_meta") or {},
            "provider_key": provider_key,
            "is_special_case": provider["is_special_case"],
            "special_case_source": provider["special_case_source"] or False,
        }

    def _build_generic_target_actual_bar(self, evaluation, line, source, chart_type):
        target_val = float(line.target or 0.0)
        actual_val = float(line.actual or 0.0)
        target_center_text = False
        if chart_type == "doughnut":
            remaining_val = round(max(target_val - actual_val, 0.0), 2)
            labels = [_("Actual"), _("Remaining")]

            # unit_str = ""
            # if line.unit:
            #     unit_str = "%" if line.unit.code == "percent" else line.unit.name

            #  Tạo chuỗi format Target chuẩn chỉnh (Ví dụ: "90 %" hoặc "150 Hợp đồng")
            target_center_text = self._format_value_with_unit(line, line.target)

            datasets = [
                {
                    "label": line.key_performance_area or source.name or _("KPI"),
                    "data": [actual_val, remaining_val],
                    "backgroundColor": ["#3b82f6", "#e2e8f0"],
                    "borderWidth": 0,
                    "hoverOffset": 4,
                    "unit": line.unit.name,
                    "datalabels": {
                        "color": ["#ffffff", "#1f2937"], # Chữ trắng trên mảng xanh, chữ đen trên mảng xám
                        "font": {
                            "weight": "bold",
                            "size": 12
                        }
                    }
                }
            ]
        else:
            labels = [_("Target"), _("Actual")]
            datasets = [
                {
                    "label": line.key_performance_area or source.name or _("KPI"),
                    "data": [target_val, actual_val],
                }
            ]

        chart_data = {
            "labels": labels,
            "datasets": datasets,
            "target_center_text": target_center_text,
        }
        chart_meta = {
            "note": _("Target: %(target)s | Actual: %(actual)s")
            % {
                "target": self._format_value_with_unit(line, line.target),
                "actual": self._format_value_with_unit(line, line.actual),
            },
        }
        return {"chart_data": chart_data, "chart_meta": chart_meta}

    def _build_generic_domain_daily_series(self, evaluation, line, source, chart_type):
        if (
            source.source_type != "domain"
            or source.aggregation not in ("count", "sum", "avg")
            or not source.date_field_id
        ):
            _logger.info(
                "Skipping generic daily series for source '%s': requires domain, valid aggregation (count/sum/avg) and date_field.",
                source.code,
            )
            return False

        model_name = source.model_name
        Model = self.env.get(model_name)
        if Model is None:
            return False

        day_range = self._build_day_range(evaluation.start_date, evaluation.end_date)
        if not day_range:
            return False

        domain = source._build_domain(
            source.domain_numerator,
            evaluation.employee_id.sudo(),
            evaluation.start_date,
            evaluation.end_date,
        )
        records = Model.sudo().search(domain)
        date_field_name = source.date_field_id.name
        date_field_type = source.date_field_id.ttype
        tz = self._get_employee_tz(evaluation.employee_id)

        data_by_day = {day: [] for day in day_range}
        sum_field = source.sum_avg_field_id.name if source.sum_avg_field_id else None

        for record in records:
            value = record[date_field_name]
            bucket_day = self._coerce_record_day(value, date_field_type, tz)
            if bucket_day in data_by_day:
                if source.aggregation == "count":
                    data_by_day[bucket_day].append(1)
                elif sum_field and record[sum_field] not in (False, None):
                    data_by_day[bucket_day].append(float(record[sum_field]))

        # Đọc trực tiếp logic hiển thị từ field cấu hình trên Data Source
        is_maintenance = source.kpi_behavior == "maintenance"

        final_values = []
        running_total = 0.0

        for day in day_range:
            day_records = data_by_day[day]

            if not day_records:
                daily_val = 0.0
            elif source.aggregation in ("count", "sum"):
                daily_val = sum(day_records)
            elif source.aggregation == "avg":
                daily_val = sum(day_records) / len(day_records)

            if is_maintenance:
                final_values.append(daily_val)
            else:
                running_total += daily_val
                final_values.append(running_total)

        labels = [self._format_day_label(day) for day in day_range]

        dataset = {
            "label": line.key_performance_area or line.name or source.name or _("Value"),
            "data": final_values,
        }

        if chart_type == "line":
            dataset.update(
                {
                    "fill": True,
                    "tension": 0.35,
                    "pointRadius": 3,
                    "spanGaps": False,
                }
            )

        datasets = [dataset]

        # Thêm đường Target nét đứt (Nếu KPI line có thiết lập Target)
        if line.target:
            target_val = float(line.target)
            datasets.append(
                {
                    "type": "line",  # Ép kiểu Line (Giúp tạo Combo Chart nếu chart gốc là Bar)
                    "label": _("Target"),
                    "data": [target_val] * len(labels),
                    "borderColor": "red",
                    "borderDash": [5, 4],  # Tạo hiệu ứng nét đứt
                    "borderWidth": 2,
                    "pointRadius": 0,  # Ẩn chấm tròn để đường kẻ mượt hơn
                    "fill": False,
                    "tension": 0,  # Ép đường thẳng tắp, không uốn lượn
                }
            )

        note = _("Target: %s") % self._format_value_with_unit(line, line.target)
        return {
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": {
                "note": note,
            },
        }

    def _build_special_engine_punctuality(self, evaluation, line, source, chart_type):
        engine = self.env["hr.kpi.engine"]
        day_range = self._build_day_range(evaluation.start_date, evaluation.end_date)
        labels = [self._format_day_label(day) for day in day_range]
        per_day = engine.get_first_checkin_series(
            evaluation.employee_id,
            line,
            evaluation.start_date,
            evaluation.end_date,
        )
        expected_hour = engine.get_expected_start_hour(evaluation.employee_id)
        grace_minutes = engine._get_late_grace_minutes()

        chart_data = {
            "labels": labels,
            "datasets": [
                {
                    "label": _("Check-in"),
                    "data": per_day,
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 5,
                    "spanGaps": True,
                },
                {
                    "label": _("Start time"),
                    "data": [expected_hour] * len(labels),
                    "borderDash": [5, 4],
                    "borderWidth": 1.5,
                    "pointRadius": 0,
                    "fill": False,
                },
            ],
        }
        chart_meta = {
            "note": _("Start: %(start)s")
            % {
                "start": self._format_hour(expected_hour),
                "grace": grace_minutes,
            },
            "y_axis": {
                "format": "hour",
                "min": max(0, int(expected_hour) - 1),
                "max": math.ceil(expected_hour) + 1.5,
                "stepSize": 0.25,
            },
        }
        return {"chart_data": chart_data, "chart_meta": chart_meta}

    def _build_special_engine_attendance_overview(
        self, evaluation, line, source, chart_type
    ):
        engine = self.env["hr.kpi.engine"]
        metrics = engine.get_attendance_period_metrics(
            evaluation.employee_id,
            line,
            evaluation.start_date,
            evaluation.end_date,
        )
        worked = float(metrics.get("worked_days") or 0.0)
        expected = float(metrics.get("expected_work_days") or 0.0)
        absent = max(expected - worked, 0.0)

        chart_data = {
            "labels": [_("Days Present"), _("Days Absent")],
            "datasets": [
                {
                    "label": source.name or _("Attendance"),
                    "data": [worked, absent],
                    "backgroundColor": ["#3b82f6", "#e2e8f0"],
                    "borderWidth": 0,
                    "hoverOffset": 4,
                }
            ],
        }
        chart_meta = {
            "center_value": self._format_number(expected),
            "center_label": _("Total Days"),
            "legend_rows": [
                {
                    "label": _("Days Present"),
                    "value": self._format_number(worked),
                    "color": "#3b82f6",
                },
                {
                    "label": _("Days Absent"),
                    "value": self._format_number(absent),
                    "color": "#e2e8f0",
                },
            ],
            "note": _("Target: %s") % self._format_value_with_unit(line, line.target),
            "calendar": engine.get_attendance_worked_dates(
                evaluation.employee_id,
                evaluation.start_date,
                evaluation.end_date,
            ),
        }
        return {"chart_data": chart_data, "chart_meta": chart_meta}

    def _get_employee_tz(self, employee):
        tz_name = (
            employee.resource_calendar_id.tz or employee.tz or self.env.user.tz or "UTC"
        )
        return pytz.timezone(tz_name)

    def _build_day_range(self, start_date, end_date):
        d_from = fields.Date.to_date(start_date)
        d_to = fields.Date.to_date(end_date)
        if not d_from or not d_to or d_from > d_to:
            return []

        day_range = []
        current = d_from
        while current <= d_to:
            day_range.append(current)
            current += datetime.timedelta(days=1)
        return day_range

    def _coerce_record_day(self, value, field_type, tz):
        if not value:
            return False
        if field_type == "date":
            return fields.Date.to_date(value)
        if field_type == "datetime":
            dt_value = fields.Datetime.to_datetime(value)
            if not dt_value:
                return False
            if dt_value.tzinfo is None:
                dt_value = pytz.UTC.localize(dt_value)
            return dt_value.astimezone(tz).date()
        return False

    def _format_day_label(self, day):
        return day.strftime("%d/%m")

    def _format_hour(self, value):
        if value is None:
            return "--"
        hours = int(value)
        minutes = int(round((float(value) - hours) * 60.0))
        return "%s:%s" % (hours, str(minutes).zfill(2))

    def _format_number(self, value):
        return ("%0.2f" % float(value or 0.0)).rstrip("0").rstrip(".")

    def _format_value_with_unit(self, line, value):
        value_text = self._format_number(value)
        if line.unit and line.unit.code == "percent":
            return "%s%%" % value_text
        unit_name = line.unit.name if line.unit else ""
        return "%s %s" % (value_text, unit_name) if unit_name else value_text
