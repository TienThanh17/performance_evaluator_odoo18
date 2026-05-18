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
    # Thêm trường liên kết Header Template Phòng ban để làm gốc lọc dữ liệu
    department_kpi_id = fields.Many2one(
        'hr.department.kpi',
        string='Mẫu KPI Phòng ban Cha',
        domain="[('department_id', '=', department_id), ('period', '=', period)]"
    )

    @api.constrains('kpi_line_ids')
    def _check_total_weight(self):
        for kpi in self:
            # Lọc bỏ các dòng là section/note (chỉ tính các dòng KPI thực tế)
            valid_lines = kpi.kpi_line_ids.filtered(lambda l: not l.is_section)

            # Tính tổng weight
            total_weight = sum(valid_lines.mapped('weight'))

            # Bỏ qua validate nếu chưa có dòng nào (tùy logic nghiệp vụ của bạn)
            if not valid_lines:
                continue

            # Sử dụng float_compare của Odoo để tránh lỗi sai số thập phân (ví dụ: 99.9999999 != 100.0)
            # if float_compare(total_weight, 100.0, precision_digits=2) != 0:
            #     raise ValidationError(
            #         _("The total weight of all KPI lines must equal exactly 100. The current total is %s.") % total_weight
            #     )

            # Khai báo mức độ sai số cho phép.
             # 0.02 sẽ cover được trường hợp 33.33 * 3 = 99.99 hoặc các làm tròn tương tự
            tolerance = 0.1

            # Nếu khoảng cách từ tổng hiện tại đến 100 lớn hơn sai số cho phép thì mới báo lỗi
            if abs(total_weight - 100.0) > tolerance:
                raise ValidationError(
                    _("The total weight of all KPI lines must equal exactly 100. The current total is %s.") % round(total_weight, 2)
                )

    @api.constrains('department_kpi_id', 'kpi_line_ids')
    def _check_kpi_line_parent_dept_lines(self):
        for kpi in self:
            for line in kpi.kpi_line_ids.filtered('parent_dept_line_id'):
                if not kpi.department_kpi_id:
                    raise ValidationError(
                        _("Please select a parent Department KPI Template before linking department KPI lines.")
                    )
                if line.parent_dept_line_id.department_kpi_id != kpi.department_kpi_id:
                    raise ValidationError(
                        _("The selected department KPI line must belong to the parent Department KPI Template.")
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
