# Prompt: Phân quyền cho các Model KPI Phòng Ban mới
# Dành cho: GitHub Copilot / Gemini 2.5 Pro
# Module: `custom_adecsol_hr_performance_evaluator` (Odoo 16/17)

---

## 1. BỐI CẢNH — ĐỌC KỸ TRƯỚC KHI VIẾT BẤT CỨ DÒNG NÀO

Module đã có sẵn hệ thống phân quyền gồm **4 groups** và **2 loại kiểm soát**:
- `ir.model.access` (CSV): kiểm soát CRUD ở cấp model — ai được read/write/create/unlink.
- `ir.rule` (XML): kiểm soát ở cấp record — ai được thấy bản ghi nào trong model đó.

**Hai cơ chế này hoạt động như AND logic trong Odoo:**
> Nếu `ir.model.access` cho phép read nhưng `ir.rule` lọc ra 0 record → user thấy danh sách trống, KHÔNG báo lỗi.
> Nếu `ir.model.access` không cho phép write → Odoo raise `AccessError` dù `ir.rule` không lọc gì.

---

## 2. HỆ THỐNG GROUPS HIỆN CÓ — KHÔNG ĐƯỢC TẠO THÊM GROUP MỚI

Tất cả groups đã định nghĩa trong `security/security.xml`, dùng đúng `ref` sau đây:

| XML ID (dùng trong ref) | Tên | Implied groups | Dùng cho |
|---|---|---|---|
| `custom_adecsol_hr_performance_evaluator.group_employee` | Employee | — | Nhân viên thường |
| `custom_adecsol_hr_performance_evaluator.group_manager` | Manager | implies `group_employee` | Trưởng phòng |
| `custom_adecsol_hr_performance_evaluator.group_hr` | HR | — | Phòng nhân sự |
| `custom_adecsol_hr_performance_evaluator.group_admin` | Admin (Dev) | implies `group_hr` | Admin hệ thống |

**QUAN TRỌNG về implied_ids:**
- `group_manager` implies `group_employee` → Manager **tự động có** mọi quyền của Employee.
- `group_admin` implies `group_hr` → Admin **tự động có** mọi quyền của HR.
- Nghĩa là: nếu bạn ghi rule cho `group_employee`, Manager cũng bị ảnh hưởng trừ khi có rule riêng cho Manager override lại.

---

## 3. PATTERN PHÂN QUYỀN HIỆN CÓ — PHẢI NHẤT QUÁN

Đọc kỹ pattern này từ `security.xml` hiện tại để áp dụng đúng:

### Pattern `ir.rule` hiện tại cho từng model:

**`hr.performance.evaluation` (đánh giá cá nhân):**
- Employee: chỉ thấy evaluation của chính mình → `[('employee_id.user_id', '=', user.id)]`
- Manager: thấy evaluation của nhân sự trong phòng mình quản lý → `[('employee_id.department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`

**`hr.kpi` (template KPI cá nhân):**
- Manager: chỉ thấy template gắn với department mình quản lý → `[('department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`
- **Lưu ý: Employee KHÔNG có rule riêng cho hr.kpi** → Employee không truy cập trực tiếp template KPI.

**`hr.performance.report`:**
- Manager: chỉ thấy report của department mình → `[('department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`
- **Lưu ý: Employee KHÔNG có rule cho hr.performance.report** → Nhân viên không truy cập report tổng hợp.

### Pattern CSV (`ir.model.access`) — suy ra từ cấu trúc 24 rows, 8 columns:

Mỗi model thường có 4 rows tương ứng 4 groups. Convention đặt tên:
```
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_{model_snake}_{role},{Model}: {Role},model_{model_underscore},{module}.{group_xmlid},R,W,C,U
```

