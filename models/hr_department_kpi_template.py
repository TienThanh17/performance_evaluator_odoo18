from odoo import api, fields, models


class HrDepartmentKpiTemplate(models.Model):
    _name = "hr.department.kpi.template"
    _description = "Department KPI Template"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    department_id = fields.Many2one("hr.department", ondelete="cascade")
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
    kpi_line_ids = fields.One2many(
        "hr.department.kpi.template.line", "department_kpi_id"
    )

    # Khai báo các field chứa tên động của từng Pillar
    pillar_p3_dept_name = fields.Char(compute="_compute_dynamic_pillar_names")

    def _compute_dynamic_pillar_names(self):
        pillars = self.env['hr.evaluation.pillar'].sudo().search([
            ('code', 'in', ['p3_department'])
        ])
        self.pillar_p3_dept_name = pillars.name or ""

    # Validate normalized 3P weights once on the final x2many state of each template.
    def _validate_kpi_line_weight_batch(self):
        # Gom toàn bộ line còn lại của các template hiện tại để validator kiểm tra
        # trên trạng thái cuối cùng sau khi batch command đã chạy xong.
        line_records = self.mapped("kpi_line_ids")
        if line_records:
            line_records._validate_normalized_3p_weight_structure()

    # Dời normalized 3P validation lên parent create để child line không validate
    # giữa chừng khi form tạo mới gửi nhiều one2many commands cùng lúc.
    @api.model_create_multi
    def create(self, vals_list):
        # Nếu caller đã chủ động skip validate hoặc create không đụng kpi_line_ids
        # thì giữ nguyên flow mặc định để tránh thêm overhead không cần thiết.
        if self.env.context.get("skip_normalized_3p_weight_validation") or not any(
            "kpi_line_ids" in vals for vals in vals_list
        ):
            return super().create(vals_list)

        # Tạm bỏ qua validate ở child line để Odoo xử lý trọn bộ command list trước.
        records = super(
            HrDepartmentKpiTemplate,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).create(vals_list)

        # Chỉ validate một lần trên trạng thái cuối cùng của từng template vừa tạo.
        records._validate_kpi_line_weight_batch()
        return records

    # Dời normalized 3P validation lên parent write để child write/unlink không
    # validate giữa chừng khi một lần save vừa update vừa delete line.
    def write(self, vals):
        # Các batch không chạm kpi_line_ids hoặc đã được caller bọc context skip
        # thì tiếp tục dùng flow mặc định.
        if "kpi_line_ids" not in vals or self.env.context.get(
            "skip_normalized_3p_weight_validation"
        ):
            return super().write(vals)

        # Tạm bỏ qua validate ở child line để Odoo hoàn tất toàn bộ one2many
        # commands, bao gồm cả write/unlink chạy nối tiếp trong cùng transaction.
        res = super(
            HrDepartmentKpiTemplate,
            self.with_context(skip_normalized_3p_weight_validation=True),
        ).write(vals)

        # Sau khi command list hoàn tất, validate đúng trên trạng thái cuối.
        self._validate_kpi_line_weight_batch()
        return res

    # Trả về department KPI lines theo flat preorder để các màn generate giữ đúng cây template.
    def get_hierarchy_ordered_lines(self):
        self.ensure_one()
        if not self.kpi_line_ids:
            return self.env["hr.department.kpi.template.line"]

        # Tái sử dụng helper ở line model để giữ nguyên thứ tự root, child và grandchild.
        return self.kpi_line_ids[:1]._get_hierarchy_ordered_lines(
            scope_lines=self.kpi_line_ids
        )

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")
        new_parent = super().copy(default)
        for line in self.kpi_line_ids:
            line.copy({"department_kpi_id": new_parent.id})
        return new_parent
