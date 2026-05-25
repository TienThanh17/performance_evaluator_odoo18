# Codex Task — Triển khai `hr.kpi.scoring.formula`
## Module: `custom_adecsol_hr_performance_evaluator` — Odoo 18

---

## Bối cảnh

Module hiện tại đang hardcode `formula_type` selection trực tiếp trên
`hr.kpi.template.line` và `hr.department.kpi.template.line`:

```python
formula_type = fields.Selection(
    [
        ("linear",     "Tuyến tính"),
        ("step_table", "Bảng bậc thang"),
        ("lower_zero", "Trừ điểm"),
    ],
    default="linear",
    required=True,
)
step_table_json = fields.Text()
```

Logic tính điểm nằm trong engine, đọc `formula_type` rồi switch case.

**Yêu cầu:** Tách công thức tính điểm thành model riêng `hr.kpi.scoring.formula`
để HR có thể tạo, tái sử dụng và tuỳ chỉnh công thức trên giao diện mà không cần dev.

---

## Constraint bất biến — KHÔNG được thay đổi

- Thang điểm KHÔNG hardcode `10` — luôn gọi `self.get_score_scale_base()`
  để lấy max score (có thể là 10 hoặc 100 tuỳ cấu hình hệ thống).
- Không xoá `formula_type` và `step_table_json` trên line ngay — giữ lại
  với `deprecated=True` và migrate data sang `scoring_formula_id` trong cùng task này.
- Không thay đổi state machine phiếu đánh giá.
- Không thay đổi logic bottom-up aggregation.
- `hr.kpi.scoring.formula` là global — dùng chung toàn hệ thống,
  không giới hạn theo department hay template.

---

## TASK 1 — Tạo model `hr.kpi.scoring.formula`

**File mới:** `models/hr_kpi_scoring_formula.py`

### 1.1 Fields

```python
class HrKpiScoringFormula(models.Model):
    _name = 'hr.kpi.scoring.formula'
    _description = 'KPI Scoring Formula'
    _order = 'sequence, name'

    name        = fields.Char(required=True)
    sequence    = fields.Integer(default=10)
    active      = fields.Boolean(default=True)
    description = fields.Text()

    formula_type = fields.Selection([
        ('linear',     'Tuyến tính'),
        ('step_table', 'Bảng bậc thang'),
        ('penalty',    'Trừ điểm'),
        ('expression', 'Biểu thức tuỳ chỉnh'),
    ], required=True, default='linear')

    # ── linear ────────────────────────────────────────────────────────────
    # direction: higher_better → score tăng khi actual tăng
    #            lower_better  → score tăng khi actual giảm
    linear_direction = fields.Selection([
        ('higher_better', 'Càng cao càng tốt'),
        ('lower_better',  'Càng thấp càng tốt'),
    ], default='higher_better')

    # Cho phép điểm vượt max_score khi actual > target không?
    # False → cap tại get_score_scale_base()
    # True  → tính thực tế, có thể > max_score (bonus)
    linear_allow_exceed = fields.Boolean(
        default=False,
        string='Cho phép vượt điểm tối đa (bonus)'
    )

    # ── step_table ────────────────────────────────────────────────────────
    # JSON schema:
    # [
    #   {"from": 0,   "to": 50,   "score": 0},
    #   {"from": 50,  "to": 80,   "score": 5},
    #   {"from": 80,  "to": 100,  "score": 8},
    #   {"from": 100, "to": null, "score": 10}
    # ]
    # "to": null = không giới hạn trên (≥ from)
    # Các bậc KHÔNG cần liên tục — khoảng trống xử lý theo step_out_of_range
    step_table_json = fields.Text(default='[]')

    step_out_of_range = fields.Selection([
        ('zero',    'Trả về 0 điểm'),
        ('nearest', 'Lấy điểm của bậc gần nhất'),
    ], default='zero', required=True,
       string='Xử lý ngoài bảng',
       help="Áp dụng khi actual không nằm trong bất kỳ bậc nào đã định nghĩa.")

    # ── penalty ───────────────────────────────────────────────────────────
    # Công thức: max(base_score - actual * deduct_per_unit, floor)
    penalty_base_score    = fields.Float(default=10.0,
        string='Điểm ban đầu',
        help="Điểm xuất phát. Thường = get_score_scale_base()."
    )
    penalty_deduct_per_unit = fields.Float(default=1.0,
        string='Điểm trừ mỗi đơn vị vi phạm'
    )
    penalty_floor         = fields.Float(default=0.0,
        string='Điểm tối thiểu (sàn)'
    )

    # ── expression ────────────────────────────────────────────────────────
    # Biến được phép dùng: actual, target, max_score
    # max_score được inject = get_score_scale_base() tại runtime
    # Engine dùng safe_eval với whitelist, timeout 5s
    # KHÔNG được dùng: env, self, import, open, exec, eval
    expression_code = fields.Char(
        string='Biểu thức',
        help=(
            "Biểu thức Python một dòng. Biến dùng được: actual, target, max_score.\n"
            "Ví dụ: min(actual / target * max_score, max_score) if target else 0"
        )
    )

    # ── computed preview ──────────────────────────────────────────────────
    # Hiển thị biểu thức tổng hợp (readonly) để IT review
    preview_expression = fields.Char(
        compute='_compute_preview_expression',
        string='Biểu thức tổng hợp',
        store=False,
    )

    # Đếm số KPI line đang dùng formula này
    kpi_line_count = fields.Integer(compute='_compute_kpi_line_count')
```