Ví dụ từ pattern hiện có (suy luận từ 24 rows / ~6 models cá nhân × 4 groups):
```csv
access_hr_performance_evaluation_employee,hr.performance.evaluation Employee,model_hr_performance_evaluation,custom_adecsol_hr_performance_evaluator.group_employee,1,1,0,0
access_hr_performance_evaluation_manager,hr.performance.evaluation Manager,model_hr_performance_evaluation,custom_adecsol_hr_performance_evaluator.group_manager,1,1,0,0
access_hr_performance_evaluation_hr,hr.performance.evaluation HR,model_hr_performance_evaluation,custom_adecsol_hr_performance_evaluator.group_hr,1,1,1,1
access_hr_performance_evaluation_admin,hr.performance.evaluation Admin,model_hr_performance_evaluation,custom_adecsol_hr_performance_evaluator.group_admin,1,1,1,1
```

---

## 4. CÁC MODEL MỚI CẦN PHÂN QUYỀN

Có **5 model mới** từ task phát triển KPI Phòng Ban:

| Model (Python `_name`) | Odoo model XML ID (`model_` + underscore) | Mô tả |
|---|---|---|
| `hr.department.kpi` | `model_hr_department_kpi` | Template KPI phòng ban |
| `hr.department.kpi.line` | `model_hr_department_kpi_line` | Tiêu chí trong template |
| `hr.department.performance.evaluation` | `model_hr_department_performance_evaluation` | Bản ghi đánh giá phòng ban |
| `hr.department.evaluation.line` | `model_hr_department_evaluation_line` | Dòng chỉ tiêu trong đánh giá |
| `hr.department` (extension) | `base.model_hr_department` | Mở rộng model có sẵn của Odoo |

**CRITICAL — `hr.department` là model của Odoo core:**
- `model_id:id` trong CSV phải dùng `base.model_hr_department` (không phải `custom_adecsol_...model_hr_department`).
- KHÔNG tạo `ir.rule` cho `hr.department` — model này đã có rule riêng từ Odoo core (`hr` module). Việc thêm rule sẽ gây conflict hoặc restrict quá mức.

---

## 5. MA TRẬN PHÂN QUYỀN CHI TIẾT

### 5.1. `ir.model.access` — Quyền CRUD theo group

**`hr.department.kpi` (Template KPI phòng ban):**

| Group | Read | Write | Create | Unlink | Lý do |
|---|---|---|---|---|---|
| Employee | 0 | 0 | 0 | 0 | Nhân viên không cần biết template KPI phòng |
| Manager | 1 | 0 | 0 | 0 | Trưởng phòng xem được template của mình, nhưng HR/Admin mới tạo/sửa |
| HR | 1 | 1 | 1 | 1 | HR quản lý toàn bộ template |
| Admin | 1 | 1 | 1 | 1 | Full access |

**`hr.department.kpi.line` (Tiêu chí template):**

| Group | Read | Write | Create | Unlink | Lý do |
|---|---|---|---|---|---|
| Employee | 0 | 0 | 0 | 0 | — |
| Manager | 1 | 0 | 0 | 0 | Xem được tiêu chí nhưng không sửa |
| HR | 1 | 1 | 1 | 1 | — |
| Admin | 1 | 1 | 1 | 1 | — |

**`hr.department.performance.evaluation` (Bản ghi đánh giá phòng ban):**

| Group | Read | Write | Create | Unlink | Lý do |
|---|---|---|---|---|---|
| Employee | 0 | 0 | 0 | 0 | Nhân viên không truy cập đánh giá cấp phòng |
| Manager | 1 | 1 | 0 | 0 | Trưởng phòng nhập actual + submit, nhưng không tự tạo/xóa |
| HR | 1 | 1 | 1 | 1 | HR tạo batch, quản lý toàn bộ |
| Admin | 1 | 1 | 1 | 1 | Full access |

**`hr.department.evaluation.line` (Dòng chỉ tiêu đánh giá):**

| Group | Read | Write | Create | Unlink | Lý do |
|---|---|---|---|---|---|
| Employee | 0 | 0 | 0 | 0 | — |
| Manager | 1 | 1 | 0 | 0 | Trưởng phòng nhập actual + manager_comment trên từng dòng |
| HR | 1 | 1 | 1 | 1 | — |
| Admin | 1 | 1 | 1 | 1 | — |

