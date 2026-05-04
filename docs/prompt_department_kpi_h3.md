# Prompt: Phát triển tính năng KPI Phòng Ban (Hướng 3 — Kết hợp)
# Dành cho: GitHub Copilot / Gemini 2.5 Pro
# Module: `custom_adecsol_hr_performance_evaluator` (Odoo 16/17)

---

## 1. BỐI CẢNH VÀ MỤC TIÊU

Bạn đang phát triển thêm tính năng **KPI Phòng Ban** cho module Odoo hiện có tên
`custom_adecsol_hr_performance_evaluator`. Module này đang quản lý KPI **cá nhân**
(employee-level). Nhiệm vụ là thêm KPI **phòng ban** theo "Hướng 3 — Kết hợp":

```
department_score = α × dept_kpi_score + β × avg_individual_score
```

Trong đó:
- `dept_kpi_score`: điểm từ bộ KPI riêng của phòng ban (do trưởng phòng/BGĐ đặt mục tiêu).
- `avg_individual_score`: trung bình `performance_score` của toàn bộ nhân sự trong phòng
  đã được approved trong cùng kỳ.
- `α` + `β` = 1.0, cấu hình được per phòng ban, mặc định `α=0.5, β=0.5`.

---

## 2. CODE HIỆN CÓ — BẮT BUỘC ĐỌC KỸ TRƯỚC KHI VIẾT BẤT CỨ DÒNG NÀO

### 2.1. Abstract model `hr.kpi.engine` (file: `models/hr_kpi_engine.py`)

Đây là engine tính toán KPI tự động. Các pattern quan trọng:

```python
class HrKpiEngine(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _description = 'HR KPI Engine'

    @api.model
    def compute(self, employee, kpi_line, date_from, date_to) -> float:
        """
        Trả về giá trị actual (float) cho một employee + kpi_line.
        - Nếu kpi_line.is_auto=False hoặc data_source='manual' → return 0.0
        - Hiện có 3 data_source: 'task_on_time', 'late_days', 'attendance_full'
        """

    @api.model
    def compute_with_metrics(self, employee, kpi_line, date_from, date_to):
        """
        Returns (value: float, metrics: dict|False)
        Dùng khi cần metadata kèm theo (hiện chỉ 'attendance_full' dùng).
        """

    @api.model
    def _value_or_percentage(self, kpi_line, numerator, denominator) -> float:
        """
        Helper trung tâm xử lý target_type:
        - target_type='value'      → return numerator
        - target_type='percentage' → return (numerator/denominator)*100
        PHẢI dùng helper này cho mọi data source mới, không tự tính.
        """

    @api.model
    def _get_tz(self, employee) -> pytz.timezone:
        """Lấy timezone từ resource_calendar_id.tz > employee.tz > user.tz > UTC"""

    def _get_duration_days_for_date(self, calendar, day_date) -> float:
        """Trả về duration_days theo calendar cho một ngày cụ thể. 0.0 nếu không phải ngày làm."""
```

**Timezone rule quan trọng** (KHÔNG được vi phạm):
- Mọi datetime truyền vào `_get_work_days_data_batch` phải được `tz.localize()` trước.
- KHÔNG dùng `.replace(tzinfo=...)` — phải dùng `tz.localize(naive_dt)`.
- Lý do: nhân viên VN (+7) sẽ bị lệch ngày nếu truyền naive UTC.

**Pattern `compute_leaves=False`** (KHÔNG được vi phạm):
- Tất cả `_get_work_days_data_batch` trong engine đều dùng `compute_leaves=False`.
- Đây là thiết kế chủ ý để giữ cùng hệ quy chiếu (ngày lễ được tách riêng ở bước 4).

### 2.2. Các model cá nhân hiện có (KHÔNG sửa đổi)

