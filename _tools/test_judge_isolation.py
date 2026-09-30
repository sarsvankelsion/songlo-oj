"""Kiểm thử rằng thư mục làm việc của bộ chấm dùng được từ tài khoản đã hạ quyền.

Vì sao cần script này: đây là lỗi chỉ tồn tại trên máy chủ Linux, và triệu chứng
của nó trỏ sai chỗ hoàn toàn.

`tempfile.mkdtemp` tạo thư mục với quyền 0700 thuộc tài khoản gọi nó — tức
`root`, vì `deploy/README.md` cho tiến trình chấm chạy bằng root. Tiến trình con
sau đó bị hạ xuống `SONGLO_JUDGE_RUNAS_UID` trước khi `exec`. Tài khoản đó không
có quyền **tìm kiếm** trên thư mục 0700 của root, nên `g++` không mở nổi
`main.cpp`:

    cc1plus: fatal error: main.cpp: Permission denied

Thông báo nằm trong nhật ký dịch, cùng chỗ với lỗi cú pháp của học sinh. Nhìn
qua thì như mọi bài làm đều sai, nhưng **mọi** bài đều CE kể cả bài đúng, và
không có bài nào chạy được một bộ dữ liệu nào.

Vì sao các bài kiểm thử khác không bắt được: trên Windows không có `setuid` nên
không hạ quyền, và trên máy chủ thì phải chạy bằng root mới tái hiện. Script này
vì thế có hai chế độ:

  * Phần 1 chạy được ở mọi hệ điều hành.
  * Phần 2–5 chỉ chạy khi là POSIX **và** đang là root; nếu không, chúng được
    báo là bỏ qua chứ không im lặng coi như đạt.

Phần 5 tốn khoảng 5 giây vì nó chờ đồng hồ canh giờ thực cắt một bài ngủ — đúng
thứ đang bảo vệ hàng đợi chấm khỏi một chương trình không bao giờ kết thúc.

    python _tools/test_judge_isolation.py

Script không đụng vào CSDL thật: mọi thứ nằm trong thư mục tạm.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import db, judge, sandbox  # noqa: E402

failures: list[str] = []
skipped: list[str] = []

SRC = """\
#include <iostream>
int main() {
    long long a, b;
    std::cin >> a >> b;
    std::cout << a + b << "\\n";
    return 0;
}
"""

# Ngủ lâu hơn giới hạn thời gian. Tiêu tốn gần như không CPU, nên chỉ đồng hồ
# canh giờ thực cắt được — đây là bài kiểm chứng chính đường đó.
SRC_SLEEP = """\
#include <iostream>
#include <thread>
#include <chrono>
int main() {
    long long a, b;
    std::cin >> a >> b;
    std::this_thread::sleep_for(std::chrono::seconds(30));
    std::cout << a + b << "\\n";
    return 0;
}
"""


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'LỖI '} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def skip(label: str, why: str) -> None:
    print(f"  BỎ QUA {label}  — {why}")
    skipped.append(label)


def sandbox_account() -> tuple[int, int] | None:
    """Tài khoản để hạ quyền: ưu tiên biến môi trường, rồi tới `nobody`."""
    uid = os.environ.get("SONGLO_JUDGE_RUNAS_UID")
    gid = os.environ.get("SONGLO_JUDGE_RUNAS_GID")
    if uid:
        return int(uid), (int(gid) if gid else -1)
    try:
        import pwd

        p = pwd.getpwnam("nobody")
        return p.pw_uid, p.pw_gid
    except (ImportError, KeyError):
        return None


def child_uses_dir(workdir: Path, uid: int, gid: int) -> tuple[bool, str]:
    """Fork, hạ quyền, rồi thử đi vào thư mục, đọc và tạo tệp.

    Đây đúng là ba thao tác mà `g++` cần: đi qua thư mục, đọc `main.cpp`, ghi
    tệp thực thi. Thiếu bất kỳ quyền nào trong đó thì bài nộp CE.
    """
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            os.setgid(gid)
            os.setgroups([])
            os.setuid(uid)
            os.chdir(workdir)
            (workdir / "main.cpp").read_text()
            (workdir / "probe.tmp").write_text("x")
            os.write(write_fd, b"OK")
        except Exception as exc:  # noqa: BLE001
            os.write(write_fd, f"{type(exc).__name__}: {exc}".encode())
        os._exit(0)
    os.close(write_fd)
    message = os.read(read_fd, 4096).decode("utf-8", "replace")
    os.close(read_fd)
    os.waitpid(pid, 0)
    return message == "OK", message


def nproc_limit_after_limits(runas_uid: str | None, runas_gid: str | None):
    """Chạy `_apply_posix_limits` trong tiến trình con, đọc lại RLIMIT_NPROC."""
    import resource

    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        sandbox.RUNAS_UID = runas_uid
        sandbox.RUNAS_GID = runas_gid
        try:
            sandbox._apply_posix_limits(1, 256 * 1024 * 1024)
            value = str(resource.getrlimit(resource.RLIMIT_NPROC)[0])
        except Exception as exc:  # noqa: BLE001
            value = f"lỗi: {exc!r}"
        os.write(write_fd, value.encode())
        os._exit(0)
    os.close(write_fd)
    message = os.read(read_fd, 4096).decode("utf-8", "replace")
    os.close(read_fd)
    os.waitpid(pid, 0)
    return message


def build_temp_db(db_path: Path) -> object:
    """CSDL tối thiểu: một đề, một bộ dữ liệu, một bài nộp đúng."""
    db.init_db(db_path)
    conn = db.connect(db_path)
    now = db.utc_now()
    with conn:
        conn.execute(
            "INSERT INTO users (username, full_name, role, password_hash, created_at)"
            " VALUES ('gv', 'Giáo viên', 'teacher', 'x', ?)", (now,))
        conn.execute(
            "INSERT INTO problems (code, name, time_limit_ms, memory_limit_mb,"
            " status, created_at, updated_at)"
            " VALUES ('T1', 'Tổng hai số', 1000, 256, 'live', ?, ?)", (now, now))
        conn.execute(
            "INSERT INTO tests (problem_id, ordinal, input, output)"
            " VALUES (1, 1, '2 3\n', '5\n')")
        conn.execute(
            "INSERT INTO submissions (problem_id, user_id, source, status, created_at)"
            " VALUES (1, 1, ?, 'pending', ?)", (SRC, now))
        conn.execute(
            "INSERT INTO submissions (problem_id, user_id, source, status, created_at)"
            " VALUES (1, 1, ?, 'pending', ?)", (SRC_SLEEP, now))
    return conn


def main() -> int:
    is_posix = os.name == "posix"
    is_root = is_posix and os.geteuid() == 0
    account = sandbox_account() if is_posix else None

    print("1. Không cấu hình tài khoản hạ quyền — phải không đụng vào thư mục")
    keep_uid, keep_gid = sandbox.RUNAS_UID, sandbox.RUNAS_GID
    sandbox.RUNAS_UID = sandbox.RUNAS_GID = None
    workdir = Path(tempfile.mkdtemp(prefix="songlo-iso-"))
    (workdir / "main.cpp").write_text(SRC, encoding="utf-8")
    before = (workdir.stat().st_uid, workdir.stat().st_gid, workdir.stat().st_mode)
    sandbox.prepare_workspace(workdir)
    after = (workdir.stat().st_uid, workdir.stat().st_gid, workdir.stat().st_mode)
    check("chủ và quyền giữ nguyên", before == after, f"{oct(before[2] & 0o777)}")

    if not is_posix:
        print("\nPhần 2–5 cần Linux: Windows không có setuid nên không hạ quyền được.")
        skip("toàn bộ phần 2–5", "không phải POSIX")
    elif not is_root:
        print("\nPhần 2–5 cần chạy bằng root: chỉ root mới đổi được chủ tệp.")
        skip("toàn bộ phần 2–5", f"euid={os.geteuid()}, cần 0")
    elif account is None:
        skip("toàn bộ phần 2–5", "không tìm thấy tài khoản để hạ quyền")
    else:
        uid, gid = account
        print(f"\n2. Hạ quyền xuống uid={uid} gid={gid} — thư mục phải dùng được")
        sandbox.RUNAS_UID, sandbox.RUNAS_GID = str(uid), str(gid)

        plain = Path(tempfile.mkdtemp(prefix="songlo-iso-plain-"))
        (plain / "main.cpp").write_text(SRC, encoding="utf-8")
        ok_before, why_before = child_uses_dir(plain, uid, gid)
        check("thư mục 0700 của root thì KHÔNG dùng được (đúng như lỗi gốc)",
              not ok_before, why_before or "dùng được — môi trường khác thường")

        sandbox.prepare_workspace(workdir)
        check("prepare_workspace đổi chủ thư mục", workdir.stat().st_uid == uid,
              f"uid={workdir.stat().st_uid}")
        ok_after, why_after = child_uses_dir(workdir, uid, gid)
        check("sau khi đổi chủ thì dùng được", ok_after, why_after)

        print("\n3. RLIMIT_NPROC chỉ áp khi thật sự đã hạ quyền")
        sandbox.RUNAS_UID = sandbox.RUNAS_GID = None
        without = nproc_limit_after_limits(None, None)
        check("không hạ quyền -> không siết số tiến trình",
              without != str(sandbox.MAX_PROCESSES), f"RLIMIT_NPROC={without}")
        with_drop = nproc_limit_after_limits(str(uid), str(gid))
        check("có hạ quyền -> siết đúng bằng MAX_PROCESSES",
              with_drop == str(sandbox.MAX_PROCESSES), f"RLIMIT_NPROC={with_drop}")

        print("\n4. Chấm thật một bài đúng — phải ra AC, không phải CE")
        sandbox.RUNAS_UID, sandbox.RUNAS_GID = str(uid), str(gid)
        tmp = Path(tempfile.mkdtemp(prefix="songlo-iso-e2e-"))
        # Thư mục gốc cũng phải đi qua được, không chỉ thư mục làm việc.
        # `mkdtemp` để nó ở quyền 0700, mà đây lại là thư mục **cha** của thư mục
        # làm việc: quyền tìm kiếm thiếu ở đây cho ra đúng lỗi
        # "PermissionError: .../main" khi chạy, muộn hơn một bước so với lỗi
        # tương tự ở thư mục làm việc. Trên máy chủ thật, `/var/lib/songlo/judge`
        # là 0755 nên không có chuyện này — đặt lại đúng 0755 để phép kiểm phản
        # ánh đúng môi trường triển khai.
        os.chmod(tmp, 0o755)
        conn = build_temp_db(tmp / "songlo.db")
        try:
            outcome = judge.judge_submission(conn, 1, tmp / "judge")
            check("kết quả là AC", outcome.verdict == "AC",
                  f"{outcome.verdict} {outcome.score}/{outcome.max_score}")
            check("không còn 'Permission denied' trong nhật ký dịch",
                  "Permission denied" not in outcome.compile_log,
                  outcome.compile_log.strip().splitlines()[-1] if outcome.compile_log else "")
            check("bộ dữ liệu cũng chạy được",
                  len(outcome.tests) == 1 and outcome.tests[0].verdict == "AC",
                  outcome.tests[0].verdict if outcome.tests else "không có bộ nào")

            print("\n5. Bài ngủ 30 giây — đồng hồ canh giờ thực phải cắt được")
            # Giới hạn thực là 1000 ms * 3 + 2 giây = 5 giây.
            hung = judge.judge_submission(conn, 2, tmp / "judge")
            check("kết quả là TLE", hung.verdict == "TLE", hung.verdict)
            check("báo thời gian thực, không phải thời gian CPU",
                  hung.time_ms >= 4000,
                  f"{hung.time_ms} ms — thời gian CPU của một bài ngủ chỉ vài ms")
        finally:
            conn.close()

    sandbox.RUNAS_UID, sandbox.RUNAS_GID = keep_uid, keep_gid

    print()
    if failures:
        print(f"{len(failures)} phép kiểm tra KHÔNG đạt:")
        for f in failures:
            print("  -", f)
        return 1
    if skipped:
        print(f"Đạt phần đã chạy; {len(skipped)} phần bị bỏ qua (chạy trên máy chủ Linux bằng root để kiểm đủ).")
        return 0
    print("Tất cả phép kiểm tra đều đạt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
