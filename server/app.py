"""Ứng dụng Flask: các tuyến đường và truy vấn.

Cách chạy (xem thêm README.md):

    python -m server.seed          # tạo CSDL và dữ liệu mẫu
    python -m server.app           # chạy máy chủ phát triển
    python -m server.worker        # tiến trình chấm bài, mở một cửa sổ khác

Một quyết định về thư mục tĩnh: ``static_folder`` trỏ vào ``../demo/assets``
chứ không phải một thư mục riêng. ``demo/`` là bản tham chiếu tĩnh của giao diện
và cũng là nơi chứa ``style.css``/``app.js``. Trỏ vào đó nghĩa là chỉ có **một**
bản CSS duy nhất cho cả bản demo lẫn bản chạy thật; nếu tách ra thành hai bản,
sửa giao diện ở một chỗ sẽ khiến chỗ kia lệch đi mà không ai nhận ra.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, url_for,
)

from . import auth, db, formatting
from .judge import VERDICT_LABEL

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# Số lượt nộp tối đa cho một học sinh trên một đề trong một ngày.
DAILY_SUBMIT_LIMIT = 20

# Độ dài tối đa của mã nguồn, tính bằng ký tự. 64 KB tương đương khoảng 2 000
# dòng — thừa sức cho mọi bài của cấp 2, nhưng chặn được việc ai đó dán cả một
# tệp nén vào ô soạn thảo.
MAX_SOURCE_LENGTH = 64 * 1024

# Khung mã nguồn điền sẵn khi mở ô soạn thảo.
#
# Đây không phải chuyện thẩm mỹ: một ô trống hoàn toàn khiến học sinh lớp 7 phải
# nhớ lại từ đầu cả `#include` lẫn cấu trúc `main`, và trên thực tế phần lớn lỗi
# dịch của học sinh mới là lỗi ở những dòng này chứ không phải ở thuật toán. Có
# sẵn khung thì bài nộp đầu tiên đã chạy được, và các em tập trung vào phần tính
# toán. Cũng đặt luôn `long long` cho hai biến để lỗi tràn số — lỗi phổ biến
# nhất ở dạng bài này — không còn là lỗi mặc định.
_STARTER_CODE = """#include <iostream>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    // Viết bài giải ở đây.

    return 0;
}"""


# ==========================================================================
# Khởi tạo ứng dụng
# ==========================================================================
def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(PROJECT_DIR / "demo" / "assets"),
        static_url_path="/assets",
    )

    var_dir = Path(os.environ.get("SONGLO_VAR", BASE_DIR / "var"))
    app.config.update(
        # Khoá ký cookie phiên. Phải cố định giữa các lần khởi động, nếu không
        # mọi người dùng bị đăng xuất sau mỗi lần restart. Giá trị mặc định chỉ
        # dùng cho môi trường phát triển; khi chạy thật phải đặt qua biến môi
        # trường SONGLO_SECRET.
        SECRET_KEY=os.environ.get("SONGLO_SECRET", "dev-only-doi-khoa-nay-khi-chay-that"),
        DATABASE=str(var_dir / "songlo.db"),
        JUDGE_WORKSPACE=str(var_dir / "judge"),
        COMPILER=os.environ.get("SONGLO_COMPILER", "g++"),
        DAILY_SUBMIT_LIMIT=DAILY_SUBMIT_LIMIT,
        MAX_SOURCE_LENGTH=MAX_SOURCE_LENGTH,
    )
    if config:
        app.config.update(config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db.init_db(app.config["DATABASE"])

    app.teardown_appcontext(db.close_db)
    auth.init_app(app)
    formatting.register_filters(app)

    _register_routes(app)
    _register_error_handlers(app)
    return app


# ==========================================================================
# Truy vấn dùng chung
# ==========================================================================
def _class_names(conn) -> list[str]:
    rows = db.query(
        conn,
        "SELECT DISTINCT class_name FROM users WHERE class_name <> '' ORDER BY class_name",
    )
    return [r["class_name"] for r in rows]


def _topics(conn) -> list[str]:
    rows = db.query(
        conn,
        "SELECT DISTINCT topic FROM problems WHERE topic <> '' AND status = 'live' ORDER BY topic",
    )
    return [r["topic"] for r in rows]


def _user_best_by_problem(conn, user_id: int) -> dict[int, int]:
    """Điểm cao nhất của một học sinh cho mỗi đề. Dùng để hiện chấm trạng thái."""
    rows = db.query(
        conn,
        """SELECT problem_id, MAX(score) AS best, MAX(max_score) AS max_score
             FROM submissions
            WHERE user_id = ? AND status = 'done'
            GROUP BY problem_id""",
        (user_id,),
    )
    out = {}
    for r in rows:
        if r["max_score"] and r["best"] >= r["max_score"]:
            out[r["problem_id"]] = 2      # đã giải đúng
        elif r["best"] > 0:
            out[r["problem_id"]] = 1      # đã nộp, chưa đúng
        else:
            out[r["problem_id"]] = 1
    return out


def _daily_submission_count(conn, user_id: int, problem_id: int) -> int:
    """Số lượt nộp hôm nay (theo giờ Việt Nam) cho một đề.

    Cắt ngày theo giờ Việt Nam chứ không theo UTC: nếu cắt theo UTC thì hạn mức
    sẽ được đặt lại lúc 7 giờ sáng giờ Việt Nam, đúng giữa buổi học.
    """
    start_local = db.to_local(db.utc_now()).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return db.scalar(
        conn,
        """SELECT COUNT(*) FROM submissions
            WHERE user_id = ? AND problem_id = ? AND created_at >= ?""",
        (user_id, problem_id, start_utc),
    )


def _contest_phase(row) -> str:
    """Giai đoạn của kỳ thi, tính từ thời gian thực chứ không đọc cột status.

    Cột ``status`` trong CSDL là trạng thái biên tập do giáo viên đặt. Còn đây
    là trạng thái theo đồng hồ. Hiển thị theo đồng hồ là đúng, vì nếu giáo viên
    quên đổi trạng thái thì kỳ thi vẫn phải tự mở và tự đóng đúng giờ.
    """
    if row["status"] == "draft":
        return "draft"
    now = db.utc_now()
    if now < row["starts_at"]:
        return "upcoming"
    if now <= row["ends_at"]:
        return "open"
    return "closed"


def _enqueue_submission(conn, user_id: int, problem_id: int, source: str,
                        contest_id: int | None = None) -> int:
    """Ghi một bài nộp mới ở trạng thái chờ chấm. Trả về mã bài nộp."""
    with conn:
        cur = conn.execute(
            """INSERT INTO submissions
                 (problem_id, user_id, contest_id, language, source, status, created_at)
               VALUES (?, ?, ?, 'cpp17', ?, 'pending', ?)""",
            (problem_id, user_id, contest_id, source, db.utc_now()),
        )
    return cur.lastrowid


# ==========================================================================
# Các tuyến đường
# ==========================================================================
def _register_routes(app: Flask) -> None:

    # ---------------------------------------------------------------- trang chủ
    @app.route("/")
    def index():
        conn = db.get_db()
        user = auth.current_user()

        stats = {
            "problems": db.scalar(
                conn, "SELECT COUNT(*) FROM problems WHERE status = 'live'"),
            "problems_this_month": db.scalar(
                conn,
                "SELECT COUNT(*) FROM problems WHERE status = 'live' AND created_at >= ?",
                (_month_start_utc(),),
            ),
            "submissions": db.scalar(conn, "SELECT COUNT(*) FROM submissions"),
            "accepted": db.scalar(
                conn, "SELECT COUNT(*) FROM submissions WHERE verdict = 'AC'"),
            "students": db.scalar(
                conn, "SELECT COUNT(*) FROM users WHERE role = 'student'"),
            "classes": db.scalar(
                conn, "SELECT COUNT(DISTINCT class_name) FROM users WHERE class_name <> ''"),
        }
        stats["accept_rate"] = (
            round(stats["accepted"] / stats["submissions"] * 100)
            if stats["submissions"] else 0
        )

        # Kỳ thi gần nhất chưa kết thúc, để hiện đồng hồ đếm ngược trên trang chủ.
        next_contest = db.query_one(
            conn,
            """SELECT * FROM contests
                WHERE status <> 'draft' AND ends_at >= ?
                ORDER BY starts_at LIMIT 1""",
            (db.utc_now(),),
        )
        open_contests = db.scalar(
            conn,
            "SELECT COUNT(*) FROM contests WHERE status <> 'draft' AND starts_at <= ? AND ends_at >= ?",
            (db.utc_now(), db.utc_now()),
        )

        new_problems = db.query(
            conn,
            """SELECT p.*,
                      (SELECT COUNT(DISTINCT s.user_id) FROM submissions s
                        WHERE s.problem_id = p.id AND s.verdict = 'AC') AS solved_by
                 FROM problems p
                WHERE p.status = 'live'
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 5""",
        )

        leaderboard = _leaderboard_rows(conn, scope=None, limit=5)
        recent = _recent_submissions(conn, limit=5)
        recent = [_decorate_submission(r) for r in recent]

        return render_template(
            "index.html",
            active="index",
            stats=stats,
            next_contest=next_contest,
            contest_phase=_contest_phase(next_contest) if next_contest else None,
            open_contests=open_contests,
            new_problems=new_problems,
            leaderboard=leaderboard,
            recent=recent,
            user=user,
        )

    # ---------------------------------------------------------------- đề bài
    @app.route("/problems")
    def problems():
        conn = db.get_db()
        user = auth.current_user()

        q = (request.args.get("q") or "").strip()
        topic = (request.args.get("topic") or "").strip()
        difficulty = (request.args.get("difficulty") or "").strip()
        mine = (request.args.get("mine") or "").strip()

        where = ["p.status = 'live'"]
        params: list = []
        if q:
            where.append("(p.code LIKE ? OR p.name LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if topic:
            where.append("p.topic = ?")
            params.append(topic)
        if difficulty:
            where.append("p.difficulty = ?")
            params.append(difficulty)

        rows = db.query(
            conn,
            f"""SELECT p.*,
                       (SELECT COUNT(DISTINCT s.user_id) FROM submissions s
                         WHERE s.problem_id = p.id AND s.verdict = 'AC') AS solved_by,
                       (SELECT COUNT(*) FROM submissions s WHERE s.problem_id = p.id) AS attempts
                  FROM problems p
                 WHERE {' AND '.join(where)}
                 ORDER BY p.code""",
            params,
        )

        solved_map = _user_best_by_problem(conn, user["id"]) if user else {}
        items = []
        for r in rows:
            state = solved_map.get(r["id"], 0)
            if mine == "solved" and state != 2:
                continue
            if mine == "unsolved" and state == 2:
                continue
            if mine == "attempted" and state != 1:
                continue
            d = dict(r)
            d["my_state"] = state
            d["accept_rate"] = round(r["solved_by"] / r["attempts"] * 100) if r["attempts"] else 0
            items.append(d)

        total_live = db.scalar(conn, "SELECT COUNT(*) FROM problems WHERE status = 'live'")

        return render_template(
            "problems.html",
            active="problems",
            problems=items,
            total=total_live,
            topics=_topics(conn),
            classes=_class_names(conn),
            filters={"q": q, "topic": topic, "difficulty": difficulty, "mine": mine},
        )

    @app.route("/problems/<code>")
    def problem_detail(code: str):
        conn = db.get_db()
        user = auth.current_user()

        problem = db.query_one(
            conn,
            "SELECT * FROM problems WHERE code = ? AND status <> 'draft'",
            (code,),
        )
        if problem is None:
            abort(404)

        tests = db.query(
            conn,
            "SELECT ordinal, is_hidden, points FROM tests WHERE problem_id = ? ORDER BY ordinal",
            (problem["id"],),
        )

        # Bài nộp gần nhất của chính người đang xem, để hiện trong tab kết quả.
        latest = None
        if user:
            latest = db.query_one(
                conn,
                """SELECT * FROM submissions
                    WHERE user_id = ? AND problem_id = ?
                    ORDER BY id DESC LIMIT 1""",
                (user["id"], problem["id"]),
            )

        latest_tests = []
        if latest and latest["status"] == "done":
            latest_tests = db.query(
                conn,
                "SELECT * FROM test_results WHERE submission_id = ? ORDER BY ordinal",
                (latest["id"],),
            )
        passed_count = sum(1 for t in latest_tests if t["verdict"] == "AC")

        # Đánh dấu bộ nào là bộ ẩn, để bảng kết quả hiện được nhãn "ẩn" mà không
        # phải lộ nội dung. Lấy từ bảng `tests` chứ không suy từ `test_results`,
        # vì `test_results` cố tình để trống nội dung của bộ ẩn.
        hidden_ordinals = {
            t["ordinal"] for t in tests if t["is_hidden"]
        }

        # Vài bộ công khai đầu tiên, hiện làm ví dụ trong phần đề bài. Giới hạn
        # ở hai bộ: đó là số ví dụ một đề cấp 2 cần, và hiện hết 20 bộ sẽ làm
        # phần đề bài dài không đọc được.
        sample_tests = db.query(
            conn,
            """SELECT input, output FROM tests
                WHERE problem_id = ? AND is_hidden = 0
                ORDER BY ordinal LIMIT 2""",
            (problem["id"],),
        )

        my_submissions = []
        remaining = None
        if user:
            my_submissions = db.query(
                conn,
                """SELECT * FROM submissions
                    WHERE user_id = ? AND problem_id = ?
                    ORDER BY id DESC LIMIT 8""",
                (user["id"], problem["id"]),
            )
            used = _daily_submission_count(conn, user["id"], problem["id"])
            remaining = max(0, app.config["DAILY_SUBMIT_LIMIT"] - used)

        solved_by = db.scalar(
            conn,
            "SELECT COUNT(DISTINCT user_id) FROM submissions WHERE problem_id = ? AND verdict = 'AC'",
            (problem["id"],),
        )

        return render_template(
            "problem.html",
            active="problems",
            problem=problem,
            tests=tests,
            latest=latest,
            latest_tests=latest_tests,
            passed_count=passed_count,
            hidden_ordinals=hidden_ordinals,
            sample_tests=sample_tests,
            starter_code=_STARTER_CODE,
            my_submissions=my_submissions,
            remaining=remaining,
            daily_limit=app.config["DAILY_SUBMIT_LIMIT"],
            solved_by=solved_by,
            visible_tests=sum(1 for t in tests if not t["is_hidden"]),
            hidden_tests=sum(1 for t in tests if t["is_hidden"]),
        )

    @app.route("/problems/<code>/submit", methods=["POST"])
    @auth.login_required
    def problem_submit(code: str):
        conn = db.get_db()
        user = auth.current_user()

        problem = db.query_one(
            conn, "SELECT * FROM problems WHERE code = ? AND status <> 'draft'", (code,))
        if problem is None:
            abort(404)

        source = request.form.get("source") or ""
        if not source.strip():
            flash("Em chưa nhập mã nguồn.", "warn")
            return redirect(url_for("problem_detail", code=code) + "#panel-submit")

        if len(source) > app.config["MAX_SOURCE_LENGTH"]:
            flash("Mã nguồn quá dài. Giới hạn là 64 KB.", "warn")
            return redirect(url_for("problem_detail", code=code) + "#panel-submit")

        if db.scalar(
            conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?", (problem["id"],)
        ) == 0:
            flash("Đề này chưa có bộ dữ liệu nên chưa chấm được. Em báo giáo viên giúp nhé.", "warn")
            return redirect(url_for("problem_detail", code=code) + "#panel-submit")

        used = _daily_submission_count(conn, user["id"], problem["id"])
        if used >= app.config["DAILY_SUBMIT_LIMIT"]:
            flash(
                f"Em đã dùng hết {app.config['DAILY_SUBMIT_LIMIT']} lượt nộp cho đề này hôm nay. "
                "Hạn mức được đặt lại vào 0 giờ ngày mai.",
                "warn",
            )
            return redirect(url_for("problem_detail", code=code) + "#panel-submit")

        submission_id = _enqueue_submission(conn, user["id"], problem["id"], source)
        flash("Đã nhận bài nộp. Hệ thống đang chấm, em chờ trong giây lát.", "ok")
        return redirect(url_for("submission_detail", submission_id=submission_id))

    # ---------------------------------------------------------------- bài nộp
    @app.route("/submissions")
    @auth.login_required
    def submissions():
        conn = db.get_db()
        user = auth.current_user()

        # Giáo viên xem được bài nộp của mọi học sinh; học sinh chỉ thấy bài của mình.
        scope = request.args.get("scope") or ("all" if auth.is_teacher(user) else "mine")
        if not auth.is_teacher(user):
            scope = "mine"

        where, params = ["1 = 1"], []
        if scope == "mine":
            where.append("s.user_id = ?")
            params.append(user["id"])

        verdict = (request.args.get("verdict") or "").strip()
        if verdict:
            where.append("s.verdict = ?")
            params.append(verdict)

        q = (request.args.get("q") or "").strip()
        if q:
            where.append("(p.code LIKE ? OR p.name LIKE ? OR u.full_name LIKE ?)")
            params += [f"%{q}%", f"%{q}%", f"%{q}%"]

        rows = db.query(
            conn,
            f"""SELECT s.*, p.code AS problem_code, p.name AS problem_name,
                       u.full_name, u.class_name
                  FROM submissions s
                  JOIN problems p ON p.id = s.problem_id
                  JOIN users u    ON u.id = s.user_id
                 WHERE {' AND '.join(where)}
                 ORDER BY s.id DESC
                 LIMIT 200""",
            params,
        )
        items = [_decorate_submission(r) for r in rows]

        summary = {
            "total": db.scalar(
                conn, "SELECT COUNT(*) FROM submissions WHERE user_id = ?", (user["id"],)),
            "accepted": db.scalar(
                conn,
                "SELECT COUNT(*) FROM submissions WHERE user_id = ? AND verdict = 'AC'",
                (user["id"],)),
            "solved": db.scalar(
                conn,
                """SELECT COUNT(*) FROM (
                       SELECT problem_id, MAX(score) AS best, MAX(max_score) AS mx
                         FROM submissions WHERE user_id = ? AND status = 'done'
                        GROUP BY problem_id) t
                    WHERE t.mx > 0 AND t.best >= t.mx""",
                (user["id"],)),
            "problems": db.scalar(conn, "SELECT COUNT(*) FROM problems WHERE status = 'live'"),
        }
        summary["accept_rate"] = (
            round(summary["accepted"] / summary["total"] * 100) if summary["total"] else 0
        )

        breakdown = db.query(
            conn,
            """SELECT verdict, COUNT(*) AS n FROM submissions
                WHERE user_id = ? AND status = 'done'
                GROUP BY verdict ORDER BY n DESC""",
            (user["id"],),
        )

        return render_template(
            "submissions.html",
            active="submissions",
            submissions=items,
            summary=summary,
            breakdown=breakdown,
            scope=scope,
            filters={"verdict": verdict, "q": q},
            is_teacher=auth.is_teacher(user),
        )

    @app.route("/submissions/<int:submission_id>")
    @auth.login_required
    def submission_detail(submission_id: int):
        conn = db.get_db()
        user = auth.current_user()

        row = db.query_one(
            conn,
            """SELECT s.*, p.code AS problem_code, p.name AS problem_name,
                      p.time_limit_ms, p.memory_limit_mb, p.id AS problem_id,
                      u.full_name, u.class_name
                 FROM submissions s
                 JOIN problems p ON p.id = s.problem_id
                 JOIN users u    ON u.id = s.user_id
                WHERE s.id = ?""",
            (submission_id,),
        )
        if row is None:
            abort(404)
        # Học sinh chỉ xem được bài của mình. Trả 404 chứ không 403 để không xác
        # nhận sự tồn tại của bài nộp người khác.
        if row["user_id"] != user["id"] and not auth.is_teacher(user):
            abort(404)

        results = db.query(
            conn,
            "SELECT * FROM test_results WHERE submission_id = ? ORDER BY ordinal",
            (submission_id,),
        )

        # Bộ dữ liệu sai đầu tiên, để hiện phần so sánh vào–ra ở đầu trang.
        first_bad = next((r for r in results if r["verdict"] != "AC"), None)
        # Chỉ so sánh khi có nội dung: bộ ẩn để trống ba trường này.
        if first_bad and not first_bad["expected_seen"] and not first_bad["actual_seen"]:
            first_bad = None

        passed = sum(1 for r in results if r["verdict"] == "AC")
        counts: dict[str, int] = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

        # Bộ ẩn phải lấy từ bảng `tests`: `test_results` cố tình để trống nội
        # dung của bộ ẩn nên không thể suy ra từ đó.
        hidden_ordinals = {
            t["ordinal"] for t in db.query(
                conn, "SELECT ordinal, is_hidden FROM tests WHERE problem_id = ?",
                (row["problem_id"],))
            if t["is_hidden"]
        }

        return render_template(
            "submission.html",
            active="submissions",
            submission=row,
            results=results,
            first_bad=first_bad,
            passed=passed,
            total_tests=len(results),
            counts=counts,
            hidden_ordinals=hidden_ordinals,
            source_lines=row["source"].count("\n") + 1,
            summary_sentence=_summary_sentence(row, passed, len(results)),
            fix_hints=_fix_hints(row, first_bad),
            verdict_label=VERDICT_LABEL,
        )

    @app.route("/api/submissions/<int:submission_id>")
    @auth.login_required
    def api_submission(submission_id: int):
        """Trạng thái chấm, cho trang tự cập nhật khi bài đang chờ."""
        conn = db.get_db()
        user = auth.current_user()
        row = db.query_one(conn, "SELECT * FROM submissions WHERE id = ?", (submission_id,))
        if row is None or (row["user_id"] != user["id"] and not auth.is_teacher(user)):
            abort(404)
        return jsonify({
            "id": row["id"],
            "status": row["status"],
            "verdict": row["verdict"],
            "score": row["score"],
            "max_score": row["max_score"],
            "done": row["status"] in ("done", "error"),
            "url": url_for("submission_detail", submission_id=row["id"]),
        })

    # ---------------------------------------------------------- bảng xếp hạng
    @app.route("/leaderboard")
    def leaderboard():
        conn = db.get_db()
        scope = (request.args.get("scope") or "").strip()
        class_filter = scope if scope and scope != "all" else None

        rows = _leaderboard_rows(conn, scope=class_filter, limit=200)
        top = rows[:10]
        max_score = max((r["score"] for r in top), default=0) or 1
        for i, r in enumerate(top):
            r["bar_percent"] = round(r["score"] / max_score * 100)

        return render_template(
            "leaderboard.html",
            active="leaderboard",
            rows=rows,
            top=top,
            scope=scope or "all",
            classes=_class_names(conn),
        )

    # ---------------------------------------------------------------- kỳ thi
    @app.route("/contests")
    def contests():
        conn = db.get_db()
        user = auth.current_user()

        rows = db.query(
            conn,
            """SELECT c.*,
                      (SELECT COUNT(*) FROM contest_problems cp WHERE cp.contest_id = c.id) AS problem_count,
                      (SELECT COUNT(*) FROM contest_entries ce WHERE ce.contest_id = c.id) AS entries
                 FROM contests c
                WHERE c.status <> 'draft'
                ORDER BY c.starts_at DESC""",
        )
        items = []
        for r in rows:
            d = dict(r)
            d["phase"] = _contest_phase(r)
            items.append(d)

        upcoming = [c for c in items if c["phase"] == "upcoming"]
        live = [c for c in items if c["phase"] == "open"]
        past = [c for c in items if c["phase"] == "closed"]

        # Số liệu cá nhân cho kỳ thi đang diễn ra.
        live_stats = None
        if live and user:
            contest = live[0]
            live_stats = {
                "done": db.scalar(
                    conn,
                    """SELECT COUNT(DISTINCT s.problem_id) FROM submissions s
                        WHERE s.user_id = ? AND s.contest_id = ? AND s.verdict = 'AC'""",
                    (user["id"], contest["id"]),
                ),
                "score": db.scalar(
                    conn,
                    """SELECT COALESCE(SUM(t.best), 0) FROM (
                           SELECT problem_id, MAX(score) AS best FROM submissions
                            WHERE user_id = ? AND contest_id = ?
                            GROUP BY problem_id) t""",
                    (user["id"], contest["id"]),
                ),
                "used": db.scalar(
                    conn,
                    "SELECT COUNT(*) FROM submissions WHERE user_id = ? AND contest_id = ?",
                    (user["id"], contest["id"]),
                ),
            }

        return render_template(
            "contests.html",
            active="contests",
            upcoming=upcoming,
            live=live,
            past=past,
            live_stats=live_stats,
        )

    # ------------------------------------------------------------ đăng nhập
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if auth.current_user():
                return redirect(url_for("index"))
            return render_template("login.html", active="login", classes=_class_names(db.get_db()))

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM users WHERE username = ?", (username,))

        # Một thông báo lỗi duy nhất cho cả hai trường hợp sai tên đăng nhập và
        # sai mật khẩu. Nếu tách ra, kẻ tấn công dò được tên đăng nhập nào có
        # thật bằng cách đọc thông báo.
        if row is None or not auth.verify_password(row["password_hash"], password):
            flash("Tên đăng nhập hoặc mật khẩu không đúng.", "warn")
            return render_template("login.html", active="login",
                                   classes=_class_names(conn), username=username), 401

        if not row["is_active"]:
            flash("Tài khoản này đang bị khoá. Em liên hệ giáo viên phụ trách.", "warn")
            return render_template("login.html", active="login",
                                   classes=_class_names(conn), username=username), 403

        auth.login_user(row)
        with conn:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                         (db.utc_now(), row["id"]))

        nxt = request.form.get("next") or request.args.get("next") or ""
        # Chỉ chuyển hướng trong nội bộ site. Nếu không kiểm tra, kẻ tấn công có
        # thể gửi một liên kết /login?next=https://trang-gia-mao để lừa học sinh
        # đăng nhập rồi bị đưa sang trang khác.
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = url_for("index")
        return redirect(nxt)

    @app.route("/logout", methods=["POST"])
    def logout():
        auth.logout_user()
        flash("Em đã đăng xuất.", "ok")
        return redirect(url_for("index"))

    # ---------------------------------------------------------- khu giáo viên
    @app.route("/teacher")
    @auth.teacher_required
    def teacher():
        conn = db.get_db()
        stats = {
            "students": db.scalar(conn, "SELECT COUNT(*) FROM users WHERE role = 'student'"),
            "classes": db.scalar(
                conn, "SELECT COUNT(DISTINCT class_name) FROM users WHERE class_name <> ''"),
            "problems": db.scalar(conn, "SELECT COUNT(*) FROM problems"),
            "pending_review": db.scalar(
                conn, "SELECT COUNT(*) FROM problems WHERE status = 'review'"),
            "today": db.scalar(
                conn, "SELECT COUNT(*) FROM submissions WHERE created_at >= ?",
                (_day_start_utc(),)),
            "open_contests": db.scalar(
                conn,
                "SELECT COUNT(*) FROM contests WHERE status <> 'draft' AND starts_at <= ? AND ends_at >= ?",
                (db.utc_now(), db.utc_now())),
        }

        class_rows = db.query(
            conn,
            """SELECT u.class_name,
                      COUNT(*) AS size,
                      (SELECT COUNT(DISTINCT s.user_id) FROM submissions s
                        JOIN users u2 ON u2.id = s.user_id
                       WHERE u2.class_name = u.class_name AND s.verdict = 'AC') AS solved,
                      (SELECT COUNT(*) FROM submissions s
                        JOIN users u3 ON u3.id = s.user_id
                       WHERE u3.class_name = u.class_name) AS attempts,
                      (SELECT MAX(s.created_at) FROM submissions s
                        JOIN users u4 ON u4.id = s.user_id
                       WHERE u4.class_name = u.class_name) AS last_at
                 FROM users u
                WHERE u.role = 'student' AND u.class_name <> ''
                GROUP BY u.class_name
                ORDER BY u.class_name""",
        )
        classes = []
        for r in class_rows:
            d = dict(r)
            d["percent"] = round(r["solved"] / r["size"] * 100) if r["size"] else 0
            classes.append(d)

        recent = [_decorate_submission(r) for r in _recent_submissions(conn, limit=8)]

        next_contest = db.query_one(
            conn,
            """SELECT * FROM contests
                WHERE status <> 'draft' AND ends_at >= ?
                ORDER BY starts_at LIMIT 1""",
            (db.utc_now(),),
        )

        return render_template(
            "teacher.html",
            active="teacher",
            stats=stats,
            classes=classes,
            recent=recent,
            next_contest=next_contest,
        )

    @app.route("/teacher/problems", methods=["GET", "POST"])
    @auth.teacher_required
    def teacher_problems():
        conn = db.get_db()
        user = auth.current_user()

        if request.method == "POST":
            error = _create_problem(conn, user, request.form)
            if error:
                flash(error, "warn")
            else:
                flash("Đã lưu đề mới ở dạng bản nháp.", "ok")
            return redirect(url_for("teacher_problems"))

        rows = db.query(
            conn,
            """SELECT p.*,
                      u.full_name AS author_name,
                      (SELECT COUNT(*) FROM tests t WHERE t.problem_id = p.id) AS test_count,
                      (SELECT COUNT(*) FROM tests t WHERE t.problem_id = p.id AND t.is_hidden = 1) AS hidden_count
                 FROM problems p
                 LEFT JOIN users u ON u.id = p.author_id
                ORDER BY p.code""",
        )
        return render_template(
            "teacher_problems.html",
            active="teacher",
            problems=rows,
            topics=_topics(conn),
        )

    @app.route("/teacher/problems/<code>/tests", methods=["GET", "POST"])
    @auth.teacher_required
    def teacher_problem_tests(code: str):
        conn = db.get_db()
        problem = db.query_one(conn, "SELECT * FROM problems WHERE code = ?", (code,))
        if problem is None:
            abort(404)

        if request.method == "POST":
            action = request.form.get("action") or "add"
            if action == "delete":
                with conn:
                    conn.execute("DELETE FROM tests WHERE problem_id = ? AND ordinal = ?",
                                 (problem["id"], request.form.get("ordinal", type=int)))
                flash("Đã xoá bộ dữ liệu.", "ok")
            else:
                _add_test(conn, problem, request.form)
                flash("Đã thêm bộ dữ liệu.", "ok")
            return redirect(url_for("teacher_problem_tests", code=code))

        tests = db.query(
            conn, "SELECT * FROM tests WHERE problem_id = ? ORDER BY ordinal", (problem["id"],))
        return render_template(
            "teacher_tests.html",
            active="teacher",
            problem=problem,
            tests=tests,
        )

    @app.route("/teacher/classes")
    @auth.teacher_required
    def teacher_classes():
        conn = db.get_db()
        class_name = (request.args.get("class") or "").strip()
        classes = _class_names(conn)
        if not class_name and classes:
            class_name = classes[0]

        students = []
        summary = {"size": 0, "avg": 0, "best": 0, "idle": 0}
        if class_name:
            rows = db.query(
                conn,
                """SELECT u.id, u.full_name, u.username, u.is_active, u.last_login_at,
                          COALESCE((SELECT SUM(t.best) FROM (
                              SELECT problem_id, MAX(score) AS best FROM submissions
                               WHERE user_id = u.id AND status = 'done'
                               GROUP BY problem_id) t), 0) AS total_score,
                          COALESCE((SELECT COUNT(*) FROM (
                              SELECT problem_id, MAX(score) AS best, MAX(max_score) AS mx
                                FROM submissions WHERE user_id = u.id AND status = 'done'
                               GROUP BY problem_id) t2
                             WHERE t2.mx > 0 AND t2.best >= t2.mx), 0) AS solved,
                          (SELECT MAX(created_at) FROM submissions WHERE user_id = u.id) AS last_at,
                          (SELECT COUNT(*) FROM submissions WHERE user_id = u.id) AS attempts
                     FROM users u
                    WHERE u.role = 'student' AND u.class_name = ?
                    ORDER BY total_score DESC, u.full_name""",
                (class_name,),
            )
            students = [dict(r) for r in rows]
            if students:
                scores = [s["total_score"] for s in students]
                summary = {
                    "size": len(students),
                    "avg": round(sum(scores) / len(scores)),
                    "best": max(scores),
                    "idle": sum(1 for s in students if s["attempts"] == 0),
                }

        return render_template(
            "teacher_classes.html",
            active="teacher",
            classes=classes,
            class_name=class_name,
            students=students,
            summary=summary,
        )


# ==========================================================================
# Truy vấn phụ trợ
# ==========================================================================
def _month_start_utc() -> str:
    now = db.to_local(db.utc_now())
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day_start_utc() -> str:
    now = db.to_local(db.utc_now())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _leaderboard_rows(conn, scope: str | None, limit: int) -> list[dict]:
    """Bảng xếp hạng.

    Điểm của một học sinh là **tổng điểm cao nhất đạt được ở từng đề**, không
    phải tổng tất cả các lần nộp. Nếu cộng tất cả các lần nộp thì nộp lại nhiều
    lần sẽ tự động tăng điểm, và bảng xếp hạng sẽ đo số lần bấm nút chứ không
    đo năng lực.
    """
    where = ["u.role = 'student'"]
    params: list = []
    if scope:
        where.append("u.class_name = ?")
        params.append(scope)
    params.append(limit)

    rows = db.query(
        conn,
        f"""SELECT u.id, u.full_name, u.class_name,
                   COALESCE((SELECT SUM(t.best) FROM (
                       SELECT problem_id, MAX(score) AS best FROM submissions
                        WHERE user_id = u.id AND status = 'done'
                        GROUP BY problem_id) t), 0) AS score,
                   COALESCE((SELECT COUNT(*) FROM (
                       SELECT problem_id, MAX(score) AS best, MAX(max_score) AS mx
                         FROM submissions WHERE user_id = u.id AND status = 'done'
                        GROUP BY problem_id) t2
                      WHERE t2.mx > 0 AND t2.best >= t2.mx), 0) AS solved,
                   (SELECT COUNT(*) FROM submissions WHERE user_id = u.id) AS attempts,
                   (SELECT COUNT(*) FROM submissions WHERE user_id = u.id AND verdict = 'AC') AS accepted
              FROM users u
             WHERE {' AND '.join(where)}
             ORDER BY score DESC, solved DESC, u.full_name
             LIMIT ?""",
        params,
    )
    out = []
    for i, r in enumerate(rows):
        d = dict(r)
        d["rank"] = i + 1
        d["accept_rate"] = round(r["accepted"] / r["attempts"] * 100) if r["attempts"] else 0
        out.append(d)
    return out


def _recent_submissions(conn, limit: int) -> list:
    return db.query(
        conn,
        """SELECT s.*, p.code AS problem_code, p.name AS problem_name,
                  u.full_name, u.class_name
             FROM submissions s
             JOIN problems p ON p.id = s.problem_id
             JOIN users u    ON u.id = s.user_id
            ORDER BY s.id DESC
            LIMIT ?""",
        (limit,),
    )


def _decorate_submission(row) -> dict:
    """Thêm các trường dẫn xuất mà template cần."""
    d = dict(row)
    d["is_finished"] = d.get("status") in ("done", "error")
    return d


def _summary_sentence(submission, passed: int, total: int) -> str:
    """Một câu mô tả kết quả, hiện ngay dưới mã kết quả ở đầu trang chi tiết.

    Viết riêng cho từng mã thay vì một câu chung, vì "Sai" không nói được gì
    cho học sinh. Câu này là chỗ để nói *cái gì* đã xảy ra theo cách mà một
    người mới học lập trình hiểu được.
    """
    v = submission["verdict"]
    if total == 0:
        return "Đề bài chưa có bộ dữ liệu nên hệ thống không chấm được."
    if v == "AC":
        return f"Đạt {total}/{total} bộ dữ liệu. Bài làm đã đúng hoàn toàn."
    if v == "CE":
        return "Chương trình không dịch được. Xem tab “Nhật ký dịch” để biết lỗi ở dòng nào."
    if v == "TLE":
        return (f"Đạt {passed}/{total} bộ dữ liệu. Chương trình chạy quá "
                f"{submission['time_limit_ms'] / 1000:.1f} giây ở một số bộ — "
                "thường là do thuật toán chưa đủ nhanh.")
    if v == "MLE":
        return (f"Đạt {passed}/{total} bộ dữ liệu. Chương trình dùng quá "
                f"{submission['memory_limit_mb']} MB bộ nhớ — có thể do mảng khai báo quá lớn.")
    if v == "RE":
        return (f"Đạt {passed}/{total} bộ dữ liệu. Chương trình bị dừng giữa chừng — "
                "thường là truy cập mảng ngoài phạm vi, chia cho 0, hoặc gọi đệ quy quá sâu.")
    if v == "IE":
        return "Hệ thống chấm gặp lỗi. Em báo giáo viên giúp nhé."
    if v == "WA":
        wrong = total - passed
        return (f"Đạt {passed}/{total} bộ dữ liệu. Bài sai ở {wrong} bộ — "
                "xem phần so sánh bên dưới để biết chỗ khác nhau đầu tiên.")
    return f"Đạt {passed}/{total} bộ dữ liệu."


def _fix_hints(submission, first_bad) -> list[str]:
    """Gợi ý hướng sửa, theo mã kết quả.

    Cố ý không đưa ra lời giải. Đây là gợi ý về *chỗ cần nhìn*, không phải đáp
    án — nếu hệ thống nói luôn cách sửa thì bài tập mất hết ý nghĩa.
    """
    v = submission["verdict"]
    if v == "AC":
        return []

    if v == "CE":
        return [
            "Mở tab <strong>Nhật ký dịch</strong> ở trên. Dòng lỗi có ghi rõ số dòng và "
            "nội dung trình biên dịch phàn nàn.",
            "Lỗi thường gặp nhất là thiếu dấu <code>;</code> ở cuối câu lệnh, "
            "hoặc viết sai tên biến ở một chỗ nào đó.",
        ]

    if v == "WA":
        hints = []
        if first_bad:
            hints.append(
                f"Bộ dữ liệu {first_bad['ordinal']} là chỗ khác nhau đầu tiên. "
                "So sánh ba ô ở trên: đầu vào, kết quả đúng, và kết quả chương trình in ra."
            )
        hints += [
            "Kiểm tra trường hợp biên: số âm, số 0, giá trị lớn nhất mà đề cho phép.",
            "Kiểm tra kiểu dữ liệu. Tổng hoặc tích của hai số có thể vượt quá giới hạn của "
            "<code>int</code> (2 147 483 647) — khi đó phải dùng <code>long long</code>.",
            "Kiểm tra xem chương trình có in thừa chữ nào ngoài kết quả không. "
            "Hệ thống so khớp từng ký tự.",
        ]
        return hints

    if v == "TLE":
        return [
            "Ước lượng số phép tính của thuật toán. Nếu đề cho <code>n</code> tới "
            "10<sup>5</sup> thì thuật toán hai vòng lồng nhau (khoảng <code>n²</code> phép tính) "
            "sẽ quá chậm — cần cách làm nhanh hơn.",
            "Kiểm tra chương trình có vòng lặp vô hạn không, đặc biệt ở phần đọc dữ liệu.",
        ]

    if v == "MLE":
        return [
            "Mảng khai báo quá lớn là nguyên nhân thường gặp nhất. "
            "Một mảng <code>int a[1000000]</code> đã chiếm 4 MB.",
            "Khai báo mảng lớn <strong>trong hàm <code>main</code></strong> dùng bộ nhớ ngăn xếp "
            "rất hạn chế; khai báo ở ngoài hàm (biến toàn cục) thì dùng bộ nhớ động, rộng hơn nhiều.",
        ]

    if v == "RE":
        return [
            "Kiểm tra truy cập mảng ngoài phạm vi: chỉ số chạy từ <code>0</code> tới "
            "<code>n-1</code>, không phải tới <code>n</code>.",
            "Kiểm tra phép chia cho 0 — hay xảy ra khi mẫu số là biến và ở bộ dữ liệu nào đó bằng 0.",
            "Nếu dùng đệ quy, kiểm tra điều kiện dừng. Đệ quy không có điểm dừng sẽ làm tràn ngăn xếp.",
        ]

    return []


# ==========================================================================
# Tạo đề và bộ dữ liệu (giáo viên)
# ==========================================================================
def _create_problem(conn, user, form) -> str | None:
    """Trả về thông báo lỗi, hoặc None nếu thành công."""
    code = (form.get("code") or "").strip().upper()
    name = (form.get("name") or "").strip()
    statement = (form.get("statement") or "").strip()

    if not code or not name:
        return "Mã đề và tên bài không được để trống."
    if not code.replace("-", "").isalnum():
        return "Mã đề chỉ được gồm chữ, số và dấu gạch ngang."
    if db.query_one(conn, "SELECT id FROM problems WHERE code = ?", (code,)):
        return f"Mã đề {code} đã tồn tại."
    if not statement:
        return "Chưa nhập nội dung đề bài."

    try:
        time_ms = int(float(form.get("time_limit_s") or 1) * 1000)
    except (TypeError, ValueError):
        time_ms = 1000
    try:
        memory_mb = int(form.get("memory_limit_mb") or 256)
    except (TypeError, ValueError):
        memory_mb = 256

    # Kẹp giá trị vào khoảng hợp lý. Một giới hạn thời gian bằng 0 sẽ khiến mọi
    # bài nộp đều bị xử là quá thời gian, và giáo viên sẽ tưởng học sinh làm sai.
    time_ms = max(100, min(time_ms, 10_000))
    memory_mb = max(16, min(memory_mb, 1024))

    now = db.utc_now()
    with conn:
        conn.execute(
            """INSERT INTO problems
                 (code, name, difficulty, topic, statement, time_limit_ms,
                  memory_limit_mb, points_mode, status, author_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
            (
                code, name,
                form.get("difficulty") or "co-ban",
                (form.get("topic") or "").strip(),
                statement, time_ms, memory_mb,
                form.get("points_mode") or "even",
                user["id"], now, now,
            ),
        )
    return None


