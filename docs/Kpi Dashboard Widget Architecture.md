# Kpi Dashboard Widget Architecture: Business Logic Matrix

## 1. Core Concepts (Khái niệm cốt lõi)
Hệ thống KPI Dashboard được thiết kế dựa trên một ma trận 2x2. Cấu trúc hiển thị và luồng truy vấn dữ liệu (Query Logic) của bất kỳ biểu đồ nào cũng được quyết định bởi giao điểm của 2 trường:
- **`dashboard_kind` (Mặt trận hiển thị):** 'individual' (Cá nhân) hoặc 'department' (Phòng ban).
- **`widget_class` (Quy mô dữ liệu):** 'micro' (Chi tiết 1 chỉ tiêu) hoặc 'macro' (Tổng hợp động nhiều chỉ tiêu/nhiều người).

Ngoài ma trận 2x2 ở trên, code hiện tại còn có các khóa điều hướng nghiệp vụ cấp 2:
- Với **micro widget**, logic thực thi còn phụ thuộc vào `provider_key`; riêng dashboard phòng ban phụ thuộc thêm `department_micro_mode`.
- Với **macro widget**, logic thực thi phụ thuộc vào `macro_widget_type`, `target_model`, `measure_field_id`, `group_by_field_id`, `date_granularity` và `filter_domain`.

Dưới đây là đặc tả nghiệp vụ (Business Logic) và cách triển khai Code cho 4 trường hợp giao điểm này.

---

## 2. The 4 Business Cases (Đặc tả 4 trường hợp)

### CASE 1: Individual + Micro (Dashboard Cá nhân - Soi chi tiết 1 KPI)
- **Business Need:** Nhân viên muốn xem tiến độ thực hiện của MỘT chỉ tiêu cụ thể của chính mình (VD: "Tháng này mình đã bán được bao nhiêu doanh số so với Target?").
- **Query Logic:**
  - Không search trực tiếp toàn bảng, mà lấy từ `current_evaluation.evaluation_line_ids`.
  - Chỉ nhận các dòng thỏa: `is_section = False`, `kpi_type = 'auto'`, `data_source_id = widget.data_source_id`.
  - Nếu có nhiều dòng khớp thì chỉ lấy **dòng đầu tiên** để dựng chart.
  - Sau khi bắt đúng dòng KPI, hệ thống route tiếp theo `provider_key` của widget.
- **Output theo provider:**
  - `generic_target_actual_bar`: dựng biểu đồ Target vs Actual cho đúng 1 dòng KPI, hỗ trợ `bar` hoặc `doughnut`.
  - `generic_domain_daily_series`: dựng chuỗi dữ liệu theo ngày từ `data_source` dạng domain, yêu cầu source có `date_field` và `aggregation` thuộc `count/sum/avg`; dữ liệu có thể chạy theo kiểu `cumulative` hoặc `maintenance` tùy `kpi_behavior`.
  - `special_engine_punctuality`: dựng line chart giờ check-in từng ngày bằng engine chấm công.

### CASE 2: Individual + Macro (Dashboard Cá nhân - Nhìn toàn cảnh phong độ)
- **Business Need:** Nhân viên muốn nhìn bức tranh tổng thể: "Năng lực cốt lõi của mình đang mạnh/yếu ở đâu?", "Phong độ 6 tháng qua của mình thế nào?", hoặc "Tháng này mình đang đứng thứ mấy trong phòng?".
- **Query Logic:**
  - **Radar Chart:** Chỉ chạy cho dashboard cá nhân. Dữ liệu lấy từ `evaluation_line_ids` của phiếu hiện tại, lọc các dòng định tính `not is_section` và **không có `data_source_id`**.
  - **Trend Line:** Dùng Query Builder động, hỗ trợ cả `target_model = evaluation` hoặc `evaluation_line`. Domain gốc là theo đúng nhân viên hiện tại và chỉ loại `state = cancel`, không bắt buộc `state = done`, không khóa theo kỳ. Nếu group theo field ngày/giờ thì hệ thống dùng `date_granularity` để tạo biểu thức groupby. Kết quả lấy **6 nhóm gần nhất**, sau đó đảo thứ tự để hiển thị từ cũ đến mới. Màu dây: `#3b82f6`.
  - **Distribution (Xếp hạng/Phân phối):** Dùng Query Builder động, hỗ trợ cả `evaluation` hoặc `evaluation_line`. Domain gốc lấy toàn bộ dữ liệu của **đúng phòng ban và đúng kỳ** của phiếu hiện tại, sau đó group theo `group_by_field_id` được cấu hình; không bị cố định là `employee_id`.
- **UX/Coloring Logic ĐẶC BIỆT:** Khi vẽ Distribution cho cá nhân, phải bôi màu Vàng (`#f59e0b`) cho cột của chính nhân viên đó để làm nổi bật, các đồng nghiệp khác bôi màu xám (`#e5e7eb`).
  - Lưu ý: việc tô vàng chỉ xảy ra khi widget đang group theo `employee_id`; nếu group theo field khác thì toàn bộ cột sẽ dùng màu xám.

