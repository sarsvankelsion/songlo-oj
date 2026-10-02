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
import csv
import io
import os
import re
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import aiwriter, auth, db, gendata, grades, themis   # noqa: E402
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
                  # Cô lập cả hai thư mục làm việc. Mặc định chúng là
                  # `server/var/judge` và `server/var/gendata`, tức là bài kiểm
                  # thử sẽ ghi vào cây mã nguồn — và mục §21 dịch và chạy chương
                  # trình thật, nên nó tạo ra tệp thật.
                  "JUDGE_WORKSPACE": os.path.join(TMP, "judge"),
                  "GENDATA_WORKSPACE": os.path.join(TMP, "gendata")})
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
#
# Phai chap nhan **hai** cau tra loi khac nhau, vi hai he dieu hanh giet no theo
# hai cach khac nhau: tren Linux `RLIMIT_CPU` gui `SIGXCPU` roi `SIGKILL` nen no
# chet vi tin hieu (dong ho gio thuc khong kip chay), con tren Windows khong co
# `RLIMIT_CPU` nen dong ho gio thuc moi la thu giet no. Doi dung mot cau la bai
# kiem dung o may nay va sai o may kia — va do dung la chuyen da xay ra.
r = gen({"gen_source": "int main() { while (true) {} }"})
body = text(r)
check("bo sinh treo: bao da vuot gioi han thoi gian",
      ("không kết thúc trong 5 giây" in body) or ("quá 5 giây CPU" in body),
      body[:400])
# Va tuyet doi khong duoc bao bang ma thoat am. Tren Linux, mot tien trinh bi
# giet vi tin hieu co `exit_code = -1`; di thang vao nhanh "thoát với mã %d" thi
# giao vien nhan cau "Bộ sinh dữ liệu thoát với mã -1" — mot con so khong co
# nghia gi voi ho, va khong noi gi ve viec da vuot thoi gian.
check("bo sinh treo: khong bao bang ma thoat am", "mã -1" not in body, body[:400])
check("bo sinh treo: khong them bo nao", len(sl901_tests()) == 0, len(sl901_tests()))

# Thu muc lam viec cua viec sinh du lieu phai **khac** thu muc cham bai. Tren may
# chu that, `judge/` thuoc `root` va tien trinh web (tai khoan `songlo`) khong ghi
# duoc vao do — dung chung mot thu muc thi moi lan sinh du lieu deu 500.
check("sinh du lieu dung thu muc lam viec rieng",
      app.config["GENDATA_WORKSPACE"] != app.config["JUDGE_WORKSPACE"],
      (app.config["GENDATA_WORKSPACE"], app.config["JUDGE_WORKSPACE"]))

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

print("\n=== 22. Xuat bang diem ra CSV ===")

# Vi sao kiem phan nay: day la duong **duy nhat** dua diem ra khoi he thong. Mot
# loi o day khong lam sap trang nao ca — no cho ra mot tep trong nhu that, va
# giao vien chep so diem tu no. Ba nhom phai kiem:
#
#   1. Tep co mo duoc dung khong (BOM, dau phan cach, CRLF, chong cong thuc).
#   2. Bang co dung noi dung khong (o trong khac o 0; diem chi trong pham vi
#      dang xuat; hoc sinh khong nop bai van phai co ten).
#   3. Quyen va cac duong sai.
#
# Khong chay bo cham that: thu dang kiem la phep ket xuat, khong phai phep cham.
# Chen thang cac dong `submissions` da cham xong cho phep kiem dung nhung ca
# muon kiem — o trong so voi so 0, thang diem `custom` khac 100 — ma khong phu
# thuoc vao toc do cua g++.

CLS = "9Z"
OTHER = "8Z"


def seed_grades():
    """Dung du lieu diem cho muc §22. Xoa sach truoc de chay lai duoc."""
    c = db.connect(DB)
    with c:
        for code in ("SL950", "SL951", "SL952"):
            c.execute("DELETE FROM problems WHERE code = ?", (code,))
        c.execute("DELETE FROM users WHERE username LIKE 'zzgd%'")
        c.execute("DELETE FROM contests WHERE name = 'Kiem thu xuat diem'")
    now = db.utc_now()
    with c:
        for u, name, cls in (("zzgd1", "Trần Văn Giỏi", CLS),
                             ("zzgd2", "Lê Thị Khá", CLS),
                             ("zzgd3", "Phạm Văn Vắng", CLS),
                             ("zzgd4", "Hoàng Thị Lớp Khác", OTHER)):
            c.execute(
                """INSERT INTO users (username, full_name, class_name, role, password_hash,
                                      is_active, must_change_password, created_at)
                   VALUES (?,?,?,'student',?,1,0,?)""",
                (u, name, cls, auth.hash_password("123456"), now))
        # SL950 chia deu 2 bo -> toi da 100.
        # SL951 che do `custom` voi 60+20 -> toi da 80, KHONG phai 100. Day la
        # cho chung minh diem toi da duoc tinh tu dinh nghia de chu khong phai
        # mot hang so 100 gan cung.
        for code, name, mode in (("SL950", "Tổng dãy số", "even"),
                                 ("SL951", "Đếm ước số", "custom"),
                                 ("SL952", "Đề của lớp khác", "even")):
            c.execute(
                """INSERT INTO problems (code, name, statement, difficulty, topic,
                        time_limit_ms, memory_limit_mb, points_mode, status, created_at, updated_at)
                   VALUES (?,?,'', 'co-ban', '', 1000, 256, ?, 'live', ?, ?)""",
                (code, name, mode, now, now))
        pid = {r["code"]: r["id"] for r in db.query(c, "SELECT id, code FROM problems")}
        for code, pts in (("SL950", [0, 0]), ("SL951", [60, 20]), ("SL952", [0, 0])):
            for i, p in enumerate(pts, start=1):
                c.execute("INSERT INTO tests (problem_id, ordinal, input, output, is_hidden,"
                          " points, note) VALUES (?,?,?,'',1,?,'')", (pid[code], i, "1\n", p))
        uid = {r["username"]: r["id"] for r in db.query(
            c, "SELECT id, username FROM users WHERE username LIKE 'zzgd%'")}

        def sub(user, code, score, mx, status="done", contest=None, verdict="AC"):
            c.execute(
                """INSERT INTO submissions (problem_id, user_id, contest_id, language, source,
                        status, verdict, score, max_score, time_ms, memory_kb, created_at)
                   VALUES (?,?,?,'cpp17','',?,?,?,?,1,1,?)""",
                (pid[code], uid[user], contest, status, verdict, score, mx, now))

        # zzgd1: diem tuyet doi ca hai de.
        sub("zzgd1", "SL950", 100, 100)
        sub("zzgd1", "SL951", 80, 80)
        # zzgd2: nop nhieu lan, chi lay diem cao nhat; mot lan 0 diem that su.
        sub("zzgd2", "SL950", 50, 100)
        sub("zzgd2", "SL950", 70, 100)
        sub("zzgd2", "SL951", 0, 80, verdict="WA")
        # zzgd3: khong nop bai nao. Van phai co ten trong bang diem.
        # zzgd4 thuoc lop khac: khong duoc lot vao bang diem cua lop 9Z.
        sub("zzgd4", "SL952", 100, 100)
        sub("zzgd4", "SL950", 100, 100)
    c.close()
    return pid, uid