| Model | Mục đích | Fields quan trọng |
|---|---|---|
| `hr.kpi` | Template KPI cá nhân | `name`, `period`, `department_id`, `job_id`, `kpi_line_ids` |
| `hr.kpi.line` | Tiêu chí trong template | `kpi_type`, `target`, `target_type`, `direction`, `weight`, `is_auto`, `data_source`, `is_section` |
| `hr.performance.evaluation` | Bản ghi đánh giá cá nhân | `employee_id`, `kpi_id`, `start_date`, `end_date`, `performance_score`, `performance_level`, state machine: Draft→Submitted→Approved→Cancel |
| `hr.performance.evaluation.line` | Dòng đánh giá | `actual`, `system_score`, `final_rating`, `employee_rating_*`, `manager_rating_*` |
| `hr.performance.report` | Hub tạo batch evaluation | Gửi reminder, export Excel |
| `hr.employee` (extension) | Gắn `performance_score` từ latest approved evaluation | — |

**RULE: Không sửa bất kỳ model nào trong danh sách trên.** Chỉ được thêm field mới vào
`hr.department` (xem mục 3.7).

---

## 3. CÁC MODEL CẦN TẠO MỚI

### 3.1. `hr.department.kpi` — Template KPI phòng ban

```python
class HrDepartmentKpi(models.Model):
    _name = 'hr.department.kpi'
    _description = 'Department KPI Template'

    name = fields.Char(required=True)
    department_id = fields.Many2one('hr.department', required=True, ondelete='cascade')
    period = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('biannual', 'Biannual'),
        ('annual', 'Annual'),
    ], required=True)

    # Trọng số kết hợp — phải validate α + β = 1.0
    alpha = fields.Float(
        string='Trọng số KPI riêng (α)',
        default=0.5,
        help='Trọng số cho điểm KPI riêng phòng ban. α + β phải = 1.0'
    )
    beta = fields.Float(
        string='Trọng số TB cá nhân (β)',
        default=0.5,
        help='Trọng số cho trung bình điểm cá nhân. α + β phải = 1.0'
    )

    kpi_line_ids = fields.One2many('hr.department.kpi.line', 'department_kpi_id')

    @api.constrains('alpha', 'beta')
    def _check_weights(self):
        for rec in self:
            if abs(rec.alpha + rec.beta - 1.0) > 1e-6:
                raise ValidationError('α + β phải bằng 1.0')
```

### 3.2. `hr.department.kpi.line` — Tiêu chí trong template phòng ban

Tương tự `hr.kpi.line` nhưng:
- Không có `employee_rating_*` / `manager_rating_*` (không có self-assessment cá nhân).
- Có `is_auto` và `data_source` để kết nối với engine mở rộng.
- `data_source` selection phải bao gồm các giá trị cũ + giá trị mới cho phòng ban:

```python
data_source = fields.Selection([
    ('manual', 'Manual'),
    # Cá nhân (giữ nguyên để tái sử dụng engine):
    ('task_on_time', 'Task on time (cá nhân)'),
    ('late_days', 'Late days (cá nhân)'),
    ('attendance_full', 'Attendance full (cá nhân)'),
    # Phòng ban — MỚI:
    ('dept_task_completion', 'Tỷ lệ hoàn thành task phòng ban'),
    ('dept_attendance_rate', 'Tỷ lệ chuyên cần phòng ban'),
    ('dept_avg_individual', 'TB điểm cá nhân (auto-aggregated)'),
], default='manual')

kpi_type = fields.Selection([
    ('quantitative', 'Quantitative'),
    ('binary', 'Binary'),
    ('rating', 'Rating'),
    ('score', 'Score'),
], required=True)

target = fields.Float()
target_type = fields.Selection([('value', 'Value'), ('percentage', 'Percentage')], default='value')
direction = fields.Selection([('higher', 'Higher is better'), ('lower', 'Lower is better')], default='higher')
weight = fields.Float(default=1.0)
is_auto = fields.Boolean(default=False)
is_section = fields.Boolean(default=False)
department_kpi_id = fields.Many2one('hr.department.kpi', ondelete='cascade')
```

### 3.3. `hr.department.performance.evaluation` — Bản ghi đánh giá phòng ban

State machine: `draft` → `submitted` → `approved` → `cancel`

