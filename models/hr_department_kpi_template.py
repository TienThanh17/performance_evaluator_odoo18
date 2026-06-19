from odoo import _, api, fields, models


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
    employee_template_count = fields.Integer(
        compute="_compute_employee_template_count",
        string="Employee Template Count",
    )

    # Khai báo các field chứa tên động của từng Pillar
    pillar_p3_dept_name = fields.Char(compute="_compute_dynamic_pillar_names")
    total_weight_p3_department = fields.Float(
        compute="_compute_total_weight_by_pillar",
        string="P3 Department Total Weight",
        store=False,
    )

    # Đếm số employee KPI template cùng phòng ban để hiển thị trên smart button.
    @api.depends("department_id")
    def _compute_employee_template_count(self):
        department_ids = self.mapped("department_id").ids
        counts_by_department = {}

        # Gom số lượng theo phòng ban một lần để tránh query lặp cho từng record.
        if department_ids:
            grouped_data = self.env["hr.kpi.template"].read_group(
                [("department_id", "in", department_ids)],
                ["department_id"],
                ["department_id"],
            )
            counts_by_department = {
                group["department_id"][0]: group["department_id_count"]
                for group in grouped_data
                if group.get("department_id")
            }

        for rec in self:
            # Nếu chưa gán phòng ban thì không có employee template liên kết để mở.
            rec.employee_template_count = counts_by_department.get(rec.department_id.id, 0)

    def _compute_dynamic_pillar_names(self):
        pillars = self.env['hr.evaluation.pillar'].sudo().search([
            ('code', 'in', ['p3_department'])
        ])
        self.pillar_p3_dept_name = pillars.name or ""

    # Tính tổng weight top-level của pillar phòng ban để UI hiển thị tổng phân bổ hiện tại.
    @api.depends("kpi_line_ids.weight", "kpi_line_ids.parent_line_id")
    def _compute_total_weight_by_pillar(self):
        for rec in self:
            # Chỉ cộng các line top-level để tránh cộng trùng subtree của section phòng ban.
            root_lines = rec.kpi_line_ids.filtered(lambda line: not line.parent_line_id)
            rec.total_weight_p3_department = sum(root_lines.mapped("weight"))

    # Mở danh sách employee KPI template cùng phòng ban; nếu chỉ có một record thì mở thẳng form.
    def action_open_employee_templates(self):
        self.ensure_one()

        # Chỉ lấy các employee template dùng chung department với department template hiện tại.
        domain = [("department_id", "=", self.department_id.id)] if self.department_id else []
        employee_templates = self.env["hr.kpi.template"].search(domain)

        # Tái sử dụng action chuẩn của employee template để giữ nguyên list/form view hiện có.
        action = self.env.ref(
            "custom_adecsol_hr_performance_evaluator.hr_kpi_action"
        ).read()[0]
        action["domain"] = domain
        action["context"] = {
            "default_department_id": self.department_id.id if self.department_id else False,
        }

        # Nếu chỉ có một bản mẫu thì điều hướng thẳng sang form thay vì đi qua list.
        if len(employee_templates) == 1:
            action["view_mode"] = "form"
            action["res_id"] = employee_templates.id

        return action

    # Đồng bộ weight section một lần trên trạng thái x2many cuối cùng của template.
    def _validate_kpi_line_weight_batch(self):
        # Gom toàn bộ line còn lại của các template hiện tại để validator kiểm tra
        # trên trạng thái cuối cùng sau khi batch command đã chạy xong.
        line_records = self.mapped("kpi_line_ids")
        if line_records:
            line_records._refresh_weight_structure()

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

        # Chỉ refresh weight một lần trên trạng thái cuối cùng của từng template vừa tạo.
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

        # Sau khi command list hoàn tất, refresh đúng trên trạng thái cuối.
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

    # Duplicate the department KPI template and rebuild its line tree on the new record.
    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault("name", self.name + " (Copy)")

        # Create the new parent first so copied lines can point to a real template.
        new_parent = super().copy(default)

        # Copy lines in preorder so every parent exists before its children.
        source_lines = self.get_hierarchy_ordered_lines()
        line_model = self.env["hr.department.kpi.template.line"].with_context(
            skip_hierarchy_sequence_sync=True,
            skip_normalized_3p_weight_validation=True,
        )
        copied_lines = self.env["hr.department.kpi.template.line"]
        line_map = {}

        for source_line in source_lines:
            # Reuse the source values, but remap the parent line to the duplicated tree.
            line_vals = source_line.copy_data()[0]
            line_vals["department_kpi_id"] = new_parent.id
            line_vals["parent_line_id"] = line_map.get(
                source_line.parent_line_id.id, False
            )

            copied_line = line_model.create(line_vals)
            line_map[source_line.id] = copied_line.id
            copied_lines |= copied_line

        # Đồng bộ lại weight section của cây copy sau khi toàn bộ node đã tồn tại.
        if copied_lines:
            copied_lines._refresh_weight_structure()
        return new_parent