> **Tại sao Manager có Write=1 trên line nhưng Create=0?**
> Line được tạo tự động khi HR generate evaluation từ template. Trưởng phòng chỉ có nhiệm vụ điền `actual` và `manager_comment` vào line đã có. Nếu cho Create=1, trưởng phòng có thể tự thêm tiêu chí ngoài template → phá vỡ tính nhất quán của KPI.

### 5.2. `ir.rule` — Lọc record theo group

**`hr.department.kpi` (Template):**
- Manager: chỉ thấy template của phòng mình → `[('department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`
- Employee: KHÔNG có rule (vì `ir.model.access` đã block read=0, không cần rule)

**`hr.department.kpi.line` (Tiêu chí template):**
- Manager: chỉ thấy line thuộc template của phòng mình → `[('department_kpi_id.department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`

**`hr.department.performance.evaluation` (Bản ghi đánh giá):**
- Manager: chỉ thấy evaluation của phòng mình → `[('department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`

**`hr.department.evaluation.line` (Dòng đánh giá):**
- Manager: chỉ thấy line thuộc evaluation của phòng mình → `[('evaluation_id.department_id.manager_id.user_id', '=', user.id)]`
- HR: thấy tất cả → `[(1,'=',1)]`
- Admin: bypass → `[(1,'=',1)]`

---

## 6. OUTPUT CẦN TẠO

### 6.1. File `security/ir.model.access.csv`

Bạn phải **APPEND** vào file CSV hiện có, không được xóa 24 rows cũ.
Thêm đúng **16 rows mới** (4 model mới × 4 groups).
`hr.department` extension không cần thêm vào CSV vì quyền CRUD đã có từ Odoo core.

Format header (giữ nguyên nếu file đã có, không thêm lại):
```
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

Convention đặt tên `id`:
```
access_{model_snake_no_dots}_{role}
```
Ví dụ: `access_hr_department_kpi_manager`, `access_hr_department_evaluation_line_hr`

Convention đặt `name` (cột thứ 2, chỉ để hiển thị):
```
hr.department.kpi Manager
hr.department.evaluation.line HR
```

**Bảng 16 rows cần thêm** (viết đúng thứ tự: employee → manager → hr → admin cho từng model):

```
Model 1: hr.department.kpi
Model 2: hr.department.kpi.line
Model 3: hr.department.performance.evaluation
Model 4: hr.department.evaluation.line
```

Giá trị perm theo ma trận mục 5.1 ở trên.

### 6.2. File `security/security.xml`

Thêm các `<record>` mới vào **trong block `<data noupdate="0">`** hiện có, sau dòng cuối cùng của KPI Template rules (sau `rule_hr_kpi_admin_all`), trước thẻ đóng `</data>`.

**KHÔNG được:**
- Tạo thêm `<data>` block mới.
- Sửa bất kỳ `<record>` nào đã có.
- Thay đổi `noupdate` attribute.

**Cấu trúc XML cần thêm** (16 records `ir.rule` cho 4 model × 4 rules):

```xml
<!-- ========================================= -->
<!-- Record Rules: Department KPI Template     -->
<!-- ========================================= -->

<!-- Manager: chỉ template của phòng mình -->
<record id="rule_dept_kpi_manager_own" model="ir.rule">
    <field name="name">Dept KPI: Manager - Own Department</field>
    <field name="model_id" ref="custom_adecsol_hr_performance_evaluator.model_hr_department_kpi"/>
    <field name="domain_force">[('department_id.manager_id.user_id', '=', user.id)]</field>
    <field name="groups" eval="[(4, ref('custom_adecsol_hr_performance_evaluator.group_manager'))]"/>
</record>

<!-- HR: see all -->
...

<!-- Admin: bypass -->
...

<!-- (tương tự cho 3 model còn lại) -->
```

---

## 7. RULES KHÔNG ĐƯỢC VI PHẠM

### 7.1. Về XML ID của model trong ir.rule

`model_id` trong `ir.rule` dùng `ref=""`, giá trị là XML ID của model trong Odoo.
Convention: `{module_name}.model_{model_name_with_underscores}`.

```xml
<!-- ✅ ĐÚNG — model của module này -->
<field name="model_id" ref="custom_adecsol_hr_performance_evaluator.model_hr_department_kpi"/>

