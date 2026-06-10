# ADEC SOL Performance Evaluator — Technical Documentation

## Tổng quan

Module `custom_adecsol_hr_performance_evaluator` cung cấp hệ thống đánh giá hiệu suất KPI cho nhân viên và phòng ban trong Odoo 18. Hệ thống hỗ trợ tự động thu thập chỉ số khách quan từ Task, Attendance, Leave; quy đổi điểm về thang điểm 10; liên kết KPI con của nhân viên với KPI cha của phòng ban; tính điểm phòng ban theo hướng bottom-up; và pha trộn điểm KPI phòng ban vào điểm KPI cuối cùng của cá nhân theo trọng số cấu hình.

Các thay đổi quan trọng trong code hiện tại:

- Không còn dùng `target_type` trong model, view, data và business logic.
- Đơn vị KPI được quản lý động bằng model `hr.kpi.unit`.
- KPI phần trăm được nhận diện bằng `unit.code == "percent"`.
- KPI phòng ban có thể tự động lấy điểm từ KPI con bằng `data_source = "child_kpi_average"`.
- Dashboard cây KPI hiển thị điểm theo thang `/10` và theo dõi cả KPI rủi ro/thiếu dữ liệu của cấp cá nhân lẫn phòng ban.

---

## Kiến trúc

Mối quan hệ giữa các thực thể cốt lõi trong hệ thống được thể hiện qua sơ đồ dưới đây:

```text
┌────────────────────────────────────────────────────────┐
│ hr.department.kpi                                      │
│ (Template KPI Phòng ban)                               │
└──────────────────────────┬─────────────────────────────┘
                           │ O2M: kpi_line_ids
                           ▼
┌────────────────────────────────────────────────────────┐
│ hr.department.kpi.line                                 │
│ (Dòng KPI cha cấp phòng ban)                           │
└──────────────────────────▲─────────────────────────────┘
                           │ M2O: parent_dept_line_id
┌──────────────────────────┴─────────────────────────────┐
│ hr.kpi.line                                            │
│ (Dòng KPI con cấp nhân viên)                           │
└──────────────────────────▲─────────────────────────────┘
                           │ O2M: kpi_line_ids
┌──────────────────────────┴─────────────────────────────┐
│ hr.kpi                                                 │
│ (Template KPI Nhân viên)                               │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│ hr.department.performance.evaluation                   │
│ (Phiếu đánh giá KPI phòng ban)                         │
└──────────────────────────┬─────────────────────────────┘
                           │ O2M: evaluation_line_ids
                           ▼
┌────────────────────────────────────────────────────────┐
│ hr.department.evaluation.line                          │
│ (Dòng KPI phòng ban thực tế)                           │
└──────────────────────────▲─────────────────────────────┘
                           │ M2O: parent_dept_evaluation_line_id
┌──────────────────────────┴─────────────────────────────┐
│ hr.performance.evaluation.line                         │
│ (Dòng KPI nhân viên thực tế)                           │
└──────────────────────────▲─────────────────────────────┘
                           │ O2M: evaluation_line_ids
┌──────────────────────────┴─────────────────────────────┐
│ hr.performance.evaluation                              │
│ (Phiếu đánh giá KPI cá nhân)                           │
└────────────────────────────────────────────────────────┘
```

### Cơ chế thừa kế và quản lý KPI

1. **Template KPI phòng ban (`hr.department.kpi`)**
   - Quản lý các nhóm mục tiêu lớn của phòng ban.
   - Mỗi dòng KPI phòng ban là một KPI cha (`hr.department.kpi.line`).


2. **Template KPI nhân viên (`hr.kpi`)**
   - Quản lý KPI chi tiết cho nhân viên theo phòng ban, vị trí công việc và chu kỳ.
   - Mỗi dòng KPI nhân viên (`hr.kpi.line`) có thể trỏ đến một dòng KPI phòng ban cha qua `parent_dept_line_id`.