### 1.2 Constraints & validation

```python
@api.constrains('formula_type', 'step_table_json')
def _check_step_table(self):
    """Validate step_table_json khi formula_type = step_table."""
    import json
    for rec in self:
        if rec.formula_type != 'step_table':
            continue
        if not rec.step_table_json:
            raise ValidationError("Bảng bậc thang không được để trống.")
        try:
            steps = json.loads(rec.step_table_json)
        except (json.JSONDecodeError, TypeError):
            raise ValidationError("step_table_json không phải JSON hợp lệ.")
        if not isinstance(steps, list) or len(steps) == 0:
            raise ValidationError("Bảng bậc thang phải có ít nhất 1 bậc.")
        for i, step in enumerate(steps):
            if not all(k in step for k in ('from', 'to', 'score')):
                raise ValidationError(
                    f"Bậc thang {i+1} thiếu key 'from', 'to' hoặc 'score'."
                )
            if step['to'] is not None and step['to'] <= step['from']:
                raise ValidationError(
                    f"Bậc thang {i+1}: 'to' phải lớn hơn 'from'."
                )

@api.constrains('formula_type', 'expression_code')
def _check_expression(self):
    """Validate expression_code khi formula_type = expression."""
    BLOCKED = ['env', 'self', 'import', 'open', 'exec', '__']
    for rec in self:
        if rec.formula_type != 'expression':
            continue
        if not rec.expression_code:
            raise ValidationError("Biểu thức không được để trống.")
        expr = rec.expression_code
        for blocked in BLOCKED:
            if blocked in expr:
                raise ValidationError(
                    f"Biểu thức không được chứa '{blocked}'."
                )
        # Test parse syntax
        try:
            compile(expr, '<kpi_expr>', 'eval')
        except SyntaxError as e:
            raise ValidationError(f"Cú pháp biểu thức không hợp lệ: {e}")

```

### 1.3 Method compute_score — core logic

