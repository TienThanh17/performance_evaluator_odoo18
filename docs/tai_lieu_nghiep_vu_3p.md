# Tài liệu Mô tả Nghiệp vụ Tính điểm KPI 3P (Hệ thống ADecSol HR)

Tài liệu này hệ thống hóa các quy tắc nghiệp vụ (Business Rules) tính toán điểm số cho các tiêu chí thuộc mô hình Lương 3P (Position - Person - Performance), được phân tích dựa trên dữ liệu bảng tính Excel thực tế và các yêu cầu chuẩn hóa cấu hình trên hệ thống Odoo 18.

---

## 1. Tổng quan cấu trúc Đánh giá 3P

Hệ thống đánh giá hiệu suất nhân sự và phân phối thu nhập dựa trên 3 trụ cột cốt lõi:
* **P1 (Position):** Lương theo vị trí chức danh (Cố định, do Kế toán/HR nhập dựa trên khung lương).
* **P2 (Person):** Đánh giá năng lực cá nhân, chia làm 2 phần chính:
    * **P2.1 (Kiến thức - Knowledge):** Điểm chuẩn cố định, trừ điểm theo hành vi sai phạm.
    * **P2.2 (Kỹ năng chuyên môn - Hard/Soft Skills):** Chấm điểm trực tiếp dựa trên năng lực thực tế.
* **P3 (Performance):** Đánh giá hiệu suất công việc thực tế qua chỉ số KPI, chia làm 2 cấp độ:
    * **P3.1.1:** KPI Cá nhân (Individual KPI).
    * **P3.1.2:** KPI Phòng ban (Department KPI).

---

## 2. Chi tiết cơ chế tính điểm từng tiêu chí (P)

### 2.1. Tiêu chí P2.1 (Kiến thức) - Cơ chế "Trừ điểm lũy tiến từ con lên cha"

#### 📌 Bản chất nghiệp vụ:
Nhân viên được mặc định cấp một quỹ điểm chuẩn tối đa cho mỗi Section (Nhóm kiến thức). Trong quá trình vận hành, nếu nhân viên vi phạm hoặc không đáp ứng các tiêu chí chi tiết (Dòng con), điểm phạt sẽ được tích lũy và trừ trực tiếp vào quỹ điểm của Nhóm (Dòng cha).

#### 🧮 Thuật toán tính toán:
1.  **Dòng con (KPI Line - Leaf Nodes):** Không có điểm đạt riêng, chỉ ghi nhận giá trị điểm trừ cố định (thường định nghĩa là số âm như `-1`, `-2`).
2.  **Dòng cha (Section - Parent Nodes):** Định nghĩa Trọng số tối đa (`weight` hoặc `max_score`).
3.  **Công thức tổng hợp tại Dòng cha:**
    $$	ext{Điểm đạt được của Section} = \max\left(0, 	ext{Trọng số tối đa} + \sum 	ext{Điểm trừ của các dòng con}
ight)$$

*Ví dụ thực tế từ Sheet P2.1:*
* **Section C (QUY TRÌNH PHÒNG BAN):** Trọng số tối đa = 15 điểm.
* Dòng con C.1 (Sai quy trình xử lý sự cố): Điểm phạt = -2 điểm.
* Dòng con C.2 (Không cập nhật nhật ký hệ thống): Điểm phạt = -1 điểm.
* **Kết quả Section C:** $15 + (-2) + (-1) = 12$ điểm.

---

### 2.2. Tiêu chí P2.2 (Kỹ năng chuyên môn) - Cơ chế "Chấm điểm trực tiếp"

#### 📌 Bản chất nghiệp vụ:
Đây là bảng đánh giá năng lực hành vi và kỹ năng thực hiện công việc. Không áp dụng công thức trừ điểm hay ma trận phức tạp, điểm số dựa trên sự đánh giá chủ quan mang tính định lượng của Quản lý và Nhân viên.

#### 🧮 Thuật toán tính toán:
1.  **Quy trình 2 bước:**
    * **Nhân viên tự đánh giá (Self-Assessment):** Nhân viên tự nhập điểm tự chấm từ mảng thang điểm quy định (Ví dụ: Thang điểm 10). Trường này mang tính chất tham khảo và đối chiếu.
    * **Quản trị viên đánh giá (Manager Rating):** Cấp trên trực tiếp chấm điểm dựa trên quan sát thực tế.
2.  **Công thức dòng cuối cùng:**
    $$	ext{Điểm đạt được của dòng} = 	ext{Điểm do Quản lý chấm (Manager Rating Score)}$$
3.  **Tổng điểm P2.2:** Bằng tổng điểm chấm của tất cả các dòng tiêu chí kỹ năng.

---

### 2.3. Tiêu chí P3.1.1 & P3.1.2 (KPI Cá nhân & Phòng ban) - Cơ chế "Phạt hủy diệt Section" (Wipeout Penalty)

#### 📌 Bản chất nghiệp vụ:
Cấu trúc cây KPI của P3 gồm 3 cấp: **Dòng Cha lớn (Section)** $
ightarrow$ **Dòng Cha nhỏ (Sub-Section)** $
ightarrow$ **Dòng Chỉ tiêu con (KPI Line)**. 
Để đảm bảo tính nghiêm khắc trong quản trị hiệu suất và ràng buộc chất lượng tối hạn, P3 áp dụng cơ chế **"Phạt hủy diệt"**. Nếu *bất kỳ* một chỉ tiêu con nào rơi vào trạng thái vi phạm nghiêm trọng (hoặc có số lần vi phạm vượt ngưỡng), toàn bộ số điểm tích lũy của cả Section lớn đó sẽ bị hủy về `0` điểm, bất kể các chỉ tiêu khác trong cùng nhóm đạt kết quả xuất sắc.

#### 🧮 Thuật toán tính toán:
1.  Mỗi dòng KPI con ghi nhận: `violation_count` (Số lần vi phạm) và `penalty_per_violation` (Trọng số phạt hoặc cờ báo vi phạm nghiêm trọng).
2.  **Công thức kiểm tra tại Dòng cha lớn (Section):**
    * Nếu tồn tại ít nhất 1 dòng con thuộc Section đó có trạng thái vi phạm nghiêm trọng (`is_violated = True` hoặc tổng điểm phạt vượt ngưỡng tối hạn):
        $$	ext{Điểm đạt được của toàn bộ Section} = 0$$
    * Nếu không có vi phạm nghiêm trọng, điểm tính theo trọng số hoàn thành bình thường:
        $$	ext{Điểm đạt được của Section} = \sum 	ext{Điểm đạt của các Sub-section/KPI Lines}$$

*Ví dụ thực tế từ Sheet P3 phòng IT:*
* **Section An Toàn Lao Động:** Bao gồm các tiêu chí về trang bị bảo hộ, nội quy công trường.
* Nếu nhân viên vi phạm lỗi "Không đội mũ bảo hộ trên công trường" $
ightarrow$ Lỗi này kích hoạt cờ vi phạm nghiêm trọng.
* **Kết quả:** Toàn bộ điểm của Section An Toàn Lao Động lập tức bị hủy về 0 điểm (Mất trắng điểm trọng số của phần này).