3. **Phiếu đánh giá thực tế**
   - `hr.department.performance.evaluation` là phiếu KPI phòng ban trong một kỳ.
   - `hr.performance.evaluation` là phiếu KPI cá nhân trong cùng kỳ.
   - Khi generate theo phòng ban, các dòng KPI con của nhân viên được liên kết đến dòng KPI phòng ban thực tế qua `parent_dept_evaluation_line_id`.

4. **Quy đổi thang điểm 10**
   - Điểm dòng KPI cá nhân dùng `final_rating` thang 0-10.
   - Điểm dòng KPI phòng ban dùng `final_score` thang 0-10.
   - Dashboard tổng quan, KPI Tree và badge kết quả đều đọc điểm theo thang 10.

---

## Luồng nghiệp vụ

### 1. Khởi tạo & Phát hành (Initialization & Batch Generation)

1. **HR/Quản lý cấu hình dữ liệu nền**
   - Cấu hình ngưỡng điểm tại Settings: `kpi_threshold_excellent`, `kpi_threshold_pass`.
   - Cấu hình số phút đi trễ cho phép: `late_grace_minutes`.
   - Cấu hình danh mục đơn vị KPI tại menu `Configuration > KPI Units`.

2. **HR/Quản lý tạo template KPI**
   - Tạo template KPI phòng ban (`hr.department.kpi`) và các dòng KPI cha.
   - Tạo template KPI nhân viên (`hr.kpi`) và các dòng KPI con.
   - Với KPI con cần cuốn điểm lên phòng ban, chọn `parent_dept_line_id`.

3. **Phát hành KPI cá nhân lẻ**
   - Dùng `hr.kpi.generate.wizard` để phát hành KPI cá nhân từ template `hr.kpi`.
   - Hệ thống sinh `hr.performance.evaluation` và các `hr.performance.evaluation.line`.

4. **Phát hành KPI toàn phòng ban**
   - Dùng `hr.department.kpi.generate.wizard`.
   - Hệ thống sinh `hr.department.performance.evaluation`, các dòng KPI phòng ban, `hr.performance.report`, và các phiếu KPI cá nhân cho nhân viên thuộc phòng ban.
   - Các dòng KPI con của nhân viên được link đến dòng KPI cha phòng ban ở cả cấp template và cấp evaluation.

### 2. Tự động tính toán chỉ số (Auto-Computation of Metrics)

Với các chỉ tiêu có `is_auto = True`, KPI Engine (`hr.kpi.engine`) sẽ tính `actual` trong khoảng `start_date` đến `end_date`.

Các nguồn dữ liệu nhân viên hiện có:

- **Task hoàn thành (`done_task`)**: Đếm số task được giao đã hoàn thành trong kỳ. Nếu unit là `%`, engine trả về tỷ lệ hoàn thành trên tổng task; nếu unit là `task`, engine trả về số lượng task.
- **Task đúng hạn (`task_on_time`)**: Đếm task hoàn thành đúng hạn. Unit `%` cho kết quả tỷ lệ đúng hạn.
- **Đi muộn (`late_days`)**: Đếm số ngày đi muộn bằng cách so sánh check-in đầu tiên với giờ bắt đầu làm việc theo calendar, có cộng `late_grace_minutes`.
- **Đi làm đầy đủ (`attendance_full`)**: Tính ngày phải làm, ngày có mặt, ngày nghỉ phép đã duyệt, ngày nghỉ lễ và ngày nghỉ không phép để phục vụ scoring kỷ luật chuyên cần.

Quy tắc unit hiện tại:

- Không còn dùng `target_type`.
- Nếu `unit.code == "percent"` thì `_value_or_percentage()` trả về `(numerator / denominator) * 100`.
- Nếu unit khác `%`, engine trả về giá trị thô.

> [!NOTE]
> Bộ tính toán tự động dùng timezone của nhân viên/calendar để tránh lệch ngày khi xử lý Attendance và Leave.

### 3. Tự động tổng hợp KPI phòng ban từ KPI con (Bottom-up)

Với dòng KPI phòng ban có `data_source = "child_kpi_average"`:

1. Hệ thống gom các dòng KPI con `hr.performance.evaluation.line` đang link đến dòng KPI phòng ban.
2. Với từng nhân viên, tính điểm danh mục cha bằng trung bình gia quyền:

```text
Điểm danh mục của nhân viên =
    Σ(final_rating KPI con × weight KPI con) / Σ(weight KPI con)
```

3. Điểm `actual` của dòng KPI phòng ban là trung bình cộng điểm danh mục của các nhân viên có KPI con hợp lệ:

```text
actual KPI cha phòng ban =
    Σ(điểm danh mục của từng nhân viên) / số nhân viên có dữ liệu hợp lệ
```

4. Dòng KPI phòng ban tiếp tục dùng `actual`, `target`, `direction` để tính `system_score` và `final_score`.

Các trường hợp đặc biệt:

- KPI con có `weight <= 0` bị bỏ qua.
- Nhân viên không có KPI con trong danh mục đó bị bỏ qua.
- Không có dòng con hợp lệ thì `actual = 0`.

### 4. Nhân viên Tự đánh giá (Self-Evaluation)

1. Phiếu cá nhân bắt đầu ở trạng thái `self_evaluation`.
2. Nhân viên nhập tự đánh giá và bình luận ở các KPI thủ công.
3. Với KPI định tính, các trường employee rating được mirror sang manager rating trong giai đoạn self-evaluation để hiển thị điểm tạm tính.
4. Nhân viên bấm **Submit** để chuyển sang `manager_evaluating`.
5. Hệ thống gửi thông báo/email cho quản lý phòng ban.

### 5. Quản lý Đánh giá & Điều chỉnh (Manager Evaluating)

1. Phiếu chuyển sang `manager_evaluating`.
2. Nhân viên không còn được sửa các trường tự đánh giá.
3. Quản lý/HR nhập hoặc điều chỉnh điểm quản lý và comment.
4. Logic `write()` trên line kiểm soát quyền sửa theo trạng thái phiếu và nhóm người dùng.

### 6. Duyệt & Hoàn tất (Finalization & Approval)

1. Quản lý hoặc HR bấm **Approve** để hoàn tất phiếu.
2. Phiếu chuyển sang `completed` và bị khóa dữ liệu.
3. `performance_score` là trung bình gia quyền KPI cá nhân.
4. `final_score` là điểm cuối cùng sau khi pha trộn với `dept_kpi_score`.
5. Điểm mới nhất có thể được đồng bộ về `hr.employee.performance_score` để phục vụ theo dõi nhân sự.

---

## Cấu hình / Các Model

### 1. Đơn vị KPI (`hr.kpi.unit`)

Danh mục đơn vị dùng chung cho KPI template và evaluation line.

- `name`: Tên hiển thị, ví dụ `%`, `điểm`, `ngày`, `task`.
- `code`: Mã kỹ thuật duy nhất, ví dụ `percent`, `score`, `day`, `task`.
- `active`: Cho phép lưu trữ unit cũ mà không xóa dữ liệu lịch sử.

Unit mặc định có trong data:

- `%` (`percent`)
- `điểm` (`score`)
- `ngày` (`day`)
- `task` (`task`)

### 2. Template KPI Cá nhân (`hr.kpi` & `hr.kpi.line`)

Quản lý các chỉ tiêu hiệu suất mẫu cho nhân viên.

* **`hr.kpi`**
  - `period`: Chu kỳ KPI.
  - `department_id`: Phòng ban áp dụng.
  - `job_id`: Vị trí công việc áp dụng.
  - `department_kpi_id`: Template KPI phòng ban cha.
  - `kpi_line_ids`: Danh sách dòng KPI.

* **`hr.kpi.line`**
  - `key_performance_area`: Tên KPI hoặc tên section.
  - `kpi_type`: `quantitative`, `binary`, `rating`, `score`.
  - `unit`: Đơn vị KPI (`hr.kpi.unit`). Unit `%` thay thế hoàn toàn logic `target_type` cũ.
  - `direction`: `higher_better` hoặc `lower_better`.
  - `target`: Mục tiêu.
  - `weight`: Trọng số dòng KPI.
  - `is_auto`: Tự động tính actual.
  - `data_source`: `manual`, `done_task`, `task_on_time`, `late_days`, `attendance_full`.
  - `parent_dept_line_id`: Dòng KPI cha phòng ban.
  - `is_section` / `display_type`: Dòng section/note.

