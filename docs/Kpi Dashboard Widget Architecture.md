# Kpi Dashboard Widget Architecture: Business Logic Matrix

## 1. Core Concepts (Khái niệm cốt lõi)
Hệ thống KPI Dashboard được thiết kế dựa trên một ma trận 2x2. Cấu trúc hiển thị và luồng truy vấn dữ liệu (Query Logic) của bất kỳ biểu đồ nào cũng được quyết định bởi giao điểm của 2 trường:
- **`dashboard_kind` (Mặt trận hiển thị):** 'individual' (Cá nhân) hoặc 'department' (Phòng ban).
- **`widget_class` (Quy mô dữ liệu):** 'micro' (Chi tiết 1 chỉ tiêu) hoặc 'macro' (Tổng hợp động nhiều chỉ tiêu/nhiều người).

Dưới đây là đặc tả nghiệp vụ (Business Logic) và cách triển khai Code cho 4 trường hợp giao điểm này.

---

## 2. The 4 Business Cases (Đặc tả 4 trường hợp)

### CASE 1: Individual + Micro (Dashboard Cá nhân - Soi chi tiết 1 KPI)
- **Business Need:** Nhân viên muốn xem tiến độ thực hiện của MỘT chỉ tiêu cụ thể của chính mình (VD: "Tháng này mình đã bán được bao nhiêu doanh số so với Target?").
- **Query Logic:** - Model: `hr.kpi.evaluation.line`
  - Domain: `[('evaluation_id', '=', current_evaluation.id), ('data_source_id', '=', widget.data_source_id.id)]`
- **Output:** Trả về biểu đồ Target vs Actual (Cột/Bánh) hoặc chuỗi dữ liệu hàng ngày (Daily Series) của ĐÚNG 1 dòng KPI đó.

### CASE 2: Individual + Macro (Dashboard Cá nhân - Nhìn toàn cảnh phong độ)
- **Business Need:** Nhân viên muốn nhìn bức tranh tổng thể: "Năng lực cốt lõi của mình đang mạnh/yếu ở đâu?", "Phong độ 6 tháng qua của mình thế nào?", hoặc "Tháng này mình đang đứng thứ mấy trong phòng?".
- **Query Logic:**
  - **Radar Chart:** Query `evaluation.line` của phiếu hiện tại, lọc các dòng định tính (không có data_source).
  - **Trend Line:** Dùng Query Builder (Target model = `evaluation`), Domain: `[('employee_id', '=', current_evaluation.employee_id.id), ('state', '=', 'done')]`. Nhóm theo Tháng. Màu dây: `#3b82f6` (Xanh dương).
  - **Distribution (Xếp hạng):** Dùng Query Builder lấy TOÀN BỘ phiếu của phòng ban trong tháng. Gom nhóm theo `employee_id`. 
- **UX/Coloring Logic ĐẶC BIỆT:** Khi vẽ Distribution cho cá nhân, phải bôi màu Vàng (`#f59e0b`) cho cột của chính nhân viên đó để làm nổi bật, các đồng nghiệp khác bôi màu xám (`#e5e7eb`).

### CASE 3: Department + Micro (Dashboard Phòng ban - So sánh chéo 1 KPI cụ thể)
- **Business Need:** Trưởng phòng muốn so sánh năng lực thực thi của TẤT CẢ nhân viên trên CÙNG 1 CHỈ TIÊU (VD: "Trong số KPI Doanh số, ai đang bán tốt nhất?"). Hoặc xem tiến độ KPI chung của cả phòng.
- **Query Logic:**
  - Model: `hr.kpi.evaluation.line`
  - Domain: `[('evaluation_id.department_id', '=', current_evaluation.department_id.id), ('evaluation_id.period_id', '=', current_evaluation.period_id.id), ('data_source_id', '=', widget.data_source_id.id), ('evaluation_id.state', 'not in', ['draft', 'cancel'])]`
- **Output:** Biểu đồ Bar Chart. Trục X là tên của từng nhân viên, Trục Y gồm 2 cột so sánh Actual (Thực tế) và Target (Mục tiêu).

### CASE 4: Department + Macro (Dashboard Phòng ban - Phân tích dữ liệu động)
- **Business Need:** Trưởng phòng (hoặc Ban Giám Đốc) cần các công cụ BI động để vẽ bất kỳ báo cáo tổng hợp nào. VD: So sánh Tổng điểm (final_score) của nhân viên, Xu hướng điểm tự đánh giá, hoặc Trung bình điểm kỹ năng mềm của cả phòng.
- **Query Logic:** - Sử dụng Đầy đủ sức mạnh của **Multi-Model Query Builder**.
  - `target_model`: Có thể là `evaluation` (Phiếu tổng) hoặc `evaluation_line` (Chi tiết tiêu chí).
  - `measure_field_id` và `group_by_field_id`: Quyết định trục Y và Trục X.
  - Domain: `[('department_id', '=', current_evaluation.department_id.id), ('period_id', '=', current_evaluation.period_id.id)]` (Hoặc trỏ qua `evaluation_id.department_id` nếu là bảng line).
- **UX/Coloring Logic:** Vẽ Trend Line dùng màu xanh lá (`#10b981`). Vẽ Distribution (Bar chart) tô toàn bộ các cột màu xanh dương đồng đều (`#3b82f6`) thể hiện sự công bằng khi sếp nhìn vào tập thể.

---

## 3. Developer Guidelines (Nguyên tắc lập trình cho Chart Service)

Khi triển khai hàm `build_dynamic_charts` và các hàm helper trong file `hr_kpi_dashboard_chart_service.py`, cần tuân thủ nghiêm ngặt:
1. **Routing thông minh:** Lấy `widget.widget_class` và biến context `dashboard_kind` làm kim chỉ nam để điều hướng (if/elif) vào đúng hàm xử lý (VD: `_build_micro_dept_comparison` vs `_build_micro_individual`).
2. **Generic Query Safety:** Khi sử dụng Macro Query Builder, luôn kiểm tra `target_model` để xây dựng `base_domain` tương ứng nhằm tránh lỗi Field Error từ ORM. Luôn bọc `safe_eval` khi xử lý `widget.filter_domain`.
3. **Many2one Tuple Handling:** Khi hàm `read_group` gom nhóm bằng một field Many2one (như `employee_id`), kết quả trả về là tuple `(id, 'Tên')`. Code xử lý data phải tự động parse tuple này để lấy tên ném vào labels của Chart.js.