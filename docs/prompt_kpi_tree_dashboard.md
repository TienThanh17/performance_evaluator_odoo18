# Prompt: KPI Tree Dashboard
# Model: claude-sonnet-4-6 (antigravity)
# Module: custom_adecsol_hr_performance_evaluator (Odoo 17)

---

## SHARED CONTEXT — ĐỌC KỸ TRƯỚC KHI VIẾT BẤT CỨ DÒNG NÀO

```
Module: custom_adecsol_hr_performance_evaluator (Odoo 18)
UI framework: OWL (Odoo Web Library) + Chart.js — đã có sẵn trong module.
Không dùng React, Vue, hoặc bất kỳ SPA framework nào khác.

Models liên quan đến dashboard này:
  hr.performance.evaluation
    - employee_id (Many2one hr.employee)
    - dept_evaluation_id (Many2one hr.department.performance.evaluation)
    - performance_score (Float)  — điểm KPI cá nhân thuần túy
    - final_score (Float, store) — điểm cuối = dept×0.4 + cá_nhân×0.6
    - final_level (Selection: excellent/pass/fail)
    - state (Selection: self_evaluation/manager_evaluating/completed/cancel)
    - kpi_id (Many2one hr.kpi)
    - performance_report_id (Many2one hr.performance.report)
    - Method: get_dashboard_data()

  hr.department.performance.evaluation
    - department_id (Many2one hr.department)
    - dept_kpi_score (Float) — điểm KPI riêng phòng ban
    - state (Selection: draft/submitted/approved/cancel)
    - Method: get_dept_kpi_score()

  hr.department (extension của Odoo core)
    - avg_final_score (Float, compute không store)
      — trung bình final_score của tất cả hr.performance.evaluation
        có state='completed', department_id=self.id

  hr.employee (Odoo core, có extension)
    - department_id (Many2one hr.department)
    - image_128 (Binary)
    - job_id (Many2one hr.job)

  res.config.settings (global thresholds):
    - kpi_threshold_excellent: default 90.0
    - kpi_threshold_pass: default 50.0
    (Lưu ý: file md ghi default 9.0 / 5.0 — đây là thang 0-10.
     Khi hiển thị trên dashboard nhân với 10 ra thang 0-100.
     PHẢI đọc file res_config_settings.py để xác định đúng
     key và thang điểm trước khi dùng.)

Module hiện có OWL dashboards:
  - kpi_individual_dashboard  (static_src/components/...)
  - kpi_department_dashboard
  - performance_dashboard_form (js_class trên hr.performance.report)
  Tham khảo cấu trúc file của các dashboard này để đặt file mới
  đúng convention, KHÔNG được tạo cấu trúc folder khác biệt.

Quy ước đặt tên file trong module:
  static/src/components/kpi_tree_dashboard/
    kpi_tree_dashboard.js
    kpi_tree_dashboard.xml   (OWL template)
    kpi_tree_dashboard.scss  (nếu cần style riêng)
  views/kpi_tree_dashboard_views.xml
  __manifest__.py: cần cập nhật 'assets' và 'data'
```

---

## NHIỆM VỤ TỔNG QUAN

Tạo một dashboard mới tên **KPI Tree** gồm 3 phần chính:
1. **6 metric cards** hàng đầu
2. **Cây KPI 3 cấp** (cây chính, chiếm 70% diện tích)
3. **4 panel phân tích** phía dưới

Dashboard được truy cập qua **menu mới** độc lập (không nhúng vào form nào).
Toàn bộ là OWL component thuần, không dùng `js_class` trên form.

---

## PHẦN A — BACKEND: METHOD LẤY DỮ LIỆU

### A1. Method `get_kpi_tree_data()` trên `hr.performance.evaluation`

Đây là **single RPC call** duy nhất từ frontend. Trả về toàn bộ data cần thiết
cho dashboard trong một lần gọi để tránh N+1 queries.

