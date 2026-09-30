"""Render các trang cần đăng nhập ra HTML tĩnh, để chụp ảnh hoặc kiểm tra bố cục.

Vì sao cần: `chrome --headless --screenshot` không đăng nhập được. Các trang của
giáo viên vì thế không có cách nào xem thử bằng ảnh chụp, trong khi đó lại đúng
là những trang có bảng nhiều cột — loại dễ tràn ngang nhất.

Cách làm: dùng `test_client` của Flask để đăng nhập và lấy HTML đã render, ghi
ra `demo/_render/`. Đặt trong `demo/` là có chủ ý: template gọi tài sản tĩnh bằng
đường dẫn tuyệt đối `/assets/...`, nên chỉ cần phục vụ thư mục `demo/` là CSS và
JS tải được, không phải sửa gì trong HTML.

    python _tools/render_pages.py
    cd demo && python -m http.server 8813        # rồi mở http://127.0.0.1:8813/_render/

Sau đó chụp hoặc đo bố cục trên các tệp trong `_render/`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.app import create_app  # noqa: E402

CSRF_RE = re.compile(r'name="_csrf"\s+value="([^"]+)"')

# (đường dẫn, tên tệp, tài khoản đăng nhập)
PAGES = [
    ("/", "01-trang-chu", None),
    ("/problems", "02-danh-sach-de", None),
    ("/problems/SL001", "03-chi-tiet-de", None),
    ("/problems/SL001?tab=submit", "04-nop-bai", None),
    ("/problems/SL001?tab=result", "05-ket-qua", None),
    ("/leaderboard", "06-bang-xep-hang", None),
    ("/contests", "07-ky-thi", None),
    ("/login", "08-dang-nhap", None),
    ("/submissions/1", "09-bai-nop-cua-em", "student"),
    ("/submissions/3", "10-bai-nop-mle", "teacher"),
    ("/submissions/4", "11-bai-nop-ce", "teacher"),
    ("/submissions/13", "12-bai-nop-tle", "teacher"),
    ("/teacher", "13-tong-quan-giao-vien", "teacher"),
    ("/teacher/problems", "14-soan-de", "teacher"),
    ("/teacher/problems/SL001/tests", "15-bo-du-lieu", "teacher"),
    ("/teacher/classes", "16-lop-hoc", "teacher"),
]

ACCOUNTS = {
    "teacher": ("cophang", "Songlo@GV2026"),
    "student": ("9A01", "Songlo@2026"),
}


def login(client, who: str) -> bool:
    username, password = ACCOUNTS[who]
    page = client.get("/login").get_data(as_text=True)
    match = CSRF_RE.search(page)
    if not match:
        return False
    resp = client.post(
        "/login",
        data={"username": username, "password": password, "_csrf": match.group(1)},
    )
    return resp.status_code in (200, 302)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "server" / "var" / "songlo.db"))
    parser.add_argument("--out", default=str(ROOT / "demo" / "_render"))
    args = parser.parse_args(argv)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    app = create_app({"DATABASE": args.database})

    clients: dict[str, object] = {"guest": app.test_client()}
    for who in ("teacher", "student"):
        client = app.test_client()
        if login(client, who):
            clients[who] = client
        else:
            print(f"  CẢNH BÁO: đăng nhập {who} thất bại; các trang của tài khoản này sẽ bị bỏ qua")

    failures = []
    for path, name, who in PAGES:
        client = clients.get(who or "guest")
        if client is None:
            continue
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        if resp.status_code != 200:
            failures.append((path, resp.status_code))
            print(f"  LỖI {resp.status_code}  {path}")
            continue
        (outdir / f"{name}.html").write_text(html, encoding="utf-8")
        print(f"  ok  {len(html):>6} byte  {name}.html")

    print()
    print(f"Đã ghi vào {outdir}")
    print("Xem: cd demo && python -m http.server 8813")
    print(f"     rồi mở http://127.0.0.1:8813/_render/")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
