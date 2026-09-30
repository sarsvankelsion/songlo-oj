"""Chấm một bài nộp: dịch bằng g++, chạy từng bộ dữ liệu, so khớp đầu ra.

Tệp này không phụ thuộc Flask. Nó chỉ nhận một kết nối CSDL và một mã bài nộp,
nên có thể gọi từ worker chấm, từ một script dòng lệnh, hoặc từ bài kiểm thử.

Thứ tự phân loại kết quả được định nghĩa ở :data:`VERDICT_SEVERITY` và có lý do
cụ thể — xem chú thích ở đó.
"""

from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .sandbox import RunResult, read_capped, run_limited

# Giới hạn CPU mềm gửi SIGXCPU; giới hạn cứng gửi SIGKILL. Đọc qua getattr để
# tệp này vẫn nạp được trên hệ điều hành không có hai tín hiệu đó (chúng là đặc
# trưng của POSIX), thay vì làm sập cả tiến trình chấm lúc import.
SIGXCPU = getattr(signal, "SIGXCPU", 24)
SIGKILL = getattr(signal, "SIGKILL", 9)

# Cờ dịch. `-O2` vì đề thi nào cũng giả định mức tối ưu thông thường; `-Wall
# -Wextra` để cảnh báo hiện ra trong nhật ký dịch — phần lớn lỗi của học sinh
# (biến chưa dùng, so sánh sai kiểu, thiếu return) hiện ra ở đây trước cả khi
# bài chạy sai.
COMPILE_FLAGS = ["-std=c++17", "-O2", "-pipe", "-Wall", "-Wextra"]

# Dịch cần nhiều bộ nhớ và thời gian hơn hẳn chương trình lúc chạy. Đây là giới
# hạn cho chính g++, không phải cho bài của học sinh.
COMPILE_TIME_MS = 20_000
COMPILE_MEMORY_MB = 1024

# Thứ tự ưu tiên khi một bài sai ở nhiều bộ dữ liệu theo nhiều kiểu khác nhau.
# Số nhỏ hơn = nghiêm trọng hơn = được chọn làm kết quả chung.
#
# Vì sao MLE và TLE đứng trên WA: nếu một bài vừa quá thời gian vừa ra sai kết
# quả, nguyên nhân gốc gần như luôn là thuật toán chưa đủ nhanh, chứ không phải
# phép tính sai. Hiện "Quá thời gian" cho học sinh biết cần tối ưu thuật toán;
# hiện "Sai" sẽ khiến em đi tìm lỗi ở chỗ không có lỗi.
VERDICT_SEVERITY = {"IE": 0, "MLE": 1, "TLE": 2, "RE": 3, "WA": 4, "AC": 5}

VERDICT_LABEL = {
    "AC": "Đúng",
    "WA": "Sai",
    "TLE": "Quá thời gian",
    "MLE": "Quá bộ nhớ",
    "RE": "Lỗi khi chạy",
    "CE": "Lỗi dịch",
    "IE": "Lỗi hệ thống chấm",
}

# Tỉ lệ đỉnh bộ nhớ so với giới hạn để coi là "quá bộ nhớ" khi tiến trình chết
# bằng tín hiệu. Không dùng 1.0 vì RLIMIT_AS chặn ở mức cấp phát, nên đỉnh RSS
# đo được luôn thấp hơn giới hạn một chút.
MEMORY_PRESSURE_RATIO = 0.92


@dataclass
class TestOutcome:
    ordinal: int
    verdict: str
    time_ms: int
    memory_kb: int
    points: int
    message: str = ""
    input_seen: str = ""
    expected_seen: str = ""
    actual_seen: str = ""


@dataclass
class JudgeOutcome:
    verdict: str
    score: int
    max_score: int
    time_ms: int
    memory_kb: int
    compile_log: str = ""
    tests: list[TestOutcome] = field(default_factory=list)


