# ADEC SOL Performance Evaluator — Technical Documentation

## Tổng quan

Module `custom_adecsol_hr_performance_evaluator` cung cấp hệ thống đánh giá hiệu suất (KPI) toàn diện cho nhân viên và phòng ban trong Odoo 18. Hệ thống hỗ trợ tự động thu thập chỉ số khách quan từ các phân hệ khác (Task, Attendance, Leave), quy đổi điểm số về thang điểm 10 chuẩn hóa, đồng bộ thời gian thực luồng tự đánh giá của nhân viên, đánh giá của quản lý và pha trộn (blend) điểm số phòng ban vào điểm số cá nhân theo các trọng số cấu hình linh hoạt.

---

## Kiến trúc

Mối quan hệ giữa các thực thể cốt lõi trong hệ thống được thể hiện qua sơ đồ dưới đây:

```
┌────────────────────────────────────────────────────────┐
│ hr.performance.report                                  │
│ (Dashboard Quản lý KPI cho 1 phòng ban + 1 chu kỳ)     │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (O2M - evaluation_ids)
┌────────────────────────────────────────────────────────┐
│ hr.performance.evaluation                              │
│ (Đánh giá KPI cá nhân của từng nhân viên)             │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (O2M - evaluation_line_ids)
┌───────────────────────────────────┐       ┌───────────────────────────────────┐
│ hr.performance.evaluation.line    │◄──────│ hr.department.evaluation.line     │
│ (Chi tiết đánh giá cá nhân)       │  link │ (Chi tiết đánh giá phòng ban)     │
└───────────────────────────────────┘       └─────────────────┬─────────────────┘
                                                              ▲
                                                              │ (O2M)
                                            ┌─────────────────┴─────────────────┐
                                            │ hr.department.perf.evaluation     │
                                            │ (Đánh giá KPI phòng ban độc lập)  │
                                            └───────────────────────────────────┘
```

### Cơ chế thừa kế và quản lý KPI:
1. **Dashboard quản lý phòng ban (`hr.performance.report`)**: 
   - Đóng vai trò là trung tâm quản lý (dashboard) chuyên biệt cho **một phòng ban duy nhất** (`department_id`) và **một chu kỳ duy nhất** (`period`).
   - Liên kết trực tiếp một-nhiều (`One2many`) tới tất cả các bản đánh giá cá nhân `hr.performance.evaluation` của các nhân viên thuộc phòng ban đó trong chu kỳ tương ứng.
   - **Hoàn toàn độc lập** và không liên quan gì đến thực thể đánh giá hiệu suất của chính phòng ban đó (`hr.department.perf.evaluation`).
2. **Templates gốc**: 
   - `hr.department.kpi`: Cấu hình danh mục KPI và trọng số pha trộn phòng ban (`dept_weight`).
   - `hr.kpi`: Cấu hình danh mục KPI cá nhân áp dụng theo phòng ban hoặc chu kỳ.
3. **Bộ tạo hàng loạt (Batch Wizards)**:
   - `hr.department.kpi.generate.wizard`: Khởi tạo bản đánh giá phòng ban `hr.department.performance.evaluation` độc lập. Đồng thời, wizard này tự động sinh ra một đợt báo cáo quản lý `hr.performance.report` cho phòng ban và tạo hàng loạt bản đánh giá cá nhân `hr.performance.evaluation` cho các nhân viên thuộc phòng ban. Các dòng chỉ tiêu cá nhân được liên kết tới chỉ tiêu phòng ban cha thông qua `parent_dept_evaluation_line_id`.
4. **Quy đổi thang điểm 10**:
   - Tất cả các KPI (định lượng, định tính, nhị phân, xếp hạng sao) đều được quy đổi về thang điểm 10 chuẩn hóa trước khi tính điểm trung bình có trọng số.

---

## Luồng nghiệp vụ

