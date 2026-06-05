from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEvaluationPillar(models.Model):
    _name = "hr.evaluation.pillar"
    _description = "Evaluation Pillar"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()
    category_ids = fields.One2many(
        "hr.evaluation.category",
        "pillar_id",
        string="Categories",
    )

    _sql_constraints = [
        (
            "hr_evaluation_pillar_code_uniq",
            "unique(code)",
            "The pillar code must be unique.",
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
                raise ValidationError("Pillar code is required.")