```python
def compute_score(self, actual, target):
    """
    Tính điểm từ actual và target.

    Args:
        actual (float): Giá trị thực tế.
        target (float): Giá trị mục tiêu.

    Returns:
        float: Điểm trong khoảng [0, max_score] (trừ khi linear_allow_exceed=True).
    """
    self.ensure_one()
    max_score = self.get_score_scale_base()

    if self.formula_type == 'linear':
        return self._score_linear(actual, target, max_score)
    elif self.formula_type == 'step_table':
        return self._score_step_table(actual, max_score)
    elif self.formula_type == 'penalty':
        return self._score_penalty(actual)
    elif self.formula_type == 'expression':
        return self._score_expression(actual, target, max_score)
    return 0.0

def _score_linear(self, actual, target, max_score):
    if not target:
        return 0.0
    if self.linear_direction == 'higher_better':
        score = (actual / target) * max_score
    else:
        score = (target / actual) * max_score if actual else max_score
    if not self.linear_allow_exceed:
        score = min(score, max_score)
    return round(max(score, 0.0), 4)

def _score_step_table(self, actual, max_score):
    import json
    try:
        steps = json.loads(self.step_table_json or '[]')
    except Exception:
        return 0.0

    # Tìm bậc chứa actual
    matched = None
    for step in steps:
        low  = step.get('from', 0)
        high = step.get('to')   # None = không giới hạn trên
        if high is None:
            if actual >= low:
                matched = step
                break
        else:
            if low <= actual < high:
                matched = step
                break

    if matched:
        return round(float(matched['score']), 4)

    # Xử lý out-of-range
    if self.step_out_of_range == 'zero':
        return 0.0
    elif self.step_out_of_range == 'nearest':
        if not steps:
            return 0.0
        # Tìm bậc gần nhất theo midpoint
        def midpoint(s):
            lo = s.get('from', 0)
            hi = s.get('to') or (lo + 1)
            return (lo + hi) / 2
        nearest = min(steps, key=lambda s: abs(midpoint(s) - actual))
        return round(float(nearest['score']), 4)
    return 0.0

def _score_penalty(self, actual):
    score = self.penalty_base_score - (actual * self.penalty_deduct_per_unit)
    return round(max(score, self.penalty_floor), 4)

def _score_expression(self, actual, target, max_score):
    from odoo.tools.safe_eval import safe_eval
    local_vars = {
        'actual':    actual,
        'target':    target,
        'max_score': max_score,
        # Math helpers an toàn
        'min': min, 'max': max, 'abs': abs, 'round': round,
    }
    try:
        result = safe_eval(self.expression_code or '0', local_vars)
        return round(float(result), 4)
    except Exception as e:
        _logger.warning(
            "KPI expression '%s' failed: %s | actual=%s target=%s",
            self.expression_code, e, actual, target
        )
        return 0.0
```

### 1.4 Method preview & count

```python
@api.depends('formula_type', 'linear_direction', 'linear_allow_exceed',
             'penalty_base_score', 'penalty_deduct_per_unit', 'penalty_floor',
             'expression_code')
def _compute_preview_expression(self):
    for rec in self:
        scale = 'max_score'
        if rec.formula_type == 'linear':
            if rec.linear_direction == 'higher_better':
                expr = f"actual / target * {scale}"
            else:
                expr = f"target / actual * {scale}"
            if not rec.linear_allow_exceed:
                expr = f"min({expr}, {scale})"
            rec.preview_expression = expr
        elif rec.formula_type == 'step_table':
            rec.preview_expression = "lookup(actual, step_table)"
        elif rec.formula_type == 'penalty':
            rec.preview_expression = (
                f"max({rec.penalty_base_score} "
                f"- actual × {rec.penalty_deduct_per_unit}, "
                f"{rec.penalty_floor})"
            )
        elif rec.formula_type == 'expression':
            rec.preview_expression = rec.expression_code or ''
        else:
            rec.preview_expression = ''

def _compute_kpi_line_count(self):
    """Đếm tổng số KPI line (template + dept) đang dùng formula này."""
    for rec in self:
        count_tpl = self.env['hr.kpi.template.line'].search_count(
            [('scoring_formula_id', '=', rec.id)]
        )
        count_dept = self.env['hr.department.kpi.template.line'].search_count(
            [('scoring_formula_id', '=', rec.id)]
        )
        rec.kpi_line_count = count_tpl + count_dept

# Test execute button (dùng trong form view)
def action_test_formula(self):
    """Wizard test formula với actual/target nhập tay."""
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window',
        'res_model': 'hr.kpi.scoring.formula.test.wizard',
        'view_mode': 'form',
        'target': 'new',
        'context': {'default_formula_id': self.id},
    }
```

