"""Kết nối SQLite, khởi tạo lược đồ, và các tiện ích thời gian.

Không dùng ORM. Với quy mô một trường, câu SQL viết thẳng dễ đọc hơn và không
thêm phụ thuộc nào phải cài.

Hai quy ước quan trọng, áp dụng cho toàn bộ mã nguồn:

1. **Mọi thời điểm lưu trong CSDL đều là UTC**, dạng ``2026-09-30T12:34:56Z``.
   Nhờ vậy so sánh chuỗi là đúng thứ tự thời gian và không phụ thuộc múi giờ
   của máy chủ. Đổi sang giờ Việt Nam chỉ xảy ra ở tầng hiển thị
   (:func:`to_local`). Nếu lưu giờ địa phương, một lần đổi múi giờ của VPS sẽ
   làm toàn bộ dữ liệu cũ sai lệch mà không ai phát hiện.

2. **Thời gian chạy là mili giây, bộ nhớ là KB, đều là số nguyên.** Dùng số
   thực ở đây sẽ kéo theo sai số khi so sánh với giới hạn.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Múi giờ Việt Nam là UTC+7 và **không có giờ mùa hè**, nên một độ lệch cố định
# là đúng quanh năm. Dùng `timezone(timedelta(hours=7))` thay vì tên vùng
# `Asia/Ho_Chi_Minh` để không phụ thuộc cơ sở dữ liệu múi giờ của hệ điều hành —
# trên một VPS tối giản, tên vùng đó có thể không tồn tại.
VN_TZ = timezone(timedelta(hours=7), name="ICT")

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


# ---------------------------------------------------------------- thời gian
def utc_now() -> str:
    """Thời điểm hiện tại, dạng chuỗi ISO-8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str | None) -> datetime | None:
    """Đọc chuỗi ISO-8601 do :func:`utc_now` sinh ra."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def to_local(value: str | None) -> datetime | None:
    """Đổi một mốc UTC trong CSDL sang giờ Việt Nam để hiển thị."""
    dt = parse_utc(value)
    return dt.astimezone(VN_TZ) if dt else None


def iso_from_local_input(value: str) -> str | None:
    """Đổi chuỗi ``datetime-local`` của biểu mẫu HTML (giờ Việt Nam) sang UTC.

    ``<input type="datetime-local">`` gửi lên ``2026-11-20T08:00`` — đó là giờ
    tường mà giáo viên gõ, tức giờ Việt Nam. Ghi thẳng chuỗi này vào CSDL sẽ
    lệch 7 tiếng.
    """
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=VN_TZ).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return None


def local_input_value(value: str | None) -> str:
    """Chiều ngược lại: UTC trong CSDL -> chuỗi cho ``<input datetime-local>``."""
    dt = to_local(value)
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


# ---------------------------------------------------------------- kết nối
def connect(db_path: str | Path) -> sqlite3.Connection:
    """Mở kết nối đã cấu hình sẵn.

    ``check_same_thread=False`` là cần thiết vì tiến trình web có thể dùng kết
    nối từ luồng khác; SQLite ở chế độ WAL chịu được một người ghi và nhiều
    người đọc cùng lúc.
    """
    conn = sqlite3.connect(str(db_path), timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # Chờ thay vì báo lỗi ngay khi có tranh chấp ghi — worker và web cùng ghi.
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(db_path: str | Path) -> None:
    """Tạo thư mục và áp lược đồ. Gọi được nhiều lần."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


# Các cột thêm sau khi CSDL đã chạy thật, dạng (bảng, cột, khai báo).
#
# Vì sao cần bảng này: ``schema.sql`` dùng ``CREATE TABLE IF NOT EXISTS``, mà
# câu lệnh đó **không thêm cột vào bảng đã tồn tại**. Trên máy đã có dữ liệu
# thật, sửa `CREATE TABLE` trong `schema.sql` chỉ có tác dụng với CSDL mới —
# máy đang chạy sẽ thiếu cột và mọi truy vấn `SELECT *` trả về hàng thiếu khoá,
# lỗi hiện ra ở tận tầng template chứ không ở chỗ khai báo.
#
# Thêm cột bằng ALTER TABLE là thao tác rẻ và không mất dữ liệu. Chỉ áp dụng
# cho cột **có giá trị mặc định** — cột NOT NULL không mặc định sẽ bị SQLite từ
# chối khi bảng đã có dòng.
_ADDED_COLUMNS = (
    ("users", "avatar_file", "TEXT NOT NULL DEFAULT ''"),
    ("users", "bio", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Thêm những cột còn thiếu. Chạy lại nhiều lần được."""
    for table, column, decl in _ADDED_COLUMNS:
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if not existing:
            # Bảng chưa tồn tại thì `schema.sql` đã tạo đủ cột rồi.
            continue
        if column not in existing:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))


# ------------------------------------------------------- truy vấn tiện dụng
def get_db() -> sqlite3.Connection:
    """Kết nối CSDL của request hiện tại, mở một lần rồi dùng lại.

    ``flask`` được nhập bên trong hàm chứ không ở đầu tệp: ``worker.py`` dùng
    tệp này mà không cần Flask, và một ``import flask`` ở cấp mô-đun sẽ bắt
    tiến trình chấm phải cài Flask mới chạy được.
    """
    from flask import current_app, g

    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exception=None) -> None:
    """Đóng kết nối cuối mỗi request. Đăng ký qua ``app.teardown_appcontext``."""
    from flask import g

    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def query_one(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def scalar(conn: sqlite3.Connection, sql: str, params=(), default=0):
    """Lấy một giá trị đơn. Trả ``default`` khi không có dòng nào.

    Dùng cho các ô số liệu trên trang chủ: ``SELECT COUNT(*)`` luôn trả về một
    dòng nên không cần nhánh này, nhưng ``SELECT SUM(...)`` trên bảng rỗng trả
    về ``NULL``, và ``None`` sẽ in ra thành chữ "None" trên giao diện.
    """
    row = conn.execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]
