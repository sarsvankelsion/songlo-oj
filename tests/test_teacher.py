#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kiểm thử quyền giáo viên và việc nhập bộ dữ liệu từ tệp ZIP.

Chạy từ thư mục gốc dự án:

    python tests/test_teacher.py

Dùng CSDL tạm và tự xoá sau khi chạy — không chạm vào dữ liệu thật.

Vì sao cần bộ kiểm thử này, chứ không kiểm bằng mắt: phần lớn các tuyến đường ở
đây là **xoá** và **thay đổi quyền**. Kiểm bằng mắt chỉ thấy được đường đi đúng;
cái đáng kiểm là những đường đi sai — học sinh gọi được tuyến đường của giáo
viên, giáo viên tự khoá được tài khoản mình đang dùng, xoá một đề mà không biết
nó kéo theo bao nhiêu bài của học sinh.

Riêng phần ZIP: đây là chỗ dữ liệu vào do người dùng đưa và có thể chứa bất cứ
thứ gì. Một tệp không phải ZIP, một tệp ZIP rỗng, hay một tệp ZIP chỉ có `.cpp`
mà không có dữ liệu — cả ba đều phải trả về thông báo đọc được, không phải một
trang lỗi 500.
"""
import io
import os
import re
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import auth, db, themis                    # noqa: E402
from server.app import create_app                      # noqa: E402

OK = []
BAD = []


def check(label, cond, extra=""):
    (OK if cond else BAD).append(label)
    print("  %s %s%s" % ("ok  " if cond else "SAI ", label,
                         ("  <- " + str(extra)) if extra and not cond else ""))


def make_zip(files):
    """``files`` là dict tên -> nội dung (str hoặc bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            z.writestr(name, content)
    return buf.getvalue()


# ===========================================================================
# Phần 1 — themis.parse_zip, kiểm thẳng không qua mạng
# ===========================================================================
print("\n=== 1. themis.parse_zip ===")

# --- 1a. Cách đặt tên Themis: mỗi bộ một thư mục TESTxx ---
tests, report = themis.parse_zip(make_zip({
    "TEST01/SL001.INP": "5\n1 2 3 4 5\n",
    "TEST01/SL001.OUT": "15\n",
    "TEST02/SL001.INP": "3\n7 7 7\n",
    "TEST02/SL001.OUT": "21\n",
}))
check("ghep duoc 2 bo theo thu muc TESTxx", len(tests) == 2, report)
check("bo 1 dung noi dung vao", tests[0]["input"] == "5\n1 2 3 4 5\n" if tests else False)
check("bo 1 dung noi dung ra", tests[0]["output"] == "15\n" if tests else False)
check("ten bo giu ca thu muc", tests[0]["name"] == "TEST01/SL001" if tests else False)
check("bao cao khong co tep le", report["orphan_in"] == 0 and report["orphan_out"] == 0)

# --- 1b. Cách để phẳng ---
tests, report = themis.parse_zip(make_zip({
    "SL001.INP": "1\n", "SL001.OUT": "2\n",
    "SL002.INP": "3\n", "SL002.OUT": "4\n",
}))
check("ghep duoc 2 bo de phang", len(tests) == 2, report)
check("bo phang xep theo ten", [t["name"] for t in tests] == ["SL001", "SL002"], tests)

# --- 1c. Chữ hoa chữ thường và các đuôi khác ---
tests, report = themis.parse_zip(make_zip({
    "bai1.inp": "a\n", "bai1.out": "b\n",
    "bai2.in": "c\n", "bai2.ans": "d\n",
    "bai3.INP": "e\n", "bai3.OUT": "f\n",
}))
check("nhan .inp/.out/.in/.ans va khong phan biet hoa thuong", len(tests) == 3, report)

# --- 1d. `.inp.txt` phai la duoi 'in', khong bi cat thanh 'txt' ---
tests, report = themis.parse_zip(make_zip({
    "SL001.inp.txt": "1\n", "SL001.out.txt": "2\n",
}))
check("nhan .inp.txt / .out.txt", len(tests) == 1, report)
check("ten goi y bo dung phan duoi", tests[0]["name"] == "SL001" if tests else False, tests)

# --- 1e. Thu tu phai theo so, khong theo chuoi ---
tests, report = themis.parse_zip(make_zip({
    "TEST2/SL.INP": "2\n", "TEST2/SL.OUT": "2\n",
    "TEST10/SL.INP": "10\n", "TEST10/SL.OUT": "10\n",
    "TEST9/SL.INP": "9\n", "TEST9/SL.OUT": "9\n",
}))
order = [t["name"] for t in tests]
check("TEST2 < TEST9 < TEST10 (thu tu so)", order == ["TEST2/SL", "TEST9/SL", "TEST10/SL"],
      order)

# --- 1f. Tep le: vao khong co ra, ra khong co vao ---
tests, report = themis.parse_zip(make_zip({
    "A.INP": "1\n", "A.OUT": "1\n",
    "B.INP": "2\n",
    "C.OUT": "3\n",
}))
check("chi ghep cap du ca hai", len(tests) == 1, report)
check("dem duoc tep vao le", report["orphan_in"] == 1, report)
check("dem duoc tep ra le", report["orphan_out"] == 1, report)

# --- 1g. Tep rac cua he dieu hanh ---
tests, report = themis.parse_zip(make_zip({
    "__MACOSX/TEST01/._SL.INP": "rac\n",
    "Thumbs.db": "rac\n",
    ".DS_Store": "rac\n",
    "TEST01/SL.INP": "1\n",
    "TEST01/SL.OUT": "2\n",
}))
check("bo qua tep rac, khong tinh la tep le", len(tests) == 1 and
      report["orphan_in"] == 0 and report["orphan_out"] == 0, report)

# --- 1h. Tep .cpp / loi giai trong ZIP: bo qua, khong gay loi ---
tests, report = themis.parse_zip(make_zip({
    "TEST01/SL.INP": "1\n", "TEST01/SL.OUT": "2\n",
    "SL.cpp": "#include <iostream>\n",
    "SL001.cpp": "int main(){}\n",
    "README.txt": "De thi khoi 9\n",
}))
check("bo qua .cpp va .txt, van ghep duoc bo", len(tests) == 1, report)
check("bao cao co dem tep khong nhan dang", report["skipped"] == 3, report)

# --- 1i. Khong phai ZIP ---
tests, report = themis.parse_zip(b"day khong phai la mot tep zip")
check("tep khong phai ZIP: khong bo du lieu", tests == [])
check("tep khong phai ZIP: co thong bao loi", bool(report.get("error")), report)

# --- 1j. ZIP rong / khong co cap nao ---
tests, report = themis.parse_zip(make_zip({"SL.cpp": "int main(){}\n"}))
check("zip khong co du lieu: khong bo nao", tests == [])
check("zip khong co du lieu: co thong bao", bool(report.get("error")), report)

# --- 1k. Bang ma CP1258 (tieng Viet tren Windows) ---
# Doc bang UTF-8 se ra chuoi rac ma KHONG bao loi — day la ly do phai thu lan luot.
viet = "Sông Lô\n".encode("cp1258")
tests, report = themis.parse_zip(make_zip({"SL.INP": viet, "SL.OUT": b"1\n"}))
check("doc duoc tep CP1258", tests and tests[0]["input"] == "Sông Lô\n",
      tests[0]["input"] if tests else report)

# --- 1l. Trung ten goc khac thu muc la hai bo khac nhau ---
tests, report = themis.parse_zip(make_zip({
    "TEST01/SL.INP": "1\n", "TEST01/SL.OUT": "1\n",
    "TEST02/SL.INP": "2\n", "TEST02/SL.OUT": "2\n",
}))
check("cung ten goc khac thu muc = 2 bo", len(tests) == 2, report)

# --- 1m. CRLF phai ve LF, neu khong so khop se sai ---
tests, report = themis.parse_zip(make_zip({"SL.INP": b"1\r\n2\r\n", "SL.OUT": b"3\r\n"}))
check("CRLF duoc doi thanh LF", tests and tests[0]["input"] == "1\n2\n",
      repr(tests[0]["input"]) if tests else report)

# ===========================================================================
# Phần 2 — các tuyến đường giáo viên, qua ứng dụng thật
# ===========================================================================
TMP = tempfile.mkdtemp(prefix="songlo-teacher-test-")
DB = os.path.join(TMP, "songlo.db")
print("\nCSDL tam:", DB)

app = create_app({"TESTING": True, "DATABASE": DB, "SECRET_KEY": "test",
                  # Cô lập luôn thư mục chấm. Mặc định nó là `server/var/judge`,
                  # tức là bài kiểm thử sẽ ghi vào cây mã nguồn — và mục §21 dịch
                  # và chạy chương trình thật, nên nó tạo ra tệp thật.
                  "JUDGE_WORKSPACE": os.path.join(TMP, "judge")})
app.config["MAX_CONTENT_LENGTH"] = 96 * 1024 * 1024   # cho phép ZIP lớn trong bài kiểm

conn = db.connect(DB)
with conn:
    conn.execute(
        """INSERT INTO users (username, full_name, class_name, role, password_hash,
                              is_active, must_change_password, created_at)
           VALUES (?,?,?,?,?,1,0,?)""",
        ("thumai", "Trần Thị Thu Mai", "", "teacher",
         auth.hash_password("giaovien1"), db.utc_now()),
    )
    conn.execute(
        """INSERT INTO users (username, full_name, class_name, role, password_hash,
                              is_active, must_change_password, created_at)
           VALUES (?,?,?,?,?,1,0,?)""",
        ("an.nguyen9a", "Nguyễn Văn An", "9A", "student",
         auth.hash_password("hocsinh1"), db.utc_now()),
    )
    conn.execute(
        """INSERT INTO problems (code, name, statement, difficulty, topic, time_limit_ms,
                                 memory_limit_mb, points_mode, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("SL001", "Đếm số nguyên tố", "Đếm số nguyên tố nhỏ hơn n.", "co-ban", "Số học",
         1000, 256, "even", "live", db.utc_now(), db.utc_now()),
    )
    conn.execute(
        """INSERT INTO problems (code, name, statement, difficulty, topic, time_limit_ms,
                                 memory_limit_mb, points_mode, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("SL002", "Tính tổng", "Tính tổng dãy số.", "co-ban", "Số học",
         1000, 256, "even", "draft", db.utc_now(), db.utc_now()),
    )
conn.close()


def login(client, username, password):
    page = client.get("/login")
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', page.data.decode("utf-8", "replace"))
    return client.post("/login", data={"username": username, "password": password,
                                       "_csrf": m.group(1) if m else ""})


def token(client, path):
    """Lấy token CSRF đang dùng trong phiên (mọi trang đều nhúng nó vào biểu mẫu)."""
    page = client.get(path)
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', page.data.decode("utf-8", "replace"))
    return m.group(1) if m else ""


def text(resp):
    return resp.data.decode("utf-8", "replace")


print("\n=== 2. Quyen: hoc sinh khong duoc vao khu giao vien ===")
student = app.test_client()
login(student, "an.nguyen9a", "hocsinh1")
for path in ("/teacher/users", "/teacher/contests", "/teacher/problems", "/teacher/classes"):
    r = student.get(path)
    check("hoc sinh bi chan %s" % path, r.status_code in (302, 403), r.status_code)

teacher = app.test_client()
login(teacher, "thumai", "giaovien1")

print("\n=== 3. Trang quan ly tai khoan va ky thi mo duoc ===")
for path in ("/teacher/users", "/teacher/contests", "/teacher"):
    r = teacher.get(path)
    check("giao vien mo duoc %s" % path, r.status_code == 200, r.status_code)

page = text(teacher.get("/teacher/users"))
check("trang tai khoan co o tim kiem", 'name="q"' in page)
check("trang tai khoan co o vai tro", 'name="role"' in page)
check("trang tai khoan liet ke hoc sinh co that", "an.nguyen9a" in page)
# Mỗi dòng là một biểu mẫu riêng, gửi bằng thuộc tính `form=` của HTML5.
check("trang tai khoan khai bieu mau cho tung dong", 'id="uf-1"' in page or 'id="uf-' in page)
check("nut Luu gan vao bieu mau cua dong", 'form="uf-' in page)

page = text(teacher.get("/teacher/contests"))
check("trang ky thi co bieu mau tao moi", 'action="/teacher/contests/create"' in page)

print("\n=== 4. Cap tai khoan moi ===")
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/create",
                 data={"_csrf": csrf, "username": "binh.le9a", "full_name": "Lê Thanh Bình",
                       "class_name": "9A", "role": "student"},
                 follow_redirects=True)
body = text(r)
check("cap duoc tai khoan", r.status_code == 200 and "Đã tạo tài khoản" in body, body[:200])

m = re.search(r"Mật khẩu tạm:\s*([A-Za-z0-9]+)", body)
temp = m.group(1) if m else None
check("thong bao co mat khau tam", bool(temp), body[:400])
check("mat khau tam du dai", bool(temp) and len(temp) >= 8, temp)

conn = db.connect(DB)
row = db.query_one(conn, "SELECT * FROM users WHERE username = ?", ("binh.le9a",))
check("tai khoan co trong CSDL", row is not None)
check("co dang hieu luc", row and row["is_active"] == 1)
check("bat buoc doi mat khau lan dau", row and row["must_change_password"] == 1)
check("mat khau luu dang bam, khong luu chuoi goc",
      row and row["password_hash"] != temp and len(row["password_hash"]) > 20)
conn.close()

# Đăng nhập thật bằng mật khẩu tạm, và phải bị chặn cho tới khi đổi.
newbie = app.test_client()
login(newbie, "binh.le9a", temp)
r = newbie.get("/problems")
check("dang nhap duoc bang mat khau tam", r.status_code in (200, 302))
check("bi ep sang trang doi mat khau", r.status_code == 302 and "/account" in r.headers.get("Location", ""),
      r.headers.get("Location"))

print("\n=== 5. Trung ten dang nhap thi bao loi, khong tao them ===")
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/create",
                 data={"_csrf": csrf, "username": "an.nguyen9a", "full_name": "Trùng Tên",
                       "class_name": "9A", "role": "student"},
                 follow_redirects=True)