pid, uid = seed_grades()

# --- 22a. slug va to_csv, kiem thang khong qua mang ------------------------
check("slug bo dau tieng Viet", grades.slug("Kiểm tra giữa kỳ I") == "kiem-tra-giua-ky-i",
      grades.slug("Kiểm tra giữa kỳ I"))
check("slug bo dau d/Đ", grades.slug("Đội tuyển") == "doi-tuyen", grades.slug("Đội tuyển"))
check("slug chuoi rong co gia tri du phong", grades.slug("   ") == "khong-ten")
check("slug khong de gach noi lien nhau", "--" not in grades.slug("a  --  b"),
      grades.slug("a  --  b"))

raw = grades.to_csv({"header": ["Họ và tên", "Điểm"],
                     "rows": [["Nguyễn Văn An", 100], ["=1+1", ""]]}, ";")
check("CSV co BOM UTF-8", raw[:3] == b"\xef\xbb\xbf")
check("CSV ngat dong bang CRLF", b"\r\n" in raw)
check("CSV ngat cot bang dau cham phay", ";" in raw.decode("utf-8-sig"))
check("CSV giu duoc chu co dau",
      "Nguyễn Văn An" in raw.decode("utf-8-sig"), raw[:60])
# O bat dau bang `=` bi Excel coi la cong thuc. Phai co mot dau nhay don chan lai.
check("CSV chan o bat dau bang dau bang",
      "'=1+1" in raw.decode("utf-8-sig"), raw.decode("utf-8-sig"))
# Nhung o **so** thi khong duoc them dau nhay: them vao la moi phep tinh trong
# Excel hong, vi con so tro thanh chuoi.
check("CSV khong chan o so", ";100" in raw.decode("utf-8-sig"),
      raw.decode("utf-8-sig"))
check("CSV chan o bat dau bang @ va +",
      all(("'" + bad) in grades.to_csv(
          {"header": ["x"], "rows": [[bad]]}, ";").decode("utf-8-sig")
          for bad in ("@SUM(A1)", "+1", "-1")), )
check("dau phan cach la tuy chon", b"," in grades.to_csv(
    {"header": ["a", "b"], "rows": [[1, 2]]}, ","))
# Dau phan cach nam ngoai danh sach cho phep phai bi thay bang `;`, khong duoc
# lot ra tep: mot tep ngat bang `|` thi Excel doc ca dong thanh mot o duy nhat.
# Kiem dong tieu de cho chinh xac — dem dau `;` trong ca tep se dem ca dong du
# lieu va khong noi len dieu gi.
_bad = grades.to_csv({"header": ["a", "b"], "rows": [[1, 2]]}, "|").decode("utf-8-sig")
check("dau phan cach la bi tu choi thi ve mac dinh",
      _bad.splitlines()[0] == "a;b" and "|" not in _bad, _bad)


def read_csv(body):
    """Doc lai tep CSV thanh danh sach dong. Tra ``(dong_tieu_de, cac_dong)``."""
    text = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    return rows[0], rows[1:]


def row_of(rows, name_part):
    for r in rows:
        if name_part in r[0]:
            return r
    return None


# --- 22b. Bang diem cua lop, qua dung tuyen duong --------------------------
r = teacher.get("/teacher/classes/export?class=%s" % CLS)
check("xuat bang diem lop tra 200", r.status_code == 200, r.status_code)
check("tra ve tep dinh kem", "attachment" in r.headers.get("Content-Disposition", ""),
      r.headers.get("Content-Disposition"))
check("khong cho luu dem tep diem", r.headers.get("Cache-Control") == "no-store",
      r.headers.get("Cache-Control"))
disp = r.headers.get("Content-Disposition", "")
check("ten tep khong dau (tieu de HTTP la latin-1)", disp.isascii(), disp)
check("ten tep co ma lop", "9z" in disp.lower(), disp)

header, rows = read_csv(r.data)
check("dong dau la ho ten", header[0] == "Họ và tên", header[:3])
check("co cot lop", header[2] == "Lớp", header[:3])
# Cot la nhung de **lop nay da lam**, theo ma de. SL952 chi co lop khac lam nen
# khong duoc xuat hien — mot bang diem 30 cot toan o trong thi khong ai doc.
check("cot de dung la hai de lop nay da lam",
      [h.split()[0] for h in header if h.startswith("SL")] == ["SL950", "SL951"],
      header)
check("diem toi da lay tu dinh nghia de, khong phai hang so 100",
      any(h.startswith("SL951") and "(80)" in h for h in header), header)
check("de cua lop khac khong lot vao", not any("SL952" in h for h in header), header)
check("co cot tong diem kem diem toi da",
      any("Tổng điểm" in h and "180" in h for h in header), header)
check("bang co du 3 hoc sinh cua lop", len(rows) == 3, [r0[0] for r0 in rows])
check("hoc sinh lop khac khong co trong bang",
      row_of(rows, "Lớp Khác") is None, [r0[0] for r0 in rows])

# Hoc sinh khong nop bai nao van phai co ten: mot bang diem thieu ten mot em la
# mot bang diem sai, va khong co gi bao loi ca.
v = row_of(rows, "Vắng")
check("hoc sinh khong nop bai van co dong", v is not None)
if v:
    check("o diem cua em khong nop bai la TRONG, khong phai 0",
          all(cell == "" for cell in v[3:5]), v)
    check("tong diem cua em khong nop bai la 0", v[5] == "0", v)

g = row_of(rows, "Giỏi")
check("hoc sinh diem tuyet doi co du hai cot", g is not None and g[3] == "100" and g[4] == "80", g)
check("tong diem cong dung", g is not None and g[5] == "180", g)
check("dem dung so bai giai tron ven", g is not None and g[6] == "2", g)

k = row_of(rows, "Khá")
# Nop hai lan cho SL950: phai lay diem CAO NHAT (70), khong phai lan cuoi (70 la
# lan cuoi nen khong phan biet duoc) va cung khong phai lan dau (50).
check("lay diem cao nhat trong cac lan nop", k is not None and k[3] == "70", k)
# Da nop ma 0 diem thi phai la so 0, khac han o trong cua em khong nop bai.
check("da nop ma 0 diem thi ghi 0, khong de trong", k is not None and k[4] == "0", k)
check("so bai giai tron ven khong tinh bai 0 diem", k is not None and k[6] == "0", k)