### 1. Khởi tạo & Phát hành (Initialization & Batch Generation)
1. **HR/Quản lý** khởi chạy wizard phát hành KPI tùy theo nhu cầu:
   - **Cá nhân lẻ**: Dùng `hr.kpi.generate.wizard` để phát hành KPI cá nhân từ template `hr.kpi` cho các nhân viên được chọn, đồng thời liên kết vào đợt báo cáo quản lý `hr.performance.report`.
   - **Toàn phòng ban**: Dùng `hr.department.kpi.generate.wizard`. Hệ thống tự động tạo `hr.department.performance.evaluation` cho phòng ban, sau đó tạo một đợt báo cáo quản lý `hr.performance.report` riêng cho phòng ban và quét toàn bộ nhân viên hoạt động trong bộ phận để tạo các bản đánh giá cá nhân `hr.performance.evaluation` tương ứng nằm dưới sự quản lý của đợt báo cáo này.
2. Hệ thống tự động gửi thông báo hệ thống (Inbox/Chatter) kèm liên kết trực tiếp tới từng nhân viên để bắt đầu quy trình tự đánh giá.

### 2. Tự động tính toán chỉ số (Auto-Computation of Metrics)
Với các chỉ tiêu có thuộc tính tự động (`is_auto = True`), bộ máy **KPI Engine** (`hr.kpi.engine`) sẽ tự động tính toán giá trị thực tế (`actual`) trong khoảng thời gian đánh giá (`start_date` đến `end_date`):
* **Task hoàn thành (`done_task`)**: Đếm số lượng công việc được giao cho nhân viên đã hoàn thành (`stage_id.is_done_stage = True`) có hạn chót (`date_deadline`) nằm trong kỳ. Có thể tính theo số lượng (Value) hoặc tỷ lệ % hoàn thành trên tổng số task được giao (Percentage).
* **Task đúng hạn (`task_on_time`)**: Tỷ lệ % số task hoàn thành đúng hạn (`done_date <= date_deadline`) trên tổng số task đã hoàn thành được giao.
* **Đi muộn (`late_days`)**: Đếm số ngày đi muộn bằng cách so sánh giờ check-in đầu tiên trong ngày (`hr.attendance`) với giờ bắt đầu làm việc theo lịch (`resource.calendar.attendance`), có cộng thêm số phút đi trễ cho phép (`late_grace_minutes`).
* **Đi làm đầy đủ (`attendance_full`)**: So sánh số ngày phải làm theo lịch chuẩn (expected_raw), ngày thực tế đi làm (worked_days), ngày nghỉ có phép đã duyệt (approved_leave_days) và ngày nghỉ lễ chung (public_holiday_days). Engine tính toán số ngày nghỉ không phép (unpaid_leave_days) để đưa vào công thức phạt điểm.

> [!NOTE]
> Bộ tính toán tự động sử dụng múi giờ bản địa của nhân viên (ưu tiên Việt Nam `Asia/Ho_Chi_Minh`) để tránh hoàn toàn lệch múi giờ UTC gây sai số ngày làm việc đầu/cuối tháng.

### 3. Nhân viên Tự đánh giá (Self-Evaluation)
1. Phiếu đánh giá ban đầu ở trạng thái `self_evaluation`.
2. Nhân viên nhập đánh giá thực tế và bình luận của chính mình trên các chỉ tiêu định tính (Star rating, Binary, Score).
3. **Cơ chế phản hồi thời gian thực (Auto-Mirroring)**: Nhờ logic `onchange` và `write` được override trên `hr.performance.evaluation.line`, các giá trị tự đánh giá của nhân viên tự động được sao chép sang cột đánh giá của Quản lý khi phiếu ở trạng thái `self_evaluation`, giúp nhân viên xem trước kết quả điểm số tạm tính trực tiếp trên màn hình giao diện.
4. Nhân viên bấm **"Submit"** để chuyển trạng thái sang `manager_evaluating`. Hệ thống sẽ gửi email tự động và tag thông báo nhắc việc đến Quản lý phòng ban.

### 4. Quản lý Đánh giá & Điều chỉnh (Manager Evaluating)
1. Phiếu chuyển sang trạng thái `manager_evaluating`. Lúc này nhân viên bị khóa quyền ghi trên phiếu.
2. Quản lý thực hiện chỉnh sửa cột điểm của Quản lý, nhập ý kiến phản hồi và điều chỉnh điểm số nếu cần thiết.
3. Hệ thống áp dụng kiểm tra quyền chặt chẽ: Chỉ người dùng thuộc nhóm Manager (`group_manager`) hoặc HR (`group_hr`) mới được phép chỉnh sửa các trường của quản lý khi phiếu ở trạng thái này.