check("bao trung ten dang nhap", "đã có người dùng" in text(r), text(r)[:300])

print("\n=== 6. Hoc sinh phai thuoc mot lop ===")
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/create",
                 data={"_csrf": csrf, "username": "vohocsinh", "full_name": "Vô Lớp",
                       "class_name": "", "role": "student"},
                 follow_redirects=True)
check("thieu lop thi tu choi", "phải thuộc một lớp" in text(r), text(r)[:300])
conn = db.connect(DB)
check("khong tao tai khoan nao", db.query_one(
    conn, "SELECT id FROM users WHERE username = ?", ("vohocsinh",)) is None)
conn.close()

print("\n=== 7. Ten dang nhap co dau cham / gach duoi ===")
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/create",
                 data={"_csrf": csrf, "username": "chi_pham9b", "full_name": "Phạm Thùy Chi",
                       "class_name": "9B", "role": "student"},
                 follow_redirects=True)
check("nhan ten dang nhap co gach duoi", "Đã tạo tài khoản" in text(r), text(r)[:300])

csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/create",
                 data={"_csrf": csrf, "username": "co dau cach", "full_name": "Có Dấu Cách",
                       "class_name": "9A", "role": "student"},
                 follow_redirects=True)
check("tu choi ten dang nhap co dau cach", "chỉ gồm chữ, số" in text(r), text(r)[:300])

