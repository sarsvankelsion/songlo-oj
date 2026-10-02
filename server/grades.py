"""Xuất bảng điểm ra tệp CSV để nộp sổ điểm.

Vì sao cần: trước tệp này, điểm chỉ đọc được **trên màn hình**. Giáo viên muốn
nộp sổ điểm thì phải chép tay từng con số — một lớp 40 em nhân với 5 đề là 200
lần chép, và mỗi lần là một cơ hội sai. Đây là việc cản trở công việc thật lớn
nhất còn lại của hệ thống.

Vì sao **CSV** chứ không phải `.xlsx`: `requirements.txt` ghi rõ nguyên tắc giữ
phụ thuộc ở mức tối thiểu, kèm danh sách những gói cố ý **không** dùng — mỗi gói
thêm vào là một thứ phải cập nhật vá bảo mật trên máy chủ của trường. CSV đọc
được bằng Excel, Google Sheets, LibreOffice và mọi ngôn ngữ lập trình, không cần
gói nào. Đổi lại, ba chi tiết dưới đây quyết định tệp có mở đúng hay không, và
cả ba đều là loại lỗi **im lặng** nếu bỏ qua.

1. **BOM UTF-8.** Thiếu ba byte ``\\ufeff`` ở đầu tệp thì Excel bản Windows đoán
   bảng mã theo locale và mọi chữ có dấu thành rác: "Nguyễn Văn An" hiện ra
   thành "Nguyá»…n VÄƒn An". Không có thông báo lỗi nào, chỉ có một tệp đọc
   không được.
2. **Dấu phân cách.** Windows dùng "list separator" theo vùng, và tiếng Việt lấy
   ``,`` làm dấu thập phân nên dấu phân cách danh sách là ``;``. Một tệp ngăn
   bằng ``,`` sẽ dồn **toàn bộ** nội dung vào một cột khi bấm đúp trong Excel.
   Vì vậy mặc định ở đây là ``;``, và có lựa chọn ``,`` cho Google Sheets.
3. **Ô bắt đầu bằng `=`, `+`, `-`, `@`.** Excel coi đó là công thức và thực thi
   (CWE-1236, "CSV injection"). Tên học sinh do giáo viên nhập nên khó xảy ra,
   nhưng một dấu nháy đơn thêm vào rẻ hơn rất nhiều so với việc giải thích vì
   sao một tệp điểm lại chạy được lệnh.

Tệp này không phụ thuộc Flask: nó nhận một kết nối CSDL và trả về dữ liệu thuần,
nên gọi được từ tuyến đường, từ script, hoặc từ bài kiểm thử.
"""

from __future__ import annotations

import csv
import io
import unicodedata

from . import db
from .judge import assign_points

# Điểm tối đa của **một đề**. `judge.judge_submission` chấm mọi đề trên thang
# 100 điểm rồi chia cho các bộ dữ liệu, nên con số này cố định — trừ chế độ
# `custom`, nơi giáo viên tự nhập điểm từng bộ và tổng có thể khác 100. Vì vậy
# điểm tối đa luôn được **tính từ định nghĩa đề**, không lấy hằng số này.
PROBLEM_TOTAL = 100

SEPARATORS = (";", ",")


# ------------------------------------------------------------------ tiện ích
def slug(text: str) -> str:
    """Đổi một chuỗi thành phần tên tệp chỉ có ASCII.

    Tên tệp trong `Content-Disposition` là **tiêu đề HTTP**, và tiêu đề HTTP
    mặc định là latin-1. Đưa thẳng chữ có dấu vào đó thì hoặc là ném lỗi, hoặc
    là bị mã hoá sai và trình duyệt lưu ra một tên tệp rác. Cách đúng theo chuẩn
    là dùng `filename*=UTF-8''…`, nhưng bỏ dấu đi thì đơn giản hơn và không mất
    gì: tên tệp chỉ để người đọc nhận ra nó, còn nội dung mới là dữ liệu.
    """
    # NFD tách "ế" thành "e" + dấu kết hợp; bỏ các ký tự kết hợp là xong.
    plain = "".join(c for c in unicodedata.normalize("NFD", text)
                    if not unicodedata.combining(c))
    plain = plain.replace("đ", "d").replace("Đ", "D")
    out = []
    for c in plain:
        if c.isalnum() and c.isascii():
            out.append(c)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-").lower() or "khong-ten"