# --- 22c. Bang ket qua cua ky thi -----------------------------------------
c = db.connect(DB)
with c:
    c.execute("""INSERT INTO contests (name, description, starts_at, ends_at, scoring,
                                        status, created_at)
                 VALUES ('Kiem thu xuat diem','','2026-09-01T00:00:00Z','2026-09-02T00:00:00Z',
                         'ioi','closed',?)""", (db.utc_now(),))
    cid = db.scalar(c, "SELECT id FROM contests WHERE name = 'Kiem thu xuat diem'")
    # Thu tu cot lay theo `contest_problems.ordinal` — tuc la thu tu giao vien
    # tich, khong phai theo ma de. Do la thong tin co nghia: de 1, de 2, de 3.
    c.execute("INSERT INTO contest_problems (contest_id, problem_id, ordinal) VALUES (?,?,1)",
              (cid, pid["SL951"]))
    c.execute("INSERT INTO contest_problems (contest_id, problem_id, ordinal) VALUES (?,?,2)",
              (cid, pid["SL950"]))
    # Diem trong ky thi, khac han diem ngoai ky thi.
    c.execute("""INSERT INTO submissions (problem_id, user_id, contest_id, language, source,
                    status, verdict, score, max_score, time_ms, memory_kb, created_at)
                 VALUES (?,?,?,'cpp17','','done','AC',90,100,1,1,?)""",
              (pid["SL950"], uid["zzgd1"], cid, db.utc_now()))
    c.execute("""INSERT INTO submissions (problem_id, user_id, contest_id, language, source,
                    status, verdict, score, max_score, time_ms, memory_kb, created_at)
                 VALUES (?,?,?,'cpp17','','done','AC',40,80,1,1,?)""",
              (pid["SL951"], uid["zzgd1"], cid, db.utc_now()))
    # Mot em dang cho cham: chua co diem, nhung da tham gia. Phai co ten trong
    # bang — loc theo `done` se lam em do bien mat khoi so diem trong im lang.
    c.execute("""INSERT INTO submissions (problem_id, user_id, contest_id, language, source,
                    status, verdict, score, max_score, time_ms, memory_kb, created_at)
                 VALUES (?,?,?,'cpp17','','pending','',0,0,0,0,?)""",
              (pid["SL950"], uid["zzgd2"], cid, db.utc_now()))
c.close()

r = teacher.get("/teacher/contests/%d/export" % cid)
check("xuat ket qua ky thi tra 200", r.status_code == 200, r.status_code)
header, rows = read_csv(r.data)
check("cot de cua ky thi theo thu tu giao vien tich",
      [h.split()[0] for h in header if h.startswith("SL")] == ["SL951", "SL950"], header)
check("bang ky thi chi co nguoi da tham gia", len(rows) == 2, [x[0] for x in rows])
check("nguoi ngoai ky thi khong co trong bang",
      row_of(rows, "Lớp Khác") is None, [x[0] for x in rows])
gi = row_of(rows, "Giỏi")
# Diem ngoai ky thi cua em nay la 100 va 80; trong ky thi la 90 va 40. Lay nham
# se thoi phong diem cua hoc sinh, va do la loi te nhat ma phep kiem nay phai chan.
check("chi lay diem TRONG ky thi, khong lay diem ca nam",
      gi is not None and gi[3] == "40" and gi[4] == "90", gi)
check("tong diem ky thi dung", gi is not None and gi[5] == "130", gi)
kh = row_of(rows, "Khá")
check("nguoi dang cho cham van co ten trong bang", kh is not None)
# Bai dang cho cham thi o diem phai de **trong**, khong duoc ghi 0. Ghi 0 o day
# la noi voi giao vien rang em nay lam sai het, trong khi su that la chua ai cham
# — va do la cach mat diem cua hoc sinh trong im lang. O trong nghia la "chua co
# diem"; canh bao `bài chưa chấm xong` o tren trang noi vi sao co o trong do.
check("nguoi dang cho cham de trong o diem, khong ghi 0",
      kh is not None and kh[4] == "", kh)
check("nguoi dang cho cham van duoc dem la da nop",
      kh is not None and kh[7] == "1", kh)

check("ky thi khong ton tai tra 404",
      teacher.get("/teacher/contests/99999/export").status_code == 404)

# --- 22d. Quyen va cac duong sai ------------------------------------------
r = student.get("/teacher/classes/export?class=%s" % CLS)
check("hoc sinh khong xuat duoc bang diem", r.status_code in (302, 403), r.status_code)
r = student.get("/teacher/contests/%d/export" % cid)
check("hoc sinh khong xuat duoc ket qua ky thi", r.status_code in (302, 403), r.status_code)

r = teacher.get("/teacher/classes/export?class=KHONGCOLOP", follow_redirects=True)
check("lop khong ton tai thi bao loi, khong tra tep rong",
      "chưa chọn lớp" in text(r), text(r)[:200])

# Ghi de dau phan cach qua chuoi truy van (khong co trong giao dien).
r = teacher.get("/teacher/classes/export?class=%s&sep=," % CLS)
check("ghi de duoc dau phan cach bang ?sep=", b"," in r.data and b";" not in r.data[:200],
      r.data[:80])

# --- 22e. Man hinh phai co nut va phai noi ro khi con bai chua cham --------
page = text(teacher.get("/teacher/classes?class=%s" % CLS))
check("trang lop hoc co nut xuat bang diem", "Xuất bảng điểm" in page)
check("nut tro dung tuyen duong", "/teacher/classes/export?class=9Z" in page, page[:100])
check("co canh bao khi con bai chua cham", "bài chưa chấm xong" in page)

page = text(teacher.get("/teacher/contests"))
check("trang ky thi co nut xuat ket qua", "Xuất kết quả" in page)
check("trang ky thi canh bao bai chua cham", "bài chưa chấm xong" in page)

# --- 22f. De moi nop va chua cham xong van phai co cot ---------------------
# Truong hop de bi mat: mot de ma **ca lop** moi nop va chua cham xong. Neu cot
# duoc suy ra tu cac bai `done` thi de do khong co cot nao — no bien mat khoi so
# diem, va khong co gi bao loi ngoai mot con so o trang khac.
c = db.connect(DB)
with c:
    c.execute("""INSERT INTO problems (code, name, statement, difficulty, topic,
                    time_limit_ms, memory_limit_mb, points_mode, status, created_at, updated_at)
                 VALUES ('SL953','Đề mới chưa chấm','', 'co-ban','', 1000, 256, 'even',
                         'live', ?, ?)""", (db.utc_now(), db.utc_now()))
    p953 = db.scalar(c, "SELECT id FROM problems WHERE code = 'SL953'")
    c.execute("INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points, note)"
              " VALUES (?,1,'1\n','',1,0,'')", (p953,))
    c.execute("""INSERT INTO submissions (problem_id, user_id, contest_id, language, source,
                    status, verdict, score, max_score, time_ms, memory_kb, created_at)
                 VALUES (?,?,NULL,'cpp17','','pending','',0,0,0,0,?)""",
              (p953, uid["zzgd1"], db.utc_now()))
