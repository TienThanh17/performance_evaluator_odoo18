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
            ("micro", "Biểu đồ Chi tiết"),
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
    target_model = fields.Selection(
        TARGET_MODEL_SELECTION,
        string="Target Model",
        required=True,
        default="evaluation",
    )
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
    )
    def _check_widget_config(self):
        allowed_chart_types = {
            "generic_target_actual_bar": {"bar", "doughnut"},
            "generic_domain_daily_series": {"line", "bar"},
            "special_engine_punctuality": {"line"},
            "special_engine_attendance_overview": {"doughnut"},
        }
        for widget in self:
            if widget.widget_class == "micro":
                if (
                    not widget.data_source_id
                    or not widget.provider_key
                    or not widget.micro_chart_type
                ):
                    raise ValidationError(
                        _(
                            "Micro widget '%s' bat buoc phai co Data Source, Provider va Micro Chart Type."
                        )
                        % widget.name
                    )
                allowed = allowed_chart_types.get(widget.provider_key, set())
                if allowed and widget.micro_chart_type not in allowed:
                    raise ValidationError(
                        _(
                            "Micro Chart Type '%(chart)s' khong hop le cho provider '%(provider)s' tren widget '%(name)s'."
                        )
                        % {
                            "chart": widget.micro_chart_type,
                            "provider": widget.provider_key,
                            "name": widget.name,
                        }
                    )
                if (
                    widget.provider_key == "generic_domain_daily_series"
                    and not widget.kpi_behavior
                ):
                    raise ValidationError(
                        _(
                            "Micro widget '%s' su dung provider daily series bat buoc phai co KPI Behavior."
                        )
                        % widget.name
                    )
                if (
                    widget.provider_key != "generic_domain_daily_series"
                    and widget.kpi_behavior
                ):
                    raise ValidationError(
                        _(
                            "KPI Behavior chi ap dung cho provider 'generic_domain_daily_series' tren widget '%s'."
                        )
                        % widget.name
                    )
                if (
                    widget.dashboard_kind == "department"
                    and not widget.department_micro_mode
                ):
                    raise ValidationError(
                        _(
                            "Department micro widget '%s' bat buoc phai co Department Micro Mode."
                        )
                        % widget.name
                    )
                continue

            if not widget.macro_widget_type:
                raise ValidationError(
                    _("Macro widget '%s' bat buoc phai co Macro Widget Type.")
                    % widget.name
                )

            if widget.macro_widget_type in ("trend_line", "distribution"):
                if not widget.measure_field_id or not widget.group_by_field_id:
                    raise ValidationError(
                        _(
                            "Macro widget '%s' bat buoc phai co Measure Field va Group By Field."
                        )
                        % widget.name
                    )
                if widget.group_by_ttype in ("date", "datetime") and not widget.date_granularity:
                    raise ValidationError(
                        _(
                            "Macro widget '%s' group theo field ngay/gio bat buoc phai co Date Granularity."
                        )
                        % widget.name
                    )

    def _serialize_widget(self):
        self.ensure_one()
        data_source = self.data_source_id
        measure_field = self.measure_field_id
        group_by_field = self.group_by_field_id
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
            "provider_key": self.provider_key or "",
            "micro_chart_type": self.micro_chart_type or "",
            "kpi_behavior": self.kpi_behavior or "",
        }

    @api.model
    def get_dashboard_widget_records(self, dashboard_kind, widget_class=False):
        domain = [("dashboard_kind", "=", dashboard_kind), ("active", "=", True)]
        if widget_class:
            domain.append(("widget_class", "=", widget_class))
        return self.sudo().search(
            domain,
            order="sequence, id",
        )

    @api.model
    def get_dashboard_widgets(self, dashboard_kind):
        widgets = self.get_dashboard_widget_records(dashboard_kind)
        return [widget._serialize_widget() for widget in widgets]
