from odoo import fields, models


class HrJob(models.Model):
    _inherit = "hr.job"

    x_p11_standard_amount = fields.Float(
        string="Standard Amount P1.1",
        digits=(16, 0),
        default=0.0,
    )
    x_p12_standard_amount = fields.Float(
        string="Standard Amount P1.2",
        digits=(16, 0),
        default=0.0,
    )
    x_p21_standard_amount = fields.Float(
        string="Standard Amount P2.1",
        digits=(16, 0),
        default=0.0,
    )
    x_p22_standard_amount = fields.Float(
        string="Standard Amount P2.2",
        digits=(16, 0),
        default=0.0,
    )
    x_p31_standard_amount = fields.Float(
        string="Standard Amount P3.1",
        digits=(16, 0),
        default=0.0,
    )
    x_p32_standard_amount = fields.Float(
        string="Standard Amount P3.2",
        digits=(16, 0),
        default=0.0,
    )