c.close()

header, rows = read_csv(teacher.get("/teacher/classes/export?class=%s" % CLS).data)
check("de chi co bai dang cho cham van co cot, khong bi mat",
      any(h.startswith("SL953") for h in header), header)
p953_col = next(i for i, h in enumerate(header) if h.startswith("SL953"))
check("o diem cua de chua cham la trong, khong phai 0",
      row_of(rows, "Giỏi")[p953_col] == "", row_of(rows, "Giỏi"))
page = text(teacher.get("/teacher/classes?class=%s" % CLS))
check("trang lop canh bao bai chua cham sau khi co de moi", "bài chưa chấm xong" in page)

# Don sach: xoa de, xoa ky thi, xoa tai khoan tam. Xoa theo thu tu de khong
# vuong khoa ngoai.
c = db.connect(DB)
with c:
    c.execute("DELETE FROM contests WHERE name = 'Kiem thu xuat diem'")
    for code in ("SL950", "SL951", "SL952", "SL953"):
        c.execute("DELETE FROM problems WHERE code = ?", (code,))
    c.execute("DELETE FROM users WHERE username LIKE 'zzgd%'")
c.close()

# ===========================================================================
# Phần 24 — nhờ AI viết bộ sinh và lời giải mẫu
# ===========================================================================
# Không bài nào ở đây gọi ra Internet. Phần thuần của `aiwriter` được kiểm thẳng,
# còn tuyến đường được kiểm bằng một hàm gọi AI **giả**: gọi thật một mô hình ngôn
# ngữ vừa chậm vừa không ổn định, và sẽ làm bộ bài kiểm thử phụ thuộc vào mạng —
# đúng thứ mà một bộ bài kiểm thử không nên phụ thuộc.
print("\n=== 24. Nho AI viet bo sinh va loi giai mau ===")

# Hai chuỗi này phải khác nhau ở một chỗ dễ nhận ra, vì bài kiểm quan trọng nhất
# ở đây là **không được lẫn ô**: bộ sinh vào ô bộ sinh, lời giải vào ô lời giải.
GEN_OK = "// BO SINH GIA\nint main(int argc, char** argv) {\n  srand(atoi(argv[1]));\n}"
SOL_OK = "// LOI GIAI GIA\nint main() {\n  return 0;\n}"

# --- 24a. Tach hai khoi ma nguon tu cau tra loi ----------------------------
g, s = aiwriter.extract_blocks("===GEN===\n" + GEN_OK + "\n===SOL===\n" + SOL_OK + "\n")
check("24a tach duoc theo moc", g == GEN_OK and s == SOL_OK, (g, s))

g, s = aiwriter.extract_blocks(
    "```cpp\n" + GEN_OK + "\n```\n===SOL===\n```cpp\n" + SOL_OK + "\n```")
check("24a bo duoc hang rao ``` quanh moi khoi", g == GEN_OK and s == SOL_OK, (g, s))

# Dạng câu trả lời hay gặp nhất, và là dạng đã làm hỏng một bản trước: mô hình
# chào hỏi trước rồi mới vào mã. Nếu chỉ tìm mốc ở **đầu chuỗi** thì mất cả hai
# khối, và lỗi hiện ra là "không tách được" — đọc không ra là vì lời dẫn.
g, s = aiwriter.extract_blocks(
    "Dưới đây là hai chương trình bạn cần:\n\n===GEN===\n" + GEN_OK +
    "\n===SOL===\n" + SOL_OK + "\n\nChúc thầy cô dạy tốt!")
check("24a bo qua duoc loi dan truoc va sau", g == GEN_OK and s == SOL_OK, (g, s))

# Mã trần rồi thêm một câu kết: không có ``` để dựa vào nên phải dựa vào cấu trúc.
# Không cắt thì câu kết nằm luôn trong ô lời giải mẫu, và trình dịch báo lỗi cú
# pháp ở dòng cuối — đọc không ra là do đâu.
g, s = aiwriter.extract_blocks("===GEN===\n" + GEN_OK + "\n===SOL===\n" + SOL_OK +
                               "\n\nChúc thầy cô dạy tốt!")
check("24a cat duoc loi ket sau ma tran", g == GEN_OK and s == SOL_OK, (g, s))

# ...và không được cắt nhầm. Một khai báo như `struct Point { ... };` đóng ngoặc về
# 0 **trước** `main`, nên cách đếm độ sâu ngoặc nhọn sẽ cắt cụt chương trình ở đây.
STRUCT = "struct Point { int x, y; };\n\nint main() {\n  return 0;\n}"
g, s = aiwriter.extract_blocks("===GEN===\nint main() { return 0; }\n===SOL===\n" + STRUCT)
check("24a khong cat cut chuong trinh co struct truoc main", s == STRUCT, repr(s))

g, s = aiwriter.extract_blocks("  ===GEN===  \n" + GEN_OK + "\n  ===SOL===  \n" + SOL_OK)
check("24a chiu duoc khoang trang quanh moc", g == GEN_OK and s == SOL_OK, (g, s))

# Không có mốc nhưng đúng hai khối: thứ tự gần như luôn là bộ sinh rồi lời giải.
g, s = aiwriter.extract_blocks("```cpp\n" + GEN_OK + "\n```\n\n```cpp\n" + SOL_OK + "\n```")
check("24a khong moc nhung dung hai khoi thi van nhan",
      g == GEN_OK and s == SOL_OK, (g, s))

for label, bad in (
    ("rong", ""),
    ("chi khoang trang", "   \n\n  "),
    ("chi mot khoi", "```cpp\n" + GEN_OK + "\n```"),
    ("ba khoi", "```cpp\na\n```\n```cpp\nb\n```\n```cpp\nc\n```"),
    ("co GEN nhung thieu SOL", "===GEN===\n" + GEN_OK),
    ("chi co van xuoi", "Toi khong viet duoc bai nay."),
):
    try:
        aiwriter.extract_blocks(bad)
        check("24a tu choi khi %s" % label, False, "da nhan nham")
    except aiwriter.AIError:
        check("24a tu choi khi %s" % label, True)

# --- 24b. Cau hoi gui di phai mang du gioi han cua de ----------------------
msgs = aiwriter.build_messages("Đếm số nguyên tố <= n.", 1500, 512, 12)
check("24b co dung hai thong diep", len(msgs) == 2, len(msgs))
check("24b thong diep dau la chi dan he thong", msgs[0]["role"] == "system")
check("24b de bai nam trong cau hoi", "Đếm số nguyên tố <= n." in msgs[1]["content"])
check("24b gui kem gioi han thoi gian cua de", "1500 ms" in msgs[1]["content"],
      msgs[1]["content"])
