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
    Flask, Response, abort, current_app, flash, jsonify, redirect,
    render_template, request, send_from_directory, url_for,
)

from . import aiwriter, auth, avatars, db, formatting, gendata, grades, themis
from .judge import COMPILE_FLAGS, VERDICT_LABEL

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# Số lượt nộp tối đa cho một học sinh trên một đề trong một ngày.
DAILY_SUBMIT_LIMIT = 20

# Tập giá trị hợp lệ cho các ô chọn của đề.
#
# Vì sao cần whitelist chứ không lấy thẳng giá trị từ biểu mẫu: `difficulty` và
# `points_mode` đi thẳng vào câu truy vấn và vào tên lớp CSS. Một giá trị lạ lọt
# vào CSDL sẽ không khớp với `DIFFICULTY_LABEL` trong `formatting.py`, và giao
# diện hiện ra mã thô (`co-ban2`) ở chỗ đáng lẽ là nhãn tiếng Việt. Biểu mẫu là
# dữ liệu do người dùng gửi lên, không phải danh sách do mình kiểm soát.
DIFFICULTIES = ("co-ban", "trung-binh", "nang-cao")
POINTS_MODES = ("even", "custom")
PROBLEM_STATUSES = ("draft", "review", "live")

# Giới hạn thời gian và bộ nhớ, tính bằng mili giây và MB.
MIN_TIME_MS, MAX_TIME_MS = 100, 10_000
MIN_MEMORY_MB, MAX_MEMORY_MB = 16, 1024

# Độ dài tối đa của mã nguồn, tính bằng ký tự. 64 KB tương đương khoảng 2 000
# dòng — thừa sức cho mọi bài của cấp 2, nhưng chặn được việc ai đó dán cả một
# tệp nén vào ô soạn thảo.
MAX_SOURCE_LENGTH = 64 * 1024

# Độ dài tối đa của phần giới thiệu bản thân, tính bằng ký tự. 240 là khoảng
# bốn dòng trên màn hình điện thoại — đủ để viết một câu giới thiệu, không đủ để
# biến trang cá nhân thành nơi đăng bài.
MAX_BIO_LENGTH = 240

