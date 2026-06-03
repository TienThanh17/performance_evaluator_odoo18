import datetime
import logging
import math

import pytz

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class HrKpiDashboardChartService(models.AbstractModel):
    _name = "hr.kpi.dashboard.chart.service"
    _description = "KPI Dashboard Chart Service"

    @api.model
    def build_dynamic_charts(self, evaluation, dashboard_kind="individual"):
        evaluation = evaluation.sudo()
        if not evaluation:
            return []

        charts = []
        widgets = self.env["hr.kpi.dashboard.widget"].get_dashboard_widget_records(
            dashboard_kind
        )
        for widget in widgets:
            chart = False
            if widget.widget_class == "micro" and widget.data_source_id:
                if dashboard_kind == "department":
                    chart = self._build_department_micro_chart(evaluation, widget)
                else:
                    chart = self._build_individual_micro_chart(evaluation, widget)
            elif widget.widget_class == "macro":
                chart = self._build_macro_chart(evaluation, widget)
            if not chart:
                continue
            chart.setdefault(
                "key",
                "chart_widget_%s_%s"
                % (widget.id, widget.macro_widget_type or widget.widget_class),
            )
            chart.setdefault("widget_id", widget.id)
            chart.setdefault("sequence", widget.sequence or 0)
            chart.setdefault("widget_class", widget.widget_class)
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

    # ---------------------------------------------------------
    # MICRO WIDGETS
    # ---------------------------------------------------------
    def _build_individual_micro_chart(self, evaluation, widget):
        matched_line = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                not line.is_section
                and line.kpi_type == "quantitative"
                and line.data_source_id.id == widget.data_source_id.id
            )
        )
        if not matched_line:
            return False

        line = matched_line[0].sudo()
        source = widget.data_source_id.sudo()
        provider_key = widget.provider_key
        provider = self._provider_registry().get(provider_key)
        if not provider:
            return False

        chart_type = widget.micro_chart_type or provider["default_chart_type"]
        if chart_type not in provider["allowed_chart_types"]:
            _logger.warning(
                "Skipping widget '%s': chart type '%s' is not compatible with provider '%s'.",
                widget.display_name,
                chart_type,
                provider_key,
            )
            return False

        payload = provider["builder"](
            evaluation=evaluation,
            line=line,
            source=source,
            widget=widget,
            chart_type=chart_type,
            dashboard_kind="individual",
        )
        if not payload:
            return False

        title = self._line_title(line, source)
        subtitle = source.name if source.name and source.name != title else ""
        return {
            "key": "chart_widget_%s_line_%s" % (widget.id, line.id),
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": title,
            "subtitle": subtitle,
            "chart_type": chart_type,
            "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
            "chart_meta": payload.get("chart_meta") or {},
            "provider_key": widget.provider_key or "",
            "widget_class": widget.widget_class,
            "is_special_case": provider["is_special_case"],
            "special_case_source": provider["special_case_source"] or False,
        }

    def _build_department_micro_chart(self, evaluation, widget):
        if evaluation._name != "hr.department.performance.evaluation":
            return False
        if widget.department_micro_mode == "employee_compare":
            return self._build_department_employee_compare_chart(evaluation, widget)
        if widget.department_micro_mode == "department_progress":
            return self._build_department_progress_chart(evaluation, widget)
        return False

    def _build_department_employee_compare_chart(self, evaluation, widget):
        if not evaluation.department_id or not evaluation.period_id or not widget.data_source_id:
            return False

        line_model = self.env["hr.performance.evaluation.line"].sudo()
        lines = line_model.search(
            [
                ("is_section", "=", False),
                ("kpi_type", "=", "quantitative"),
                ("data_source_id", "=", widget.data_source_id.id),
                ("evaluation_id.department_id", "=", evaluation.department_id.id),
                ("evaluation_id.period_id", "=", evaluation.period_id.id),
                ("evaluation_id.state", "!=", "cancel"),
            ],
            order="evaluation_id desc, id desc",
        )
        if not lines:
            return False

        latest_line_by_employee = {}
        for line in lines:
            employee = line.evaluation_id.employee_id
            if not employee or employee.id in latest_line_by_employee:
                continue
            latest_line_by_employee[employee.id] = line

        compare_lines = sorted(
            latest_line_by_employee.values(),
            key=lambda line: (
                line.evaluation_id.employee_id.name or "",
                line.evaluation_id.id or 0,
                line.id or 0,
            ),
        )
        if not compare_lines:
            return False

        chart_type = widget.micro_chart_type or "bar"
        if chart_type == "doughnut":
            chart_type = "bar"

        labels = [line.evaluation_id.employee_id.name or _("Employee") for line in compare_lines]
        actual_values = [round(float(line.actual or 0.0), 2) for line in compare_lines]
        target_values = [round(float(line.target or 0.0), 2) for line in compare_lines]
        source = widget.data_source_id.sudo()

        datasets = [
            {
                "label": _("Target"),
                "data": target_values,
            },
            {
                "label": _("Actual"),
                "data": actual_values,
            },
        ]
        if chart_type == "line":
            for dataset in datasets:
                dataset.update(
                    {
                        "fill": False,
                        "tension": 0.3,
                        "pointRadius": 4,
                    }
                )

        return {
            "key": "chart_widget_%s_compare_%s" % (widget.id, widget.data_source_id.id),
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or source.name or _("Employee Comparison"),
            "subtitle": _("Across employees in the selected department and period"),
            "chart_type": chart_type,
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": {
                "note": _("Comparing Actual and Target values across employees."),
            },
            "provider_key": widget.provider_key or "",
            "widget_class": widget.widget_class,
            "is_special_case": False,
            "special_case_source": False,
        }

    def _build_department_progress_chart(self, evaluation, widget):
        matched_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                not line.is_section
                and line.kpi_type == "quantitative"
                and line.data_source_id.id == widget.data_source_id.id
            )
        )
        if not matched_lines:
            return False

        source = widget.data_source_id.sudo()
        chart_type = widget.micro_chart_type or "bar"
        if len(matched_lines) > 1 and chart_type == "doughnut":
            chart_type = "bar"

        if len(matched_lines) == 1:
            line = matched_lines[0].sudo()
            payload = self._build_target_actual_payload_for_line(
                line,
                source,
                chart_type,
            )
            if not payload:
                return False
            title = line.name or source.name or widget.name or _("Department KPI")
            subtitle = source.name if source.name and source.name != title else ""
            return {
                "key": "chart_widget_%s_dept_line_%s" % (widget.id, line.id),
                "widget_id": widget.id,
                "sequence": widget.sequence or 0,
                "title": title,
                "subtitle": subtitle,
                "chart_type": chart_type,
                "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
                "chart_meta": payload.get("chart_meta") or {},
                "provider_key": widget.provider_key or "",
                "widget_class": widget.widget_class,
                "is_special_case": False,
                "special_case_source": False,
            }

        payload = self._build_target_actual_payload_for_lines(
            matched_lines.sudo(),
            chart_type,
            label_getter=lambda line: line.name or source.name or _("Department KPI"),
        )
        if not payload:
            return False
        return {
            "key": "chart_widget_%s_dept_progress_%s"
            % (widget.id, widget.data_source_id.id),
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or source.name or _("Department KPI Progress"),
            "subtitle": _("Current department KPI lines"),
            "chart_type": chart_type,
            "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
            "chart_meta": payload.get("chart_meta") or {},
            "provider_key": widget.provider_key or "",
            "widget_class": widget.widget_class,
            "is_special_case": False,
            "special_case_source": False,
        }

    # ---------------------------------------------------------
    # MACRO WIDGETS
    # ---------------------------------------------------------
    def _build_macro_chart(self, evaluation, widget):
        if widget.macro_widget_type == "radar_chart":
            if widget.dashboard_kind != "individual":
                return False
            return self._build_macro_radar(evaluation, widget)
        if widget.macro_widget_type == "trend_line":
            return self._build_macro_trend(evaluation, widget)
        if widget.macro_widget_type == "distribution":
            return self._build_macro_distribution(evaluation, widget)
        return False

    def _build_macro_radar(self, evaluation, widget):
        qualitative_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: not line.is_section and not line.data_source_id
        )
        if not qualitative_lines:
            return False

        labels = [
            line.key_performance_area or line.name or _("KPI")
            for line in qualitative_lines
        ]
        scores = [
            round(float(getattr(line, "final_rating", 0.0) or 0.0), 2)
            for line in qualitative_lines
        ]
        return {
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Qualitative KPI Radar"),
            "chart_type": "radar",
            "chart_data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": _("Điểm đánh giá"),
                        "data": scores,
                        "backgroundColor": "rgba(59, 130, 246, 0.2)",
                        "borderColor": "#3b82f6",
                        "pointBackgroundColor": "#3b82f6",
                    }
                ],
            },
            "chart_meta": {},
        }

    def _build_macro_trend(self, evaluation, widget):
        measure_name = widget.measure_field_id.name
        group_by_name = widget.group_by_field_id.name
        group_by_expr = self._build_groupby_expr(widget)
        model_name = self._resolve_target_model_name(widget)
        if not model_name or not measure_name or not group_by_name:
            return False

        domain = self._build_macro_trend_domain(evaluation, widget)
        extra_domain = self._parse_filter_domain(widget.filter_domain)
        if extra_domain:
            domain.extend(extra_domain)

        history_data = self.env[model_name].sudo().read_group(
            domain=domain,
            fields=[f"{measure_name}:avg"],
            groupby=[group_by_expr],
            limit=6,
            orderby=f"{group_by_expr} desc",
        )
        if not history_data:
            return False

        history_data.reverse()
        labels = []
        values = []
        for item in history_data:
            group_value = self._extract_group_value(item, group_by_expr, group_by_name)
            labels.append(
                self._normalize_group_label(group_value, widget.group_by_ttype)
            )
            values.append(
                round(float(self._extract_aggregate_value(item, measure_name) or 0.0), 2)
            )

        if widget.dashboard_kind == "individual":
            line_color = "#3b82f6"
        else:
            line_color = "#10b981"

        return {
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Trend"),
            "chart_type": "line",
            "chart_data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": widget.name or _("Trend"),
                        "data": values,
                        "borderColor": line_color,
                        "backgroundColor": f"{line_color}33",
                        "pointBackgroundColor": line_color,
                        "tension": 0.3,
                        "fill": True,
                    }
                ],
            },
            "chart_meta": {},
        }

    def _build_macro_distribution(self, evaluation, widget):
        measure_name = widget.measure_field_id.name
        group_by_name = widget.group_by_field_id.name
        group_by_expr = self._build_groupby_expr(widget)
        model_name = self._resolve_target_model_name(widget)
        if not model_name or not measure_name or not group_by_name:
            return False

        domain = self._build_macro_distribution_domain(evaluation, widget)
        extra_domain = self._parse_filter_domain(widget.filter_domain)
        if extra_domain:
            domain.extend(extra_domain)

        distribution_data = self.env[model_name].sudo().read_group(
            domain=domain,
            fields=[f"{measure_name}:avg"],
            groupby=[group_by_expr],
        )
        if not distribution_data:
            return False

        distribution_data.sort(
            key=lambda item: self._extract_aggregate_value(item, measure_name) or 0.0,
            reverse=True,
        )

        labels = []
        scores = []
        colors = []
        for item in distribution_data:
            group_value = self._extract_group_value(item, group_by_expr, group_by_name)
            labels.append(
                self._normalize_group_label(group_value, widget.group_by_ttype)
            )
            scores.append(
                round(float(self._extract_aggregate_value(item, measure_name) or 0.0), 2)
            )
            if (
                widget.dashboard_kind == "individual"
                and group_by_name == "employee_id"
                and self._group_matches_current_employee(group_value, evaluation)
            ):
                colors.append("#f59e0b")
            elif widget.dashboard_kind == "individual":
                colors.append("#e5e7eb")
            else:
                colors.append("#3b82f6")

        return {
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Distribution"),
            "chart_type": "bar",
            "chart_data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": widget.name or _("Distribution"),
                        "data": scores,
                        "backgroundColor": colors,
                    }
                ],
            },
            "chart_meta": {},
        }

    def _resolve_target_model_name(self, widget):
        return (
            "hr.performance.evaluation"
            if widget.target_model == "evaluation"
            else "hr.performance.evaluation.line"
        )

    def _build_groupby_expr(self, widget):
        group_by_name = widget.group_by_field_id.name
        if widget.group_by_ttype in ("date", "datetime"):
            granularity = widget.date_granularity or "month"
            return f"{group_by_name}:{granularity}"
        return group_by_name

    def _build_macro_trend_domain(self, evaluation, widget):
        if widget.target_model == "evaluation":
            domain = [("state", "!=", "cancel")]
            if widget.dashboard_kind == "individual":
                domain.append(("employee_id", "=", evaluation.employee_id.id))
            else:
                domain.append(("department_id", "=", evaluation.department_id.id))
            return domain

        domain = [("evaluation_id.state", "!=", "cancel")]
        if widget.dashboard_kind == "individual":
            domain.append(("evaluation_id.employee_id", "=", evaluation.employee_id.id))
        else:
            domain.append(("evaluation_id.department_id", "=", evaluation.department_id.id))
        return domain

    def _build_macro_distribution_domain(self, evaluation, widget):
        if widget.target_model == "evaluation":
            return [
                ("department_id", "=", evaluation.department_id.id),
                ("period_id", "=", evaluation.period_id.id),
                ("state", "!=", "cancel"),
            ]

        return [
            ("evaluation_id.department_id", "=", evaluation.department_id.id),
            ("evaluation_id.period_id", "=", evaluation.period_id.id),
            ("evaluation_id.state", "!=", "cancel"),
        ]

    def _parse_filter_domain(self, filter_domain):
        if not filter_domain:
            return []
        try:
            parsed = safe_eval(filter_domain)
        except Exception as exc:
            _logger.warning("Invalid dashboard widget filter domain '%s': %s", filter_domain, exc)
            return []
        return parsed if isinstance(parsed, list) else []

    def _extract_group_value(self, item, group_by_expr, group_by_name):
        return item.get(group_by_expr, item.get(group_by_name))

    def _extract_aggregate_value(self, item, measure_name):
        return item.get(measure_name, item.get(f"{measure_name}_avg"))

    def _normalize_group_label(self, group_value, group_type):
        if isinstance(group_value, tuple):
            return group_value[1]
        if isinstance(group_value, datetime.date):
            return fields.Date.to_string(group_value)
        if isinstance(group_value, datetime.datetime):
            return fields.Datetime.to_string(group_value)
        if group_type in ("date", "datetime") and group_value:
            return str(group_value)
        return str(group_value or _("Undefined"))

    def _group_matches_current_employee(self, group_value, evaluation):
        if not evaluation.employee_id:
            return False
        if isinstance(group_value, tuple):
            return group_value[0] == evaluation.employee_id.id
        return group_value == evaluation.employee_id.id

    # ---------------------------------------------------------
    # GENERIC TARGET/ACTUAL PAYLOAD HELPERS
    # ---------------------------------------------------------
    def _build_target_actual_payload_for_line(self, line, source, chart_type):
        target_val = float(line.target or 0.0)
        actual_val = float(line.actual or 0.0)
        target_center_text = False
        chart_meta = {
            "note": _("Target: %(target)s | Actual: %(actual)s")
            % {
                "target": self._format_value_with_unit(line, line.target),
                "actual": self._format_value_with_unit(line, line.actual),
            },
        }

        if chart_type == "doughnut":
            remaining_val = round(max(target_val - actual_val, 0.0), 2)
            chart_meta.update(
                {
                    "center_value": self._format_number(target_val),
                    "center_label": line.unit.name if line.unit else _("Target"),
                }
            )
            target_center_text = self._format_value_with_unit(line, line.target)
            chart_data = {
                "labels": [_("Actual"), _("Remaining")],
                "datasets": [
                    {
                        "label": self._line_title(line, source),
                        "data": [actual_val, remaining_val],
                        "backgroundColor": ["#3b82f6", "#e2e8f0"],
                        "borderWidth": 0,
                        "hoverOffset": 4,
                    }
                ],
                "target_center_text": target_center_text,
            }
            return {"chart_data": chart_data, "chart_meta": chart_meta}

        datasets = [
            {
                "label": self._line_title(line, source),
                "data": [target_val, actual_val],
            }
        ]
        if chart_type == "line":
            datasets[0].update(
                {
                    "fill": False,
                    "tension": 0.3,
                    "pointRadius": 4,
                }
            )
        return {
            "chart_data": {
                "labels": [_("Target"), _("Actual")],
                "datasets": datasets,
            },
            "chart_meta": chart_meta,
        }

    def _build_target_actual_payload_for_lines(self, lines, chart_type, label_getter):
        if not lines:
            return False
        labels = [label_getter(line) for line in lines]
        target_values = [round(float(line.target or 0.0), 2) for line in lines]
        actual_values = [round(float(line.actual or 0.0), 2) for line in lines]
        datasets = [
            {
                "label": _("Target"),
                "data": target_values,
            },
            {
                "label": _("Actual"),
                "data": actual_values,
            },
        ]
        if chart_type == "line":
            for dataset in datasets:
                dataset.update(
                    {
                        "fill": False,
                        "tension": 0.3,
                        "pointRadius": 4,
                    }
                )
        return {
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": {
                "note": _("Comparing Target and Actual values."),
            },
        }

    # ---------------------------------------------------------
    # INDIVIDUAL MICRO PROVIDERS
    # ---------------------------------------------------------
    def _line_title(self, line, source):
        return (
            getattr(line, "key_performance_area", False)
            or getattr(line, "name", False)
            or source.name
            or _("KPI Chart")
        )

    def _build_generic_target_actual_bar(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
    ):
        return self._build_target_actual_payload_for_line(line, source, chart_type)

    def _build_generic_domain_daily_series(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
    ):
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

        model = self.env.get(source.model_name)
        if model is None:
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
        records = model.sudo().search(domain)
        date_field_name = source.date_field_id.name
        date_field_type = source.date_field_id.ttype
        tz = self._get_employee_tz(evaluation.employee_id)

        data_by_day = {day: [] for day in day_range}
        sum_field = source.sum_avg_field_id.name if source.sum_avg_field_id else None

        for record in records:
            value = record[date_field_name]
            bucket_day = self._coerce_record_day(value, date_field_type, tz)
            if bucket_day not in data_by_day:
                continue
            if source.aggregation == "count":
                data_by_day[bucket_day].append(1)
            elif sum_field and record[sum_field] not in (False, None):
                data_by_day[bucket_day].append(float(record[sum_field]))

        is_maintenance = widget.kpi_behavior == "maintenance"
        final_values = []
        running_total = 0.0
        for day in day_range:
            day_records = data_by_day[day]
            if not day_records:
                daily_val = 0.0
            elif source.aggregation in ("count", "sum"):
                daily_val = sum(day_records)
            else:
                daily_val = sum(day_records) / len(day_records)

            if is_maintenance:
                final_values.append(round(daily_val, 2))
            else:
                running_total += daily_val
                final_values.append(round(running_total, 2))

        labels = [self._format_day_label(day) for day in day_range]
        dataset = {
            "label": self._line_title(line, source),
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
        if line.target:
            target_val = float(line.target)
            datasets.append(
                {
                    "type": "line",
                    "label": _("Target"),
                    "data": [target_val] * len(labels),
                    "borderColor": "#ef4444",
                    "borderDash": [5, 4],
                    "borderWidth": 2,
                    "pointRadius": 0,
                    "fill": False,
                    "tension": 0,
                }
            )

        return {
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": {
                "note": _("Target: %s")
                % self._format_value_with_unit(line, line.target),
            },
        }

    def _build_special_engine_punctuality(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
    ):
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

        return {
            "chart_data": {
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
            },
            "chart_meta": {
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
            },
        }

    def _build_special_engine_attendance_overview(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
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
        return {
            "chart_data": {
                "labels": [_("Days Present"), _("Days Absent")],
                "datasets": [
                    {
                        "label": source.name or _("Attendance"),
                        "data": [round(worked, 2), round(absent, 2)],
                        "backgroundColor": ["#3b82f6", "#e2e8f0"],
                        "borderWidth": 0,
                        "hoverOffset": 4,
                    }
                ],
                "target_center_text": self._format_number(expected),
            },
            "chart_meta": {
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
            },
        }

    # ---------------------------------------------------------
    # GENERIC HELPERS
    # ---------------------------------------------------------
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

    def _get_employee_tz(self, employee):
        if not employee:
            return pytz.UTC
        tz_name = (
            employee.resource_calendar_id.tz or employee.tz or self.env.user.tz or "UTC"
        )
        return pytz.timezone(tz_name)

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