---

## TASK 2 — Wizard test formula

**File mới:** `wizard/hr_kpi_scoring_formula_test_wizard.py`

```python
class HrKpiScoringFormulaTestWizard(models.TransientModel):
    _name = 'hr.kpi.scoring.formula.test.wizard'
    _description = 'Test KPI Scoring Formula'

    formula_id = fields.Many2one('hr.kpi.scoring.formula', required=True)
    test_actual = fields.Float(string='Actual (thử nghiệm)', default=80.0)
    test_target = fields.Float(string='Target (thử nghiệm)', default=100.0)
    test_result = fields.Float(string='Kết quả điểm', readonly=True)
    result_computed = fields.Boolean(default=False)

    def action_compute(self):
        self.ensure_one()
        self.test_result = self.formula_id.compute_score(
            self.test_actual, self.test_target
        )
        self.result_computed = True
        # Giữ wizard mở để HR có thể thử nhiều giá trị
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
```

**View wizard:** Form đơn giản với 2 input + nút "Tính điểm" + hiển thị kết quả lớn.
Kết quả hiển thị có màu: xanh nếu ≥ `threshold_pass`, đỏ nếu dưới.

---

## TASK 3 — Seed data builtin formulas

**File:** `data/hr_kpi_scoring_formula_data.xml`

```xml
<!-- 1. Tuyến tính — càng cao càng tốt (capped) -->
<record id="formula_linear_higher" model="hr.kpi.scoring.formula">
    <field name="name">Tuyến tính — Càng cao càng tốt</field>
    <field name="sequence">1</field>
    <field name="formula_type">linear</field>
    <field name="linear_direction">higher_better</field>
    <field name="linear_allow_exceed">False</field>
    
    <field name="description">
        actual / target × max_score, tối đa max_score.
        Dùng cho: doanh thu, số task, tỷ lệ hoàn thành.
    </field>
</record>

<!-- 2. Tuyến tính — càng thấp càng tốt (capped) -->
<record id="formula_linear_lower" model="hr.kpi.scoring.formula">
    <field name="name">Tuyến tính — Càng thấp càng tốt</field>
    <field name="sequence">2</field>
    <field name="formula_type">linear</field>
    <field name="linear_direction">lower_better</field>
    <field name="linear_allow_exceed">False</field>
    
    <field name="description">
        target / actual × max_score, tối đa max_score.
        Dùng cho: tỷ lệ lỗi, chi phí, thời gian xử lý.
    </field>
</record>

<!-- 3. Tuyến tính — vượt target được bonus -->
<record id="formula_linear_higher_bonus" model="hr.kpi.scoring.formula">
    <field name="name">Tuyến tính — Có bonus khi vượt target</field>
    <field name="sequence">3</field>
    <field name="formula_type">linear</field>
    <field name="linear_direction">higher_better</field>
    <field name="linear_allow_exceed">True</field>
    
    <field name="description">
        actual / target × max_score, KHÔNG giới hạn trên.
        Dùng cho: Sales KPI muốn khuyến khích vượt chỉ tiêu.
    </field>
</record>

<!-- 4. Trừ điểm — 1 điểm/đơn vị vi phạm -->
<record id="formula_penalty_1pt" model="hr.kpi.scoring.formula">
    <field name="name">Trừ điểm — 1 điểm/đơn vị</field>
    <field name="sequence">10</field>
    <field name="formula_type">penalty</field>
    <field name="penalty_base_score">10.0</field>
    <field name="penalty_deduct_per_unit">1.0</field>
    <field name="penalty_floor">0.0</field>
    
    <field name="description">
        Bắt đầu từ 10, trừ 1 điểm mỗi đơn vị vi phạm, tối thiểu 0.
        Dùng cho: đi muộn (số ngày), số lần vi phạm kỷ luật.
    </field>
</record>

<!-- 5. Trừ điểm — 2 điểm/đơn vị vi phạm -->
<record id="formula_penalty_2pt" model="hr.kpi.scoring.formula">
    <field name="name">Trừ điểm — 2 điểm/đơn vị</field>
    <field name="sequence">11</field>
    <field name="formula_type">penalty</field>
    <field name="penalty_base_score">10.0</field>
    <field name="penalty_deduct_per_unit">2.0</field>
    <field name="penalty_floor">0.0</field>
    
    <field name="description">
        Bắt đầu từ 10, trừ 2 điểm mỗi đơn vị vi phạm. Nghiêm khắc hơn.
    </field>
</record>
```