check("24b gui kem gioi han bo nho cua de", "512 MB" in msgs[1]["content"])
check("24b gui kem so bo can sinh", "12 bộ" in msgs[1]["content"])
check("24b chi dan noi ro argv[1]", "argv[1]" in msgs[0]["content"])
check("24b chi dan noi ro stdin va stdout",
      "stdin" in msgs[0]["content"] and "stdout" in msgs[0]["content"])
check("24b chi dan noi ro moc tra loi",
      "===GEN===" in msgs[0]["content"] and "===SOL===" in msgs[0]["content"])
# Mã dài quá thì bị cắt giữa chừng, nên chỉ dẫn phải yêu cầu viết gọn. Không có
# câu này thì bộ sinh kèm chú thích dài chiếm phần lớn hạn mức token.
check("24b chi dan yeu cau viet gon de khong bi cat",
      "GỌN" in msgs[0]["content"])

# --- 24c. Qua dung tuyen duong, voi ham goi AI gia -------------------------
STUB = {"gen": GEN_OK, "sol": SOL_OK, "calls": 0, "statement": None, "kwargs": None}


def stub_write(statement, **kw):
    STUB["calls"] += 1
    STUB["statement"] = statement
    STUB["kwargs"] = kw
    return STUB["gen"], STUB["sol"]


def count_tests():
    c = db.connect(DB)
    try:
        return db.scalar(c, "SELECT COUNT(*) FROM tests")
    finally:
        c.close()


def textarea(page, name):
    """Lấy nội dung một `<textarea name="...">` trong trang trả về."""
    m = re.search(r'name="%s"[^>]*>(.*?)</textarea>' % name, page, re.S)
    return m.group(1) if m else None


_real_write = aiwriter.write
aiwriter.write = stub_write
app.config["AI_KEY"] = "khoa-gia"
# SL001 chứ không phải SL002: SL002 bị xoá ở mục kiểm tra "xoá đề" phía trên, nên
# dùng nó ở đây sẽ nhận 404 và mọi bài kiểm của mục này đạt một cách giả tạo.
TESTS_URL = "/teacher/problems/SL001/tests"

try:
    tok = token(teacher, TESTS_URL)
    n_before = count_tests()

    resp = teacher.post(TESTS_URL, data={"action": "ai_write",
                                         "statement": "Đếm số nguyên tố nhỏ hơn n.",
                                         "_csrf": tok})
    page = text(resp)
    check("24c tuyen duong tra ve 200, khong chuyen huong",
          resp.status_code == 200, resp.status_code)
    check("24c goi AI dung mot lan", STUB["calls"] == 1, STUB["calls"])
    # Đây là bài kiểm quan trọng nhất của mục này: hai ô không được lẫn nhau.
    check("24c ma bo sinh nam dung o gen_source",
          (textarea(page, "gen_source") or "").strip() == GEN_OK,
          repr(textarea(page, "gen_source"))[:90])
    check("24c ma loi giai nam dung o sol_source",
          (textarea(page, "sol_source") or "").strip() == SOL_OK,
          repr(textarea(page, "sol_source"))[:90])
    check("24c de bai vua dan duoc giu lai tren trang",
          (textarea(page, "statement") or "").strip() == "Đếm số nguyên tố nhỏ hơn n.",
          repr(textarea(page, "statement"))[:90])
    # Không được tự sinh dữ liệu: mã do AI viết chưa ai đọc.
    check("24c KHONG tu them bo du lieu nao", count_tests() == n_before,
          (n_before, count_tests()))
    check("24c gui kem gioi han that cua de",
          STUB["kwargs"].get("time_limit_ms") == 1000
          and STUB["kwargs"].get("memory_limit_mb") == 256, STUB["kwargs"])

    # Ô đề bài để trống thì lấy đề bài đã lưu của đề, không bắt dán lại.
    STUB["statement"] = None
    teacher.post(TESTS_URL, data={"action": "ai_write", "statement": "", "_csrf": tok})
    check("24c o de bai trong thi lay de bai da luu cua de",
          STUB["statement"] == "Đếm số nguyên tố nhỏ hơn n.", repr(STUB["statement"]))

    # Số bộ phải bị kẹp trong trần, nếu không giáo viên gõ 999 là chờ hết ngân sách.
    teacher.post(TESTS_URL, data={"action": "ai_write", "statement": "Đề",
                                  "count": "999", "_csrf": tok})
    check("24c so bo duoc kep trong tran", STUB["kwargs"]["count"] == gendata.MAX_COUNT,
          STUB["kwargs"]["count"])

    # Đề bài quá dài phải bị chặn **trước** khi gọi: chờ hai chục giây rồi mới
    # biết là dán nhầm tệp là kiểu lỗi tốn thời gian nhất.
    STUB["calls"] = 0
    resp = teacher.post(TESTS_URL, data={
        "action": "ai_write", "statement": "x" * (aiwriter.MAX_STATEMENT_CHARS + 1),
        "_csrf": tok})
    check("24c de bai qua dai thi khong goi AI", STUB["calls"] == 0, STUB["calls"])
    check("24c de bai qua dai thi noi ro gioi han", "dài quá" in text(resp))

    # Đường lỗi: thông báo của AI phải hiện cho giáo viên, và đề bài vừa dán phải
    # còn nguyên — bắt dán lại sau khi chờ là kiểu làm phiền khiến người ta thôi dùng.
    def stub_fail(statement, **kw):
        raise aiwriter.AIError("Khoá API không đúng hoặc đã hết hạn (401).")

    aiwriter.write = stub_fail
    resp = teacher.post(TESTS_URL, data={"action": "ai_write", "statement": "Đề bài thử",
                                         "_csrf": tok})
    page = text(resp)
    check("24c loi cua AI hien ra, khong dung trang loi",
          resp.status_code == 200 and "hết hạn" in page, resp.status_code)
    check("24c de bai vua dan van con sau khi loi",
          (textarea(page, "statement") or "").strip() == "Đề bài thử",
          repr(textarea(page, "statement"))[:90])

    # Lỗi "không tách được" xảy ra **sau khi** đã nhận được câu trả lời: mã nguồn
    # vẫn nằm trong đó, chỉ là mô hình đánh dấu khác đi. Vứt đi thì giáo viên chờ
    # 13 giây rồi nhận về con số không — chuyện đã xảy ra thật trên máy chủ.
    RAW = "Dưới đây là mã:\n```cpp\nint main(){ return 0; }\n```"

    def stub_unparsed(statement, **kw):
        raise aiwriter.AIError("Không tách được hai chương trình từ câu trả lời.",
                               raw=RAW)

    aiwriter.write = stub_unparsed
    resp = teacher.post(TESTS_URL, data={"action": "ai_write", "statement": "Đề bài thử",
                                         "_csrf": tok})
    page = text(resp)
    # Chuỗi nhận biết phải nằm trong **thông báo**, không phải trong nhãn của ô:
    # "Bộ sinh dữ liệu" là nhãn có sẵn ở mọi lần tải trang, kiểm bằng nó thì đạt
    # một cách giả tạo.
    check("24c khong tach duoc thi van giu cau tra loi cua AI",
          RAW in (textarea(page, "gen_source") or ""),
          repr(textarea(page, "gen_source"))[:120])
    check("24c khong tach duoc thi noi ro da dat vao o nao",
          "vẫn còn nguyên trong ô" in page)
    check("24c khong tach duoc thi de bai van con",
          (textarea(page, "statement") or "").strip() == "Đề bài thử")

    # Lỗi **không** kèm câu trả lời (bị cắt vì hết token) thì ô phải để trống:
    # mã thiếu một nửa đưa vào ô dễ bị tưởng là mã hoàn chỉnh rồi đi tìm một lỗi
    # dịch không có thật.
    def stub_truncated(statement, **kw):
        raise aiwriter.AIError("AI viết dài quá trần 8000 token nên bị cắt giữa chừng.")

    aiwriter.write = stub_truncated
    resp = teacher.post(TESTS_URL, data={"action": "ai_write", "statement": "Đề bài thử",
                                         "_csrf": tok})
    page = text(resp)
    check("24c bi cat thi khong do ma do dang vao o",
          not (textarea(page, "gen_source") or "").strip(),
          repr(textarea(page, "gen_source"))[:120])
    check("24c bi cat thi khong hua la da giu cau tra loi",
          "vẫn còn nguyên trong ô" not in page)
    aiwriter.write = stub_write

    # Đề không có đề bài và ô cũng để trống: phải nói rõ, và không tốn một lần gọi.
    c = db.connect(DB)
    with c:
        c.execute("""INSERT INTO problems (code, name, statement, difficulty, topic,
                        time_limit_ms, memory_limit_mb, points_mode, status, created_at, updated_at)
                     VALUES ('SL954','Đề trống','', 'co-ban','', 1000, 256, 'even',
                             'draft', ?, ?)""", (db.utc_now(), db.utc_now()))
    c.close()
    STUB["calls"] = 0
    resp = teacher.post("/teacher/problems/SL954/tests",
                        data={"action": "ai_write", "statement": "", "_csrf": tok})
    check("24c khong co de bai thi khong goi AI", STUB["calls"] == 0, STUB["calls"])
    check("24c khong co de bai thi noi ro", "Chưa có đề bài" in text(resp))

    # Học sinh không được dùng đường này. Lấy token CSRF của chính phiên học sinh:
    # dùng token của giáo viên thì yêu cầu bị chặn vì CSRF trước, và bài kiểm sẽ
    # đạt một cách giả tạo.
    stok = token(student, "/")
    resp = student.post(TESTS_URL, data={"action": "ai_write", "statement": "Đề",
                                         "_csrf": stok})
    check("24c hoc sinh khong nho duoc AI viet de",
          resp.status_code in (302, 403), resp.status_code)
