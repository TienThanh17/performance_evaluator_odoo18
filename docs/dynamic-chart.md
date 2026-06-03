# Role
Bạn là một Senior Odoo 18 Developer. Chúng ta đang tiếp tục nâng cấp module KPI Dashboard.

# Context & Objective
Hiện tại Macro Widget đang là một Dynamic Query Builder hoạt động hoàn hảo trên model cha `hr.kpi.evaluation`. 
Tuy nhiên, business cần mở rộng: Macro Widget (cho các chart Trend và Distribution) phải cho phép người dùng chọn nguồn dữ liệu là bảng cha (`hr.kpi.evaluation`) HOẶC bảng con (`hr.kpi.evaluation.line`).

Mục tiêu của bạn:
1. Thêm trường `target_model` vào `hr.kpi.dashboard.widget`.
2. Cập nhật lại domain của `measure_field_id` và `group_by_field_id` trên giao diện XML để nó lọc linh hoạt danh sách field theo `target_model` mà user chọn.
3. Cập nhật backend (Chart Service) để linh hoạt thay đổi `model_name` và `base_domain` dựa trên `target_model`.

# Yêu cầu thực thi (Làm theo 3 bước sau)

## Bước 1: Cập nhật Model `hr.kpi.dashboard.widget`
- Thêm trường `target_model`:
  ```python
  target_model = fields.Selection([
      ('evaluation', 'Phiếu đánh giá tổng (Evaluation)'),
      ('evaluation_line', 'Chi tiết tiêu chí (Evaluation Line)')
  ], string="Nguồn truy vấn (Model)", default='evaluation', required=True)
  ```

  Nới lỏng domain ở file Python cho 2 trường measure_field_id và group_by_field_id:

measure_field_id: domain="[('model', 'in', ['hr.kpi.evaluation', 'hr.kpi.evaluation.line']), ('ttype', 'in', ['float', 'integer', 'monetary'])]"

group_by_field_id: domain="[('model', 'in', ['hr.kpi.evaluation', 'hr.kpi.evaluation.line']), ('store', '=', True)]"

## Bước 2: Cập nhật XML Form View của Widget
Trong view form của hr.kpi.dashboard.widget, phần cấu hình Macro:

Đặt field target_model lên trên cùng của khối cấu hình Macro.

Ghi đè domain của measure_field_id và group_by_field_id trên XML để nó thay đổi động (dynamic domain) theo target_model:

XML
<field name="measure_field_id" options="{'no_create': True}"
       invisible="macro_widget_type == 'radar_chart'"
       domain="[('model', '=', target_model == 'evaluation' and 'hr.kpi.evaluation' or 'hr.kpi.evaluation.line'), ('ttype', 'in', ['float', 'integer', 'monetary'])]"/>

<field name="group_by_field_id" options="{'no_create': True}"
       invisible="macro_widget_type == 'radar_chart'"
       domain="[('model', '=', target_model == 'evaluation' and 'hr.kpi.evaluation' or 'hr.kpi.evaluation.line'), ('store', '=', True)]"/>

## Bước 3: Cập nhật Logic ở Chart Service (hr_kpi_dashboard_chart_service.py)
Trong 2 hàm _build_macro_trend và _build_macro_distribution, bạn cần trích xuất model_name và xây dựng base_domain dựa vào target_model.

Ví dụ cấu trúc cho _build_macro_distribution:

```Python
def _build_macro_distribution(self, evaluation, widget):
        # 1. Xác định Model
        model_name = 'hr.kpi.evaluation' if widget.target_model == 'evaluation' else 'hr.kpi.evaluation.line'
        
        # 2. Xây dựng Base Domain tùy theo Model
        if widget.target_model == 'evaluation':
            domain = [
                ('department_id', '=', evaluation.department_id.id),
                ('period_id', '=', evaluation.period_id.id),
                ('state', 'not in', ['draft', 'cancel'])
            ]
        else: # evaluation_line
            domain = [
                ('evaluation_id.department_id', '=', evaluation.department_id.id),
                ('evaluation_id.period_id', '=', evaluation.period_id.id),
                ('evaluation_id.state', 'not in', ['draft', 'cancel'])
            ]
            
        # 3. Kế thừa logic cũ: Áp dụng filter_domain, xác định measure, groupby
        # ... [Giữ nguyên code xử lý measure_field_id và group_by_field_id cũ] ...
        
        # 4. Thực thi truy vấn với model_name động
        distribution_data = self.env[model_name].read_group(
            domain=domain,
            fields=[f"{measure}:avg"],
            groupby=[groupby]
        )
        
        # ... [Giữ nguyên code vẽ chart và tô màu cũ] ...
```

Tương tự cho _build_macro_trend:

Nếu target_model == 'evaluation': Base domain dùng ('employee_id', '=', ...) hoặc ('department_id', '=', ...).

Nếu target_model == 'evaluation_line': Base domain phải truy xuất qua quan hệ, ví dụ: ('evaluation_id.employee_id', '=', ...) hoặc ('evaluation_id.department_id', '=', ...).

Hãy viết code refactor hoàn chỉnh, sạch sẽ.