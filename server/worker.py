"""Tiến trình chấm bài: nhận bài nộp từ hàng đợi và chấm.

Chạy tách khỏi tiến trình web. Hai lý do, cả hai đều là lý do kỹ thuật chứ không
phải sở thích kiến trúc:

1. **An toàn của ``preexec_fn``.** Tầng chạy tiến trình con cần đặt giới hạn tài
   nguyên giữa ``fork()`` và ``exec()``, và tài liệu Python nói rõ thao tác đó
   không an toàn khi tiến trình có nhiều luồng. Tiến trình web có nhiều luồng
   (mỗi request một luồng), nên nếu chấm ngay trong đó thì thỉnh thoảng một bài
   nộp sẽ treo vô cớ và rất khó tái hiện. Tiến trình này là đơn luồng nên không
   có vấn đề đó.

2. **Một bài nộp không làm chậm cả hệ thống.** Dịch và chạy là việc nặng. Nếu
   làm trong tiến trình web, một bài nộp có vòng lặp vô hạn sẽ chiếm mất một
   worker của web server.

Chạy:

    python -m server.worker                # chạy mãi, chấm liên tục
    python -m server.worker --once         # chấm hết hàng đợi rồi thoát
    python -m server.worker --recover      # trả các bài kẹt về hàng đợi rồi thoát
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time
from pathlib import Path

from . import db, judge

# Sau bao lâu thì coi một bài "đang chấm" là kẹt. Một bài chấm bình thường mất
# vài giây; quá 10 phút nghĩa là tiến trình chấm đã chết giữa chừng (mất điện,
# bị kill, hoặc gặp lỗi không bắt được) và bài đó sẽ nằm mãi ở trạng thái
# "đang chấm" nếu không có bước thu hồi này.
STALE_JUDGING_SECONDS = 600

IDLE_SLEEP_SECONDS = 0.5
MAX_IDLE_SLEEP_SECONDS = 5.0

_running = True


def _handle_stop(signum, _frame):
    """Dừng êm khi systemd gửi SIGTERM, thay vì chết giữa lúc đang chấm."""
    global _running
    _running = False
    print(f"[judge] nhận tín hiệu {signum}, sẽ dừng sau bài đang chấm", flush=True)


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def recover_stale(conn, older_than_seconds: int = STALE_JUDGING_SECONDS) -> int:
    """Trả những bài nộp bị kẹt ở trạng thái 'judging' về lại hàng đợi."""
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    with conn:
        cur = conn.execute(
            """UPDATE submissions
                  SET status = 'pending', claimed_at = NULL, claimed_by = NULL
                WHERE status = 'judging' AND (claimed_at IS NULL OR claimed_at < ?)""",
            (cutoff,),
        )
        n = cur.rowcount
    if n:
        conn.execute(
            "INSERT INTO judge_log (submission_id, at, level, message) VALUES (NULL, ?, ?, ?)",
            (db.utc_now(), "warn", f"Thu hồi {n} bài nộp bị kẹt ở trạng thái đang chấm"),
        )
        conn.commit()
    return n


def claim_next(conn, who: str) -> int | None:
    """Giành quyền chấm bài nộp cũ nhất đang chờ. Trả về mã bài nộp hoặc None.

    Dùng ``BEGIN IMMEDIATE`` chứ không để SQLite tự mở giao dịch: chế độ mặc
    định là giao dịch hoãn, nghĩa là đọc trước rồi mới xin khoá ghi. Hai tiến
    trình chấm cùng đọc thấy một bài, rồi lần lượt ghi — cả hai đều tưởng mình
    đã giành được. ``BEGIN IMMEDIATE`` xin khoá ghi ngay từ đầu nên chỉ một
    tiến trình vào được. Điều kiện ``status = 'pending'`` trong câu UPDATE là
    lớp bảo vệ thứ hai, và ``rowcount`` là lớp thứ ba.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT id FROM submissions WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        cur = conn.execute(
            """UPDATE submissions
                  SET status = 'judging', claimed_at = ?, claimed_by = ?
                WHERE id = ? AND status = 'pending'""",
            (db.utc_now(), who, row["id"]),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return None
        conn.execute("COMMIT")
        return row["id"]
    except Exception:
        # Chỉ lùi khi thật sự đang có giao dịch. Nếu lỗi xảy ra sau câu COMMIT
        # (ví dụ Ctrl-C đúng lúc đó), giao dịch đã đóng và một lệnh ROLLBACK vô
        # điều kiện sẽ ném OperationalError — lỗi này thay thế lỗi gốc và làm
        # cho nguyên nhân thật biến mất khỏi dấu vết.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def judge_one(conn, submission_id: int, workspace: Path) -> None:
    who = worker_id()
    try:
        outcome = judge.judge_submission(conn, submission_id, workspace)
        print(
            f"[judge] #{submission_id}: {outcome.verdict} "
            f"{outcome.score}/{outcome.max_score} điểm, "
            f"{outcome.time_ms} ms, {outcome.memory_kb} KB",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        # Bắt mọi lỗi để một bài nộp hỏng không làm chết cả tiến trình chấm.
        # Không có nhánh này thì một đề cấu hình sai sẽ khiến worker thoát và
        # toàn bộ hàng đợi đứng yên cho tới khi có người nhận ra.
        conn.rollback()
        with conn:
            conn.execute(
                """UPDATE submissions
                      SET status = 'error', verdict = 'IE', judged_at = ?
                    WHERE id = ?""",
                (db.utc_now(), submission_id),
            )
            conn.execute(
                "INSERT INTO judge_log (submission_id, at, level, message) VALUES (?, ?, ?, ?)",
                (submission_id, db.utc_now(), "error", f"{type(exc).__name__}: {exc}"),
            )
        print(f"[judge] #{submission_id}: lỗi hệ thống — {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tiến trình chấm bài Song Lo OJ")

    # Đường dẫn mặc định suy ra từ SONGLO_VAR, đúng như cách `app.py` làm. Nếu
    # để hai tiến trình tự tính theo hai cách khác nhau thì một lần đặt sai biến
    # môi trường sẽ khiến tiến trình web ghi vào CSDL này còn tiến trình chấm
    # đọc CSDL khác. Triệu chứng là "nộp bài mãi không chấm xong", và rất khó
    # lần ra vì cả hai tiến trình đều chạy bình thường.
    var_dir = Path(os.environ.get("SONGLO_VAR", Path(__file__).resolve().parent / "var"))

    parser.add_argument("--database", default=os.environ.get("SONGLO_DB", str(var_dir / "songlo.db")),
                        help="đường dẫn tệp CSDL SQLite")
    parser.add_argument("--workspace", default=os.environ.get("SONGLO_JUDGE_WORKSPACE", str(var_dir / "judge")),
                        help="thư mục làm việc tạm khi dịch và chạy bài")
    parser.add_argument("--compiler", default=os.environ.get("SONGLO_COMPILER", "g++"))
    parser.add_argument("--once", action="store_true",
                        help="chấm hết hàng đợi hiện có rồi thoát")
    parser.add_argument("--recover", action="store_true",
                        help="chỉ thu hồi các bài bị kẹt rồi thoát")
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    # Không tự tạo CSDL khi tệp chưa có.
    #
    # Theo `deploy/README.md`, tiến trình chấm chạy bằng root; tiến trình web
    # chạy bằng một tài khoản riêng. Nếu tệp CSDL chưa tồn tại thì `init_db` sẽ
    # tạo nó **thuộc root**, và từ đó tiến trình web không ghi được vào nữa.
    # Triệu chứng đến rất muộn và rất khó đoán: web chạy bình thường, đăng nhập
    # bình thường, chỉ tới khi học sinh nộp bài mới hỏng.
    #
    # Tạo CSDL là việc của `server.seed`, và phải chạy bằng chính tài khoản của
    # tiến trình web. Ở đây chỉ áp lược đồ lên một CSDL đã có.
    if not Path(args.database).exists():
        print(f"[judge] không thấy CSDL ở {args.database}.\n"
              f"        Hãy chạy `python -m server.seed` bằng tài khoản của tiến trình web\n"
              f"        (không phải root) trước khi bật tiến trình chấm.",
              file=sys.stderr, flush=True)
        return 2

    db.init_db(args.database)
    conn = db.connect(args.database)
    workspace = Path(args.workspace)

    who = worker_id()
    print(f"[judge] khởi động {who}; CSDL {args.database}; trình dịch {args.compiler}", flush=True)

    recovered = recover_stale(conn)
    if recovered:
        print(f"[judge] thu hồi {recovered} bài nộp bị kẹt", flush=True)

    if args.recover:
        return 0

    idle_sleep = IDLE_SLEEP_SECONDS
    while _running:
        submission_id = claim_next(conn, who)
        if submission_id is None:
            if args.once:
                break
            time.sleep(idle_sleep)
            # Tăng dần thời gian chờ khi hàng đợi rỗi, nhưng có trần: chờ lâu
            # quá thì một bài mới nộp sẽ phải đợi vô ích.
            idle_sleep = min(idle_sleep * 1.5, MAX_IDLE_SLEEP_SECONDS)
            continue

        idle_sleep = IDLE_SLEEP_SECONDS
        judge_one(conn, submission_id, workspace)

        # Kiểm tra định kỳ các bài bị kẹt, phòng trường hợp có tiến trình chấm
        # khác đã chết giữa chừng.
        if submission_id % 50 == 0:
            recover_stale(conn)

    conn.close()
    print("[judge] đã dừng", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