### 5. Duyệt & Hoàn tất (Finalization & Approval)
1. Quản lý hoặc nhân sự bấm **"Approve"** để hoàn tất phiếu, trạng thái chuyển sang `completed` và khóa toàn bộ dữ liệu (Read-only).
2. Khi phiếu được duyệt, hệ thống kích hoạt tính toán điểm số cuối cùng (`final_score`) kết hợp điểm phòng ban và điểm cá nhân theo trọng số cấu hình.
3. Điểm hiệu suất mới nhất của nhân viên sẽ tự động đồng bộ ngược lại trường `performance_score` trên model `hr.employee` để phục vụ công tác nhân sự, theo dõi và lập báo cáo.

---

## Cấu hình / Các Model

### 1. Template KPI Cá nhân (`hr.kpi` & `hr.kpi.line`)
Quản lý các chỉ tiêu hiệu suất mẫu thiết lập cho nhân viên.
* **`hr.kpi`**: Chứa thông tin chu kỳ (`period`), phòng ban liên kết (`department_id`) và danh sách dòng chỉ tiêu.
* **`hr.kpi.line`**: Từng dòng chỉ tiêu cụ thể.
  - `key_performance_area`: Tên chỉ tiêu đánh giá.
  - `kpi_type`: Loại KPI (`quantitative` - định lượng, `binary` - nhị phân, `rating` - đánh giá sao, `score` - nhập điểm trực tiếp).
  - `target_type`: Kiểu mục tiêu (`value` - giá trị số, `percentage` - tỷ lệ %).
  - `direction`: Chiều hướng đánh giá (`higher_better` - càng cao càng tốt, `lower_better` - càng thấp càng tốt).
  - `target`: Giá trị/Tỷ lệ mục tiêu đề ra.
  - `weight`: Trọng số của dòng chỉ tiêu (Tổng trọng số của tất cả các dòng không phải Section trong một Template bắt buộc nằm trong khoảng từ `99.9%` đến `100.1%` để đảm bảo tính toàn vẹn toán học).
  - `is_auto`: Đánh dấu KPI tự động thu thập từ hệ thống.
  - `data_source`: Nguồn dữ liệu tự động (`done_task`, `task_on_time`, `late_days`, `attendance_full`).

### 2. Template KPI Phòng ban (`hr.department.kpi` & `hr.department.kpi.line`)
Quản lý chỉ tiêu hiệu suất mẫu cấp phòng ban.
* **`hr.department.kpi`**: Chứa thông tin phòng ban, chu kỳ và trọng số pha trộn phòng ban `dept_weight` (mặc định là `0.4`, tức là điểm phòng ban chiếm 40% và điểm cá nhân chiếm 60% trong điểm tổng hợp cuối cùng).
* **`hr.department.kpi.line`**: Tương tự `hr.kpi.line` nhưng áp dụng cho cấp phòng ban với các nguồn tự động riêng biệt (`dept_task_completion` - tỷ lệ hoàn thành task của phòng, `dept_attendance_rate` - tỷ lệ đi làm của phòng, `dept_avg_individual` - điểm cá nhân trung bình của các nhân viên trong phòng).

### 3. Phiếu Đánh giá Cá nhân (`hr.performance.evaluation` & `hr.performance.evaluation.line`)
Bản ghi thực tế ghi nhận quá trình đánh giá của từng nhân viên.
* **`hr.performance.evaluation`**:
  - `employee_id`: Nhân viên được đánh giá.
  - `state`: Trạng thái luồng (`self_evaluation` → `manager_evaluating` → `completed` → `cancel`).
  - `performance_score`: Điểm KPI cá nhân (trung bình có trọng số của tất cả dòng chỉ tiêu).
  - `final_score`: Điểm KPI cuối cùng sau khi pha trộn với điểm phòng ban.
  - `performance_level` & `final_level`: Xếp loại tương ứng (`excellent` - Xuất sắc, `pass` - Đạt, `fail` - Không đạt) dựa trên ngưỡng điểm cấu hình.
  - `dept_evaluation_id`: Liên kết đến phiếu đánh giá của phòng ban tương ứng trong kỳ.
