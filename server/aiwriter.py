"""Nhờ một mô hình ngôn ngữ viết bộ sinh dữ liệu và lời giải mẫu từ đề bài.

Vì sao có tệp này: `gendata.py` đã trả lời được câu hỏi *"lấy dữ liệu chấm ở
đâu?"* — nhưng chỉ khi giáo viên **đã có** hai chương trình C++ trong tay. Với
giáo viên THCS, bước còn lại đó vẫn là rào cản thật: phần lớn không viết C++
thường xuyên, nên một đề 20 bộ vẫn tốn cả buổi. Tệp này lấp đúng bước đó — đưa
đề bài, nhận về hai chương trình, rồi để giáo viên **đọc lại** trước khi dùng.

Bốn nguyên tắc thiết kế, và lý do của từng cái:

- **Không tự chạy.** Hàm ở đây chỉ *trả về* mã nguồn. Việc sinh dữ liệu vẫn do
  giáo viên bấm nút, qua `gendata.generate_tests`. Mã do AI viết không có gì bảo
  đảm, mà nó sẽ được **biên dịch rồi chạy trên máy chủ** — một bước người đọc lại
  là mức tối thiểu, không phải sự chậm chạp. Đây cũng là lý do tuyến đường không
  có tham số kiểu "sinh luôn".
- **Không giữ khoá.** Khoá API nằm trong biến môi trường của máy chủ
  (xem `deploy/README.md`), vì repo này là **công khai**. Không có khoá thì tính
  năng ẩn hẳn — không hiện một nút bấm rồi báo lỗi.
- **Chỉ dùng thư viện chuẩn.** `requirements.txt` của dự án chỉ có Flask. Thêm
  `requests` chỉ để gọi một tuyến đường là cái giá không cần thiết, nhất là trên
  máy chủ không có Internet ra ngoài theo mặc định.
- **Lỗi phải đọc được.** Mọi thất bại ở đây đều ném `AIError` với câu tiếng Việt
  nói rõ chuyện gì xảy ra và làm gì tiếp — người đọc là giáo viên, không phải
  người đọc log.
- **Thử lại, nhưng theo con số máy chủ đưa.** Khi hết hạn mức, máy chủ trả về
  đúng thời gian còn phải chờ (``reset after 1m 29s``), nên `write` chờ theo đó
  thay vì đoán. Vẫn có một ngân sách chặn trên (`MAX_TOTAL_SECONDS`) vì vượt thời
  hạn của gunicorn thì giáo viên nhận 502 trắng thay vì câu giải thích — xem
  `write`.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

# Giá trị mặc định chỉ là gợi ý; tuyến đường đọc từ cấu hình, và cấu hình đọc từ
# biến môi trường. Đổi máy chủ AI thì không phải sửa mã nguồn.
DEFAULT_BASE = "https://sarsed.eu.cc/v1"

# Mô hình mặc định. Đã đổi từ `oc/space-bunny-free` sang `jw/claude-opus-4-8`.
#
# Vì sao: đo thật hai lần trên cùng một đề, dịch và chạy cả hai chương trình rồi
# đối chiếu đáp án với một cài đặt độc lập bằng Python —
#
#   oc/space-bunny-free : lần 1 **không trả lời trong 90 giây**, lần 2 mất 34,9 s
#   jw/claude-opus-4-8  : 15,0 s và 15,3 s, đúng 10/10 bộ cả hai lần
#
# Bản cũ không hẳn sai, nhưng **không ổn định**: cùng một đề mà lúc được lúc hết
# giờ, và giáo viên không có cách nào đoán trước. Đổi mô hình thì đặt
# `SONGLO_AI_MODEL` trong `/etc/songlo.env`, không phải sửa tệp này.
#
# Đổi lại, mô hình này có **hạn mức theo từng đợt**: gọi dồn dập thì bị chặn
# khoảng hai phút rồi tự hết. Xem `_Transient` và `write` — chỗ đó đọc con số máy
# chủ đưa ra thay vì đoán.
DEFAULT_MODEL = "jw/claude-opus-4-8"

# Thời gian chờ một lần gọi. Phải **nhỏ hơn** thời hạn của gunicorn, nếu không
# gunicorn giết tiến trình trước và giáo viên nhận 502 thay vì một câu giải
# thích. Đo thật hai lần cùng một đề: 16 giây và 34 giây — chênh nhau chỉ vì mức
# tải của máy chủ AI. 90 giây là rộng rãi cho cả hai.
DEFAULT_TIMEOUT = 90

# Ngân sách cho **cả** lần nhờ viết, kể cả các lần thử lại. Phải nhỏ hơn thời hạn
# của gunicorn (`--timeout 120`, xem deploy/README.md): vượt qua thì gunicorn giết
# tiến trình và giáo viên nhận 502 trắng thay vì một câu giải thích. 100 giây chừa
# 20 giây cho phần còn lại của yêu cầu.
#
# Cố ý **không** đưa thành biến môi trường: đây là ràng buộc giữa tệp này và cấu
# hình máy chủ, đổi một bên mà quên bên kia thì hỏng theo cách rất khó lần.
MAX_TOTAL_SECONDS = 100

# Nghỉ bao lâu trước mỗi lần thử lại, khi máy chủ **không** nói còn phải chờ bao
# lâu. Một lần thôi: đo thật cho thấy thử lại mù quáng gần như không cứu được gì
# (5 lần gọi liên tiếp, có thử lại, vẫn 3/5 như khi chưa có), nên nó chỉ có ích
# cho một cái ngắt thật sự thoáng qua — mạng chập chờn, kết nối bị đóng.
RETRY_DELAYS = (1.0,)

# Chờ tại chỗ nhiều nhất bao nhiêu giây khi máy chủ **có** nói thời gian chờ.
#
# Máy chủ nói "reset after 1m 29s" — chờ đủ 90 giây thì giáo viên ngồi nhìn vòng
# xoay suốt một phút rưỡi, và ăn hết ngân sách của cả yêu cầu. Quá 25 giây thì
# thà báo thẳng "còn 1 phút 29 giây nữa" để giáo viên chủ động, còn hơn bắt chờ.
MAX_WAIT_SECONDS = 25

# Trần độ dài đề bài đưa vào. Đề cấp 2 dài nhất cũng chỉ vài nghìn ký tự; cắt ở
# đây là để một lần dán nhầm cả tệp không đốt sạch hạn mức token.
MAX_STATEMENT_CHARS = 6000

# Trần token cho câu trả lời. Đo thật: một đề cấp 2 tốn khoảng 2000 token cho cả
# hai chương trình, nhưng đề phức tạp hơn thì vượt 4000 và bị cắt giữa chừng —
# đã xảy ra thật. Endpoint nhận tới 32000, nên 8000 là mức rộng rãi mà vẫn còn
# dư địa để nhận ra một câu trả lời bất thường.
MAX_TOKENS = 8000

# Cloudflare đứng trước máy chủ AI và chặn User-Agent mặc định của thư viện chuẩn
# (`Python-urllib/3.x`) bằng 403. Đã đo thật: cùng một yêu cầu, không đặt
# User-Agent thì 403, đặt bất kỳ giá trị nào khác thì 200. Đây là loại lỗi chỉ
# hiện trên máy chủ thật, và đọc thì y như "sai khoá API".
USER_AGENT = "SongLoOJ/1.0"

MARK_GEN = "===GEN==="
MARK_SOL = "===SOL==="

SYSTEM_PROMPT = """Bạn viết hai chương trình C++ cho một hệ thống chấm bài của trường trung học cơ sở.

