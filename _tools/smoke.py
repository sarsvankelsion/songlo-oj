"""Kiểm tra khói: đi qua mọi tuyến đường và báo lỗi render.

Mục đích không phải kiểm thử logic — mà là bắt lỗi template. Một template Jinja
gọi một biến mà tuyến đường không truyền vào sẽ chỉ lộ ra khi có người mở đúng
trang đó, và nếu không có bước này thì người phát hiện là học sinh.

Chạy:

    python _tools/smoke.py                    # dùng CSDL đã seed
    python _tools/smoke.py --database <path>

**Tệp này cần CSDL của bộ dữ liệu mẫu, không chạy được trên CSDL thật của
trường.** Nó dùng tên đăng nhập (`cophang`, `9A01`) và số hiệu bài nộp của bộ
mẫu. CSDL thật có học sinh mang tên khác, nên đăng nhập sẽ thất bại và tệp này
báo lỗi — nhưng lỗi đó là **chạy sai CSDL**, không phải tuyến đường hỏng. Từ nay
nó nói rõ điều đó thay vì chỉ in "đăng nhập thất bại".

**Phần học sinh chạy trên một bản sao CSDL, không phải CSDL gốc.** `seed.py` đặt
``must_change_password = 1`` cho mọi học sinh, và guard ở tầng ứng dụng chuyển
hướng mọi trang về `/account` cho tới khi em đó đổi mật khẩu. Muốn mở được các
trang của học sinh thì phải hạ cờ đó xuống — mà hạ trên CSDL thật là sửa dữ liệu
của trường. Vì vậy tệp này sao CSDL sang thư mục tạm, hạ cờ ở bản sao, rồi mới
đăng nhập. Trước đây không có bước sao chép đó nên phần học sinh báo **11 lỗi
giả** và che mất toàn bộ một nhánh giao diện.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import db  # noqa: E402
from server.app import create_app  # noqa: E402

CSRF_RE = re.compile(r'name="_csrf"\s+value="([^"]+)"')

TEACHER_LOGIN = ("cophang", "Songlo@GV2026")
STUDENT_LOGIN = ("9A01", "Songlo@2026")

# (đường dẫn, ghi chú)
PUBLIC_ROUTES = [
    ("/", "trang chủ"),
    ("/problems", "danh sách đề"),
    ("/problems?difficulty=co-ban", "lọc theo độ khó"),
    ("/problems?q=nguyên", "tìm kiếm"),
    ("/problems?sort=code&dir=asc", "sắp xếp"),
    ("/problems/SL001", "chi tiết đề"),
    ("/problems/SL001?tab=submit", "tab nộp bài"),
    ("/problems/SL001?tab=result", "tab kết quả"),
    ("/leaderboard", "bảng xếp hạng"),
    ("/leaderboard?scope=9A", "bảng xếp hạng theo lớp"),
    ("/contests", "kỳ thi"),
    ("/contests?tab=closed", "kỳ thi đã đóng"),
    ("/login", "đăng nhập"),
]

# Những tuyến đường bắt buộc đăng nhập. Kiểm tra cả mã trả về **và** đích đến:
# một chuyển hướng về nhầm chỗ vẫn là 302, nên chỉ kiểm tra mã thì không đủ.
ANONYMOUS_REDIRECTS = [
    "/submissions",
    "/submissions?scope=all",
    "/submissions/1",
    "/teacher",
    "/teacher/problems",
]

TEACHER_ROUTES = [
    ("/teacher", "tổng quan giáo viên"),
    ("/teacher/problems", "soạn đề"),
    ("/teacher/problems/SL001/edit", "sửa đề"),
    ("/teacher/problems/SL001/tests", "bộ dữ liệu"),
    ("/teacher/classes", "lớp học"),
    ("/teacher/classes?class=9B", "lớp học, chọn lớp khác"),
    ("/submissions", "bài nộp toàn trường"),
    # Giáo viên xem được bài nộp của mọi học sinh, nên đây là chỗ duy nhất kiểm
    # tra được các nhánh giao diện riêng của từng loại kết quả.
    ("/submissions/2", "chi tiết bài nộp WA"),
    ("/submissions/3", "chi tiết bài nộp MLE"),
    ("/submissions/4", "chi tiết bài nộp CE"),
    ("/submissions/7", "chi tiết bài nộp RE"),
    ("/submissions/13", "chi tiết bài nộp TLE"),
]

# Học sinh chỉ thấy bài của mình. Đây vừa là danh sách trang cần kiểm tra, vừa
# là danh sách các bài nộp **không** được phép xem — nên phải kiểm tra cả hai
# chiều: mở được bài của mình, và không mở được bài của người khác.
STUDENT_ROUTES = [
    ("/", "trang chủ"),
    ("/submissions", "bài nộp của em"),
    ("/submissions?verdict=WA", "lọc theo kết quả"),
    ("/submissions?scope=all", "scope=all bị ép về mine, vẫn 200"),
    ("/submissions/1", "chi tiết bài nộp của chính mình (9A01)"),
    ("/problems/SL006?tab=submit", "nộp bài"),
]

# Bài nộp của học sinh khác: học sinh mở vào phải nhận 404, giáo viên mở vào
# phải nhận 200. Dùng chung một danh sách cho cả hai chiều để không bỏ sót.
OTHERS_SUBMISSIONS = [2, 3, 4, 7, 13]

# Kiểm tra khi **đã** đăng nhập, vì với khách thì các tuyến này chuyển hướng
# trước khi kịp tra CSDL.
NOT_FOUND_ROUTES = [
    ("/khong-ton-tai", 404),
    ("/problems/KHONGCO", 404),
    ("/submissions/99999", 404),
    ("/teacher/problems/KHONGCO/edit", 404),
    ("/teacher/problems/KHONGCO/tests", 404),
]


def csrf_from(html: str) -> str:
    m = CSRF_RE.search(html)
    if not m:
        raise SystemExit("Không tìm thấy trường _csrf trong trang đăng nhập.")
    return m.group(1)


def login(client, username: str, password: str) -> bool:
    page = client.get("/login")
    token = csrf_from(page.get_data(as_text=True))
    resp = client.post(
        "/login",
        data={"username": username, "password": password, "_csrf": token},
        follow_redirects=False,
    )
    return resp.status_code in (301, 302, 303)


def login_failed(who: str, username: str, database: str) -> None:
    """Noi ro vi sao dang nhap that bai, thay vi chi bao "that bai".

    Tep nay dung ten dang nhap cua **bo du lieu mau**. Tren CSDL that cua truong,
    nhung ten do khong con (hoc sinh that co ten khac), va neu chi in ra "dang
    nhap that bai" thi nguoi doc se tuong tuyen duong hong — trong khi van de la
    dang chay sai CSDL. Da mat mot vong vi dung nhu vay.
    """
    print(f"  LỖI: đăng nhập {who} thất bại với tài khoản «{username}».")
    print(f"       CSDL đang dùng: {database}")
    print("       Tệp này dùng tài khoản của **bộ dữ liệu mẫu** "
          f"({TEACHER_LOGIN[0]}, {STUDENT_LOGIN[0]}). Nếu đang trỏ vào CSDL thật")
    print("       của trường thì các tài khoản đó không tồn tại — chạy "
          "`python -m server.seed` trước,")
    print("       hoặc trỏ `--database` vào CSDL mẫu. Đây không phải lỗi tuyến đường.")


def check(client, routes, failures, label):
    for path, note in routes:
        resp = client.get(path)
        body = resp.get_data(as_text=True)
        ok = resp.status_code == 200
        # Trang lỗi của Flask vẫn trả 200 nếu template nuốt lỗi, nên kiểm tra
        # thêm dấu hiệu lỗi còn sót trong HTML.
        leak = "jinja2" in body.lower() or "Traceback" in body
        mark = "ok " if ok and not leak else "LỖI"
        if not ok or leak:
            failures.append((label, path, resp.status_code, note))
        print(f"  {mark} {resp.status_code}  {path:<40} {note}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "server" / "var" / "songlo.db"))
    args = parser.parse_args(argv)

    app = create_app({"DATABASE": args.database, "TESTING": False})
    failures: list = []

    print("Khách chưa đăng nhập:")
    client = app.test_client()
    check(client, PUBLIC_ROUTES, failures, "khách")

    print("\nKhách truy cập trang bắt buộc đăng nhập (phải chuyển hướng về /login):")
    for path in ANONYMOUS_REDIRECTS:
        resp = client.get(path)
        location = resp.headers.get("Location", "")
        ok = resp.status_code == 302 and "/login" in location
        print(f"  {'ok ' if ok else 'LỖI'} {resp.status_code}  {path:<40} -> {location}")
        if not ok:
            failures.append(("khách", path, resp.status_code, f"chuyển hướng tới {location!r}"))

    print("\nGiáo viên (cophang):")
    teacher_client = app.test_client()
    if not login(teacher_client, *TEACHER_LOGIN):
        login_failed("giáo viên", TEACHER_LOGIN[0], args.database)
        failures.append(("giáo viên", "/login", 0, "đăng nhập thất bại"))
    else:
        check(teacher_client, TEACHER_ROUTES, failures, "giáo viên")
        print("  -- trang lỗi, khi đã đăng nhập --")
        for path, expected in NOT_FOUND_ROUTES:
            resp = teacher_client.get(path)
            ok = resp.status_code == expected
            print(f"  {'ok ' if ok else 'LỖI'} {resp.status_code}  {path:<40} (mong đợi {expected})")
            if not ok:
                failures.append(("404", path, resp.status_code, f"mong đợi {expected}"))

    # -- Học sinh, phần 1: chưa đổi mật khẩu lần đầu ----------------------
    # Đây là hành vi thật của một tài khoản mới, và nó phải được kiểm chứ không
    # phải bị coi là lỗi: mọi trang đều chuyển hướng về `/account`, còn `/account`
    # thì mở được — nếu không thì người dùng kẹt vòng lặp chuyển hướng.
    print("\nHọc sinh (9A01) — chưa đổi mật khẩu lần đầu (guard phải chặn):")
    student_client = app.test_client()
    if not login(student_client, *STUDENT_LOGIN):
        login_failed("học sinh", STUDENT_LOGIN[0], args.database)
        failures.append(("học sinh", "/login", 0, "đăng nhập thất bại"))
    else:
        for path, note in STUDENT_ROUTES:
            resp = student_client.get(path)
            location = resp.headers.get("Location", "")
            ok = resp.status_code == 302 and "/account" in location
            print(f"  {'ok ' if ok else 'LỖI'} {resp.status_code}  {path:<40} -> {location}")
            if not ok:
                failures.append(("guard", path, resp.status_code,
                                 f"mong đợi 302 tới /account, nhận {location!r}"))
        resp = student_client.get("/account")
        ok = resp.status_code == 200
        print(f"  {'ok ' if ok else 'LỖI'} {resp.status_code}  {'/account':<40} "
              f"trang đổi mật khẩu phải mở được")
        if not ok:
            failures.append(("guard", "/account", resp.status_code,
                             "trang đổi mật khẩu không mở được"))

    # -- Học sinh, phần 2: đã đổi mật khẩu, chạy trên bản sao CSDL --------
    # Sao chép bằng `Connection.backup` chứ không `copy2`: CSDL chạy ở chế độ
    # WAL, và chép mỗi tệp chính sẽ bỏ mất phần dữ liệu còn nằm trong `-wal`.
    print("\nHọc sinh (9A01) — đã đổi mật khẩu (trên bản sao CSDL):")
    tmpdir = tempfile.mkdtemp(prefix="smoke-")
    try:
        tmp_db = os.path.join(tmpdir, "songlo.db")
        src = db.connect(args.database)
        dst = sqlite3.connect(tmp_db)
        src.backup(dst)
        dst.close()
        src.close()
        clone = db.connect(tmp_db)
        with clone:
            clone.execute("UPDATE users SET must_change_password = 0 WHERE role = 'student'")
        clone.close()

        app2 = create_app({"DATABASE": tmp_db, "TESTING": False})
        student_client = app2.test_client()
        if not login(student_client, *STUDENT_LOGIN):
            login_failed("học sinh", STUDENT_LOGIN[0], tmp_db)
            failures.append(("học sinh", "/login", 0, "đăng nhập trên bản sao thất bại"))
        else:
            check(student_client, STUDENT_ROUTES, failures, "học sinh")

            print("  -- bài nộp của học sinh khác: phải bị chặn bằng 404 --")
            for sid in OTHERS_SUBMISSIONS:
                resp = student_client.get(f"/submissions/{sid}")
                ok = resp.status_code == 404
                print(f"  {'ok ' if ok else 'LỖI'} {resp.status_code}  /submissions/{sid}"
                      f"{'':<25} (mong đợi 404)")
                if not ok:
                    failures.append(
                        ("học sinh", f"/submissions/{sid}", resp.status_code,
                         "xem được bài của học sinh khác"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if failures:
        print(f"THẤT BẠI: {len(failures)} tuyến đường")
        for label, path, code, note in failures:
            print(f"  [{label}] {path} -> {code} ({note})")
        return 1
    print("Tất cả tuyến đường đều đạt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