finally:
    aiwriter.write = _real_write
    app.config["AI_KEY"] = ""

c = db.connect(DB)
with c:
    c.execute("DELETE FROM problems WHERE code = 'SL954'")
c.close()

# --- 24d. Chua cau hinh khoa thi the do khong duoc dung ra -----------------
page = text(teacher.get(TESTS_URL))
check("24d chua co khoa thi khong hien the nho AI", "Nhờ AI viết" not in page)
check("24d nhung the sinh du lieu thu cong van con",
      "Sinh dữ liệu từ lời giải mẫu" in page)

# --- 24e. Bi cat vi het token: chua chac da hong ---------------------------
# `finish_reason == "length"` chỉ nói mô hình dừng sớm, **không** nói hai chương
# trình bị thiếu. Bản trước báo lỗi ngay khi thấy `length`, nên nó từ chối cả
# những câu trả lời đã đủ hai chương trình — và đó là lỗi đã xảy ra thật.
import json as _json                      # noqa: E402
import urllib.request as _urlreq          # noqa: E402


class _FakeResp:
    def __init__(self, payload):
        # Nhan ca dict (JSON mot lan) lan chuoi tho (SSE) — hai dang ma endpoint
        # that tra ve tuy theo mo hinh.
        if isinstance(payload, bytes):
            self._body = payload
        elif isinstance(payload, str):
            self._body = payload.encode()
        else:
            self._body = _json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ai_reply(content, finish):
    return {"choices": [{"finish_reason": finish,
                         "message": {"role": "assistant", "content": content}}]}


def _with_reply(payload, capture=None):
    """Chay `aiwriter.write` voi mot cau tra loi gia. Tra ve ``(ket qua, loi)``."""
    real = _urlreq.urlopen

    def _open(req, timeout=None):
        if capture is not None:
            capture["body"] = req.data
        return _FakeResp(payload)

    _urlreq.urlopen = _open
    try:
        return aiwriter.write("Đề bài thử", base="https://vidu.test/v1",
                              key="khoa-gia", model="model-gia"), None
    except aiwriter.AIError as exc:
        return None, exc
    finally:
        _urlreq.urlopen = real


CAPTURED = {}
# Đủ hai chương trình rồi mới lan man cho tới lúc hết chỗ: **dùng được**.
got, err = _with_reply(_ai_reply(
    "Dưới đây là hai chương trình:\n\n===GEN===\n" + GEN_OK +
    "\n===SOL===\n" + SOL_OK + "\n\nChúc thầy cô dạy tốt!", "length"), CAPTURED)
check("24e bi cat nhung du hai chuong trinh thi van nhan",
      err is None and got == (GEN_OK, SOL_OK), (err, got))

# Chương trình viết gọn trên một dòng **không có dòng `}` nào cả**, mà vẫn đúng.
# Đây là lý do việc nhận ra "bị cắt" phải dựa vào số ngoặc chứ không dựa vào
# "có dòng `}` hay không".
got, err = _with_reply(_ai_reply(
    "===GEN===\nint main(){srand(1);}\n===SOL===\nint main(){return 0;}", "length"))
check("24e chuong trinh viet tren mot dong van duoc nhan",
      err is None and got == ("int main(){srand(1);}", "int main(){return 0;}"),
      (err, got))

# Và hạn mức token phải **thật sự** được gửi đi: đổi hằng số mà quên gửi thì
# việc nâng trần không có tác dụng gì.
sent = _json.loads(CAPTURED.get("body") or b"{}")
check("24e han muc token da nang duoc gui trong yeu cau",
      sent.get("max_tokens") == aiwriter.MAX_TOKENS, sent.get("max_tokens"))
check("24e han muc token thuc su rong hon muc cu 4000",
      aiwriter.MAX_TOKENS > 4000, aiwriter.MAX_TOKENS)
# Doi mo hinh ma khong gui ten mo hinh di thi moi thu van "chay" — chi la chay
# bang mo hinh cu. Phai kiem ten mo hinh co mat trong yeu cau.
check("24e ten mo hinh duoc gui dung trong yeu cau",
      sent.get("model") == "model-gia", sent.get("model"))