print("\n=== 8. Sua tai khoan ===")
conn = db.connect(DB)
row = db.query_one(conn, "SELECT id FROM users WHERE username = ?", ("binh.le9a",))
bid = row["id"]
conn.close()

csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/update" % bid,
                 data={"_csrf": csrf, "full_name": "Lê Thanh Bình (đổi tên)",
                       "class_name": "9C", "role": "student", "is_active": "1"},
                 follow_redirects=True)
conn = db.connect(DB)
row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (bid,))
check("sua duoc ho ten", row["full_name"] == "Lê Thanh Bình (đổi tên)", row["full_name"])
check("sua duoc lop", row["class_name"] == "9C", row["class_name"])
conn.close()

# Bo tich o "Hoat dong" -> tai khoan bi khoa.
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/update" % bid,
                 data={"_csrf": csrf, "full_name": "Lê Thanh Bình (đổi tên)",
                       "class_name": "9C", "role": "student"},
                 follow_redirects=True)
conn = db.connect(DB)
row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (bid,))
check("bo tich Hoat dong = khoa tai khoan", row["is_active"] == 0, row["is_active"])
conn.close()

# Tai khoan bi khoa thi khong vao duoc phan can dang nhap.
# Phai kiem tren `/account` chu khong phai `/problems`: danh sach de bai la trang
# cong khai, nên nó trả 200 cho cả khách vãng lai — một bài kiểm trên trang đó
# sẽ xanh kể cả khi việc khoá tài khoản không có tác dụng gì.
locked = app.test_client()
login(locked, "binh.le9a", temp)
r = locked.get("/account")
check("tai khoan bi khoa khong vao duoc",
      r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      "%s %s" % (r.status_code, r.headers.get("Location")))

print("\n=== 9. Khong tu khoa / tu xoa tai khoan dang dang nhap ===")
conn = db.connect(DB)
me = db.query_one(conn, "SELECT id FROM users WHERE username = ?", ("thumai",))
meid = me["id"]
conn.close()

csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/update" % meid,
                 data={"_csrf": csrf, "full_name": "Trần Thị Thu Mai", "class_name": "",
                       "role": "teacher"},     # khong gui is_active = tu khoa minh
                 follow_redirects=True)
check("chan tu khoa chinh minh", "Không thể tự khoá" in text(r), text(r)[:300])
conn = db.connect(DB)
row = db.query_one(conn, "SELECT is_active FROM users WHERE id = ?", (meid,))
check("tai khoan minh van hoat dong", row["is_active"] == 1)
conn.close()

csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/delete" % meid, data={"_csrf": csrf},
                 follow_redirects=True)
check("chan tu xoa chinh minh", "Không thể xoá tài khoản đang đăng nhập" in text(r), text(r)[:300])
conn = db.connect(DB)
check("tai khoan minh van con", db.query_one(
    conn, "SELECT id FROM users WHERE id = ?", (meid,)) is not None)
conn.close()

print("\n=== 10. Dat lai mat khau ===")
csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/reset" % bid, data={"_csrf": csrf},
                 follow_redirects=True)
body = text(r)
m = re.search(r"Mật khẩu mới của\s*binh\.le9a\s*là:\s*([A-Za-z0-9]+)", body)
check("bao mat khau moi", bool(m), body[:400])
conn = db.connect(DB)
row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (bid,))
check("bat lai co phai doi mat khau", row["must_change_password"] == 1)
check("mat khau cu khong con dung",
      not auth.verify_password(row["password_hash"], "matkhaucu1"))
conn.close()

