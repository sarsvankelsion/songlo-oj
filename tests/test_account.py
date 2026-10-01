#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kiểm thử trang cá nhân: đổi mật khẩu, ảnh đại diện, giới thiệu, và migration.

Chạy từ thư mục gốc dự án:/n/n    python tests/test_account.py

Dùng CSDL tạm trong thư mục tạm và tự xoá sau khi chạy — không chạm vào dữ liệu
thật. Cần Flask và Pillow.

Đây là bộ kiểm thử duy nhất của dự án. Nó tồn tại vì trang cá nhân là phần đầu
tiên nhận **tệp do người dùng tải lên**, và đó là loại tính năng mà kiểm tra bằng
mắt không đủ: một tệp PHP đổi tên thành `.png` trông y hệt một ảnh trên giao diện.
"""
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import auth, db                       # noqa: E402
from server.app import create_app                 # noqa: E402

OK = []
BAD = []


def check(label, cond, extra=""):
    (OK if cond else BAD).append(label)
    print("  %s %s%s" % ("ok  " if cond else "SAI ", label,
                         ("  <- " + str(extra)) if extra and not cond else ""))


def make_image(w=800, h=600, fmt="JPEG", color=(200, 60, 60)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, fmt)
    return buf.getvalue()


def make_png_bomb(w=50000, h=50000):
    """PNG that khai bao kich thuoc khong lo nhung chi chua vai byte du lieu.

    Sua thang truong width/height trong khoi IHDR: 8 byte chu ky + 4 do dai +
    4 loai khoi = 16, roi tới 4 byte rong va 4 byte cao.
    """
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buf, "PNG")
    raw = bytearray(buf.getvalue())
    raw[16:20] = w.to_bytes(4, "big")
    raw[20:24] = h.to_bytes(4, "big")
    # Phai tinh lai CRC cua khoi IHDR, khong thi Pillow bao loi CRC truoc khi kip
    # kiem tra kich thuoc — va bai kiem thu se "dat" vi sai ly do.
    crc = zlib.crc32(bytes(raw[12:29])) & 0xFFFFFFFF
    raw[29:33] = crc.to_bytes(4, "big")
    return bytes(raw)


TMP = tempfile.mkdtemp(prefix="songlo-account-test-")
DB = os.path.join(TMP, "songlo.db")
print("CSDL tam:", DB)

app = create_app({"TESTING": True, "DATABASE": DB, "SECRET_KEY": "test",
                  "WTF_CSRF_ENABLED": False})

# ---------------------------------------------------------------- du lieu mau
conn = db.connect(DB)
with conn:
    conn.execute(
        """INSERT INTO users (username, full_name, class_name, role, password_hash,
                              is_active, must_change_password, created_at)
           VALUES (?,?,?,?,?,1,1,?)""",
        ("an.nguyen9a", "Nguyễn Văn An", "9A", "student",
         auth.hash_password("matkhaucu1"), db.utc_now()),
    )
    conn.execute(
        """INSERT INTO users (username, full_name, class_name, role, password_hash,
                              is_active, must_change_password, created_at)
           VALUES (?,?,?,?,?,1,0,?)""",
        ("thumai", "Trần Thị Thu Mai", "", "teacher",
         auth.hash_password("giaovien1"), db.utc_now()),
    )
conn.close()


def login(client, username, password):
    page = client.get("/login")
    token = page.data.decode("utf-8", "replace")
    import re
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', token)
    return client.post("/login", data={"username": username, "password": password,
                                       "_csrf": m.group(1) if m else ""},
                       follow_redirects=False)


print()
print("=== 1. Ep doi mat khau lan dau ===")
c = app.test_client()
login(c, "an.nguyen9a", "matkhaucu1")
r = c.get("/problems", follow_redirects=False)
check("vao /problems bi chan khi chua doi mat khau", r.status_code == 302,
      "nhan %s" % r.status_code)
check("chuyen huong ve /account", "/account" in (r.headers.get("Location") or ""),
      r.headers.get("Location"))
r = c.get("/account")
check("trang /account mo duoc", r.status_code == 200, "nhan %s" % r.status_code)
body = r.data.decode("utf-8", "replace")
check("co khung canh bao doi mat khau", "alert--warn" in body)
check("co 3 o mat khau", body.count('type="password"') == 3,
      body.count('type="password"'))

print()
print("=== 2. Cac truong hop mat khau sai ===")
import re as _re
csrf = _re.search(r'name="_csrf"\s+value="([^"]+)"', body).group(1)


def change_pw(cur, new, confirm):
    return c.post("/account/password",
                  data={"_csrf": csrf, "current_password": cur,
                        "new_password": new, "confirm_password": confirm},
                  follow_redirects=True).data.decode("utf-8", "replace")


t = change_pw("saomatkhau", "matkhaumoi1", "matkhaumoi1")
check("sai mat khau hien tai -> bao loi", "Mật khẩu hiện tại không đúng" in t)
t = change_pw("matkhaucu1", "matkhaumoi1", "khacnhau")
check("hai lan nhap khac nhau -> bao loi", "không giống nhau" in t)
t = change_pw("matkhaucu1", "abc", "abc")
check("mat khau ngan -> bao loi", "ít nhất 8 ký tự" in t)
t = change_pw("matkhaucu1", "12345678", "12345678")
check("mat khau de doan -> bao loi", "quá dễ đoán" in t)
t = change_pw("matkhaucu1", "an.nguyen9a", "an.nguyen9a")
check("mat khau trung ten dang nhap -> bao loi", "trùng với tên đăng nhập" in t)
_c = db.connect(DB)
check("cac lan sai khong lam mat co must_change_password",
      db.query_one(_c, "SELECT must_change_password FROM users WHERE username='an.nguyen9a'")[0] == 1)
_c.close()

print()
print("=== 3. Doi mat khau thanh cong ===")
t = change_pw("matkhaucu1", "MatKhauMoi2026", "MatKhauMoi2026")
check("bao thanh cong", "Đã đổi mật khẩu" in t)
conn2 = db.connect(DB)
row = db.query_one(conn2, "SELECT * FROM users WHERE username='an.nguyen9a'")
check("co must_change_password da tat", row["must_change_password"] == 0)
check("mat khau moi dung", auth.verify_password(row["password_hash"], "MatKhauMoi2026"))
check("mat khau cu khong con dung",
      not auth.verify_password(row["password_hash"], "matkhaucu1"))
conn2.close()
r = c.get("/problems", follow_redirects=False)
check("sau khi doi, /problems mo lai", r.status_code == 200, "nhan %s" % r.status_code)

print()
print("=== 4. Anh dai dien ===")
r = c.post("/account/avatar",
           data={"_csrf": csrf, "avatar": (io.BytesIO(make_image()), "anh.jpg")},
           content_type="multipart/form-data", follow_redirects=True)
check("tai anh JPEG that -> thanh cong", "Đã cập nhật ảnh đại diện" in
      r.data.decode("utf-8", "replace"))
conn2 = db.connect(DB)
row = db.query_one(conn2, "SELECT avatar_file FROM users WHERE username='an.nguyen9a'")
conn2.close()
name1 = row["avatar_file"]
check("CSDL co ten tep anh", bool(name1), name1)
avatars_dir = os.path.join(TMP, "avatars")
check("tep anh nam dung thu muc", os.path.exists(os.path.join(avatars_dir, name1)))
from PIL import Image
# `Image.open` doc luoi: no mo tep va GIU TEP MO cho tới khi anh duoc nap hoac
# dong. Tren Windows, khong xoa duoc mot tep dang mo — nen neu khong dong o day,
# buoc kiem tra "anh cu da bi xoa" o phan 6 se that bai vi ly do chang lien quan
# gi den ma nguon dang kiem.
with Image.open(os.path.join(avatars_dir, name1)) as img:
    check("anh duoc cat vuong 256x256", img.size == (256, 256), img.size)
    check("anh luu dang PNG", img.format == "PNG", img.format)

r = c.get("/avatar/1")
check("phuc vu duoc anh", r.status_code == 200, r.status_code)
check("dung kieu noi dung", r.headers.get("Content-Type", "").startswith("image/png"),
      r.headers.get("Content-Type"))

print()
print("=== 5. Cac tep khong phai anh phai bi tu choi ===")
r = c.post("/account/avatar",
           data={"_csrf": csrf, "avatar": (io.BytesIO(b"<?php system($_GET['c']); ?>"), "vo.png")},
           content_type="multipart/form-data", follow_redirects=True)
t = r.data.decode("utf-8", "replace")
check("ma PHP doi ten .png bi tu choi", "không đọc được như một ảnh" in t)
conn2 = db.connect(DB)
check("CSDL khong doi khi bi tu choi",
      db.query_one(conn2, "SELECT avatar_file FROM users WHERE username='an.nguyen9a'")[0] == name1)
conn2.close()

r = c.post("/account/avatar",
           data={"_csrf": csrf, "avatar": (io.BytesIO(b"khong phai anh"), "a.txt")},
           content_type="multipart/form-data", follow_redirects=True)
check("tep van ban bi tu choi",
      "không đọc được như một ảnh" in r.data.decode("utf-8", "replace"))

r = c.post("/account/avatar",
           data={"_csrf": csrf, "avatar": (io.BytesIO(make_png_bomb()), "bom.png")},
           content_type="multipart/form-data", follow_redirects=True)
t = r.data.decode("utf-8", "replace")
check("bom giai nen bi tu choi",
      ("quá lớn" in t) or ("không đọc được" in t), t[t.find("alert--warn"):][:120])

r = c.post("/account/avatar",
           data={"_csrf": csrf, "avatar": (io.BytesIO(b"x" * (6 * 1024 * 1024)), "to.png")},
           content_type="multipart/form-data", follow_redirects=True)
check("tep qua nang bi tu choi",
      "quá lớn" in r.data.decode("utf-8", "replace"),
      r.status_code)

print()
print("=== 6. Doi anh moi thi xoa anh cu ===")
c.post("/account/avatar",
       data={"_csrf": csrf, "avatar": (io.BytesIO(make_image(400, 400, "PNG")), "moi.png")},
       content_type="multipart/form-data", follow_redirects=True)
conn2 = db.connect(DB)
name2 = db.query_one(conn2, "SELECT avatar_file FROM users WHERE username='an.nguyen9a'")[0]
conn2.close()
check("ten tep doi", name2 != name1, "%s -> %s" % (name1, name2))
check("anh cu da bi xoa", not os.path.exists(os.path.join(avatars_dir, name1)))
check("anh moi co tren dia", os.path.exists(os.path.join(avatars_dir, name2)))

r = c.post("/account/avatar/remove", data={"_csrf": csrf}, follow_redirects=True)
check("xoa anh duoc", "Đã xoá ảnh đại diện" in r.data.decode("utf-8", "replace"))
check("tep da bi xoa khoi dia", not os.path.exists(os.path.join(avatars_dir, name2)))
r = c.get("/avatar/1")
check("khong con anh thi tra 404", r.status_code == 404, r.status_code)

print()
print("=== 7. Gioi thieu ===")
r = c.post("/account/profile", data={"_csrf": csrf, "bio": "x" * 500},
           follow_redirects=True)
check("gioi thieu qua dai -> bao loi", "dài quá" in r.data.decode("utf-8", "replace"))
r = c.post("/account/profile", data={"_csrf": csrf, "bio": "  Em thich toan va C++.  "},
           follow_redirects=True)
check("luu gioi thieu duoc", "Đã lưu phần giới thiệu" in r.data.decode("utf-8", "replace"))
conn2 = db.connect(DB)
check("khoang trang hai dau duoc cat",
      db.query_one(conn2, "SELECT bio FROM users WHERE username='an.nguyen9a'")[0] ==
      "Em thich toan va C++.")
conn2.close()

print()
print("=== 8. Khach chua dang nhap ===")
c2 = app.test_client()
r = c2.get("/account", follow_redirects=False)
check("chua dang nhap -> chuyen ve /login", r.status_code == 302 and "/login" in
      (r.headers.get("Location") or ""), r.headers.get("Location"))
r = c2.get("/avatar/1", follow_redirects=False)
check("anh dai dien khong mo cong khai", r.status_code == 302, r.status_code)

print()
print("=== 9. Trang khac khong bi vo ===")
c3 = app.test_client()
login(c3, "thumai", "giaovien1")
for path in ("/", "/problems", "/submissions", "/leaderboard", "/contests",
             "/teacher", "/teacher/problems", "/teacher/classes", "/account"):
    r = c3.get(path)
    check("giao vien mo duoc %s" % path, r.status_code == 200, r.status_code)

print()
print("=== 10. Migration: CSDL cu thieu cot ===")
OLD = os.path.join(TMP, "cu.db")
old = sqlite3.connect(OLD)
old.executescript("""
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  class_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'student',
  password_hash TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