1. BỘ SINH DỮ LIỆU
   - Nhận chỉ số bộ ở argv[1]. Phải gọi srand(atoi(argv[1])) để cùng chỉ số thì
     sinh ra cùng dữ liệu.
   - KHÔNG đọc stdin. Nó tạo dữ liệu, không nhận dữ liệu.
   - In dữ liệu vào ra stdout, đúng định dạng mà đề bài mô tả: không thêm dòng
     tiêu đề, không thêm lời nhắc, không thêm chú thích vào dữ liệu.
   - Sinh dữ liệu đa dạng: bộ đầu nhỏ và đơn giản, các bộ sau lớn dần tới sát
     giới hạn của đề, và phải có bộ chạm biên (giá trị nhỏ nhất và lớn nhất mà
     đề cho phép). Dữ liệu phải đủ để phân biệt lời giải đúng với lời giải chạy
     chậm — nếu không thì đề không phân loại được học sinh.

2. LỜI GIẢI MẪU
   - Đọc dữ liệu vào từ stdin, in đáp án ra stdout.
   - Phải ĐÚNG với mọi dữ liệu hợp lệ theo đề bài. Đáp án của mọi bộ đều lấy từ
     chương trình này, nên một chỗ sai làm hỏng cả bộ dữ liệu, và không có gì
     phát hiện ra.

