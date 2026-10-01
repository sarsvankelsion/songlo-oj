"""Nhận, kiểm tra và cắt ảnh đại diện của học sinh.

Bốn quyết định, và lý do của từng cái:

1. **Ảnh được mã hoá lại, không lưu nguyên tệp tải lên.** Đọc bằng Pillow rồi
   ghi ra PNG mới nghĩa là mọi thứ không phải điểm ảnh đều bị bỏ: EXIF (có thể
   chứa toạ độ GPS nhà học sinh), chú thích, và cả những tệp được chế ra để vừa
   là ảnh vừa là thứ khác. Tải lên một tệp `.php` đổi tên thành `.png` cũng
   không qua được bước này vì Pillow không mở được nó.

2. **Luôn ghi ra PNG, cố định kích thước 256×256, cắt giữa.** Giữ nguyên kích
   thước gốc thì một ảnh 6000×4000 sẽ được phục vụ nguyên cho mọi người xem
   trang — vừa chậm vừa tốn băng thông. Cắt vuông ở giữa thay vì bóp méo: bóp
   méo ảnh chân dung trông như lỗi.

3. **Tên tệp có một token ngẫu nhiên, và tên cũ bị xoá.** Nhờ token, đổi ảnh là
   đổi luôn URL, nên trình duyệt và Cloudflare không thể phục vụ ảnh cũ từ đệm.
   Không có token thì học sinh đổi ảnh mà vẫn thấy ảnh cũ, và không có cách nào
   giải thích cho em ấy rằng phải nhấn Ctrl+F5.

4. **Trần kích thước tệp và trần số điểm ảnh.** Trần tệp chặn việc tải lên một
   tệp 200 MB. Trần điểm ảnh chặn "bom giải nén": một tệp PNG vài chục KB có
   thể khai báo kích thước 50000×50000, và Pillow sẽ cố cấp phát 10 GB khi giải
   nén. Đây là kiểu tấn công làm sập máy chủ mà nhìn tệp tải lên không thấy gì.
"""

from __future__ import annotations

import secrets
from pathlib import Path

# Trần kích thước tệp tải lên, tính bằng byte. Ảnh chân dung chụp bằng điện
# thoại thường 2–5 MB, nên 5 MB là đủ rộng rãi mà vẫn chặn được tệp lớn.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Cạnh của ảnh vuông lưu lại.
AVATAR_SIZE = 256

# Trần số điểm ảnh khi giải nén. 20 triệu điểm ảnh tương đương ảnh 4472×4472 —
# rộng hơn mọi ảnh điện thoại thật, nhưng chặn được bom giải nén.
MAX_PIXELS = 20_000_000

# Định dạng cho phép đọc vào. Loại trừ SVG: SVG là XML, có thể chứa JavaScript,
# và phục vụ nó cùng tên miền với trang web là mở đường cho đánh cắp phiên.
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "BMP", "WEBP", "TIFF"}

DIR_NAME = "avatars"