* **`hr.performance.evaluation.line`**: Ghi nhận chi tiết điểm số từng chỉ tiêu.
  - `employee_rating_*` & `employee_comment`: Kết quả tự đánh giá và ý kiến của nhân viên.
  - `manager_rating_*` & `manager_adjustment` & `manager_comment`: Điểm đánh giá, điểm điều chỉnh và ý kiến của quản lý.
  - `system_score`: Điểm số do hệ thống tính toán (đối với KPI định lượng).
  - `final_rating`: Điểm số chốt cuối cùng dùng để tính toán điểm tổng hợp (ưu tiên điểm quản lý nhập, nếu trống sẽ tự động lấy điểm nhân viên tự đánh giá hoặc điểm hệ thống tính).

### 4. Phiếu Đánh giá Phòng ban (`hr.department.performance.evaluation` & `hr.department.evaluation.line`)
Bản ghi đánh giá thực tế của cấp bộ phận.
* **`hr.department.performance.evaluation`**: Lưu trữ điểm trung bình phòng ban `dept_kpi_score` thu được từ các dòng chỉ tiêu cấp phòng ban.
* **`hr.department.evaluation.line`**: Chi tiết đánh giá chỉ tiêu cấp phòng ban.

### 5. Dashboard Quản lý Đánh giá (`hr.performance.report`)
Đóng vai trò là trung tâm dashboard để theo dõi và quản lý tập trung tất cả các phiếu đánh giá hiệu suất cá nhân `hr.performance.evaluation` của toàn bộ nhân viên thuộc cùng một phòng ban (`department_id`) trong cùng một chu kỳ (`period`). Hỗ trợ các chức năng quản trị:
* Giao diện Dashboard OWL thống kê nhanh số lượng phiếu đã hoàn thành, đang tự đánh giá hoặc đang chờ quản lý duyệt.
* Gửi thông báo và nhắc nhở thời hạn hoàn thành hàng loạt cho các nhân viên thuộc phòng ban quản lý.
* Tự động xuất báo cáo đánh giá hàng loạt cho cả phòng ban dưới dạng file Excel (`.xlsx`) được thiết kế và căn chỉnh chuyên nghiệp theo template mẫu.
* Cung cấp hàm API `get_report_dashboard_data` tổng hợp dữ liệu biểu đồ phân tích (phân bổ điểm số, xếp hạng nhân viên) trực quan trên giao diện Dashboard.

---

## Phân quyền

Hệ thống phân quyền được cấu hình chặt chẽ thông qua các Nhóm người dùng (Groups) và Quy tắc truy cập bản ghi (Record Rules) trong phân hệ `security.xml`:

### 1. Các Nhóm quyền (Security Groups)

| Nhóm quyền | Kế thừa quyền | Mô tả quyền hạn |
|---|---|---|
| **Employee** (`group_employee`) | Không | Quyền cơ bản nhất của nhân viên. Chỉ được phép xem các phiếu đánh giá của chính mình. Chỉ được phép chỉnh sửa các trường tự đánh giá khi phiếu ở trạng thái `self_evaluation`. |
| **Manager** (`group_manager`) | Employee | Quản lý bộ phận. Có quyền xem toàn bộ phiếu đánh giá của nhân viên thuộc phòng ban mình quản lý. Có quyền cấu hình KPI cho phòng ban và thực hiện đánh giá khi phiếu ở trạng thái `manager_evaluating`. |
| **HR** (`group_hr`) | Không | Nhân viên phòng HR. Có quyền quản trị toàn bộ hệ thống: tạo template, phát hành đợt đánh giá, xem và điều chỉnh tất cả các phiếu đánh giá của toàn bộ nhân viên công ty. |
| **Admin (Dev)** (`group_admin`) | HR | Quản trị hệ thống cấp cao. Có quyền can thiệp hệ thống và bypass các cấu hình nghiệp vụ thông thường. |

### 2. Quy tắc truy cập bản ghi (Record Rules)

Hệ thống áp dụng các miền lọc (domain) nghiêm ngặt để đảm bảo an toàn dữ liệu:

* **Đánh giá cá nhân (`hr.performance.evaluation`)**:
  - *Employee*: `[('employee_id.user_id', '=', user.id)]` — Chỉ truy cập phiếu của chính mình.
  - *Manager*: `[('employee_id.department_id.manager_id.user_id', '=', user.id)]` — Chỉ truy cập các phiếu của nhân viên thuộc phòng ban mình làm quản lý trực tiếp.
  - *HR & Admin*: `[(1, '=', 1)]` — Truy cập toàn bộ dữ liệu.
* **Dòng đánh giá cá nhân (`hr.performance.evaluation.line`)**:
  - Áp dụng các điều kiện tương tự thông qua quan hệ liên kết đến phiếu đánh giá cha (`evaluation_id.employee_id.user_id` / `evaluation_id.employee_id.department_id.manager_id.user_id`).
* **Đánh giá phòng ban (`hr.department.performance.evaluation`)**:
  - *Manager*: `[('department_id.manager_id.user_id', '=', user.id)]` — Chỉ xem bảng đánh giá của phòng ban mình quản lý.
  - *HR & Admin*: Toàn quyền.

---

## Hiệu năng & Xử lý Kỹ thuật

### 1. Thuật toán Tính điểm Chuẩn hóa (Standardized Scoring Algorithms)

Hệ thống quy đổi tất cả các kiểu dữ liệu chỉ tiêu về thang điểm 10 chuẩn hóa để tính toán trung bình có trọng số:

* **KPI Định lượng (`quantitative`)**:
  - Nếu `direction = 'higher_better'` (Càng cao càng tốt):
    $$\text{system\_score} = \min\left(\frac{\text{actual}}{\text{target}} \times 10.0, 10.0\right)$$
  - Nếu `direction = 'lower_better'` (Càng thấp càng tốt):
    $$\text{system\_score} = \min\left(\frac{\text{target}}{\text{actual}} \times 10.0, 10.0\right)$$
  - **Trường hợp đặc biệt `late_days` (Số ngày đi muộn)**: Điểm số bắt đầu từ 10.0 điểm, mỗi ngày đi muộn bị trừ thẳng 1.0 điểm:
    $$\text{system\_score} = \max(10.0 - (\text{late\_days} \times 1.0), 0.0)$$
  - **Trường hợp đặc biệt `attendance_full` (Đi làm đầy đủ)**: Nếu nhân viên phát sinh bất kỳ ngày nghỉ không phép nào (`attendance_has_unpaid_leave = True`), điểm hệ thống lập tức quy về $0.0$ điểm để răn đe kỷ luật lao động. Nếu nghỉ phép hợp lệ, điểm số được tính toán dựa trên tỷ lệ chuyên cần trừ dần từ 10 điểm.
* **KPI Đánh giá sao (`rating`)**: Quy đổi 0-5 sao sang thang điểm 10:
  $$\text{score} = \frac{\text{rating\_star}}{5.0} \times 10.0$$
* **KPI Nhị phân (`binary`)**: Trả lời 'Yes' = 10.0 điểm, 'No' = 0.0 điểm.
* **KPI Nhập điểm (`score`)**: Nhận trực tiếp giá trị float nhập vào từ thang điểm 0-10.

### 2. Công thức Pha trộn Điểm phòng ban (Blending Score Formula)

Điểm tổng hợp cuối cùng của nhân viên được tính toán tự động khi phiếu hoàn tất:
$$\text{final\_score} = (\text{dept\_kpi\_score} \times \text{dept\_weight}) + (\text{performance\_score} \times (1.0 - \text{dept\_weight}))$$

#### Quy tắc nghiệp vụ xử lý ngoại lệ:
- Phiếu chưa liên kết đánh giá phòng ban hoặc đánh giá phòng ban bị hủy (`cancel`): Điểm số phòng ban không được đưa vào tính toán, hệ thống tự động gán $\text{final\_score} = \text{performance\_score}$ để bảo vệ quyền lợi của nhân viên.
- Nếu không có cấu hình template phòng ban cụ thể, trọng số `dept_weight` mặc định lấy là `0.4`.

