from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


MICRO_PROVIDER_SELECTION = [
    ("generic_target_actual_bar", "Generic Target vs Actual"),
    ("generic_domain_daily_series", "Generic Daily Series"),
    ("special_engine_punctuality", "Special Case: Check-in"),
    (
        "special_engine_attendance_overview",
        "Special Case: Attendance Overview",
    ),
]

MICRO_CHART_TYPE_SELECTION = [
    ("line", "Line"),
    ("bar", "Bar"),
    ("doughnut", "Doughnut"),
]

KPI_BEHAVIOR_SELECTION = [
    ("cumulative", "Tích lũy"),
    ("maintenance", "Duy trì"),
]

MACRO_WIDGET_TYPE_SELECTION = [
    ("radar_chart", "Biểu đồ radar"),
    ("trend_line", "Đường xu hướng (Biểu đồ dây)"),
    ("distribution", "Phân phối (Biểu đồ cột)"),
]
TARGET_MODEL_SELECTION = [
    ("evaluation", "Performance Evaluation"),
    ("evaluation_line", "Performance Evaluation Line"),
]

DEPARTMENT_MICRO_MODE_SELECTION = [
    ("employee_compare", "Compare Employees"),
    ("department_progress", "Department KPI Progress"),
]

class HrKpiDashboardWidget(models.Model):
    _name = "hr.kpi.dashboard.widget"
    _description = "KPI Dashboard Widget"
    _order = "dashboard_kind, sequence, id"

    name = fields.Char(required=True, translate=True)
    dashboard_kind = fields.Selection(
        [
            ("individual", "Dashboard Cá Nhân"),
            ("department", "Dashboard Phòng Ban"),
        ],
        required=True,
        default="individual",
    )
    widget_class = fields.Selection(
        [
            ("macro", "Biểu đồ Tổng hợp"),
            ("micro", "Biểu đồ Chi tiết KPI"),
        ],
        required=True,
        default="micro",
    )
    macro_widget_type = fields.Selection(
        MACRO_WIDGET_TYPE_SELECTION,
        string="Chart Type",
        oldname="widget_type",
    )
    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        string="Data Source",
        ondelete="set null",
    )
    provider_key = fields.Selection(
        MICRO_PROVIDER_SELECTION,
        string="Provider",
    )
    micro_chart_type = fields.Selection(
        MICRO_CHART_TYPE_SELECTION,
        string="Chart Type",
    )
    kpi_behavior = fields.Selection(
        KPI_BEHAVIOR_SELECTION,
        string="KPI Behavior",
    )
    employee_template_line_id = fields.Many2one(
        "hr.kpi.template.line",
        string="Employee Template Line",
        ondelete="set null",
        help="Select the employee KPI template line that this micro widget should read from.",
    )
    department_template_line_ids = fields.Many2many(
        "hr.department.kpi.template.line",
        "hr_kpi_dashboard_widget_department_template_line_rel",
        "widget_id",
        "template_line_id",
        string="Department Template Lines",
        help="Select the department KPI template lines that this micro widget should read from.",
    )
    target_model = fields.Selection(
        TARGET_MODEL_SELECTION,
        string="Target Model",
        required=True,
        default="evaluation",
    )
    target_model_real_name = fields.Char(
        compute="_compute_target_model_real_name",
        string="Target Model Real Name",
    )

    @api.depends("target_model")
    def _compute_target_model_real_name(self):
        for record in self:
            if record.target_model == "evaluation":
                record.target_model_real_name = "hr.performance.evaluation"
            elif record.target_model == "evaluation_line":
                record.target_model_real_name = "hr.performance.evaluation.line"
            else:
                record.target_model_real_name = False

    measure_field_id = fields.Many2one(
        "ir.model.fields",
        string="Measure Field",
        domain=[
            (
                "model",
                "in",
                ["hr.performance.evaluation", "hr.performance.evaluation.line"],
            ),
            ("ttype", "in", ["float", "integer", "monetary"]),
        ],
        ondelete="set null",
    )
    group_by_field_id = fields.Many2one(
        "ir.model.fields",
        string="Group By Field",
        domain=[
            (
                "model",
                "in",
                ["hr.performance.evaluation", "hr.performance.evaluation.line"],
            ),
            ("store", "=", True),
        ],
        ondelete="set null",
    )
    group_by_ttype = fields.Selection(
        related="group_by_field_id.ttype",
        string="Group By Type",
        readonly=True,
    )
    date_granularity = fields.Selection(
        [
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("quarter", "Quarter"),
            ("year", "Year"),
        ],
        string="Date Granularity",
        default="month",
    )
    filter_domain = fields.Text(default="[]")
    department_micro_mode = fields.Selection(
        DEPARTMENT_MICRO_MODE_SELECTION,
        string="Department Micro Mode",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    department_ids = fields.Many2many(
        "hr.department",
        "hr_kpi_dashboard_widget_department_rel",
        "widget_id",
        "department_id",
        string="Departments",
        help="Leave empty to apply this widget to all departments. Select one or more departments to scope the widget to those departments only.",
    )
    radar_template_line_ids = fields.Many2many(
        "hr.kpi.template.line",
        "hr_kpi_dashboard_widget_radar_template_line_rel",
        "widget_id",
        "template_line_id",
        string="Radar Template Lines",
        help="Select the KPI template lines that should appear in this radar chart. Leave empty to keep the radar widget inactive until it is configured.",
    )

    # Đồng bộ KPI Behavior khi provider đổi để tránh giữ lại giá trị cũ không còn hợp lệ.
    @api.onchange("provider_key")
    def _onchange_provider_key(self):
        for widget in self:
            if widget.provider_key != "generic_domain_daily_series":
                widget.kpi_behavior = False

    # Chuẩn hóa vals trước khi lưu để KPI Behavior chỉ tồn tại với daily series provider.
    @api.model
    def _normalize_widget_vals(self, vals):
        normalized_vals = dict(vals or {})
        if (
            normalized_vals.get("provider_key")
            and normalized_vals["provider_key"] != "generic_domain_daily_series"
        ):
            normalized_vals["kpi_behavior"] = False
        return normalized_vals

    # Làm sạch dữ liệu đầu vào ngay từ create để constraint không bị vướng bởi giá trị cũ.
    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [
            self._normalize_widget_vals(vals) for vals in (vals_list or [])
        ]
        return super().create(normalized_vals_list)

    # Khi đổi provider qua ORM, tự clear KPI Behavior cũ nếu provider mới không còn dùng field này.
    def write(self, vals):
        normalized_vals = self._normalize_widget_vals(vals)
        return super().write(normalized_vals)

    @api.constrains(
        "widget_class",
        "data_source_id",
        "provider_key",
        "micro_chart_type",
        "kpi_behavior",
        "macro_widget_type",
        "dashboard_kind",
        "target_model",
        "measure_field_id",
        "group_by_field_id",
        "group_by_ttype",
        "date_granularity",
        "department_micro_mode",
        "employee_template_line_id",
        "department_template_line_ids",
        "radar_template_line_ids",
    )
    # Kiểm tra cấu hình widget theo đúng rule nghiệp vụ của từng loại dashboard chart.
    def _check_widget_config(self):
        allowed_chart_types = {
            "generic_target_actual_bar": {"bar", "doughnut"},
            "generic_domain_daily_series": {"line", "bar"},
            "special_engine_punctuality": {"line"},
            "special_engine_attendance_overview": {"doughnut"},
        }
        for widget in self:
            # Micro widget chỉ bắt buộc provider và chart type; selector line mới sẽ quyết định KPI cần chart.
            if widget.widget_class == "micro":
                if not widget.provider_key or not widget.micro_chart_type:
                    raise ValidationError(
                        _(
                            "Micro widget '%s' must define a Provider and Micro Chart Type."
                        )
                        % widget.name
                    )
                # Giới hạn chart type theo đúng provider đang được chọn.
                allowed = allowed_chart_types.get(widget.provider_key, set())
                if allowed and widget.micro_chart_type not in allowed:
                    raise ValidationError(
                        _(
                            "Micro Chart Type '%(chart)s' is not valid for provider '%(provider)s' on widget '%(name)s'."
                        )
                        % {
                            "chart": widget.micro_chart_type,
                            "provider": widget.provider_key,
                            "name": widget.name,
                        }
                    )
                # Daily series là provider duy nhất cần khai báo KPI behavior.
                if (
                    widget.provider_key == "generic_domain_daily_series"
                    and not widget.kpi_behavior
                ):
                    raise ValidationError(
                        _(
                            "Micro widget '%s' using the daily series provider must define a KPI Behavior."
                        )
                        % widget.name
                    )
                # Các provider còn lại không được mang theo KPI behavior để tránh cấu hình nhiễu.
                if (
                    widget.provider_key != "generic_domain_daily_series"
                    and widget.kpi_behavior
                ):
                    raise ValidationError(
                        _(
                            "KPI Behavior only applies to the 'generic_domain_daily_series' provider on widget '%s'."
                        )
                        % widget.name
                    )
                # Dashboard cá nhân sẽ validate line selector và provider compatibility theo employee template line.
                if widget.dashboard_kind == "individual":
                    widget._validate_individual_micro_selector()

                # Dashboard phòng ban cần thêm mode để service biết cách dựng chart micro.
                if (
                    widget.dashboard_kind == "department"
                    and not widget.department_micro_mode
                ):
                    raise ValidationError(
                        _(
                            "Department micro widget '%s' must define a Department Micro Mode."
                        )
                        % widget.name
                    )

                # Dashboard phòng ban dùng selector khác nhau theo từng department micro mode.
                if widget.dashboard_kind == "department":
                    widget._validate_department_micro_selector()
                continue

            # Macro widget phải khai báo rõ chart type trước khi kiểm tra từng biến thể.
            if not widget.macro_widget_type:
                raise ValidationError(
                    _("Macro widget '%s' must define a Macro Widget Type.")
                    % widget.name
                )

            # Trend/Distribution vẫn dùng flow query động nên cần measure/group/date như cũ.
            if widget.macro_widget_type in ("trend_line", "distribution"):
                if not widget.measure_field_id or not widget.group_by_field_id:
                    raise ValidationError(
                        _(
                            "Macro widget '%s' must define both Measure Field and Group By Field."
                        )
                        % widget.name
                    )
                if widget.group_by_ttype in ("date", "datetime") and not widget.date_granularity:
                    raise ValidationError(
                        _(
                            "Macro widget '%s' grouped by a date or datetime field must define a Date Granularity."
                        )
                        % widget.name
                    )
                continue

            # Radar chart chỉ hợp lệ trên dashboard cá nhân và phải đọc từ evaluation record.
            if widget.macro_widget_type == "radar_chart":
                if widget.dashboard_kind != "individual":
                    raise ValidationError(
                        _(
                            "Radar widget '%s' is only supported on the individual dashboard."
                        )
                        % widget.name
                    )
                if widget.target_model != "evaluation":
                    raise ValidationError(
                        _(
                            "Radar widget '%s' must use the Performance Evaluation target model."
                        )
                        % widget.name
                    )

    # Kiểm tra selector line và provider compatibility cho micro widget trên dashboard cá nhân.
    def _validate_individual_micro_selector(self):
        self.ensure_one()

        # Rollout mềm: widget cũ chưa chọn selector mới vẫn được lưu, runtime sẽ tự bỏ qua.
        template_line = self.employee_template_line_id
        if not template_line:
            return

        # Section row không có dữ liệu target/actual phù hợp cho micro chart.
        if template_line.is_section:
            raise ValidationError(
                _(
                    "Micro widget '%(widget)s' cannot use section row '%(line)s' as the employee template line."
                )
                % {
                    "widget": self.name,
                    "line": template_line.key_performance_area or template_line.display_name,
                }
            )

        # Generic target/actual chỉ cần line hợp lệ; không phụ thuộc source trên widget.
        if self.provider_key == "generic_target_actual_bar":
            return

        source = template_line.data_source_id
        if self.provider_key == "generic_domain_daily_series":
            # Daily series cần domain source, aggregation phù hợp và date field để bucket theo ngày.
            if (
                not source
                or source.source_type != "domain"
                or source.aggregation not in ("count", "sum", "avg")
                or not source.date_field_id
            ):
                raise ValidationError(
                    _(
                        "Employee template line '%(line)s' on widget '%(widget)s' must use a domain data source with count, sum, or average aggregation and a date field for the daily series provider."
                    )
                    % {
                        "line": template_line.key_performance_area
                        or template_line.display_name,
                        "widget": self.name,
                    }
                )
            return

        # Các provider attendance đặc thù cần line mang đúng source code để engine và chart semantics nhất quán.
        required_source_code = {
            "special_engine_punctuality": "attendance_late_days",
            "special_engine_attendance_overview": "attendance_present_days",
        }.get(self.provider_key)
        if required_source_code and (not source or source.code != required_source_code):
            raise ValidationError(
                _(
                    "Employee template line '%(line)s' on widget '%(widget)s' must use data source '%(source)s' for provider '%(provider)s'."
                )
                % {
                    "line": template_line.key_performance_area or template_line.display_name,
                    "widget": self.name,
                    "source": required_source_code,
                    "provider": self.provider_key,
                }
            )

    # Kiểm tra selector line của micro widget trên dashboard phòng ban theo mode đang cấu hình.
    def _validate_department_micro_selector(self):
        self.ensure_one()

        # Employee compare tái sử dụng employee KPI template line để map line của từng nhân viên trong cùng kỳ.
        if self.department_micro_mode == "employee_compare":
            if self.employee_template_line_id and self.employee_template_line_id.is_section:
                raise ValidationError(
                    _(
                        "Department micro widget '%(widget)s' cannot use section row '%(line)s' as the employee template line."
                    )
                    % {
                        "widget": self.name,
                        "line": self.employee_template_line_id.key_performance_area
                        or self.employee_template_line_id.display_name,
                    }
                )
            return

        # Department progress có thể chart nhiều line, nhưng tất cả đều phải là line thực chứ không phải section.
        if self.department_micro_mode == "department_progress":
            section_lines = self.department_template_line_ids.filtered("is_section")
            if section_lines:
                raise ValidationError(
                    _(
                        "Department micro widget '%(widget)s' cannot use section rows in Department Template Lines: %(lines)s."
                    )
                    % {
                        "widget": self.name,
                        "lines": ", ".join(section_lines.mapped("name")),
                    }
                )

    # Trả payload widget cho frontend/admin với đầy đủ metadata scope phòng ban.
    def _serialize_widget(self):
        self.ensure_one()
        data_source = self.data_source_id
        measure_field = self.measure_field_id
        group_by_field = self.group_by_field_id
        employee_template_line = self.employee_template_line_id
        department_template_lines = self.department_template_line_ids.sorted(
            key=lambda line: (line.sequence or 0, line.id or 0)
        )
        radar_template_lines = self.radar_template_line_ids.sorted(
            key=lambda line: (line.sequence or 0, line.id or 0)
        )
        return {
            "id": self.id,
            "name": self.name,
            "dashboard_kind": self.dashboard_kind,
            "widget_class": self.widget_class,
            "macro_widget_type": self.macro_widget_type or "",
            "widget_type": self.macro_widget_type or "",
            "target_model": self.target_model or "evaluation",
            "measure_field_id": measure_field.id if measure_field else False,
            "measure_field_name": measure_field.name if measure_field else "",
            "group_by_field_id": group_by_field.id if group_by_field else False,
            "group_by_field_name": group_by_field.name if group_by_field else "",
            "group_by_ttype": self.group_by_ttype or "",
            "date_granularity": self.date_granularity or "",
            "filter_domain": self.filter_domain or "[]",
            "department_micro_mode": self.department_micro_mode or "",
            "sequence": self.sequence or 0,
            "active": bool(self.active),
            "data_source_id": data_source.id if data_source else False,
            "data_source_name": data_source.name if data_source else "",
            "department_ids": self.department_ids.ids,
            "department_names": self.department_ids.mapped("name"),
            "employee_template_line_id": employee_template_line.id
            if employee_template_line
            else False,
            "employee_template_line_name": employee_template_line.key_performance_area
            if employee_template_line
            else "",
            "department_template_line_ids": department_template_lines.ids,
            "department_template_line_names": department_template_lines.mapped("name"),
            "radar_template_line_ids": radar_template_lines.ids,
            "radar_template_line_names": radar_template_lines.mapped(
                "key_performance_area"
            ),
            "provider_key": self.provider_key or "",
            "micro_chart_type": self.micro_chart_type or "",
            "kpi_behavior": self.kpi_behavior or "",
        }

    # Lấy record widget theo dashboard kind và scope phòng ban hiện tại.
    @api.model
    def get_dashboard_widget_records(
        self, dashboard_kind, widget_class=False, department=False
    ):
        domain = [("dashboard_kind", "=", dashboard_kind), ("active", "=", True)]
        if widget_class:
            domain.append(("widget_class", "=", widget_class))

        department_id = department.id if hasattr(department, "id") else department

        # Nếu dashboard không có department context thì chỉ lấy widget global.
        # Nếu có department thì lấy cả widget global lẫn widget được gắn đúng
        # phòng ban hiện tại.
        if department_id:
            domain.extend(
                [
                    "|",
                    ("department_ids", "=", False),
                    ("department_ids", "in", [department_id]),
                ]
            )
        else:
            domain.append(("department_ids", "=", False))

        return self.sudo().search(
            domain,
            order="sequence, id",
        )

    # Trả danh sách widget đã serialize theo dashboard kind và scope phòng ban.
    @api.model
    def get_dashboard_widgets(self, dashboard_kind, department=False):
        widgets = self.get_dashboard_widget_records(
            dashboard_kind,
            department=department,
        )
        return [widget._serialize_widget() for widget in widgets]
