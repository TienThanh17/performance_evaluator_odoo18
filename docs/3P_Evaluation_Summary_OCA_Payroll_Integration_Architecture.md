# TÀI LIỆU KIẾN TRÚC TÍCH HỢP: 3P EVALUATION SUMMARY & OCA PAYROLL

Tài liệu này đặc tả luồng dữ liệu độc lập và logic kết nối giữa dòng tổng kết kết quả 3P (`hr.evaluation.3p.summary.line`) với mô-đun Lương OCA (Odoo 18 Community) mà không can thiệp vào cấu trúc gốc của Hợp đồng (`hr_contract`).

---

## 1. BẢN CHẤT CÔNG THỨC LƯƠNG 3P CUỐI CÙNG

Mô-đun Lương OCA sẽ tính toán dòng tiền dựa trên các giá trị số thực tế được chốt tại một dòng dữ liệu tổng kết KPI cụ thể. Tất cả các tham số (Số tiền định mức + Hệ số kết quả) đều nằm trọn vẹn trong bản ghi `hr.evaluation.3p.summary.line`.

$$
\text{Lương cuối cùng} = (P1.1 + P1.2) + (\text{Lương } P2.1 \text{ định mức} \times \text{Hệ số } P2.1) + (\text{Lương } P2.2 \text{ định mức} \times \text{Hệ số } P2.2) + (\text{Thưởng } P3.1 \text{ định mức} \times \text{Hệ số KPI Nhân viên}) + (\text{Thưởng } P3.2 \text{ định mức} \times \text{Hệ số Doanh thu})
$$

---

## 2. ÁNH XẠ DỮ LIỆU SANG OCA PAYROLL (DATA MAPPING)

Vì mô-đun Payroll của OCA chạy độc lập, chúng ta sẽ chuyển **toàn bộ các biến số** (cả số tiền và hệ số) từ dòng KPI sang bảng dữ liệu đầu vào (**Inputs**) của Phiếu lương nhân viên (`hr.payslip`).

Khi chu kỳ 3P được duyệt chốt (`summary_state == 'done'`), hệ thống tự động tìm Phiếu lương Nháp (`state == 'draft'`) của nhân viên trong kỳ đó và tạo/cập nhật các mã Inputs (Other Input Types) như sau:

| Biến số trong Model KPI (`hr.evaluation.3p.summary.line`) | Mã Input trong OCA Payroll | Vai trò trong Công thức |
| :--- | :--- | :--- |
| `p1_base_salary` | `P1_BASE` | P1.1 - Số tiền lương vị trí |
| `p1_allowance` | `P1_ALLOW` | P1.2 - Số tiền phụ cấp |
| `p2_1_score_raw` | `P21_SCORE` | Hệ số kết quả P2.1 |
| `p2_2_score_raw` | `P22_SCORE` | Hệ số kết quả P2.2 |
| `p3_1_score` | `P31_SCORE` | Hệ số KPI Nhân viên (P3.1) |
| `p3_2_revenue` | `P32_REVENUE` | Hệ số Doanh thu (P3.2) |

> **Lưu ý nghiệp vụ:** Các mức lương định mức (như lương định mức P2.1, P2.2, thưởng định mức P3.1, P3.2) sẽ được kế toán nhập tay trực tiếp hoặc import hàng loạt vào các trường tương ứng trên chính giao diện dòng KPI này trước khi chốt, giúp tái sử dụng thông tin theo từng kỳ đánh giá mà không cần động vào Contract.

---

## 3. LOGIC XỬ LÝ PYTHON TRONG QUY TẮC LƯƠNG (SALARY RULES CODE)

Khi kế toán nhấn nút `Compute Sheet` trên Bảng lương tổng của OCA, hệ thống sẽ bốc tách các giá trị từ bộ mã `inputs` ở trên để tính toán tự động.

### Quy tắc 1: Lương Vị trí & Phụ cấp (P1)

- **Code:** `P1_TOTAL`

- **Python Code:**

```python
p1_1 = inputs.dict.get('P1_BASE') and inputs.dict['P1_BASE'].amount or 0.0
p1_2 = inputs.dict.get('P1_ALLOW') and inputs.dict['P1_ALLOW'].amount or 0.0
result = p1_1 + p1_2
```

### Quy tắc 2: Lương Năng lực P2 (Gộp cả P2.1 và P2.2)

- **Code:** `P2_TOTAL`

- **Python Code:**

```python
# Ở đây vì không lấy từ contract, số tiền định mức cố định cho P2, P3
# sẽ do bạn cấu hình làm quy tắc hằng số (Fix cứng số tiền) trong quy tắc lương OCA
# Hoặc nếu số tiền này thay đổi theo từng người, bạn bổ sung thêm mã Input tiền định mức vào đây.

p21_dinhmuc = 5000000  # Ví dụ số tiền định mức cụ thể quy định của công ty
p22_dinhmuc = 3000000

he_so_p21 = inputs.dict.get('P21_SCORE') and inputs.dict['P21_SCORE'].amount or 0.0
he_so_p22 = inputs.dict.get('P22_SCORE') and inputs.dict['P22_SCORE'].amount or 0.0

result = (p21_dinhmuc * he_so_p21) + (p22_dinhmuc * he_so_p22)
```

### Quy tắc 3: Thưởng Kết quả P3 (Gộp cả KPI cá nhân P3.1 và Doanh thu P3.2)

- **Code:** `P3_TOTAL`

- **Python Code:**

```python
p31_dinhmuc = 4000000  # Ví dụ số tiền thưởng định mức cụ thể
p32_dinhmuc = 6000000

he_so_p31 = inputs.dict.get('P31_SCORE') and inputs.dict['P31_SCORE'].amount or 0.0
he_so_p32 = inputs.dict.get('P32_REVENUE') and inputs.dict['P32_REVENUE'].amount or 0.0

result = (p31_dinhmuc * he_so_p31) + (p32_dinhmuc * he_so_p32)
```

### Quy tắc 4: Tổng Lương Cuối Cùng

- **Code:** `NET_SALARY`

- **Python Code:**

```python
result = P1_TOTAL + P2_TOTAL + P3_TOTAL
```

---