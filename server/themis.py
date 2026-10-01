"""Đọc bộ dữ liệu chấm bài từ tệp ZIP theo cách đặt tên của Themis.

Vì sao cần: một đề thi thật có 20–40 bộ dữ liệu. Bắt giáo viên dán tay từng bộ
vào hai ô là việc làm mất cả buổi và chắc chắn có lỗi sao chép — mà lỗi sao chép
trong bộ dữ liệu thì không ai phát hiện cho tới lúc học sinh bị chấm sai.

**Chấp nhận nhiều cách đặt tên, không chỉ một.** Các kho đề của trường đến từ
nhiều nguồn và không thống nhất: có bộ đặt `TEST01/SL001.INP`, có bộ để phẳng
`SL001.INP`, có bộ dùng `.in`/`.out` chữ thường. Từ chối tất cả trừ một kiểu là
biến việc nhập dữ liệu thành một câu đố. Ở đây chỉ cần **một tệp vào và một tệp
ra cùng tên gốc trong cùng thư mục** là đủ để ghép thành một bộ.

Quy ước phần mở rộng, không phân biệt chữ hoa chữ thường:
    vào:  .inp, .in, .inp.txt
    ra:   .out, .ans, .out.txt, .sol

Thứ tự các bộ được giữ theo tên thư mục rồi tên tệp, để `TEST01`, `TEST02`,
`TEST10` xếp đúng thứ tự số học chứ không phải thứ tự chuỗi (`TEST10` không được
đứng trước `TEST2`).
"""

from __future__ import annotations

import io
import re
import zipfile

# Phần mở rộng nhận là "dữ liệu vào", xếp dài trước ngắn để `.inp.txt` không bị
# cắt nhầm thành `.txt`.
INPUT_EXTS = ("inp.txt", "in.txt", "inp", "in")
OUTPUT_EXTS = ("out.txt", "ans.txt", "sol.txt", "out", "ans", "sol")

# Trần an toàn. Một đề của cấp 2 không bao giờ chạm tới các con số này, nhưng một
# tệp ZIP được chế ra thì có — và giải nén không giới hạn là cách làm sập máy chủ
# bằng một tệp tải lên vài chục KB.
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 4000
MAX_TEST_BYTES = 4 * 1024 * 1024

# Bảng mã thử lần lượt. Đây là chuyện thật, không phải phòng xa: bộ dữ liệu cũ
# của các trường thường lưu bằng CP1258 (tiếng Việt trên Windows), và có bộ còn
# dùng TCVN3 — đọc bằng UTF-8 sẽ ra một chuỗi ký tự rác mà **không báo lỗi**,
# rồi bộ dữ liệu sai đó được đem đi chấm cho học sinh.
ENCODINGS = ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1")


def _decode(raw: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    # latin-1 nhận mọi byte nên nhánh này không tới được, nhưng để lại cho rõ ý.
    return raw.decode("latin-1", "replace").replace("\r\n", "\n")


def _strip_ext(name: str) -> tuple[str, str]:
    """Tách tên tệp thành (tên gốc, loại) với loại là ``'in'``/``'out'``/``''``."""
    low = name.lower()
    for ext in INPUT_EXTS:
        if low.endswith("." + ext):
            return name[: -(len(ext) + 1)], "in"
    for ext in OUTPUT_EXTS:
        if low.endswith("." + ext):
            return name[: -(len(ext) + 1)], "out"
    return name, ""


def _sort_key(name: str):
    """Sắp xếp theo số trong tên trước, rồi mới tới chuỗi.

    Không có bước này thì `TEST10` đứng ngay sau `TEST1`, và thứ tự bộ dữ liệu
    trên trang đề bài sai — nhìn thì nhỏ, nhưng giáo viên đối chiếu với Themis sẽ
    thấy lệch và không biết tin cái nào.
    """
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _is_junk(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return (not base or base.startswith(".")
            or name.startswith("__MACOSX/")
            or base.lower() in ("thumbs.db", "desktop.ini"))


def parse_zip(data: bytes) -> tuple[list[dict], dict]:
    """Đọc tệp ZIP và trả về ``(danh_sách_bộ_dữ_liệu, báo_cáo)``.

    Mỗi bộ dữ liệu là ``{'name': …, 'input': …, 'output': …}``.

    Không ném ngoại lệ cho dữ liệu vào sai: trả về báo cáo để tầng giao diện nói
    cho giáo viên biết chuyện gì đã xảy ra. Ném lỗi ra ngoài thì giáo viên chỉ
    nhận một trang lỗi và không biết tệp mình sai ở đâu.
    """
    report = {"files": 0, "pairs": 0, "orphan_in": 0, "orphan_out": 0,
              "skipped": 0, "truncated": False}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [], dict(report, error="Tệp không phải ZIP hợp lệ.")
    except Exception:
        return [], dict(report, error="Không đọc được tệp ZIP.")

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not _is_junk(i.filename)]
        report["files"] = len(infos)

        if len(infos) > MAX_FILES:
            return [], dict(report, error="Tệp ZIP có quá nhiều tệp (giới hạn %d)." % MAX_FILES)
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL_BYTES:
            return [], dict(report,
                            error="Dung lượng giải nén quá lớn (giới hạn %d MB)."
                                  % (MAX_TOTAL_BYTES // (1024 * 1024)))

        # Gom theo (thư mục, tên gốc). Khoá là thứ quyết định việc ghép cặp: hai
        # tệp cùng tên gốc nhưng khác thư mục là hai bộ dữ liệu khác nhau.
        buckets: dict[tuple[str, str], dict] = {}
        for info in infos:
            path = info.filename
            folder = path.rsplit("/", 1)[0] if "/" in path else ""
            base = path.rsplit("/", 1)[-1]
            stem, kind = _strip_ext(base)
            if not kind:
                report["skipped"] += 1
                continue
            if info.file_size > MAX_TEST_BYTES:
                report["skipped"] += 1
                continue
            try:
                content = _decode(zf.read(info))
            except Exception:
                report["skipped"] += 1
                continue
            buckets.setdefault((folder, stem), {})[kind] = content

        tests = []
        for (folder, stem), pair in sorted(
                buckets.items(), key=lambda kv: (_sort_key(kv[0][0]), _sort_key(kv[0][1]))):
            if "in" in pair and "out" in pair:
                label = stem if not folder else "%s/%s" % (folder, stem)
                tests.append({"name": label, "input": pair["in"], "output": pair["out"]})
            elif "in" in pair:
                report["orphan_in"] += 1
            else:
                report["orphan_out"] += 1

        report["pairs"] = len(tests)
        if not tests and not report.get("error"):
            report["error"] = ("Không ghép được cặp dữ liệu nào. Cần mỗi bộ có một tệp "
                               "vào (.INP) và một tệp ra (.OUT) cùng tên gốc.")
        return tests, report