### 3. Template KPI Phòng ban (`hr.department.kpi` & `hr.department.kpi.line`)

Quản lý KPI mẫu cấp phòng ban.

* **`hr.department.kpi`**
  - `department_id`: Phòng ban áp dụng.
  - `period`: Chu kỳ KPI.
  - `kpi_line_ids`: Danh sách KPI phòng ban.

* **`hr.department.kpi.line`**
  - `name`: Tên KPI phòng ban.
  - `kpi_type`, `unit`, `direction`, `target`, `weight`.
  - `data_source`: Hiện flow chính gồm `manual` và `child_kpi_average`.
  - `child_template_line_ids`: Trace các KPI con template đang link vào dòng KPI cha.
  - `child_template_rows_json`: Dữ liệu matrix để hiển thị KPI con ngay trong UI.

### 4. Phiếu Đánh giá Cá nhân (`hr.performance.evaluation` & `hr.performance.evaluation.line`)

* **`hr.performance.evaluation`**
  - `employee_id`: Nhân viên được đánh giá.
  - `state`: `self_evaluation`, `manager_evaluating`, `completed`, `cancel`.
  - `performance_score`: Trung bình gia quyền `final_rating` của các line.
  - `dept_evaluation_id`: Phiếu KPI phòng ban cùng kỳ.
  - `final_score`: Điểm cuối cùng sau khi blend phòng ban/cá nhân.
  - `performance_level` và `final_level`: `excellent`, `pass`, `fail`.

* **`hr.performance.evaluation.line`**
  - `kpi_line_id`: Dòng template nguồn.
  - `parent_dept_line_id`: Dòng KPI phòng ban template cha.
  - `parent_dept_evaluation_line_id`: Dòng KPI phòng ban thực tế cha.
  - `unit`: Đơn vị KPI được copy từ template.
  - `actual`: Giá trị thực tế cho KPI định lượng.
  - `system_score`: Điểm hệ thống tính theo rule.
  - `final_rating`: Điểm cuối cùng của dòng, thang 0-10.
  - `employee_rating_*`, `manager_rating_*`, `employee_comment`, `manager_comment`: Dữ liệu tự đánh giá và quản lý đánh giá.

### 5. Phiếu Đánh giá Phòng ban (`hr.department.performance.evaluation` & `hr.department.evaluation.line`)

* **`hr.department.performance.evaluation`**
  - `department_id`: Phòng ban.
  - `department_kpi_id`: Template KPI phòng ban.
  - `evaluation_line_ids`: Các dòng KPI phòng ban thực tế.
  - `dept_kpi_score`: Điểm KPI phòng ban thang 0-10.
  - `get_dept_kpi_score()`: Method trả điểm phòng ban hiện tại để pha trộn vào điểm cá nhân.

* **`hr.department.evaluation.line`**
  - `department_kpi_line_id`: Dòng template nguồn.
  - `unit`: Đơn vị KPI.
  - `actual`, `target`, `direction`.
  - `system_score`, `final_score`.
  - `child_evaluation_line_ids`: Trace KPI con của nhân viên.
  - `child_line_rows_json`: Dữ liệu matrix KPI con theo nhân viên.

### 6. Dashboard Quản lý Đánh giá (`hr.performance.report`)

Đóng vai trò trung tâm theo dõi các phiếu KPI cá nhân của nhân viên trong một phòng ban/kỳ.

* Giao diện dashboard OWL thống kê số lượng phiếu, điểm trung bình và trạng thái.
* Gửi thông báo nhắc deadline.
* Xuất báo cáo Excel.
* Cung cấp dữ liệu tổng hợp cho dashboard form.

### 7. KPI Tree Dashboard

Dashboard cây KPI dùng D3 local asset.