```python
@api.model
def get_kpi_tree_data(self, period_start=None, period_end=None):
    """
    Trả về dict đầy đủ cho KPI Tree dashboard.

    Args:
        period_start (str|None): 'YYYY-MM-DD'. None = lấy kỳ gần nhất có data.
        period_end   (str|None): 'YYYY-MM-DD'. None = lấy kỳ gần nhất có data.

    Returns dict với cấu trúc:
    {
      'period': {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD', 'label': 'T04/2026'},
      'available_periods': [
          {'start':..., 'end':..., 'label':...},  # sort desc
      ],
      'company': {
          'avg_final_score': float,   # mean(dept.avg_final_score) cho các dept có data
          'total_employees': int,     # số nhân sự có evaluation trong kỳ
          'total_depts': int,
          'pass_rate': float,         # % evaluations có final_level != 'fail'
      },
      'departments': [
          {
              'id': int,              # hr.department.id
              'name': str,
              'manager_name': str,    # department.manager_id.name hoặc ''
              'avg_final_score': float,  # avg final_score của nhân viên trong phòng, kỳ này
              'dept_kpi_score': float,   # từ hr.department.performance.evaluation.dept_kpi_score
              'employee_count': int,
              'employees': [
                  {
                      'id': int,           # hr.performance.evaluation.id
                      'employee_id': int,  # hr.employee.id
                      'name': str,         # employee.name
                      'job': str,          # employee.job_id.name hoặc ''
                      'avatar_url': str,   # '/web/image/hr.employee/{id}/image_128'
                      'final_score': float,
                      'performance_score': float,
                      'dept_kpi_score': float,  # từ dept_evaluation_id.dept_kpi_score
                      'final_level': str,   # 'excellent'/'pass'/'fail'
                      'state': str,
                  },
              ],
          },
      ],
      'risk_kpis': [
          # Top 5 hr.performance.evaluation.line có performance_score thấp nhất
          # Chỉ lấy line có is_section=False và state của evaluation != 'cancel'
          {
              'kpi_name': str,      # evaluation_line.name
              'dept_name': str,
              'employee_name': str,
              'score': float,       # performance_score của line (thang 0-10 hoặc 0-100)
              'level': str,         # 'fail'/'pass'/'excellent'
          },
      ],
      'missing_data_kpis': [
          # Top 5 evaluation.line có actual=0, is_auto=False, is_section=False
          {
              'kpi_name': str,
              'dept_name': str,
              'employee_name': str,
          },
      ],
      'logic_warnings': int,   # HARDCODE = 2 (chưa có engine kiểm tra logic)
      'thresholds': {
          'excellent': float,   # từ res.config.settings
          'pass': float,
      },
    }
    """
```

**Lưu ý quan trọng khi implement:**

- `available_periods`: Query `SELECT DISTINCT start_date, end_date FROM hr_performance_evaluation ORDER BY start_date DESC LIMIT 12`. Nếu không có data, trả về list rỗng và company.avg_final_score = 0.
- `departments`: Chỉ lấy department có ít nhất 1 `hr.performance.evaluation` trong kỳ đó. Không lấy department rỗng.
- `avg_final_score` của department trong method này: tính trực tiếp từ `hr.performance.evaluation` của kỳ được chọn — KHÔNG lấy từ `hr.department.avg_final_score` vì field đó không lọc theo kỳ.
- `dept_kpi_score` của department: lấy từ `hr.department.performance.evaluation` có `department_id = dept.id` và `start_date/end_date` khớp với kỳ. Nếu không có → trả về 0.0.
- `risk_kpis`: sort `performance_score ASC`, limit 5. Chuyển về thang 0-100 nếu cần.
- Toàn bộ query dùng `.sudo()` vì đây là dashboard dành cho HR/Manager/Admin.
- Wrap toàn bộ method trong try/except, log lỗi, trả về dict rỗng hợp lệ nếu fail.

### A2. Đăng ký method là JSON-RPC controller hoặc dùng `@api.model`

Dùng `@api.model` + gọi từ OWL qua `this.env.services.orm.call(...)`.
KHÔNG cần viết thêm controller HTTP riêng.

---

## PHẦN B — FRONTEND: OWL COMPONENT

### B1. File structure