# ------------------------------------------------------------------ tiện ích
def normalize_output(text: str) -> str:
    """Chuẩn hoá trước khi so khớp.

    Bỏ khoảng trắng cuối mỗi dòng và bỏ các dòng trống ở cuối. Đây là quy ước
    gần như phổ biến của các hệ thống chấm bài: một dấu cách thừa ở cuối dòng
    không phải là lỗi của học sinh, và bắt lỗi đó sẽ khiến các em mất điểm vì
    những thứ không liên quan tới thuật toán.

    Ngược lại, **không** bỏ khoảng trắng ở đầu dòng và **không** gộp dòng: với
    các bài in ra bảng hoặc hình, vị trí ký tự chính là nội dung.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def first_difference(expected: str, actual: str) -> str:
    """Mô tả ngắn gọn chỗ sai đầu tiên, để hiện trong cột Ghi chú."""
    exp = normalize_output(expected).split("\n")
    act = normalize_output(actual).split("\n")
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else None
        a = act[i] if i < len(act) else None
        if e != a:
            if e is None:
                return f"Thừa dòng thứ {i + 1}"
            if a is None:
                return f"Thiếu dòng thứ {i + 1}"
            return f"Dòng {i + 1}: mong đợi “{e}”, nhận “{a}”"
    return ""


def assign_points(total: int, mode: str, raw_points: list[int]) -> list[int]:
    """Chia điểm cho từng bộ dữ liệu.

    Chế độ chia đều không dùng phép chia lấy dư đơn giản, vì 100 điểm chia cho
    7 bộ sẽ ra 14,28… và tổng các phần chỉ đạt 98. Phần dư được phát cho những
    bộ đầu tiên để tổng luôn đúng bằng ``total``.
    """
    n = len(raw_points)
    if n == 0:
        return []
    if mode == "custom" and sum(raw_points) > 0:
        return list(raw_points)
    base, remainder = divmod(total, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


# -------------------------------------------------------------- dịch mã nguồn
def compile_source(
    workdir: Path,
    source: str,
    compiler: str = "g++",
    flags: list[str] | None = None,
) -> tuple[bool, str, Path]:
    """Dịch ``source`` trong ``workdir``. Trả (thành công, nhật ký, tệp chạy)."""
    src = workdir / "main.cpp"
    src.write_text(source, encoding="utf-8")

    # Mingw trên Windows luôn thêm đuôi ".exe" dù tên trong -o đã ghi rõ, nên
    # phải đoán đúng tên tệp trước khi kiểm tra nó có tồn tại hay không. Nếu
    # đoán sai, mọi bài nộp đều báo "trình dịch thành công nhưng không tạo ra
    # tệp thực thi" trong khi trình dịch hoàn toàn bình thường.
    output_name = "main.exe" if os.name == "nt" else "main"
    binary = workdir / output_name

    # Tìm trình dịch theo đường dẫn tuyệt đối. Môi trường của tiến trình con bị
    # thu hẹp về một PATH tối thiểu (xem `sandbox._child_env`), nên nếu để tên
    # trần "g++" thì trình dịch không nằm trong PATH đó và mọi bài nộp đều báo
    # không tìm thấy trình dịch.
    resolved = shutil.which(compiler)
    if resolved is None:
        return False, (
            f"Không tìm thấy trình dịch “{compiler}” trong PATH.\n\n"
            "Trên máy chủ cần cài gói g++ (ví dụ: apt install g++)."
        ), binary

    argv = [resolved] + (flags or COMPILE_FLAGS) + ["-o", output_name, "main.cpp"]
    out_path = workdir / "compile.stdout"
    err_path = workdir / "compile.stderr"

    try:
        result = run_limited(
            argv=argv,
            cwd=workdir,
            stdin_path=None,
            stdout_path=out_path,
            stderr_path=err_path,
            time_limit_ms=COMPILE_TIME_MS,
            memory_limit_mb=COMPILE_MEMORY_MB,
        )
    except FileNotFoundError:
        return False, f"Không tìm thấy trình dịch “{compiler}”. Kiểm tra lại gói g++ trên máy chấm.", binary

    log = read_capped(err_path, 32 * 1024).strip()
    stdout_log = read_capped(out_path, 8 * 1024).strip()
    header = "$ " + " ".join(argv)

    if result.killed_by_watchdog:
        return False, f"{header}\n\nDịch quá thời gian cho phép ({COMPILE_TIME_MS // 1000} giây).\n\n{log}", binary

    if result.exit_code != 0:
        return False, f"{header}\n$ echo $?\n{result.exit_code}\n\n{log}".strip(), binary

    if not binary.exists():
        return False, f"{header}\n\nTrình dịch báo thành công nhưng không tạo ra tệp thực thi.", binary

    # Dịch thành công vẫn có thể có cảnh báo. Giữ lại để hiện trong tab nhật ký:
    # phần lớn lỗi tràn số và so sánh sai kiểu hiện ra ở đây.
    body = f"{header}\n$ echo $?\n0\n\n"
    body += log if log else "Không có cảnh báo."
    if stdout_log:
        body += f"\n\n{stdout_log}"
    body += f"\nThời gian dịch: {result.wall_ms / 1000:.2f} giây"
    body += f"\nKích thước tệp thực thi: {binary.stat().st_size / (1024 * 1024):.1f} MB"
    return True, body, binary


# ------------------------------------------------------------ chạy một bộ dữ liệu
def _classify(result: RunResult, time_limit_ms: int, memory_limit_kb: int, expected: str, actual: str) -> tuple[str, str]:
    """Quyết định kết quả của một bộ dữ liệu. Trả (mã kết quả, ghi chú)."""
    if result.killed_by_watchdog:
        return "TLE", "Chương trình không kết thúc trong thời gian cho phép"

    # Giới hạn CPU mềm gửi SIGXCPU, giới hạn cứng gửi SIGKILL. Cả hai đều là
    # quá thời gian, nhưng phải loại trừ SIGKILL do chính đồng hồ canh giờ gửi
    # (đã xử lý ở nhánh trên).
    if result.term_signal in (SIGXCPU, SIGKILL):
        if result.cpu_ms >= time_limit_ms * 0.95:
            return "TLE", "Chương trình dùng quá thời gian CPU cho phép"

    # Kiểm tra bộ nhớ trước khi kiểm tra mã thoát: một chương trình hết bộ nhớ
    # thường chết bằng SIGABRT (C++ ném bad_alloc) hoặc SIGSEGV (C dùng malloc
    # trả về NULL), và nếu xét theo mã thoát thì sẽ bị xếp nhầm thành "lỗi khi
    # chạy" — trong khi nguyên nhân thật là dùng quá nhiều bộ nhớ.
    if result.memory_kb >= memory_limit_kb * MEMORY_PRESSURE_RATIO:
        used_mb = result.memory_kb / 1024
        limit_mb = memory_limit_kb / 1024
        if result.memory_kb >= memory_limit_kb:
            note = f"Dùng {used_mb:.0f} MB, vượt giới hạn {limit_mb:.0f} MB"
        else:
            # Đỉnh RSS đo được luôn thấp hơn giới hạn một chút (RLIMIT_AS chặn ở
            # mức cấp phát), nên bộ chấm coi là quá bộ nhớ ngay từ 92% giới hạn.
            # Ở dải 92–100% mà nói "vượt giới hạn" là mâu thuẫn với chính con số
            # hiển thị ngay bên cạnh: "Dùng 255 MB, vượt giới hạn 256 MB".
            note = (
                f"Dùng {used_mb:.0f} MB, chạm ngưỡng an toàn "
                f"{limit_mb * MEMORY_PRESSURE_RATIO:.0f} MB "
                f"({MEMORY_PRESSURE_RATIO:.0%} của giới hạn {limit_mb:.0f} MB)"
            )
        return "MLE", note

    if result.term_signal is not None:
        return "RE", f"Chương trình bị dừng bởi tín hiệu {result.term_signal} ({_signal_name(result.term_signal)})"
    if result.exit_code != 0:
        return "RE", f"Chương trình thoát với mã {result.exit_code}"

    if normalize_output(actual) != normalize_output(expected):
        note = first_difference(expected, actual)
        return "WA", note or "Kết quả không khớp"

    return "AC", ""


def _signal_name(sig: int) -> str:
    try:
        return signal.Signals(sig).name
    except (ValueError, AttributeError):
        return "không rõ"


# ------------------------------------------------------------------- chấm bài
def judge_submission(
    conn: sqlite3.Connection,
    submission_id: int,
    workspace_root: Path,
    compiler: str = "g++",
) -> JudgeOutcome:
    """Chấm một bài nộp và ghi kết quả vào CSDL."""
    sub = db.query_one(
        conn,
        """SELECT s.*, p.code AS problem_code, p.time_limit_ms, p.memory_limit_mb,
                  p.points_mode
             FROM submissions s JOIN problems p ON p.id = s.problem_id
            WHERE s.id = ?""",
        (submission_id,),
    )
    if sub is None:
        raise ValueError(f"Không có bài nộp #{submission_id}")

    tests = db.query(
        conn,
        "SELECT * FROM tests WHERE problem_id = ? ORDER BY ordinal",
        (sub["problem_id"],),
    )

    total_points = 100
    points = assign_points(total_points, sub["points_mode"], [t["points"] for t in tests])
    max_score = sum(points)

    if not tests:
        outcome = JudgeOutcome(
            verdict="IE",
            score=0,
            max_score=0,
            time_ms=0,
            memory_kb=0,
            compile_log="",
        )
        _write_results(conn, submission_id, outcome, "Đề bài chưa có bộ dữ liệu nào nên không thể chấm.")
        return outcome

    workspace_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"sub{submission_id}-", dir=str(workspace_root)))

    try:
        ok, compile_log, binary = compile_source(workdir, sub["source"], compiler=compiler)
        if not ok:
            outcome = JudgeOutcome(
                verdict="CE",
                score=0,
                max_score=max_score,
                time_ms=0,
                memory_kb=0,
                compile_log=compile_log,
            )
            _write_results(conn, submission_id, outcome, "Dịch không thành công.")
            return outcome

        outcomes: list[TestOutcome] = []
        time_limit_kb = sub["memory_limit_mb"] * 1024

        for test, test_points in zip(tests, points):
            ordinal = test["ordinal"]
            in_path = workdir / f"{ordinal:02d}.in"
            out_path = workdir / f"{ordinal:02d}.out"
            err_path = workdir / f"{ordinal:02d}.err"
            in_path.write_text(test["input"], encoding="utf-8")

            result = run_limited(
                argv=[str(binary)],
                cwd=workdir,
                stdin_path=in_path,
                stdout_path=out_path,
                stderr_path=err_path,
                time_limit_ms=sub["time_limit_ms"],
                memory_limit_mb=sub["memory_limit_mb"],
            )

            actual = read_capped(out_path)
            verdict, note = _classify(
                result, sub["time_limit_ms"], time_limit_kb, test["output"], actual
            )

            # Với bộ dữ liệu ẩn, không ghi nội dung vào CSDL. Nếu chỉ giấu ở tầng
            # hiển thị thì một lỗi ở template cũng đủ làm lộ đề, còn ở đây thì
            # không có gì để lộ.
            hidden = bool(test["is_hidden"])
            outcomes.append(
                TestOutcome(
                    ordinal=ordinal,
                    verdict=verdict,
                    time_ms=result.cpu_ms if result.cpu_ms > 0 else result.wall_ms,
                    memory_kb=result.memory_kb,
                    points=test_points if verdict == "AC" else 0,
                    message=note if not hidden or verdict == "AC" else _hide_detail(note),
                    input_seen="" if hidden else test["input"],
                    expected_seen="" if hidden else test["output"],
                    actual_seen="" if hidden else actual,
                )
            )

        overall = _overall_verdict(outcomes)
        outcome = JudgeOutcome(
            verdict=overall,
            score=sum(o.points for o in outcomes),
            max_score=max_score,
            time_ms=max(o.time_ms for o in outcomes),
            memory_kb=max(o.memory_kb for o in outcomes),
            compile_log=compile_log,
            tests=outcomes,
        )
        _write_results(conn, submission_id, outcome, "")
        return outcome

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _hide_detail(note: str) -> str:
    """Rút gọn ghi chú cho bộ dữ liệu ẩn.

    Ghi chú kiểu ``Dòng 1: mong đợi “3000000000”, nhận “-1294967296”`` chính là
    nội dung của bộ dữ liệu ẩn. Học sinh chỉ được biết bộ đó sai, không được
    biết nó chứa gì.
    """
    return "Bộ dữ liệu ẩn không đạt" if note else ""


def _overall_verdict(outcomes: list[TestOutcome]) -> str:
    if all(o.verdict == "AC" for o in outcomes):
        return "AC"
    worst = min(
        (o for o in outcomes if o.verdict != "AC"),
        key=lambda o: VERDICT_SEVERITY.get(o.verdict, 9),
    )
    return worst.verdict


def _write_results(
    conn: sqlite3.Connection,
    submission_id: int,
    outcome: JudgeOutcome,
    log_message: str,
) -> None:
    """Ghi kết quả vào CSDL trong một giao dịch."""
    with conn:
        conn.execute("DELETE FROM test_results WHERE submission_id = ?", (submission_id,))
        for t in outcome.tests:
            conn.execute(
                """INSERT INTO test_results
                     (submission_id, ordinal, verdict, time_ms, memory_kb, points, message,
                      input_seen, expected_seen, actual_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    submission_id, t.ordinal, t.verdict, t.time_ms, t.memory_kb,
                    t.points, t.message, t.input_seen, t.expected_seen, t.actual_seen,
                ),
            )

        conn.execute(
            """UPDATE submissions
                  SET status = 'done', verdict = ?, score = ?, max_score = ?,
                      time_ms = ?, memory_kb = ?, compile_log = ?, judged_at = ?
                WHERE id = ?""",
            (
                outcome.verdict, outcome.score, outcome.max_score,
                outcome.time_ms, outcome.memory_kb, outcome.compile_log,
                db.utc_now(), submission_id,
            ),
        )

        if log_message:
            conn.execute(
                "INSERT INTO judge_log (submission_id, at, level, message) VALUES (?, ?, ?, ?)",
                (submission_id, db.utc_now(), "error", log_message),
            )