check("24e co mo hinh mac dinh", bool(aiwriter.DEFAULT_MODEL), aiwriter.DEFAULT_MODEL)

# Thiếu nửa cuối của khối thứ hai: phải báo lỗi, và lỗi phải nói rõ là bị cắt.
got, err = _with_reply(_ai_reply(
    "===GEN===\n" + GEN_OK + "\n===SOL===\nint main() {", "length"))
check("24e thieu chuong trinh thi bao loi", err is not None and got is None, got)
check("24e loi noi ro bi cat vi het token",
      err is not None and str(aiwriter.MAX_TOKENS) in str(err), str(err)[:90])

# Không bị cắt mà vẫn không tách được: thông báo phải **khác**, không được đổ
# cho việc hết token — nếu không thì giáo viên đi tăng trần token vô ích.
got, err = _with_reply(_ai_reply("Tôi không viết được bài này.", "stop"))
check("24e khong tach duoc thi bao loi", err is not None and got is None, got)
check("24e khong do loi cho viec het token",
      err is not None and "hết token" not in str(err), str(err)[:90])

# --- 24f. Doc duoc ca hai dang phan hoi ------------------------------------
# Cung mot dia chi, cung mot yeu cau, nhung co mo hinh tra JSON mot lan con co mo
# hinh tra **SSE** (tung dong `data: {...}`, moi dong mot manh `delta.content`).
# Chi doc mot dang thi mo hinh kia hong voi thong bao "khong phai JSON" — trong
# khi du lieu van nguyen ven, chi la dong goi khac.
SSE = (
    'data: {"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"index":0,"delta":{"content":"===GEN===\\n"}}]}\n\n'
    'data: {"choices":[{"index":0,"delta":{"content":"int main(){}\\n"}}]}\n\n'
    'data: {"choices":[{"index":0,"delta":{"content":"===SOL===\\nint main(){}"}}]}\n\n'
    'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    'data: [DONE]\n\n'
)
parsed = aiwriter._parse_body(SSE)
check("24f gom duoc cac manh SSE thanh mot cau tra loi",
      parsed["choices"][0]["message"]["content"]
      == "===GEN===\nint main(){}\n===SOL===\nint main(){}",
      repr(parsed["choices"][0]["message"]["content"])[:90])
check("24f doc duoc finish_reason trong SSE",
      parsed["choices"][0]["finish_reason"] == "stop",
      parsed["choices"][0]["finish_reason"])
check("24f van doc duoc JSON mot lan",
      aiwriter._parse_body('{"choices":[{"finish_reason":"stop",'
                           '"message":{"content":"x"}}]}')["choices"][0]["message"]["content"]
      == "x")

# Và đầu-cuối: một phản hồi SSE phải đi hết được đường ống, không chỉ hàm tách.
got, err = _with_reply(SSE)
check("24f phan hoi SSE di het duoc duong ong",
      err is None and got == ("int main(){}", "int main(){}"), (err, got))

# --- 24g. Loi tam thoi thi tu thu lai --------------------------------------
# Mô hình mặc định nhanh gấp ba lần mô hình cũ nhưng **cứ vài lần liên tiếp lại
# bị chặn**: đo 5 lần liên tiếp cùng một đề thì 3 lần qua, 2 lần nhận 503 (bên
# trong là 403 của nhà cung cấp — hết lượt trong chốc lát, không phải khoá sai).
# Lần gọi ngay sau đó qua bình thường, nên chỗ sửa đúng là thử lại, không phải
# đổi lại mô hình chậm.
import io as _io                           # noqa: E402
import urllib.error as _urlerr             # noqa: E402

V1 = "https://vidu.test/v1/chat/completions"


def _http(code, body="nha cung cap tu choi", headers=None):
    return _urlerr.HTTPError(V1, code, "loi", headers or {},
                             _io.BytesIO(body.encode()))


def _seq(*outcomes):
    """Chay `write` voi mot chuoi ket qua theo thu tu. Tra ``(kq, loi, cac_timeout)``.

    Lần nào hết chuỗi thì lặp lại kết quả cuối — đủ để mô tả "chặn liên tục".
    """
    real = _urlreq.urlopen
    calls = []

    def _open(req, timeout=None):
        calls.append(timeout)
        item = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return _FakeResp(item)

    _urlreq.urlopen = _open
    try:
        return aiwriter.write("Đề bài thử", base="https://vidu.test/v1",
                              key="khoa-gia", model="model-gia"), None, calls
    except aiwriter.AIError as exc:
        return None, exc, calls
    finally:
        _urlreq.urlopen = real


GOOD = _ai_reply("===GEN===\n" + GEN_OK + "\n===SOL===\n" + SOL_OK, "stop")

# Bỏ thời gian nghỉ thật (1 s + 3 s) — bài kiểm không nên chờ.
_saved_delays = aiwriter.RETRY_DELAYS
_saved_total = aiwriter.MAX_TOTAL_SECONDS
aiwriter.RETRY_DELAYS = (0.0, 0.0)

got, err, calls = _seq(_http(503), GOOD)
check("24g gap 503 thi tu thu lai va lan sau qua",
      err is None and got == (GEN_OK, SOL_OK), (err, got))
check("24g 503 o lan dau thi goi dung hai lan", len(calls) == 2, len(calls))

got, err, calls = _seq(_http(503))
check("24g 503 lien tuc thi bao loi chu khong tra ve rong",
      got is None and err is not None, got)
check("24g 503 lien tuc thi thu dung ba lan", len(calls) == 3, len(calls))
check("24g loi cuoi noi ro da thu may lan", "3 lần" in str(err), str(err)[:120])
check("24g loi cuoi giu chi tiet cua lan cuoi", "503" in str(err), str(err)[:200])

# 403 trực tiếp **không** thử lại: khoá sai thì ba lần gọi chỉ làm giáo viên chờ
# thêm một phút mà kết quả không đổi. Đây là ranh giới giữa `_Transient` và
# `AIError`, nên phải kiểm cả hai phía.
got, err, calls = _seq(_http(403, "blocked"))
check("24g 403 thi khong thu lai", len(calls) == 1, len(calls))
check("24g 403 thi van bao loi doc duoc", err is not None and "403" in str(err),
      str(err)[:90])
check("24g 403 thi khong do loi cho viec thu lai nhieu lan",
      "đã thử" not in str(err), str(err)[:90])

got, err, calls = _seq(_http(401, "bad key"))
check("24g 401 thi khong thu lai", len(calls) == 1, len(calls))

# 429 là "hết lượt trong chốc lát" — thử lại được.
got, err, calls = _seq(_http(429), GOOD)
check("24g 429 thi thu lai duoc", err is None and len(calls) == 2, (err, calls))

# Lỗi mạng cũng thử lại được.
got, err, calls = _seq(_urlerr.URLError("mang chap chon"), GOOD)
check("24g loi mang thi thu lai duoc", err is None and len(calls) == 2, (err, calls))

