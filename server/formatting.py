"""Bộ lọc định dạng dùng trong template.

Mọi con số và thời điểm hiển thị cho người dùng đều đi qua đây. Lý do: định dạng
tiếng Việt khác định dạng mặc định của Python ở cả dấu thập phân (``,`` thay vì
``.``) lẫn dấu phân cách nghìn (``.`` thay vì ``,``). Để nguyên định dạng mặc
định thì điểm số hiện ra thành ``1,204`` trong khi học sinh đọc là "một nghìn
hai trăm linh bốn" — và ngược lại ``0.31`` đọc thành "không phẩy ba một" thì
đúng nhưng không nhất quán với phần còn lại của giao diện.
"""

from __future__ import annotations

from . import db
from .judge import VERDICT_LABEL

DIFFICULTY_LABEL = {
    "co-ban": "Cơ bản",
    "trung-binh": "Trung bình",
    "nang-cao": "Nâng cao",
}

# Lớp CSS cho nhãn độ khó. Tái dùng đúng các lớp đã có trong style.css.
DIFFICULTY_CLASS = {
    "co-ban": "badge badge--green",
    "trung-binh": "badge",
    "nang-cao": "badge badge--red",
}

PROBLEM_STATUS_LABEL = {
    "draft": "Bản nháp",
    "review": "Chờ duyệt",
    "live": "Đã công khai",
}

PROBLEM_STATUS_CLASS = {
    "draft": "badge badge--grey",
    "review": "badge badge--red",
    "live": "badge badge--green",
}

SUBMISSION_STATUS_LABEL = {
    "pending": "Đang chờ chấm",
    "judging": "Đang chấm",
    "done": "Đã chấm",
    "error": "Lỗi hệ thống chấm",
}

# Lớp CSS của nhãn kết quả. Phải phủ hết các mã trong judge.VERDICT_LABEL, nếu
# thiếu một mã thì nhãn sẽ mất màu chứ không lỗi — nên có bài kiểm thử cho việc
# này ở tests/.
VERDICT_CLASS = {
    "AC": "verdict verdict--ac",
    "WA": "verdict verdict--wa",
    "TLE": "verdict verdict--tle",
    "MLE": "verdict verdict--tle",
    "RE": "verdict verdict--rte",
    "CE": "verdict verdict--ce",
    "IE": "verdict verdict--ce",
    "": "verdict verdict--pending",
}

# Lớp CSS cho ô vuông nhỏ trong bảng danh sách đề.
VERDICT_DOT_CLASS = {
    "AC": "dot dot--ac",
    "WA": "dot dot--wa",
    "TLE": "dot dot--tle",
    "MLE": "dot dot--tle",
    "RE": "dot dot--wa",
    "CE": "dot dot--wa",
}

# Lớp CSS cho dải kết luận ở đầu trang chi tiết bài nộp. Chỉ có bốn biến thể
# màu, nên các mã được gom nhóm: nhóm "quá tài nguyên" dùng chung màu cam, nhóm
# "chương trình hỏng" dùng chung màu xám.
VBAR_CLASS = {
    "AC": "vbar vbar--ac",
    "WA": "vbar vbar--wa",
    "TLE": "vbar vbar--tle",
    "MLE": "vbar vbar--tle",
    "RE": "vbar vbar--ce",
    "CE": "vbar vbar--ce",
    "IE": "vbar vbar--ce",
    "": "vbar",
}


# ------------------------------------------------------------------- số
def vn_number(value) -> str:
    """1234567 -> '1.234.567'."""
    if value is None:
        return "0"
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def vn_decimal(value, places: int = 2) -> str:
    """0.31 -> '0,31'."""
    if value is None:
        return "0"
    return f"{float(value):.{places}f}".replace(".", ",")


def vn_percent(part, whole) -> str:
    if not whole:
        return "0%"
    return f"{round(part / whole * 100)}%"


# --------------------------------------------------------------- thời gian
def vn_datetime(value) -> str:
    dt = db.to_local(value)
    return dt.strftime("%H:%M · %d/%m/%Y") if dt else "—"


def vn_time(value) -> str:
    dt = db.to_local(value)
    return dt.strftime("%H:%M") if dt else "—"


def vn_day_month(value) -> str:
    dt = db.to_local(value)
    return dt.strftime("%H:%M · %d/%m") if dt else "—"


def vn_date(value) -> str:
    dt = db.to_local(value)
    return dt.strftime("%d/%m/%Y") if dt else "—"


def vn_date_long(value) -> str:
    """'Thứ Sáu, 20/11/2026 · 08:00' — dùng cho danh sách kỳ thi."""
    dt = db.to_local(value)
    if not dt:
        return "—"
    weekday = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][dt.weekday()]
    return f"{weekday}, {dt.strftime('%d/%m/%Y')} · {dt.strftime('%H:%M')}"


