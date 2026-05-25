# Codex Refactor Plan — KPI Module Dynamic Architecture
## Module: `custom_adecsol_hr_performance_evaluator` — Odoo 18

---

## Mục tiêu tổng thể

Refactor module KPI từ kiến trúc single-tenant cứng sang kiến trúc đa khách hàng động.
Không được phá vỡ luồng nghiệp vụ: self_evaluation → manager_evaluating → completed.

---

## Constraint bất biến — KHÔNG được thay đổi

- Tên module: `custom_adecsol_hr_performance_evaluator`
- Odoo version: 18
- State machine phiếu: `self_evaluation` → `manager_evaluating` → `completed` | `cancel`
- Công thức blending: `final_score = dept_kpi_score * dept_weight + performance_score * individual_weight`
- Bottom-up aggregation: `child_kpi_average` vẫn là giá trị hợp lệ cho `dept_source_type`
- Security groups: `group_employee`, `group_manager`, `group_hr`, `group_admin`

---

## Mapping model cũ → mới

| Model cũ | Model mới | Ghi chú |
|---|---|---|
| `hr.kpi` | `hr.kpi.template` | Đổi tên, giữ nguyên logic |
| `hr.kpi.line` | `hr.kpi.template.line` | Đổi tên, bổ sung fields mới |
| `hr.department.kpi` | `hr.department.kpi.template` | Đổi tên, bổ sung `period_id`, `scoring_profile_id` |
| `hr.department.kpi.line` | `hr.department.kpi.template.line` | Đổi tên, bổ sung `formula_type`, `step_table_json` |
| `hr.performance.evaluation` | Giữ nguyên tên | Bổ sung `period_id` FK |
| `hr.performance.evaluation.line` | Giữ nguyên tên | Bổ sung `data_source_id` |
| `hr.department.performance.evaluation` | Giữ nguyên tên | Bổ sung `period_id` FK |
| `hr.department.evaluation.line` | Giữ nguyên tên | Không đổi |
| `hr.performance.report` | Giữ nguyên tên | Bổ sung `period_id` FK |
| _(mới)_ | `hr.kpi.period` | Model mới hoàn toàn |
| _(mới)_ | `hr.kpi.scoring.profile` | Model mới hoàn toàn |
| _(mới)_ | `hr.kpi.data.source` | Thay thế `data_source` selection field |
| `hr.kpi.unit` | Giữ nguyên tên | Không đổi |

---

## PHASE 1 — Thêm model cấu hình mới (không phá cũ)

### Task 1.1 — Tạo `hr.kpi.period`

**File:** `models/hr_kpi_period.py`

```python
class HrKpiPeriod(models.Model):
    _name = 'hr.kpi.period'
    _description = 'KPI Period'
    _order = 'date_start desc'

    name = fields.Char(required=True)
    period_type = fields.Selection([
        ('monthly', 'Hàng tháng'),
        ('quarterly', 'Hàng quý'),
        ('biannual', 'Nửa năm'),
        ('yearly', 'Hàng năm'),
        ('custom', 'Tuỳ chỉnh'),
    ], required=True, default='monthly')
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('date_check', 'CHECK(date_end >= date_start)',
         'Ngày kết thúc phải sau ngày bắt đầu'),
    ]
```

**View:** Form + List view tại menu `Configuration > KPI Periods`.
**Access:** HR/Admin CRUD, Employee/Manager read-only.

---

### Task 1.2 — Tạo `hr.kpi.scoring.profile`

**File:** `models/hr_kpi_scoring_profile.py`

```python
class HrKpiScoringProfile(models.Model):
    _name = 'hr.kpi.scoring.profile'
    _description = 'KPI Scoring Profile'

    name = fields.Char(required=True)
    threshold_excellent = fields.Float(default=8.5, digits=(5, 2))
    threshold_pass = fields.Float(default=6.0, digits=(5, 2))
    active = fields.Boolean(default=True)

    # Computed: số template đang dùng profile này
    template_count = fields.Integer(compute='_compute_template_count')
```

**View:** Form + List tại `Configuration > Scoring Profiles`.
**Access:** HR/Admin CRUD.
**Lưu ý:** Settings global `kpi_threshold_excellent` và `kpi_threshold_pass` giữ nguyên
làm fallback khi template không chỉ định profile.

---

### Task 1.3 — Tạo `hr.kpi.data.source`

Đây là model quan trọng nhất của phase này.

