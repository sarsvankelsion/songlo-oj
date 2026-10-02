"""Kiểm thử chức năng sửa đề (`/teacher/problems/<code>/edit`).

Vì sao cần một script riêng thay vì thêm vào `smoke.py`: `smoke.py` chỉ đọc, còn
ở đây phải **ghi** — tạo đề, sửa đề, công khai đề. Nếu chạy thẳng trên CSDL thật
thì mỗi lần kiểm thử lại để lại rác, và tệ hơn là có thể sửa nhầm một đề đang
dùng. Nên script này **sao chép CSDL ra tệp tạm** rồi làm việc trên bản sao.

Nó kiểm tra những điều mà việc đọc mã không chứng minh được:

  1. trang sửa đề hiện đúng giá trị đang có trong CSDL;
  2. sửa rồi lưu thì giá trị trong CSDL đổi thật;
  3. lưu thất bại thì **không** đổi gì, và biểu mẫu giữ nguyên những gì đã gõ;
  4. không công khai được một đề chưa có bộ dữ liệu;
  5. công khai được một đề đã có bộ dữ liệu, và sau đó học sinh thấy nó;
  6. giá trị lạ trong ô chọn bị thay bằng mặc định, không lọt vào CSDL;
  7. mã đề không đổi được dù biểu mẫu có gửi lên mã khác.

    python _tools/test_edit_problem.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import db  # noqa: E402
from server.app import create_app  # noqa: E402

CSRF_RE = re.compile(r'name="_csrf"\s+value="([^"]+)"')
TEACHER = ("cophang", "Songlo@GV2026")
STUDENT = ("9A01", "Songlo@2026")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'LỖI '} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def login(client, who) -> None:
    username, password = who
    page = client.get("/login").get_data(as_text=True)
    m = CSRF_RE.search(page)
    if not m:
        raise SystemExit("Không tìm thấy _csrf trong trang đăng nhập.")
    client.post("/login", data={"username": username, "password": password, "_csrf": m.group(1)})


def token(client, path: str) -> str:
    page = client.get(path).get_data(as_text=True)
    m = CSRF_RE.search(page)
    if not m:
        raise SystemExit(f"Không tìm thấy _csrf ở {path}.")
    return m.group(1)


def row(conn, code):
    return db.query_one(conn, "SELECT * FROM problems WHERE code = ?", (code,))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", default=str(ROOT / "server" / "var" / "songlo.db"))
    args = ap.parse_args(argv)

    source = Path(args.database)
    if not source.is_file():
        sys.exit(f"Không thấy CSDL {source}. Chạy `python -m server.seed` trước.")

    # Bản sao dùng chung một thư mục tạm với tệp CSDL, để SQLite tạo được các tệp
    # phụ (-wal, -shm) bên cạnh mà không đụng vào thư mục thật.
    tmpdir = Path(tempfile.mkdtemp(prefix="songlo-edit-test-"))
    try:
        tmpdb = tmpdir / "test.db"
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(source) + suffix)
            if src.is_file():
                shutil.copy2(src, str(tmpdb) + suffix)

        app = create_app({"DATABASE": str(tmpdb), "TESTING": True})
        conn = db.connect(str(tmpdb))

        # Hạ cờ đổi-mật-khẩu trên **bản sao**. `seed.py` đặt cờ đó cho mọi học
        # sinh, và guard ở tầng ứng dụng chuyển hướng mọi trang về `/account`
        # cho tới khi đổi mật khẩu — nên tài khoản học sinh ở đây không mở được
        # trang nào, và hai phép kiểm "học sinh thấy đề" / "học sinh mở được đề"
        # báo lỗi trong khi hệ thống vẫn đúng. Chỉ hạ trên bản sao nên dữ liệu
        # thật không bị chạm.
        with conn:
            conn.execute("UPDATE users SET must_change_password = 0 WHERE role = 'student'")

        teacher = app.test_client()
        login(teacher, TEACHER)
        student = app.test_client()
        login(student, STUDENT)

        # ---------------------------------------------------------------- 1
        print("\n1. Trang sửa đề hiện đúng giá trị đang có")
        before = row(conn, "SL001")
        page = teacher.get("/teacher/problems/SL001/edit").get_data(as_text=True)
        check("mở được trang sửa đề", "Sửa đề —" in page)
        check("hiện đúng tên bài", before["name"] in page, before["name"])
        check("hiện đúng giới hạn thời gian",
              f'value="{before["time_limit_ms"] / 1000:g}"' in page)
        check("hiện đúng giới hạn bộ nhớ",
              f'value="{before["memory_limit_mb"]}"' in page)
        check("đề bài hiện trong textarea", "Cho hai số nguyên a và b" in page)
        check("mã đề khoá, không sửa được",
              re.search(r'id="p-code"[^>]*disabled', page) is not None)
        check("trạng thái hiện tại được chọn",
              re.search(r'value="live"[^>]*selected', page) is not None)

        # ---------------------------------------------------------------- 2
        print("\n2. Sửa rồi lưu thì CSDL đổi thật")
        t = token(teacher, "/teacher/problems/SL001/edit")
        resp = teacher.post("/teacher/problems/SL001/edit", data={
            "_csrf": t,
            "name": "Tổng hai số nguyên (đã sửa)",
            "difficulty": "trung-binh",
            "topic": "Số học",
            "points_mode": "even",
            "time_limit_s": "2",
            "memory_limit_mb": "512",
            "statement": "YÊU CẦU\nCho hai số nguyên a và b. In ra tổng.\n",
            "status": "live",
        }, follow_redirects=False)
        after = row(conn, "SL001")
        check("chuyển hướng về danh sách đề sau khi lưu", resp.status_code == 302,
              f"mã {resp.status_code}")
        check("tên bài đã đổi", after["name"] == "Tổng hai số nguyên (đã sửa)", after["name"])
        check("độ khó đã đổi", after["difficulty"] == "trung-binh", after["difficulty"])
        check("thời gian đã đổi thành 2000 ms", after["time_limit_ms"] == 2000,
              str(after["time_limit_ms"]))
        check("bộ nhớ đã đổi thành 512 MB", after["memory_limit_mb"] == 512,
              str(after["memory_limit_mb"]))
        check("đề bài đã đổi", "In ra tổng" in after["statement"])
        check("updated_at đã được ghi lại", after["updated_at"] >= after["created_at"])

        # ---------------------------------------------------------------- 3
        print("\n3. Lưu thất bại thì không đổi gì, và giữ nguyên chữ đã gõ")
        snapshot = dict(row(conn, "SL001"))
        t = token(teacher, "/teacher/problems/SL001/edit")
        resp = teacher.post("/teacher/problems/SL001/edit", data={
            "_csrf": t,
            "name": "",                       # thiếu tên bài → phải bị chặn
            "statement": "Nội dung mới giáo viên vừa gõ, rất dài, không được mất.",
            "difficulty": "nang-cao",
            "time_limit_s": "3",
            "memory_limit_mb": "256",
            "status": "live",
        })
        body = resp.get_data(as_text=True)
        now = dict(row(conn, "SL001"))
        check("không ghi gì vào CSDL khi lưu lỗi", now == snapshot)
        check("báo lỗi cho giáo viên", "Tên bài không được để trống" in body)
        check("giữ lại đề bài vừa gõ",
              "Nội dung mới giáo viên vừa gõ, rất dài, không được mất." in body)
        check("giữ lại độ khó vừa chọn",
              re.search(r'value="nang-cao"[^>]*selected', body) is not None)

        # ---------------------------------------------------------------- 4
        print("\n4. Không công khai được đề chưa có bộ dữ liệu")
        t = token(teacher, "/teacher/problems")
        teacher.post("/teacher/problems", data={
            "_csrf": t,
            "code": "SLTEST",
            "name": "Đề thử chưa có dữ liệu",
            "difficulty": "co-ban",
            "topic": "Thử",
            "points_mode": "even",
            "time_limit_s": "1",
            "memory_limit_mb": "256",
            "statement": "Đề này cố ý không có bộ dữ liệu nào.",
        })
        created = row(conn, "SLTEST")
        check("tạo được đề mới", created is not None)
        check("đề mới ở dạng bản nháp", created["status"] == "draft", created["status"])

        t = token(teacher, "/teacher/problems/SLTEST/edit")
        resp = teacher.post("/teacher/problems/SLTEST/edit", data={
            "_csrf": t,
            "name": created["name"],
            "statement": created["statement"],
            "difficulty": "co-ban",
            "time_limit_s": "1",
            "memory_limit_mb": "256",
            "status": "live",
        })
        body = resp.get_data(as_text=True)
        check("bị chặn khi công khai mà chưa có bộ dữ liệu",
              row(conn, "SLTEST")["status"] == "draft")
        check("nói rõ lý do", "chưa có bộ dữ liệu" in body)
        check("cảnh báo hiện sẵn trên trang", "Đề này chưa có bộ dữ liệu nào"
              in teacher.get("/teacher/problems/SLTEST/edit").get_data(as_text=True))

        # ---------------------------------------------------------------- 5
        print("\n5. Công khai được sau khi đã có bộ dữ liệu, và học sinh thấy")
        t = token(teacher, "/teacher/problems/SLTEST/tests")
        teacher.post("/teacher/problems/SLTEST/tests", data={
            "_csrf": t, "action": "add",
            "input": "1 2\n", "output": "3\n", "is_hidden": "on",
        })
        t = token(teacher, "/teacher/problems/SLTEST/edit")
        teacher.post("/teacher/problems/SLTEST/edit", data={
            "_csrf": t,
            "name": created["name"],
            "statement": created["statement"],
            "difficulty": "co-ban",
            "time_limit_s": "1",
            "memory_limit_mb": "256",
            "status": "live",
        })
        check("công khai được sau khi thêm bộ dữ liệu",
              row(conn, "SLTEST")["status"] == "live", row(conn, "SLTEST")["status"])
        check("học sinh thấy đề trong danh sách",
              "SLTEST" in student.get("/problems").get_data(as_text=True))
        check("học sinh mở được đề",
              student.get("/problems/SLTEST").status_code == 200)

        # ---------------------------------------------------------------- 6
        print("\n6. Giá trị lạ trong ô chọn không lọt vào CSDL")
        t = token(teacher, "/teacher/problems/SL001/edit")
        teacher.post("/teacher/problems/SL001/edit", data={
            "_csrf": t,
            "name": after["name"],
            "statement": after["statement"],
            "difficulty": "khong-ton-tai",
            "points_mode": "cung-khong",
            "status": "bịa-đặt",
            "time_limit_s": "abc",            # không phải số
            "memory_limit_mb": "-999",        # ngoài khoảng cho phép
        })
        odd = row(conn, "SL001")
        check("độ khó lạ → về mặc định",
              odd["difficulty"] == "co-ban", odd["difficulty"])
        check("thang điểm lạ → về mặc định",
              odd["points_mode"] == "even", odd["points_mode"])
        check("trạng thái lạ → giữ nguyên trạng thái cũ",
              odd["status"] == after["status"], odd["status"])
        check("thời gian không phải số → về mặc định 1000 ms",
              odd["time_limit_ms"] == 1000, str(odd["time_limit_ms"]))
        check("bộ nhớ âm → kẹp về tối thiểu 16 MB",
              odd["memory_limit_mb"] == 16, str(odd["memory_limit_mb"]))

        # ---------------------------------------------------------------- 7
        print("\n7. Mã đề không đổi được")
        t = token(teacher, "/teacher/problems/SL001/edit")
        teacher.post("/teacher/problems/SL001/edit", data={
            "_csrf": t,
            "code": "SL999",                  # cố tình gửi mã khác
            "name": odd["name"],
            "statement": odd["statement"],
            "difficulty": "co-ban",
            "time_limit_s": "1",
            "memory_limit_mb": "256",
            "status": "live",
        })
        check("mã đề giữ nguyên SL001", row(conn, "SL001") is not None)
        check("không sinh ra đề SL999", row(conn, "SL999") is None)

        # ---------------------------------------------------------------- 8
        print("\n8. Học sinh không vào được trang sửa đề")
        resp = student.get("/teacher/problems/SL001/edit", follow_redirects=False)
        check("học sinh bị chặn", resp.status_code in (302, 403, 404),
              f"mã {resp.status_code}")

        print()
        if failures:
            print(f"{len(failures)} phép kiểm tra KHÔNG đạt:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("Tất cả phép kiểm tra đều đạt.")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
