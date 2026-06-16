# BÀI TOÁN NGHIỆP VỤ: ĐỒNG BỘ ĐIỂM ĐÁNH GIÁ 3P TỪ ODOO SANG EXCEL

## 1. Mô tả xung đột giữa Hệ thống (Odoo) và Báo cáo (Excel cũ)

### Cơ chế trong Odoo

Hệ thống lưu trữ và tính toán điểm của các tiêu chí thành phần (ví dụ: TC1 đến TC5 trong nhóm P2.1) đồng nhất theo **Thang điểm 100**.

Giá trị tổng hợp (**Hệ số**) được tính theo phương pháp **Bình quân gia quyền**:

```text
Hệ số Odoo = SUM(Điểm tiêu chí thang 100 × Trọng số) / SUM(Trọng số)
```

Ví dụ:

| Tiêu chí | Điểm | Trọng số |
| -------- | ---- | -------- |
| TC1      | 80   | 20       |
| TC2      | 90   | 30       |
| TC3      | 70   | 50       |

```text
Hệ số Odoo
= (80×20 + 90×30 + 70×50) / (20+30+50)
= (1600 + 2700 + 3500) / 100
= 78
```

---

### Cơ chế trong Excel cũ

Báo cáo không hiển thị điểm thang 100 mà hiển thị **Điểm thô (Raw Score)**, tức là điểm đã nhân theo tỷ trọng của từng tiêu chí.

Cột **Hệ số** trong Excel được tính bằng công thức:

```text
Hệ số Excel = SUM(Điểm thô các tiêu chí) / 100
```

Ví dụ:

| Tiêu chí | Điểm thô |
| -------- | -------- |
| TC1      | 16       |
| TC2      | 27       |
| TC3      | 35       |

```text
Hệ số Excel
= (16 + 27 + 35) / 100
= 78 / 100
= 0.78
```

---

## 2. Mục tiêu giải quyết

Khi thực hiện chức năng xuất Excel (`action_export_excel`), file xuất ra phải:

* Giữ nguyên thói quen sử dụng của người dùng.
* Hiển thị **Điểm thô (Raw Score)** tại các ô tiêu chí thành phần.
* Giữ nguyên công thức tính **Hệ số** theo cách của Excel cũ.
* Đảm bảo kết quả hiển thị khớp 100% với UI/UX hiện tại.
* Không làm thay đổi logic lưu trữ và tính toán theo thang điểm 100 trong cơ sở dữ liệu Odoo.

---

## 3. Công thức quy đổi ngược dữ liệu

Để chuyển đổi dữ liệu từ lớp lưu trữ (Odoo) sang lớp hiển thị (Excel), áp dụng công thức sau cho từng tiêu chí thành phần:

```text
Điểm thô ghi vào Excel
=
(Điểm tiêu chí trên Odoo × Trọng số gốc của tiêu chí)
/
100
```

### Ví dụ

| Tiêu chí | Điểm trên Odoo | Trọng số | Điểm thô ghi Excel |
| -------- | -------------- | -------- | ------------------ |
| TC1      | 80             | 20       | 16                 |
| TC2      | 90             | 30       | 27                 |
| TC3      | 70             | 50       | 35                 |

```text
TC1 = (80 × 20) / 100 = 16
TC2 = (90 × 30) / 100 = 27
TC3 = (70 × 50) / 100 = 35
```

Tổng điểm thô:

```text
16 + 27 + 35 = 78
```

Hệ số Excel:

```text
78 / 100 = 0.78
```

---

## 4. Quy tắc xử lý khi ghi dữ liệu vào file Excel

### 4.1. Đối với các cột Tiêu chí thành phần (TC1, TC2, ...)

Áp dụng công thức quy đổi ngược:

```text
Điểm thô
=
(Điểm Odoo × Trọng số)
/
100
```

Sau khi tính toán:

* Ghi trực tiếp giá trị điểm thô vào ô Excel.
* Định dạng dữ liệu là **Number**.
* Không ghi công thức Excel cho các ô tiêu chí.
* Không ghi điểm thang 100 từ Odoo vào Excel.

---

### 4.2. Đối với các cột Hệ số (Cột tổng hợp)

**Không được ghi giá trị số cứng từ Odoo.**

Bắt buộc ghi **công thức Excel động** theo định dạng:

```excel
=SUM(Ô_TC_Đầu_Tiên:Ô_TC_Cuối_Cùng)/100
```

Ví dụ tại dòng 18:

```excel
=SUM(J18:N18)/100
```

Ví dụ tại dòng 25:

```excel
=SUM(J25:N25)/100
```

Yêu cầu:

* Công thức phải được ghi trực tiếp vào ô Excel.
* Khi người dùng click vào ô Hệ số phải nhìn thấy công thức.
* Excel tự tính toán giá trị khi mở file.

---

## 5. Thuật toán xử lý khi Export Excel

### Bước 1: Đọc dữ liệu từ Odoo

Ví dụ dữ liệu nguồn:

```python
[
    {"name": "TC1", "score": 80, "weight": 20},
    {"name": "TC2", "score": 90, "weight": 30},
    {"name": "TC3", "score": 70, "weight": 50},
]
```

### Bước 2: Quy đổi từng tiêu chí sang Điểm thô

```text
raw_score = (score × weight) / 100
```

Kết quả:

```python
TC1 = 16
TC2 = 27
TC3 = 35
```

### Bước 3: Ghi các điểm thô vào các ô TC

Ví dụ:

```text
J18 = 16
K18 = 27
L18 = 35
```

### Bước 4: Ghi công thức vào ô Hệ số

Ví dụ:

```excel
M18 = =SUM(J18:L18)/100
```

Không ghi:

```text
M18 = 0.78
```

---

## 6. Kết quả kỳ vọng

### Các cột Tiêu chí thành phần

* Hiển thị điểm thô đúng định dạng Excel cũ.
* Người dùng nhìn thấy các giá trị quen thuộc như trước khi chuyển sang Odoo.

### Các cột Hệ số

* Chứa công thức Excel động:

```excel
=SUM(...)/100
```

* Tự động tính toán khi mở file.
* Khi người dùng click vào ô sẽ thấy đúng công thức nghiệp vụ.

### Tính nhất quán hệ thống

* Odoo tiếp tục lưu trữ dữ liệu theo thang điểm 100.
* Excel tiếp tục hiển thị dữ liệu theo dạng điểm thô.
* Không thay đổi nghiệp vụ hiện hành.
* Kết quả xuất Excel tương thích 100% với quy trình sử dụng trước đây.