INSERT INTO users (username, full_name, password_hash, created_at)
VALUES ('cu', 'Nguoi Cu', 'x', '2026-01-01T00:00:00Z');
""")
old.commit()
old.close()
db.init_db(OLD)
old = sqlite3.connect(OLD)
old.row_factory = sqlite3.Row
cols = {r["name"] for r in old.execute("PRAGMA table_info(users)")}
check("them duoc cot avatar_file", "avatar_file" in cols)
check("them duoc cot bio", "bio" in cols)
row = old.execute("SELECT * FROM users WHERE username='cu'").fetchone()
check("du lieu cu con nguyen", row["full_name"] == "Nguoi Cu")
check("cot moi co gia tri mac dinh rong", row["avatar_file"] == "" and row["bio"] == "")
old.close()
db.init_db(OLD)
old = sqlite3.connect(OLD)
n = old.execute("SELECT COUNT(*) FROM users").fetchone()[0]
old.close()
check("chay migration lan hai khong nhan doi du lieu", n == 1, n)

print()
print("=== 11. Migration chay song song (gunicorn nhieu worker) ===")
# Loi that da xay ra tren may chu: gunicorn khoi dong nhieu worker cung luc, moi
# worker goi create_app() va do do goi migration. Hai worker cung doc thay cot
# con thieu, roi ca hai cung ALTER; worker thu hai nhan "duplicate column name"
# va chet ngay luc khoi dong. May chu phat trien cua Flask chi co mot tien
# trinh nen khong bao gio tai hien duoc.


class _StaleConn:
    """Bọc kết nối thật nhưng giấu đi vài cột — mô phỏng tiến trình đọc chậm.

    Nhờ lớp bọc này mà cuộc tranh trở nên **tất định**: ta tự tay dựng đúng
    trạng thái "đã đọc xong bảng, chưa kịp ALTER" thay vì hy vọng hai luồng
    chạy trúng nhau.
    """

    def __init__(self, real, hide):
        self._real = real
        self._hide = set(hide)

    def execute(self, sql, params=()):
        if sql.startswith("PRAGMA table_info"):
            rows = self._real.execute(sql, params).fetchall()
            return [r for r in rows if r["name"] not in self._hide]
        return self._real.execute(sql, params)


RACE = os.path.join(TMP, "race.db")
db.init_db(RACE)          # da co du cot
race = db.connect(RACE)
try:
    db._migrate(_StaleConn(race, {"avatar_file", "bio"}))
    check("doc thay cot thieu nhung cot da co -> khong nem loi", True)
except Exception as exc:                                  # noqa: BLE001
    check("doc thay cot thieu nhung cot da co -> khong nem loi", False, exc)
race.close()

# Va mot lan chay that su song song, de bat ca truong hop khoa CSDL.
import threading                                              # noqa: E402

errors = []


def _race_init(path, gate):
    try:
        gate.wait()
        db.init_db(path)
    except Exception as exc:                                  # noqa: BLE001
        errors.append(exc)


for _round in range(4):
    R2 = os.path.join(TMP, "race%d.db" % _round)
    # Tao CSDL cu (thieu cot) bang cach dung thang schema khong co hai cot moi.
    old = sqlite3.connect(R2)
    old.executescript("""
    CREATE TABLE users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
      full_name TEXT NOT NULL, class_name TEXT NOT NULL DEFAULT '',
      role TEXT NOT NULL DEFAULT 'student', password_hash TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1,
      must_change_password INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, last_login_at TEXT);
    """)
    old.commit()
    old.close()
    gate = threading.Barrier(4)
    threads = [threading.Thread(target=_race_init, args=(R2, gate)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

check("4 tien trinh cung chay migration: khong tien trinh nao loi",
      not errors, errors[:1])

shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 60)
print("DAT: %d   SAI: %d" % (len(OK), len(BAD)))
if BAD:
    for b in BAD:
        print("  -", b)
sys.exit(1 if BAD else 0)