- Company node: điểm công ty là trung bình `dept_kpi_score` của các phòng ban trong kỳ.
- Department node: điểm chính là `dept_kpi_score`.
- Employee node: điểm chính là `performance_score`.
- Tất cả điểm hiển thị theo thang `/10`.
- Risk/Missing panels lấy cả KPI cá nhân và KPI phòng ban:
  - `risk_lines`: các KPI fail theo `threshold_pass`.
  - `missing_data_lines`: các KPI auto quantitative thiếu dữ liệu actual.
  - Mỗi dòng có badge nguồn `Cá nhân` hoặc `Phòng ban`.
  - Panel chính hiển thị 5 dòng đầu, modal hiển thị tất cả.
  - Click vào dòng sẽ mở form line tương ứng theo `line_model` và `line_id`.

---

## Phân quyền

Hệ thống phân quyền được cấu hình thông qua Groups và Record Rules.

### 1. Các Nhóm quyền (Security Groups)

| Nhóm quyền | Kế thừa quyền | Mô tả quyền hạn |
|---|---|---|
| **Employee** (`group_employee`) | Không | Xem phiếu của chính mình, nhập tự đánh giá khi phiếu ở `self_evaluation`. |
| **Manager** (`group_manager`) | Employee | Xem và đánh giá nhân viên thuộc phòng ban mình quản lý. |
| **HR** (`group_hr`) | Không | Quản trị toàn bộ hệ thống KPI, template, phiếu đánh giá và báo cáo. |
| **Admin (Dev)** (`group_admin`) | HR | Quyền quản trị cao nhất cho cấu hình và vận hành. |

### 2. Quy tắc truy cập bản ghi (Record Rules)

* **Đánh giá cá nhân (`hr.performance.evaluation`)**
  - Employee: chỉ truy cập phiếu của chính mình.
  - Manager: truy cập phiếu của nhân viên thuộc phòng ban mình quản lý.
  - HR/Admin: truy cập toàn bộ.

* **Dòng đánh giá cá nhân (`hr.performance.evaluation.line`)**
  - Áp dụng theo phiếu cha `evaluation_id`.

* **Đánh giá phòng ban (`hr.department.performance.evaluation`)**
  - Manager: chỉ truy cập phòng ban mình quản lý.
  - HR/Admin: truy cập toàn bộ.

* **Danh mục unit (`hr.kpi.unit`)**
  - Employee/Manager: đọc.
  - HR/Admin: CRUD.

---

## Hiệu năng & Xử lý Kỹ thuật

### 1. Thuật toán Tính điểm Chuẩn hóa (Standardized Scoring Algorithms)

Hệ thống quy đổi các kiểu KPI về thang điểm 10.

* **KPI Định lượng (`quantitative`)**
  - Nếu `direction = 'higher_better'`:

    ```text
    system_score = min((actual / target) * 10, 10)
    ```

  - Nếu `direction = 'lower_better'`:

    ```text
    system_score = min((target / actual) * 10, 10)
    ```

  - Target và Actual luôn cùng đơn vị. Nếu unit là `%`, cả hai đều là giá trị 0-100.

* **KPI `late_days`**
  - Bắt đầu từ 10 điểm.
  - Mỗi ngày đi muộn trừ 1 điểm.

    ```text
    system_score = max(10 - late_days, 0)
    ```

* **KPI `attendance_full`**
  - Có nghỉ không phép thì điểm về 0.
  - Nghỉ phép hợp lệ được chấm theo số ngày nghỉ: 0 ngày = 10 điểm, 1-5 ngày giảm dần, trên 5 ngày = 0 điểm.

* **KPI Đánh giá sao (`rating`)**

  ```text
  score = (rating_0_5 / 5) * 10
  ```

* **KPI Nhị phân (`binary`)**
  - Yes = 10.
  - No = 0.

* **KPI Nhập điểm (`score`)**
  - Nhận trực tiếp điểm 0-10.

### 3. Tối ưu hóa hiệu năng & Chống Race Condition

* **Computed stored fields**
  - `performance_score`, `final_score`, `dept_kpi_score`, `system_score`, `final_rating`, `final_score` line được lưu để list/dashboard đọc nhanh.

* **KPI Engine**
  - Tái sử dụng logic compute cho dashboard breakdown.
  - Dùng batch/search domain thay vì tính rời rạc quá nhiều nơi.

