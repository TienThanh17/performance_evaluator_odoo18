# KPI Scoring (Odoo 18 – hr_performance_evaluator)

Tài liệu này mô tả cách module **hr_performance_evaluator** tính điểm KPI theo mô hình 3 lớp (objective + adjustment), sử dụng **thang điểm 10**.

## 1) Khái niệm & Field liên quan

Trong model `hr.performance.evaluation.line`, các field chính phục vụ tính điểm:

- `kpi_type`: loại KPI
  - `quantitative`: số lượng/giá trị (so sánh Actual vs Target)
  - `binary`: đạt/không đạt
  - `rating`: đánh giá sao (0–5)
- `target_type`: đơn vị của Target/Actual
  - `value`: số tuyệt đối (vd: 30)
  - `percentage`: phần trăm 0–100 (vd: 90)
- `direction` (chỉ quan trọng cho `quantitative`):
  - `higher_better`: càng cao càng tốt
  - `lower_better`: càng thấp càng tốt
- `target`: mục tiêu
- `actual`: kết quả thực tế (giá trị canonical duy nhất, dùng cho tính điểm hệ thống)
- `system_score`: điểm hệ thống (objective) – tính tự động
- `employee_rating`: nhân viên tự chấm (0–10) – nhập tay (áp dụng cho KPI non-quantitative manual)
- `manager_rating`: quản lý chấm/duyệt (0–10) – nhập tay
- `manager_adjustment`: điều chỉnh của quản lý (subjective) – nhập tay

---

## 2) Mô hình tính điểm

### 2.1. System Score (Objective)

`system_score` phản ánh **mức độ đạt KPI dựa trên Actual vs Target** mà không bị ảnh hưởng bởi ý kiến chủ quan.

> Kết quả `system_score` luôn được **giới hạn trong [0, 10]**.

## 2) Mô hình tính điểm 3 lớp

```
system_score = clamp(score_raw, 0, 10)
```

Trong đó `clamp(x, 0, 10) = max(0, min(x, 10))`.

#### A) KPI Type = `quantitative`

Nếu `target <= 0` thì `system_score = 0`.

- **direction = higher_better** (càng cao càng tốt)

```
score_raw = (actual / target) * 10
```

- **direction = lower_better** (càng thấp càng tốt)

Nếu `actual <= 0` thì `score_raw = 0` (tránh chia cho 0).

```
score_raw = (target / actual) * 10
```

Sau đó:

```
system_score = clamp(score_raw, 0, 10)
```

> `target_type` chỉ quyết định **đơn vị** (value hoặc %). Công thức vẫn giống nhau vì Target và Actual luôn cùng loại.

#### C) KPI Type = `binary`

- Đạt KPI: `system_score = 10`
- Không đạt: `system_score = 0`

Thông thường UI dùng boolean `binary_result` để bật/tắt đạt KPI.

#### D) KPI Type = `rating`

Rating 0–5 sao quy đổi về thang 10:

```
score_raw = (rating / 5) * 10
system_score = clamp(score_raw, 0, 10)
```

Ví dụ:
- 4/5 sao → system_score = 8.0

---

### 2.2. Self vs Manager rating & Final Rating

Áp dụng chủ yếu cho KPI **non-quantitative manual** (ví dụ: `binary`, `rating`, `score`):

- Trước khi submit: nhân viên nhập `employee_rating` (0–10).
### 2.2. Manager Adjustment (Subjective)

> Module có constraint giới hạn khoảng điều chỉnh để đảm bảo tính ổn định của thang điểm.

Công thức:

```
manager_adjustment ∈ [-3, +3]
```
---
final_rating = clamp(manager_rating, 0, 10)
```

---

## 3) Điểm tổng hợp (Performance Score)

Trên model `hr.performance.evaluation`, điểm tổng hợp dùng trọng số `weight`:

### 2.3. Final Rating (Kết quả cuối dòng KPI)

final_raw = system_score + manager_adjustment
final_rating = clamp(final_raw, 0, 10)
  - `final_rating_i` (0–10)
  - `weight_i`

Tổng trọng số:

```
TotalWeight = Σ weight_i
```

Điểm KPI tổng hợp:

```
performance_score = (Σ (final_rating_i * weight_i)) / TotalWeight
```

Nếu `TotalWeight = 0` thì `performance_score = 0`.

---

## 4) Gợi ý vận hành

- Nhập đúng `actual` theo từng loại KPI.
- Với KPI non-quantitative manual: nhân viên nhập `employee_rating` trước khi Submit.
- Quản lý kiểm tra và chốt bằng `manager_rating`.
- Sử dụng `manager_adjustment` để tinh chỉnh trong phạm vi cho phép.

---

## 5) Giải thích công thức theo “ngôn ngữ con người”

Mục tiêu của module là chấm KPI theo **thang 10 điểm** và tách rõ:

1) **Điểm hệ thống (System Score)**: máy tự tính dựa trên số liệu (khách quan)
Mục tiêu của module là chấm KPI theo **thang 10 điểm** và tách rõ 2 phần:

Cuối cùng, hệ thống luôn đảm bảo điểm **không bao giờ nhỏ hơn 0 và không bao giờ lớn hơn 10**.

2) **Điều chỉnh của quản lý (Manager Adjustment)**: quản lý cộng/trừ thêm (chủ quan nhưng có kiểm soát)

#### KPI dạng Số (Quantitative)

- Nếu KPI là kiểu “**càng cao càng tốt**” (Higher is Better):
  - Bạn đạt đúng mục tiêu → được khoảng **10 điểm**.
  - Bạn đạt một nửa mục tiêu → được khoảng **5 điểm**.
  - Bạn vượt mục tiêu → hệ thống vẫn **chỉ tối đa 10 điểm**.

- Nếu KPI là kiểu “**càng thấp càng tốt**” (Lower is Better) (ví dụ: tỷ lệ lỗi, số lần trễ hạn):
  - Bạn đạt đúng ngưỡng mục tiêu → được khoảng **10 điểm**.
  - Bạn thấp hơn mục tiêu (tốt hơn yêu cầu) → vẫn **tối đa 10 điểm**.
  - Bạn cao hơn mục tiêu (xấu hơn yêu cầu) → điểm sẽ **giảm dần**.

#### KPI dạng Phần trăm (target_type = Percentage)

Ví dụ “On-time tasks ≥ 90%”:
- `target_type = percentage`
- `target = 90`
- `actual = 80`

Điểm vẫn tính theo tỷ lệ so với Target (theo `direction`), không có heuristic tự convert %.

#### KPI dạng Đạt/Không đạt (Binary)

- Đạt → **10 điểm**
- Không đạt → **0 điểm**

#### KPI dạng Đánh giá sao (Rating)

- 5 sao → **10 điểm**
- 4 sao → **8 điểm**
- 3 sao → **6 điểm**

(Nói đơn giản: sao càng cao thì điểm càng cao, quy đổi thẳng sang thang 10.)

### 5.2. Final Rating (Điểm cuối) được tính ra sao?

Với KPI non-quantitative manual:

- Nhân viên tự chấm `employee_rating`
- Quản lý có thể **cộng thêm** điểm (ví dụ +1.0, +2.0)
- hoặc **trừ bớt** điểm (ví dụ -0.5, -1.0)

### 5.3. Final Rating (Điểm cuối) được tính ra sao?

Điểm cuối của 1 dòng KPI =

> **Điểm hệ thống** + **Điều chỉnh của quản lý**

Sau đó hệ thống “chốt” lại:

- Nếu nhỏ hơn 0 → lấy **0**
- Nếu lớn hơn 10 → lấy **10**

Điểm cuối = clamp(`manager_rating`, 0, 10).

### 5.4. Performance Score (Điểm tổng) được hiểu đơn giản thế nào?

Mỗi KPI có **trọng số** (weight). KPI nào quan trọng hơn thì weight lớn hơn.

Điểm tổng là **điểm trung bình có trọng số**:

- KPI quan trọng sẽ ảnh hưởng nhiều hơn
- KPI ít quan trọng sẽ ảnh hưởng ít hơn

Nếu tổng trọng số bằng 0 thì hệ thống trả về 0 để tránh lỗi.