# Hợp đồng với tầng trên: `app.py` chỉ bắt `aiwriter.AIError`. Lỗi tạm thời lọt
# ra ngoài mà không phải `AIError` thì giáo viên nhận trang lỗi 500.
check("24g loi tam thoi van la AIError de tuyen duong bat duoc",
      issubclass(aiwriter._Transient, aiwriter.AIError))

# Ngân sách thời gian: đây là cơ chế chống 502. Ba lần × 90 giây = 270 giây, vượt
# thời hạn 120 giây của gunicorn, nên thời gian chờ **từng lần** phải bị cắt theo
# phần ngân sách còn lại.
aiwriter.MAX_TOTAL_SECONDS = 5
got, err, calls = _seq(_http(503))
check("24g thoi gian cho moi lan bi cat theo ngan sach con lai",
      bool(calls) and max(calls) <= 5, calls)
aiwriter.MAX_TOTAL_SECONDS = 0
got, err, calls = _seq(_http(503))
check("24g ngan sach can thi khong goi them lan nao", len(calls) == 0, len(calls))
check("24g ngan sach can thi van bao loi doc duoc",
      err is not None and "tạm thời" in str(err), str(err)[:90])

aiwriter.MAX_TOTAL_SECONDS = _saved_total
aiwriter.RETRY_DELAYS = _saved_delays

# --- 24h. Het han muc: cho theo dung con so may chu noi ----------------------
# Bài học đắt nhất của vòng này. Bản đầu em đoán "chặn vài giây rồi hết" nên đặt
# thử lại sau 1 s và 3 s. Đo lại thì **không cứu được lần nào** (5 lần gọi, có
# thử lại, vẫn 3/5) — vì máy chủ nói thẳng lý do:
#
#   HTTP 503 {"error":{"message":"[...claude-opus-4-8] [403]:
#            HTTP 403 (reset after 1m 29s)"}}
#
# Chặn đủ 89 giây, và cùng lúc đó `oc/space-bunny-free` qua 10/10 yêu cầu liên
# tiếp. Nghĩa là hạn mức **của riêng mô hình**, reset theo cửa sổ. Đoán sai chỗ
# này thì hoặc là chờ vô ích, hoặc là bỏ một mô hình đúng chỉ vì dùng sai cách.
check("24h doc duoc 'reset after 1m 29s'", aiwriter._reset_after_seconds(
    "HTTP 403 (reset after 1m 29s)") == 89)
check("24h doc duoc 'reset after 40s'",
      aiwriter._reset_after_seconds("HTTP 403 (reset after 40s)") == 40)
check("24h doc duoc 'reset after 2m 0s'",
      aiwriter._reset_after_seconds("(reset after 2m 0s)") == 120)
check("24h khong co thi tra None",
      aiwriter._reset_after_seconds("provider tu choi", "") is None)

check("24h doc so giay thanh cau doc duoc", aiwriter._human_seconds(40) == "40 giây",
      aiwriter._human_seconds(40))
check("24h doc so giay thanh phut va giay",
      aiwriter._human_seconds(89) == "1 phút 29 giây", aiwriter._human_seconds(89))
check("24h phut chan thi khong hien 0 giay",
      aiwriter._human_seconds(120) == "2 phút", aiwriter._human_seconds(120))


class _Clock:
    """Bọc `time` để ghi lại các lần `sleep` mà không phải chờ thật."""

    def __init__(self, real):
        self._real = real
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)

    def __getattr__(self, name):
        return getattr(self._real, name)


BLOCK_89 = '{"error":{"message":"[claude-opus-4-8] [403]: HTTP 403 (reset after 1m 29s)"}}'
BLOCK_5 = '{"error":{"message":"[claude-opus-4-8] [403]: HTTP 403 (reset after 5s)"}}'

_saved_clock = aiwriter.time
_saved_max_wait = aiwriter.MAX_WAIT_SECONDS
clock = _Clock(_saved_clock)
aiwriter.time = clock
aiwriter.RETRY_DELAYS = (0.0, 0.0)

# Chặn 89 giây: **không** chờ. Bắt giáo viên nhìn vòng xoay một phút rưỡi mà còn
# ăn hết ngân sách của cả yêu cầu; báo thẳng số còn lại thì hơn.
got, err, calls = _seq(_http(503, BLOCK_89))
check("24h chan 89 giay thi khong ngoi cho", len(calls) == 1, len(calls))
check("24h chan 89 giay thi khong sleep lan nao", clock.slept == [], clock.slept)
check("24h loi noi ro con bao lau nua moi dung lai duoc",
      err is not None and "1 phút 29 giây" in str(err), str(err)[:140])
check("24h loi goi dung ten chuyen: het han muc",
      err is not None and "hạn mức" in str(err), str(err)[:90])

# Chặn 5 giây: đủ ngắn để chờ tại chỗ, và chờ **đúng** con số đó cộng một giây
# đồng hồ lệch — không phải một giá trị đoán.
clock.slept = []
got, err, calls = _seq(_http(503, BLOCK_5), GOOD)
check("24h chan ngan thi cho roi thu lai va qua",
      err is None and got == (GEN_OK, SOL_OK), (err, got))
check("24h cho dung so giay may chu noi, cong mot",
      clock.slept == [6.0], clock.slept)
check("24h chan ngan thi chi goi hai lan", len(calls) == 2, len(calls))

# Chặn ngắn nhưng ngân sách không còn chỗ: vẫn phải bỏ, không được chờ quá.
clock.slept = []
aiwriter.MAX_TOTAL_SECONDS = 5
got, err, calls = _seq(_http(503, BLOCK_5), GOOD)
check("24h ngan sach khong du cho thoi gian cho thi bo",
      len(calls) == 1 and clock.slept == [], (len(calls), clock.slept))
aiwriter.MAX_TOTAL_SECONDS = _saved_total

# Máy chủ chỉ gửi tiêu đề chuẩn `Retry-After` (đơn vị giây) chứ không nói trong
# thân: vẫn phải đọc.
clock.slept = []
got, err, calls = _seq(_http(503, "qua tai", {"Retry-After": "7"}), GOOD)
check("24h doc duoc tieu de Retry-After",
      err is None and clock.slept == [8.0], (err, clock.slept))

# Không có con số nào thì mới dùng tới giá trị đoán.
clock.slept = []
got, err, calls = _seq(_http(503, "qua tai khong noi gi"), GOOD)
check("24h khong co con so thi dung gia tri doan",
      err is None and clock.slept == [0.0], clock.slept)

aiwriter.MAX_WAIT_SECONDS = _saved_max_wait
aiwriter.RETRY_DELAYS = _saved_delays
aiwriter.time = _saved_clock

shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print("DAT: %d   SAI: %d" % (len(OK), len(BAD)))
if BAD:
    print("\nCac bai sai:")
    for b in BAD:
        print("  -", b)
sys.exit(1 if BAD else 0)