def avatars_dir(var_dir) -> Path:
    """Thư mục chứa ảnh đại diện. Tạo nếu chưa có."""
    path = Path(var_dir) / DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pillow():
    """Nhập Pillow muộn, và nói rõ nếu thiếu.

    Nhập ở cấp mô-đun sẽ làm cả ứng dụng không khởi động được khi máy chủ thiếu
    Pillow — trong khi mọi tính năng khác vẫn chạy tốt. Nhập ở đây thì chỉ riêng
    việc tải ảnh lên là hỏng, và thông báo nói đúng nguyên nhân.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None, None, "Máy chủ chưa cài Pillow nên chưa nhận được ảnh. Báo giáo viên phụ trách."
    return Image, ImageOps, None


def save_avatar(var_dir, user_id: int, storage) -> tuple[str, str | None]:
    """Xử lý một tệp tải lên và trả về ``(tên_tệp_mới, lỗi)``.

    Đúng một trong hai giá trị khác rỗng. Không ném ngoại lệ ra ngoài: mọi kiểu
    tệp hỏng đều phải trở thành một câu thông báo đọc được, vì người tải lên là
    học sinh cấp 2 chứ không phải người gỡ lỗi.
    """
    Image, ImageOps, err = _pillow()
    if err:
        return "", err

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS

    if storage is None or not getattr(storage, "filename", ""):
        return "", "Em chưa chọn ảnh nào."

    # Đọc vào bộ nhớ trước rồi mới xử lý. Đọc thẳng từ luồng của request cũng
    # được, nhưng khi cần mở lại lần hai (bước kiểm tra tính toàn vẹn) thì luồng
    # đã ở cuối và phải seek — làm sẵn ở đây cho rõ ràng.
    raw = storage.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return "", "Ảnh quá lớn (giới hạn %d MB). Em chọn ảnh nhỏ hơn nhé." % (
            MAX_UPLOAD_BYTES // (1024 * 1024))
    if not raw:
        return "", "Tệp rỗng, em chọn lại ảnh khác nhé."

    import io

    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = (probe.format or "").upper()
        if fmt not in ALLOWED_FORMATS:
            return "", "Định dạng ảnh không hợp lệ. Em dùng PNG, JPG hoặc WEBP nhé."
        # verify() phát hiện tệp bị cắt cụt hoặc hỏng cấu trúc. Sau khi gọi nó,
        # đối tượng ảnh không dùng lại được nữa — phải mở lại từ đầu.
        probe.verify()
    except Image.DecompressionBombError:
        return "", "Ảnh có kích thước quá lớn để xử lý."
    except Exception:
        return "", "Tệp này không đọc được như một ảnh. Em chọn ảnh khác nhé."

    try:
        img = Image.open(io.BytesIO(raw))
        # exif_transpose xoay ảnh theo thẻ Orientation trong EXIF trước khi ta
        # bỏ EXIF đi. Không làm bước này thì ảnh chụp dọc bằng điện thoại sẽ
        # nằm ngang sau khi lưu.
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), method=Image.LANCZOS,
                           centering=(0.5, 0.5))
        if img.mode == "RGBA":
            # Nền trong suốt sẽ thành đen khi hiển thị trên nền tối của một số
            # trình duyệt. Ghép lên nền trắng để ảnh luôn đọc được.
            from PIL import Image as _Image

            bg = _Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
    except Image.DecompressionBombError:
        return "", "Ảnh có kích thước quá lớn để xử lý."
    except Exception:
        return "", "Không xử lý được ảnh này. Em thử ảnh khác nhé."

    name = "%d-%s.png" % (user_id, secrets.token_hex(8))
    target = avatars_dir(var_dir) / name
    try:
        img.save(target, "PNG", optimize=True)
    except Exception:
        return "", "Không ghi được ảnh lên máy chủ. Em thử lại sau."
    return name, None


def delete_avatar(var_dir, filename: str) -> None:
    """Xoá tệp ảnh cũ. Không báo lỗi nếu tệp đã không còn.

    Cố tình bỏ qua **mọi** lỗi ở đây, kể cả những lỗi không phải "không tìm thấy
    tệp": quyền ghi sai, hệ tệp chỉ đọc, hoặc trên Windows tệp đang bị một tiến
    trình khác mở. Hệ quả duy nhất của việc bỏ qua là một tệp mồ côi nằm lại —
    vài chục KB, không ai trỏ tới, không phải vấn đề bảo mật. Đổi lại, làm hỏng
    cả thao tác đổi ảnh đại diện chỉ vì không xoá được ảnh cũ là đánh đổi sai:
    học sinh sẽ thấy báo lỗi dù ảnh mới đã lưu thành công.

    Điều **không** được bỏ qua là đường dẫn: tên tệp đọc từ CSDL, nên nếu ai đó
    sửa tay cho nó chứa `/` hoặc `..` thì ghép thẳng vào đường dẫn sẽ cho phép
    xoá tệp nằm ngoài thư mục ảnh. Chặn ở đây chứ không tin dữ liệu.
    """
    if not filename:
        return
    if "/" in filename or "\\" in filename or ".." in filename:
        return
    try:
        (avatars_dir(var_dir) / filename).unlink(missing_ok=True)
    except OSError:
        pass