```python
class HrDepartmentPerformanceEvaluation(models.Model):
    _name = 'hr.department.performance.evaluation'
    _description = 'Department Performance Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(compute='_compute_name', store=True)
    department_id = fields.Many2one('hr.department', required=True)
    department_kpi_id = fields.Many2one('hr.department.kpi', required=True)
    performance_report_id = fields.Many2one('hr.performance.report')

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    deadline = fields.Date()

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True)

    evaluation_line_ids = fields.One2many(
        'hr.department.evaluation.line', 'evaluation_id'
    )

    # Điểm thành phần
    dept_kpi_score = fields.Float(
        compute='_compute_dept_kpi_score', store=True,
        help='Điểm từ KPI riêng phòng ban (trung bình có trọng số các line)'
    )
    avg_individual_score = fields.Float(
        compute='_compute_avg_individual_score', store=True,
        help='TB performance_score của nhân sự đã approved trong kỳ'
    )

    # Điểm tổng hợp cuối cùng
    department_score = fields.Float(
        compute='_compute_department_score', store=True,
        help='α × dept_kpi_score + β × avg_individual_score'
    )
    department_level = fields.Selection([
        ('excellent', 'Excellent'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], compute='_compute_department_level', store=True)
```

**Logic compute quan trọng:**

`_compute_dept_kpi_score`: Trung bình có trọng số `final_score` của tất cả
`evaluation_line_ids` không phải `is_section`, tương tự cách `hr.performance.evaluation`
tính `performance_score`.

`_compute_avg_individual_score`: Tìm tất cả `hr.performance.evaluation` có:
- `state = 'approved'`
- `employee_id.department_id = self.department_id`
- `start_date >= self.start_date` và `end_date <= self.end_date`

Sau đó lấy trung bình `performance_score`.

`_compute_department_score`:
```python
alpha = self.department_kpi_id.alpha
beta = self.department_kpi_id.beta
self.department_score = alpha * self.dept_kpi_score + beta * self.avg_individual_score
```

### 3.4. `hr.department.evaluation.line` — Dòng đánh giá phòng ban

```python
class HrDepartmentEvaluationLine(models.Model):
    _name = 'hr.department.evaluation.line'
    _description = 'Department Evaluation Line'

    evaluation_id = fields.Many2one(
        'hr.department.performance.evaluation', ondelete='cascade'
    )
    department_kpi_line_id = fields.Many2one('hr.department.kpi.line')

    # Copy từ template
    name = fields.Char()
    kpi_type = fields.Selection(...)  # same as hr.department.kpi.line
    target = fields.Float()
    target_type = fields.Selection(...)
    direction = fields.Selection(...)
    weight = fields.Float()
    is_auto = fields.Boolean()
    data_source = fields.Selection(...)
    is_section = fields.Boolean()

    # Actual nhập tay hoặc auto
    actual = fields.Float()

    # Điểm tính toán
    system_score = fields.Float(compute='_compute_system_score', store=True)
    final_score = fields.Float(compute='_compute_final_score', store=True)

    # Manager có thể override
    manager_score_override = fields.Float()
    use_override = fields.Boolean(default=False)
    manager_comment = fields.Text()
```

**Rule tính `system_score`**: Dùng cùng logic với `hr.performance.evaluation.line`:
- `quantitative`: `(actual / target) * 100` nếu `direction=higher`, `(target / actual) * 100` nếu `direction=lower`. Clamp 0–100.
- `binary`: 100 nếu actual >= target, else 0.
- `rating` / `score`: Truyền thẳng actual.

**Rule tính `final_score`**: Nếu `use_override=True` → dùng `manager_score_override`, ngược lại dùng `system_score`.

### 3.5. Mở rộng `hr.kpi.engine` — Thêm data source phòng ban

**QUAN TRỌNG**: Không sửa class `HrKpiEngine` gốc. Tạo một mixin riêng hoặc
extend qua `_inherit`.