def relative_time(value) -> str:
    """'2 giờ trước', 'Hôm qua', '3 ngày trước'."""
    dt = db.to_local(value)
    if not dt:
        return "—"
    now = db.to_local(db.utc_now())
    seconds = (now - dt).total_seconds()
    if seconds < 60:
        return "Vừa xong"
    if seconds < 3600:
        return f"{int(seconds // 60)} phút trước"
    if seconds < 86400:
        return f"{int(seconds // 3600)} giờ trước"
    days = int(seconds // 86400)
    if days == 1:
        return "Hôm qua"
    if days < 30:
        return f"{days} ngày trước"
    return vn_date(value)


# ------------------------------------------------------------- số đo chấm bài
def vn_seconds(ms_value) -> str:
    """310 -> '0,31 s'. Dùng cho thời gian chạy."""
    if not ms_value:
        return "—"
    return f"{ms_value / 1000:.2f}".replace(".", ",") + " s"


def vn_memory(kb_value) -> str:
    """2150 -> '2,1 MB'. Dùng cho bộ nhớ."""
    if not kb_value:
        return "—"
    if kb_value < 1024:
        return f"{kb_value} KB"
    return f"{kb_value / 1024:.1f}".replace(".", ",") + " MB"


def vn_runtime(ms_value, limit_ms=None, verdict: str = "") -> str:
    """Thời gian chạy để hiển thị, có xử lý riêng cho bài quá thời gian.

    Với bài quá thời gian, con số đo được **không phải** thời gian chương trình
    cần để chạy xong — đó là lúc hệ thống cắt nó. In thẳng ra sẽ thành
    "5,02 s" trong khi giới hạn của đề là 1 giây, và học sinh hiểu sai thành
    chương trình của mình chậm gấp năm lần. Con số đó chỉ là một **cận dưới**,
    nên in "> 1,00 s" mới đúng điều đo được.

    Con số này còn phụ thuộc nền tảng: trên máy chủ là thời gian CPU, còn trên
    Windows là thời gian thực (xem ghi chú đầu ``sandbox.py``). Cùng một bài có
    thể ra hai số khác nhau, nên càng không nên in nó như một sự thật tuyệt đối.
    """
    if verdict == "TLE" and limit_ms:
        return "> " + vn_seconds(limit_ms)
    return vn_seconds(ms_value)


def vn_range(starts_at, ends_at) -> str:
    """Khoảng thời gian của một kỳ thi.

    Vì sao cần filter riêng: mẫu cũ là ``{{ starts_at|vn_date_long }} –
    {{ ends_at|vn_time }}``. ``vn_date_long`` đã kèm cả giờ, còn ``vn_time`` chỉ
    có giờ — nên một kỳ thi chạy từ 23/09 tới 03/10 hiện thành
    "Thứ Tư, 23/09/2026 · 19:44 – 19:44", trông như kỳ thi dài 0 phút vì **ngày
    kết thúc biến mất**. Chỉ in giờ ở vế sau khi hai mốc cùng một ngày.
    """
    start = db.to_local(starts_at)
    end = db.to_local(ends_at)
    if not start or not end:
        return "—"
    head = vn_date_long(starts_at)
    if start.date() == end.date():
        return f"{head} – {end.strftime('%H:%M')}"
    return f"{head} – {vn_date_long(ends_at)}"


# ------------------------------------------------------------- nhãn và lớp
def avatar_initials(full_name: str) -> str:
    """'Nguyễn Văn An' -> 'NA'.

    Tên người Việt viết theo thứ tự họ — đệm — tên, nên hai chữ cái đầu của
    chuỗi là họ và tên đệm (ví dụ 'Nguyễn Văn' -> 'NV'), không phải thứ người
    đọc nhận ra. Lấy **họ** và **tên** mới đúng thói quen: 'NA', 'TB', 'MC'.
    """
    parts = [p for p in (full_name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def verdict_text(code: str) -> str:
    return VERDICT_LABEL.get(code or "", "Đang chấm")


def verdict_class(code: str) -> str:
    return VERDICT_CLASS.get(code or "", "verdict verdict--pending")


def verdict_dot(code: str) -> str:
    return VERDICT_DOT_CLASS.get(code or "", "dot dot--none")


def vbar_class(code: str) -> str:
    return VBAR_CLASS.get(code or "", "vbar")


def difficulty_text(code: str) -> str:
    return DIFFICULTY_LABEL.get(code or "", code or "")


def difficulty_class(code: str) -> str:
    return DIFFICULTY_CLASS.get(code or "", "badge")


def problem_status_text(code: str) -> str:
    return PROBLEM_STATUS_LABEL.get(code or "", code or "")


def problem_status_class(code: str) -> str:
    return PROBLEM_STATUS_CLASS.get(code or "", "badge badge--grey")


def submission_status_text(code: str) -> str:
    return SUBMISSION_STATUS_LABEL.get(code or "", code or "")


def register_filters(app) -> None:
    app.jinja_env.filters.update(
        vn_number=vn_number,
        vn_decimal=vn_decimal,
        vn_percent=vn_percent,
        vn_datetime=vn_datetime,
        vn_time=vn_time,
        vn_day_month=vn_day_month,
        vn_date=vn_date,
        vn_date_long=vn_date_long,
        vn_range=vn_range,
        relative_time=relative_time,
        vn_seconds=vn_seconds,
        vn_memory=vn_memory,
        vn_runtime=vn_runtime,
        avatar_initials=avatar_initials,
        verdict_text=verdict_text,
        verdict_class=verdict_class,
        verdict_dot=verdict_dot,
        vbar_class=vbar_class,
        difficulty_text=difficulty_text,
        difficulty_class=difficulty_class,
        problem_status_text=problem_status_text,
        problem_status_class=problem_status_class,
        submission_status_text=submission_status_text,
    )
