"""Đăng nhập, phiên làm việc, phân quyền và chống CSRF.

Ba quyết định đáng giải thích:

1. **Mật khẩu băm bằng PBKDF2-SHA256 của Werkzeug**, không phải SHA256 thuần.
   Băm thuần không có yếu tố làm chậm, nên một bảng tra sẵn (rainbow table) phá
   được gần như tức thì. PBKDF2 lặp hàng trăm nghìn lần khiến việc thử mật khẩu
   trở nên đắt. Werkzeug có sẵn trong Flask nên không thêm phụ thuộc.

2. **Phiên làm việc nằm trong cookie có chữ ký**, không có bảng session trong
   CSDL. Với một trường học, điều này bỏ được một bảng và một truy vấn cho mỗi
   request. Đổi lại: không thể thu hồi phiên của một người ngay lập tức. Cách xử
   lý: khi giáo viên khoá một tài khoản, mọi request sau đó của tài khoản ấy bị
   từ chối vì :func:`current_user` đọc lại ``is_active`` từ CSDL mỗi lần — chỉ
   còn lại một khoảng trễ bằng thời gian sống tối đa của cookie.

3. **CSRF được kiểm tra ở tầng hook trước request**, không phải ở từng tuyến
   đường. Kiểm tra ở từng chỗ thì chỉ cần quên một chỗ là hở; kiểm tra tập trung
   thì mặc định là an toàn và muốn miễn trừ phải nói rõ.
"""

from __future__ import annotations

import functools
import hmac
import secrets
from datetime import timedelta

from flask import flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

# Số vòng lặp PBKDF2. 260 000 là mức khuyến nghị của OWASP cho PBKDF2-SHA256
# tại thời điểm viết. Máy chủ trường học chỉ băm một lần cho mỗi lần đăng nhập
# nên chi phí này không đáng kể.
PBKDF2_ITERATIONS = 260_000

CSRF_SESSION_KEY = "_csrf"
CSRF_FIELD_NAME = "_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Các phương thức làm thay đổi dữ liệu, tức là phải có CSRF.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# ------------------------------------------------------------------ mật khẩu
def hash_password(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        # Chuỗi băm hỏng hoặc sai định dạng: coi như không khớp thay vì để lỗi
        # 500 lộ ra ngoài.
        return False


def make_temp_password(length: int = 10) -> str:
    """Sinh mật khẩu tạm để giáo viên phát cho học sinh.

    Bỏ các ký tự dễ nhìn nhầm khi đọc trên giấy: ``0/O``, ``1/l/I``. Mật khẩu
    này được đọc to hoặc chép tay trong phòng máy, nên khả năng đọc đúng quan
    trọng hơn vài bit entropy.

    **Và chỉ dùng chữ thường.** Bản trước trộn cả chữ hoa, mà chữ hoa thì không
    đọc được thành lời: `EpxWn7Dq3E` đọc lên là "e p x w n 7 d q 3 e" — người
    nghe gõ đúng chuỗi đó và bị từ chối, trong khi mật khẩu hoàn toàn đúng. Đo
    được trên máy chủ thật: cùng một mật khẩu, gõ nguyên văn thì vào, gõ chữ
    thường thì nhận `401`. Cả mục đích của hàm này là để đọc cho người khác
    chép, nên giữ chữ hoa là tự phá mục đích của chính nó.

    Mất khoảng 7 bit so với bảng chữ cái trộn hoa/thường (10 ký tự × log2(33)
    ≈ 50 bit). Không đáng lo: đây là mật khẩu dùng một lần, bị bắt đổi ngay lần
    đăng nhập đầu, và băm bằng PBKDF2.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# --------------------------------------------------------------------- CSRF
def csrf_token() -> str:
    """Lấy token CSRF của phiên hiện tại, tạo mới nếu chưa có."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _csrf_ok() -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        # Chưa có token trong phiên: mọi biểu mẫu đều đã gọi csrf_token() khi
        # render, nên trường hợp này chỉ xảy ra với request không do người dùng
        # thật gửi. Từ chối.
        return False
    supplied = request.form.get(CSRF_FIELD_NAME) or request.headers.get(CSRF_HEADER_NAME, "")
    # So sánh bằng hmac.compare_digest để thời gian so sánh không phụ thuộc vào
    # số ký tự trùng đầu — so sánh bằng `==` rò rỉ thông tin qua thời gian.
    return hmac.compare_digest(str(supplied), str(expected))


# ---------------------------------------------------------------- người dùng
def current_user():
    """Người dùng đang đăng nhập, hoặc ``None``.

    Kết quả được nhớ trong ``g`` cho từng request để không truy vấn lại nhiều
    lần trong cùng một lần render.
    """
    if "user" in g:
        return g.user

    uid = session.get("uid")
    if not uid:
        g.user = None
        return None

    row = db.query_one(
        db.get_db(),
        "SELECT * FROM users WHERE id = ? AND is_active = 1",
        (uid,),
    )
    if row is None:
        # Tài khoản đã bị khoá hoặc bị xoá trong lúc phiên còn hiệu lực.
        session.pop("uid", None)
    g.user = row
    return row


def login_user(user_row) -> None:
    session.clear()
    session["uid"] = user_row["id"]
    # Tạo token CSRF mới sau khi đăng nhập: token cũ thuộc về phiên ẩn danh, và
    # giữ nguyên nó qua bước đăng nhập là điều kiện cho tấn công cố định phiên.
    session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    session.permanent = True


def logout_user() -> None:
    session.clear()


def is_teacher(user=None) -> bool:
    user = user if user is not None else current_user()
    return bool(user) and user["role"] in ("teacher", "admin")


def is_admin(user=None) -> bool:
    user = user if user is not None else current_user()
    return bool(user) and user["role"] == "admin"


# ---------------------------------------------------------------- phân quyền
def login_required(view):
    """Yêu cầu đã đăng nhập. Chưa đăng nhập thì chuyển tới trang đăng nhập."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Em cần đăng nhập để xem trang này.", "warn")
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def teacher_required(view):
    """Yêu cầu vai trò giáo viên hoặc quản trị.

    Trả về 403 chứ không chuyển hướng: người dùng đã đăng nhập nhưng không đủ
    quyền, và chuyển hướng sẽ khiến họ tưởng mình chưa đăng nhập.
    """

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Em cần đăng nhập để xem trang này.", "warn")
            return redirect(url_for("login", next=request.full_path))
        if not is_teacher(user):
            from flask import abort

            abort(403)
        return view(*args, **kwargs)

    return wrapped


# ------------------------------------------------------------ tích hợp Flask
def init_app(app) -> None:
    app.permanent_session_lifetime = timedelta(days=14)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    # Bật dòng dưới khi chạy thật sau HTTPS. Để tắt khi thử ở máy cá nhân vì
    # trình duyệt sẽ không gửi cookie qua http://127.0.0.1.
    # app.config.setdefault("SESSION_COOKIE_SECURE", True)

    @app.before_request
    def _protect_unsafe_methods():
        if request.method in UNSAFE_METHODS and not _csrf_ok():
            from flask import abort

            abort(400, description="Thiếu hoặc sai mã CSRF. Tải lại trang rồi thử lại.")

    @app.context_processor
    def _inject_user():
        return {
            "current_user": current_user(),
            "csrf_token": csrf_token,
            "is_teacher": is_teacher(),
        }