```python
class HrKpiEngineDeptExtension(models.AbstractModel):
    _name = 'hr.kpi.engine'          # Kế thừa, không tạo mới
    _inherit = 'hr.kpi.engine'

    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        """
        Entry point mới cho KPI phòng ban. Tương tự compute() nhưng nhận
        department thay vì employee.

        Args:
            department: hr.department recordset
            dept_kpi_line: hr.department.kpi.line recordset
            date_from, date_to: date

        Returns:
            float — giá trị actual
        """
        if not dept_kpi_line.is_auto or (dept_kpi_line.data_source or 'manual') == 'manual':
            return 0.0

        if dept_kpi_line.data_source == 'dept_task_completion':
            return self._compute_dept_task_completion(department, dept_kpi_line, date_from, date_to)
        if dept_kpi_line.data_source == 'dept_attendance_rate':
            return self._compute_dept_attendance_rate(department, dept_kpi_line, date_from, date_to)
        if dept_kpi_line.data_source == 'dept_avg_individual':
            return self._compute_dept_avg_individual(department, dept_kpi_line, date_from, date_to)

        return 0.0

    @api.model
    def _compute_dept_task_completion(self, department, dept_kpi_line, date_from, date_to):
        """
        Tỷ lệ hoàn thành task của toàn bộ nhân sự trong phòng ban.

        Definition:
        - Lấy tất cả user thuộc employees của department trong kỳ.
        - Task: project.task assigned cho bất kỳ user nào trong nhóm đó.
        - Completed on time: stage_id.is_done_stage=True và done_date <= date_deadline.
        - Phạm vi: date_deadline nằm trong [date_from, date_to].

        KHÔNG gọi _compute_task_on_time của từng employee riêng lẻ rồi average —
        vì sẽ bị đếm trùng task assign cho nhiều người.
        Thay vào đó: query thẳng task theo department's user_ids.

        Returns float theo _value_or_percentage().
        """
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', department.id),
            ('active', '=', True),
        ])
        user_ids = employees.mapped('user_id').ids
        if not user_ids:
            return 0.0

        Task = self.env['project.task'].sudo()
        domain = [
            ('user_ids', 'in', user_ids),
            ('stage_id.is_done_stage', '=', True),
            ('date_deadline', '>=', date_from),
            ('date_deadline', '<=', date_to),
            ('project_id', '!=', False),
        ]
        tasks = Task.search(domain)
        if not tasks:
            return 0.0

        on_time = 0
        for t in tasks:
            done_dt_utc = fields.Datetime.to_datetime(t.done_date) if t.done_date else False
            deadline_dt_utc = fields.Datetime.to_datetime(t.date_deadline) if t.date_deadline else False
            if not done_dt_utc or not deadline_dt_utc:
                continue
            done_local = fields.Datetime.context_timestamp(self, done_dt_utc)
            deadline_local = fields.Datetime.context_timestamp(self, deadline_dt_utc)
            if done_local <= deadline_local:
                on_time += 1

        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=on_time,
            denominator=len(tasks),
        )

    @api.model
    def _compute_dept_attendance_rate(self, department, dept_kpi_line, date_from, date_to):
        """
        Tỷ lệ chuyên cần trung bình của phòng ban.

        Formula:
            dept_attendance_rate = mean(worked_days_i / expected_work_days_i)
            với i là từng employee trong phòng có calendar.

        Cách thực hiện:
        1. Lấy danh sách employees active của department.
        2. Với mỗi employee có resource_calendar_id:
           a. Gọi _compute_attendance_full_with_metrics() (đã có sẵn trong engine).
           b. Lấy metrics['worked_days'] / metrics['expected_work_days'].
        3. Average tất cả tỷ lệ đó.

        KHÔNG gọi _compute_attendance_full_with_metrics() với kpi_line của phòng ban —
        method đó nhận employee-level kpi_line. Thay vào đó, mock một kpi_line tạm thời
        với target_type='percentage' để get đúng output, hoặc tính thủ công từ metrics dict.

        Tốt nhất: tính thủ công từ metrics dict, không mock kpi_line.

        Returns float: tỷ lệ % (0–100) hoặc raw nếu target_type='value'.
        """
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', department.id),
            ('active', '=', True),
            ('resource_calendar_id', '!=', False),
        ])
        if not employees:
            return 0.0

        rates = []
        for emp in employees:
            # Tìm kpi_line cá nhân giả để truyền vào engine.
            # Trick: tạo dict-like object không phải recordset.
            # ĐỪNG làm vậy — thay vào đó extract metrics trực tiếp.
            #
            # Cách đúng: gọi _compute_attendance_full_with_metrics với
            # một hr.kpi.line bất kỳ có data_source='attendance_full',
            # hoặc tái dùng logic nội bộ.
            #
            # Cách an toàn nhất: gọi thẳng _compute_attendance_full_with_metrics
            # với một kpi_line stub — xem note bên dưới.
            pass

        # NOTE: _compute_attendance_full_with_metrics nhận kpi_line để biết
        # target_type. Với dept_attendance_rate ta cần tự tính rate thủ công
        # để không phụ thuộc vào kpi_line cá nhân.
        # Implement bằng cách copy logic bước 1+2 của _compute_attendance_full_with_metrics
        # (expected_raw và worked_days), sau đó tính rate = worked/expected.
        # Chỉ copy HAI bước đó, không copy toàn bộ method.

        if not rates:
            return 0.0

        avg_rate = sum(rates) / len(rates)  # 0.0–1.0
        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=avg_rate * 100,  # convert to percentage trước
            denominator=100,
        )

    @api.model
    def _compute_dept_avg_individual(self, department, dept_kpi_line, date_from, date_to):
        """
        Trung bình performance_score cá nhân của nhân sự đã approved trong kỳ.

        Definition:
        - Lấy hr.performance.evaluation với:
            state = 'approved'
            employee_id.department_id = department.id
            start_date >= date_from AND end_date <= date_to
        - Average performance_score.

        Returns float: avg score (0–100) nếu target_type='value',
                       hoặc ratio nếu target_type='percentage'.
        """
        evals = self.env['hr.performance.evaluation'].sudo().search([
            ('state', '=', 'approved'),
            ('employee_id.department_id', '=', department.id),
            ('start_date', '>=', date_from),
            ('end_date', '<=', date_to),
        ])
        if not evals:
            return 0.0

        scores = evals.mapped('performance_score')
        avg = sum(scores) / len(scores)

        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=avg,
            denominator=100,
        )
```

