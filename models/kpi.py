from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

class KPI(models.Model):
    _name = 'hr.kpi'
    _description = 'KPI for Department'

    name = fields.Char(string='KPI Template', required=True)
    kpi_line_ids = fields.One2many(
        'hr.kpi.line',
        'kpi_id',
        help="The KPI lines included in this KPI template (sections and KPI items).",
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        help="Apply this KPI template to employees in the selected job position.",
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        help="Apply this KPI template to employees in the selected department.",
    )
    period = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("half_yearly", "Half-Yearly"),
            ("yearly", "Yearly"),
        ],
        string="Evaluation Period",
        required=True,
        default="monthly",
        help="The evaluation cycle for this KPI template.",
    )

    @api.constrains('kpi_line_ids')
    def _check_total_weight(self):
        for kpi in self:
            # Lọc bỏ các dòng là section/note (chỉ tính các dòng KPI thực tế)
            valid_lines = kpi.kpi_line_ids.filtered(lambda l: not l.display_type)

            # Tính tổng weight
            total_weight = sum(valid_lines.mapped('weight'))

            # Bỏ qua validate nếu chưa có dòng nào (tùy logic nghiệp vụ của bạn)
            if not valid_lines:
                continue

            # Sử dụng float_compare của Odoo để tránh lỗi sai số thập phân (ví dụ: 99.9999999 != 100.0)
            if float_compare(total_weight, 100.0, precision_digits=2) != 0:
                raise ValidationError(
                    _("The total weight of all KPI lines must equal exactly 100. The current total is %s.") % total_weight
                )

    def copy(self, default=None):
        # 1. Initialize default dictionary
        default = default or {}

        # 2. Add specific fields to update during copy
        default['name'] = self.name + ' (Copy)'

        # 3. Call super to create the new parent record
        new_parent = super(KPI, self).copy(default)

        # 4. Iterate over original lines and copy them
        for line in self.kpi_line_ids:
            line.copy({'kpi_id': new_parent.id})

        return new_parent