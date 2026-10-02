# Lấy đề bài từ đâu

Ghi chú cho giáo viên. Trả lời câu hỏi: muốn có thêm đề cho hệ thống thì lấy ở đâu.

## Trước hết: một đề cần **hai** thứ

Để một đề chấm được, cần cả hai:

1. **Đề bài** — phần chữ học sinh đọc.
2. **Bộ dữ liệu vào – ra** — các cặp tệp để bộ chấm so kết quả.

Nguồn **đề bài** thì rất nhiều. Nguồn **dữ liệu chấm** thì ít. Hầu hết các kho
đề trên mạng chỉ cho đề bài; dữ liệu chấm họ giữ lại vì đó là thứ khiến một kỳ
thi chấm được. Nên khi đi tìm, câu hỏi đầu tiên luôn là: *nguồn này có kèm dữ
liệu chấm không?*

## Nhóm 1 — Có sẵn dữ liệu chấm, nhập thẳng bằng ZIP

Đây là nhóm đáng ưu tiên: có đề là có luôn dữ liệu, không phải nghĩ thêm.

### USACO — nguồn tốt nhất, đã thử chạy thật

Trang chủ: <https://www.usaco.org/index.php?page=contests>

Mỗi kỳ thi có bốn bảng: **Bronze**, Silver, Gold, Platinum. Mỗi đề có ba liên
kết: `View problem` (đề bài), **`Test data`** (dữ liệu chấm, tệp ZIP), và
`Solution` (lời giải).

Đã tải thử `prob1_bronze_dec20.zip` và cho qua bộ nhập ZIP của hệ thống này:

```
số bộ ghép được: 10
báo cáo: files=20, pairs=10, orphan_in=0, orphan_out=0, skipped=0
```

Tức là **không phải sửa gì**: tải ZIP về, kéo vào trang bộ dữ liệu, xong. Tệp
ZIP chứa `1.in` … `10.out` để phẳng, và bộ nhập đã nhận đúng định dạng đó.

Ba điều cần biết:

- **Đề bằng tiếng Anh.** Phải dịch lại phần đề bài rồi dán vào ô soạn đề.
- **Kỳ từ tháng 12/2020 trở đi dùng vào/ra chuẩn** (đọc `cin`, ghi `cout`) —
  khớp với hệ thống này. Các kỳ **trước 12/2020** đọc ghi bằng tệp có tên riêng
  (`freopen("xyz.in", ...)`), nên phải sửa lại câu chữ trong đề bài cho khớp,
  chứ dữ liệu vẫn nhập được bình thường.
- **Bảng Bronze** gần với trình độ THCS nhất. Silver trở lên là chương trình
  chuyên, khó hơn nhiều so với đề HSG lớp 9.
- Ghi nguồn USACO khi dùng.

### Đề Themis kèm thư mục `TEST`

Nhiều đề thi HSG của các tỉnh, khi chia sẻ, có kèm thư mục `TEST01/`, `TEST02/`…
mỗi thư mục một cặp `.INP` / `.OUT`. Đây **chính là** định dạng gốc mà bộ nhập
ZIP sinh ra để phục vụ, nên nhập được ngay, kể cả khi các tệp nằm trong thư mục
con.

Không có kho chính thức nào tập trung dạng này. Thực tế lấy được từ: đĩa kèm của
các kỳ thi, nhóm giáo viên Tin học, hoặc kho nội bộ của Sở/Phòng.

## Nhóm 2 — Có đề bài, phải tự làm bộ dữ liệu

### Tin học trẻ — `tinhoctre.vn`

<https://tinhoctre.vn/dethi/>

Kho đề **chính thức** của Hội thi Tin học trẻ toàn quốc, các năm **2022 – 2026**,
đủ các vòng: sơ khảo, khu vực (Bắc / Trung / Nam), chung kết toàn quốc.

Các bảng: **A — Tiểu học**, **B — THCS**, **C1 — THPT Chuyên Tin**,
**C2 — THPT Không Chuyên Tin**.

**Bảng B là đúng cấp 2.** Ví dụ vòng sơ khảo bảng B năm 2024: <https://tinhoctre.vn/contest/24tht_sokhao_b>

Đọc đề và nộp bài được, nhưng **không tải được dữ liệu chấm** — đây là một trang
chấm bài, không phải kho tải về.

### LQDOJ — `lqdoj.edu.vn`

Kho đề tiếng Việt lớn nhất hiện nay, chạy trên nền DMOJ. Có nhiều đề đúng tầm
lớp 9, kể cả đề tuyển sinh 10 môn Tin của các tỉnh.

Đọc đề được, **không tải được dữ liệu chấm**.

### Kho PDF đề thi HSG các tỉnh