<!-- ✅ ĐÚNG — model của Odoo core -->
<field name="model_id" ref="base.model_hr_department"/>

<!-- ❌ SAI — thiếu module prefix -->
<field name="model_id" ref="model_hr_department_kpi"/>

<!-- ❌ SAI — dùng tên model thay vì XML ID -->
<field name="model_id" ref="hr.department.kpi"/>
```

### 7.2. Về `groups` trong ir.rule — dùng `eval` với tuple lệnh ORM

```xml
<!-- ✅ ĐÚNG — lệnh (4, ref) để link many2many -->
<field name="groups" eval="[(4, ref('custom_adecsol_hr_performance_evaluator.group_manager'))]"/>

<!-- ❌ SAI — thiếu eval, thiếu tuple command -->
<field name="groups" ref="custom_adecsol_hr_performance_evaluator.group_manager"/>
```

### 7.3. Về `domain_force` — phải là chuỗi Python domain hợp lệ

```xml
<!-- ✅ ĐÚNG — truy cập nhiều cấp quan hệ -->
<field name="domain_force">[('evaluation_id.department_id.manager_id.user_id', '=', user.id)]</field>

<!-- ✅ ĐÚNG — bypass all -->
<field name="domain_force">[(1,'=',1)]</field>

<!-- ❌ SAI — dùng False thay vì chuỗi domain -->
<field name="domain_force">False</field>

<!-- ❌ SAI — dùng [] empty (Odoo interpret khác nhau tùy version) -->
<field name="domain_force">[]</field>
```

### 7.4. Về Employee group và model mới

Employee có `read=0` trên tất cả model mới → **KHÔNG tạo `ir.rule` cho group_employee** trên các model này.
Lý do: `ir.rule` chỉ có tác dụng filter record khi user đã có quyền đọc model. Nếu `ir.model.access` block read=0, thêm rule là vô nghĩa và gây nhầm lẫn khi đọc code.

### 7.5. Về `hr.department` extension

- KHÔNG thêm `ir.rule` cho `hr.department` trong file này.
- KHÔNG thêm `ir.model.access` cho `hr.department` — đã có từ Odoo base.
- Nếu cần restrict field `department_score` / `department_level` chỉ hiển thị với Manager+, dùng `groups` attribute trực tiếp trên `<field>` trong view XML, không dùng rule.

### 7.6. Về implied_ids — tránh nhân đôi quyền

Vì `group_manager` implies `group_employee`, nếu Employee rule có domain A và Manager rule có domain B, thì Manager user sẽ thấy union của A ∪ B (Odoo OR các rule trong cùng model với cùng user).

Các model mới Employee không có rule → Manager chỉ bị ảnh hưởng bởi Manager rule của chính mình. Không cần lo overlap ở đây.

Tương tự: `group_admin` implies `group_hr` → Admin sẽ thấy union của HR rule + Admin rule, nhưng cả hai đều là `[(1,'=',1)]` nên không vấn đề.

---

## 8. CHECKLIST TRƯỚC KHI SUBMIT

- [ ] CSV có đúng 16 rows mới, không xóa 24 rows cũ.
- [ ] Mỗi `id` trong CSV là duy nhất, không trùng với rows hiện có.
- [ ] `model_id:id` trong CSV dùng đúng prefix `custom_adecsol_hr_performance_evaluator.model_` (không phải `base.`).
- [ ] `group_id:id` trong CSV dùng đúng prefix `custom_adecsol_hr_performance_evaluator.group_`.
- [ ] XML không có `<record>` nào cho Employee trên 4 model mới.
- [ ] XML không có `<record>` nào cho `hr.department`.
- [ ] Mọi `model_id ref=""` trong XML dùng đúng format `{module}.model_{name}`.
- [ ] Mọi `groups eval=""` dùng đúng format `[(4, ref('...'))]`.
- [ ] Tổng số `ir.rule` mới trong XML: đúng 12 records (3 rules × 4 model: Manager + HR + Admin, không có Employee).
- [ ] Không có `<data>` block mới, chỉ append vào block hiện có.
- [ ] Không sửa bất kỳ record nào đã có trong file.
