# Tài liệu Đặc tả Nghiệp vụ Chấm điểm KPI 3P trên Odoo 18 (Dành cho AI/LLM Reader)

Tài liệu này chuẩn hóa toán học và cấu trúc dữ liệu toàn bộ quy trình nghiệp vụ đánh giá hiệu suất 3P (Position - Person - Performance) từ các file Excel thủ công sang hệ thống ERP Odoo 18. Thiết kế cấu trúc dưới đây tối ưu hóa cho AI Đọc-Hiểu để tự động lập trình và refactor mã nguồn.

---

## 1. Nguyên tắc thiết kế Kiến trúc Dữ liệu tổng thể
Hệ thống phân tách rõ ràng giữa **Trọng số (Weight)** và **Thang điểm chấm (Scale)**:
* **Weight (Trọng số):** Thể hiện mức độ quan trọng của tiêu chí. Tổng trọng số của tất cả các tiêu chí trong một Trụ cột (Pillar) luôn luôn quy đổi về mốc $100\%$.
* **Scale (Thang điểm):** Thước đo năng lực hoặc mức độ hoàn thành công việc, đồng bộ ở mảng thang điểm $[0 - 100]$ điểm cho tất cả các tiêu chí để giao diện nhất quán.

---

## 2. Đặc tả thuật toán và Cấu trúc dữ liệu chi tiết từng Trụ cột (P)

### 2.1. Trụ cột P2.1 (Kiến thức - Knowledge)

#### Cấu trúc cây dữ liệu (Multi-level Tree Hierarchy):
Cấu trúc phân rã trọng số 3 cấp: `Section (Nhóm cha lớn) -> Sub-Section (Nhóm con) -> KPI Line (Chỉ tiêu chi tiết)`. Ràng buộc tổng weight:
1.  Tổng `weight` của tất cả các `Section` trong P2.1 = $100$.
2.  Tổng `weight` của tất cả các `Sub-Section` thuộc một `Section` = `weight` của `Section` cha đó.
3.  Tổng `weight` của tất cả các `KPI Line` thuộc một `Sub-Section` = `weight` của `Sub-Section` cha đó.

#### Cơ chế chấm điểm (Scoring Mechanism):
* Cấu hình tại dòng lá (`KPI Line`): `kpi_type = 'manual'` (Chấm thủ công) và `manual_scoring_type = 'binary'` (Lựa chọn Đạt / Không đạt).
* **Quy tắc giá trị:**
    * Nếu chọn **"Đạt" (Passed)** $
ightarrow$ Ghi nhận $100$ điểm.
    * Nếu chọn **"Không đạt" (Failed)** $
ightarrow$ Ghi nhận $0$ điểm.

#### Công thức Roll-up tổng hợp điểm từ Dưới lên Trên:
Điểm số của các nút cha (`Sub-Section` và `Section`) được tính tự động bằng trung bình cộng có trọng số (Weighted Average) của các nút con trực tiếp của nó:

$$	ext{Score}_{	ext{parent}} = rac{\sum \left(	ext{Score}_{	ext{child}} 	imes 	ext{Weight}_{	ext{child}}
ight)}{	ext{Weight}_{	ext{parent}}}$$

*Trong đó:*
* $	ext{Score}_{	ext{parent}}$: Điểm đạt được của nút cha (thang điểm 100).
* $	ext{Score}_{	ext{child}}$: Điểm của nút con (nếu là dòng lá thì bằng 0 hoặc 100).
* $	ext{Weight}_{	ext{child}}$: Trọng số nội bộ của nút con.
* $	ext{Weight}_{	ext{parent}}$: Trọng số của nút cha.

---

### 2.2. Trụ cột P2.2 (Kỹ năng chuyên môn - Skills)

#### Cấu trúc dữ liệu:
* Bảng phẳng hoặc cây 1 cấp (`KPI Line` trực tiếp).
* Các điểm số tối đa (Max Points) trong biểu mẫu cũ được chuyển hóa thành trường `weight`.
* **Ràng buộc:** Tổng `weight` của tất cả các tiêu chí trong P2.2 luôn luôn bằng $100$.

#### Cơ chế chấm điểm và Tính điểm:
* Giao diện cung cấp trường nhập liệu trực tiếp: `manager_rating_score` (Điểm do Quản lý chấm) theo thang điểm từ $0$ đến $100$.
* **Công thức tính điểm đạt của từng dòng:**
    $$	ext{Final\_Rating}_{	ext{line}} = 	ext{manager\_rating\_score}$$
* **Tổng điểm đạt của Pillar P2.2:** Do tổng weight bằng 100, tổng điểm P2.2 bằng tổng điểm trọng số của các dòng:
    $$	ext{Total\_P2.2} = \sum \left(rac{	ext{Final\_Rating}_{	ext{line}} 	imes 	ext{Weight}_{	ext{line}}}{100}
ight)$$

---

### 2.3. Trụ cột P3 (Performance - Gồm P3.1.1 Cá nhân & P3.1.2 Phòng ban)