**File:** `models/hr_kpi_data_source.py`

#### 1.3a — Model fields

```python
class HrKpiDataSource(models.Model):
    _name = 'hr.kpi.data.source'
    _description = 'KPI Data Source'

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        help="Mã kỹ thuật duy nhất, không dấu, không space. VD: task_ontime_rate"
    )
    active = fields.Boolean(default=True)
    source_type = fields.Selection([
        ('domain', 'Domain builder (no-code)'),
        ('python', 'Python code'),
    ], required=True, default='domain')
    description = fields.Text(help="Mô tả ngắn hiển thị khi HR chọn nguồn dữ liệu")

    # ── Domain mode fields ──────────────────────────────────────────────────
    model_name = fields.Char(
        string="Model dữ liệu",
        help="Tên kỹ thuật của model Odoo. VD: project.task, hr.attendance"
    )
    aggregation = fields.Selection([
        ('count',  'Đếm số bản ghi'),
        ('ratio',  'Tỷ lệ (tử / mẫu × 100)'),
        ('sum',    'Tổng một field số'),
        ('avg',    'Trung bình một field số'),
    ], default='count')
    employee_scope = fields.Selection([
        ('user_ids',         'Được giao cho (user_ids contains)'),
        ('user_id',          'Người phụ trách (user_id =)'),
        ('create_uid',       'Người tạo (create_uid =)'),
        ('hr_responsible_id','HR responsible'),
    ], default='user_ids',
       help="Cách lọc bản ghi theo nhân viên. Engine tự inject employee.user_id.id")

    # Domain cho tử số (hoặc domain duy nhất nếu agg=count/sum/avg)
    # Lưu dạng string "[]" — widget="domain" trong view
    # Placeholder {start_date} và {end_date} được engine thay trước khi eval
    domain_numerator = fields.Char(
        default='[]',
        help="Domain Odoo chuẩn. Dùng '{start_date}' và '{end_date}' làm placeholder."
    )
    # Domain cho mẫu số — chỉ dùng khi aggregation = 'ratio'
    domain_denominator = fields.Char(
        default='[]',
        help="Domain mẫu số. Chỉ áp dụng khi phép tính là Tỷ lệ."
    )
    # Field để sum/avg — chỉ dùng khi aggregation = 'sum' hoặc 'avg'
    sum_avg_field = fields.Char(
        help="Tên field số để tính tổng/trung bình. VD: amount_total, qty_done"
    )

    # ── Python mode fields ──────────────────────────────────────────────────
    python_code = fields.Text(
        default="""# Biến sẵn có: env, employee, start_date, end_date
# Gán kết quả vào biến 'result' (kiểu float)
# Chỉ được đọc dữ liệu, không được ghi (write/create/unlink/sudo bị chặn)

result = 0.0
""",
        help="Python code. Gán kết quả vào biến 'result'."
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã kỹ thuật phải duy nhất'),
    ]
```

#### 1.3b — Method compute trong engine

Thêm vào `hr.kpi.engine` (hoặc trong chính model `hr.kpi.data.source`):