<https://github.com/zukahai/provincial-informatics-exam-questions>

**283 đề**, chia theo `Tỉnh / Lớp / Năm học`, có **Lớp 9**; trải từ 2011–2012 tới
2024–2025, gần đủ 63 tỉnh thành.

Chỉ có đề bài dạng PDF. Không có dữ liệu chấm, không có lời giải. Muốn dùng thì
phải gõ lại đề và tự làm bộ dữ liệu.

Các trang cùng loại (đều là PDF, đều không có dữ liệu chấm):
`dethitinhoc.net`, `dethi.edu.vn`, `techacademy.edu.vn`, `baigiangmoi.com`,
`vitinhtandan.com`.

### Sách giáo khoa Tin học 6–9 (GDPT 2018)

Bài tập trong sách. Ngắn, đúng chương trình, nhưng phải tự đặt dữ liệu.

## Nhóm 3 — Tự sinh dữ liệu

Với đề ở nhóm 2, cách chắc chắn nhất là: viết một **lời giải mẫu**, cho nó chạy
trên dữ liệu sinh ngẫu nhiên, lấy kết quả làm đáp án. Việc này làm được nhưng
hiện chưa có công cụ trong hệ thống — xem mục "Còn thiếu gì" ở dưới.

## Quy trình cho một đề lấy từ nguồn không có dữ liệu

Ví dụ lấy một đề bảng B từ `tinhoctre.vn`:

1. Mở đề, **dán thẳng vào ô soạn đề** ở trang *Soạn đề*. Dán cả tệp `.tex` cũng
   được — hệ thống tự đổi tiêu đề mục, bảng và chữ đậm.
2. Viết **lời giải mẫu** bằng C++, chạy thử vài bộ nhỏ để chắc là đúng.
3. Tạo **10–20 bộ dữ liệu**: vài bộ nhỏ để học sinh nhìn thấy, phần lớn là bộ
   lớn để chặn những cách làm sai mà vẫn qua được ví dụ.
4. **Đánh dấu ẩn** cho các bộ lớn. Không đánh dấu thì học sinh mở tab *Đề bài*
   là thấy hết đáp án.
5. Nhập bằng ZIP, hoặc gõ tay từng bộ nếu chỉ có vài bộ. Nhập ZIP xong đề **tự
   được công khai**.
6. Mở đề bằng một tài khoản học sinh thử, nộp một bài cố tình sai, xem có ra
   `WA` không. Nếu ra `AC` thì bộ dữ liệu chưa chặn được gì.

## Một đề nên có bao nhiêu bộ dữ liệu

- **Ít nhất 3 bộ**, và **ít nhất 1 bộ ẩn**. Đề chỉ có một bộ thì học sinh chỉ cần
  in ra đúng kết quả của ví dụ là qua bài.
- **10–20 bộ** là khoảng hợp lý cho một đề lớp 9.
- Trần khuyến nghị **30 bộ**, để giờ cao điểm việc chấm không ùn.
- Mỗi bộ tối đa **4 MB**, cả tệp ZIP tối đa **64 MB**.

## Về bản quyền

- **Đề thi của Sở / Phòng GD&ĐT**: dùng trong nội bộ nhà trường để dạy học là
  việc bình thường. **Đăng công khai lên Internet** thì nên xin phép hoặc ghi rõ
  nguồn.
- **USACO**: dữ liệu công khai trên trang chủ, dùng được; ghi nguồn.
- **LQDOJ, Tin học trẻ**: đề có thể thuộc bản quyền của ban tổ chức. Dùng để dạy
  thì nên ghi nguồn; đừng đăng lại thành kho đề của mình.
- **Kho GitHub ở trên không ghi giấy phép.** Mặc định là giữ toàn quyền, nên chỉ
  nên dùng làm tài liệu tham khảo cho giáo viên, không đăng lại.

## Còn thiếu gì

Chưa có trong hệ thống, xếp theo mức độ hữu ích:

1. **Sinh dữ liệu từ lời giải mẫu.** Tải lên một tệp `.cpp` là lời giải đúng, hệ
   thống sinh N bộ ngẫu nhiên rồi tự tạo tệp đáp án. Đây là thứ biến một đề lấy
   từ nhóm 2 thành một đề chấm được trong vài phút, thay vì cả buổi gõ tay. Hệ
   thống đã có sẵn bộ chấm chạy được C++ trong sandbox nên dùng lại được.
2. **Nhập đề kèm cả đề bài lẫn dữ liệu trong một tệp.** Hiện ZIP chỉ mang dữ
   liệu; đề bài phải dán riêng.
3. **Trang "Nguồn đề" trong khu giáo viên**, để giáo viên khác trong trường đọc
   được mà không cần mở repo này.