---

## TASK 4 — Gắn `scoring_formula_id` vào KPI line

### 4.1 Thêm field vào `hr.kpi.template.line`

```python
scoring_formula_id = fields.Many2one(
    'hr.kpi.scoring.formula',
    string='Công thức tính điểm',
    ondelete='restrict',
    help="Để trống = dùng formula builtin mặc định theo formula_type cũ."
)
```

**Quy tắc fallback khi `scoring_formula_id` trống:**
Engine tìm builtin formula tương ứng `formula_type` cũ:
- `linear` + `higher_better` → `formula_linear_higher`
- `linear` + `lower_better`  → `formula_linear_lower`
- `lower_zero`               → `formula_penalty_1pt`

Thêm helper method vào line:

```python
def get_effective_formula(self):
    """Trả formula hiệu lực: scoring_formula_id nếu có, else tìm builtin fallback."""
    self.ensure_one()
    if self.scoring_formula_id:
        return self.scoring_formula_id
    # Fallback map từ formula_type cũ
    FALLBACK_MAP = {
        ('linear',     'higher_better'): 'formula_linear_higher',
        ('linear',     'lower_better'):  'formula_linear_lower',
        ('lower_zero', ''):              'formula_penalty_1pt',
        ('step_table', ''):              None,  # không có builtin, phải set rõ
    }
    key = (self.formula_type or 'linear', self.linear_direction or '')
    xml_id = FALLBACK_MAP.get(key)
    if xml_id:
        ref = self.env.ref(
            f'custom_adecsol_hr_performance_evaluator.{xml_id}',
            raise_if_not_found=False
        )
        if ref:
            return ref
    return None
```

Tương tự thêm vào `hr.department.kpi.template.line`.

### 4.2 Thêm field vào `hr.performance.evaluation.line`

```python
scoring_formula_id = fields.Many2one(
    'hr.kpi.scoring.formula',
    related='kpi_line_id.scoring_formula_id',
    store=True,
    string='Công thức tính điểm',
)
```

---

## TASK 5 — Refactor engine để dùng formula mới

Trong `hr.kpi.engine` (hoặc nơi tính `system_score`), thay toàn bộ switch case cũ:

**Trước:**
```python
if line.formula_type == 'linear':
    if direction == 'higher_better':
        system_score = min((actual / target) * 10, 10)
    else:
        system_score = min((target / actual) * 10, 10) if actual else 10
elif line.formula_type == 'step_table':
    ...
elif line.formula_type == 'lower_zero':
    system_score = max(10 - actual, 0)
```

**Sau:**
```python
def _compute_system_score_for_line(self, line, actual, target):
    """
    Tính system_score cho một KPI line.
    Ưu tiên: scoring_formula_id > get_effective_formula() > fallback 0.
    """
    formula = line.get_effective_formula()
    if not formula:
        _logger.warning(
            "KPI line '%s' (id=%s) không có formula — trả 0.",
            line.name, line.id
        )
        return 0.0
    try:
        return formula.compute_score(actual or 0.0, target or 0.0)
    except Exception as e:
        _logger.error(
            "compute_score lỗi: formula='%s', actual=%s, target=%s, error=%s",
            formula.name, actual, target, e
        )
        return 0.0
```

