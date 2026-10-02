#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In ra HTML cua mot dong trong bang danh sach de (khu giao vien).

Dung de nhin bang mat sau khi sua giao dien. Khong phai bai kiem tra.

    python tests/_dump_problems_row.py
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import auth, db                        # noqa: E402
from server.app import create_app                  # noqa: E402

TMP = tempfile.mkdtemp(prefix="songlo-dump-")
DB = os.path.join(TMP, "songlo.db")
app = create_app({"TESTING": True, "DATABASE": DB, "SECRET_KEY": "t"})

conn = db.connect(DB)
now = db.utc_now()
with conn:
    conn.execute(
        """INSERT INTO users (username, full_name, class_name, role, password_hash,
                              is_active, must_change_password, created_at)
           VALUES (?,?,?,?,?,1,0,?)""",
        ("gv", "Giáo Viên", "", "teacher", auth.hash_password("matkhau123"), now))
    for code, status in (("SL001", "live"), ("SL002", "draft"), ("SL003", "review")):
        conn.execute(
            """INSERT INTO problems (code, name, statement, difficulty, topic,
                                     time_limit_ms, memory_limit_mb, points_mode,
                                     status, created_at, updated_at)
               VALUES (?,?,?,?,?,1000,256,'even',?,?,?)""",
            (code, "Bài " + code, "Đề bài.", "co-ban", "Số học", status, now, now))
    # SL002 co du lieu (de xem nut "Cong khai" that), SL003 khong co.
    pid = db.query_one(conn, "SELECT id FROM problems WHERE code='SL002'")["id"]
    conn.execute("INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points) "
                 "VALUES (?,1,'1\\n','1\\n',1,0)", (pid,))
conn.close()

client = app.test_client()
page = client.get("/login").data.decode("utf-8")
csrf = re.search(r'name="_csrf"\s+value="([^"]+)"', page).group(1)
client.post("/login", data={"username": "gv", "password": "matkhau123", "_csrf": csrf})

html = client.get("/teacher/problems").data.decode("utf-8")
body = html[html.index("<tbody>"):html.index("</tbody>")]
for row in re.findall(r"<tr>[\s\S]*?</tr>", body):
    print("=" * 70)
    print(row.strip())

print("\n" + "=" * 70)
print("Cảnh báo đầu trang:")
m = re.search(r'<div class="alert alert--warn" role="note">[\s\S]*?</div>\s*</div>\s*</div>', html)
print(m.group(0) if m else "(không có)")

shutil.rmtree(TMP, ignore_errors=True)