print("\n=== 11. Xoa tai khoan: bai nop di theo, de bai o lai ===")
conn = db.connect(DB)
pid = db.query_one(conn, "SELECT id FROM problems WHERE code = ?", ("SL001",))["id"]
with conn:
    conn.execute(
        """INSERT INTO submissions (user_id, problem_id, language, source, status,
                                    verdict, score, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (bid, pid, "C++17", "int main(){}", "done", "AC", 100, db.utc_now()))
    conn.execute("UPDATE problems SET author_id = ? WHERE id = ?", (bid, pid))
conn.close()

csrf = token(teacher, "/teacher/users")
r = teacher.post("/teacher/users/%d/delete" % bid, data={"_csrf": csrf},
                 follow_redirects=True)
check("bao so bai nop bi xoa theo", "Kéo theo 1 bài nộp" in text(r), text(r)[:300])
conn = db.connect(DB)
check("tai khoan da bi xoa", db.query_one(
    conn, "SELECT id FROM users WHERE id = ?", (bid,)) is None)
check("bai nop cua em do da bi xoa theo", db.scalar(
    conn, "SELECT COUNT(*) FROM submissions WHERE user_id = ?", (bid,)) == 0)
row = db.query_one(conn, "SELECT author_id FROM problems WHERE id = ?", (pid,))
check("de bai o lai, chi mat ten nguoi soan", row is not None and row["author_id"] is None,
      row["author_id"] if row else "mat de")
conn.close()

print("\n=== 12. Nhap bo du lieu tu ZIP qua giao dien ===")
csrf = token(teacher, "/teacher/problems/SL001/tests")
zip_bytes = make_zip({
    "TEST01/SL001.INP": "5\n1 2 3 4 5\n", "TEST01/SL001.OUT": "15\n",
    "TEST02/SL001.INP": "3\n7 7 7\n", "TEST02/SL001.OUT": "21\n",
    "TEST03/SL001.INP": "1\n9\n", "TEST03/SL001.OUT": "9\n",
    "loigiai.cpp": "int main(){}\n",
})
r = teacher.post("/teacher/problems/SL001/tests",
                 data={"_csrf": csrf, "action": "import",
                       "zip": (io.BytesIO(zip_bytes), "SL001.zip")},
                 content_type="multipart/form-data", follow_redirects=True)
body = text(r)
check("nhap duoc 3 bo tu ZIP", "Đã nhập 3 bộ dữ liệu" in body, body[:400])
check("bao ca tep bo qua", "không nhận dạng được" in body, body[:400])

conn = db.connect(DB)
rows = db.query(conn, "SELECT * FROM tests WHERE problem_id = ? ORDER BY ordinal", (pid,))
check("CSDL co dung 3 bo", len(rows) == 3, len(rows))
check("bo nhap tu ZIP mac dinh la AN", all(r["is_hidden"] == 1 for r in rows))
check("thu tu bat dau tu 1", [r["ordinal"] for r in rows] == [1, 2, 3],
      [r["ordinal"] for r in rows])
check("noi dung vao cua bo 1 dung", rows[0]["input"] == "5\n1 2 3 4 5\n", repr(rows[0]["input"]))
check("ghi chu luu ten bo", rows[0]["note"] == "TEST01/SL001", rows[0]["note"])
conn.close()

print("\n=== 13. Nhap them thi cong don, khong xoa bo cu ===")
csrf = token(teacher, "/teacher/problems/SL001/tests")
zip_bytes = make_zip({"TEST04/SL001.INP": "2\n2 2\n", "TEST04/SL001.OUT": "4\n"})
teacher.post("/teacher/problems/SL001/tests",
             data={"_csrf": csrf, "action": "import",
                   "zip": (io.BytesIO(zip_bytes), "them.zip")},
             content_type="multipart/form-data", follow_redirects=True)
conn = db.connect(DB)
n = db.scalar(conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?", (pid,))
last = db.query_one(conn, "SELECT MAX(ordinal) AS m FROM tests WHERE problem_id = ?", (pid,))
check("nhap them: bo cu con nguyen", n == 4, n)
check("bo moi noi tiep so thu tu", last["m"] == 4, last["m"])
conn.close()

print("\n=== 14. Tich 'thay the' thi xoa bo cu ===")
csrf = token(teacher, "/teacher/problems/SL001/tests")
zip_bytes = make_zip({"T1/SL.INP": "1\n", "T1/SL.OUT": "1\n"})
r = teacher.post("/teacher/problems/SL001/tests",
                 data={"_csrf": csrf, "action": "import", "replace": "1",
                       "zip": (io.BytesIO(zip_bytes), "thay.zip")},
                 content_type="multipart/form-data", follow_redirects=True)
check("bao da thay toan bo", "đã thay toàn bộ bộ cũ" in text(r), text(r)[:400])
conn = db.connect(DB)
check("chi con 1 bo", db.scalar(
    conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?", (pid,)) == 1)
conn.close()

print("\n=== 15. ZIP hong: bao loi doc duoc, khong vo trang ===")
csrf = token(teacher, "/teacher/problems/SL001/tests")
r = teacher.post("/teacher/problems/SL001/tests",
                 data={"_csrf": csrf, "action": "import",
                       "zip": (io.BytesIO(b"khong phai zip"), "rac.zip")},
                 content_type="multipart/form-data", follow_redirects=True)
check("bao tep khong phai ZIP", "không phải ZIP hợp lệ" in text(r), text(r)[:300])
check("trang van la 200", r.status_code == 200)

csrf = token(teacher, "/teacher/problems/SL001/tests")
r = teacher.post("/teacher/problems/SL001/tests",
                 data={"_csrf": csrf, "action": "import"},
                 content_type="multipart/form-data", follow_redirects=True)
check("khong chon tep: bao ro rang", "chưa chọn tệp ZIP" in text(r), text(r)[:300])

print("\n=== 16. Xoa de bai: keo theo du lieu va bai nop ===")
conn = db.connect(DB)
pid2 = db.query_one(conn, "SELECT id FROM problems WHERE code = ?", ("SL002",))["id"]
with conn:
    conn.execute("INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points) "
                 "VALUES (?,1,'1\\n','1\\n',1,0)", (pid2,))
    conn.execute(
        """INSERT INTO submissions (user_id, problem_id, language, source, status,
                                    verdict, score, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (meid, pid2, "C++17", "int main(){}", "done", "AC", 100, db.utc_now()))
conn.close()

csrf = token(teacher, "/teacher/problems")
r = teacher.post("/teacher/problems/SL002/delete", data={"_csrf": csrf},
                 follow_redirects=True)
body = text(r)
check("bao so bo du lieu va bai nop bi xoa", "Kéo theo 1 bộ dữ liệu và 1 bài nộp" in body,
      body[:400])
conn = db.connect(DB)
check("de da bi xoa", db.query_one(
    conn, "SELECT id FROM problems WHERE code = ?", ("SL002",)) is None)
check("bo du lieu xoa theo (cascade)", db.scalar(
    conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?", (pid2,)) == 0)
check("bai nop xoa theo (cascade)", db.scalar(
    conn, "SELECT COUNT(*) FROM submissions WHERE problem_id = ?", (pid2,)) == 0)
conn.close()

print("\n=== 17. Ky thi: tao, sua, chon de, xoa ===")
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/create",
                 data={"_csrf": csrf, "name": "Khảo sát giữa kỳ I",
                       "description": "Ba bài, 90 phút",
                       "starts_at": "2026-11-20T08:00", "ends_at": "2026-11-20T09:30",
                       "scoring": "ioi", "status": "draft"},
                 follow_redirects=True)
check("tao duoc ky thi", "Đã tạo kỳ thi" in text(r), text(r)[:300])
conn = db.connect(DB)
c = db.query_one(conn, "SELECT * FROM contests WHERE name = ?", ("Khảo sát giữa kỳ I",))
check("ky thi co trong CSDL", c is not None)
cid = c["id"] if c else None
# Gio Viet Nam 08:00 phai duoc luu thanh 01:00 UTC, khong phai 08:00.
check("gio Viet Nam duoc doi sang UTC", c and c["starts_at"] == "2026-11-20T01:00:00Z",
      c["starts_at"] if c else None)
conn.close()

# Ket thuc truoc khi bat dau -> tu choi
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/create",
                 data={"_csrf": csrf, "name": "Sai giờ",
                       "starts_at": "2026-11-20T10:00", "ends_at": "2026-11-20T09:00",
                       "scoring": "ioi", "status": "draft"},
                 follow_redirects=True)
check("chan thoi gian ket thuc truoc bat dau", "phải sau thời gian bắt đầu" in text(r),
      text(r)[:300])

# Sua ky thi
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/%d/update" % cid,
                 data={"_csrf": csrf, "name": "Khảo sát giữa kỳ I (đổi tên)",
                       "description": "Bốn bài", "starts_at": "2026-11-20T08:00",
                       "ends_at": "2026-11-20T10:00", "scoring": "acm", "status": "open"},
                 follow_redirects=True)
