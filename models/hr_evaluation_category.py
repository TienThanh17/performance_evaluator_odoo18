from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEvaluationCategory(models.Model):
    _name = "hr.evaluation.category"
    _description = "Evaluation Category"
    _order = "pillar_id, sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    pillar_id = fields.Many2one(
        "hr.evaluation.pillar",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [
        (
            "hr_evaluation_category_code_pillar_uniq",
            "unique(code, pillar_id)",
            "The category code must be unique inside a pillar.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code"):
                vals["code"] = self._normalize_code(vals["code"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("code"):
            vals = dict(vals, code=self._normalize_code(vals["code"]))
        return super().write(vals)

    @api.model
    def _normalize_code(self, code):
        return (code or "").strip().lower()

    @api.constrains("code")
    def _check_code(self):
        for rec in self:
            code = self._normalize_code(rec.code)
            if not code:
                raise ValidationError("Category code is required.")