**Lưu ý quan trọng:**
- `formula.compute_score()` gọi `self.get_score_scale_base()` bên trong —
  đảm bảo method này available trên model `hr.kpi.scoring.formula`
  bằng cách kế thừa từ mixin hoặc đọc từ `ir.config_parameter`.
- Nếu `get_score_scale_base()` hiện đang là method của model khác (ví dụ `hr.kpi.engine`),
  cần quyết định: di chuyển vào mixin dùng chung, hoặc pass `max_score`
  như tham số vào `compute_score(actual, target, max_score=None)`.
  **Khuyến nghị:** Dùng tham số optional để formula tự lấy nếu không có:

```python
def compute_score(self, actual, target, max_score=None):
    self.ensure_one()
    if max_score is None:
        max_score = self.get_score_scale_base()
    ...
```

---

## TASK 6 — View `hr.kpi.scoring.formula`

**File:** `views/hr_kpi_scoring_formula_views.xml`

### Form view — yêu cầu show/hide theo formula_type

```xml
<form string="Công thức tính điểm KPI">
  <sheet>
    <div class="oe_button_box" name="button_box">
      <button class="oe_stat_button" type="object"
              name="action_view_kpi_lines" icon="fa-list">
        <field name="kpi_line_count" widget="statinfo"
               string="KPI đang dùng"/>
      </button>
    </div>

    <group>
      <field name="name"/>
      <field name="formula_type" widget="radio"/>
      <field name="description"/>
    </group>

    <!-- LINEAR -->
    <group string="Cấu hình tuyến tính"
           attrs="{'invisible': [('formula_type','!=','linear')]}">
      <field name="linear_direction"/>
      <field name="linear_allow_exceed"/>
      <field name="preview_expression" readonly="1"/>
    </group>

    <!-- STEP TABLE -->
    <group string="Bảng bậc thang"
           attrs="{'invisible': [('formula_type','!=','step_table')]}">
      <field name="step_out_of_range"/>
      <!-- Widget bảng bậc thang: dùng custom OWL widget hoặc JSON editor -->
      <field name="step_table_json" widget="kpi_step_table_editor"/>
      <field name="preview_expression" readonly="1"/>
    </group>

    <!-- PENALTY -->
    <group string="Cấu hình trừ điểm"
           attrs="{'invisible': [('formula_type','!=','penalty')]}">
      <field name="penalty_base_score"/>
      <field name="penalty_deduct_per_unit"/>
      <field name="penalty_floor"/>
      <field name="preview_expression" readonly="1"/>
    </group>

    <!-- EXPRESSION -->
    <group string="Biểu thức tuỳ chỉnh"
           attrs="{'invisible': [('formula_type','!=','expression')]}">
      <div class="alert alert-warning" role="alert">
        Dành cho IT/Developer. Biến được phép: 
        <code>actual</code>, <code>target</code>, <code>max_score</code>,
        <code>min</code>, <code>max</code>, <code>abs</code>, <code>round</code>.
      </div>
      <field name="expression_code" placeholder="min(actual / target * max_score, max_score) if target else 0"/>
      <field name="preview_expression" readonly="1" string="Preview"/>
    </group>
  </sheet>

  <footer>
    <button name="action_test_formula" type="object"
            string="Chạy thử công thức" class="btn-secondary"/>
  </footer>
</form>
```

### List view

```xml
<tree string="Công thức tính điểm KPI">
  <field name="sequence" widget="handle"/>
  <field name="name"/>
  <field name="formula_type"/>
  <field name="preview_expression"/>
  <field name="kpi_line_count" string="Đang dùng"/>
  <field name="active"/>
</tree>
```

### OWL widget `kpi_step_table_editor`

Tạo widget OWL để HR nhập bảng bậc thang dạng grid thay vì nhập JSON thô.

