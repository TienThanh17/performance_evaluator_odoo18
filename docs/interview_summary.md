# HR Performance Evaluator (custom_adecsol_hr_performance_evaluator) – Tóm tắt để trả lời phỏng vấn

## 1) Mục tiêu & bài toán giải quyết
Module **ADEC SOL HR Performance Evaluator** giúp doanh nghiệp **đánh giá hiệu suất nhân sự theo KPI** ngay trong Odoo.

Bài toán thực tế:
- KPI và đánh giá thường làm bằng Excel/Google Sheet → khó chuẩn hoá, khó phân quyền, khó lưu lịch sử.
- Cần một quy trình: **tạo bộ KPI chuẩn (template) → tạo phiếu đánh giá theo kỳ → nhân viên tự đánh giá → quản lý duyệt/chốt → ra điểm và xếp hạng**.
- Một số KPI nên **tự động lấy dữ liệu** từ các phân hệ sẵn có của Odoo (Project task, Attendance, Leave).

## 2) Phạm vi module / tích hợp hệ thống
Theo `__manifest__.py`, module phụ thuộc:
- `hr`, `contacts`, `mail` (nhân sự + giao tiếp/thông báo)
- `project`, `project_task_done_date` (KPI theo công việc/task)
- `hr_attendance` (KPI đi trễ/đi làm)
- `hr_holidays` (KPI nghỉ phép / nghỉ không phép)

Tức là module đóng vai trò “**lớp nghiệp vụ đánh giá**” nằm trên dữ liệu HR/Project/Attendance/Leave có sẵn.

## 3) Các chức năng chính (nói kiểu phỏng vấn)
### 3.1. Quản lý KPI Template (định nghĩa bộ KPI)
- Tạo **KPI Template** theo phòng ban/vị trí (tuỳ thiết kế).
- Mỗi template có nhiều **KPI lines** và có thể có **Section** để nhóm theo *Key Performance Area*.
- Mỗi KPI line có:
  - `kpi_type`: cách chấm (định lượng / đạt-không-đạt / rating / score)
  - `target`, `target_type` (value hoặc percentage)
  - `direction` (higher_better / lower_better) cho KPI định lượng
  - `weight`: trọng số
  - cờ chu kỳ áp dụng: `is_monthly`, `is_quarterly`, `is_half_yearly`, `is_yearly`
  - `is_auto` + `data_source`: KPI tự động lấy dữ liệu (manual / task_on_time / late_days / attendance_full)

### 3.2. Tạo Performance Evaluation (phiếu đánh giá theo kỳ)
Model chính: `hr.performance.evaluation`.
- Khi tạo phiếu, module tự lấy **khoảng thời gian (start/end)** và **deadline** từ `evaluation.alert` đang active.
- Khi user chọn `kpi_id` (template), hệ thống tự **generate evaluation lines**:
  - lọc template lines theo cờ chu kỳ tương ứng (`is_{period}`)
  - giữ thứ tự theo `sequence`
  - giữ nguyên các dòng section để UI hiển thị phân nhóm

### 3.3. Workflow: Draft → Submitted → Approved (và Cancel)
- **Draft**: nhân viên nhập self-assessment hoặc nhập actual (tuỳ KPI).
- **Submit** (`action_submit`):
  - Validate dữ liệu bắt buộc cho các KPI manual không-định-lượng (binary/rating/score).
  - Tự động copy *employee rating* sang *manager rating* làm baseline.
- **Approve** (`action_approve`): quản lý chốt kết quả.
- **Cancel**: khoá phiếu.

### 3.4. Compute KPI tự động (automation)
- Nút/Action `action_compute_auto_kpi()` gọi `hr.kpi.engine` để tính `actual` cho các evaluation lines có `is_auto=True`.
- Engine hiện hỗ trợ các data sources:
  - `task_on_time`: KPI task hoàn thành đúng hạn trong khoảng thời gian.
  - `late_days`: KPI số ngày đi trễ (so với lịch làm việc + grace minutes).
  - `attendance_full`: KPI “full attendance metrics” (expected/worked/leave/holiday/unpaid leave) và trả thêm metrics.