```
static/src/components/kpi_tree_dashboard/
    kpi_tree_dashboard.js     ← Component chính
    kpi_tree_dashboard.xml    ← Template OWL
    kpi_tree_dashboard.scss   ← Style (nếu cần, không bắt buộc)
```

Tham khảo cấu trúc của component dashboard hiện có trong module để đặt
`import`, `registry.category`, và `owl.Component` đúng convention.

### B2. State của component

```javascript
setup() {
    this.state = useState({
        loading: true,
        data: null,           // response từ get_kpi_tree_data()
        selectedNode: null,   // { type: 'company'|'dept'|'emp', id, data }
        expandedDepts: new Set(),  // Set of department id — MỞ HẾT khi load
        metric: 'final',      // 'final' | 'perf' | 'dept'
        selectedPeriod: null, // { start, end, label }
    });
    onMounted(() => this.loadData());
}
```

**Expand mặc định**: Sau khi `loadData()` thành công, set `expandedDepts` bằng
`new Set(data.departments.map(d => d.id))` — mở hết tất cả phòng ban.

### B3. Metric cards (6 cards)

Render từ `this.state.data`:

| # | Label | Source | Ghi chú |
|---|---|---|---|
| 1 | KPI công ty | `data.company.avg_final_score` | **REAL DATA** |
| 2 | KPI hoạt động | `data.company.pass_rate` | **REAL DATA** — % đạt & xuất sắc |
| 3 | KPI tài chính | `'—'` | **HARDCODE** — hiển thị "Chưa tích hợp" |
| 4 | KPI rủi ro | `data.risk_kpis.length` (count) | **REAL DATA** |
| 5 | KPI thiếu dữ liệu | `data.missing_data_kpis.length` | **REAL DATA** |
| 6 | Cảnh báo logic | `data.logic_warnings` (= 2) | **HARDCODE từ backend** |

Mỗi card click → `selectNode('company')` để highlight tương ứng trên cây.

### B4. Cây KPI — render bằng SVG thuần trong OWL template

**KHÔNG dùng thư viện cây ngoài** (D3 tree, react-d3-tree...). Render SVG thủ công.

#### Layout tọa độ:

```
Layer 0 — ROOT (company):   y = 50px,  1 node, cx = svgWidth/2
Layer 1 — DEPT:             y = 160px, N nodes căn đều theo chiều ngang
Layer 2 — EMPLOYEE:         y = 270px, M nodes, nhóm theo dept cha
```

#### Tính chiều rộng SVG động:

```javascript
get svgWidth() {
    // Đếm tổng số "slot" cần thiết ở layer 2
    // Mỗi dept đã expand: số nhân viên của dept đó (tối thiểu 1 slot)
    // Mỗi dept chưa expand: 1 slot
    const slots = this.state.data.departments.reduce((sum, dept) => {
        const isExp = this.state.expandedDepts.has(dept.id);
        return sum + (isExp ? Math.max(1, dept.employees.length) : 1);
    }, 0);
    const NODE_W = 100;  // px mỗi slot
    const PADDING = 60;
    return Math.max(640, slots * NODE_W + PADDING);
}
```

#### Mỗi node SVG gồm:

```
<g class="kpi-node" t-on-click="() => onNodeClick(node)">
  <rect rx="8" fill="{levelBg}" stroke="{levelColor}" stroke-width="1.2" />
  <text font-size="17" font-weight="500" fill="{levelColor}">{score}%</text>
  <text font-size="10" fill="{levelColor}">{label}</text>
  <!-- Nếu type='emp': thêm avatar circle -->
  <!-- Nếu type='dept' và có nhân viên: thêm icon +/- expand -->
</g>
```

**Avatar nhân viên** trên node cấp 3: dùng `<image>` SVG với
`href="{avatar_url}"`, clip bằng `<clipPath>` hình tròn 16px radius.
Nếu không có avatar, render initials bằng `<circle>` + `<text>`.

#### Connector lines:

Vẽ `<line>` từ bottom-center của node cha đến top-center của node con.
Màu line = `levelColor(node_con.score)` để giúp nhận biết nhanh trạng thái.

#### Màu theo điểm (dùng threshold từ `data.thresholds`):