```python
def execute(self, employee, start_date, end_date):
    """Thực thi data source, trả về giá trị float."""
    self.ensure_one()
    if self.source_type == 'domain':
        return self._execute_domain(employee, start_date, end_date)
    elif self.source_type == 'python':
        return self._execute_python(employee, start_date, end_date)
    return 0.0

def _execute_domain(self, employee, start_date, end_date):
    """Thực thi domain source."""
    Model = self.env.get(self.model_name)
    if not Model:
        raise UserError(f"Model '{self.model_name}' không tồn tại.")

    fmt = {
        'start_date': str(start_date),
        'end_date': str(end_date),
    }

    def build_domain(raw_domain_str, employee):
        """Parse domain string, inject employee filter và placeholder."""
        from odoo.tools.safe_eval import safe_eval
        # Thay placeholder string
        filled = raw_domain_str.format(**fmt) if raw_domain_str else '[]'
        domain = safe_eval(filled)
        # Inject employee scope
        scope_map = {
            'user_ids': ('user_ids', 'in', [employee.user_id.id]),
            'user_id':  ('user_id',  '=',  employee.user_id.id),
            'create_uid': ('create_uid', '=', employee.user_id.id),
            'hr_responsible_id': ('hr_responsible_id', '=', employee.id),
        }
        if self.employee_scope and self.employee_scope in scope_map:
            domain = [scope_map[self.employee_scope]] + domain
        return domain

    if self.aggregation == 'count':
        domain = build_domain(self.domain_numerator, employee)
        return float(Model.search_count(domain))

    elif self.aggregation == 'ratio':
        domain_num = build_domain(self.domain_numerator, employee)
        domain_den = build_domain(self.domain_denominator, employee)
        num = Model.search_count(domain_num)
        den = Model.search_count(domain_den)
        return round((num / den * 100), 2) if den else 0.0

    elif self.aggregation in ('sum', 'avg'):
        if not self.sum_avg_field:
            return 0.0
        domain = build_domain(self.domain_numerator, employee)
        records = Model.search(domain)
        vals = [v for v in records.mapped(self.sum_avg_field) if v is not False]
        if not vals:
            return 0.0
        return round(sum(vals), 2) if self.aggregation == 'sum' \
            else round(sum(vals) / len(vals), 2)

    return 0.0

def _execute_python(self, employee, start_date, end_date):
    """Thực thi python code trong sandbox."""
    from odoo.tools.safe_eval import safe_eval

    # Whitelist globals — KHÔNG cho phép import, write, sudo
    local_vars = {
        'env': self.env,
        'employee': employee,
        'start_date': start_date,
        'end_date': end_date,
        'result': 0.0,
    }
    safe_eval(
        self.python_code or 'result = 0.0',
        local_vars,
        mode='exec',
        nocopy=True,
        timeout=10,
    )
    return float(local_vars.get('result', 0.0))
```

#### 1.3c — View `hr.kpi.data.source`

Form view phải dùng `attrs` để show/hide field theo `source_type` và `aggregation`:

```xml
<form>
  <sheet>
    <group>
      <field name="name"/>
      <field name="code"/>
      <field name="source_type" widget="radio"/>
      <field name="description"/>
    </group>

    <!-- Domain mode -->
    <group attrs="{'invisible': [('source_type','!=','domain')]}">
      <field name="model_name"
             placeholder="project.task"
             help="Nhập tên kỹ thuật model Odoo"/>
      <field name="aggregation"/>
      <field name="employee_scope"/>
    </group>

    <group attrs="{'invisible': [('source_type','!=','domain')]}">
      <!-- Tử số luôn hiển thị khi domain mode -->
      <field name="domain_numerator"
             widget="domain"
             options="{'model': 'model_name'}"
             attrs="{'invisible': [('model_name','=',False)]}"/>

      <!-- Mẫu số chỉ hiển thị khi agg = ratio -->
      <field name="domain_denominator"
             widget="domain"
             options="{'model': 'model_name'}"
             attrs="{'invisible': ['|',('model_name','=',False),('aggregation','!=','ratio')]}"/>

      <!-- Field sum/avg chỉ hiển thị khi agg = sum/avg -->
      <field name="sum_avg_field"
             attrs="{'invisible': [('aggregation','not in',['sum','avg'])]}"/>
    </group>

    <!-- Python mode -->
    <group attrs="{'invisible': [('source_type','!=','python')]}">
      <div class="alert alert-warning">
        Chế độ này dành cho IT/Developer. Code chạy trong sandbox readonly.
        Biến sẵn có: <code>env</code>, <code>employee</code>,
        <code>start_date</code>, <code>end_date</code>.
        Gán kết quả vào <code>result</code>.
      </div>
      <field name="python_code" widget="ace" options="{'mode': 'python'}"/>
    </group>

    <!-- Test button -->
    <footer>
      <button name="action_test_execute" type="object"
              string="Chạy thử" class="btn-secondary"
              attrs="{'invisible': [('model_name','=',False),('source_type','=','domain')]}"/>
    </footer>
  </sheet>
</form>
```

**Lưu ý widget `domain`:** `options="{'model': 'model_name'}"` — giá trị là **tên field** chứa model name (không phải model name trực tiếp). Widget tự gọi `fields_get` của model đó để build filter builder.

#### 1.3d — Placeholder trong domain_numerator

Widget `domain` của Odoo **không cho phép** nhập string tự do như `{start_date}` trực tiếp trong filter builder vì nó validate kiểu dữ liệu. Giải pháp:

- HR dùng filter builder cho các điều kiện cố định (stage, tag, loại...).
- Điều kiện date range theo kỳ **KHÔNG nhập qua widget domain** mà được engine **tự động inject** dựa trên `employee_scope` và `date_field` config:

Bổ sung thêm 2 fields vào model:

```python
date_field_start = fields.Char(
    default='date_deadline',
    help="Tên field ngày để lọc bắt đầu kỳ. VD: date_deadline, date, check_in"
)
date_field_end = fields.Char(
    default='date_deadline',
    help="Tên field ngày để lọc kết thúc kỳ."
)
```

Engine tự thêm `[(date_field_start, '>=', start_date), (date_field_end, '<=', end_date)]`
vào domain trước khi `search_count` — HR không cần tự thêm điều kiện ngày, tránh nhầm lẫn.

---

## PHASE 2 — Refactor Template models

### Task 2.1 — Rename `hr.kpi` → `hr.kpi.template`

**File cũ:** `models/hr_kpi.py` → **File mới:** `models/hr_kpi_template.py`

Thay đổi:
- `_name = 'hr.kpi.template'`
- `_inherit` thêm `mail.thread` nếu chưa có
- Bổ sung fields:
  ```python
  period_id = fields.Many2one('hr.kpi.period', string='Kỳ KPI')
  scoring_profile_id = fields.Many2one('hr.kpi.scoring.profile')
  ```
- Giữ nguyên tất cả fields cũ: `department_id`, `job_id`, `department_kpi_id`, `kpi_line_ids`

**Migration:** Tạo `migrations/18.0.2.0.0/pre-migrate.py`:
```python
def migrate(cr, version):
    # Rename table
    cr.execute("ALTER TABLE hr_kpi RENAME TO hr_kpi_template")
    # Cập nhật ir.model, ir.model.fields references
    cr.execute("""
        UPDATE ir_model SET model = 'hr.kpi.template'
        WHERE model = 'hr.kpi'
    """)
    cr.execute("""
        UPDATE ir_model_fields SET model = 'hr.kpi.template', model_id = (
            SELECT id FROM ir_model WHERE model = 'hr.kpi.template'
        )
        WHERE model = 'hr.kpi'
    """)
```

### Task 2.2 — Rename `hr.kpi.line` → `hr.kpi.template.line`

**File cũ:** `models/hr_kpi_line.py` → **File mới:** `models/hr_kpi_template_line.py`

Thay đổi:
- `_name = 'hr.kpi.template.line'`
- Bổ sung fields:
  ```python
  data_source_id = fields.Many2one(
      'hr.kpi.data.source',
      string='Nguồn dữ liệu',
      help="Thay thế data_source selection cũ"
  )
  formula_type = fields.Selection([
      ('linear',     'Tuyến tính (mặc định)'),
      ('step_table', 'Bảng bậc thang'),
      ('lower_zero', 'Trừ điểm (lower_better từ 10)'),
  ], default='linear')
  step_table_json = fields.Text(
      help='JSON: [{"from": 0, "to": 50, "score": 0}, {"from": 50, "to": 80, "score": 5}, ...]'
  )
  ```
- Giữ `data_source` selection cũ với `deprecated=True` trong 1 version để migration data.
- Field `is_auto` vẫn giữ nguyên — khi `data_source_id` được set thì `is_auto = True` tự động.

**Logic scoring mới trong engine:** Khi tính `system_score` cho dòng `quantitative`:
```python
def _compute_system_score(self, line, actual, target, direction):
    formula = getattr(line, 'formula_type', 'linear')

    if formula == 'step_table' and line.step_table_json:
        import json
        table = json.loads(line.step_table_json)
        for row in sorted(table, key=lambda r: r['from']):
            if row['from'] <= actual < row['to']:
                return float(row['score'])
        return 0.0

    elif formula == 'lower_zero':
        # Dùng cho late_days: 10 - actual, min 0
        return max(10.0 - actual, 0.0)

    else:  # linear (mặc định)
        if not target:
            return 0.0
        if direction == 'higher_better':
            return min((actual / target) * 10, 10.0)
        else:
            return min((target / actual) * 10, 10.0) if actual else 10.0
```

### Task 2.3 — Rename `hr.department.kpi` → `hr.department.kpi.template`

**File cũ:** `models/hr_department_kpi.py`

Thay đổi:
- `_name = 'hr.department.kpi.template'`
- Bổ sung fields:
  ```python
  period_id = fields.Many2one('hr.kpi.period')
  scoring_profile_id = fields.Many2one('hr.kpi.scoring.profile')
  ```
