from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrKpiUnit(models.Model):
    _name = "hr.kpi.unit"
    _description = "KPI Unit"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "The KPI unit code must be unique."),
    ]

    @api.constrains("name", "code")
    def _check_name_code(self):
        for unit in self:
            if not (unit.name or "").strip():
                raise ValidationError(_("Unit name is required."))
            if not (unit.code or "").strip():
                raise ValidationError(_("Unit code is required."))