conn = db.connect(DB)
c = db.query_one(conn, "SELECT * FROM contests WHERE id = ?", (cid,))
check("sua duoc ten ky thi", c["name"] == "Khảo sát giữa kỳ I (đổi tên)", c["name"])
check("sua duoc cach tinh diem", c["scoring"] == "acm", c["scoring"])
check("sua duoc trang thai", c["status"] == "open", c["status"])
conn.close()

# Chon de cho ky thi
conn = db.connect(DB)
allp = db.query(conn, "SELECT id FROM problems ORDER BY code")
ids = [r["id"] for r in allp]
conn.close()
csrf = token(teacher, "/teacher/contests")
# Nhiều ô cùng tên `problem_id`: truyền giá trị dạng danh sách, đúng cách một
# biểu mẫu có nhiều ô tích gửi lên.
r = teacher.post("/teacher/contests/%d/problems" % cid,
                 data={"_csrf": csrf, "problem_id": [str(i) for i in ids]},
                 follow_redirects=True)
check("bao dung so de da luu", "danh sách đề của kỳ thi: %d đề" % len(ids) in text(r),
      text(r)[:300])
conn = db.connect(DB)
_n = db.scalar(conn, "SELECT COUNT(*) FROM contest_problems WHERE contest_id = ?", (cid,))
check("CSDL co du so de", _n == len(ids), "co %d, mong doi %d, ids=%s" % (_n, len(ids), ids))
# `ordinal` la NOT NULL khong co mac dinh: thieu no thi lenh ghi that bai, va
# neu lenh do lai dung `INSERT OR IGNORE` thi that bai do hoan toan im lang.
_ord = [r["ordinal"] for r in db.query(
    conn, "SELECT ordinal FROM contest_problems WHERE contest_id = ? ORDER BY ordinal", (cid,))]
check("ordinal duoc ghi, bat dau tu 1", _ord == list(range(1, len(ids) + 1)), _ord)
conn.close()

# Gui trung mot ma de hai lan (bieu mau meo): phai bo qua ban trung, khong vo trang
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/%d/problems" % cid,
                 data={"_csrf": csrf, "problem_id": [str(ids[0]), str(ids[0])]},
                 follow_redirects=True)
conn = db.connect(DB)
check("gui trung ma de khong lam vo trang", r.status_code == 200, r.status_code)
check("gui trung ma de chi luu mot dong", db.scalar(
    conn, "SELECT COUNT(*) FROM contest_problems WHERE contest_id = ?", (cid,)) == 1)
conn.close()

# De khong ton tai: bao ro da bo qua, khong bao thanh cong khong
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/%d/problems" % cid,
                 data={"_csrf": csrf, "problem_id": [str(ids[0]), "999999"]},
                 follow_redirects=True)
check("bao bo qua de khong ton tai", "Bỏ qua 1 đề không còn tồn tại" in text(r), text(r)[:300])

# Bo het de
csrf = token(teacher, "/teacher/contests")
teacher.post("/teacher/contests/%d/problems" % cid, data={"_csrf": csrf},
             follow_redirects=True)
conn = db.connect(DB)
check("bo het tich thi danh sach de rong", db.scalar(
    conn, "SELECT COUNT(*) FROM contest_problems WHERE contest_id = ?", (cid,)) == 0)
conn.close()

# Dang ky du thi, roi xoa ky thi: luot dang ky di, bai nop o lai
conn = db.connect(DB)
with conn:
    conn.execute("INSERT INTO contest_entries (contest_id, user_id, registered_at) VALUES (?,?,?)",
                 (cid, meid, db.utc_now()))
conn.close()
csrf = token(teacher, "/teacher/contests")
r = teacher.post("/teacher/contests/%d/delete" % cid, data={"_csrf": csrf},
                 follow_redirects=True)
check("bao kem so luot dang ky", "kèm 1 lượt đăng ký" in text(r), text(r)[:300])
conn = db.connect(DB)
check("ky thi da bi xoa", db.query_one(
    conn, "SELECT id FROM contests WHERE id = ?", (cid,)) is None)
check("luot dang ky xoa theo", db.scalar(
    conn, "SELECT COUNT(*) FROM contest_entries WHERE contest_id = ?", (cid,)) == 0)
conn.close()

print("\n=== 18. Cong khai de: soan xong la ra toi hoc sinh ===")

# Tao de that qua dung bieu mau ma giao vien dung — khong chen thang vao CSDL,
# vi chinh buoc tao de la cho sinh ra trang thai 'draft'.
csrf = token(teacher, "/teacher/problems")
r = teacher.post("/teacher/problems",
                 data={"_csrf": csrf, "code": "SL900", "name": "Tính tổng kiểm thử",
                       "statement": "Tính tổng dãy số.", "difficulty": "co-ban",
                       "topic": "Số học", "points_mode": "even",
                       "time_limit_s": "1", "memory_limit_mb": "256"},
                 follow_redirects=True)
body = text(r)
check("tao duoc de moi", "Đã tạo đề SL900" in body, body[:300])
check("thong bao tao de noi ro buoc con thieu", "nhập bộ dữ liệu" in body, body[:300])
conn = db.connect(DB)
row = db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")
check("de moi ra doi o dang ban nhap", row is not None and row["status"] == "draft",
      row and row["status"])
conn.close()

# SL900 dang la 'draft' va **chua co bo du lieu nao**. Cong khai phai bi chan,
# va ly do phai noi ro buoc con thieu chu khong chi tra mot trang loi.
csrf = token(teacher, "/teacher/problems")
r = teacher.post("/teacher/problems/SL900/status",
                 data={"_csrf": csrf, "status": "live"}, follow_redirects=True)
check("chua co du lieu thi khong cong khai duoc",
      "chưa có bộ dữ liệu" in text(r), text(r)[:300])