- Giữ `dept_weight` và `individual_weight` (KHÔNG tạo `blending.component`).
- Giữ `kpi_line_ids` O2M.

### Task 2.4 — Rename `hr.department.kpi.line` → `hr.department.kpi.template.line`

Bổ sung:
```python
formula_type = fields.Selection([...])  # như task 2.2
step_table_json = fields.Text()
dept_source_type = fields.Selection([
    ('manual',            'Nhập thủ công'),
    ('child_kpi_average', 'Trung bình từ KPI nhân viên'),
    ('data_source',       'Nguồn dữ liệu tự động'),
], default='manual')
data_source_id = fields.Many2one('hr.kpi.data.source')
```

---

## PHASE 3 — Bổ sung `period_id` vào Evaluation models

### Task 3.1 — Thêm `period_id` vào `hr.performance.evaluation`

```python
period_id = fields.Many2one(
    'hr.kpi.period',
    string='Kỳ KPI',
    compute='_compute_period_id',
    store=True,
    readonly=False,
)

@api.depends('kpi_template_id.period_id')
def _compute_period_id(self):
    for rec in self:
        rec.period_id = rec.kpi_template_id.period_id
```

Tương tự thêm vào `hr.department.performance.evaluation` và `hr.performance.report`.

### Task 3.2 — Thêm `data_source_id` vào `hr.performance.evaluation.line`

```python
data_source_id = fields.Many2one(
    'hr.kpi.data.source',
    related='kpi_line_id.data_source_id',
    store=True,
)
```

---

## PHASE 4 — Refactor `hr.kpi.engine`

### Task 4.1 — Thay selection hardcode bằng `data_source_id`

**Trước (cũ):**
```python
if line.data_source == 'done_task':
    actual = self._compute_done_task(...)
elif line.data_source == 'task_on_time':
    actual = self._compute_task_on_time(...)
elif line.data_source == 'late_days':
    actual = self._compute_late_days(...)
elif line.data_source == 'attendance_full':
    actual = self._compute_attendance_full(...)
```

**Sau (mới):**
```python
def _compute_actual_for_line(self, line, employee, start_date, end_date):
    source = line.data_source_id
    if not source:
        return 0.0
    try:
        return source.execute(employee, start_date, end_date)
    except Exception as e:
        _logger.warning("KPI source '%s' failed for employee %s: %s",
                        source.code, employee.name, e)
        return 0.0
```

### Task 4.2 — Seed data source builtin

### Task 4.3 — Migration data source cũ sang mới

Tạo `migrations/18.0.2.0.0/post-migrate.py`:

```python
def migrate(cr, version):
    """Map giá trị data_source selection cũ sang data_source_id FK mới."""
    mapping = {
        'done_task':       'source_done_task',
        'task_on_time':    'source_task_on_time',
        'late_days':       'source_late_days',
        'attendance_full': 'source_attendance_full',
    }
    for old_val, xml_id in mapping.items():
        cr.execute("""
            UPDATE hr_kpi_template_line tl
            SET data_source_id = (
                SELECT res_id FROM ir_model_data
                WHERE module = 'custom_adecsol_hr_performance_evaluator'
                  AND name = %s
            )
            WHERE tl.data_source = %s
              AND tl.data_source_id IS NULL
        """, (xml_id, old_val))
        # Tương tự cho hr_department_kpi_template_line
        cr.execute("""
            UPDATE hr_department_kpi_template_line
            SET data_source_id = (
                SELECT res_id FROM ir_model_data
                WHERE module = 'custom_adecsol_hr_performance_evaluator'
                  AND name = %s
            )
            WHERE data_source = %s
              AND data_source_id IS NULL
        """, (xml_id, old_val))
```

---

## PHASE 5 — Thêm `dashboard.widget` model độc lập

### Task 5.1 — Tạo `hr.kpi.dashboard.widget`

**File:** `models/hr_kpi_dashboard_widget.py`

```python
class HrKpiDashboardWidget(models.Model):
    _name = 'hr.kpi.dashboard.widget'
    _description = 'KPI Dashboard Widget'
    _order = 'sequence'

    name = fields.Char(required=True)
    widget_type = fields.Selection([
        ('score_card',   'Thẻ điểm'),
        ('bar_chart',    'Biểu đồ cột'),
        ('radar_chart',  'Biểu đồ radar'),
        ('trend_line',   'Đường xu hướng'),
        ('kpi_tree',     'Cây KPI'),
        ('distribution', 'Phân phối điểm'),
    ], required=True)
    scope = fields.Selection([
        ('company',    'Toàn công ty'),
        ('department', 'Theo phòng ban'),
        ('personal',   'Cá nhân'),
    ], required=True, default='company')
    measure_field = fields.Char(default='final_score')
    filter_domain = fields.Char(default='[]')
    group_by = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
```

