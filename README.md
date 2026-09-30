# Hệ thống chấm bài lập trình — Trường THCS Sông Lô

Giao diện cho một **online judge** phục vụ nội bộ Trường THCS Sông Lô (xã Tam Sơn, tỉnh Phú Thọ). Học sinh luyện tập và thi đấu môn Tin học bằng **C++**, bài nộp được chấm tự động theo bộ dữ liệu, có bộ dữ liệu ẩn và bảng xếp hạng.

> **Trạng thái: chỉ có front end.** Đây là bản demo giao diện, chưa có backend, chưa đăng nhập thật, chưa chấm bài. Toàn bộ dữ liệu hiển thị trong trang là dữ liệu mẫu viết cứng.

## Ảnh chụp

| Trang chủ | Danh sách đề |
|---|---|
| ![Trang chủ](docs/01-trang-chu.jpg) | ![Danh sách đề](docs/02-danh-sach-de.jpg) |

| Nộp bài (có tô màu cú pháp) | Bảng xếp hạng |
|---|---|
| ![Nộp bài](docs/03-nop-bai.jpg) | ![Bảng xếp hạng](docs/04-bang-xep-hang.jpg) |

| Tổng quan giáo viên | Danh sách bài nộp |
|---|---|
| ![Tổng quan giáo viên](docs/05-tong-quan-giao-vien.jpg) | ![Bài nộp](docs/06-bai-nop.jpg) |

| Chi tiết một bài nộp | Chế độ tối |
|---|---|
| ![Chi tiết bài nộp](docs/07-chi-tiet-bai-nop.jpg) | ![Chế độ tối](docs/08-che-do-toi.jpg) |

## Xem thử

Cần chạy qua HTTP, không mở trực tiếp bằng `file://` — trình duyệt sẽ chặn tải phông chữ do CORS:

```bash
cd demo
python -m http.server 8777
```

Rồi mở `http://127.0.0.1:8777/`.

Không có bước build. Không dùng framework. CSS và JS đều là file tĩnh.

## Các trang

Nhóm **học sinh**:

| Tệp | Nội dung |
|---|---|
| `index.html` | Trang chủ — ảnh trường, số liệu, kỳ thi sắp tới có đếm ngược, đề mới, bảng xếp hạng tuần |
| `problems.html` | Danh sách đề — tìm kiếm, lọc theo độ khó và chủ đề, bảng sắp xếp được, phân trang |
| `problem.html` | Chi tiết đề + nộp bài — 3 thẻ: Đề bài / Nộp bài / Kết quả chấm |
| `submissions.html` | Danh sách bài nộp — lọc theo kết quả, ngôn ngữ, khoảng thời gian |
| `submission.html` | Chi tiết một lần nộp — kết luận, so sánh ở bộ dữ liệu chưa đạt, kết quả từng bộ, mã nguồn, nhật ký dịch |
| `contests.html` | Kỳ thi — đang diễn ra, sắp diễn ra, đã kết thúc |
| `leaderboard.html` | Bảng xếp hạng — top 3, biểu đồ cột ngang, bảng đầy đủ |
| `login.html` | Đăng nhập — có minh hoạ báo lỗi theo chuẩn trợ năng |

Nhóm **giáo viên** (bấm nút chuyển vai trò ở góc trên bên phải):

| Tệp | Nội dung |
|---|---|
| `teacher.html` | Tổng quan — tiến độ từng lớp, bài nộp gần đây, việc cần xử lý |
| `teacher-problems.html` | Soạn đề — danh sách đề, biểu mẫu tạo đề, quản lý bộ dữ liệu kể cả bộ ẩn |
| `teacher-classes.html` | Lớp học & điểm — sổ điểm từng lớp, cấp tài khoản, xuất bảng điểm |

Liên kết sâu tới từng thẻ hoạt động được, ví dụ `problem.html#panel-submit` mở thẳng phần nộp bài.

## Cấu trúc

```
.
├── demo/                     Bản demo giao diện (mở thư mục này để xem)
│   ├── *.html                11 trang
│   └── assets/
│       ├── css/style.css     Toàn bộ hệ thống thiết kế (token + thành phần)
│       ├── js/app.js         Tương tác, không phụ thuộc thư viện ngoài
│       └── img/              logo.png (huy hiệu, nền trong suốt) + ảnh trường
├── docs/                     Ảnh chụp cho README
├── assets/                   Ảnh gốc tải từ website nhà trường (kể cả huy hiệu)
├── research/                 Ghi chú khảo sát DMOJ/VNOJ
│   ├── dmoj_install.md
│   ├── dmoj_settings.py
│   └── judge_config.md
└── bao-cao-dmoj-tinh-gon.html   Báo cáo: đánh giá DMOJ, phương án tinh gọn, lộ trình
```

## Hệ thống thiết kế

Phong cách **Swiss grid + product UI**: lưới rõ ràng, tương phản cao, đổ bóng thật để tạo chiều sâu, thang chữ dứt khoát. Phù hợp công cụ dữ liệu dày đặc.

Bảng màu lấy từ chính website nhà trường, đã lọc bỏ màu mặc định của Bootstrap:

| Vai trò | Mã màu | Nguồn |
|---|---|---|
| Chính | `#1B18CC` | Thanh menu trang trường |
| Phụ | `#186BCC` | Dòng tên trường |
| Nhấn | `#DA251E` | Màu đỏ cờ ở dòng cơ quan chủ quản |
| Nền | `#F3F4F7` | Nền trang |
| Chữ | `#14161C` | Nội dung |