conn = db.connect(DB)
check("trang thai van la draft",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")["status"] == "draft")
conn.close()

# De ban nhap khong duoc ra toi hoc sinh — ca danh sach lan duong dan truc tiep.
check("hoc sinh khong thay de ban nhap trong danh sach",
      "SL900" not in text(student.get("/problems")))
r = student.get("/problems/SL900")
check("hoc sinh mo thang de ban nhap bi chan", r.status_code == 404, r.status_code)

# Man hinh phai **noi ra** rang de dang khong hien voi hoc sinh. Thieu dong nay
# chinh la ly do mot de soan xong nam im ma khong ai biet.
page = text(teacher.get("/teacher/problems"))
check("danh sach co canh bao de chua cong khai", "đề chưa công khai" in page)
check("canh bao noi ro hoc sinh khong thay", "học sinh không thấy" in page)
check("o trang thai ghi ro 'Hoc sinh khong thay'", "Học sinh không thấy" in page)
check("nut Cong khai bi mo khi thieu du lieu", "chưa công khai được" in page)
# Chua co du lieu thi chi co nut mo, khong co bieu mau nao de gui — nen trong
# trang khong co `action=...` tro tới tuyến đường đổi trạng thái.
check("thieu du lieu thi khong co bieu mau doi trang thai",
      'action="/teacher/problems/SL900/status"' not in page)

# Nhap du lieu vao mot de dang o ban nhap thi de **tu** cong khai. Day la duong
# di that: soan de -> nhap bo du lieu -> hoc sinh thay. Khong co buoc thu ba.
zip_bytes = make_zip({
    "TEST01/SL900.INP": "1 2\n", "TEST01/SL900.OUT": "3\n",
    "TEST02/SL900.INP": "3 4\n", "TEST02/SL900.OUT": "7\n",
})
r = teacher.post("/teacher/problems/SL900/tests",
                 data={"_csrf": csrf, "action": "import",
                       "zip": (io.BytesIO(zip_bytes), "bo.zip")},
                 content_type="multipart/form-data", follow_redirects=True)
body = text(r)
check("nhap ZIP xong", "Đã nhập 2 bộ dữ liệu" in body, body[:400])
check("thong bao noi de da cong khai", "đã được công khai" in body, body[:400])
conn = db.connect(DB)
check("trang thai thanh live sau khi nhap",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")["status"] == "live")
conn.close()
check("hoc sinh da thay de", "SL900" in text(student.get("/problems")))

# Thu hoi ve ban nhap: de bien mat khoi danh sach cua hoc sinh.
r = teacher.post("/teacher/problems/SL900/status",
                 data={"_csrf": csrf, "status": "draft"}, follow_redirects=True)
check("thu hoi duoc", "đã thu hồi" in text(r), text(r)[:300])
check("thu hoi xong hoc sinh khong thay nua",
      "SL900" not in text(student.get("/problems")))

# Co du lieu roi thi dong tren danh sach phai co bieu mau cong khai that.
page = text(teacher.get("/teacher/problems"))
check("co du lieu thi co bieu mau doi trang thai tren danh sach",
      'action="/teacher/problems/SL900/status"' in page)
check("nut cong khai khong con bi mo", "chưa công khai được" not in page)
# Dong nay phai hien cho MOI de chua cong khai, ke ca de da co du lieu. Truoc
# day no chi hien khi de thieu du lieu — tuc la hien dung luc it can nhat.
check("de co du lieu nhung chua cong khai van ghi 'Hoc sinh khong thay'",
      "Học sinh không thấy" in page)

# Cong khai lai bang mot bam.
r = teacher.post("/teacher/problems/SL900/status",
                 data={"_csrf": csrf, "status": "live"}, follow_redirects=True)
check("cong khai lai duoc bang mot bam", "đã công khai" in text(r), text(r)[:300])
check("hoc sinh thay lai", "SL900" in text(student.get("/problems")))

# De o 'review' la giao vien da chon ro rang -> nhap du lieu KHONG tu doi.
conn = db.connect(DB)
with conn:
    conn.execute("UPDATE problems SET status='review' WHERE code='SL900'")
conn.close()
teacher.post("/teacher/problems/SL900/tests",
             data={"_csrf": csrf, "action": "import",
                   "zip": (io.BytesIO(zip_bytes), "bo.zip")},
             content_type="multipart/form-data", follow_redirects=True)
conn = db.connect(DB)
check("de o 'review' khong bi tu doi trang thai",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")["status"] == "review")
conn.close()

# O "Giu de o ban nhap" thi khong tu cong khai.
conn = db.connect(DB)
with conn:
    conn.execute("UPDATE problems SET status='draft' WHERE code='SL900'")
conn.close()
r = teacher.post("/teacher/problems/SL900/tests",
                 data={"_csrf": csrf, "action": "import", "keep_draft": "1",
                       "zip": (io.BytesIO(zip_bytes), "bo.zip")},
                 content_type="multipart/form-data", follow_redirects=True)
check("tich giu nhap thi khong tu cong khai", "vẫn ở bản nháp" in text(r), text(r)[:400])
conn = db.connect(DB)
check("trang thai van la draft khi tich giu nhap",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")["status"] == "draft")
conn.close()

# Trang bo du lieu: da co du lieu thi phai co nut cong khai ngay tai cho.
page = text(teacher.get("/teacher/problems/SL900/tests"))
check("trang bo du lieu bao de chua cong khai", "học sinh chưa thấy" in page)
check("trang bo du lieu co nut cong khai ngay", "Công khai đề ngay" in page)
check("bieu mau nhap co o giu nhap", 'name="keep_draft"' in page)

# Trang sua de: co nut "Luu va cong khai", va nut do phai **de** o chon trang
# thai. Khong de thi bam nut ma de van nam o ban nhap — dung cai bay can dep.
page = text(teacher.get("/teacher/problems/SL900/edit"))
check("trang sua de co nut Luu va cong khai", 'name="publish"' in page)

r = teacher.post("/teacher/problems/SL900/edit",
                 data={"_csrf": csrf, "name": "Tính tổng", "statement": "Tính tổng dãy số.",
                       "difficulty": "co-ban", "topic": "Số học", "points_mode": "even",
                       "time_limit_s": "1", "memory_limit_mb": "256",
                       "status": "draft", "publish": "1"}, follow_redirects=True)
check("bam Luu va cong khai thi bao da cong khai",
      "Đã lưu và công khai" in text(r), text(r)[:300])
conn = db.connect(DB)
check("o chon la 'draft' nhung trang thai thanh live",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL900'")["status"] == "live")
conn.close()

# De chua co du lieu thi trang sua de khong hien nut do, nhung phai noi vi sao.
conn = db.connect(DB)
with conn:
    conn.execute("DELETE FROM tests WHERE problem_id = "
                 "(SELECT id FROM problems WHERE code='SL900')")
    conn.execute("UPDATE problems SET status='draft' WHERE code='SL900'")
conn.close()
page = text(teacher.get("/teacher/problems/SL900/edit"))
check("thieu du lieu thi an nut Luu va cong khai", 'name="publish"' not in page)
check("thieu du lieu thi noi ro vi sao", "chưa có bộ dữ liệu nào" in page)

print("\n=== 18b. Doi trang thai: chan cac duong di sai ===")

# Hoc sinh khong duoc doi trang thai de. Dung token cua chinh phien hoc sinh,
# neu khong thi bai kiem chi chung minh CSRF chan duoc chu khong chung minh
# `teacher_required` chan duoc.
s_csrf = token(student, "/account")
r = student.post("/teacher/problems/SL001/status",
                 data={"_csrf": s_csrf, "status": "draft"})
check("hoc sinh khong doi duoc trang thai de", r.status_code in (302, 403), r.status_code)
conn = db.connect(DB)
check("trang thai SL001 khong bi hoc sinh doi",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL001'")["status"] == "live")
conn.close()

# De khong ton tai -> 404, khong phai 500.
r = teacher.post("/teacher/problems/KHONGCO/status",
                 data={"_csrf": csrf, "status": "live"})
check("doi trang thai de khong ton tai tra 404", r.status_code == 404, r.status_code)

# Trang thai la -> tu choi, khong ghi gi.
r = teacher.post("/teacher/problems/SL001/status",
                 data={"_csrf": csrf, "status": "published"}, follow_redirects=True)
check("trang thai la bi tu choi", "không hợp lệ" in text(r), text(r)[:300])
conn = db.connect(DB)
check("trang thai khong doi khi gia tri la",
      db.query_one(conn, "SELECT status FROM problems WHERE code='SL001'")["status"] == "live")
conn.close()

# `back` la mot truong cua bieu mau: nhan bua thi thanh open redirect.
r = teacher.post("/teacher/problems/SL001/status",
                 data={"_csrf": csrf, "status": "live", "back": "https://example.com/x"})
check("khong chuyen huong ra ngoai site",
      "example.com" not in r.headers.get("Location", ""), r.headers.get("Location"))

r = teacher.post("/teacher/problems/SL001/status",
                 data={"_csrf": csrf, "status": "live",
                       "back": "/teacher/problems/SL001/tests"})
check("back noi bo duoc ton trong",
      r.headers.get("Location", "").endswith("/teacher/problems/SL001/tests"),
      r.headers.get("Location"))

print("\n=== 19. Trang khac khong bi vo ===")
for path in ("/", "/problems", "/submissions", "/leaderboard", "/contests",
             "/teacher", "/teacher/problems", "/teacher/classes", "/teacher/users",
             "/teacher/contests", "/teacher/problems/SL001/tests",
             "/teacher/problems/SL001/edit"):
    r = teacher.get(path)
    check("giao vien mo duoc %s" % path, r.status_code == 200, r.status_code)

print("\n=== 20. Tep khong ton tai tra 404, khong phai 500 ===")
for path in ("/teacher/problems/KHONGCO/tests", "/teacher/users/99999/update",
             "/teacher/users/99999/delete", "/teacher/users/99999/reset",
             "/teacher/contests/99999/update", "/teacher/contests/99999/delete"):
    r = teacher.post(path, data={"_csrf": token(teacher, "/teacher/users")})
    check("%s tra 404" % path, r.status_code == 404, r.status_code)

print("\n=== 21. Sinh bo du lieu tu bo sinh va loi giai mau ===")

# Vì sao kiểm phần này kỹ: đây là đường **chạy chương trình do giáo viên gửi
# lên**. Mọi thứ khác trong tệp này chỉ đọc/ghi CSDL; riêng ở đây có một tiến
# trình được dịch và chạy thật. Ba nhóm phải kiểm:
#
#   1. Đường đúng: sinh ra bộ dữ liệu, đánh dấu ẩn, tự công khai.
#   2. Cùng chỉ số bộ thì ra cùng dữ liệu — đây là lý do bộ sinh nhận `argv[1]`,
#      và nếu mất tính chất này thì không sinh lại được đúng bộ cũ khi cần.
#   3. Mọi đường sai đều phải trả về **một câu đọc được**, không phải trang 500
#      và không phải im lặng: bộ sinh không dịch được, bộ sinh không in gì, bộ
#      sinh treo, lời giải mẫu thoát lỗi, thiếu một trong hai, mã nguồn quá dài.

GEN_OK = r'''
#include <iostream>
#include <cstdlib>
using namespace std;
int main(int argc, char** argv) {
    int seed = argc > 1 ? atoi(argv[1]) : 1;
    srand(seed);
    int n = 3 + rand() % 5;
    cout << n << "\n";
    for (int i = 0; i < n; i++) cout << rand() % 100 << " ";
    cout << "\n";
    return 0;
}
'''

SOL_OK = r'''
#include <iostream>
using namespace std;
int main() {
    int n; cin >> n;
    long long s = 0, x;
    while (n--) { cin >> x; s += x; }
    cout << s << "\n";
    return 0;
}
'''

# Tao de qua dung bieu mau that, giong muc §18. De sinh ra o trang thai `draft`.
csrf = token(teacher, "/teacher/problems")
teacher.post("/teacher/problems",
             data={"_csrf": csrf, "code": "SL901", "name": "Tổng dãy sinh tự động",
                   "statement": "Tính tổng dãy số.", "difficulty": "co-ban",
                   "topic": "Số học", "points_mode": "even",
                   "time_limit_s": "1", "memory_limit_mb": "256"},
             follow_redirects=True)

TESTS_URL = "/teacher/problems/SL901/tests"


def sl901_tests():
    """Doc cac bo du lieu cua SL901 thang tu CSDL."""
    c = db.connect(DB)
    rows = db.query(
        c, """SELECT t.ordinal, t.input, t.output, t.is_hidden, t.note
                FROM tests t JOIN problems p ON p.id = t.problem_id
               WHERE p.code = 'SL901' ORDER BY t.ordinal""")
    c.close()
    return rows


def sl901_status():
    c = db.connect(DB)
    row = db.query_one(c, "SELECT status FROM problems WHERE code = 'SL901'")
    c.close()
    return row["status"]


def wipe_sl901():
    c = db.connect(DB)
    with c:
        c.execute("""DELETE FROM tests WHERE problem_id =
                       (SELECT id FROM problems WHERE code = 'SL901')""")
        c.execute("UPDATE problems SET status = 'draft' WHERE code = 'SL901'")
    c.close()


def gen(data, follow=True):
    d = {"_csrf": csrf, "action": "generate",
         "gen_source": GEN_OK, "sol_source": SOL_OK, "count": "3"}
    d.update(data)
    return teacher.post(TESTS_URL, data=d, follow_redirects=follow)


# --- 21a. Duong dung -------------------------------------------------------
r = gen({})
body = text(r)
check("sinh duoc 3 bo", "Đã sinh 3 bộ dữ liệu" in body, body[:400])
rows = sl901_tests()
check("CSDL co dung 3 bo", len(rows) == 3, len(rows))
check("bo sinh ra deu la bo an", all(x["is_hidden"] == 1 for x in rows),
      [(x["ordinal"], x["is_hidden"]) for x in rows])
check("ghi chu noi ro bo nao do bo sinh tao",
      [x["note"] for x in rows] == ["sinh 01", "sinh 02", "sinh 03"],
      [x["note"] for x in rows])
# Dap an phai la tong cua chinh du lieu vao — tuc la loi giai mau da chay tren
# dung bo du lieu ma bo sinh vua tao, chu khong phai mot con so nao khac.
ok_answers = True
for x in rows:
    nums = [int(v) for v in x["input"].split()]
    if len(nums) < 1 or sum(nums[1:]) != int(x["output"].strip()):
        ok_answers = False
check("dap an dung la tong cua du lieu vao", ok_answers,
      [(x["input"], x["output"]) for x in rows])
check("de tu cong khai sau khi sinh", sl901_status() == "live", sl901_status())
check("thong bao noi de da ra toi hoc sinh", "đã được công khai" in body, body[:400])
check("hoc sinh thay de vua sinh du lieu", "SL901" in text(student.get("/problems")))

# --- 21b. Cung chi so bo -> cung du lieu -----------------------------------
# Sinh them 3 bo nua voi **cung** hai chuong trinh. Bo 4, 5, 6 phai trung bo 1,
# 2, 3. Mat tinh chat nay nghia la khong tai tao duoc mot bo cu the khi can doi
# chieu, va do la ly do duy nhat khien bo sinh nhan `argv[1]`.
first = [x["input"] for x in sl901_tests()]
r = gen({})
again = [x["input"] for x in sl901_tests()]
check("sinh them 3 bo nua", len(again) == 6, len(again))
check("cung chi so bo thi ra cung du lieu", again[3:6] == first[0:3],
      list(zip(first[0:3], again[3:6])))
check("khong tu xoa bo cu khi sinh them", len(again) == 6, len(again))

# --- 21c. count = 0 van phai sinh duoc mot bo ------------------------------
# Keo ve 1 chu khong phai 0: mot yeu cau "sinh 0 bo" ma tra ve trang thai thanh
# cong kem 0 bo la mot yeu cau im lang khong lam gi.
wipe_sl901()
r = gen({"count": "0"})
check("count = 0 keo ve 1 bo", "Đã sinh 1 bộ dữ liệu" in text(r), text(r)[:300])
check("CSDL co 1 bo", len(sl901_tests()) == 1, len(sl901_tests()))

# --- 21d. Cac duong sai ----------------------------------------------------
wipe_sl901()

r = gen({"gen_source": "int main() { this is not cpp }"})
body = text(r)
check("bo sinh khong dich duoc: bao loi", "Bộ sinh dữ liệu không dịch được" in body,
      body[:400])
check("bo sinh khong dich duoc: khong them bo nao", len(sl901_tests()) == 0,
      len(sl901_tests()))

r = gen({"sol_source": "int main() { this is not cpp }"})
check("loi giai mau khong dich duoc: bao loi",
      "Lời giải mẫu không dịch được" in text(r), text(r)[:400])

# Bo sinh chay xong ma khong in gi. Day la loi rat de mac: quen `cout`, hoac
# ghi ra `cerr`. Neu khong chan thi se co mot bo du lieu vao rong, va moi bai
# nop deu dung — de trong nhu vay khong ai nhan ra la de.
r = gen({"gen_source": "int main() { return 0; }"})
check("bo sinh khong in gi: bao loi doc duoc",
      "không in ra gì" in text(r), text(r)[:400])
check("bo sinh khong in gi: khong them bo nao", len(sl901_tests()) == 0,
      len(sl901_tests()))

# Loi giai mau chay xong voi ma thoat khac 0.
r = gen({"sol_source": "int main() { return 3; }"})
check("loi giai mau thoat loi: bao loi doc duoc",
      "Lời giải mẫu thoát với mã 3" in text(r), text(r)[:400])

r = gen({"gen_source": "   "})
check("thieu bo sinh: bao loi", "Cần cả bộ sinh dữ liệu và lời giải mẫu" in text(r),
      text(r)[:300])
r = gen({"sol_source": ""})
check("thieu loi giai mau: bao loi", "Cần cả bộ sinh dữ liệu và lời giải mẫu" in text(r),
      text(r)[:300])

# Ma nguon qua dai. Chan truoc khi ghi ra dia, khong phai sau khi dich.
r = gen({"gen_source": "//" + "x" * (64 * 1024)})
check("ma nguon qua dai: bao loi", "dài quá 64 KB" in text(r), text(r)[:300])

# Bo sinh khong ket thuc. Day la duong nguy hiem nhat: khong co gioi han thi
# mot worker cua gunicorn bi giu mai mai, va chi can vai lan la ca trang dung.
# Chay that voi gioi han that (5 giay) chu khong ha xuong cho nhanh — ha xuong
# thi bai kiem khong con chung minh duoc gioi han that su co tac dung.
r = gen({"gen_source": "int main() { while (true) {} }"})
check("bo sinh treo: bao loi doc duoc", "không kết thúc trong 5 giây" in text(r),
      text(r)[:400])
check("bo sinh treo: khong them bo nao", len(sl901_tests()) == 0, len(sl901_tests()))

# --- 21e. keep_draft: giao vien dang soan do ------------------------------
wipe_sl901()
r = gen({"keep_draft": "1"})
body = text(r)
check("keep_draft: van sinh duoc du lieu", "Đã sinh 3 bộ dữ liệu" in body, body[:400])
check("keep_draft: de van o ban nhap", sl901_status() == "draft", sl901_status())
check("keep_draft: thong bao noi ro hoc sinh chua thay",
      "vẫn ở bản nháp" in body, body[:400])

# --- 21f. Quyen va CSRF ----------------------------------------------------
# Dung token cua **chinh phien hoc sinh**. Lay token cua giao vien thi bai kiem
# chi chung minh CSRF chan duoc, chu khong chung minh `teacher_required` chan
# duoc — ma day moi la thu can chung minh.
s_csrf = token(student, "/account")
r = student.post(TESTS_URL, data={"_csrf": s_csrf, "action": "generate",
                                  "gen_source": GEN_OK, "sol_source": SOL_OK,
                                  "count": "1"})
check("hoc sinh khong sinh duoc du lieu", r.status_code in (302, 403), r.status_code)

r = teacher.post(TESTS_URL, data={"action": "generate",
                                  "gen_source": GEN_OK, "sol_source": SOL_OK,
                                  "count": "1"})
check("thieu CSRF thi bi chan", r.status_code == 400, r.status_code)

# --- 21g. Bieu mau phai co du truong --------------------------------------
page = text(teacher.get(TESTS_URL))
check("bieu mau sinh co o bo sinh", 'name="gen_source"' in page)
check("bieu mau sinh co o loi giai mau", 'name="sol_source"' in page)
check("bieu mau sinh co o so bo", 'name="count"' in page)
check("bieu mau sinh noi ro tran so bo", 'max="30"' in page)
check("bieu mau sinh co o giu nhap", 'name="keep_draft"' in page)
check("bieu mau sinh noi ro bo sinh nhan argv",
      "argv[1]" in page, page[:200])

# Don sach de khong anh huong cac muc sau.
conn = db.connect(DB)
with conn:
    conn.execute("DELETE FROM problems WHERE code = 'SL901'")
conn.close()

shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print("DAT: %d   SAI: %d" % (len(OK), len(BAD)))
if BAD:
    print("\nCac bai sai:")
    for b in BAD:
        print("  -", b)
sys.exit(1 if BAD else 0)