**File:** `static/src/components/kpi_step_table_editor/`

Yêu cầu widget:
- Hiển thị bảng có thể thêm/xóa hàng: cột `Từ`, `Đến`, `Điểm`
- Ô `Đến` của hàng cuối có checkbox "Không giới hạn" → set `to: null`
- Validate: `to > from`, điểm trong khoảng `[0, get_score_scale_base()]`
- Tự động sort theo `from` tăng dần khi save
- Serialize/deserialize JSON để sync với field `step_table_json`

---

## TASK 7 — Migration data

**File:** `migrations/18.0.2.1.0/post-migrate.py`

```python
def migrate(cr, version):
    """
    Map formula_type cũ trên hr_kpi_template_line
    sang scoring_formula_id mới.
    """
    # Map (formula_type, direction) → xml_id của builtin formula
    MAPPING = [
        ('linear',     'higher_better', 'formula_linear_higher'),
        ('linear',     'lower_better',  'formula_linear_lower'),
        ('lower_zero', '',              'formula_penalty_1pt'),
        ('lower_zero', 'lower_better',  'formula_penalty_1pt'),
    ]
    MODULE = 'custom_adecsol_hr_performance_evaluator'

    for formula_type, direction, xml_name in MAPPING:
        # Lấy res_id của builtin formula
        cr.execute("""
            SELECT res_id FROM ir_model_data
            WHERE module = %s AND name = %s
        """, (MODULE, xml_name))
        row = cr.fetchone()
        if not row:
            continue
        formula_id = row[0]

        # Update hr_kpi_template_line
        if direction:
            cr.execute("""
                UPDATE hr_kpi_template_line
                SET scoring_formula_id = %s
                WHERE formula_type = %s
                  AND linear_direction = %s
                  AND scoring_formula_id IS NULL
            """, (formula_id, formula_type, direction))
        else:
            cr.execute("""
                UPDATE hr_kpi_template_line
                SET scoring_formula_id = %s
                WHERE formula_type = %s
                  AND scoring_formula_id IS NULL
            """, (formula_id, formula_type))

        # Tương tự cho hr_department_kpi_template_line
        if direction:
            cr.execute("""
                UPDATE hr_department_kpi_template_line
                SET scoring_formula_id = %s
                WHERE formula_type = %s
                  AND linear_direction = %s
                  AND scoring_formula_id IS NULL
            """, (formula_id, formula_type, direction))
        else:
            cr.execute("""
                UPDATE hr_department_kpi_template_line
                SET scoring_formula_id = %s
                WHERE formula_type = %s
                  AND scoring_formula_id IS NULL
            """, (formula_id, formula_type))

    # step_table: không có builtin tương ứng,
    # giữ step_table_json cũ và để scoring_formula_id = NULL
    # HR sẽ tự tạo formula step_table mới và gán lại
    cr.execute("""
        INSERT INTO mail_message (...)  -- optional: log warning cho HR biết
    """)
```

**Lưu ý:** Các line có `formula_type = 'step_table'` cũ sẽ KHÔNG tự migrate được
vì step_table_json cũ nằm trên line, còn model mới lưu trong formula record.
Sau migrate, hệ thống cần:
1. Hiển thị warning trên KPI line nếu `formula_type = 'step_table'` mà `scoring_formula_id` trống.
2. HR tự tạo formula step_table mới từ dữ liệu cũ rồi gán lại.

Thêm validation vào `hr.kpi.template.line`:
```python
@api.constrains('formula_type', 'scoring_formula_id')
def _check_step_table_has_formula(self):
    for rec in self:
        if rec.formula_type == 'step_table' and not rec.scoring_formula_id:
            raise ValidationError(
                f"KPI '{rec.name}': Loại công thức 'Bảng bậc thang' "
                "yêu cầu chọn Công thức tính điểm."
            )
```

---

## TASK 8 — Menu & Access rights