```javascript
levelColor(score) {
    if (score >= this.state.data.thresholds.excellent * 10) return '#1D9E75';
    if (score >= this.state.data.thresholds.pass * 10)      return '#378ADD';
    if (score <= 0) return '#B4B2A9';
    return '#E24B4A';
}
levelBg(score) {
    if (score >= this.state.data.thresholds.excellent * 10) return '#E1F5EE';
    if (score >= this.state.data.thresholds.pass * 10)      return '#E6F1FB';
    if (score <= 0) return '#F1EFE8';
    return '#FCEBEB';
}
```

**Lưu ý thang điểm**: `thresholds.excellent` và `thresholds.pass` từ backend
là thang 0-10 (theo `res.config.settings`). `final_score` từ backend là thang
0-100. Nhân threshold × 10 trước khi so sánh.
HOẶC: nếu đọc code thực tế thấy tất cả đều cùng thang → dùng thang đó nhất quán.
**Phải đọc file res_config_settings.py và hr_performance_evaluation.py để xác định trước.**

### B5. Detail Panel (bên phải, hiển thị khi click node)

Panel này thay đổi nội dung theo `this.state.selectedNode.type`:

**type = 'company'**:
- Tiêu đề: "Công ty"
- Hiển thị: avg_final_score, total_employees, total_depts, pass_rate
- Không có sparkline (hardcode note: "Trend theo quý sẽ cập nhật sau")

**type = 'dept'**:
- Tiêu đề: dept.name
- Sub: dept.manager_name
- Hiển thị: avg_final_score, dept_kpi_score, employee_count
- Công thức breakdown: `dept_kpi × dept_weight + avg_cá_nhân × (1 - dept_weight)`
- Sparkline: **HARDCODE** 6 điểm mẫu, có ghi chú "* Trend hardcode — cần get_kpi_trend()"

**type = 'emp'**:
- Tiêu đề: emp.name
- Sub: emp.job
- Avatar lớn hơn (32px radius)
- Hiển thị: final_score, performance_score, dept_kpi_score, state
- Công thức breakdown: `{dept_kpi_score} × 0.4 + {performance_score} × 0.6 = {final_score}`
- Badge trạng thái evaluation (self_evaluation / manager_evaluating / completed)
- Sparkline: **HARDCODE**, ghi chú tương tự

### B6. 4 panel phía dưới

**Panel 1 — Top KPI rủi ro** (REAL DATA):
```xml
<t t-foreach="data.risk_kpis" t-as="item" t-key="item_index">
    <div class="risk-row">
        <span t-esc="item.kpi_name"/> — <span t-esc="item.dept_name"/>
        <span t-esc="item.score + '%'"/>
        <span t-attf-class="badge badge-{item.level}"/>
    </div>
</t>
```

**Panel 2 — Đóng góp phòng ban** (REAL DATA score, HARDCODE trọng số):
```javascript
// Render từ data.departments
// Hiển thị: dept.name | dept.avg_final_score (progress bar) | ghi chú "Trọng số hardcode"
```

**Panel 3 — KPI thiếu dữ liệu** (REAL DATA):
```xml
<t t-foreach="data.missing_data_kpis" t-as="item" t-key="item_index">
    <div class="miss-row">
        <span t-esc="item.kpi_name"/> — <span t-esc="item.employee_name"/>
        <span class="tag-missing">Thiếu dữ liệu</span>
    </div>
</t>
```

**Panel 4 — Insight điều hành AI** (FULL HARDCODE):
```xml
<!-- Hardcode 3 insight mẫu, có ghi chú rõ "Dữ liệu mẫu — tích hợp AI sau" -->
```

---

## PHẦN C — MENU VÀ VIEW REGISTRATION

### C1. File `views/kpi_tree_dashboard_views.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Client action để load OWL component -->
    <record id="action_kpi_tree_dashboard" model="ir.actions.client">
        <field name="name">KPI Tree</field>
        <field name="tag">kpi_tree_dashboard</field>
        <field name="target">main</field>
    </record>

    <!-- Menu item — đặt cùng cấp với các menu KPI hiện có trong module -->
    <!-- Đọc file views/menus.xml hiện có để tìm đúng parent menu id -->
    <menuitem
        id="menu_kpi_tree_dashboard"
        name="KPI Tree"
        action="action_kpi_tree_dashboard"
        parent="{PARENT_MENU_ID}"
        sequence="5"
        groups="custom_adecsol_hr_performance_evaluator.group_manager,
                custom_adecsol_hr_performance_evaluator.group_hr,
                custom_adecsol_hr_performance_evaluator.group_admin"
    />
