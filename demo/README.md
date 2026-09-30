# Bản demo giao diện — Hệ thống chấm bài lập trình

Demo front end cho online judge của Trường THCS Sông Lô. **Chưa có backend** — toàn bộ dữ liệu trong trang là ví dụ viết cứng.

Tổng quan dự án, ảnh chụp và bảng màu: xem [`../README.md`](../README.md).

## Xem thử

Cần chạy qua HTTP, không mở trực tiếp bằng `file://` (trình duyệt sẽ chặn tải phông chữ do CORS):

```bash
cd demo
python -m http.server 8777
```

Rồi mở `http://127.0.0.1:8777/`.

## Các trang

Nhóm học sinh:

| Tệp | Nội dung |
|---|---|
| `index.html` | Trang chủ — số liệu, kỳ thi sắp tới có đếm ngược, đề mới, bảng xếp hạng tuần, bài nộp gần đây |
| `problems.html` | Danh sách đề — tìm kiếm, lọc theo độ khó và chủ đề, bảng sắp xếp được, phân trang |
| `problem.html` | Chi tiết đề + nộp bài — 3 thẻ: Đề bài / Nộp bài / Kết quả chấm |
| `submissions.html` | Danh sách bài nộp — lọc theo kết quả, ngôn ngữ, khoảng thời gian; có thống kê phân loại |
| `submission.html` | Chi tiết một lần nộp — kết luận, so sánh ở bộ dữ liệu chưa đạt, bảng kết quả từng bộ, mã nguồn tô màu, nhật ký dịch |
| `contests.html` | Kỳ thi — kỳ thi đang diễn ra, sắp diễn ra, đã kết thúc |
| `leaderboard.html` | Bảng xếp hạng — top 3, biểu đồ cột ngang, bảng đầy đủ sắp xếp được |
| `login.html` | Đăng nhập — có minh hoạ báo lỗi theo chuẩn trợ năng |

Nhóm giáo viên:

| Tệp | Nội dung |
|---|---|
| `teacher.html` | Tổng quan — tiến độ từng lớp, bài nộp gần đây, việc cần xử lý, kỳ thi sắp tới |
| `teacher-problems.html` | Soạn đề — danh sách đề kèm trạng thái duyệt, biểu mẫu tạo đề, bảng bộ dữ liệu (có cột ẩn/công khai), vùng nhập tệp zip |
| `teacher-classes.html` | Lớp học & điểm — sổ điểm từng lớp, thống kê tài khoản, xuất bảng điểm |

Nút chuyển vai trò **Học sinh / Giáo viên** nằm ở góc trên bên phải mỗi trang. Đây là chi tiết riêng của bản demo để xem được cả hai phía mà không cần đăng nhập; khi nối backend thì bỏ đi.

Cạnh đó là nút đổi **chế độ sáng / tối**. Lần đầu truy cập, trang theo cài đặt hệ điều hành; sau khi người dùng tự bấm thì lựa chọn được nhớ trong `localStorage` và không bị ghi đè nữa.

Liên kết sâu tới từng thẻ, ví dụ `problem.html#panel-submit` mở thẳng phần nộp bài.

## Cấu trúc

```
demo/
├── index.html · problems.html · problem.html · submissions.html · submission.html
├── contests.html · leaderboard.html · login.html
├── teacher.html · teacher-problems.html · teacher-classes.html
└── assets/
    ├── css/style.css     Toàn bộ hệ thống thiết kế (token + thành phần)
    ├── js/app.js         Tương tác, không phụ thuộc thư viện ngoài
    └── img/              logo.png (huy hiệu trường, nền trong suốt)
                          hero.jpg (nền mờ cho khối hero ở trang chủ)
```

Không có bước build. Không dùng framework. CSS và JS đều là file tĩnh — chuyển thẳng sang template Django được.

## Hệ thống thiết kế

Phong cách **Swiss grid + product UI**: lưới rõ ràng, tương phản cao, đổ bóng thật để tạo chiều sâu, thang chữ dứt khoát. Phù hợp công cụ dữ liệu dày đặc.

Bảng màu và phông chữ: xem bảng đầy đủ trong [`../README.md`](../README.md).

### Huy hiệu nhà trường

Biểu trưng ở header là huy hiệu chính thức của trường (`assets/img/logo.png`), nền đã xoá thành trong suốt. Vì trong suốt nên chỉ cần **một tệp duy nhất** cho cả hai chế độ — không có biến thể sáng/tối riêng. Lưu ý: phần nền trắng *bên trong* vòng tròn là một phần thiết kế của huy hiệu, nên ở chế độ tối huy hiệu hiện ra như một huy hiệu tròn nền sáng.

Hiển thị ở **52×52 px** (khai báo trong `.site-head__mark`). Huy hiệu có vòng chữ nhỏ bao quanh nên dưới khoảng 50 px là nhoè. Nhớ sửa cả thuộc tính `width`/`height` trên thẻ `<img>` ở mọi trang cho khớp.

