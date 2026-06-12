from odoo import _, api, fields, models


class HrKpiTemplate(models.Model):
    _name = "hr.kpi.template"
    _description = "Employee KPI Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string=_("Name"), required=True, tracking=True)
    kpi_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        help="The KPI lines included in this KPI template.",
        ondelete='cascade',
    )
    kpi_line_p2_1_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p2_1")],
        string="P2.1 KPI Lines",
        help="KPI lines that belong to the P2.1 pillar.",
        ondelete='cascade',
    )
    kpi_line_p2_2_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p2_2")],
        string="P2.2 KPI Lines",
        help="KPI lines that belong to the P2.2 pillar.",
        ondelete='cascade',
    )
    kpi_line_p3_individual_ids = fields.One2many(
        "hr.kpi.template.line",
        "kpi_id",
        domain=[("pillar_code", "=", "p3_individual")],
        string="P3 Individual KPI Lines",
        help="KPI lines that belong to the P3 individual pillar.",
        ondelete='cascade',
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
        help="Quy định tần suất sử dụng bản mẫu này.",
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
    pillar_p2_1_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Tên Pillar P2.1"
    )
    pillar_p2_2_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Tên Pillar P2.2"
    )
    pillar_p3_ind_name = fields.Char(
        compute="_compute_dynamic_pillar_names", string="Tên Pillar P3"
    )

    def _compute_dynamic_pillar_names(self):
        # Truy vấn database một lần để lấy tất cả các pillar cần thiết (Tối ưu hiệu suất)
        # Giả định model hr.evaluation.pillar của bạn có trường 'code' để nhận diện
        pillars = (
            self.env["hr.evaluation.pillar"]
            .sudo()
            .search([("code", "in", ["p2_1", "p2_2", "p3_individual"])])
        )

        # Tạo một dictionary { 'p2_1': 'Kiến Thức', 'p2_2': 'Kỹ năng chuyên môn', ... }
        pillar_dict = {p.code: p.name for p in pillars}

        for rec in self:
            # Gán tên từ database, nếu không tìm thấy thì dùng tên mặc định
            rec.pillar_p2_1_name = pillar_dict.get("p2_1", "P2.1")
            rec.pillar_p2_2_name = pillar_dict.get("p2_2", "P2.2")
            rec.pillar_p3_ind_name = pillar_dict.get(
                "p3_individual", "P3.1.1 KPI Cá Nhân"
            )

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

    # Trả về danh sách field one2many có thể gửi command làm thay đổi KPI lines.
    def _get_weight_validation_line_fields(self):
        # Gom cả field tổng và các field theo từng tab pillar để parent write/create
        # có thể nhận diện đầy đủ mọi save path từ form.
        return (
            "kpi_line_ids",
            "kpi_line_p2_1_ids",
            "kpi_line_p2_2_ids",
            "kpi_line_p3_individual_ids",
        )

    # Validate normalized 3P weights một lần trên trạng thái cuối cùng của template.
    def _validate_kpi_line_weight_batch(self):
        # Luôn gom từ kpi_line_ids để validator nhìn thấy toàn bộ cây line còn lại
        # sau khi Odoo xử lý xong batch command của các tab.
        line_records = self.mapped("kpi_line_ids")
        if line_records:
            line_records._validate_normalized_3p_weight_structure()

    # Dời normalized 3P validation lên parent create để child line không validate
    # giữa chừng khi form tạo mới gửi nhiều one2many commands cùng lúc.
    @api.model_create_multi
    def create(self, vals_list):
        line_fields = self._get_weight_validation_line_fields()

        # Nếu caller đã chủ động skip validate hoặc create không đụng các field
        # one2many KPI line thì giữ nguyên flow mặc định.
        if self.env.context.get("skip_normalized_3p_weight_validation") or not any(
            any(field in vals for field in line_fields) for vals in vals_list
        ):
            return super().create(vals_list)

        # Tạm bỏ qua validate ở child line để Odoo xử lý trọn bộ command list trước.
        records = super(
            HrKpiTemplate,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).create(vals_list)

        # Chỉ validate một lần trên trạng thái cuối cùng của template vừa tạo.
        records._validate_kpi_line_weight_batch()
        return records

    # Dời normalized 3P validation lên parent write để child write/unlink không
    # validate giữa chừng khi một lần save vừa update vừa delete line.
    def write(self, vals):
        line_fields = self._get_weight_validation_line_fields()

        # Các write không chạm KPI line hoặc đã được caller bọc context skip
        # thì tiếp tục dùng flow mặc định.
        if self.env.context.get("skip_normalized_3p_weight_validation") or not any(
            field in vals for field in line_fields
        ):
            return super().write(vals)

        # Tạm bỏ qua validate ở child line để Odoo hoàn tất toàn bộ one2many
        # commands, bao gồm cả write/unlink chạy nối tiếp trong cùng transaction.
        res = super(
            HrKpiTemplate,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).write(vals)

        # Sau khi command list hoàn tất, validate đúng trên trạng thái cuối.
        self._validate_kpi_line_weight_batch()
        return res

    # Trả về KPI lines theo thứ tự preorder của từng pillar để các màn generate giữ đúng cây template.
    def get_hierarchy_ordered_lines(self):
        self.ensure_one()
        ordered_ids = []

        # Nhóm theo pillar hiện có và ưu tiên theo sequence của master pillar.
        pillar_groups = {}
        for line in self.kpi_line_ids:
            pillar_groups.setdefault(line.pillar_id.id or False, []).append(line)

        for pillar_id in sorted(
            pillar_groups,
            key=lambda current_id: (
                self.env["hr.evaluation.pillar"].browse(current_id).sequence
                if current_id
                else -1,
                current_id or 0,
            ),
        ):
            scope_lines = self.env["hr.kpi.template.line"].browse(
                [line.id for line in pillar_groups[pillar_id]]
            )
            if not scope_lines:
                continue

            # Dùng helper của line model để lấy đúng flat preorder trong từng tab pillar.
            ordered_ids.extend(
                scope_lines[:1]
                ._get_hierarchy_ordered_lines(scope_lines=scope_lines)
                .ids
            )
        return self.env["hr.kpi.template.line"].browse(ordered_ids)

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"kpi_id": new_parent.id})
        return new_parent