**Lưu ý:** Widget này là config — OWL component dashboard đọc danh sách widget active
rồi render tương ứng. Không FK vào dept_template.

---

## PHASE 6 — Cập nhật `__manifest__.py` và file structure

### Task 6.1 — Cập nhật `__manifest__.py`

```python
'version': '18.0.2.0.0',  # bump version
'data': [
    # Security
    'security/ir.model.access.csv',
    'security/record_rules.xml',
    # Config models (load trước)
    'views/hr_kpi_period_views.xml',
    'views/hr_kpi_scoring_profile_views.xml',
    'views/hr_kpi_data_source_views.xml',
    'views/hr_kpi_dashboard_widget_views.xml',
    # Template models
    'views/hr_kpi_template_views.xml',
    'views/hr_department_kpi_template_views.xml',
    # Evaluation models
    'views/hr_performance_evaluation_views.xml',
    'views/hr_department_performance_evaluation_views.xml',
    'views/hr_performance_report_views.xml',
    # Data
    'data/hr_kpi_unit_data.xml',
    'data/hr_kpi_scoring_profile_data.xml',   # profile mặc định
    'data/hr_kpi_data_source_data.xml',        # 4 source builtin
    # Wizard
    'wizard/hr_department_kpi_generate_wizard_views.xml',
],
```

### Task 6.2 — Cập nhật menu `Configuration`

Thêm vào menu Configuration:
- KPI Periods (`hr.kpi.period`)
- Scoring Profiles (`hr.kpi.scoring.profile`)
- Data Sources (`hr.kpi.data.source`)
- Dashboard Widgets (`hr.kpi.dashboard.widget`)

---

## PHASE 7 — Tests

### Task 7.1 — Test `hr.kpi.data.source`

```python
class TestKpiDataSource(TransactionCase):

    def test_domain_count_source(self):
        """Domain source aggregation=count trả đúng số lượng."""
        ...

    def test_domain_ratio_source(self):
        """Ratio source trả % đúng khi có num và den."""
        ...

    def test_domain_ratio_zero_denominator(self):
        """Ratio trả 0.0 khi mẫu số = 0, không raise ZeroDivisionError."""
        ...

    def test_python_source_basic(self):
        """Python source với code đơn giản trả đúng result."""
        ...

    def test_python_source_sandbox_blocked(self):
        """Python source không được phép gọi env.write()."""
        with self.assertRaises(Exception):
            source = self.env['hr.kpi.data.source'].create({
                'name': 'Evil', 'code': 'evil', 'source_type': 'python',
                'python_code': "env['hr.employee'].search([])[0].write({'name': 'hacked'})"
            })
            source.execute(self.employee, self.start, self.end)

    def test_employee_scope_injection(self):
        """Engine tự inject employee_id vào domain, không lấy data của người khác."""
        ...
```

---

## Thứ tự thực hiện cho Codex

Feed từng phase theo thứ tự. Sau mỗi phase chạy:

```bash
# Kiểm tra syntax
python -m py_compile models/*.py

# Upgrade module
odoo-bin -d <db> -u custom_adecsol_hr_performance_evaluator --stop-after-init --log-level=warn

# Chạy test phase vừa xong
odoo-bin -d <db> --test-enable --stop-after-init -u custom_adecsol_hr_performance_evaluator \
  --test-tags /custom_adecsol_hr_performance_evaluator
```

**Không gộp nhiều phase vào 1 lần commit** — mỗi phase phải pass test trước khi sang phase tiếp theo.

---

## Checklist trước khi merge

- [ ] `python -m py_compile` pass toàn bộ models/
- [ ] Upgrade không có WARNING về deprecated fields
- [ ] 4 source builtin (`done_task`, `task_on_time`, `late_days`, `attendance_full`) hoạt động đúng như cũ
- [ ] Domain widget hiển thị đúng field list khi HR chọn model
- [ ] Python sandbox chặn write/create/unlink
- [ ] Record rules security không bị phá vỡ