Ô `alt` của ảnh để rỗng có chủ ý: tên trường nằm ngay bên cạnh huy hiệu, nên nếu đọc cả hai thì trình đọc màn hình sẽ lặp lại thông tin hai lần.

### Chế độ tối

Mọi thành phần chỉ tham chiếu **token ngữ nghĩa** (`--bg`, `--surface`, `--fg`, `--border`, `--link`, `--ink`, `--fill`, `--row-alt`, `--track`, `--deep`, các màu kết quả…) chứ không dùng mã màu trực tiếp. Nhờ vậy toàn bộ chế độ tối nằm gọn trong một khối `html[data-theme="dark"]` dài khoảng 45 dòng — không có quy tắc nào của thành phần bị viết lại lần hai.

Đổi chế độ được thực hiện bằng một đoạn script nhỏ đặt trong `<head>`, chạy **trước lần vẽ đầu tiên**, nên không có hiện tượng nháy trắng khi tải trang.

## Trợ năng

Đã áp dụng theo danh sách kiểm tra trước khi giao:

- Liên kết "Bỏ qua điều hướng" ở đầu mỗi trang
- Vòng tiêu điểm rõ ràng trên mọi thành phần tương tác, không bao giờ xoá `outline` mà không thay thế
- Vùng chạm tối thiểu 44×44 px
- Bảng có `caption` ẩn, tiêu đề cột sắp xếp được báo trạng thái qua `aria-sort`
- Không dùng màu đơn thuần để báo trạng thái — ô trạng thái trong danh sách đề có cả nhãn cho trình đọc màn hình
- Biểu đồ cột có bảng số liệu đầy đủ ngay bên dưới
- Biểu mẫu đăng nhập: tóm tắt lỗi đặt trên cùng, nhận tiêu điểm khi gửi thất bại, mỗi lỗi liên kết tới đúng ô nhập, kèm lỗi ngay tại ô
- Thẻ dùng `role="tab"` / `role="tabpanel"`, điều hướng bằng phím mũi tên, `Home`, `End`
- Tôn trọng `prefers-reduced-motion`
- Có kiểu in riêng cho trang đề bài
- Nút đổi chế độ sáng/tối có `aria-pressed` và nhãn đổi theo trạng thái hiện tại
- Không tràn ngang ở bề rộng 390 px trên cả 11 trang

## Chi tiết kỹ thuật đáng chú ý

**Tô màu cú pháp C++ không dùng thư viện.** `app.js` có một bộ tách từ bằng một biểu thức chính quy duy nhất, chạy trên lớp `<pre class="editor__hl">` nằm dưới một `textarea` trong suốt chữ. Con trỏ, vùng chọn và thao tác cuộn vẫn là của trình duyệt. Lớp `is-hl` chỉ được bật sau khi lớp tô màu đã vẽ xong — nếu JS lỗi thì chữ trong `textarea` vẫn hiện bình thường.

Hai lớp phải trùng khít số đo phông (cùng `font-family`, `font-size`, `line-height`, `padding`, `tab-size`) nếu không mã nguồn sẽ lệch khỏi cột số dòng.

**Ô soạn thảo tự giãn** theo nội dung, tối thiểu 210 px, tối đa 620 px rồi mới cuộn — tránh mảng tối trống bên dưới những bài ngắn.

**Bộ lọc bảng** dùng chung một hàm cho cả tìm kiếm chữ, nút chọn nhanh (chip) và ô chọn: mỗi `<select data-filter-select data-filter-key="verdict">` được đối chiếu với thuộc tính `data-verdict` của dòng.

**Khung xem mã nguồn chỉ đọc** (`submission.html`) dùng lại đúng bộ tô màu của ô soạn thảo nhưng bỏ hẳn `textarea` — chỉ còn một lớp `<pre>` đã tô màu, nên không có gì phải đồng bộ ngoài cột số dòng. Việc tô màu là tuỳ chọn theo từng khối: nhật ký dịch đặt `data-lang="text"` để giữ nguyên văn, không bị tô nhầm.

## Chưa làm

- **Toàn bộ backend.** Chưa có đăng nhập thật, chưa lưu gì, chưa chấm bài.
- Nút "Nộp bài" chỉ hiện thông báo, không gửi đi đâu.
- Bộ lọc và phân trang chạy phía trình duyệt trên dữ liệu cứng.
- Bảng xếp hạng chưa lọc theo lớp thật (ô chọn "Phạm vi" chỉ để minh hoạ).
- Trang soạn đề chưa có nút chạy thử bộ dữ liệu cục bộ.

## Bước tiếp theo

1. Chốt giao diện với giáo viên, sửa những chỗ chưa hợp ý.
2. Dựng VNOJ trên máy ảo Linux, chạy thử một bài C++.
3. Chuyển CSS/JS này vào template Django của DMOJ — giữ nguyên `assets/css/style.css`, chỉ đổi phần đánh dấu thành cú pháp template.
4. Nối dần từng phần: đăng nhập → danh sách đề → nộp bài → kết quả.