# Độ dài tối thiểu của mật khẩu mới. Đặt 8 chứ không phải 6: học sinh cấp 2 quen
# dùng ngày sinh hoặc tên lớp, và những chuỗi đó nằm trong mọi danh sách mật khẩu
# rò rỉ. Đây là mức thấp nhất còn có ý nghĩa mà không khiến các em phải ghi ra
# giấy — điều còn tệ hơn cả mật khẩu yếu.
MIN_PASSWORD_LENGTH = 8

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
        # Thư mục làm việc **riêng** cho việc sinh dữ liệu, không dùng chung với
        # `JUDGE_WORKSPACE`.
        #
        # Vì sao: `JUDGE_WORKSPACE` trên máy chủ thật là `root:root` và chỉ tiến
        # trình chấm (chạy bằng root) ghi được vào đó. Việc sinh dữ liệu chạy
        # trong tiến trình web, mà tiến trình web chạy bằng tài khoản `songlo`
        # chứ không phải root — nên nó tạo thư mục trong `judge/` bị từ chối với
        # `PermissionError`, và lỗi đó chỉ hiện ra trên máy chủ thật, không hiện
        # ở máy phát triển. Dùng một thư mục riêng do tài khoản web sở hữu thì
        # không phải nới quyền cho thư mục chấm bài.
        GENDATA_WORKSPACE=str(var_dir / "gendata"),
        # Nhờ AI viết bộ sinh dữ liệu và lời giải mẫu từ đề bài (xem
        # `aiwriter.py`). Khoá **không** nằm trong mã nguồn: repo này là công
        # khai, nên khoá đặt trong `/etc/songlo.env` của máy chủ — xem
        # `deploy/README.md`. Không có khoá thì cả thẻ đó ẩn hẳn, vì hiện một
        # nút bấm rồi báo "chưa cấu hình" là cách tệ nhất để tắt một tính năng.
        AI_BASE=os.environ.get("SONGLO_AI_BASE", aiwriter.DEFAULT_BASE),
        AI_KEY=os.environ.get("SONGLO_AI_KEY", ""),
        AI_MODEL=os.environ.get("SONGLO_AI_MODEL", aiwriter.DEFAULT_MODEL),
        # Phải nhỏ hơn thời hạn của gunicorn, nếu không gunicorn giết tiến trình
        # trước và giáo viên nhận 502 thay vì một câu giải thích.
        AI_TIMEOUT=int(os.environ.get("SONGLO_AI_TIMEOUT", aiwriter.DEFAULT_TIMEOUT)),
        COMPILER=os.environ.get("SONGLO_COMPILER", "g++"),
        DAILY_SUBMIT_LIMIT=DAILY_SUBMIT_LIMIT,
        MAX_SOURCE_LENGTH=MAX_SOURCE_LENGTH,
    )
    if config:
        app.config.update(config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db.init_db(app.config["DATABASE"])

    # Trần kích thước thân request. Hai thứ người dùng tải lên dạng tệp là ảnh
    # đại diện và tệp ZIP bộ dữ liệu, nên lấy giới hạn **lớn hơn** trong hai
    # cộng thêm một ít cho phần biểu mẫu. Lấy theo ảnh đại diện (5 MB) là một
    # cái bẫy: bộ dữ liệu của một đề thi thật vượt 5 MB rất thường, và lúc đó
    # Flask trả 413 trước khi `_import_themis_zip` kịp chạy — thông báo lỗi nói
    # "tệp quá lớn" mà không nói giới hạn nào, còn hàm nhập thì không hề được gọi.
    # Đặt ở đây để tầng máy chủ từ chối trước khi Flask đọc hết thân request vào
    # bộ nhớ — nếu không, một tệp 2 GB sẽ được nạp hết rồi mới bị từ chối.
    app.config.setdefault(
        "MAX_CONTENT_LENGTH",
        max(avatars.MAX_UPLOAD_BYTES, themis.MAX_TOTAL_BYTES) + 256 * 1024,
    )

    app.teardown_appcontext(db.close_db)
    auth.init_app(app)
    formatting.register_filters(app)
    # Đổ một mốc UTC trong CSDL vào `<input type="datetime-local">` — chiều ngược
    # lại của `db.iso_from_local_input`. Đăng ký ở đây chứ không ở
    # `formatting.py`: đây là phép đổi múi giờ, không phải phép trình bày, và nó
    # phải đi cùng cặp với hàm nhận dữ liệu vào ở `_contest_form`.
    app.jinja_env.filters["local_input"] = db.local_input_value

    _register_routes(app)
    _register_password_guard(app)
    _register_error_handlers(app)
    return app


def _register_password_guard(app: Flask) -> None:
    """Ép đổi mật khẩu trước khi dùng được phần còn lại của hệ thống.

    ``seed.py`` đặt ``must_change_password = 1`` cho mọi tài khoản học sinh vì
    mật khẩu đầu tiên do giáo viên sinh ra và đọc to trong phòng máy — ai nghe
    được cũng biết. Cờ đó đã có trong CSDL từ đầu nhưng **chưa có gì đọc nó**,
    nên trên thực tế mật khẩu tạm dùng được mãi mãi.

    Đăng ký hook ở tầng ứng dụng chứ không kiểm tra trong từng tuyến đường: làm
    theo từng tuyến đường thì chỉ cần thêm một trang mới mà quên là cờ mất tác
    dụng, và không có dấu hiệu nào cho thấy điều đó.
    """
    # Những đích đến vẫn phải vào được, nếu không người dùng bị kẹt vòng lặp
    # chuyển hướng: trang đổi mật khẩu, đăng xuất, và tệp tĩnh.
    allowed = {"account", "account_password", "logout", "login", "static", "avatar_file"}

    @app.before_request
    def _force_password_change():
        if request.endpoint is None or request.endpoint in allowed:
            return None
        user = auth.current_user()
        if user is None or not user["must_change_password"]:
            return None
        flash("Em cần đổi mật khẩu trước khi dùng các phần khác của hệ thống.", "warn")
        return redirect(url_for("account"))


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


def _test_count(conn, problem) -> int:
    """Số bộ dữ liệu của một đề. Dùng ở trang sửa đề và ở chốt chặn công khai."""
    return db.scalar(
        conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?", (problem["id"],))


def _publish_blocker(conn, problem) -> str | None:
    """Lý do **không** công khai được đề này, hoặc None nếu công khai được.

    Một chỗ duy nhất giữ luật này, vì có ba đường dẫn tới việc công khai: nút
    trên danh sách đề, nút trong trang sửa đề, và bước tự công khai sau khi nhập
    dữ liệu. Nếu mỗi nơi tự kiểm tra thì sớm muộn cũng có nơi quên, và đề không
    có bộ dữ liệu sẽ ra tới học sinh.

    Vì sao chặn: học sinh vẫn mở được đề, vẫn nộp được bài, nhưng bộ chấm không
    có gì để chạy nên mọi bài đều ra "lỗi hệ thống chấm" — và lỗi ấy trông như
    hệ thống hỏng, chứ không như đề thiếu dữ liệu. Giáo viên sẽ đi tìm lỗi ở
    chỗ khác.
    """
    if not _test_count(conn, problem):
        return ("Không công khai được vì đề chưa có bộ dữ liệu nào. "
                "Thêm ít nhất một bộ ở trang bộ dữ liệu trước.")
    return None


def _set_problem_status(conn, problem, status: str) -> str | None:
    """Đổi trạng thái biên tập của một đề. Trả về lỗi, hoặc None nếu xong.

    Tách khỏi `_update_problem` để công khai một đề là **một** thao tác, không
    phải mở biểu mẫu sửa đề, tìm ô chọn trạng thái, rồi bấm lưu. Đó chính là
    chỗ mà một đề soạn xong nằm lại ở bản nháp mãi mãi: giáo viên soạn đề ở
    trang soạn đề, nhưng chỗ đổi trạng thái lại nằm trong biểu mẫu sửa đề, và
    không có gì trên màn hình nói rằng đề đang không hiện với học sinh.
    """
    if status not in PROBLEM_STATUSES:
        return "Trạng thái không hợp lệ."
    if status == "live":
        blocker = _publish_blocker(conn, problem)
        if blocker:
            return blocker
    with conn:
        conn.execute("UPDATE problems SET status = ?, updated_at = ? WHERE id = ?",
                     (status, db.utc_now(), problem["id"]))
    return None


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

    # ------------------------------------------------------ trang cá nhân
    @app.route("/account")
    @auth.login_required
    def account():
        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (auth.current_user()["id"],))
        stats = db.query_one(
            conn,
            """SELECT COUNT(*) AS attempts,
                      COALESCE(SUM(verdict = 'AC'), 0) AS accepted,
                      COUNT(DISTINCT CASE WHEN verdict = 'AC' THEN problem_id END) AS solved
                 FROM submissions WHERE user_id = ?""",
            (row["id"],),
        )
        return render_template(
            "account.html", active="account", profile=row, stats=stats,
            max_bio=MAX_BIO_LENGTH,
            max_upload_mb=avatars.MAX_UPLOAD_BYTES // (1024 * 1024),
        )

    @app.route("/account/password", methods=["POST"])
    @auth.login_required
    def account_password():
        user = auth.current_user()
        conn = db.get_db()

        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""

        # Kiểm tra mật khẩu hiện tại trước tiên. Không có bước này thì bất kỳ ai
        # cầm được điện thoại của học sinh đang mở phiên — hoặc bất kỳ thẻ script
        # nào chạy được trên máy đó — đổi được mật khẩu và chiếm tài khoản.
        if not auth.verify_password(user["password_hash"], current):
            flash("Mật khẩu hiện tại không đúng.", "warn")
            return redirect(url_for("account"))

        err = _password_problem(new, confirm, user["username"])
        if err:
            flash(err, "warn")
            return redirect(url_for("account"))

        with conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (auth.hash_password(new), user["id"]),
            )
        flash("Đã đổi mật khẩu. Lần sau em đăng nhập bằng mật khẩu mới.", "ok")
        return redirect(url_for("account"))

    @app.route("/account/profile", methods=["POST"])
    @auth.login_required
    def account_profile():
        user = auth.current_user()
        conn = db.get_db()
        bio = (request.form.get("bio") or "").strip()
        if len(bio) > MAX_BIO_LENGTH:
            flash("Phần giới thiệu dài quá %d ký tự." % MAX_BIO_LENGTH, "warn")
            return redirect(url_for("account"))
        with conn:
            conn.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user["id"]))
        flash("Đã lưu phần giới thiệu.", "ok")
        return redirect(url_for("account"))

    @app.route("/account/avatar", methods=["POST"])
    @auth.login_required
    def account_avatar():
        user = auth.current_user()
        conn = db.get_db()
        var_dir = Path(app.config["DATABASE"]).parent

        name, err = avatars.save_avatar(var_dir, user["id"], request.files.get("avatar"))
        if err:
            flash(err, "warn")
            return redirect(url_for("account"))

        # Ghi tên tệp mới vào CSDL TRƯỚC, rồi mới xoá tệp cũ. Làm ngược lại mà
        # bước ghi hỏng thì CSDL còn trỏ tới tệp vừa bị xoá, và ảnh đại diện của
        # học sinh biến thành ô trống không rõ nguyên nhân.
        old = user["avatar_file"]
        with conn:
            conn.execute("UPDATE users SET avatar_file = ? WHERE id = ?", (name, user["id"]))
        if old and old != name:
            avatars.delete_avatar(var_dir, old)
        flash("Đã cập nhật ảnh đại diện.", "ok")
        return redirect(url_for("account"))

    @app.route("/account/avatar/remove", methods=["POST"])
    @auth.login_required
    def account_avatar_remove():
        user = auth.current_user()
        conn = db.get_db()
        var_dir = Path(app.config["DATABASE"]).parent
        old = user["avatar_file"]
        with conn:
            conn.execute("UPDATE users SET avatar_file = '' WHERE id = ?", (user["id"],))
        avatars.delete_avatar(var_dir, old)
        flash("Đã xoá ảnh đại diện.", "ok")
        return redirect(url_for("account"))

    @app.route("/avatar/<int:user_id>")
    @auth.login_required
    def avatar_file(user_id: int):
        """Phục vụ ảnh đại diện.

        **Cần đăng nhập**, không mở công khai. Đây là ảnh của học sinh cấp 2, và
        một đường dẫn công khai cho phép bất kỳ ai cũng tải được toàn bộ ảnh của
        cả trường bằng cách đếm id từ 1. Yêu cầu đăng nhập giới hạn việc đó trong
        phạm vi những người đã có tài khoản.

        Tên tệp đọc từ CSDL chứ không lấy từ URL, nên không có đường dẫn nào do
        người dùng kiểm soát đi vào hệ thống tệp.
        """
        conn = db.get_db()
        row = db.query_one(conn, "SELECT avatar_file FROM users WHERE id = ?", (user_id,))
        if row is None or not row["avatar_file"]:
            abort(404)
        var_dir = Path(app.config["DATABASE"]).parent
        return send_from_directory(
            avatars.avatars_dir(var_dir), row["avatar_file"],
            mimetype="image/png", max_age=3600,
        )

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
            # Không truyền thì Jinja coi là undefined: `contest_phase == 'open'`
            # sai, và thẻ này lặng lẽ rơi vào nhánh "sắp tới" kể cả khi kỳ thi
            # đang diễn ra. Truyền tường minh, giống route trang chủ.
            contest_phase=_contest_phase(next_contest) if next_contest else None,
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
                # Nói rõ bước còn thiếu. Đề mới chưa có bộ dữ liệu nên **chưa**
                # công khai được, và nếu chỉ báo "đã lưu ở dạng bản nháp" thì
                # giáo viên không biết mình còn phải làm gì để học sinh thấy đề.
                code = (request.form.get("code") or "").strip().upper()
                flash("Đã tạo đề %s. Còn một bước: nhập bộ dữ liệu vào – ra, "
                      "đề sẽ tự được công khai." % code, "ok")
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
            compile_flags="g++ " + " ".join(COMPILE_FLAGS),
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
            elif action == "import":
                return _import_themis_zip(conn, problem, code)
            elif action == "generate":
                return _generate_tests(conn, problem, code)
            elif action == "ai_write":
                return _ai_write_tests(conn, problem)
            else:
                _add_test(conn, problem, request.form)
                flash("Đã thêm bộ dữ liệu.", "ok")
            return redirect(url_for("teacher_problem_tests", code=code))

        return _render_tests(conn, problem)

    @app.route("/teacher/problems/<code>/edit", methods=["GET", "POST"])
    @auth.teacher_required
    def teacher_problem_edit(code: str):
        conn = db.get_db()
        problem = db.query_one(conn, "SELECT * FROM problems WHERE code = ?", (code,))
        if problem is None:
            abort(404)

        if request.method == "POST":
            error = _update_problem(conn, problem, request.form)
            if error:
                flash(error, "warn")
                # Hiện lại biểu mẫu với đúng những gì giáo viên vừa gõ, không
                # phải bản cũ trong CSDL. Một đề dài mà bị xoá trắng vì thiếu
                # một ô là lý do người ta bỏ luôn trang này.
                return render_template(
                    "teacher_problem_edit.html",
                    active="teacher",
                    problem=problem,
                    topics=_topics(conn),
                    test_count=_test_count(conn, problem),
                    values=_form_values(request.form, problem),
                )
            if request.form.get("publish"):
                flash(f"Đã lưu và công khai đề {problem['code']} — học sinh đã thấy đề này.", "ok")
            else:
                flash(f"Đã lưu thay đổi cho đề {problem['code']}.", "ok")
            return redirect(url_for("teacher_problems"))

        return render_template(
            "teacher_problem_edit.html",
            active="teacher",
            problem=problem,
            topics=_topics(conn),
            test_count=_test_count(conn, problem),
            values=_form_values({}, problem),
        )

    # ------------------------------------------ khu giáo viên: công khai đề
    @app.route("/teacher/problems/<code>/status", methods=["POST"])
    @auth.teacher_required
    def teacher_problem_status(code: str):
        """Công khai hoặc thu hồi một đề — **một bấm**, ngay trên danh sách đề.

        Trước đây chỗ duy nhất đổi được trạng thái là ô chọn nằm sâu trong biểu
        mẫu sửa đề. Một đề soạn xong vì thế nằm lại ở bản nháp vĩnh viễn, và
        trên màn hình không có gì nói rằng học sinh không thấy nó.
        """
        conn = db.get_db()
        problem = db.query_one(conn, "SELECT * FROM problems WHERE code = ?", (code,))
        if problem is None:
            abort(404)

        status = request.form.get("status") or ""
        error = _set_problem_status(conn, problem, status)
        if error:
            flash(error, "warn")
        elif status == "live":
            flash("Đề %s đã công khai — học sinh đã thấy đề này." % code, "ok")
        elif status == "review":
            flash("Đề %s đã chuyển sang chờ duyệt." % code, "ok")
        else:
            flash("Đề %s đã thu hồi về bản nháp — học sinh không còn thấy đề này." % code, "ok")

        # Chỉ nhận đường dẫn nội bộ. Một trường biểu mẫu điều khiển đích chuyển
        # hướng là đủ để dựng một open redirect, mà không có lý do gì cần địa chỉ
        # ngoài: các nút gửi kèm `back` đều là đường dẫn trong site này.
        back = request.form.get("back") or ""
        if not back.startswith("/") or back.startswith("//"):
            back = url_for("teacher_problems")
        return redirect(back)

    # ------------------------------------------ khu giáo viên: xoá đề
    @app.route("/teacher/problems/<code>/delete", methods=["POST"])
    @auth.teacher_required
    def teacher_problem_delete(code: str):
        """Xoá một đề, kèm mọi thứ thuộc về nó.

        Không phải dọn tay: các bảng `tests`, `contest_problems`, `submissions`
        đều khai báo `ON DELETE CASCADE` trỏ về `problems`, và kết nối của ứng
        dụng bật `PRAGMA foreign_keys` nên SQLite tự xoá theo. (`sqlite3` CLI thì
        mặc định **không** bật, nên kiểm tra bằng CLI sẽ thấy `foreign_keys = 0`
        và tưởng cascade không chạy — đó là chuyện của CLI, không phải của ứng
        dụng.)

        Xoá đề là việc không hoàn tác được và kéo theo **toàn bộ bài nộp của học
        sinh** cho đề đó, nên số lượng bị xoá được đếm trước và nói rõ trong
        thông báo. Giáo viên cần biết mình vừa xoá bao nhiêu bài của học sinh.
        """
        conn = db.get_db()
        problem = db.query_one(conn, "SELECT * FROM problems WHERE code = ?", (code,))
        if problem is None:
            abort(404)

        n_tests = db.scalar(conn, "SELECT COUNT(*) FROM tests WHERE problem_id = ?",
                            (problem["id"],))
        n_subs = db.scalar(conn, "SELECT COUNT(*) FROM submissions WHERE problem_id = ?",
                           (problem["id"],))
        with conn:
            conn.execute("DELETE FROM problems WHERE id = ?", (problem["id"],))

        msg = "Đã xoá đề %s." % code
        if n_tests or n_subs:
            msg += " Kéo theo %d bộ dữ liệu và %d bài nộp của học sinh." % (n_tests, n_subs)
        flash(msg, "ok")
        return redirect(url_for("teacher_problems"))

    # ------------------------------------------ khu giáo viên: tài khoản
    @app.route("/teacher/users")
    @auth.teacher_required
    def teacher_users():
        """Danh sách và công cụ quản lý tài khoản.

        Trước đây giáo viên chỉ **xem** được danh sách lớp. Muốn tạo tài khoản
        cho học sinh mới, đặt lại mật khẩu cho em quên mật khẩu, hay khoá một
        tài khoản bị dùng sai, đều phải nhờ người sửa thẳng CSDL — nghĩa là trên
        thực tế không làm được.
        """
        conn = db.get_db()
        q = (request.args.get("q") or "").strip()
        role = request.args.get("role") or ""

        where, params = [], []
        if q:
            where.append("(username LIKE ? OR full_name LIKE ?)")
            params.extend(["%" + q + "%"] * 2)
        if role in ("student", "teacher", "admin"):
            where.append("role = ?")
            params.append(role)

        sql = """SELECT u.*,
                        (SELECT COUNT(*) FROM submissions WHERE user_id = u.id) AS attempts,
                        (SELECT MAX(created_at) FROM submissions WHERE user_id = u.id) AS last_at
                   FROM users u"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Học sinh xếp theo lớp rồi tên; giáo viên và quản trị lên đầu để không
        # lẫn vào giữa hàng trăm dòng học sinh.
        sql += """ ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'teacher' THEN 1 ELSE 2 END,
                            class_name, full_name"""

        users = [dict(r) for r in db.query(conn, sql, params)]
        return render_template(
            "teacher_users.html",
            active="teacher",
            users=users,
            classes=_class_names(conn),
            q=q,
            role=role,
            min_password_length=MIN_PASSWORD_LENGTH,
        )

    @app.route("/teacher/users/create", methods=["POST"])
    @auth.teacher_required
    def teacher_user_create():
        conn = db.get_db()
        username = (request.form.get("username") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        class_name = (request.form.get("class_name") or "").strip()
        role = _choice(request.form, "role", ("student", "teacher", "admin"), "student")

        error = None
        if not username or not full_name:
            error = "Cần nhập tên đăng nhập và họ tên."
        elif not username.replace(".", "").replace("_", "").isalnum():
            # Dấu chấm và gạch dưới được phép vì tên đăng nhập của trường có dạng
            # `an.nguyen9a`; còn lại phải là chữ hoặc số, không dấu cách.
            error = "Tên đăng nhập chỉ gồm chữ, số, dấu chấm và gạch dưới."
        elif db.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,)):
            error = "Tên đăng nhập %s đã có người dùng." % username
        elif role == "student" and not class_name:
            error = "Học sinh phải thuộc một lớp."

        if error:
            flash(error, "warn")
            return redirect(url_for("teacher_users"))

        # Mật khẩu đầu tiên do máy sinh và giáo viên đọc cho học sinh. Cờ
        # `must_change_password` bắt em đổi ngay lần đầu đăng nhập, nên mật khẩu
        # này chỉ sống được tới lúc đó.
        temp = auth.make_temp_password()
        with conn:
            conn.execute(
                """INSERT INTO users (username, full_name, class_name, role, password_hash,
                                      is_active, must_change_password, created_at)
                   VALUES (?,?,?,?,?,1,1,?)""",
                (username, full_name, class_name, role, auth.hash_password(temp), db.utc_now()),
            )
        flash("Đã tạo tài khoản %s. Mật khẩu tạm: %s — đọc cho học sinh rồi yêu cầu "
              "đổi ngay lần đầu đăng nhập." % (username, temp), "ok")
        return redirect(url_for("teacher_users", q=username))

    @app.route("/teacher/users/<int:user_id>/update", methods=["POST"])
    @auth.teacher_required
    def teacher_user_update(user_id: int):
        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            abort(404)

        full_name = (request.form.get("full_name") or "").strip()
        class_name = (request.form.get("class_name") or "").strip()
        role = _choice(request.form, "role", ("student", "teacher", "admin"), row["role"])
        is_active = 1 if request.form.get("is_active") else 0

        if not full_name:
            flash("Họ tên không được để trống.", "warn")
            return redirect(url_for("teacher_users"))

        # Chặn tự khoá chính mình. Không có nhánh này thì một cú bấm nhầm ở ô
        # "Đang hoạt động" là giáo viên tự đăng xuất và không vào lại được nữa —
        # và người sửa được chỉ còn là người có quyền trên máy chủ.
        if user_id == auth.current_user()["id"] and not is_active:
            flash("Không thể tự khoá tài khoản đang đăng nhập.", "warn")
            return redirect(url_for("teacher_users"))

        with conn:
            conn.execute(
                "UPDATE users SET full_name = ?, class_name = ?, role = ?, is_active = ? "
                "WHERE id = ?",
                (full_name, class_name, role, is_active, user_id),
            )
        flash("Đã lưu tài khoản %s." % row["username"], "ok")
        return redirect(url_for("teacher_users", q=row["username"]))

    @app.route("/teacher/users/<int:user_id>/reset", methods=["POST"])
    @auth.teacher_required
    def teacher_user_reset(user_id: int):
        """Đặt lại mật khẩu thành một mật khẩu tạm mới và bắt đổi ngay lần sau."""
        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            abort(404)

        temp = auth.make_temp_password()
        with conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                (auth.hash_password(temp), user_id),
            )
        flash("Mật khẩu mới của %s là: %s — đọc cho học sinh rồi yêu cầu đổi ngay."
              % (row["username"], temp), "ok")
        return redirect(url_for("teacher_users", q=row["username"]))

    @app.route("/teacher/users/<int:user_id>/delete", methods=["POST"])
    @auth.teacher_required
    def teacher_user_delete(user_id: int):
        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            abort(404)
        if user_id == auth.current_user()["id"]:
            flash("Không thể xoá tài khoản đang đăng nhập.", "warn")
            return redirect(url_for("teacher_users"))

        n_subs = db.scalar(conn, "SELECT COUNT(*) FROM submissions WHERE user_id = ?", (user_id,))
        # Đề do giáo viên này tạo không bị xoá theo: `problems.author_id` là
        # ON DELETE SET NULL, nên đề ở lại và chỉ mất tên người tạo. Xoá tài khoản
        # một giáo viên mà kéo theo cả kho đề là hậu quả không ai lường trước.
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        msg = "Đã xoá tài khoản %s." % row["username"]
        if n_subs:
            msg += " Kéo theo %d bài nộp của học sinh này." % n_subs
        flash(msg, "ok")
        return redirect(url_for("teacher_users"))

    # ------------------------------------------ khu giáo viên: kỳ thi
    @app.route("/teacher/contests")
    @auth.teacher_required
    def teacher_contests():
        conn = db.get_db()
        contests = []
        for row in db.query(conn, "SELECT * FROM contests ORDER BY starts_at DESC"):
            d = dict(row)
            d["problems"] = [dict(r) for r in db.query(
                conn,
                """SELECT p.id, p.code, p.name, p.status
                     FROM contest_problems cp JOIN problems p ON p.id = cp.problem_id
                    WHERE cp.contest_id = ? ORDER BY p.code""",
                (row["id"],))]
            d["entries"] = db.scalar(conn, "SELECT COUNT(*) FROM contest_entries WHERE contest_id = ?",
                                     (row["id"],))
            contests.append(d)

        return render_template(
            "teacher_contests.html",
            active="teacher",
            contests=contests,
            unjudged=grades.contest_unjudged(conn),
            all_problems=[dict(r) for r in db.query(
                conn, "SELECT id, code, name, status FROM problems ORDER BY code")],
        )

    @app.route("/teacher/contests/<int:contest_id>/export")
    @auth.teacher_required
    def teacher_contest_export(contest_id: int):
        """Xuất kết quả một kỳ thi ra CSV.

        Đây là tệp giáo viên thật sự cần để nộp sổ điểm: một bài kiểm tra là một
        kỳ thi, và điểm cần nộp là điểm **trong kỳ thi đó**, không phải điểm tích
        luỹ cả năm mà trang lớp học hiển thị.
        """
        conn = db.get_db()
        table = grades.contest_table(conn, contest_id)
        if table is None:
            abort(404)
        return _csv_response(table["filename"],
                             grades.to_csv(table, request.args.get("sep") or ";"))

    def _contest_form(form) -> tuple[dict, str | None]:
        """Đọc và kiểm tra biểu mẫu kỳ thi. Trả về ``(giá trị, lỗi)``."""
        name = (form.get("name") or "").strip()
        starts = db.iso_from_local_input(form.get("starts_at") or "")
        ends = db.iso_from_local_input(form.get("ends_at") or "")
        values = {
            "name": name,
            "description": (form.get("description") or "").strip(),
            "starts_at": starts,
            "ends_at": ends,
            "scoring": _choice(form, "scoring", ("ioi", "acm"), "ioi"),
            "status": _choice(form, "status", ("draft", "upcoming", "open", "closed"), "draft"),
        }
        if not name:
            return values, "Cần nhập tên kỳ thi."
        if not starts or not ends:
            return values, "Cần nhập thời gian bắt đầu và kết thúc."
        if ends <= starts:
            return values, "Thời gian kết thúc phải sau thời gian bắt đầu."
        return values, None

    @app.route("/teacher/contests/create", methods=["POST"])
    @auth.teacher_required
    def teacher_contest_create():
        conn = db.get_db()
        values, error = _contest_form(request.form)
        if error:
            flash(error, "warn")
            return redirect(url_for("teacher_contests"))

        with conn:
            conn.execute(
                """INSERT INTO contests (name, description, starts_at, ends_at, scoring,
                                         status, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (values["name"], values["description"], values["starts_at"], values["ends_at"],
                 values["scoring"], values["status"], db.utc_now()),
            )
        flash("Đã tạo kỳ thi «%s»." % values["name"], "ok")
        return redirect(url_for("teacher_contests"))

    @app.route("/teacher/contests/<int:contest_id>/update", methods=["POST"])
    @auth.teacher_required
    def teacher_contest_update(contest_id: int):
        conn = db.get_db()
        if db.query_one(conn, "SELECT id FROM contests WHERE id = ?", (contest_id,)) is None:
            abort(404)

        values, error = _contest_form(request.form)
        if error:
            flash(error, "warn")
            return redirect(url_for("teacher_contests"))

        with conn:
            conn.execute(
                """UPDATE contests SET name = ?, description = ?, starts_at = ?, ends_at = ?,
                                       scoring = ?, status = ?
                    WHERE id = ?""",
                (values["name"], values["description"], values["starts_at"], values["ends_at"],
                 values["scoring"], values["status"], contest_id),
            )
        flash("Đã lưu kỳ thi «%s»." % values["name"], "ok")
        return redirect(url_for("teacher_contests"))

    @app.route("/teacher/contests/<int:contest_id>/problems", methods=["POST"])
    @auth.teacher_required
    def teacher_contest_problems(contest_id: int):
        """Ghi lại danh sách đề của kỳ thi theo đúng những ô được tích.

        Xoá hết rồi ghi lại, thay vì tính xem cái nào thêm cái nào bớt: danh sách
        đề của một kỳ thi chỉ vài chục dòng, và cách này không thể lệch với giao
        diện — điều mà cách tính hiệu số rất dễ mắc.

        ------------------------------------------------------------------
        Hai chỗ đã từng sai ở đây, xin đừng lặp lại

        `contest_problems.ordinal` là ``NOT NULL`` và **không có giá trị mặc
        định**. Câu lệnh cũ không đưa cột đó vào, lại còn dùng
        ``INSERT OR IGNORE`` — nên mọi lượt lưu đều vi phạm ràng buộc, bị bỏ qua
        trong im lặng, và màn hình vẫn báo "đã cập nhật N đề". Giáo viên tích đề
        cho kỳ thi, bấm Lưu, thấy báo thành công, mà kỳ thi vẫn rỗng. Không có
        cách nào phát hiện ngoài việc mở lại trang và đếm.

        Vì vậy: (1) luôn ghi `ordinal` — lấy luôn thứ tự giáo viên tích, vì thứ
        tự đề trong một kỳ thi là thông tin có nghĩa; (2) bỏ ``OR IGNORE``. Nuốt
        lỗi ràng buộc là cách biến một lỗi ồn ào thành một lỗi im lặng, và loại
        lỗi im lặng là loại đắt nhất.
        """
        conn = db.get_db()
        if db.query_one(conn, "SELECT id FROM contests WHERE id = ?", (contest_id,)) is None:
            abort(404)

        # Bỏ trùng ngay từ đây: một biểu mẫu méo có thể gửi cùng một mã đề hai
        # lần, và khi đó khoá chính (contest_id, problem_id) sẽ chặn dòng thứ hai.
        ids = []
        for value in request.form.getlist("problem_id"):
            try:
                pid = int(value)
            except (TypeError, ValueError):
                continue
            if pid not in ids:
                ids.append(pid)

        saved = 0
        with conn:
            conn.execute("DELETE FROM contest_problems WHERE contest_id = ?", (contest_id,))
            for pid in ids:
                if db.query_one(conn, "SELECT id FROM problems WHERE id = ?", (pid,)) is None:
                    continue
                saved += 1
                conn.execute(
                    "INSERT INTO contest_problems (contest_id, problem_id, ordinal) "
                    "VALUES (?, ?, ?)", (contest_id, pid, saved))

        # Báo số đề **đã lưu**, không phải số ô đã tích: hai con số này khác nhau
        # khi một đề bị xoá ở tab khác trong lúc giáo viên đang tích.
        msg = "Đã lưu danh sách đề của kỳ thi: %d đề." % saved
        if saved < len(ids):
            msg += " Bỏ qua %d đề không còn tồn tại." % (len(ids) - saved)
        flash(msg, "ok")
        return redirect(url_for("teacher_contests"))

    @app.route("/teacher/contests/<int:contest_id>/delete", methods=["POST"])
    @auth.teacher_required
    def teacher_contest_delete(contest_id: int):
        conn = db.get_db()
        row = db.query_one(conn, "SELECT * FROM contests WHERE id = ?", (contest_id,))
        if row is None:
            abort(404)

        # `contest_entries` và `contest_problems` xoá theo. Còn `submissions`
        # không trỏ tới kỳ thi bằng khoá ngoại có cascade — `contest_id` ở đó là
        # ON DELETE SET NULL — nên bài nộp **ở lại**, chỉ mất liên kết tới kỳ thi.
        # Đó là chủ ý: bài học sinh đã làm không nên biến mất vì kỳ thi bị dọn.
        n_entries = db.scalar(conn, "SELECT COUNT(*) FROM contest_entries WHERE contest_id = ?",
                              (contest_id,))
        with conn:
            conn.execute("DELETE FROM contests WHERE id = ?", (contest_id,))

        flash("Đã xoá kỳ thi «%s»%s." % (
            row["name"],
            " (kèm %d lượt đăng ký)" % n_entries if n_entries else ""), "ok")
        return redirect(url_for("teacher_contests"))

    @app.route("/teacher/classes")
    @auth.teacher_required
    def teacher_classes():
        conn = db.get_db()
        class_name = (request.args.get("class") or "").strip()
        classes = _class_names(conn)
        if not class_name and classes:
            class_name = classes[0]

        students = []
        summary = {"size": 0, "avg": 0, "best": 0, "idle": 0, "active": 0}
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
                    # "Đang hoạt động" là tài khoản chưa bị khoá (`is_active`), KHÔNG
                    # phải "đã từng nộp bài". Trước đây mẫu template tính
                    # `size - idle`, ra đúng con số "đã từng nộp bài" nhưng dán nhãn
                    # sai — và mâu thuẫn với chính gợi ý ngay dưới bảng, vốn nói về
                    # tài khoản bị khoá.
                    "active": sum(1 for s in students if s["is_active"]),
                }

        return render_template(
            "teacher_classes.html",
            active="teacher",
            classes=classes,
            class_name=class_name,
            students=students,
            summary=summary,
            unjudged=grades.class_unjudged(conn, class_name) if class_name else 0,
        )

    def _csv_response(filename: str, body: bytes):
        """Trả về một tệp CSV để tải xuống.

        Ba chi tiết trong tiêu đề, mỗi cái vì một lý do đã kiểm chứng:

        - `Content-Disposition` chứ **tên tệp không dấu**. Tiêu đề HTTP mặc định
          là latin-1, nên đưa chữ có dấu vào đó thì hoặc ném lỗi, hoặc bị mã hoá
          sai và trình duyệt lưu ra một tên tệp rác. `grades.slug` bỏ dấu trước
          khi tên tệp tới đây.
        - `charset=utf-8` khai báo đúng bảng mã. Thân tệp có BOM UTF-8, và BOM là
          thứ Excel thật sự đọc — khai báo ở đây để mọi trình đọc khác cũng biết.
        - `no-store` để không ai giữ lại một bản điểm cũ: nội dung tệp phụ thuộc
          vào điểm đã chấm tới lúc nào, và một bản lưu đệm sẽ nói dối về điều đó.
        """
        return Response(
            body,
            content_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="%s"' % filename,
                "Cache-Control": "no-store",
            },
        )

    @app.route("/teacher/classes/export")
    @auth.teacher_required
    def teacher_class_export():
        """Xuất bảng điểm của một lớp ra CSV.

        `sep` nhận từ chuỗi truy vấn nhưng **không có trong giao diện**: mặc
        định `;` đã đúng cho cả Excel tiếng Việt lẫn Google Sheets (Google Sheets
        tự nhận ra dấu phân cách), nên một ô chọn nữa chỉ làm giáo viên phải
        quyết định một việc họ không có căn cứ để quyết. Giữ lại đường ghi đè cho
        trường hợp dùng phần mềm khác.
        """
        conn = db.get_db()
        table = grades.class_table(conn, request.args.get("class") or "")
        if table is None:
            flash("Em chưa chọn lớp nào để xuất điểm.", "warn")
            return redirect(url_for("teacher_classes"))
        return _csv_response(table["filename"],
                             grades.to_csv(table, request.args.get("sep") or ";"))


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

    Thứ tự khi bằng điểm: nhiều đề giải trọn vẹn hơn xếp trên, rồi tới ai đạt
    điểm ấy **sớm hơn**. Trước đây tiêu chí cuối cùng là tên học sinh, nghĩa là
    thứ tự alphabet quyết định hạng giữa các em cùng điểm — vừa tùy tiện vừa
    trông như lỗi khi sáu em cùng 100 điểm nhận sáu hạng khác nhau.
    """
    where = ["u.role = 'student'"]
    params: list = []
    if scope:
        where.append("u.class_name = ?")
        params.append(scope)
    params.append(limit)

    rows = db.query(
        conn,
        f"""SELECT u.id, u.full_name, u.class_name, u.avatar_file,
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
                   (SELECT COUNT(*) FROM submissions WHERE user_id = u.id AND verdict = 'AC') AS accepted,
                   COALESCE((SELECT MIN(created_at) FROM submissions
                              WHERE user_id = u.id AND verdict = 'AC'), '9999') AS first_ac
              FROM users u
             WHERE {' AND '.join(where)}
             ORDER BY score DESC, solved DESC, first_ac, u.full_name
             LIMIT ?""",
        params,
    )
    out = []
    prev_key = None
    prev_rank = 0
    for i, r in enumerate(rows):
        d = dict(r)
        # Hạng kiểu thi đấu (1-2-2-4): chỉ bằng hạng khi bằng **cả** khoá phân
        # định, tức là bằng điểm, bằng số đề giải trọn vẹn và cùng thời điểm đạt.
        # Đánh số thuần theo vị trí sẽ biến một khác biệt không hiển thị ở đâu
        # thành một bậc hạng khác nhau trên giao diện.
        key = (r["score"], r["solved"], r["first_ac"])
        if key != prev_key:
            prev_rank = i + 1
            prev_key = key
        d["rank"] = prev_rank
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
        # "chạm giới hạn", không phải "dùng quá": bộ chấm xếp MLE ngay từ 92% giới
        # hạn (xem MEMORY_PRESSURE_RATIO trong judge.py), nên một bài 255 MB trên
        # giới hạn 256 MB vẫn là MLE — nói "dùng quá 256 MB" ở đây là mâu thuẫn với
        # con số hiện ngay bên cạnh.
        return (f"Đạt {passed}/{total} bộ dữ liệu. Chương trình chạm giới hạn "
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
def _parse_limits(form) -> tuple[int, int]:
    """Đọc giới hạn thời gian và bộ nhớ từ biểu mẫu, đã kẹp vào khoảng hợp lý.

    Kẹp chứ không báo lỗi là có chủ ý: một giới hạn thời gian bằng 0 sẽ khiến mọi
    bài nộp đều bị xử là quá thời gian, và giáo viên sẽ tưởng học sinh làm sai.
    Dùng chung cho cả tạo và sửa đề để hai đường không thể lệch nhau.
    """
    try:
        time_ms = int(float(form.get("time_limit_s") or 1) * 1000)
    except (TypeError, ValueError):
        time_ms = 1000
    try:
        memory_mb = int(form.get("memory_limit_mb") or 256)
    except (TypeError, ValueError):
        memory_mb = 256
    return (max(MIN_TIME_MS, min(time_ms, MAX_TIME_MS)),
            max(MIN_MEMORY_MB, min(memory_mb, MAX_MEMORY_MB)))


def _choice(form, key: str, allowed: tuple[str, ...], fallback: str) -> str:
    """Lấy một giá trị trong danh sách cho phép; giá trị lạ thì lùi về mặc định."""
    value = (form.get(key) or "").strip()
    return value if value in allowed else fallback


def _password_problem(new: str, confirm: str, username: str) -> str | None:
    """Kiểm tra mật khẩu mới. Trả về câu thông báo lỗi, hoặc None nếu hợp lệ.

    Tách riêng khỏi tuyến đường để kiểm thử được mà không cần dựng cả request, và
    để mọi quy tắc về mật khẩu nằm cùng một chỗ — rải ra nhiều nhánh `if` trong
    hàm xử lý thì lần sau thêm quy tắc sẽ có chỗ quên.
    """
    if new != confirm:
        return "Hai lần nhập mật khẩu mới không giống nhau."
    if len(new) < MIN_PASSWORD_LENGTH:
        return "Mật khẩu mới cần ít nhất %d ký tự." % MIN_PASSWORD_LENGTH
    if new.strip() != new:
        return "Mật khẩu không nên bắt đầu hoặc kết thúc bằng dấu cách."
    if new.lower() == username.lower():
        return "Mật khẩu không được trùng với tên đăng nhập."
    # Danh sách ngắn những mật khẩu mà học sinh thật sự hay đặt. Không phải để
    # chống dò — PBKDF2 lo việc đó — mà để chặn đúng những chuỗi mà cả lớp sẽ
    # đoán ra ngay khi muốn nghịch tài khoản của bạn mình.
    weak = {"12345678", "123456789", "password", "matkhau", "matkhau123",
            "iloveyou", "qwertyui", "abc12345", "11111111", "00000000",
            "hocsinh123", "songlo123"}
    if new.lower() in weak:
        return "Mật khẩu này quá dễ đoán. Em chọn mật khẩu khác nhé."
    return None


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

    time_ms, memory_mb = _parse_limits(form)
    now = db.utc_now()
    with conn:
        conn.execute(
            """INSERT INTO problems
                 (code, name, difficulty, topic, statement, time_limit_ms,
                  memory_limit_mb, points_mode, status, author_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)""",
            (
                code, name,
                _choice(form, "difficulty", DIFFICULTIES, "co-ban"),
                (form.get("topic") or "").strip(),
                statement, time_ms, memory_mb,
                _choice(form, "points_mode", POINTS_MODES, "even"),
                user["id"], now, now,
            ),
        )
    return None


def _form_values(form, problem) -> dict:
    """Giá trị để hiển thị lại trong biểu mẫu sửa đề.

    Lấy từ biểu mẫu nếu có, không thì lấy từ CSDL. Dùng khi lưu thất bại: giáo
    viên vừa gõ cả một đề dài, không được xoá trắng chỉ vì một ô còn thiếu.
    """
    def pick(key, fallback):
        value = form.get(key)
        return fallback if value is None else value

    return {
        "name": pick("name", problem["name"]),
        "difficulty": pick("difficulty", problem["difficulty"]),
        "topic": pick("topic", problem["topic"]),
        "points_mode": pick("points_mode", problem["points_mode"]),
        "time_limit_s": pick("time_limit_s", f"{problem['time_limit_ms'] / 1000:g}"),
        "memory_limit_mb": pick("memory_limit_mb", problem["memory_limit_mb"]),
        "statement": pick("statement", problem["statement"]),
        "status": pick("status", problem["status"]),
    }


def _update_problem(conn, problem, form) -> str | None:
    """Cập nhật một đề đã có. Trả về thông báo lỗi, hoặc None nếu thành công.

    **Mã đề không đổi được.** Nó là định danh trong đường dẫn
    (`/problems/SL001`, `/teacher/problems/SL001/tests`), nên đổi mã sẽ làm hỏng
    mọi liên kết đã chia sẻ cho học sinh. Muốn mã khác thì tạo đề mới.

    Hàm này cũng đổi được `status`, nhưng đường dẫn **chính** để công khai một
    đề là nút một bấm trên danh sách đề (`_set_problem_status`). Ô chọn trạng
    thái trong biểu mẫu này là chỗ duy nhất đổi được trạng thái trước đây, và vì
    nó nằm sâu trong biểu mẫu sửa đề nên một đề soạn xong cứ nằm lại ở bản nháp:
    `_create_problem` luôn ghi `'draft'`, và trang danh sách đề lọc `status = 'live'`.
    """
    name = (form.get("name") or "").strip()
    statement = (form.get("statement") or "").strip()

    if not name:
        return "Tên bài không được để trống."
    if not statement:
        return "Chưa nhập nội dung đề bài."

    difficulty = _choice(form, "difficulty", DIFFICULTIES, "co-ban")
    points_mode = _choice(form, "points_mode", POINTS_MODES, "even")
    status = _choice(form, "status", PROBLEM_STATUSES, problem["status"])

    # Nút "Lưu và công khai" gửi kèm `publish=1` và **đè** ô chọn trạng thái.
    # Không đè thì giáo viên bấm "Lưu và công khai" mà ô chọn vẫn đang là "Bản
    # nháp", và đề lại nằm im — đúng cái bẫy cần dẹp.
    if form.get("publish"):
        status = "live"

    time_ms, memory_mb = _parse_limits(form)

    # Không cho công khai một đề chưa có bộ dữ liệu nào — luật nằm ở
    # `_publish_blocker`, dùng chung với nút công khai và bước tự công khai sau
    # khi nhập dữ liệu.
    if status == "live":
        blocker = _publish_blocker(conn, problem)
        if blocker:
            return blocker

    with conn:
        conn.execute(
            """UPDATE problems
                  SET name = ?, difficulty = ?, topic = ?, statement = ?,
                      time_limit_ms = ?, memory_limit_mb = ?, points_mode = ?,
                      status = ?, updated_at = ?
                WHERE id = ?""",
            (name, difficulty, (form.get("topic") or "").strip(), statement,
             time_ms, memory_mb, points_mode, status, db.utc_now(), problem["id"]),
        )
    return None


def _autopublish_after_import(conn, problem, keep_draft: bool) -> bool:
    """Sau khi nhập **hoặc sinh** bộ dữ liệu: tự công khai nếu đang ở bản nháp.

    Một chỗ duy nhất giữ luật này, vì có hai đường dẫn tới đây (nhập tệp ZIP và
    sinh từ lời giải mẫu) và mỗi nơi tự quyết thì sớm muộn có nơi quên.

    Chỉ tự công khai khi đề đang ở ``draft``, tức là chưa ai quyết định gì. Đề
    đang ở ``review`` là giáo viên đã chọn rõ ràng, không tự đổi.
    """
    if keep_draft or problem["status"] != "draft":
        return False
    return _set_problem_status(conn, problem, "live") is None


def _publish_note(problem, published: bool) -> str:
    """Câu nối vào thông báo, nói rõ đề có ra tới học sinh hay chưa.

    Không nói gì là chỗ dễ sai nhất: giáo viên nhập xong, mở trang học sinh,
    không thấy đề, và tưởng hệ thống hỏng. Nên khi đề vẫn ở bản nháp thì phải
    nói thẳng ra.
    """
    if published:
        return " Đề đã được công khai — học sinh đã thấy đề này."
    if problem["status"] == "draft":
        return " Đề vẫn ở bản nháp, học sinh chưa thấy."
    return ""


def _insert_tests(conn, problem, tests, replace: bool) -> None:
    """Ghi các bộ dữ liệu vào CSDL, tiếp nối số thứ tự đang có.

    Bộ nhập từ ngoài vào mặc định là **ẩn**: đề của trường thường lấy từ kho
    chung, và nếu hiện hết thì học sinh chỉ cần mở đề là thấy toàn bộ đáp án.
    """
    with conn:
        if replace:
            conn.execute("DELETE FROM tests WHERE problem_id = ?", (problem["id"],))

        ordinal = db.scalar(
            conn, "SELECT COALESCE(MAX(ordinal), 0) FROM tests WHERE problem_id = ?",
            (problem["id"],))
        for t in tests:
            ordinal += 1
            conn.execute(
                """INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points, note)
                   VALUES (?, ?, ?, ?, 1, 0, ?)""",
                (problem["id"], ordinal, t["input"], t["output"], t["name"]),
            )
        conn.execute("UPDATE problems SET updated_at = ? WHERE id = ?",
                     (db.utc_now(), problem["id"]))


def _import_themis_zip(conn, problem, code: str):
    """Nhập bộ dữ liệu từ tệp ZIP kiểu Themis.

    Đây là cách nhập dữ liệu **chính** cho một đề thật: đề thi có 20–40 bộ, dán
    tay từng bộ là mất cả buổi và chắc chắn có lỗi sao chép — mà lỗi sao chép
    trong bộ dữ liệu thì không ai phát hiện cho tới lúc học sinh bị chấm sai.

    Thay thế toàn bộ hay thêm vào? Mặc định là **thêm vào**, vì xoá dữ liệu cũ
    là việc không hoàn tác được và không nên xảy ra chỉ vì giáo viên bấm nhầm
    một nút. Muốn thay thì phải tích ô xác nhận riêng.
    """
    upload = request.files.get("zip")
    if upload is None or not upload.filename:
        flash("Em chưa chọn tệp ZIP nào.", "warn")
        return redirect(url_for("teacher_problem_tests", code=code))

    raw = upload.read(themis.MAX_TOTAL_BYTES + 1)
    if len(raw) > themis.MAX_TOTAL_BYTES:
        flash("Tệp ZIP quá lớn (giới hạn %d MB)." % (themis.MAX_TOTAL_BYTES // (1024 * 1024)),
              "warn")
        return redirect(url_for("teacher_problem_tests", code=code))

    tests, report = themis.parse_zip(raw)

    if report.get("error"):
        flash(report["error"], "warn")
        return redirect(url_for("teacher_problem_tests", code=code))

    replace = bool(request.form.get("replace"))
    _insert_tests(conn, problem, tests, replace)

    # Nhập xong bộ dữ liệu là lúc đề **đủ điều kiện** ra tới học sinh. Đây là
    # chỗ hay bị bỏ sót nhất: giáo viên soạn đề ở trang soạn đề, nhập dữ liệu ở
    # trang bộ dữ liệu, và không có gì trên màn hình nói rằng đề vẫn đang là bản
    # nháp — nên đề nằm im, học sinh không thấy, và giáo viên tưởng hệ thống hỏng.
    keep_draft = bool(request.form.get("keep_draft"))
    published = _autopublish_after_import(conn, problem, keep_draft)

    # Báo cáo nói cả phần **không** nhập được. Chỉ báo "đã nhập 24 bộ" mà bỏ qua
    # 6 tệp lẻ là để giáo viên tin rằng đề đã đủ dữ liệu, trong khi thực tế thiếu.
    msg = "Đã nhập %d bộ dữ liệu từ ZIP%s." % (
        len(tests), " (đã thay toàn bộ bộ cũ)" if replace else "")
    leftovers = []
    if report["orphan_in"]:
        leftovers.append("%d tệp vào không có tệp ra" % report["orphan_in"])
    if report["orphan_out"]:
        leftovers.append("%d tệp ra không có tệp vào" % report["orphan_out"])
    if report["skipped"]:
        leftovers.append("%d tệp không nhận dạng được" % report["skipped"])
    if leftovers:
        msg += " Bỏ qua: " + ", ".join(leftovers) + "."
    msg += _publish_note(problem, published)
    flash(msg, "ok" if not leftovers else "warn")
    return redirect(url_for("teacher_problem_tests", code=code))


def _render_tests(conn, problem, **extra):
    """Dựng trang bộ dữ liệu của một đề.

    Tách ra khỏi tuyến đường vì đường **nhờ AI viết** không chuyển hướng: nó phải
    trả về chính trang này với hai ô mã nguồn đã điền sẵn. `flash` + `redirect`
    là cách thường dùng, nhưng nó không mang theo được hai chương trình vừa nhận
    — mà gọi lại AI thì tốn thêm hai chục giây.
    """
    tests = db.query(
        conn, "SELECT * FROM tests WHERE problem_id = ? ORDER BY ordinal", (problem["id"],))
    context = {
        "active": "teacher",
        "problem": problem,
        "tests": tests,
        "max_count": gendata.MAX_COUNT,
        "compile_flags": "g++ " + " ".join(COMPILE_FLAGS),
        # Chưa cấu hình khoá API thì thẻ nhờ AI viết không được dựng ra chút nào.
        # Hiện một nút bấm rồi báo "chưa cấu hình" là cách tệ nhất để tắt một
        # tính năng: giáo viên tưởng nó hỏng.
        "ai_enabled": bool(current_app.config.get("AI_KEY")),
    }
    context.update(extra)
    return render_template("teacher_tests.html", **context)


def _ai_write_tests(conn, problem):
    """Nhờ AI viết bộ sinh và lời giải mẫu, rồi **điền vào hai ô** của biểu mẫu.

    Cố ý dừng ở đó, không sinh dữ liệu luôn. Mã do AI viết sẽ được biên dịch rồi
    chạy trên máy chủ, và không có gì bảo đảm nó đúng — kể cả khi nó dịch được.
    Giáo viên đọc lại rồi bấm nút: một bước, đổi lấy việc không chạy mã chưa ai
    đọc. Đây cũng là lý do không có tham số kiểu "viết rồi sinh luôn".
    """
    statement = (request.form.get("statement") or problem["statement"] or "").strip()
    if not statement:
        flash("Chưa có đề bài để nhờ AI đọc. Dán đề bài vào ô trên, hoặc lưu đề "
              "bài trong phần sửa đề trước.", "warn")
        return _render_tests(conn, problem)

    if len(statement) > aiwriter.MAX_STATEMENT_CHARS:
        flash("Đề bài dài quá %d ký tự. Cắt bớt rồi thử lại."
              % aiwriter.MAX_STATEMENT_CHARS, "warn")
        return _render_tests(conn, problem, ai_statement=statement)

    try:
        count = int(request.form.get("count") or 10)
    except (TypeError, ValueError):
        count = 10

    try:
        gen, sol = aiwriter.write(
            statement,
            base=current_app.config["AI_BASE"],
            key=current_app.config["AI_KEY"],
            model=current_app.config["AI_MODEL"],
            # Giới hạn của **chính đề này**, để bộ sinh biết phải tạo dữ liệu lớn
            # tới đâu cho vừa thời gian chạy.
            time_limit_ms=problem["time_limit_ms"],
            memory_limit_mb=problem["memory_limit_mb"],
            count=max(1, min(count, gendata.MAX_COUNT)),
            timeout=current_app.config["AI_TIMEOUT"],
        )
    except aiwriter.AIError as exc:
        # Giữ lại đề bài vừa dán: bắt dán lại sau khi chờ hai chục giây là kiểu
        # làm phiền khiến người ta thôi dùng tính năng.
        flash(str(exc), "warn")
        # Lỗi "không tách được" xảy ra **sau khi** đã nhận được câu trả lời: mã
        # nguồn vẫn nằm trong đó, chỉ là mô hình đánh dấu khác đi. Vứt đi thì giáo
        # viên chờ 13 giây và nhận về con số không. Đặt nguyên văn vào ô bộ sinh,
        # kèm một câu nói rõ phải làm gì — thêm một bước, đổi lấy việc không mất gì.
        raw = getattr(exc, "raw", "")
        if raw:
            flash("Câu trả lời của AI vẫn còn nguyên trong ô «Bộ sinh dữ liệu» ở "
                  "dưới. Em chưa tách được vì nó đánh dấu khác đi — cắt hai chương "
                  "trình ra hai ô rồi bấm «Sinh bộ dữ liệu».", "info")
        return _render_tests(conn, problem, ai_statement=statement, ai_gen=raw)

    flash("AI đã viết xong. Đọc lại hai chương trình rồi bấm «Sinh bộ dữ liệu» ở "
          "thẻ dưới. Đáp án của mọi bộ đều lấy từ lời giải mẫu, nên nó sai thì cả "
          "bộ dữ liệu sai theo.", "ok")
    return _render_tests(conn, problem, ai_statement=statement, ai_gen=gen, ai_sol=sol)


def _generate_tests(conn, problem, code: str):
    """Sinh bộ dữ liệu từ một bộ sinh và một lời giải mẫu.

    Đây là đường trả lời cho câu hỏi thật của giáo viên: *"lấy dữ liệu chấm ở
    đâu?"* — xem `docs/nguon-de.md`. Các kho đề Việt Nam cho đề bài nhưng không
    cho dữ liệu; không có dữ liệu thì đề không chấm được.

    Khác `_import_themis_zip` ở chỗ nào: ở đây giáo viên **không** tải tệp lên,
    mà đưa hai chương trình C++ và hệ thống tự tạo dữ liệu. Cùng kết quả cuối
    (các bộ ``input``/``output`` nằm trong CSDL), nên phần ghi vào CSDL và phần
    tự công khai dùng chung helper với đường nhập ZIP.
    """
    gen_source = request.form.get("gen_source") or ""
    sol_source = request.form.get("sol_source") or ""

    if not gen_source.strip() or not sol_source.strip():
        flash("Cần cả bộ sinh dữ liệu và lời giải mẫu.", "warn")
        return redirect(url_for("teacher_problem_tests", code=code))

    # Chặn theo số byte trước khi chạm tới trình dịch: `compile_source` ghi mã
    # nguồn ra đĩa, nên một ô dán nhầm cả tệp log cũng thành một tệp trên ổ đĩa.
    for label, src in (("Bộ sinh dữ liệu", gen_source), ("Lời giải mẫu", sol_source)):
        if len(src.encode("utf-8")) > gendata.MAX_SOURCE_BYTES:
            flash("%s dài quá %d KB." % (label, gendata.MAX_SOURCE_BYTES // 1024), "warn")
            return redirect(url_for("teacher_problem_tests", code=code))

    try:
        count = int(request.form.get("count") or 10)
    except (TypeError, ValueError):
        count = 10

    tests, error = gendata.generate_tests(
        gen_source, sol_source, count, app.config["GENDATA_WORKSPACE"])

    # Sinh được một phần vẫn ghi phần đó vào: giáo viên đã chờ, và bỏ đi thì họ
    # chẳng được gì. Thông báo lỗi nói rõ đã dừng ở đâu.
    if not tests:
        flash(error or "Không sinh được bộ dữ liệu nào.", "warn")
        return redirect(url_for("teacher_problem_tests", code=code))

    _insert_tests(conn, problem, tests, replace=False)
    published = _autopublish_after_import(
        conn, problem, keep_draft=bool(request.form.get("keep_draft")))

    msg = "Đã sinh %d bộ dữ liệu." % len(tests)
    msg += _publish_note(problem, published)
    if error:
        msg += " " + error
    flash(msg, "warn" if error else "ok")
    return redirect(url_for("teacher_problem_tests", code=code))


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

    # Flask trả 413 khi thân request vượt MAX_CONTENT_LENGTH. Không có nhánh này
    # thì học sinh tải lên một ảnh 8 MB sẽ nhận trang lỗi mặc định bằng tiếng Anh
    # ("Request Entity Too Large"), không nói được là ảnh quá lớn hay phải làm gì.
    @app.errorhandler(413)
    def too_large(_e):
        return render_template(
            "error.html", active="", code=413, title="Tệp quá lớn",
            message="Ảnh em chọn lớn hơn %d MB. Em chọn ảnh nhỏ hơn nhé."
                    % (avatars.MAX_UPLOAD_BYTES // (1024 * 1024)),
        ), 413


# Cho phép `flask --app server.app run` và `python -m server.app`.
app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("SONGLO_HOST", "127.0.0.1"),
        port=int(os.environ.get("SONGLO_PORT", "5000")),
        debug=os.environ.get("SONGLO_DEBUG") == "1",
    )