### 3.6. Mở rộng `hr.performance.report` — Thêm batch tạo department evaluation

```python
class HrPerformanceReport(models.Model):
    _inherit = 'hr.performance.report'

    dept_evaluation_ids = fields.One2many(
        'hr.department.performance.evaluation', 'performance_report_id',
        string='Department Evaluations'
    )

    def action_generate_department_evaluations(self):
        """
        Với mỗi department có department_kpi_id phù hợp với period của report:
        1. Kiểm tra đã tồn tại dept evaluation chưa (tránh duplicate).
        2. Tạo hr.department.performance.evaluation.
        3. Populate evaluation_line_ids từ department_kpi_id.kpi_line_ids.
        4. Nếu line.is_auto=True → gọi compute_for_department() để điền actual.
        """
```

### 3.7. Mở rộng `hr.department` — Thêm latest score

```python
class HrDepartment(models.Model):
    _inherit = 'hr.department'

    department_score = fields.Float(
        compute='_compute_department_score',
        string='Điểm KPI phòng ban (kỳ gần nhất)',
    )
    department_level = fields.Selection(
        [('excellent', 'Excellent'), ('pass', 'Pass'), ('fail', 'Fail')],
        compute='_compute_department_score',
    )

    def _compute_department_score(self):
        """
        Lấy hr.department.performance.evaluation gần nhất (state='approved',
        sorted by end_date desc) của từng department.
        Gán department_score và department_level từ bản ghi đó.
        Nếu không có → 0.0 và False.
        """
```

---

## 4. CẤU TRÚC FILE — ĐẶT CODE VÀO ĐÂY

```
custom_adecsol_hr_performance_evaluator/
├── models/
│   ├── hr_kpi_engine.py                        ← KHÔNG sửa
│   ├── hr_kpi_engine_dept_ext.py               ← TẠO MỚI (mở rộng engine)
│   ├── hr_department_kpi.py                    ← TẠO MỚI (model 3.1 + 3.2)
│   ├── hr_department_performance_evaluation.py ← TẠO MỚI (model 3.3 + 3.4)
│   ├── hr_performance_report.py                ← SỬA (thêm dept_evaluation_ids)
│   └── hr_department.py                        ← TẠO MỚI (mở rộng hr.department)
├── views/
│   ├── hr_department_kpi_views.xml             ← TẠO MỚI
│   └── hr_department_performance_views.xml     ← TẠO MỚI
└── __manifest__.py                             ← Cập nhật depends và data
```

---

## 5. CONSTRAINTS VÀ RULES KHÔNG ĐƯỢC VI PHẠM

