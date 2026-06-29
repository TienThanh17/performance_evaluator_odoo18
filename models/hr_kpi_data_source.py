import logging
import re
import unicodedata

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import safe_eval as safe_eval_tools
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)
SAFE_AST = safe_eval_tools.wrap_module(__import__("ast"), ["literal_eval"])


class HrKpiDataSource(models.Model):
    _name = "hr.kpi.data.source"
    _description = "KPI Data Source"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Unique technical code, no accents, no spaces. E.g. task_ontime_rate",
        copy=False,
    )
    unit_id = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="set null",
        help="Default unit code to assign to KPI line when this data source is selected.",
    )
    active = fields.Boolean(default=True)
    source_type = fields.Selection(
        [
            ("domain", "Domain builder"),
            ("python", "Python code"),
            ("system", "System"),
        ],
        required=True,
        default="domain",
    )
    description = fields.Text()

    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    model_name = fields.Char(
        related="model_id.model", string="Data Model", store=False
    )

    aggregation = fields.Selection(
        [
            ("count", "Record Count"),
            ("ratio", "Ratio"),
            ("sum", "Sum"),
            ("avg", "Average"),
        ],
        default="count",
    )
    user_field_id = fields.Many2one(
        "ir.model.fields",
        string="Allocation Field (User/Employee)",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['many2one', 'many2many']), ('relation', 'in', ['res.users', 'hr.employee'])]",
        help="Select the data field used to determine who this KPI belongs to.",
    )
    domain_numerator = fields.Char(default="[]")
    domain_denominator = fields.Char(default="[]")
    sum_avg_field_id = fields.Many2one(
        "ir.model.fields",
        string="Calculation Field (Sum/Avg)",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['integer', 'float', 'monetary'])]",
        options="{'no_create': True}",
        help="Select a numeric field (Integer, Float, Monetary) to perform sum or average calculations.",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields",
        string="Date Filter Field",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['date', 'datetime'])]",
        options="{'no_create': True}",
        help="Select a date field (Date or Datetime) to match with the KPI Evaluation Period.",
    )

    python_code = fields.Text(
        default=(
            "# Available: env, employee, start_date, end_date\n"
            "# Assign the numeric result to `result`\n\n"
            "result = 0.0\n"
        )
    )

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "Mã kỹ thuật phải duy nhất."),
    ]

    # Chuẩn hóa text tự do thành technical code kiểu snake_case không dấu.
    @api.model
    def _slugify_code_value(self, value):
        # Chuẩn hóa input về text an toàn trước khi xử lý bỏ dấu và ký tự đặc biệt.
        normalized_value = (value or "").strip()
        if not normalized_value:
            return ""

        # Xử lý riêng chữ đ/Đ của tiếng Việt trước khi normalize Unicode.
        normalized_value = normalized_value.replace("Đ", "D").replace("đ", "d")

        # Bỏ dấu, chuyển về ASCII và hạ chữ thường để tạo technical code ổn định.
        ascii_value = unicodedata.normalize("NFKD", normalized_value)
        ascii_value = ascii_value.encode("ascii", "ignore").decode("ascii")
        ascii_value = ascii_value.lower()

        # Thay mọi cụm ký tự không phải chữ/số bằng underscore và loại bỏ underscore thừa.
        slug_value = re.sub(r"[^a-z0-9]+", "_", ascii_value)
        return slug_value.strip("_")

    # Tạo technical code duy nhất từ một base code để tránh đụng unique constraint.
    @api.model
    def _ensure_unique_code(self, base_code, exclude_id=False):
        # Nếu base code rỗng thì dùng prefix mặc định để người dùng vẫn có mã hợp lệ.
        normalized_code = (base_code or "").strip() or "data_source"
        candidate_code = normalized_code
        suffix = 2

        # Bỏ qua chính record hiện tại khi đang sửa để không tự xem là bị trùng mã.
        domain = [("code", "=", candidate_code)]
        if exclude_id:
            domain.append(("id", "!=", exclude_id))

        while self.search_count(domain):
            candidate_code = "%s_%s" % (normalized_code, suffix)
            suffix += 1
            domain = [("code", "=", candidate_code)]
            if exclude_id:
                domain.append(("id", "!=", exclude_id))

        return candidate_code

    # Tạo technical code mới khi duplicate để không bị trống hoặc đụng unique constraint.
    def _generate_copy_code(self, base_code):
        self.ensure_one()

        # Chuẩn hóa code gốc; nếu bản gốc thiếu code thì dùng prefix an toàn cho bản sao.
        normalized_code = (base_code or "").strip() or "data_source"
        candidate_code = "%s_copy" % normalized_code
        suffix = 2

        # Tăng hậu tố đến khi tìm được code chưa tồn tại trong model hiện tại.
        while self.search_count([("code", "=", candidate_code)]):
            candidate_code = "%s_copy_%s" % (normalized_code, suffix)
            suffix += 1

        return candidate_code

    # Sinh technical code từ field name để người dùng không phải nhập tay.
    def action_generate_code_from_name(self):
        for rec in self:
            # Chặn sớm trường hợp chưa có tên để tránh tạo ra mã mặc định ngoài ý muốn.
            if not (rec.name or "").strip():
                raise UserError(_("Please enter a name before generating the code."))

            # Chuẩn hóa tên sang snake_case rồi ép uniqueness trên chính model này.
            generated_code = rec._slugify_code_value(rec.name)
            rec.code = rec._ensure_unique_code(generated_code, exclude_id=rec.id)

    # Bổ sung code tự động từ name khi caller lưu record mà chưa nhập code.
    @api.model
    def _prepare_auto_generated_code_vals(self, vals, current_record=False):
        normalized_vals = dict(vals or {})
        incoming_code = (normalized_vals.get("code") or "").strip()
        current_code = ((current_record and current_record.code) or "").strip()
        effective_name = normalized_vals.get(
            "name",
            current_record.name if current_record else False,
        )

        # Chỉ tự sinh khi caller chưa truyền code, record hiện tại cũng chưa có code,
        # và đã có name để suy ra technical code.
        if incoming_code or current_code or not (effective_name or "").strip():
            return normalized_vals

        # Tạo code từ name và ép uniqueness theo record hiện tại nếu là write.
        generated_code = self._slugify_code_value(effective_name)
        normalized_vals["code"] = self._ensure_unique_code(
            generated_code,
            exclude_id=current_record.id if current_record else False,
        )
        return normalized_vals

    # Tự sinh code trước khi create để form vẫn lưu được dù người dùng bỏ trống field code.
    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = [
            self._prepare_auto_generated_code_vals(vals) for vals in (vals_list or [])
        ]
        return super().create(prepared_vals_list)

    # Tự sinh code khi write nếu record hiện tại đang rỗng code và người dùng chỉ cập nhật name/field khác.
    def write(self, vals):
        # Nếu caller đã truyền code rõ ràng thì giữ nguyên ý định của họ.
        if (vals.get("code") or "").strip():
            return super().write(vals)

        # Mỗi record có name/code hiện tại khác nhau nên cần chuẩn hóa riêng trước khi ghi.
        for rec in self:
            normalized_vals = rec._prepare_auto_generated_code_vals(
                vals, current_record=rec
            )
            super(HrKpiDataSource, rec).write(normalized_vals)
        return True

    @api.constrains("code")
    def _check_code_format(self):
        for rec in self:
            code = (rec.code or "").strip()
            if not code:
                continue
            if " " in code:
                raise ValidationError(_("Mã kỹ thuật không được chứa khoảng trắng."))

    @api.constrains("aggregation", "sum_avg_field_id")
    def _check_sum_avg_field_required(self):
        for record in self:
            if record.aggregation in ["sum", "avg"] and not record.sum_avg_field_id:
                raise ValidationError(
                    _(
                        "Bạn bắt buộc phải chọn 'Trường tính toán (Sum/Avg)' khi phương pháp tính toán là 'Tổng' hoặc 'Trung bình'."
                    )
                )

    @api.constrains("source_type", "model_id")
    def _check_domain_source_requires_model(self):
        for record in self:
            if record.source_type == "domain" and not record.model_id:
                raise ValidationError(
                    _("Nguồn dữ liệu kiểu Domain bắt buộc phải chọn Model.")
                )

    def get_unit_id(self):
        self.ensure_one()
        return (self.unit_id.name or "").strip() or False

    # Duplicate data source và tự cấp code mới để bản sao luôn hợp lệ.
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})

        # Giữ hành vi đặt tên mặc định của Odoo, nhưng luôn ép code sang giá trị mới duy nhất.
        default["code"] = self._generate_copy_code(default.get("code") or self.code)
        return super().copy(default)

    def action_test_execute(self):
        self.ensure_one()
        employee = self.env.user.employee_id
        if not employee:
            raise UserError(_("Người dùng hiện tại chưa được liên kết với nhân viên."))
        today = fields.Date.today()
        result = self.execute(employee, today, today)
        raise UserError(_("Kết quả chạy thử: %s") % result)

    def execute(self, employee, start_date, end_date, department=False, line=False):
        self.ensure_one()
        if self.source_type == "domain":
            return self._execute_domain(
                employee, start_date, end_date, department=department
            )
        if self.source_type == "python":
            return self._execute_python(
                employee,
                start_date,
                end_date,
                department=department,
                line=line,
            )
        return 0.0

    def _build_scope_domain(self, employee, department=False):
        if not self.user_field_id:
            return []

        field_name = self.user_field_id.name
        relation = self.user_field_id.relation
        field_type = self.user_field_id.ttype

        if department:
            employees = (
                self.env["hr.employee"]
                .sudo()
                .search([("department_id", "=", department.id), ("active", "=", True)])
            )
            # Lấy list ID tùy thuộc vào trường đó trỏ tới Users hay Employees
            target_ids = (
                employees.ids
                if relation == "hr.employee"
                else employees.mapped("user_id").ids
            )

            if field_type == "many2many":
                return [(field_name, "in", target_ids)]
            else:  # many2one
                return [(field_name, "in", target_ids)]

        # Chạy cho 1 nhân viên cụ thể
        target_id = employee.id if relation == "hr.employee" else (employee.user_id.id)

        if field_type == "many2many":
            return [(field_name, "in", [target_id])]
        else:  # many2one
            return [(field_name, "=", target_id)]

    def _safe_parse_domain(self, raw_domain_str, start_date, end_date):
        raw = raw_domain_str or "[]"
        filled = raw.format(start_date=str(start_date), end_date=str(end_date))
        try:
            domain = safe_eval(filled)
        except Exception as err:
            raise UserError(
                _("Domain không hợp lệ cho nguồn dữ liệu '%s': %s") % (self.name, err)
            )
        if not isinstance(domain, list):
            raise UserError(_("Domain phải là một list Odoo hợp lệ."))
        return domain

    def _build_date_domain(self, start_date, end_date):
        """Hàm bổ sung để tạo domain lọc theo thời gian"""
        if not self.date_field_id:
            return []

        date_field_name = self.date_field_id.name

        # Lọc các bản ghi có ngày nằm trong khoảng từ start_date đến end_date
        return [(date_field_name, ">=", start_date), (date_field_name, "<=", end_date)]

    def _build_domain(
        self, raw_domain_str, employee, start_date, end_date, department=False
    ):
        domain = self._safe_parse_domain(raw_domain_str, start_date, end_date)
        scope_domain = self._build_scope_domain(employee, department=department)
        date_domain = self._build_date_domain(start_date, end_date)

        return scope_domain + domain + date_domain

    def _execute_domain(self, employee, start_date, end_date, department=False):
        Model = self.env.get(self.model_name)
        if Model is None:
            raise UserError(_("Model '%s' không tồn tại.") % (self.model_name or ""))

        domain_num = self._build_domain(
            self.domain_numerator, employee, start_date, end_date, department=department
        )
        if self.aggregation == "count":
            return float(Model.search_count(domain_num))

        if self.aggregation == "ratio":
            domain_den = self._build_domain(
                self.domain_denominator,
                employee,
                start_date,
                end_date,
                department=department,
            )
            numerator = Model.search_count(domain_num)
            denominator = Model.search_count(domain_den)
            return round((numerator / denominator) * 100.0, 2) if denominator else 0.0

        if self.aggregation in ("sum", "avg"):
            if not self.sum_avg_field_id:
                return 0.0
            records = Model.search(domain_num)
            values = [
                val
                for val in records.mapped(self.sum_avg_field_id)
                if val not in (False, None)
            ]
            if not values:
                return 0.0
            total = float(sum(values))
            if self.aggregation == "sum":
                return round(total, 2)
            return round(total / len(values), 2)

        return 0.0

    def _validate_python_code_safety(self):
        self.ensure_one()
        code = self.python_code or ""
        lowered = code.lower()
        blocked_tokens = [
            ".write(",
            ".create(",
            ".unlink(",
            ".sudo(",
            "__import__",
            "import ",
            "open(",
            "exec(",
            "eval(",
        ]
        for token in blocked_tokens:
            if token in lowered:
                raise UserError(
                    _("Python source '%(name)s' contains blocked token: %(token)s")
                    % {"name": self.name, "token": token}
                )

    def _execute_python(
        self, employee, start_date, end_date, department=False, line=False
    ):
        self._validate_python_code_safety()
        local_vars = {
            "env": self.env,
            "employee": employee,
            "department": department,
            "line": line,
            "start_date": start_date,
            "end_date": end_date,
            "result": 0.0,
            "json": safe_eval_tools.json,
            "ast": SAFE_AST,
        }
        try:
            safe_eval(
                self.python_code or "result = 0.0",
                locals_dict=local_vars,
                mode="exec",
                nocopy=True,
            )
        except Exception as err:
            _logger.warning("KPI Python source '%s' failed: %s", self.code, err)
            raise UserError(_("Python source '%s' failed: %s") % (self.name, err))
        return float(local_vars.get("result", 0.0) or 0.0)