* **Cron job**
  - `_cron_compute_auto_kpi` chạy auto compute theo batch.
  - Deadline reminder chạy nền để tránh thao tác thủ công.

* **Matrix trace data**
  - `child_line_rows_json` và `child_template_rows_json` được compute để UI render matrix nhanh, không nhúng one2many lồng nhau trong list row.

---

## Edge cases & Lưu ý

1. **Unit `%` thay thế `target_type`**
   - `target_type` không còn trong model/view/data.
   - Cột DB cũ có thể vẫn tồn tại như legacy column nhưng business logic không đọc nữa.
   - Migration `18.0.1.1.0` map record cũ có `target_type = 'percentage'` sang unit `%` nếu `unit` đang trống.

2. **Migration từ `unit_label`**
   - Migration `18.0.1.0.0` đổi `unit_label` text cũ sang `unit` Many2one.
   - Cột `unit_label_legacy` được giữ để trace dữ liệu cũ.

3. **Tổng trọng số không đạt 100%**
   - Template KPI kiểm tra tổng trọng số các dòng không phải section trong khoảng dung sai cho phép.

4. **KPI bottom-up không có dữ liệu con**
   - Không có child line hợp lệ thì actual KPI cha = 0.
   - Child line có weight <= 0 bị bỏ qua.
   - Nhân viên không có KPI con trong danh mục cha bị bỏ qua.

5. **Không có đánh giá phòng ban**
   - Điểm cuối cá nhân fallback về `performance_score` để tránh ảnh hưởng quyền lợi nhân viên.

6. **Nghỉ phép trùng ngày nghỉ lễ**
   - Engine `attendance_full` tách bucket ngày lễ, ngày đi làm, ngày nghỉ phép và ngày nghỉ không phép để giảm sai lệch do overlap.

7. **Quyền sửa theo trạng thái**
   - Phiếu `completed` hoặc `cancel` bị khóa.
   - Employee chỉ sửa self fields khi ở `self_evaluation`.
   - Manager chỉ sửa manager fields khi ở `manager_evaluating`.

---

## Chạy tests

Để kiểm tra nhanh sau khi chỉnh model/view/data:

```bash
python -m py_compile models/kpi_line.py models/hr_department_kpi_line.py models/performance_evaluation_line.py models/hr_department_evaluation_line.py models/hr_kpi_engine.py
```

Lệnh nâng cấp module:

```bash
odoo-bin -d <db_name> -u custom_adecsol_hr_performance_evaluator --stop-after-init
```

### Các trường hợp cần kiểm thử

* `TestKpiUnit`
  - Unit mặc định được tạo.
  - KPI unit `%` làm engine trả về tỷ lệ phần trăm.
  - Unit `task`, `ngày`, `điểm` hiển thị đúng và không quy đổi phần trăm.

* `TestPerformanceEvaluation`
  - Luồng `self_evaluation` → `manager_evaluating` → `completed`.
  - Employee rating được mirror sang manager rating khi self-evaluation.
  - Phiếu completed/cancel bị khóa sửa.

* `TestKpiEngine`
  - `done_task`, `task_on_time`, `late_days`, `attendance_full`.
  - Xử lý timezone và kỳ đánh giá.

* `TestBottomUpDepartmentKpi`
  - KPI con link đúng KPI cha.
  - `child_kpi_average` tính đúng trung bình gia quyền theo nhân viên rồi trung bình phòng ban.
  - Edge case không có child line, child weight = 0.

* `TestScoringLogic`
  - Công thức thang điểm 10 cho quantitative, binary, rating, score.
  - Công thức pha trộn `dept_kpi_score` và `performance_score`.

* `TestKpiTreeDashboard`
  - Company score = trung bình `dept_kpi_score` của các phòng ban.
  - Department score = `dept_kpi_score`.
  - Employee score = `performance_score`.
  - Risk/Missing line hiển thị cả KPI cá nhân và KPI phòng ban.

* `TestPerformanceSecurity`
  - Employee không xem/sửa phiếu người khác.
  - Manager chỉ xem/sửa nhân viên thuộc phòng ban mình.
  - HR/Admin có quyền toàn cục.