### 5.1. Về Odoo ORM

- **Luôn dùng `sudo()` khi query cross-model** (hr.leave, hr.attendance, project.task).
- **`@api.depends` phải khai báo đầy đủ** cho mọi `compute` field có `store=True`.
  Nếu thiếu, Odoo sẽ không recompute khi data thay đổi.
- **Không dùng raw SQL** trừ khi không thể tránh, và phải có comment giải thích lý do.
- **`ondelete='cascade'` hoặc `'restrict'`** phải xác định rõ trên mọi Many2one.

### 5.2. Về timezone (CRITICAL — đây là bug thường gặp nhất)

```python
# ✅ ĐÚNG
import pytz
tz = pytz.timezone('Asia/Ho_Chi_Minh')
naive_local = datetime.datetime.combine(d_from, datetime.time.min)
dt_local = tz.localize(naive_local)  # có timezone

# ❌ SAI — gây lệch ngày
dt_wrong = naive_local.replace(tzinfo=tz)

# ❌ SAI — truyền naive vào _get_work_days_data_batch
employee._get_work_days_data_batch(naive_local, naive_end, compute_leaves=False)
```

### 5.3. Về `compute_leaves=False`

Mọi nơi gọi `_get_work_days_data_batch` trong engine PHẢI dùng `compute_leaves=False`.
Không được đổi thành `True` dù có vẻ "đơn giản hơn" — sẽ làm sai toàn bộ phép tính.

### 5.4. Về tính điểm phòng ban

- `dept_kpi_score` chỉ tính từ các line có `is_section=False`.
- `avg_individual_score` chỉ lấy evaluation có `state='approved'`, không lấy `draft`/`submitted`.
- `department_score = alpha * dept_kpi_score + beta * avg_individual_score` — không làm
  tròn trước khi lưu, chỉ làm tròn khi hiển thị trên view.

### 5.5. Về backward compatibility

- Không thay đổi signature bất kỳ method nào trong `hr.kpi.engine` gốc.
- Method mới `compute_for_department()` là entry point riêng biệt, không merge vào `compute()`.

---

## 6. THỨ TỰ VIẾT CODE (quan trọng — viết đúng thứ tự để tránh import error)

1. `hr_department_kpi.py` — model cơ sở, không phụ thuộc gì mới.
2. `hr_department_performance_evaluation.py` — phụ thuộc model 3.1 + 3.2.
3. `hr_kpi_engine_dept_ext.py` — phụ thuộc model 3.3 + 3.4 (để query evaluation).
4. `hr_performance_report.py` — phụ thuộc tất cả trên.
5. `hr_department.py` — phụ thuộc model 3.3.
6. Views XML.
7. Cập nhật `__manifest__.py`.

---

## 7. CHECKLIST SAU KHI VIẾT XONG

Trước khi submit code, tự kiểm tra:

- [ ] `alpha + beta = 1.0` được validate bằng `@api.constrains`.
- [ ] `_compute_dept_kpi_score` có `@api.depends('evaluation_line_ids.final_score')`.
- [ ] `_compute_avg_individual_score` có `@api.depends('department_id', 'start_date', 'end_date')`.
- [ ] `_compute_department_score` có `@api.depends('dept_kpi_score', 'avg_individual_score', 'department_kpi_id.alpha', 'department_kpi_id.beta')`.
- [ ] Mọi `_get_work_days_data_batch` đều dùng `compute_leaves=False` và datetime đã localize.
- [ ] Không có raw SQL không có comment giải thích.
- [ ] `hr.department.performance.evaluation` có `_inherit = ['mail.thread', 'mail.activity.mixin']` để hỗ trợ chatter/log.
- [ ] File `__manifest__.py` đã thêm đủ các file model mới vào `'data'` và `'depends'`.

---

## 8. NHỮNG GÌ KHÔNG CẦN LÀM (để tránh scope creep)

- Không cần tạo wizard riêng — dùng button action trực tiếp trên form.
- Không cần report PDF cho phòng ban — đã có Excel từ `hr.performance.report`.
- Không cần portal view — chỉ internal users.
- Không cần gamification/badge cho phòng ban.
- Không cần API endpoint — tất cả qua ORM.
