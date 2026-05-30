from odoo import api, fields, models


class HrKpiDashboardWidget(models.Model):
    _name = "hr.kpi.dashboard.widget"
    _description = "KPI Dashboard Widget"
    _order = "dashboard_kind, sequence, id"
    _sql_constraints = [
        ("code_uniq", "unique(code)", "Dashboard widget code must be unique."),
    ]

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    dashboard_kind = fields.Selection(
        [
            ("individual", "Dashboard cá nhân"),
            ("department", "Dashboard phòng ban"),
            ("report", "Dashboard báo cáo"),
        ],
        required=True,
        default="individual",
    )
    widget_type = fields.Selection(
        [
            ("score_card", "Thẻ điểm"),
            ("bar_chart", "Biểu đồ cột"),
            ("radar_chart", "Biểu đồ radar"),
            ("trend_line", "Đường xu hướng"),
            ("distribution", "Phân phối điểm"),
        ],
        required=True,
    )
    scope = fields.Selection(
        [
            ("department", "Theo phòng ban"),
            ("personal", "Cá nhân"),
        ],
        required=True,
        default="company",
    )
    measure_field = fields.Char(default="final_score")
    filter_domain = fields.Char(default="[]")
    group_by = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    def _serialize_widget(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "dashboard_kind": self.dashboard_kind,
            "widget_type": self.widget_type,
            "scope": self.scope,
            "measure_field": self.measure_field or "",
            "group_by": self.group_by or "",
            "filter_domain": self.filter_domain or "[]",
            "sequence": self.sequence or 0,
            "active": bool(self.active),
        }

    @api.model
    def get_dashboard_widgets(self, dashboard_kind):
        widgets = self.sudo().search(
            [("dashboard_kind", "=", dashboard_kind), ("active", "=", True)]
        )
        return [widget._serialize_widget() for widget in widgets]

    @api.model
    def get_dashboard_widget_map(self, dashboard_kind):
        widgets = self.get_dashboard_widgets(dashboard_kind)
        return {widget["code"]: widget for widget in widgets}
