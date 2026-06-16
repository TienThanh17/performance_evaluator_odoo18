import datetime
import logging
import math

import pytz

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

TARGET_100_MEASURE_FIELDS = {
    "total_p2_1",
    "total_p2_2",
    "total_p3_individual",
}

CHART_COLOR_PALETTE = [
    "#2279BA",
    "#10b981",
    "#f59e0b",
    "#8b5cf6",
    "#ef4444",
    "#06b6d4",
    "#84cc16",
    "#f97316",
]


class HrKpiDashboardChartService(models.AbstractModel):
    _name = "hr.kpi.dashboard.chart.service"
    _description = "KPI Dashboard Chart Service"

    # Xác định phòng ban hiện tại của record dashboard để lọc widget đúng scope.
    def _resolve_widget_department(self, evaluation):
        if not evaluation or "department_id" not in evaluation._fields:
            return False
        return evaluation.department_id

    @api.model
    # Dựng toàn bộ chart cho dashboard hiện tại và để từng widget tự quyết định có render được hay không.
    def build_dynamic_charts(self, evaluation, dashboard_kind="individual"):
        evaluation = evaluation.sudo()
        if not evaluation:
            return []

        charts = []
        current_department = self._resolve_widget_department(evaluation)
        widgets = self.env["hr.kpi.dashboard.widget"].get_dashboard_widget_records(
            dashboard_kind,
            department=current_department,
        )
        for widget in widgets:
            chart = False
            if widget.widget_class == "micro":
                if dashboard_kind == "department":
                    chart = self._build_department_micro_chart(evaluation, widget)
                else:
                    chart = self._build_individual_micro_chart(evaluation, widget)
            elif widget.widget_class == "macro":
                chart = self._build_macro_chart(evaluation, widget)
            if not chart:
                continue

            # Chuẩn hóa palette ở bước cuối để mọi line/bar/stacked bar đều có màu dễ phân biệt.
            chart["chart_data"] = self._apply_visual_palette_to_chart_data(
                chart.get("chart_data"), chart.get("chart_type")
            )
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

    # Pha thêm alpha vào mã màu hex để tái sử dụng cùng palette cho fill và border.
    def _with_alpha(self, color_hex, alpha_hex):
        base_color = (color_hex or "").strip()
        if not base_color.startswith("#") or len(base_color) != 7:
            return color_hex
        return f"{base_color}{alpha_hex}"

    # Trả palette quay vòng theo số lượng phần tử để chart nhiều value nhìn tách bạch hơn.
    def _get_rotated_palette(self, size, offset=0):
        if size <= 0:
            return []
        palette_size = len(CHART_COLOR_PALETTE)
        return [
            CHART_COLOR_PALETTE[(offset + index) % palette_size]
            for index in range(size)
        ]

    # Tô màu điểm/cột theo từng value khi chart có từ 2 giá trị trở lên.
    def _apply_visual_palette_to_chart_data(self, chart_data, chart_type):
        if chart_type not in {"line", "bar", "stacked_bar"}:
            return chart_data
        if not chart_data:
            return chart_data

        labels = list((chart_data or {}).get("labels") or [])
        datasets = list((chart_data or {}).get("datasets") or [])
        if len(labels) < 2 or not datasets:
            return chart_data

        styled_datasets = []
        for dataset_index, dataset in enumerate(datasets):
            styled_dataset = dict(dataset or {})
            data_values = list(styled_dataset.get("data") or [])
            if len(data_values) < 2:
                styled_datasets.append(styled_dataset)
                continue

            # Giữ nguyên các target/reference line nét đứt để không phá semantics cảnh báo.
            if chart_type == "line" and styled_dataset.get("borderDash"):
                styled_datasets.append(styled_dataset)
                continue

            # Gap to Target của stacked bar phải luôn giữ màu xám để semantics thiếu hụt không bị đổi nghĩa.
            if chart_type == "stacked_bar" and styled_dataset.get("label") == _("Gap to Target"):
                gap_gray = "#94a3b8"
                styled_dataset["backgroundColor"] = [
                    self._with_alpha(gap_gray, "8C")
                ] * len(data_values)
                styled_dataset["borderColor"] = [gap_gray] * len(data_values)
                styled_datasets.append(styled_dataset)
                continue

            palette = self._get_rotated_palette(len(data_values), offset=dataset_index * 2)
            if chart_type == "line":
                # Line chart vẫn giữ màu line chính, nhưng point color đa dạng để từng value nổi bật hơn.
                styled_dataset["pointBackgroundColor"] = palette
                styled_dataset["pointBorderColor"] = palette
            else:
                # Bar/stacked bar dùng palette theo từng cột để mắt người đọc phân biệt nhanh từng value.
                styled_dataset["backgroundColor"] = [
                    self._with_alpha(color, "CC") for color in palette
                ]
                styled_dataset["borderColor"] = palette
            styled_datasets.append(styled_dataset)

        styled_chart_data = dict(chart_data)
        styled_chart_data["datasets"] = styled_datasets
        return styled_chart_data

    def _provider_registry(self):
        return {
            "generic_target_actual_bar": {
                "builder": self._build_generic_target_actual_bar,
                "default_chart_type": "bar",
                "allowed_chart_types": {"line", "bar", "doughnut", "stacked_bar"},
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

    # Resolve employee KPI line từ selector template line của micro widget trên dashboard cá nhân.
    def _resolve_individual_micro_line(self, evaluation, widget):
        template_line = widget.employee_template_line_id
        if not evaluation or not template_line:
            return False

        # Match theo backlink kpi_line_id để luôn đọc đúng snapshot line của phiếu đánh giá hiện tại.
        matched_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                not line.is_section and line.kpi_line_id.id == template_line.id
            )
        ).sorted(key=lambda line: (line.sequence or 0, line.id or 0))
        return matched_lines[:1].sudo() if matched_lines else False

    # Gom line KPI của nhiều nhân viên trong cùng phòng/kỳ theo employee template line được chọn.
    def _resolve_department_employee_compare_lines(self, evaluation, widget):
        template_line = widget.employee_template_line_id
        if not evaluation.department_id or not evaluation.period_id or not template_line:
            return []

        # Search theo kpi_line_id để bỏ hoàn toàn phụ thuộc vào widget.data_source_id.
        line_model = self.env["hr.performance.evaluation.line"].sudo()
        lines = line_model.search(
            [
                ("is_section", "=", False),
                ("kpi_line_id", "=", template_line.id),
                ("evaluation_id.department_id", "=", evaluation.department_id.id),
                ("evaluation_id.period_id", "=", evaluation.period_id.id),
                ("evaluation_id.state", "!=", "cancel"),
            ],
            order="evaluation_id desc, id desc",
        )
        if not lines:
            return []

        # Mỗi nhân viên chỉ lấy snapshot line mới nhất trong cùng kỳ/phòng ban.
        latest_line_by_employee = {}
        for line in lines:
            employee = line.evaluation_id.employee_id
            if not employee or employee.id in latest_line_by_employee:
                continue
            latest_line_by_employee[employee.id] = line

        return sorted(
            latest_line_by_employee.values(),
            key=lambda line: (
                line.evaluation_id.employee_id.name or "",
                line.evaluation_id.id or 0,
                line.id or 0,
            ),
        )

    # Resolve nhiều department evaluation line theo selector template line trên widget.
    def _resolve_department_progress_lines(self, evaluation, widget):
        selected_template_lines = widget.department_template_line_ids.sorted(
            key=lambda line: (line.sequence or 0, line.id or 0)
        )
        if not evaluation or not selected_template_lines:
            return self.env["hr.department.evaluation.line"]

        # Giữ đúng thứ tự line theo sequence của template line đã chọn thay vì phụ thuộc data source.
        template_order = {
            template_line.id: index
            for index, template_line in enumerate(selected_template_lines)
        }
        matched_lines = evaluation.evaluation_line_ids.filtered(
            lambda line: (
                not line.is_section
                and line.department_kpi_line_id.id in template_order
            )
        ).sorted(
            key=lambda line: (
                template_order.get(line.department_kpi_line_id.id, 999999),
                line.sequence or 0,
                line.id or 0,
            )
        )
        return matched_lines.sudo()

    # Trả data source snapshot gắn trên evaluation line nếu line đó có source; nếu không thì chart vẫn được phép chạy.
    def _get_chart_line_source(self, line):
        if not line or not getattr(line, "data_source_id", False):
            return False
        return line.data_source_id.sudo()

    # ---------------------------------------------------------
    # MICRO WIDGETS
    # ---------------------------------------------------------
    # Dựng micro chart cá nhân từ employee template line đã chọn thay vì match bằng widget data source.
    def _build_individual_micro_chart(self, evaluation, widget):
        matched_line = self._resolve_individual_micro_line(evaluation, widget)
        if not matched_line:
            return False

        line = matched_line[0].sudo()
        source = self._get_chart_line_source(line)
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
        subtitle = source.name if source and source.name and source.name != title else ""
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

    # Dựng chart so sánh nhiều nhân viên theo employee template line đã chọn trên widget phòng ban.
    def _build_department_employee_compare_chart(self, evaluation, widget):
        compare_lines = self._resolve_department_employee_compare_lines(
            evaluation, widget
        )
        if not compare_lines:
            return False

        chart_type = widget.micro_chart_type or "stacked_bar"
        if chart_type not in {"line", "stacked_bar"}:
            _logger.warning(
                "Skipping department employee compare widget '%s': chart type '%s' is not supported for mode '%s'.",
                widget.display_name,
                chart_type,
                widget.department_micro_mode,
            )
            return False

        # Snapshot labels và giá trị được lấy theo line mới nhất của từng nhân viên trong cùng kỳ/phòng ban.
        labels = [
            line.evaluation_id.employee_id.name or _("Employee")
            for line in compare_lines
        ]
        actual_values = [round(float(line.actual or 0.0), 2) for line in compare_lines]
        target_values = [round(float(line.target or 0.0), 2) for line in compare_lines]
        selected_title = (
            widget.employee_template_line_id.key_performance_area
            or widget.employee_template_line_id.display_name
            or _("Employee Comparison")
        )

        # Line giữ semantics Target/Actual hiện tại; stacked bar dùng Actual + Gap to Target.
        if chart_type == "stacked_bar":
            payload = self._build_department_employee_compare_stacked_payload(
                labels,
                actual_values,
                target_values,
            )
        else:
            # Line chart dùng target chuẩn từ template line để render một đường tham chiếu ngang cho cả nhóm nhân viên.
            reference_target = round(
                float(widget.employee_template_line_id.target or 0.0), 2
            )
            datasets = [
                {
                    "label": _("Target"),
                    "data": [reference_target] * len(labels),
                    "borderColor": "#ef4444",
                    "backgroundColor": "rgba(0,0,0,0)",
                    "borderDash": [5, 4],
                    "borderWidth": 2,
                    "pointRadius": 0,
                    "pointHoverRadius": 0,
                    "fill": False,
                    "tension": 0,
                },
                {
                    "label": _("Actual"),
                    "data": actual_values,
                    "borderColor": "#2279BA",
                    "pointBackgroundColor": "#2279BA",
                    "pointBorderColor": "#2279BA",
                    "fill": False,
                    "tension": 0.3,
                    "pointRadius": 4,
                },
            ]
            payload = {
                "chart_data": {
                    "labels": labels,
                    "datasets": datasets,
                },
                "chart_meta": {
                    # "note": _("Comparing employee target and actual values."),
                },
            }

        return {
            "key": "chart_widget_%s_compare_template_%s"
            % (widget.id, widget.employee_template_line_id.id),
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or selected_title or _("Employee Comparison"),
            "subtitle": (
                selected_title
                if widget.name and selected_title and selected_title != widget.name
                else ""
            ),
            "chart_type": chart_type,
            "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
            "chart_meta": payload.get("chart_meta") or {},
            "provider_key": "",
            "widget_class": widget.widget_class,
            "department_micro_mode": widget.department_micro_mode or "",
            "is_special_case": False,
            "special_case_source": False,
        }

    # Dựng stacked bar payload cho employee compare với semantics Actual + Gap to Target.
    def _build_department_employee_compare_stacked_payload(
        self, labels, actual_values, target_values
    ):
        # Phần gap chỉ hiển thị phần còn thiếu tới target; nếu actual vượt target thì gap về 0.
        gap_to_target_values = [
            round(max(target - actual, 0.0), 2)
            for target, actual in zip(target_values, actual_values)
        ]

        return {
            "chart_data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": _("Actual"),
                        "data": actual_values,
                        "stack": "employee_target_progress",
                        "backgroundColor": "rgba(3, 103, 176, 0.88)",
                        "borderColor": "#0367b0",
                    },
                    {
                        "label": _("Gap to Target"),
                        "data": gap_to_target_values,
                        "stack": "employee_target_progress",
                        "backgroundColor": "rgba(148, 163, 184, 0.55)",
                        "borderColor": "#94a3b8",
                    },
                ],
            },
            "chart_meta": {
                # "note": _("Actual values are stacked with the remaining gap to target."),
                "target_values": target_values,
                "actual_values": actual_values,
                "gap_to_target_values": gap_to_target_values,
            },
        }

    # Dựng chart tiến độ phòng ban từ danh sách department template line được chọn trên widget.
    def _build_department_progress_chart(self, evaluation, widget):
        matched_lines = self._resolve_department_progress_lines(evaluation, widget)
        if not matched_lines:
            return False

        chart_type = widget.micro_chart_type or "bar"
        if chart_type not in {"bar", "line", "doughnut"}:
            _logger.warning(
                "Skipping department progress widget '%s': chart type '%s' is not supported for mode '%s'.",
                widget.display_name,
                chart_type,
                widget.department_micro_mode,
            )
            return False
        if chart_type == "doughnut" and len(matched_lines) != 1:
            _logger.warning(
                "Skipping department progress widget '%s': doughnut chart requires exactly one matched line, got %s.",
                widget.display_name,
                len(matched_lines),
            )
            return False

        if len(matched_lines) == 1:
            line = matched_lines[0].sudo()
            payload = self._build_single_line_target_actual_payload(
                line,
                False,
                chart_type,
            )
            if not payload:
                return False
            selected_title = (
                line.name
                or (
                    line.department_kpi_line_id.name
                    if line.department_kpi_line_id
                    else False
                )
                or _("Department KPI")
            )
            title = widget.name or selected_title
            subtitle = (
                selected_title
                if widget.name and selected_title and selected_title != widget.name
                else ""
            )
            return {
                "key": "chart_widget_%s_dept_line_%s" % (widget.id, line.id),
                "widget_id": widget.id,
                "sequence": widget.sequence or 0,
                "title": title,
                "subtitle": subtitle,
                "chart_type": chart_type,
                "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
                "chart_meta": payload.get("chart_meta") or {},
                "provider_key": "",
                "widget_class": widget.widget_class,
                "department_micro_mode": widget.department_micro_mode or "",
                "is_special_case": False,
                "special_case_source": False,
            }

        payload = self._build_multi_line_target_actual_payload(
            matched_lines.sudo(),
            chart_type,
            label_getter=lambda line: (
                line.name
                or (
                    line.department_kpi_line_id.name
                    if line.department_kpi_line_id
                    else False
                )
                or _("Department KPI")
            ),
        )
        if not payload:
            return False
        return {
            "key": "chart_widget_%s_dept_progress" % widget.id,
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Department KPI Progress"),
            "subtitle": _("Selected department KPI lines"),
            "chart_type": chart_type,
            "chart_data": payload.get("chart_data") or {"labels": [], "datasets": []},
            "chart_meta": payload.get("chart_meta") or {},
            "provider_key": "",
            "widget_class": widget.widget_class,
            "department_micro_mode": widget.department_micro_mode or "",
            "is_special_case": False,
            "special_case_source": False,
        }

    # ---------------------------------------------------------
    # MACRO WIDGETS
    # ---------------------------------------------------------
    # Điều phối builder macro theo chart type để mỗi loại widget đi đúng flow dựng dữ liệu.
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

    # Dựng radar chart từ danh sách template line được cấu hình tường minh trên widget.
    def _build_macro_radar(self, evaluation, widget):
        # Soft rollout: radar widget chưa cấu hình line thì tạm thời không render chart.
        selected_template_lines = widget.radar_template_line_ids.sorted(
            key=lambda line: (line.sequence or 0, line.id or 0)
        )
        if not selected_template_lines:
            return False

        # Lập map evaluation line theo template line để resolve đúng snapshot của kỳ đánh giá hiện tại.
        evaluation_line_by_template = {
            line.kpi_line_id.id: line
            for line in evaluation.evaluation_line_ids
            if line.kpi_line_id
        }

        # Chỉ giữ lại các line đã được admin chọn và thực sự tồn tại trong evaluation hiện tại.
        matched_lines = []
        for template_line in selected_template_lines:
            evaluation_line = evaluation_line_by_template.get(template_line.id)
            if evaluation_line:
                matched_lines.append((template_line, evaluation_line))

        # Nếu toàn bộ line đã chọn đều không có snapshot tương ứng thì bỏ qua widget này.
        if not matched_lines:
            return False

        # Dùng nhãn snapshot của evaluation line trước để phản ánh đúng dữ liệu đã generate.
        labels = [
            evaluation_line.key_performance_area
            or getattr(evaluation_line, "name", False)
            or template_line.key_performance_area
            or _("KPI")
            for template_line, evaluation_line in matched_lines
        ]

        # Điểm radar đọc trực tiếp từ final_rating của từng evaluation line đã được map theo template.
        # ... (các phần trên giữ nguyên)
        scores = [
            round(float(getattr(evaluation_line, "final_rating", 0.0) or 0.0), 2)
            for _, evaluation_line in matched_lines
        ]

        # CODE THÊM MỚI: Đóng gói detail để render bảng điểm bên phải
        radar_details = [
            {"label": label, "score": score}
            for label, score in zip(labels, scores)
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
                        "label": _("Score"),
                        "data": scores,
                        "backgroundColor": "rgba(59, 130, 246, 0.2)",
                        "borderColor": "#3b82f6",
                        "pointBackgroundColor": "#3b82f6",
                        "pointRadius": 6,       # Kích thước dấu chấm to ra
                        "pointHoverRadius": 8,  # Kích thước khi hover chuột
                        "pointBorderWidth": 2,  # Độ dày viền chấm tròn
                    }
                ],
            },
            "chart_meta": {
                "radar_details": radar_details # <--- Đẩy data sang XML
            },
        }

    # Trả về target chuẩn cho các measure cần vẽ đường benchmark 100 điểm.
    def _get_macro_measure_target_value(self, measure_name):
        # Chỉ các tổng pillar chuẩn hóa theo thang 100 mới cần benchmark line cố định.
        if measure_name in TARGET_100_MEASURE_FIELDS:
            return 100.0
        return False

    # Trả nhãn measure thân thiện để legend ưu tiên hiển thị theo field đo thay vì tên widget.
    def _get_macro_measure_label(self, widget):
        measure_field = widget.measure_field_id
        if not measure_field:
            return widget.name or _("Measure")
        return measure_field.field_description or measure_field.name or widget.name or _(
            "Measure"
        )

    # Tạo metadata trục Y đủ chỗ cho benchmark line để target 100 không bị vẽ ra ngoài chart area.
    def _build_macro_target_axis_meta(self, values, target_value):
        if target_value is False:
            return {}

        # Các measure chuẩn hóa theo thang 100 phải luôn khóa trục Y trong khoảng 0..100.
        return {
            "min": 0,
            "max": float(target_value or 100.0),
            "beginAtZero": True,
        }

    # Dựng line chart trend và thêm benchmark line khi measure có target chuẩn.
    def _build_macro_trend(self, evaluation, widget):
        measure_name = widget.measure_field_id.name
        measure_label = self._get_macro_measure_label(widget)
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

        # Dataset chính hiển thị diễn biến score thực tế theo từng bucket thời gian/nhóm.
        datasets = [
            {
                "label": measure_label,
                "data": values,
                "borderColor": line_color,
                "backgroundColor": f"{line_color}33",
                "pointBackgroundColor": line_color,
                "tension": 0.3,
                "fill": True,
            }
        ]

        target_value = self._get_macro_measure_target_value(measure_name)
        chart_meta = {}
        if target_value is not False:
            # Khi measure có target chuẩn 100, thêm đường benchmark đỏ nét đứt để người xem so sánh nhanh.
            datasets.append(
                {
                    "label": _("Target"),
                    "data": [target_value] * len(labels),
                    "borderColor": "#dc2626",
                    "backgroundColor": "transparent",
                    "pointBackgroundColor": "#dc2626",
                    "pointRadius": 0,
                    "pointHoverRadius": 0,
                    "borderDash": [6, 6],
                    "tension": 0,
                    "fill": False,
                }
            )
            # Ép trục Y luôn đủ chỗ cho target line, đặc biệt khi score thực tế thấp hơn 100.
            chart_meta["y_axis"] = self._build_macro_target_axis_meta(
                values, target_value
            )

        return {
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Trend"),
            "chart_type": "line",
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": chart_meta,
        }

    # Dựng bar chart distribution và giữ thứ tự trục thời gian ổn định khi group theo date/datetime.
    def _build_macro_distribution(self, evaluation, widget):
        measure_name = widget.measure_field_id.name
        measure_label = self._get_macro_measure_label(widget)
        group_by_name = widget.group_by_field_id.name
        group_by_expr = self._build_groupby_expr(widget)
        model_name = self._resolve_target_model_name(widget)
        if not model_name or not measure_name or not group_by_name:
            return False

        # Lấy domain nền theo widget và mở rộng thêm filter_domain nếu admin có cấu hình.
        domain = self._build_macro_distribution_domain(evaluation, widget)
        extra_domain = self._parse_filter_domain(widget.filter_domain)
        if extra_domain:
            domain.extend(extra_domain)

        # Group dữ liệu theo đúng field/granularity đang cấu hình trên widget.
        distribution_data = self.env[model_name].sudo().read_group(
            domain=domain,
            fields=[f"{measure_name}:avg"],
            groupby=[group_by_expr],
        )
        if not distribution_data:
            return False

        # Group theo thời gian phải hiển thị theo thứ tự tăng dần thật sự của bucket để tránh tháng 6 đứng trước tháng 5.
        if widget.group_by_ttype in ("date", "datetime"):
            distribution_data.sort(
                key=lambda item: self._build_time_group_sort_key(
                    self._extract_group_value(item, group_by_expr, group_by_name)
                )
            )
        else:
            # Các distribution không phải thời gian vẫn ưu tiên sort theo giá trị để nổi bật nhóm lớn nhất.
            distribution_data.sort(
                key=lambda item: self._extract_aggregate_value(item, measure_name) or 0.0,
                reverse=True,
            )

        labels = []
        scores = []
        colors = []
        for item in distribution_data:
            # Chuẩn hóa label và aggregate value để frontend luôn nhận mảng đồng bộ.
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

        # Dataset cột chính hiển thị score aggregate của từng bucket/group.
        datasets = [
            {
                "label": measure_label,
                "data": scores,
                "backgroundColor": colors,
            }
        ]

        target_value = self._get_macro_measure_target_value(measure_name)
        chart_meta = {}
        if target_value is not False:
            # Distribution dùng chart_meta để frontend vẽ một đường ngang full width thay vì line dataset theo tâm cột.
            chart_meta["target_line"] = {
                "label": _("Target"),
                "value": target_value,
                "color": "#dc2626",
                "dash": [6, 6],
            }
            # Đồng bộ luôn scale Y để target 100 vẫn nằm trong chart dù dữ liệu thực tế còn thấp.
            chart_meta["y_axis"] = self._build_macro_target_axis_meta(
                scores, target_value
            )

        return {
            "widget_id": widget.id,
            "sequence": widget.sequence or 0,
            "title": widget.name or _("Distribution"),
            "chart_type": "bar",
            "chart_data": {
                "labels": labels,
                "datasets": datasets,
            },
            "chart_meta": chart_meta,
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

    # Tạo domain cho distribution và không khóa về một period khi trục X đang là thời gian.
    def _build_macro_distribution_domain(self, evaluation, widget):
        use_time_axis = widget.group_by_ttype in ("date", "datetime")

        # Khi chart đang group theo thời gian thì cần mở rộng qua nhiều kỳ để thấy nhiều cột so sánh.
        if widget.target_model == "evaluation":
            domain = [
                ("department_id", "=", evaluation.department_id.id),
                ("state", "!=", "cancel"),
            ]
            if not use_time_axis:
                # Các distribution không dùng time axis vẫn giữ logic so sánh trong cùng kỳ như trước.
                domain.append(("period_id", "=", evaluation.period_id.id))
            return domain

        domain = [
            ("evaluation_id.department_id", "=", evaluation.department_id.id),
            ("evaluation_id.state", "!=", "cancel"),
        ]
        if not use_time_axis:
            # Nhánh evaluation line cũng chỉ khóa cùng kỳ khi chart không group theo thời gian.
            domain.append(("evaluation_id.period_id", "=", evaluation.period_id.id))
        return domain

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

    # Chuẩn hóa raw group value của bucket thời gian thành sort key tăng dần ổn định.
    def _build_time_group_sort_key(self, group_value):
        normalized_value = group_value[0] if isinstance(group_value, tuple) else group_value
        if isinstance(normalized_value, datetime.datetime):
            return normalized_value
        if isinstance(normalized_value, datetime.date):
            return datetime.datetime.combine(normalized_value, datetime.time.min)
        if not normalized_value:
            return datetime.datetime.min

        text_value = str(normalized_value).strip()

        # Ưu tiên parse datetime ISO trước để giữ đúng thứ tự cả date lẫn datetime group bucket.
        try:
            return datetime.datetime.fromisoformat(text_value.replace(" ", "T"))
        except ValueError:
            pass

        # Fallback cho bucket chỉ có phần ngày hoặc chỉ có year-month do read_group trả về.
        for candidate in (f"{text_value}-01", text_value):
            try:
                parsed_date = fields.Date.to_date(candidate)
                if parsed_date:
                    return datetime.datetime.combine(parsed_date, datetime.time.min)
            except Exception:
                continue

        return datetime.datetime.max

    def _group_matches_current_employee(self, group_value, evaluation):
        if not evaluation.employee_id:
            return False
        if isinstance(group_value, tuple):
            return group_value[0] == evaluation.employee_id.id
        return group_value == evaluation.employee_id.id

    # ---------------------------------------------------------
    # GENERIC TARGET/ACTUAL PAYLOAD HELPERS
    # ---------------------------------------------------------
    # Dựng payload Target/Actual cho đúng một KPI line.
    def _build_single_line_target_actual_payload(self, line, source, chart_type):
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
        # Target/actual chart dùng thang điểm nguyên nên trục Y nên hiển thị số nguyên để dễ đọc.
        chart_meta["y_axis"] = {
            "beginAtZero": True,
            "integerOnly": True,
        }
        if chart_type == "stacked_bar":
            # Stacked bar của target/actual biểu diễn phần đạt được và phần còn thiếu tới target trên cùng một cột.
            gap_to_target = round(max(target_val - actual_val, 0.0), 2)
            return {
                "chart_data": {
                    "labels": [self._line_title(line, source)],
                    "datasets": [
                        {
                            "label": _("Actual"),
                            "data": [round(actual_val, 2)],
                            "stack": "target_actual_progress",
                            "backgroundColor": "rgba(3, 103, 176, 0.88)",
                            "borderColor": "#0367b0",
                        },
                        {
                            "label": _("Gap to Target"),
                            "data": [gap_to_target],
                            "stack": "target_actual_progress",
                            "backgroundColor": "rgba(148, 163, 184, 0.55)",
                            "borderColor": "#94a3b8",
                        },
                    ],
                },
                "chart_meta": {
                    **chart_meta,
                    "target_values": [round(target_val, 2)],
                    "actual_values": [round(actual_val, 2)],
                    "gap_to_target_values": [gap_to_target],
                },
            }
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

    # Dựng payload Target/Actual cho nhiều KPI line trong cùng một chart tổng hợp.
    def _build_multi_line_target_actual_payload(self, lines, chart_type, label_getter):
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
                # "note": _("Comparing Target and Actual values."),
            },
        }

    # ---------------------------------------------------------
    # INDIVIDUAL MICRO PROVIDERS
    # ---------------------------------------------------------
    # Ưu tiên nhãn snapshot trên line; chỉ fallback về source name khi line không có title phù hợp.
    def _line_title(self, line, source):
        return (
            getattr(line, "key_performance_area", False)
            or getattr(line, "name", False)
            or (source.name if source else False)
            or _("KPI Chart")
        )

    def _build_generic_target_actual_bar(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
    ):
        return self._build_single_line_target_actual_payload(
            line, source, chart_type
        )

    def _build_generic_domain_daily_series(
        self, evaluation, line, source, widget, chart_type, dashboard_kind
    ):
        # Daily series chỉ chạy được khi line snapshot còn giữ domain source hợp lệ.
        if not source:
            return False
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
                        "label": (source.name if source else False) or _("Attendance"),
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