### 3. Tối ưu hóa hiệu năng & Chống Race Condition
* **Lưu trữ vật lý các trường Computed (`store=True`)**: Các trường điểm số quan trọng như `performance_score`, `final_score`, `dept_kpi_score` đều được cấu hình lưu trữ vật lý trên Database. Điều này giúp hiển thị List View, Kanban View và tải dữ liệu lên Dashboard OWL cực kỳ nhanh chóng, loại bỏ hoàn toàn vấn đề N+1 truy vấn thường gặp.
* **Tối ưu hóa Truy vấn KPI Engine**: Engine sử dụng các phương thức SQL Aggregation (`search_count` trực tiếp) thay vì duyệt qua các recordset để đếm số lượng task hoàn thành, giúp nâng tốc độ thực thi lên gấp nhiều lần.
* **Xử lý bất đồng bộ bằng Cron job**: Các tác vụ nặng như tự động quét và tính toán chỉ số KPI hệ thống hàng loạt (`_cron_compute_auto_kpi`) hay quét gửi thông báo nhắc nhở hạn chót (`_cron_send_deadline_reminder`) được tách ra chạy ngầm bằng Odoo Cron theo các đợt (batch) giới hạn để tránh lock Database và quá tải bộ nhớ.

---

## Edge cases & Lưu ý

1. **Nhân viên hoặc Phòng ban bị vô hiệu hóa/Xóa**:
   - Các bản ghi đánh giá cũ vẫn được bảo toàn dữ liệu lịch sử trên DB. Tên nhân viên và phòng ban cũ vẫn được lưu trữ hoặc hiển thị an toàn.
   - Các Wizard phát hành KPI hàng loạt luôn lọc điều kiện `('active', '=', True)` để tránh phát sinh phiếu thừa cho các nhân viên đã nghỉ việc.
2. **Tổng trọng số không đạt 100%**:
   - Bộ kiểm tra ràng buộc dữ liệu (`_check_total_weight`) trên Template KPI sẽ ngăn chặn người dùng lưu bản ghi nếu tổng trọng số các dòng chỉ tiêu không bằng 1.0 (cho phép sai số siêu nhỏ trong khoảng từ $99.9\%$ đến $100.1\%$ để tránh lỗi làm tròn số học).
3. **Nghỉ phép trùng ngày nghỉ lễ**:
   - Khi tính toán chỉ số chuyên cần (`attendance_full`), nếu nhân viên xin nghỉ phép trùng vào ngày lễ của công ty, hệ thống sẽ ưu tiên ghi nhận là nghỉ phép (`approved_leave_days`) để đảm bảo không bị trừ trùng lặp trong các phép tính toán thời gian làm việc danh nghĩa.
4. **Không có đánh giá của Quản lý**:
   - Nếu Quản lý không nhập đánh giá cho các chỉ tiêu định tính, hệ thống sẽ tự động sử dụng kết quả tự đánh giá của nhân viên làm kết quả chốt cuối cùng để tính điểm trung bình, tránh việc chỉ tiêu bị bỏ trống gây sai lệch điểm số chung.

---

## Chạy tests

Để đảm bảo tính ổn định và chính xác của hệ thống, các trường hợp nghiệp vụ, công thức tính toán và phân quyền cần được xác thực qua bộ kiểm thử tự động của Odoo. 

Lệnh khởi chạy kiểm thử đối với module Performance Evaluator:
```bash
odoo-bin -d <db_name> -u custom_adecsol_hr_performance_evaluator --test-enable --stop-after-init
```

### Các lớp kiểm thử chuẩn hóa cần tích hợp bổ sung:
* `TestPerformanceEvaluation` — Kiểm tra luồng trạng thái của phiếu (Self Evaluation → Manager Evaluating → Completed), chặn quyền sửa đổi của nhân viên khi chuyển trạng thái và xác thực tự động đồng bộ hóa điểm số.
* `TestKpiEngine` — Kiểm tra tính chính xác của KPI Engine đối với các nguồn dữ liệu tự động (`done_task`, `late_days`, `attendance_full`), xác minh xử lý múi giờ và tính chuyên cần.
* `TestScoringLogic` — Xác thực các công thức quy đổi thang điểm 10 chuẩn hóa, kiểm tra ràng buộc tổng trọng số của template KPI và công thức pha trộn điểm phòng ban.
* `TestPerformanceSecurity` — Kiểm tra phân quyền truy cập bản ghi giữa Employee, Manager và HR, đảm bảo nhân viên không thể xem hoặc sửa phiếu của người khác.