Màu kết quả chấm bài dùng đúng bộ màu Bootstrap mà trang trường đang dùng:

| Kết quả | Màu |
|---|---|
| Đúng (AC) | `#5CB85C` |
| Sai (WA) | `#D9534F` |
| Quá thời gian / bộ nhớ (TLE/MLE) | `#F0AD4E` |
| Lỗi khi chạy (RTE) | `#7F77DD` |
| Lỗi dịch (CE) | `#888780` |
| Đang chấm | `#186BCC` |

Phông: **Fira Sans** cho giao diện, **Fira Code** cho mã nguồn. Đang tải từ Google Fonts — nếu triển khai trong mạng nội bộ không có Internet, cần tải về đặt cùng máy chủ và sửa `@font-face`.

### Chế độ tối

Có sẵn chế độ tối, đổi bằng nút ở góc trên bên phải. Lần đầu truy cập thì theo cài đặt hệ điều hành; sau khi người dùng tự chọn thì lựa chọn được nhớ lại.

Toàn bộ phần này chỉ chiếm một khối `html[data-theme="dark"]` khoảng 45 dòng, vì mọi thành phần đều tham chiếu token ngữ nghĩa (`--bg`, `--surface`, `--fg`, `--border`, `--link`, `--ink`, `--fill`, màu kết quả…) chứ không dùng mã màu trực tiếp. Đoạn script đổi chế độ nằm trong `<head>` và chạy trước lần vẽ đầu tiên nên không bị nháy trắng khi tải trang.

### Về logo nhà trường

Biểu trưng ở góc trên bên trái là **huy hiệu chính thức của Trường THCS Sông Lô**. Tệp gốc lưu ở `assets/school-logo.png`; bản dùng trong giao diện là `demo/assets/img/logo.png`, đã xoá nền trắng thành trong suốt nên cùng một tệp hiển thị được trên cả nền sáng lẫn nền tối, không cần thêm nền phía sau và không cần biến thể riêng cho từng chế độ.

Cách xoá nền: ảnh gốc là hình vuông có huy hiệu tròn nội tiếp, bốn góc là nền trắng phẳng. Tô loang từ bốn góc xoá đúng phần nằm ngoài vòng tròn — đo được **21,2%**, sát con số lý thuyết 21,5% (diện tích hình vuông trừ đường tròn nội tiếp) — và không đụng tới các vùng trắng bên trong huy hiệu.

Ảnh chụp sân trường tải từ website nhà trường thì vẫn giữ riêng: ảnh đó có chèn sẵn dòng chữ "TRƯỜNG THCS SÔNG LÔ - XÃ TAM SƠN - TỈNH PHÚ THỌ" nên đã được cắt lại ở những vùng không có chữ để dùng làm ảnh minh hoạ.

## Điểm đáng chú ý về kỹ thuật

- **Tô màu cú pháp C++ không cần thư viện.** `app.js` có một bộ tách từ bằng một biểu thức chính quy duy nhất, chạy trên lớp `<pre>` nằm dưới một `textarea` trong suốt chữ. Con trỏ và vùng chọn vẫn là của trình duyệt. Nếu JS lỗi, lớp tô màu không được bật và mã nguồn vẫn đọc được bình thường.
- **Ô soạn thảo tự giãn theo nội dung**, tối thiểu 210 px, tối đa 620 px rồi mới cuộn.
- **Trợ năng:** liên kết bỏ qua điều hướng, vòng tiêu điểm rõ ràng, vùng chạm tối thiểu 44×44 px, `aria-sort` cho cột sắp xếp, tóm tắt lỗi biểu mẫu nhận tiêu điểm, thẻ dùng `role="tab"` và điều hướng bằng phím mũi tên, tôn trọng `prefers-reduced-motion`.
- **Không tràn ngang ở 390 px** trên cả 11 trang (đã đo bằng script, không phải ước lượng).
- **Trang chi tiết bài nộp** giải thích được lỗi cụ thể: bộ dữ liệu 5 có `1500000000 1500000000`, kết quả đúng là `3000000000` nhưng chương trình in ra `-1294967296` — tràn số `int`. Đây là lỗi dịch không báo, chạy không sập, chỉ sai kết quả.

## Bước tiếp theo

1. Chốt giao diện với giáo viên, sửa những chỗ chưa hợp ý.
2. Dựng VNOJ (bản Việt hoá của DMOJ) trên máy ảo Linux, chạy thử một bài C++.
3. Chuyển CSS/JS này vào template Django — giữ nguyên `demo/assets/css/style.css`, chỉ đổi phần đánh dấu thành cú pháp template.
4. Nối dần từng phần: đăng nhập → danh sách đề → nộp bài → kết quả.
5. Tinh gọn DMOJ theo nhóm tính năng đã chốt trong `bao-cao-dmoj-tinh-gon.html`.

## Ghi chú về giấy phép

Phần mã trong repo này là giao diện viết mới, không chứa mã nguồn DMOJ.

Kế hoạch triển khai dựa trên **DMOJ** / **VNOJ**, cả hai đều theo giấy phép **AGPL-3.0**. Nếu lấy mã của họ vào, repo phải giữ giấy phép AGPL-3.0 và công khai toàn bộ mã nguồn phía máy chủ. Điều này cần cân nhắc trước khi triển khai chính thức.