## 4) Dữ liệu & mô hình (Data model) – nói gọn nhưng đúng
Các model cốt lõi:
- `hr.kpi`: KPI template.
- `hr.kpi.line`: dòng KPI/section trong template.
- `hr.performance.evaluation`: phiếu đánh giá theo kỳ cho 1 nhân viên.
- `hr.performance.evaluation.line`: snapshot KPI line tại thời điểm đánh giá (chứa target/weight/type/actual và các rating).
- `evaluation.alert`: định nghĩa kỳ đánh giá đang active (period + start/end/deadline).
- `hr.kpi.engine` (AbstractModel): engine tính toán `actual` từ các hệ thống liên quan.

Quan hệ:
- 1 `hr.kpi` → N `hr.kpi.line`
- 1 `hr.performance.evaluation` → N `hr.performance.evaluation.line`
- `evaluation.line.kpi_line_id` link về template line để trace nguồn.

## 5) Cách tính điểm & xếp hạng tổng
### 5.1. Điểm tổng (Average Score)
Trên `hr.performance.evaluation` có `performance_score` (thang 10, digits 1):
- Tính theo **trung bình có trọng số**:
  - \(score = \sum(final\_rating_i * weight_i) / \sum(weight_i)\)

### 5.2. Xếp loại Excellent / Pass / Fail
- Dựa vào `performance_score` và 2 ngưỡng cấu hình bằng `ir.config_parameter`:
  - `custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent` (mặc định 9)
  - `custom_adecsol_hr_performance_evaluator.kpi_threshold_pass` (mặc định 5)

UI dùng `performance_badge_class` để tô màu badge theo level.

> Ghi chú: công thức chi tiết theo từng KPI type (System Score + Manager Adjustment) nằm trong `docs/kpi_scoring.md`.

## 6) Các điểm kỹ thuật đáng nói khi phỏng vấn (implementation highlights)
1. **Generate lines theo chu kỳ**: dùng `onchange(kpi_id)` để build one2many lines theo `period`, đảm bảo đúng thứ tự và giữ section.
2. **Validation trước submit**: chặn thiếu dữ liệu cho KPI manual không-định-lượng → tránh “submit rỗng”.
3. **Automation engine tách riêng**: `hr.kpi.engine` là AbstractModel để dễ mở rộng data_source mới mà không phá core model.
4. **Attendance KPI tính đúng theo calendar + timezone**:
   - tính “expected work days” theo resource calendar
   - xét global leaves (ngày lễ) và validated leaves
   - xử lý timezone để không lệch ngày đầu/cuối kỳ
5. **Configuration qua Settings**: thresholds + late grace minutes lưu bằng system parameters.
6. **UI/UX**:
   - module có JS widgets cho one2many (kpi/evaluation) để thao tác add section/add KPI lines mượt hơn
   - SCSS tạo badges và layout cho màn hình đánh giá.

## 7) Cách kể “1 câu chuyện end-to-end” trong 60–90 giây
1. HR tạo **Evaluation Alert** cho kỳ tháng/quý (start/end/deadline).
2. HR/Manager tạo **KPI Template** cho phòng ban: nhóm theo Section, set trọng số, set KPI auto (task/attendance).
3. Manager tạo **Performance Evaluation** cho từng nhân viên → hệ thống auto fill ngày theo alert và auto sinh evaluation lines.
4. Nhân viên nhập self-assessment và submit → hệ thống validate + copy baseline sang manager.
5. Manager review, bấm Compute KPI (nếu có KPI auto), chỉnh manager rating và approve.
6. Hệ thống tính `performance_score` theo weighted average và xếp loại Excellent/Pass/Fail.

## 8) Gợi ý câu hỏi phỏng vấn hay gặp + câu trả lời ngắn
**Q: Vì sao cần `evaluation.alert`?**  
A: Để “đóng khung” kỳ đánh giá (period + start/end/deadline) và đảm bảo mọi phiếu dùng cùng mốc thời gian, tránh user tự chọn sai kỳ.

**Q: Muốn thêm KPI tự động mới thì làm như nào?**  
A: Thêm lựa chọn `data_source` ở KPI line, rồi implement hàm compute tương ứng trong `hr.kpi.engine` (hoặc tách method), cuối cùng gắn vào action compute.

**Q: Điểm tổng tính thế nào?**  
A: Weighted average của `final_rating` theo `weight`, sau đó so với thresholds để ra level.