</odoo>
```

**CRITICAL**: Đọc file `views/menus.xml` (hoặc file khai báo menu hiện có)
để tìm đúng `parent` menu id trước khi viết. Không được tự đặt parent id.

### C2. Cập nhật `__manifest__.py`

Thêm vào `'assets'` → `'web.assets_backend'`:
```python
'custom_adecsol_hr_performance_evaluator/static/src/components/kpi_tree_dashboard/kpi_tree_dashboard.js',
'custom_adecsol_hr_performance_evaluator/static/src/components/kpi_tree_dashboard/kpi_tree_dashboard.xml',
# scss nếu có:
# 'custom_adecsol_hr_performance_evaluator/static/src/components/kpi_tree_dashboard/kpi_tree_dashboard.scss',
```

Thêm vào `'data'`:
```python
'views/kpi_tree_dashboard_views.xml',
```

### C3. Đăng ký OWL component với Odoo registry

Trong `kpi_tree_dashboard.js`, cuối file:
```javascript
registry.category("actions").add("kpi_tree_dashboard", KpiTreeDashboard);
```

---

## PHẦN D — LOADING VÀ ERROR STATES

### D1. Loading state

Khi `this.state.loading = true`, hiển thị skeleton loader:
- 6 skeleton cards hàng đầu (gray animated pulse nếu CSS cho phép, hoặc plain gray)
- Placeholder hình chữ nhật thay cho cây KPI
- Không để trang trắng

### D2. Empty state

Khi `data.departments.length === 0`:
```xml
<div class="empty-state">
    <i class="fa fa-sitemap fa-3x"/>
    <p>Chưa có dữ liệu KPI cho kỳ này.</p>
    <p>Hãy tạo evaluation từ menu KPI Employee hoặc chọn kỳ khác.</p>
</div>
```

### D3. Period selector

Dropdown chọn kỳ từ `data.available_periods`. Khi đổi kỳ:
```javascript
async onPeriodChange(periodObj) {
    this.state.selectedPeriod = periodObj;
    this.state.loading = true;
    await this.loadData(periodObj.start, periodObj.end);
    // Sau khi load xong: expand lại hết tất cả dept
    this.state.expandedDepts = new Set(this.state.data.departments.map(d => d.id));
}
```

---

## PHẦN E — CHECKLIST SAU KHI VIẾT XONG

Tự kiểm tra trước khi submit:

- [ ] `get_kpi_tree_data()` dùng `@api.model` và có `sudo()`
- [ ] `avg_final_score` của dept trong method tính từ evaluations của KỲ ĐƯỢC CHỌN, không phải `hr.department.avg_final_score` (field đó không lọc theo kỳ)
- [ ] `expandedDepts` được set `new Set(all dept ids)` ngay sau khi load — mở hết
- [ ] Threshold được nhân × 10 nếu backend dùng thang 0-10 (xác nhận bằng cách đọc file)
- [ ] `risk_kpis` chỉ lấy line có `is_section=False` và evaluation `state != 'cancel'`
- [ ] Avatar SVG dùng `<clipPath>` để crop tròn, không dùng CSS border-radius trên `<image>`
- [ ] Menu item dùng đúng parent id từ file menus.xml hiện có
- [ ] `__manifest__.py` đã cập nhật cả `assets` lẫn `data`
- [ ] OWL component đã `registry.category("actions").add("kpi_tree_dashboard", ...)`
- [ ] 4 panel phía dưới: panel 1, 3 dùng real data từ response; panel 2 score real / weight hardcode; panel 4 full hardcode — tất cả có ghi chú inline
- [ ] Loading state và empty state đã implement
- [ ] Không có console.error khi departments rỗng hoặc period_start=None