def _cell(value) -> str:
    """Chuẩn bị một ô để ghi ra CSV.

    Chỉ chống công thức cho ô **văn bản**. Điểm là số do hệ thống sinh và luôn
    nằm trong khoảng 0–100, nên không cần và không nên chạm vào — thêm dấu nháy
    vào đó sẽ biến một con số thành chuỗi và mọi phép tính trong Excel hỏng.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def to_csv(table: dict, sep: str = ";") -> bytes:
    """Kết xuất bảng thành bytes CSV, kèm BOM.

    ``lineterminator`` là CRLF chứ không phải LF: Excel trên Windows chấp nhận
    cả hai, nhưng CRLF là thứ nó sinh ra và một số bản cũ hiển thị LF thành một
    dòng duy nhất.
    """
    if sep not in SEPARATORS:
        sep = SEPARATORS[0]

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=sep, lineterminator="\r\n",
                        quoting=csv.QUOTE_MINIMAL)
    writer.writerow([_cell(c) for c in table["header"]])
    for row in table["rows"]:
        writer.writerow([_cell(c) for c in row])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


# --------------------------------------------------------------- truy vấn
def _problem_maxes(conn, problems: list[dict]) -> dict:
    """Điểm tối đa của từng đề, tính từ chính định nghĩa đề.

    Không lấy ``MAX(submissions.max_score)``: con số đó là bản chụp lúc chấm, nên
    nếu giáo viên sửa bộ dữ liệu giữa kỳ thì những bài cũ giữ điểm tối đa cũ và
    bảng điểm sẽ trộn hai thang điểm khác nhau. Tính lại từ `tests` thì mọi cột
    đều cùng một thang, đúng bằng thang mà một bài nộp mới sẽ nhận.
    """
    if not problems:
        return {}
    marks = ",".join("?" * len(problems))
    rows = db.query(
        conn,
        "SELECT problem_id, points FROM tests WHERE problem_id IN (%s) "
        "ORDER BY problem_id, ordinal" % marks,
        tuple(p["id"] for p in problems),
    )
    grouped: dict[int, list[int]] = {}
    for r in rows:
        grouped.setdefault(r["problem_id"], []).append(r["points"])

    modes = {p["id"]: p.get("points_mode") or "even" for p in problems}
    out = {}
    for p in problems:
        raw = grouped.get(p["id"], [])
        out[p["id"]] = sum(assign_points(PROBLEM_TOTAL, modes[p["id"]], raw))
    return out


def _unjudged(conn, where: str, params: tuple) -> int:
    """Số bài đã nộp nhưng chưa chấm xong trong phạm vi đang xuất.

    Có mặt để giáo viên biết mà chờ: xuất tệp trong lúc máy chấm còn đang chạy
    sẽ cho ra những ô 0 không phải vì học sinh làm sai, mà vì chưa ai chấm.
    """
    return db.scalar(
        conn,
        "SELECT COUNT(*) FROM submissions s JOIN users u ON u.id = s.user_id "
        "WHERE s.status <> 'done' AND u.role = 'student' AND " + where,
        params,
    )


def class_unjudged(conn, class_name: str) -> int:
    """Số bài chưa chấm xong của một lớp. Dùng để hiện cảnh báo cạnh nút xuất."""
    return _unjudged(conn, "u.class_name = ?", ((class_name or "").strip(),))


def contest_unjudged(conn) -> dict:
    """Số bài chưa chấm xong của **từng** kỳ thi, trong một truy vấn.

    Một truy vấn cho cả danh sách chứ không phải một truy vấn cho mỗi kỳ thi:
    trang kỳ thi liệt kê mọi kỳ thi, và hỏi từng cái sẽ là N+1 truy vấn cho một
    con số chỉ để hiện một dòng gợi ý.
    """
    rows = db.query(
        conn,
        """SELECT s.contest_id, COUNT(*) AS n
             FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE s.status <> 'done' AND s.contest_id IS NOT NULL AND u.role = 'student'
            GROUP BY s.contest_id""",
    )
    return {r["contest_id"]: r["n"] for r in rows}


def _table(conn, students, problems, score_rows, attempt_rows, header_tail,
           filename: str, unjudged: int) -> dict:
    """Ghép danh sách học sinh, danh sách đề và điểm thành một bảng.

    Ô điểm có **ba** trạng thái, không phải hai:

    * **Trống** — chưa từng nộp đề đó, *hoặc* đã nộp nhưng chưa chấm xong.
    * **0** — đã nộp và chấm xong, không được điểm nào.
    * **số dương** — điểm cao nhất trong các lần nộp.

    Gộp trạng thái đầu thành 0 sẽ khiến giáo viên không phân biệt được em bỏ bài
    với em làm sai. Còn gộp trạng thái "chưa chấm xong" thành 0 thì tệ hơn: nó
    nói với giáo viên rằng em làm sai hết, trong khi sự thật là máy chấm còn
    đang chạy — và đó là cách mất điểm của học sinh trong im lặng. Vì vậy ô trống
    giữ nguyên nghĩa "chưa có điểm", và `unjudged` là con số nói vì sao có ô
    trống như thế (giao diện hiện nó thành cảnh báo cạnh nút xuất).

    ``students`` là `sqlite3.Row` chứ không phải dict (xem `db.query`), nên phải
    đọc bằng ``[]``; `Row` không có ``.get()``. Cả hai hàm gọi đều có chọn cột
    `class_name`, và thiếu nó thì ``Row`` ném lỗi ngay chứ không trả rỗng — lỗi
    ồn ào là điều đang muốn.
    """
    best = {(r["user_id"], r["problem_id"]): r["best"] for r in score_rows}
    attempts = {r["user_id"]: r["n"] for r in attempt_rows}
    maxes = _problem_maxes(conn, problems)

    header = ["Họ và tên", "Tên đăng nhập", "Lớp"]
    for p in problems:
        mx = maxes.get(p["id"], 0)
        header.append("%s %s (%d)" % (p["code"], p["name"], mx) if mx
                      else "%s %s" % (p["code"], p["name"]))
    total_max = sum(maxes.values())
    header.append("Tổng điểm (tối đa %d)" % total_max if total_max else "Tổng điểm")
    header.append("Số bài giải trọn vẹn")
    header.extend(header_tail)

    rows = []
    for s in students:
        cells = [s["full_name"], s["username"], s["class_name"]]
        total = 0
        solved = 0
        for p in problems:
            if (s["id"], p["id"]) in best:
                got = best[(s["id"], p["id"])]
                cells.append(got)
                total += got
                if got >= maxes.get(p["id"], 0) > 0:
                    solved += 1
            else:
                cells.append("")
        cells.append(total)
        cells.append(solved)
        cells.extend([attempts.get(s["id"], 0)])
        rows.append(cells)

    return {"filename": filename, "header": header, "rows": rows,
            "unjudged": unjudged, "problem_count": len(problems),
            "total_max": total_max}


# ------------------------------------------------------------------ bảng lớp
def class_table(conn, class_name: str) -> dict | None:
    """Bảng điểm của một lớp: mỗi em một dòng, mỗi đề đã làm một cột."""
    class_name = (class_name or "").strip()
    if not class_name:
        return None

    students = db.query(
        conn,
        """SELECT id, full_name, username, class_name FROM users
            WHERE role = 'student' AND class_name = ?
            ORDER BY full_name""",
        (class_name,),
    )
    # Lớp không có học sinh nghĩa là **không có lớp đó**: `class_name` chỉ tồn
    # tại vì có học sinh mang tên đó. Trả về tệp chỉ có dòng tiêu đề là để giáo
    # viên tải về một tệp trông như thật mà rỗng, rồi mới phát hiện ra.
    if not students:
        return None

    # Cột là những đề **lớp này đã thực sự làm**, không phải mọi đề đang công
    # khai. Một lớp học 5 đề trong học kỳ mà bảng điểm có 30 cột thì không đọc
    # được, và cũng không ai muốn nộp một sổ điểm toàn ô trống.
    #
    # "Đã làm" tính theo **mọi** trạng thái, không chỉ `done`. Lọc theo `done`
    # thì một đề mà cả lớp mới nộp và chưa chấm xong sẽ **không có cột nào** —
    # đề biến mất khỏi sổ điểm, và chỉ có con số `unjudged` ở nơi khác nói rằng
    # có gì đó đang thiếu. Có cột với các ô trống là trung thực hơn: lớp đã làm
    # đề đó, chưa ai chấm.
    problems = [dict(r) for r in db.query(
        conn,
        """SELECT DISTINCT p.id, p.code, p.name, p.points_mode
             FROM submissions s
             JOIN problems p ON p.id = s.problem_id
             JOIN users u ON u.id = s.user_id
            WHERE u.role = 'student' AND u.class_name = ?
            ORDER BY p.code""",
        (class_name,),
    )]

    scores = db.query(
        conn,
        """SELECT s.user_id, s.problem_id, MAX(s.score) AS best
             FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE s.status = 'done' AND u.role = 'student' AND u.class_name = ?
            GROUP BY s.user_id, s.problem_id""",
        (class_name,),
    )
    attempts = db.query(
        conn,
        """SELECT s.user_id, COUNT(*) AS n
             FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE u.role = 'student' AND u.class_name = ?
            GROUP BY s.user_id""",
        (class_name,),
    )

    today = db.to_local(db.utc_now())
    stamp = today.strftime("%Y-%m-%d") if today else ""
    return _table(
        conn, students, problems, scores, attempts,
        header_tail=["Số lượt nộp"],
        filename="bang-diem-lop-%s-%s.csv" % (slug(class_name), stamp),
        unjudged=_unjudged(conn, "u.class_name = ?", (class_name,)),
    )


# --------------------------------------------------------------- bảng kỳ thi
def contest_table(conn, contest_id: int) -> dict | None:
    """Bảng điểm của một kỳ thi: điểm **trong kỳ thi đó**, không phải điểm cả năm."""
    contest = db.query_one(conn, "SELECT * FROM contests WHERE id = ?", (contest_id,))
    if contest is None:
        return None

    problems = [dict(r) for r in db.query(
        conn,
        """SELECT p.id, p.code, p.name, p.points_mode
             FROM contest_problems cp JOIN problems p ON p.id = cp.problem_id
            WHERE cp.contest_id = ?
            ORDER BY cp.ordinal""",
        (contest_id,),
    )]

    # Học sinh có mặt = đã nộp ít nhất một bài trong kỳ thi này. Cố ý lấy **mọi**
    # trạng thái, không chỉ `done`: bảng `contest_entries` chưa có giao diện đăng
    # ký nào nên nó luôn rỗng, và lọc theo `done` sẽ làm một em đang chờ chấm
    # biến mất khỏi sổ điểm — mất điểm của học sinh trong im lặng, đúng loại lỗi
    # tệ nhất. Em đó hiện ra với ô điểm **trống** (chưa có điểm, không phải 0), và
    # `unjudged` bên dưới là con số nói vì sao.
    students = db.query(
        conn,
        """SELECT u.id, u.full_name, u.username, u.class_name FROM users u
            WHERE u.role = 'student' AND EXISTS (
                  SELECT 1 FROM submissions s
                   WHERE s.user_id = u.id AND s.contest_id = ?)
            ORDER BY u.class_name, u.full_name""",
        (contest_id,),
    )
    scores = db.query(
        conn,
        """SELECT s.user_id, s.problem_id, MAX(s.score) AS best
             FROM submissions s
            WHERE s.status = 'done' AND s.contest_id = ?
            GROUP BY s.user_id, s.problem_id""",
        (contest_id,),
    )
    attempts = db.query(
        conn,
        "SELECT user_id, COUNT(*) AS n FROM submissions WHERE contest_id = ? "
        "GROUP BY user_id",
        (contest_id,),
    )

    # Điểm tối đa của kỳ thi là tổng điểm tối đa các đề, KHÔNG dùng
    # `contest_problems.points`: cột đó chỉ có `seed.py` ghi và không chỗ nào
    # đọc, nên nó không phải thang điểm thật. Bộ chấm luôn cho mỗi đề tối đa
    # 100 điểm (`judge.PROBLEM_TOTAL`).
    return _table(
        conn, students, problems, scores, attempts,
        header_tail=["Số lượt nộp"],
        filename="ket-qua-%s-%s.csv" % (slug(contest["name"]), contest_id),
        unjudged=_unjudged(conn, "s.contest_id = ?", (contest_id,)),
    )
