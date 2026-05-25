from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrKpiPeriod(models.Model):
    _name = "hr.kpi.period"
    _description = "KPI Period"
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, translate=True)
    period_type = fields.Selection(
        [
            ("monthly", "Hàng tháng"),
            ("quarterly", "Hàng quý"),
            ("biannual", "Nửa năm"),
            ("yearly", "Hàng năm"),
            ("custom", "Tùy chỉnh"),
        ],
        required=True,
        default="monthly",
    )
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "date_check",
            "CHECK(date_end >= date_start)",
            "Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.",
        ),
    ]

    def name_get(self):
        result = []
        for rec in self:
            if rec.date_start and rec.date_end:
                label = _("%(name)s (%(start)s - %(end)s)") % {
                    "name": rec.name,
                    "start": rec.date_start,
                    "end": rec.date_end,
                }
            else:
                label = rec.name
            result.append((rec.id, label))
        return result

    @api.constrains("date_start", "date_end")
    def _check_date_range(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(
                    _("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu.")
                )
