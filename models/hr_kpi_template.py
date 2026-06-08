from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrKpiTemplate(models.Model):
    _name = "hr.kpi.template"
    _description = "Employee KPI Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string=_("Name"), required=True, tracking=True)
    kpi_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        help="The KPI lines included in this KPI template.",
    )
    kpi_line_p2_1_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p2_1")],
        string="P2.1 KPI Lines",
        help="KPI lines that belong to the P2.1 pillar.",
    )
    kpi_line_p2_2_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p2_2")],
        string="P2.2 KPI Lines",
        help="KPI lines that belong to the P2.2 pillar.",
    )
    kpi_line_p3_individual_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p3_individual")],
        string="P3 Individual KPI Lines",
        help="KPI lines that belong to the P3 individual pillar.",
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Job Position",
        help="Apply this KPI template to employees in the selected job position.",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        help="Apply this KPI template to employees in the selected department.",
    )
    period_type = fields.Selection(
        [
            ("monthly", "Hàng tháng"),
            ("quarterly", "Hàng quý"),
            ("biannual", "Nửa năm"),
            ("yearly", "Hàng năm"),
        ],
        string="Tần suất đánh giá",
        required=True,
        default="monthly",
        tracking=True,
        help="Quy định tần suất sử dụng bản mẫu này."
    )
    scoring_profile_id = fields.Many2one(
        "hr.kpi.scoring.profile",
        string="Scoring Profile",
        ondelete="set null",
    )
    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string=_("Parent Department KPI Template"),
        domain="[('department_id', '=', department_id), ('period_type', '=', period_type)]",
        ondelete="set null",
    )
    # Khai báo các field chứa tên động của từng Pillar
    pillar_p2_1_name = fields.Char(compute="_compute_dynamic_pillar_names", string="Tên Pillar P2.1")
    pillar_p2_2_name = fields.Char(compute="_compute_dynamic_pillar_names", string="Tên Pillar P2.2")
    pillar_p3_ind_name = fields.Char(compute="_compute_dynamic_pillar_names", string="Tên Pillar P3")

    def _compute_dynamic_pillar_names(self):
        # Truy vấn database một lần để lấy tất cả các pillar cần thiết (Tối ưu hiệu suất)
        # Giả định model hr.evaluation.pillar của bạn có trường 'code' để nhận diện
        pillars = self.env['hr.evaluation.pillar'].sudo().search([
            ('code', 'in', ['p2_1', 'p2_2', 'p3_individual'])
        ])
        
        # Tạo một dictionary { 'p2_1': 'Kiến Thức', 'p2_2': 'Kỹ năng chuyên môn', ... }
        pillar_dict = {p.code: p.name for p in pillars}

        for rec in self:
            # Gán tên từ database, nếu không tìm thấy thì dùng tên mặc định
            rec.pillar_p2_1_name = pillar_dict.get('p2_1', 'P2.1')
            rec.pillar_p2_2_name = pillar_dict.get('p2_2', 'P2.2')
            rec.pillar_p3_ind_name = pillar_dict.get('p3_individual', 'P3.1.1 KPI Cá Nhân')

    # @api.constrains("kpi_line_ids")
    # def _check_total_weight(self):
    #     for kpi in self:
    #         valid_lines = kpi.kpi_line_ids.filtered(lambda l: not l.is_section)
    #         total_weight = sum(valid_lines.mapped("weight"))
    #         if valid_lines and abs(total_weight - 100.0) > 0.1:
    #             raise ValidationError(
    #                 _(
    #                     "The total weight of all KPI lines must equal exactly 100. The current total is %s."
    #                 )
    #                 % round(total_weight, 2)
    #             )

    @api.constrains("department_kpi_id", "kpi_line_ids")
    def _check_kpi_line_parent_dept_lines(self):
        for kpi in self:
            kpi.kpi_line_ids._validate_parent_dept_line_consistency(
                parent_kpi=kpi.department_kpi_id
            )

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"kpi_id": new_parent.id})
        return new_parent
