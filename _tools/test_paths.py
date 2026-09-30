"""Kiểm thử rằng cả ba tiến trình suy ra đường dẫn CSDL từ **cùng một** biến.

Vì sao cần script này: đây là loại lỗi chỉ lộ ra lúc triển khai thật, và lộ ra
rất khó đoán. `app.py` và `worker.py` đọc `SONGLO_VAR`; `seed.py` thì ghi cứng
`server/var/songlo.db`. Làm đúng theo `deploy/README.md` — nơi `SONGLO_VAR` trỏ
tới `/var/lib/songlo` — thì:

  * lệnh seed tạo CSDL **trong cây mã nguồn**;
  * tiến trình web mở CSDL ở `/var/lib/songlo`, không có lược đồ, không có tài
    khoản nào;
  * và tệp chứa dữ liệu học sinh thật nằm lẫn trong thư mục mã nguồn.

Không phép kiểm tra nào đang có bắt được điều đó, vì mọi script khác đều chạy
với mặc định (không đặt `SONGLO_VAR`), mà lúc đó cả ba đường lại trùng nhau.

    python _tools/test_paths.py

Script **không** đụng vào CSDL thật: mọi thứ chạy trong thư mục tạm, và nó
chụp lại trạng thái `server/var/` trước/sau để chắc chắn không có gì mới xuất hiện.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'LỖI '} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def snapshot(d: Path) -> dict[str, int]:
    if not d.is_dir():
        return {}
    return {p.name: p.stat().st_mtime_ns for p in d.iterdir()}


def run_module(module: str, args: list[str], var_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["SONGLO_VAR"] = str(var_dir)
    env.pop("SONGLO_DB", None)
    return subprocess.run(
        [sys.executable, "-m", module] + args,
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=180,
    )


def main() -> int:
    var_dir = Path(tempfile.mkdtemp(prefix="songlo-paths-"))
    repo_var = ROOT / "server" / "var"
    before = snapshot(repo_var)

    print("1. app.py — create_app() lấy DATABASE từ SONGLO_VAR")
    os.environ["SONGLO_VAR"] = str(var_dir)
    from server.app import create_app
    app = create_app({})
    expected = str(var_dir / "songlo.db")
    check("DATABASE trỏ vào SONGLO_VAR", app.config["DATABASE"] == expected,
          f"{app.config['DATABASE']}")
    check("JUDGE_WORKSPACE trỏ vào SONGLO_VAR",
          app.config["JUDGE_WORKSPACE"] == str(var_dir / "judge"))

    print("\n2. seed.py — chạy thật, xem tệp sinh ra ở đâu")
    r = run_module("server.seed", ["--no-submissions"], var_dir)
    check("seed thoát không lỗi", r.returncode == 0, (r.stderr or "").strip()[-160:])
    check("CSDL nằm trong SONGLO_VAR", (var_dir / "songlo.db").exists())
    # `server/var/songlo.db` là CSDL phát triển, có sẵn trong repo và bị
    # .gitignore loại trừ. Nên không kiểm "không tồn tại" mà kiểm "không bị ghi
    # vào" — đó mới đúng là điều cần bảo vệ.
    check("seed KHÔNG ghi vào CSDL trong cây mã nguồn",
          before.get("songlo.db") == snapshot(repo_var).get("songlo.db"),
          "mtime giữ nguyên")

    print("\n3. worker.py — phải mở đúng CSDL đó, không tạo tệp mới")
    r = run_module("server.worker", ["--once"], var_dir)
    check("worker thoát không lỗi", r.returncode == 0, (r.stderr or "").strip()[-200:])

    print("\n4. server/var/ không bị đụng tới")
    after = snapshot(repo_var)
    check("không tệp nào mới xuất hiện trong server/var/",
          set(after) <= set(before), f"mới: {sorted(set(after) - set(before))}")

    print()
    if failures:
        print(f"{len(failures)} phép kiểm tra KHÔNG đạt:")
        for f in failures:
            print("  -", f)
        return 1
    print("Tất cả phép kiểm tra đều đạt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
