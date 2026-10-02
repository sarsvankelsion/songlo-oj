"""Sinh bộ dữ liệu chấm từ một bộ sinh và một lời giải mẫu.

Vì sao cần: các kho đề Việt Nam (LQDOJ, Tin học trẻ, đề HSG các tỉnh) cho **đề
bài** nhưng không cho **dữ liệu chấm** — xem `docs/nguon-de.md`. Không có dữ liệu
thì đề không chấm được, nên thực tế giáo viên phải gõ tay từng bộ, và một đề
15–20 bộ tốn cả buổi. Gõ tay còn có kiểu sai thứ hai: bộ dữ liệu nào cũng chỉ
kiểm được đúng những gì người ra đề đã nghĩ tới.

Cách làm ở đây là cách chuẩn của mọi hệ thống chấm — giáo viên đưa **hai** chương
trình:

  - **Bộ sinh** (`gen`): nhận chỉ số bộ qua ``argv[1]``, in ra một bộ dữ liệu vào
    bất kỳ. Nhận chỉ số là để viết được ``srand(atoi(argv[1]))`` — cùng chỉ số thì
    ra cùng dữ liệu, nên sinh lại được đúng bộ cũ khi cần.
  - **Lời giải mẫu** (`sol`): đọc dữ liệu vào từ stdin, in đáp án ra stdout.

Hệ thống chạy bộ sinh để lấy dữ liệu vào, rồi chạy lời giải mẫu trên **chính** dữ
liệu đó để lấy đáp án. Không phải tự nghĩ ra đáp án, và không phải chép tay.

Tệp này không phụ thuộc Flask — nó chỉ nhận hai chuỗi mã nguồn và một thư mục làm
việc, nên gọi được từ tuyến đường, từ script, hoặc từ bài kiểm thử.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from . import judge, sandbox

# Trần số bộ sinh trong một lần. Không phải vì CSDL, mà vì thời gian: xem
# `TOTAL_BUDGET_MS`.
MAX_COUNT = 30

# Trần kích thước một tệp dữ liệu. Đề cấp 2 không chạm tới con số này; nhưng một
# bộ sinh viết nhầm (`while (true) cout << i;`) thì chạm rất nhanh, và mỗi byte
# lọt vào là một byte nằm trong CSDL vĩnh viễn.
MAX_INPUT_BYTES = 256 * 1024

# Mã nguồn của bộ sinh và lời giải mẫu. Cả hai đều là chương trình ngắn.
MAX_SOURCE_BYTES = 64 * 1024

# Giới hạn cho mỗi lần chạy bộ sinh hoặc lời giải mẫu. Rộng hơn giới hạn chấm bài
# vì bộ sinh thường nặng hơn lời giải (nó phải *tạo* dữ liệu, không chỉ đọc).
RUN_LIMIT_MS = 5_000
RUN_MEMORY_MB = 512

# Ngân sách thời gian cho **cả** lần sinh.
#
# Con số này bị chặn bởi thứ nằm ngoài tệp này: gunicorn chạy với thời hạn mặc
# định 30 giây (xem `deploy/README.md`), và một yêu cầu vượt quá nó bị cắt với
# lỗi 502 — giáo viên mất công chờ rồi nhận một trang lỗi, và không biết đã sinh
# được bao nhiêu. Dừng ở 20 giây và báo rõ đã làm được tới đâu thì hơn hẳn.
TOTAL_BUDGET_MS = 20_000


def _read_text(path: Path) -> str:
    """Đọc một tệp dữ liệu đã sinh. Giải mã chịu lỗi để không ném ra ở đây."""
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def generate_tests(
    gen_source: str,
    sol_source: str,
    count: int,
    workspace_root: Path | str,
) -> tuple[list[dict], str | None]:
    """Sinh ``count`` bộ dữ liệu. Trả ``(danh sách bộ, thông báo lỗi)``.

    Mỗi bộ là dict ``{"name", "input", "output"}`` — đúng dạng
    :func:`themis.parse_zip` trả về, nên chỗ ghi vào CSDL dùng chung được.

    Khi có lỗi mà **đã sinh được một phần**, hàm trả về cả hai: phần đã sinh và
    thông báo. Bỏ phần đã sinh đi thì giáo viên mất công chờ mà không được gì;
    im lặng trả về phần thiếu thì họ tưởng đề đã đủ dữ liệu — đúng kiểu lỗi im
    lặng cần tránh.
    """
    count = max(1, min(int(count), MAX_COUNT))
    root = Path(workspace_root)
    workdir = root / ("gen-" + uuid.uuid4().hex[:12])
    gen_dir = workdir / "gen"
    sol_dir = workdir / "sol"

    try:
        # Hai thư mục riêng vì `judge.compile_source` luôn ghi `main.cpp` vào
        # thư mục nó nhận, và cả hai đều tạo ra tệp thực thi tên `main`.
        for d in (gen_dir, sol_dir):
            d.mkdir(parents=True, exist_ok=True)
            sandbox.prepare_workspace(d)

        ok, log, gen_bin = judge.compile_source(gen_dir, gen_source)
        if not ok:
            return [], "Bộ sinh dữ liệu không dịch được.\n\n" + log

        ok, log, sol_bin = judge.compile_source(sol_dir, sol_source)
        if not ok:
            return [], "Lời giải mẫu không dịch được.\n\n" + log

        tests: list[dict] = []
        started = time.monotonic()

        for i in range(1, count + 1):
            spent_ms = (time.monotonic() - started) * 1000
            if spent_ms > TOTAL_BUDGET_MS:
                return tests, (
                    "Hết %d giây cho phép nên chỉ sinh được %d trong %d bộ. "
                    "Bộ sinh hoặc lời giải mẫu chạy quá chậm — giảm số bộ, hoặc "
                    "giảm kích thước dữ liệu mà bộ sinh tạo ra."
                    % (TOTAL_BUDGET_MS // 1000, len(tests), count))

            in_path = gen_dir / ("%02d.in" % i)

            # Bộ sinh nhận chỉ số bộ qua `argv[1]`. Không truyền gì qua stdin:
            # bộ sinh không có dữ liệu vào, nó *tạo* dữ liệu.
            res = sandbox.run_limited(
                argv=[str(gen_bin), str(i)],
                cwd=gen_dir,
                stdin_path=None,
                stdout_path=in_path,
                stderr_path=gen_dir / ("%02d.err" % i),
                time_limit_ms=RUN_LIMIT_MS,
                memory_limit_mb=RUN_MEMORY_MB,
            )
            if res.killed_by_watchdog:
                return tests, ("Bộ sinh dữ liệu không kết thúc trong %d giây, ở bộ %d."
                               % (RUN_LIMIT_MS // 1000, i))
            if res.exit_code != 0:
                return tests, ("Bộ sinh dữ liệu thoát với mã %d ở bộ %d."
                               % (res.exit_code, i))

            size = in_path.stat().st_size
            if size == 0:
                return tests, ("Bộ sinh dữ liệu không in ra gì ở bộ %d. "
                               "Bộ sinh phải in dữ liệu vào ra stdout." % i)
            if size > MAX_INPUT_BYTES:
                return tests, ("Bộ %d sinh ra %d KB dữ liệu vào, vượt giới hạn %d KB."
                               % (i, size // 1024, MAX_INPUT_BYTES // 1024))

            out_path = sol_dir / ("%02d.out" % i)
            res = sandbox.run_limited(
                argv=[str(sol_bin)],
                cwd=sol_dir,
                stdin_path=in_path,
                stdout_path=out_path,
                stderr_path=sol_dir / ("%02d.err" % i),
                time_limit_ms=RUN_LIMIT_MS,
                memory_limit_mb=RUN_MEMORY_MB,
            )
            if res.killed_by_watchdog:
                return tests, ("Lời giải mẫu không kết thúc trong %d giây ở bộ %d. "
                               "Dữ liệu mà bộ sinh tạo ra có thể quá lớn."
                               % (RUN_LIMIT_MS // 1000, i))
            if res.exit_code != 0:
                return tests, ("Lời giải mẫu thoát với mã %d ở bộ %d. "
                               "Lời giải mẫu phải đọc stdin và in đáp án ra stdout."
                               % (res.exit_code, i))

            out_size = out_path.stat().st_size
            if out_size > MAX_INPUT_BYTES:
                return tests, ("Đáp án của bộ %d là %d KB, vượt giới hạn %d KB."
                               % (i, out_size // 1024, MAX_INPUT_BYTES // 1024))

            tests.append({
                "name": "sinh %02d" % i,
                "input": _read_text(in_path),
                "output": _read_text(out_path),
            })

        return tests, None

    finally:
        # Không dọn thì mỗi lần sinh lại bỏ lại vài chục tệp trong thư mục làm
        # việc, và thư mục đó nằm trên cùng ổ đĩa với CSDL.
        shutil.rmtree(workdir, ignore_errors=True)
