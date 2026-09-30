"""Chụp ảnh các trang trong `demo/_render/` (và trang tĩnh trong `demo/`).

Vì sao cần hai lượt: `chrome --headless --screenshot` chỉ chụp **khung nhìn**, không
chụp cả trang. Đặt `--window-size` thấp hơn nội dung thì ảnh bị cắt; cao hơn thì
thừa một khoảng trống. Nên phải đo chiều cao thật trước, rồi mới chụp đúng chiều
cao đó.

Cũng vì sao phải đi qua iframe: Chrome headless theo chế độ sáng/tối của **hệ điều
hành**, không theo cờ dòng lệnh. Trang có `prefers-color-scheme` sẽ ra sai chủ đề
mà không có dấu hiệu nào trong lệnh. `_probe_shot.html` ghi `localStorage` trước khi
gán `iframe.src`, nên script chống nháy của trang đọc được chủ đề đã ép ngay từ lần
vẽ đầu tiên.

    python _tools/shoot.py --url http://127.0.0.1:8814 --theme light
    python _tools/shoot.py --url http://127.0.0.1:8814 --theme dark --pages 13-tong-quan-giao-vien.html
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

HEIGHT_RE = re.compile(r"h=(\d+)")


def find_chrome(explicit: str | None) -> str:
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        sys.exit(f"Không thấy Chrome ở {explicit}")
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c):
            return c
    import shutil

    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    sys.exit("Không tìm thấy Chrome. Truyền --chrome <đường dẫn>.")


def base_cmd(chrome: str, profile: str) -> list[str]:
    return [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--disable-http-cache",
        "--force-device-scale-factor=1",
        f"--user-data-dir={profile}",
    ]


def winpath(p: Path) -> str:
    """Chrome trên Windows cần đường dẫn tuyệt đối kiểu Windows.

    Đường dẫn tương đối bị ghi vào thư mục cài Chrome chứ không phải thư mục làm
    việc, và lệnh vẫn báo thành công — nên phải kiểm tra lại tệp sau khi chụp.
    """
    return str(p.resolve()).replace("/", "\\")


def probe_url(base: str, page: str, theme: str, width: int) -> str:
    return f"{base}/_probe_shot.html?theme={theme}&w={width}&page={page}"


def measure(chrome: str, profile: str, url: str, width: int) -> int | None:
    cmd = base_cmd(chrome, profile) + [
        "--virtual-time-budget=8000",
        f"--window-size={width},1000",
        "--dump-dom",
        url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180).stdout
    m = re.search(r'<div id="o">h=(\d+)</div>', out)
    return int(m.group(1)) if m else None


def shoot(chrome: str, profile: str, url: str, width: int, height: int, dest: Path) -> bool:
    cmd = base_cmd(chrome, profile) + [
        "--virtual-time-budget=8000",
        f"--window-size={width},{height}",
        f"--screenshot={winpath(dest)}",
        url,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return dest.is_file() and dest.stat().st_size > 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="ví dụ http://127.0.0.1:8814")
    ap.add_argument("--dir", default="_render", help="thư mục con của demo/ (mặc định _render)")
    ap.add_argument("--out", default=None, help="thư mục ảnh (mặc định _shots/<dir>-<theme>)")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--pages", nargs="*", default=[], help="mặc định: mọi *.html trong thư mục")
    ap.add_argument("--chrome", default=None)
    args = ap.parse_args(argv)

    chrome = find_chrome(args.chrome)
    src = DEMO / args.dir
    pages = args.pages or sorted(p.name for p in src.glob("*.html") if not p.name.startswith("_"))
    if not pages:
        sys.exit(f"Không có tệp .html nào trong {src}")

    outdir = Path(args.out) if args.out else ROOT / "_shots" / f"{args.dir.strip('_')}-{args.theme}"
    outdir.mkdir(parents=True, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="songlo-shoot-")
    ok = 0
    try:
        for page in pages:
            # `_probe_shot.html` nằm ở gốc `demo/`, nên đường dẫn trang phải tính
            # từ đó: `_render/01-trang-chu.html`, không phải `01-trang-chu.html`.
            rel = f"{args.dir}/{page}" if args.dir else page
            url = probe_url(args.url, rel, args.theme, args.width)
            height = measure(chrome, profile, url, args.width)
            if height is None:
                print(f"  BỎ QUA  {page}  (không đo được chiều cao — server có chạy không?)")
                continue
            dest = outdir / f"{page.replace('.html', '')}.png"
            if shoot(chrome, profile, url, args.width, height, dest):
                print(f"  ok  {dest.stat().st_size // 1024:>5} KB  {args.width}x{height}  {dest.name}")
                ok += 1
            else:
                print(f"  LỖI     {page}  — không thấy tệp ảnh sau khi chụp")
    finally:
        import shutil

        shutil.rmtree(profile, ignore_errors=True)

    print()
    print(f"{ok}/{len(pages)} ảnh trong {outdir}")
    return 0 if ok == len(pages) else 1


if __name__ == "__main__":
    raise SystemExit(main())
