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

Một điều phải biết về **quyền** khi chạy trên máy chủ thật: hàm này được gọi từ
tiến trình web (gunicorn), mà trên máy chủ đó tiến trình web chạy bằng tài khoản
``songlo`` chứ không phải ``root``. Bộ chấm bài thì chạy bằng ``root`` nên hạ được
quyền trước khi chạy mã học sinh (xem ``sandbox._run_posix``); tiến trình web thì
không, và ``sandbox`` nuốt lỗi hạ quyền một cách có chủ ý. Hệ quả: **chương trình
do giáo viên gửi lên chạy với quyền của tài khoản web**, không phải quyền của tài
khoản hạ quyền. Vì thế thư mục làm việc ở đây phải là thư mục **riêng**, do tài
khoản web sở hữu — không dùng chung với thư mục chấm bài, vốn thuộc ``root``.

Muốn bỏ hẳn khác biệt đó thì phải chuyển việc sinh dữ liệu sang tiến trình chấm
(``worker.py``) và cho nó thành một việc trong hàng đợi. Đó là việc lớn hơn, và
là việc tiếp theo nếu trường muốn mở quyền soạn đề cho nhiều giáo viên hơn.
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
# Bị chặn bởi hai thứ nằm ngoài tệp này, và cái chặt hơn lại không phải cái dễ
# thấy:
#
#   1. Cloudflare đứng trước tên miền, và nó cắt yêu cầu gốc ở **100 giây**
#      (lỗi 524). Đây mới là trần thật.
#   2. `songlo-web` chạy gunicorn với `--timeout 120`.
#
# Bản trước để 20 giây, kèm ghi chú rằng gunicorn "mặc định 30 giây". Ghi chú đó
# đã cũ từ lâu, và cái giá của nó là thật: giáo viên xin 20 bộ, mỗi bộ mất ~2,9
# giây, nên chỉ nhận được **7 bộ** rồi thấy một câu báo lỗi — trong khi máy chủ
# còn thừa bốn lần thời gian. Đo được: cùng một bộ sinh, ngân sách 20 giây cho 8
# bộ, ngân sách 75 giây cho đủ 20.
#
# 80 giây chừa 20 giây dưới trần Cloudflare. Một yêu cầu vượt trần thì giáo viên
# nhận trang lỗi và **không biết đã sinh được bao nhiêu**; dừng sớm và báo rõ đã
# làm tới đâu thì hơn hẳn.
TOTAL_BUDGET_MS = 80_000


def _read_text(path: Path) -> str:
    """Đọc một tệp dữ liệu đã sinh. Giải mã chịu lỗi để không ném ra ở đây."""
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def _stop_reason(res, limit_ms: int, who: str) -> str | None:
    """Vì sao tiến trình bị dừng giữa đường, hoặc ``None`` nếu nó tự thoát.

    Phải tách hai đường, vì chúng bị dừng theo hai cách **khác nhau trên hai hệ
    điều hành** và gộp lại thì thông báo sai:

    - **Đồng hồ giờ thực** (``killed_by_watchdog``): chương trình không dùng CPU
      mà vẫn treo — ngủ, hoặc chờ đọc dữ liệu vào. Xảy ra giống nhau ở mọi nền
      tảng.
    - **Giới hạn CPU**: trên Linux, ``RLIMIT_CPU`` gửi ``SIGXCPU`` rồi
      ``SIGKILL``, nên tiến trình chết vì **tín hiệu** và mã thoát là ``-1``. Nếu
      chỉ kiểm ``exit_code != 0`` thì giáo viên nhận câu "thoát với mã -1" — một
      con số không có nghĩa gì với họ, và không nói gì về việc đã vượt thời gian.
      Trên Windows thì ``RLIMIT_CPU`` không có, nên cùng chương trình đó lại bị
      đồng hồ giờ thực giết và rơi vào nhánh trên.
    """
    if res.killed_by_watchdog:
        return "%s không kết thúc trong %d giây" % (who, limit_ms // 1000)
    # Lấy hai hằng số từ `judge` chứ không đọc `signal` trực tiếp: `SIGXCPU` và
    # `SIGKILL` không tồn tại trên Windows, và `judge` đã có sẵn bản `getattr` có
    # giá trị dự phòng. Đọc thẳng `signal.SIGXCPU` ở đây sẽ ném `AttributeError`
    # ngay khi dựng tuple — kể cả khi tiến trình chết vì lý do khác.
    if res.term_signal in (judge.SIGXCPU, judge.SIGKILL):
        return "%s dùng quá %d giây CPU cho phép" % (who, limit_ms // 1000)
    if res.term_signal is not None:
        return "%s bị dừng bởi tín hiệu %d" % (who, res.term_signal)
    return None


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
            if res.killed_by_watchdog or res.term_signal is not None:
                reason = _stop_reason(res, RUN_LIMIT_MS, "Bộ sinh dữ liệu")
                return tests, reason + " ở bộ %d." % i
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
            if res.killed_by_watchdog or res.term_signal is not None:
                reason = _stop_reason(res, RUN_LIMIT_MS, "Lời giải mẫu")
                return tests, reason + (
                    " ở bộ %d. Dữ liệu mà bộ sinh tạo ra có thể quá lớn." % i)
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