### Menu
Thêm vào `Configuration`:
```xml
<menuitem id="menu_kpi_scoring_formula"
          name="Công thức tính điểm"
          parent="menu_kpi_configuration"
          action="action_hr_kpi_scoring_formula"
          sequence="30"/>
```

### Access rights — `ir.model.access.csv`
```
access_kpi_scoring_formula_hr,    hr.kpi.scoring.formula, group_hr,    1,1,1,1
access_kpi_scoring_formula_mgr,   hr.kpi.scoring.formula, group_manager,1,0,0,0
access_kpi_scoring_formula_emp,   hr.kpi.scoring.formula, group_employee,1,0,0,0
```

Employee và Manager chỉ được đọc — chỉ HR mới tạo/sửa/xoá formula.

---

## TASK 9 — Tests

**File:** `tests/test_kpi_scoring_formula.py`

```python
class TestKpiScoringFormula(TransactionCase):

    def test_linear_higher_better_normal(self):
        """actual=80, target=100 → 8.0 (thang 10)"""

    def test_linear_higher_better_capped(self):
        """actual=120, target=100, allow_exceed=False → 10.0"""

    def test_linear_higher_better_bonus(self):
        """actual=120, target=100, allow_exceed=True → 12.0"""

    def test_linear_lower_better(self):
        """actual=50, target=100 → 10.0 (càng thấp càng tốt)"""

    def test_linear_zero_target(self):
        """target=0 → 0.0, không raise ZeroDivisionError"""

    def test_step_table_matched(self):
        """actual=75 nằm trong bậc [50,80) → đúng score của bậc đó"""

    def test_step_table_out_of_range_zero(self):
        """actual=150, không có bậc nào chứa, out_of_range=zero → 0.0"""

    def test_step_table_out_of_range_nearest(self):
        """actual=150, out_of_range=nearest → score của bậc gần nhất"""

    def test_step_table_unbounded_last(self):
        """actual=999, bậc cuối to=null → match và trả score đúng"""

    def test_step_table_invalid_json(self):
        """step_table_json rỗng/invalid → ValidationError khi save"""

    def test_penalty_basic(self):
        """actual=3, base=10, deduct=1 → 7.0"""

    def test_penalty_floor(self):
        """actual=15, base=10, deduct=1, floor=0 → 0.0 (không âm)"""

    def test_penalty_custom_deduct(self):
        """actual=3, base=10, deduct=2 → 4.0"""

    def test_expression_basic(self):
        """min(actual/target*max_score, max_score) với actual=80, target=100 → 8.0"""

    def test_expression_blocked_keyword(self):
        """expression chứa 'env' → ValidationError khi save"""

    def test_expression_syntax_error(self):
        """expression cú pháp sai → ValidationError khi save"""

    def test_expression_runtime_error(self):
        """expression gây ZeroDivisionError lúc runtime → trả 0.0, không crash"""

    def test_builtin_cannot_delete(self):
        """Xoá builtin formula → UserError"""

    def test_get_effective_formula_fallback(self):
        """line không có scoring_formula_id → get_effective_formula() trả builtin đúng"""

    def test_migration_linear_higher_migrated(self):
        """Sau migrate, line cũ formula_type=linear/higher_better có scoring_formula_id đúng"""
```

---

## Checklist trước khi merge

- [ ] `python -m py_compile models/hr_kpi_scoring_formula.py` pass
- [ ] `get_score_scale_base()` được gọi đúng — KHÔNG có số `10` hardcode trong `_score_*` methods
- [ ] Wizard test formula hoạt động và hiển thị kết quả
- [ ] Engine không còn switch case `formula_type` cũ
- [ ] Line có `formula_type=step_table` cũ hiển thị warning nếu chưa gán formula mới
- [ ] OWL widget `kpi_step_table_editor` serialize/deserialize JSON đúng
- [ ] `expression` bị block các keyword nguy hiểm
- [ ] Migration post-migrate chạy không lỗi trên DB có data cũ
- [ ] Tất cả tests trong Task 9 pass
