from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEvaluationPillar(models.Model):
    _name = "hr.evaluation.pillar"
    _description = "Evaluation Pillar"
    _order = "sequence, id"

    _CODE_SELECTION = [
        ("p2_1", "P2.1"),
        ("p2_2", "P2.2"),
        ("p3_individual", "P3.1.1"),
        ("p3_department", "P3.1.2"),
    ]

    name = fields.Char(required=True)
    code = fields.Selection(
        selection=_CODE_SELECTION,
        required=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [
        (
            "hr_evaluation_pillar_code_uniq",
            "unique(code)",
            "The pillar code must be unique.",
        )
    ]

    @api.constrains("code")
    def _check_code(self):
        for rec in self:
            if not rec.code:
                raise ValidationError("Pillar code is required.")