Ràng buộc chung: mỗi chương trình chạy dưới 5 giây và dưới 512 MB; mỗi tệp dữ
liệu sinh ra dưới 256 KB; chỉ dùng thư viện chuẩn C++; không đọc ghi tệp, không
dùng mạng, không gọi hệ thống.

Viết GỌN. Chú thích tối đa một dòng cho mỗi ý và không nhắc lại đề bài trong
chú thích — mã dài quá sẽ bị cắt giữa chừng và cả hai chương trình đều hỏng.

Trả lời ĐÚNG định dạng sau, không thêm chữ nào khác:

===GEN===
<mã nguồn bộ sinh>
===SOL===
<mã nguồn lời giải mẫu>"""

# Hàng rào ``` mà mô hình tự thêm, dù đã dặn đừng thêm.
_FENCE_RE = re.compile(r"```[a-zA-Z0-9+#._-]*[ \t]*\n(.*?)```", re.S)
_MARK_GEN_RE = re.compile(r"^[ \t]*===GEN===[ \t]*$", re.M)
_MARK_SOL_RE = re.compile(r"^[ \t]*===SOL===[ \t]*$", re.M)

# Máy chủ nói còn bao lâu mới dùng lại được, khi hết hạn mức:
#     "(reset after 1m 29s)"  hoặc  "(reset after 40s)"
_RESET_RE = re.compile(r"reset after\s+(?:(\d+)\s*m\s*)?(\d+)\s*s", re.I)


class AIError(Exception):
    """Lỗi khi nhờ AI viết.

    Thông báo của lớp này đi thẳng vào `flash()` và hiện cho giáo viên, nên phải
    là câu tiếng Việt đọc được — không phải thông báo của thư viện.
    """


class _Transient(AIError):
    """Lỗi có thể tự hết sau vài giây, và máy chủ thường nói rõ là bao lâu.

    Khác `AIError` ở chỗ: gặp loại này thì **thử lại có ý nghĩa**. Kèm theo đó là
    `retry_after` — số giây máy chủ nói còn phải chờ, hoặc `None` nếu nó không
    nói. Có con số đó thì không phải đoán.

    Đo thật ngày 02/10/2026, `jw/claude-opus-4-8`:

        HTTP 503  {"error":{"message":"[anthropic-compatible-.../claude-opus-4-8]
                   [403]: HTTP 403 (reset after 1m 29s)"}}

    Tức là **hạn mức theo mô hình**, reset sau khoảng 90 giây — không phải một
    cái ngắt thoáng qua. Cùng lúc đó `oc/space-bunny-free` qua 10/10 yêu cầu liên
    tiếp, nên đây không phải hạn mức của cả khoá.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def build_messages(statement: str, time_limit_ms: int = 1000,
                   memory_limit_mb: int = 256, count: int = 10) -> list[dict]:
    """Dựng hai thông điệp gửi đi.

    Giới hạn thời gian và bộ nhớ của **chính đề này** phải nằm trong câu hỏi chứ
    không nằm trong chỉ dẫn hệ thống: bộ sinh cần biết phải tạo dữ liệu lớn tới
    đâu để lời giải chạy vừa, và lời giải mẫu cần biết mình có bao nhiêu thời gian.
    """
    user = (
        "ĐỀ BÀI:\n%s\n\n"
        "Giới hạn của đề: thời gian %d ms, bộ nhớ %d MB.\n"
        "Cần %d bộ dữ liệu."
        % (statement.strip(), time_limit_ms, memory_limit_mb, count)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _code_from_section(section: str) -> str:
    """Lấy mã nguồn ra khỏi một phần của câu trả lời.

    Hai dạng đã gặp thật, và phải xử lý cả hai:

    - Mô hình bọc mã trong ``` rồi thêm lời dẫn hoặc lời kết quanh đó. Có ``` thì
      lấy đúng khối đầu tiên — đó là mã, phần còn lại là văn.
    - Mô hình in mã trần rồi thêm một câu kết ("Chúc thầy cô dạy tốt!"). Không có
      ``` để dựa vào, nên dựa vào cấu trúc: chương trình C++ viết theo lối thường
      gặp kết thúc bằng một dòng chỉ có ``}``. Cắt ở dòng cuối cùng như thế.

    Vì sao **không** đếm độ sâu ngoặc nhọn để tìm chỗ đóng cuối: một khai báo như
    ``struct Point { int x, y; };`` đóng ngoặc về 0 **trước** ``main``, nên cách đó
    cắt cụt chương trình. Dòng chỉ có ``}`` thì không nhập nhằng như vậy.

    Không có dòng nào như thế thì trả về cả phần. Cắt theo suy đoán lúc đó sẽ cắt
    vào giữa hàm — hỏng im lặng; để nguyên thì trình dịch báo lỗi và giáo viên thấy
    ngay, kèm số dòng.
    """
    fenced = _FENCE_RE.findall(section)
    if fenced:
        return fenced[0].strip()

    lines = section.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "}":
            return "\n".join(lines[:i + 1]).rstrip()
    return section.strip()


def extract_blocks(text: str) -> tuple[str, str]:
    """Tách câu trả lời thành ``(bộ sinh, lời giải mẫu)``.

    Ưu tiên hai mốc ``===GEN===`` / ``===SOL===`` vì chúng không nhập nhằng. Nếu
    mô hình không theo mốc, còn một đường dùng được: nó trả về đúng hai khối mã,
    và thứ tự gần như luôn là bộ sinh rồi lời giải. Nhận, vì bắt làm lại nghĩa là
    giáo viên chờ thêm hai chục giây nữa.

    Không đoán khi số khối không phải hai: thà báo lỗi kèm đầu câu trả lời để
    giáo viên tự sao chép, còn hơn gán nhầm khối lời giải vào ô bộ sinh.
    """
    if not text or not text.strip():
        raise AIError("Máy chủ AI trả về nội dung rỗng. Thử lại.")

    m_gen = _MARK_GEN_RE.search(text)
    m_sol = _MARK_SOL_RE.search(text)
    if m_gen and m_sol and m_gen.end() < m_sol.start():
        gen = _code_from_section(text[m_gen.end():m_sol.start()])
        sol = _code_from_section(text[m_sol.end():])
        if gen and sol:
            return gen, sol

    blocks = [_code_from_section(b) for b in _FENCE_RE.findall(text)]
    blocks = [b for b in blocks if b.strip()]
    if len(blocks) == 2:
        return blocks[0], blocks[1]

    raise AIError(
        "Không tách được hai chương trình từ câu trả lời của AI (nó trả về %d "
        "khối mã). Đầu câu trả lời:\n\n%s" % (len(blocks), text.strip()[:400]))


def _braces_balanced(code: str) -> bool:
    """Số ngoặc nhọn mở và đóng có bằng nhau không.

    Dùng để nhận ra một chương trình **bị cắt giữa chừng**. Chỉ có ý nghĩa như
    một tín hiệu phụ, khi đã biết câu trả lời bị cắt vì hết token.

    Vì sao không dùng "có dòng chỉ có ``}`` hay không": một chương trình viết gọn
    trên một dòng (``int main(){return 0;}``) hoàn toàn đúng mà không có dòng nào
    như thế, nên cách đó báo sai. Đếm ngoặc thì đúng cho cả hai dạng.

    Không bỏ qua ngoặc nằm trong chuỗi ký tự hay trong chú thích. Với chương
    trình của một đề cấp 2, ngoặc trong chuỗi là chuyện hiếm, và nếu có sai thì
    cái giá chỉ là một thông báo "bị cắt" hơi nhầm — đổi lại là giáo viên bấm
    lại, chứ không phải một lỗi dịch khó hiểu.
    """
    return code.count("{") == code.count("}")


def _parse_body(raw: str) -> dict:
    """Đọc thân phản hồi, chấp nhận **cả hai** dạng mà endpoint trả về.

    Cùng một địa chỉ, cùng một yêu cầu, nhưng có mô hình trả về một đối tượng
    JSON, có mô hình trả về **SSE** — từng dòng ``data: {...}``, mỗi dòng một
    mẩu ``delta.content``. Đã gặp thật: ``jw/claude-opus-4-8`` trả SSE trong khi
    ``oc/space-bunny-free`` trả JSON.

    Chỉ đọc một dạng thì mô hình kia hỏng với thông báo "trả về dữ liệu không
    phải JSON" — trong khi dữ liệu vẫn nguyên vẹn trong thân phản hồi, chỉ là
    đóng gói khác. Hàm này gom SSE về **đúng dạng** mà phần còn lại của tệp đang
    dùng, nên không phải sửa gì ở dưới.
    """
    text = raw.strip()
    if not text.startswith("data:"):
        return json.loads(text)

    pieces, finish = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except ValueError:
            continue
        for choice in obj.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                pieces.append(delta["content"])
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]

    return {"choices": [{"finish_reason": finish,
                         "message": {"role": "assistant", "content": "".join(pieces)}}]}


def _http_message(code: int, detail: str) -> str:
    """Dịch mã HTTP thành câu nói được với giáo viên."""
    if code == 401:
        head = "Khoá API không đúng hoặc đã hết hạn (401)."
    elif code == 403:
        head = ("Máy chủ AI từ chối yêu cầu (403). Thường là do khoá bị chặn, "
                "hoặc máy chủ AI đang chặn địa chỉ của máy chủ này.")
    elif code == 429:
        head = "Máy chủ AI báo hết lượt gọi (429). Chờ một lát rồi thử lại."
    elif code >= 500:
        head = "Máy chủ AI đang lỗi (%d). Thử lại sau." % code
    else:
        head = "Máy chủ AI trả về mã %d." % code
    return head + ("\n\n" + detail if detail else "")


def _reset_after_seconds(*texts) -> float | None:
    """Máy chủ nói còn bao lâu nữa mới dùng lại được, nếu nó có nói.

    Phản hồi thật khi bị chặn (xem `_Transient`):
    ``... [403]: HTTP 403 (reset after 1m 29s)``. Con số đó là thời gian chờ
    **chính xác** — tốt hơn hẳn mọi giá trị đoán. Không có thì trả ``None``, và
    lúc đó mới dùng tới `RETRY_DELAYS`.

    Đọc cả tiêu đề `Retry-After` (chuẩn HTTP, đơn vị giây) ở chỗ gọi.
    """
    for t in texts:
        if not t:
            continue
        m = _RESET_RE.search(t)
        if m:
            return int(m.group(1) or 0) * 60 + int(m.group(2))
    return None


def _human_seconds(seconds: float) -> str:
    """``89`` -> ``"1 phút 29 giây"``. Để câu báo lỗi đọc lên là hiểu ngay."""
    total = int(round(seconds))
    if total < 60:
        return "%d giây" % total
    phut, giay = divmod(total, 60)
    return "%d phút" % phut if not giay else "%d phút %d giây" % (phut, giay)


def _retry_after(exc, detail: str) -> float | None:
    """Số giây phải chờ, lấy từ thân phản hồi hoặc từ tiêu đề ``Retry-After``.

    Thân phản hồi được ưu tiên vì đó là con số của **đúng mô hình này**. Tiêu đề
    `Retry-After` là chuẩn HTTP nên đọc thêm, phòng khi máy chủ chỉ gửi nó.
    """
    from_body = _reset_after_seconds(detail)
    if from_body is not None:
        return from_body
    try:
        value = (exc.headers or {}).get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _call_once(statement: str, *, base: str, key: str, model: str,
               time_limit_ms: int = 1000, memory_limit_mb: int = 256,
               count: int = 10, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Một lần gọi. Không thử lại — việc đó ở `write`."""
    if not key:
        raise AIError("Chưa cấu hình khoá API cho tính năng nhờ AI viết.")
    if not statement.strip():
        raise AIError("Chưa có đề bài để nhờ AI đọc.")

    url = base.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": build_messages(statement, time_limit_ms, memory_limit_mb, count),
        "max_tokens": MAX_TOKENS,
        # Thấp, vì cần mã chạy đúng chứ không cần văn hay. Sinh lại cùng một đề
        # cũng nên ra gần như cùng một bộ dữ liệu.
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        message = _http_message(exc.code, detail)
        # 429 và 5xx là "lúc này chưa được", không phải "yêu cầu sai" — thử lại có
        # ý nghĩa. Đã gặp thật: mô hình mặc định trả 503 trong đó bao một 403 của
        # nhà cung cấp, kèm luôn thời gian chờ.
        #
        # 401 và 403 để nguyên là `AIError`: khoá sai thì thử lại chỉ tốn thời
        # gian, còn thử lại vài lần rồi mới báo thì giáo viên chờ vô ích thêm một
        # phút. Riêng 403 có thể là Cloudflare chặn — câu chữ ở `_http_message`
        # đã nói cả hai khả năng.
        if exc.code == 429 or exc.code >= 500:
            raise _Transient(message, retry_after=_retry_after(exc, detail)) from exc
        raise AIError(message) from exc
    except urllib.error.URLError as exc:
        # Mạng chập chờn, hoặc máy chủ AI đóng kết nối giữa chừng. Cả hai đều có
        # thể qua ở lần sau.
        raise _Transient(
            "Không gọi được máy chủ AI trong %d giây (%s). Thử lại, hoặc dán mã "
            "nguồn bằng tay vào ô bên dưới." % (timeout, exc.reason)) from exc
    except TimeoutError as exc:
        raise _Transient(
            "Máy chủ AI không trả lời trong %d giây. Thử lại sau." % timeout) from exc

    try:
        data = _parse_body(raw)
    except ValueError as exc:
        raise AIError("Máy chủ AI trả về dữ liệu không phải JSON:\n\n" + raw[:300]) from exc

    choices = data.get("choices") or []
    if not choices:
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else None
        raise AIError("Máy chủ AI không trả về kết quả nào." + (" " + msg if msg else ""))

    choice = choices[0]
    content = (choice.get("message") or {}).get("content") or ""
    truncated = choice.get("finish_reason") == "length"

    def _too_long():
        return AIError(
            "AI viết dài quá trần %d token nên bị cắt giữa chừng, và phần nhận "
            "được không đủ hai chương trình. Thử lại — mỗi lần nó viết một khác. "
            "Nếu vẫn vậy, đề này có thể quá lớn cho một lần: hãy tách thành hai "
            "đề nhỏ hơn, hoặc tự viết lời giải mẫu (thường ngắn hơn bộ sinh) rồi "
            "chỉ nhờ AI viết bộ sinh." % MAX_TOKENS)

    # Bị cắt vì hết token **chưa chắc** đã hỏng: mô hình có thể đã viết xong cả
    # hai chương trình rồi mới lan man thêm cho tới lúc hết chỗ. Bản trước báo
    # lỗi ngay khi thấy `length`, nên nó từ chối cả những câu trả lời dùng được.
    if not truncated:
        return extract_blocks(content)

    try:
        gen, sol = extract_blocks(content)
    except AIError:
        raise _too_long() from None

    # Tách được nhưng khối thứ hai có thể đã cụt giữa hàm. Nhận nó thì giáo viên
    # bấm "Sinh bộ dữ liệu" và nhận một lỗi dịch ở dòng cuối — đọc không ra là do
    # bị cắt. Nói thẳng ngay ở đây thì hơn.
    if not (_braces_balanced(gen) and _braces_balanced(sol)):
        raise _too_long()

    return gen, sol


def _delay_before_retry(exc, index: int, deadline: float) -> float | None:
    """Chờ bao lâu trước lần thử sau. ``None`` nghĩa là **đừng thử nữa**.

    Ưu tiên con số máy chủ đưa, vì nó chính xác: đo thật, khi hết hạn mức thì
    máy chủ trả ``(reset after 1m 29s)`` và chặn đủ 89 giây. Thử lại mù quáng sau
    1 giây chỉ tốn thêm một lượt gọi mà chắc chắn vẫn bị chặn — đã đo, 5 lần gọi
    liên tiếp có thử lại vẫn 3/5 như khi chưa có.

    Chặn lâu hơn `MAX_WAIT_SECONDS` thì không chờ: bắt giáo viên nhìn vòng xoay
    suốt một phút rưỡi, mà ngân sách của cả yêu cầu cũng hết. Báo thẳng số giây
    còn lại thì hơn.
    """
    if index >= len(RETRY_DELAYS):
        return None

    if exc.retry_after is not None:
        if exc.retry_after > MAX_WAIT_SECONDS:
            return None
        delay = exc.retry_after + 1.0            # +1 giây cho đồng hồ lệch
    else:
        delay = RETRY_DELAYS[index]

    # Phải chừa chỗ cho **chính lần gọi sau**, không chỉ cho thời gian nghỉ.
    if time.monotonic() + delay + 5 > deadline:
        return None
    return delay


def write(statement: str, *, base: str, key: str, model: str,
          time_limit_ms: int = 1000, memory_limit_mb: int = 256,
          count: int = 10, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Nhờ AI viết, tự thử lại khi thất bại chỉ là tạm thời.

    Vì sao cần: mô hình mặc định nhanh gấp ba lần mô hình cũ nhưng **hết hạn mức
    theo từng đợt**. Đo thật ngày 02/10/2026, gọi 5 lần liên tiếp cùng một đề: 3
    lần qua (12,0–13,6 giây), 2 lần nhận 503 — bên trong là 403 của nhà cung cấp
    kèm dòng ``(reset after 1m 29s)``. Cùng lúc đó ``oc/space-bunny-free`` qua
    10/10 yêu cầu liên tiếp, nên đây là hạn mức **của riêng mô hình này**, và
    cách dùng nhiều lần liên tiếp là thứ làm nó cạn.

    Ngân sách thời gian: tổng mọi lần thử không vượt `MAX_TOTAL_SECONDS`, và thời
    gian chờ của **từng lần** bị cắt theo phần ngân sách còn lại. Thiếu phần này
    thì hai lần × 90 giây = 180 giây, vượt thời hạn gunicorn — giáo viên nhận 502
    trắng và không có gì giải thích.

    Chỉ thử lại `_Transient` (429, 5xx, lỗi mạng, quá hạn). Lỗi khác — khoá sai,
    câu trả lời không tách được, bị cắt vì hết token — ném thẳng: thử lại chỉ làm
    giáo viên chờ thêm mà kết quả không đổi.
    """
    deadline = time.monotonic() + MAX_TOTAL_SECONDS
    attempts = len(RETRY_DELAYS) + 1
    tried, last, started = 0, None, time.monotonic()

    for i in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        tried += 1
        try:
            return _call_once(
                statement, base=base, key=key, model=model,
                time_limit_ms=time_limit_ms, memory_limit_mb=memory_limit_mb,
                count=count,
                # Cắt theo ngân sách còn lại, không phải lúc nào cũng `timeout`.
                timeout=max(1, int(min(timeout, remaining))),
            )
        except _Transient as exc:
            last = exc
            delay = _delay_before_retry(exc, i, deadline)
            if delay is None:
                break
            time.sleep(delay)

    waited = time.monotonic() - started

    # Hết hạn mức là chuyện khác hẳn với "mạng chập chờn": biết chính xác còn bao
    # lâu thì nói ra, đừng để giáo viên tự đoán "một lát" là bao lâu.
    if last is not None and last.retry_after is not None:
        raise AIError(
            "Mô hình này đã hết hạn mức gọi (đã thử %d lần trong %d giây). Máy "
            "chủ nói còn khoảng %s nữa mới dùng lại được. Đây là hạn mức tạm "
            "thời, không phải lỗi cấu hình — chờ hết khoảng đó rồi bấm lại, hoặc "
            "làm việc khác trong lúc chờ.\n\nChi tiết lần cuối:\n\n%s"
            % (tried, round(waited), _human_seconds(last.retry_after), last))

    if tried:
        head = "đã thử %d lần trong %d giây mà chưa qua" % (tried, round(waited))
    else:
        head = "không còn đủ thời gian để thử (ngân sách %d giây)" % MAX_TOTAL_SECONDS
    raise AIError(
        "Máy chủ AI tạm thời không nhận yêu cầu: %s. Đây thường là quá tải, không "
        "phải lỗi cấu hình — chờ một lát rồi bấm lại.\n\nChi tiết lần cuối:\n\n%s"
        % (head, last or ""))