def _add_test(conn, problem, form) -> None:
    """Thêm một bộ dữ liệu vào đề. Bỏ qua nếu thiếu đầu vào hoặc đầu ra."""
    data_in = form.get("input") or ""
    data_out = form.get("output") or ""
    if not data_in.strip() and not data_out.strip():
        return

    ordinal = db.scalar(
        conn, "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM tests WHERE problem_id = ?",
        (problem["id"],))
    try:
        points = int(form.get("points") or 0)
    except (TypeError, ValueError):
        points = 0

    with conn:
        conn.execute(
            """INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                problem["id"], ordinal, data_in, data_out,
                1 if form.get("is_hidden") else 0,
                points,
                (form.get("note") or "").strip(),
            ),
        )
        conn.execute("UPDATE problems SET updated_at = ? WHERE id = ?",
                     (db.utc_now(), problem["id"]))


# ==========================================================================
# Xử lý lỗi
# ==========================================================================
def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", active="", code=403,
                               title="Không đủ quyền",
                               message="Trang này chỉ dành cho giáo viên."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", active="", code=404,
                               title="Không tìm thấy trang",
                               message="Đường dẫn không tồn tại, hoặc nội dung đã bị xoá."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", active="", code=400,
                               title="Yêu cầu không hợp lệ",
                               message=getattr(e, "description", "Dữ liệu gửi lên không hợp lệ.")), 400


# Cho phép `flask --app server.app run` và `python -m server.app`.
app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("SONGLO_HOST", "127.0.0.1"),
        port=int(os.environ.get("SONGLO_PORT", "5000")),
        debug=os.environ.get("SONGLO_DEBUG") == "1",
    )