### CASE 3: Department + Micro (Dashboard Phòng ban - So sánh chéo 1 KPI cụ thể)
- **Business Need:** Trưởng phòng muốn hoặc so sánh năng lực thực thi của TẤT CẢ nhân viên trên CÙNG 1 CHỈ TIÊU, hoặc xem tiến độ KPI chung của chính phiếu đánh giá phòng ban hiện tại.
- **Query Logic:**
  - Code hiện tại tách thành 2 nhánh theo `department_micro_mode`.
  - **Mode `employee_compare`:**
    - Query model `hr.performance.evaluation.line`.
    - Domain thực tế: `is_section = False`, `kpi_type = 'auto'`, `data_source_id = widget.data_source_id`, `evaluation_id.department_id = current_evaluation.department_id`, `evaluation_id.period_id = current_evaluation.period_id`, `evaluation_id.state != 'cancel'`.
    - Sau khi search, hệ thống chỉ giữ **dòng mới nhất của mỗi nhân viên** rồi mới đưa vào biểu đồ so sánh.
    - Output mặc định là so sánh `Target` và `Actual` theo từng nhân viên; nếu widget cấu hình `doughnut` thì code tự ép về `bar`, còn `line` vẫn được phép dùng.
  - **Mode `department_progress`:**
    - Không search chéo toàn bộ nhân viên, mà lấy trực tiếp `evaluation_line_ids` của phiếu đánh giá phòng ban hiện tại.
    - Chỉ nhận các dòng thỏa: `is_section = False`, `kpi_type = 'auto'`, `data_source_id = widget.data_source_id`.
    - Nếu chỉ có 1 dòng KPI khớp thì dựng chart tiến độ cho riêng KPI đó.
    - Nếu có nhiều dòng KPI khớp thì dựng biểu đồ so sánh Target/Actual giữa các dòng KPI của phòng ban; nếu cấu hình `doughnut` thì code tự ép về `bar`.

### CASE 4: Department + Macro (Dashboard Phòng ban - Phân tích dữ liệu động)
- **Business Need:** Trưởng phòng (hoặc Ban Giám Đốc) cần các công cụ BI động để vẽ bất kỳ báo cáo tổng hợp nào. VD: So sánh Tổng điểm (final_score) của nhân viên, Xu hướng điểm tự đánh giá, hoặc Trung bình điểm kỹ năng mềm của cả phòng.
- **Query Logic:** Sử dụng đầy đủ sức mạnh của **Multi-Model Query Builder**.
  - `target_model`: Có thể là `evaluation` (Phiếu tổng) hoặc `evaluation_line` (Chi tiết tiêu chí).
  - `measure_field_id` và `group_by_field_id`: Quyết định trục Y và Trục X.
  - `macro_widget_type = radar_chart` hiện **không chạy cho dashboard phòng ban**; code chỉ cho radar ở dashboard cá nhân.
  - Với **Trend Line**, domain gốc chỉ khóa theo `department_id` và `state != 'cancel'` (hoặc `evaluation_id.department_id` nếu target là line), **không khóa theo kỳ**; sau đó cộng thêm `filter_domain` nếu cấu hình.
  - Với **Distribution**, domain gốc khóa theo `department_id`, `period_id` và `state != 'cancel'` (hoặc `evaluation_id.*` nếu target là line); sau đó cộng thêm `filter_domain` nếu cấu hình.
  - Cả Trend Line và Distribution đều dùng `read_group` với phép tổng hợp `avg` cho `measure_field_id`.
- **UX/Coloring Logic:** Vẽ Trend Line dùng màu xanh lá (`#10b981`). Vẽ Distribution (Bar chart) tô toàn bộ các cột màu xanh dương đồng đều (`#3b82f6`) thể hiện sự công bằng khi sếp nhìn vào tập thể.

---

## 3. Developer Guidelines (Nguyên tắc lập trình cho Chart Service)

Khi triển khai hàm `build_dynamic_charts` và các hàm helper trong file `hr_kpi_dashboard_chart_service.py`, cần tuân thủ nghiêm ngặt:
1. **Routing thông minh:** Lấy `widget.widget_class` và biến context `dashboard_kind` để route vào đúng nhánh `_build_individual_micro_chart`, `_build_department_micro_chart` hoặc `_build_macro_chart`. Trong nhánh micro phải route tiếp theo `provider_key`; riêng dashboard phòng ban phải route thêm theo `department_micro_mode`.
2. **Generic Query Safety:** Khi sử dụng Macro Query Builder, luôn kiểm tra `target_model` để xây dựng `base_domain` tương ứng nhằm tránh lỗi Field Error từ ORM. `widget.filter_domain` phải được parse bằng `safe_eval`; nếu parse lỗi thì chỉ log warning và bỏ qua filter động, không làm vỡ dashboard.
3. **Many2one Tuple Handling:** Khi hàm `read_group` gom nhóm bằng một field Many2one (như `employee_id`), kết quả trả về là tuple `(id, 'Tên')`. Code xử lý data phải tự động parse tuple này để lấy tên ném vào labels của Chart.js.
4. **Nhất quán dữ liệu micro:** Với micro widget, luôn lọc bỏ `is_section = True`; các nhánh đang dùng dữ liệu KPI tự động phải lọc thêm `kpi_type = 'auto'` để tránh kéo nhầm dòng thủ công hoặc dòng tiêu đề vào biểu đồ.