#### Cấu trúc cây dữ liệu:
* Mô hình cây tương tự P2.1: `Section -> Sub-Section -> KPI Line`.
* Tổng `weight` của các nhánh luôn quy đổi về $100\%$ tại nút gốc.

#### Cơ chế chấm điểm thông thường:
* Các dòng lá (`KPI Line`) nhận diện kết quả dựa trên các trường `target` (mục tiêu) và `actual` (thực tế).
* Điểm số cơ sở được tính toán thông qua cấu hình `scoring_formula_id` (tuyến tính, bậc thang hoặc công thức phù hợp) để quy đổi ra thang điểm $[0 - 100]$.
* Với KPI `manual`, điểm của dòng lá được lấy theo kiểu chấm thủ công tương ứng.

#### 🚨 Cơ chế "Wipeout" theo cấu hình trên dòng cha:
Hệ thống không còn cấu hình wipeout trực tiếp trên từng dòng lá (`KPI Line`). Thay vào đó, rule wipeout được cấu hình tại các dòng cha (`Section` hoặc `Sub-Section`) thông qua field boolean:

* `wipeout_if_child_zero`

#### Ý nghĩa nghiệp vụ của `wipeout_if_child_zero`:
* Field này chỉ có ý nghĩa trên các dòng `is_section = True`.
* Khi một dòng cha bật `wipeout_if_child_zero = True`, hệ thống hiểu rằng nhánh KPI đó có tính chất "điểm liệt".
* Nếu trong toàn bộ cây con của nhánh đó tồn tại **ít nhất một** KPI lá có điểm cuối bằng `0`, thì điểm của dòng cha đang bật cờ sẽ bị ép về `0`.

#### Thuật toán quét và ép điểm (Compute & Cascade Override):
Khi hàm compute của hệ thống kích hoạt, nó sẽ quét từ các dòng lá (`KPI Line`) lên các dòng cha theo cơ chế đệ quy:

1.  **Tại dòng lá (KPI Line):**
    * Điểm của dòng lá được tính theo logic KPI thông thường:
        * KPI `auto`: tính từ `target`, `actual` và `scoring_formula_id`.
        * KPI `manual`: tính theo kiểu chấm thủ công tương ứng.
    * Nếu sau khi tính toán, một dòng lá có `Final_Rating = 0`, thì dòng lá đó trở thành điều kiện kích hoạt wipeout cho các ancestor đang bật `wipeout_if_child_zero`.

2.  **Tại các dòng cha (Sub-Section và Section):**
    * Hệ thống kiểm tra toàn bộ các dòng con cháu trực thuộc nhánh của dòng cha hiện tại.
    * Nếu dòng cha có `wipeout_if_child_zero = True` và tồn tại ít nhất một dòng lá hậu duệ có `Final_Rating = 0`:
        $$\text{Final\_Rating}_{\text{parent}} = 0$$
        *Ý nghĩa nghiệp vụ:* Hủy toàn bộ điểm của nhóm cha đó về 0, bất chấp các KPI khác trong cùng nhánh đang đạt điểm cao.
    * Nếu dòng cha không bật `wipeout_if_child_zero`, hoặc không có dòng lá hậu duệ nào bằng `0`, thì điểm của dòng cha được tổng hợp theo công thức trung bình cộng có trọng số thông thường:
        $$\text{Final\_Rating}_{\text{parent}} = \frac{\sum \left(\text{Final\_Rating}_{\text{child}} \times \text{Weight}_{\text{child}}\right)}{\text{Weight}_{\text{parent}}}$$

#### Quy tắc lan truyền (Cascade All):
* Một KPI lá có điểm `0` có thể làm wipeout nhiều tầng cha khác nhau.
* Mỗi ancestor nào bật `wipeout_if_child_zero = True` thì ancestor đó sẽ bị ép về `0`.
* Ancestor nào không bật cờ thì không bị ép `0`, và vẫn tính weighted average thông thường từ các dòng con trực tiếp của nó.

---

## 4. Đặc tả Quy trình Tổng hợp cuối cùng lên Bảng lương (Summary 3P Link)

Sau khi tính toán xong điểm tổng kết của từng P độc lập trên model phiếu đánh giá (`hr.performance.evaluation`), dữ liệu điểm chuẩn hóa cuối cùng được đẩy sang bảng tổng hợp lương (`hr.evaluation.3p.summary`):

1.  $	ext{P2.1\_Score} = 	ext{Total Score của Section thuộc P2.1}$ (Thang 100)
2.  $	ext{P2.2\_Score} = 	ext{Total Score của tiêu chí P2.2}$ (Thang 100)
3.  $	ext{P3.1.1\_Score} = 	ext{Total Score của KPI cá nhân sau khi quét lỗi Wipeout}$ (Thang 100)
4.  $	ext{P3.1.2\_Score} = 	ext{Total Score của KPI phòng ban sau khi quét lỗi Wipeout}$ (Thang 100)

Hệ số lương 3P cuối cùng (`salary_coefficient`) dùng làm căn cứ tính lương thưởng cho phòng Kế toán sẽ được điều phối động thông qua cấu hình trọng số của các trụ cột P tùy theo quy định của doanh nghiệp tại thời điểm đánh giá.
