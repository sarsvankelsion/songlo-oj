"""Tạo dữ liệu mẫu cho hệ thống: tài khoản, đề bài, bộ dữ liệu, kỳ thi.

Chạy:

    python -m server.seed                  # tạo dữ liệu, giữ nguyên nếu đã có
    python -m server.seed --reset          # xoá CSDL rồi tạo lại từ đầu
    python -m server.seed --no-submissions # chỉ tạo tài khoản/đề/kỳ thi

--------------------------------------------------------------------------
VÌ SAO BÀI NỘP MẪU LÀ MÃ C++ THẬT
--------------------------------------------------------------------------
Script này **không** ghi điểm sẵn vào CSDL. Nó chèn các bài nộp ở trạng thái
``pending`` kèm mã nguồn C++ thật, rồi để ``server/worker.py`` chấm chúng.

Làm vậy tốn thêm một bước, nhưng đổi lại toàn bộ con số trên giao diện — điểm,
bảng xếp hạng, tỉ lệ đúng, thời gian chạy, bộ nhớ — đều do chính bộ chấm sinh
ra. Nếu ghi điểm thẳng vào CSDL thì mọi trang vẫn đẹp, nhưng ta không kiểm
chứng được gì cả: một lỗi ở tầng chấm sẽ nằm im cho tới khi học sinh thật nộp
bài. Bộ bài nộp mẫu ở đây vì vậy cũng chính là bộ kiểm thử: nó phủ đủ sáu loại
kết quả, và hai cơ chế chặn quá thời gian khác nhau (xem ``DEMO_SUBMISSIONS``).

--------------------------------------------------------------------------
TÀI KHOẢN
--------------------------------------------------------------------------
Mật khẩu dưới đây chỉ để chạy thử. **Phải đổi trước khi đưa lên máy chủ trường.**
Học sinh được đặt ``must_change_password = 1`` để hệ thống nhắc đổi ở lần đăng
nhập đầu tiên.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Cho phép chạy cả `python -m server.seed` lẫn `python server/seed.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import db  # noqa: E402
from server.auth import hash_password  # noqa: E402

TEACHER_PASSWORD = "Songlo@GV2026"
STUDENT_PASSWORD = "Songlo@2026"

# ------------------------------------------------------------------ tài khoản
TEACHERS = [
    # (username, họ tên, vai trò)
    ("cophang", "Phạm Thu Hằng", "admin"),
    ("thaydung", "Nguyễn Tiến Dũng", "teacher"),
]

STUDENTS = [
    ("9A", "Nguyễn Văn An"), ("9A", "Trần Thị Bình"), ("9A", "Vũ Thị Lan"),
    ("9A", "Nguyễn Đức Huy"), ("9A", "Phan Thị Mai"), ("9A", "Bùi Quang Minh"),
    ("9A", "Đặng Thu Trang"), ("9A", "Lý Hoàng Nam"),
    ("9B", "Ngô Thị Hồng"), ("9B", "Trịnh Văn Khánh"), ("9B", "Hoàng Minh Tuấn"),
    ("9B", "Lê Thị Ngọc"), ("9B", "Đỗ Văn Phúc"), ("9B", "Nguyễn Thị Quỳnh"),
    ("8A", "Phạm Văn Sơn"), ("8A", "Trần Thị Tâm"), ("8A", "Vũ Đức Thắng"),
    ("8A", "Nguyễn Thị Uyên"), ("8A", "Bùi Văn Vinh"),
    ("8B", "Lê Thị Xuân"), ("8B", "Hoàng Văn Yên"), ("8B", "Đặng Thị Ánh"),
    ("8B", "Ngô Văn Bảo"),
    ("7A", "Trần Thị Cẩm"), ("7A", "Lý Văn Đạt"), ("7A", "Phan Thị Hà"),
]


def student_username(class_name: str, index: int) -> str:
    """Tên đăng nhập theo lớp: 9A01, 9A02, … 8B04.

    Chọn kiểu này thay vì tên viết không dấu vì hai lý do: học sinh lớp 6–7 gõ
    đúng một chuỗi ngắn dễ hơn nhiều so với tên có dấu gạch, và giáo viên đọc
    được thành tiếng trong giờ thực hành. ``NguyenVanAn9A`` vừa dài vừa dễ gõ
    sai, còn ``9A01`` thì không.
    """
    return f"{class_name}{index:02d}"


# --------------------------------------------------------------------- đề bài
# Mỗi đề: mã, tên, độ khó, chủ đề, giới hạn thời gian (ms), giới hạn bộ nhớ
# (MB), đề bài, và danh sách bộ dữ liệu (vào, ra, ẩn?, ghi chú).
#
# Mỗi đề có đúng 2 bộ công khai và 2 bộ ẩn. Con số 2 là có chủ ý: bộ công khai
# để học sinh hiểu định dạng vào–ra, còn nếu công khai cả bốn thì chỉ cần in ra
# đáp án của ví dụ là qua bài.
PROBLEMS = [
    {
        "code": "SL001",
        "name": "Tổng hai số nguyên",
        "difficulty": "co-ban",
        "topic": "Số học",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Cho hai số nguyên a và b. Hãy tính tổng của chúng.

DỮ LIỆU VÀO
Một dòng duy nhất chứa hai số nguyên a và b, cách nhau ít nhất một dấu cách.

DỮ LIỆU RA
Một số nguyên duy nhất là tổng a + b.

GIỚI HẠN
-10^9 ≤ a, b ≤ 10^9.

VÍ DỤ
Dữ liệu vào:  3 5
Dữ liệu ra:   8

LƯU Ý
Tổng của hai số có thể vượt quá phạm vi của kiểu int (khoảng 2,1 tỷ).
Hãy dùng kiểu long long.""",
        "tests": [
            ("3 5", "8", 0, "Ví dụ trong đề"),
            ("-7 12", "5", 0, "Có số âm"),
            ("1000000000 1000000000", "2000000000", 1, "Vượt phạm vi int"),
            ("0 0", "0", 1, "Trường hợp biên"),
        ],
    },
    {
        "code": "SL002",
        "name": "Đếm số nguyên tố trong đoạn",
        "difficulty": "trung-binh",
        "topic": "Số học",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Cho hai số nguyên dương a và b (a ≤ b). Hãy đếm xem trong đoạn [a, b] có bao
nhiêu số nguyên tố.

Số nguyên tố là số tự nhiên lớn hơn 1 chỉ chia hết cho 1 và chính nó.

DỮ LIỆU VÀO
Một dòng duy nhất chứa hai số nguyên a và b.

DỮ LIỆU RA
Một số nguyên duy nhất là số lượng số nguyên tố trong đoạn [a, b].

GIỚI HẠN
1 ≤ a ≤ b ≤ 100 000.

VÍ DỤ
Dữ liệu vào:  1 10
Dữ liệu ra:   4

GIẢI THÍCH
Các số nguyên tố trong đoạn [1, 10] là 2, 3, 5, 7.

LƯU Ý
Cách kiểm tra từng số một bằng vòng lặp tới căn bậc hai vẫn đủ nhanh với giới
hạn này. Sàng Eratosthenes sẽ nhanh hơn, nhưng không bắt buộc.""",
        "tests": [
            ("1 10", "4", 0, "Ví dụ trong đề"),
            ("14 16", "0", 0, "Đoạn không có số nguyên tố"),
            ("90 100", "1", 1, "Chỉ có 97"),
            ("2 2", "1", 1, "Đoạn chỉ có một số, chính là số nguyên tố nhỏ nhất"),
        ],
    },
    {
        "code": "SL003",
        "name": "Tổng các chữ số",
        "difficulty": "co-ban",
        "topic": "Số học",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Cho một số nguyên không âm n. Hãy tính tổng các chữ số của n.

DỮ LIỆU VÀO
Một dòng duy nhất chứa số nguyên n.

DỮ LIỆU RA
Một số nguyên duy nhất là tổng các chữ số của n.

GIỚI HẠN
0 ≤ n ≤ 10^18.

VÍ DỤ
Dữ liệu vào:  12345
Dữ liệu ra:   15

GIẢI THÍCH
1 + 2 + 3 + 4 + 5 = 15.

LƯU Ý
n có thể có tới 19 chữ số, vượt xa phạm vi của int. Có thể đọc n như một chuỗi
rồi cộng từng ký tự, cách này tránh hoàn toàn vấn đề tràn số.""",
        "tests": [
            ("12345", "15", 0, "Ví dụ trong đề"),
            ("0", "0", 0, "Trường hợp biên"),
            ("999999999999999999", "162", 1, "Số lớn nhất có 18 chữ số 9"),
            ("1000000000000000000", "1", 1, "10^18"),
        ],
    },
    {
        "code": "SL004",
        "name": "Số đối xứng",
        "difficulty": "co-ban",
        "topic": "Xâu ký tự",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Một số được gọi là đối xứng nếu đọc từ trái sang phải cũng giống như đọc từ
phải sang trái. Cho số nguyên dương n, hãy kiểm tra xem n có đối xứng không.

DỮ LIỆU VÀO
Một dòng duy nhất chứa số nguyên dương n.

DỮ LIỆU RA
In ra YES nếu n đối xứng, ngược lại in ra NO.

GIỚI HẠN
1 ≤ n ≤ 10^9.

VÍ DỤ
Dữ liệu vào:  12321
Dữ liệu ra:   YES

Dữ liệu vào:  1000
Dữ liệu ra:   NO

LƯU Ý
Đọc n vào một biến kiểu string rồi so sánh với xâu đảo ngược là cách ngắn nhất.
Nếu tách chữ số bằng phép chia lấy dư thì số 0 ở cuối (như 1000) sẽ bị mất.""",
        "tests": [
            ("12321", "YES", 0, "Ví dụ trong đề"),
            ("1000", "NO", 0, "Số 0 ở cuối, bẫy khi tách bằng phép chia"),
            ("7", "YES", 1, "Số có một chữ số"),
            ("1000000001", "YES", 1, "Đối xứng nhưng có nhiều số 0 ở giữa"),
        ],
    },
    {
        "code": "SL005",
        "name": "Đếm ký tự trong xâu",
        "difficulty": "co-ban",
        "topic": "Xâu ký tự",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Cho một xâu s chỉ gồm các chữ cái thường trong bảng chữ cái tiếng Anh, không
chứa dấu cách. Hãy đếm xem trong s có bao nhiêu ký tự 'a'.

DỮ LIỆU VÀO
Một dòng duy nhất chứa xâu s.

DỮ LIỆU RA
Một số nguyên duy nhất là số lần xuất hiện của ký tự 'a'.

GIỚI HẠN
Độ dài của s không vượt quá 1000 ký tự.

VÍ DỤ
Dữ liệu vào:  banana
Dữ liệu ra:   3

GIẢI THÍCH
Xâu banana có ký tự 'a' ở các vị trí 2, 4 và 6 (đếm từ 1).

LƯU Ý
Chú ý phân biệt ký tự 'a' với chữ 'A'. Đề bài chỉ hỏi về chữ 'a' thường.""",
        "tests": [
            ("banana", "3", 0, "Ví dụ trong đề"),
            ("xyz", "0", 0, "Không có ký tự nào"),
            ("aaaa", "4", 1, "Toàn ký tự cần đếm"),
            ("abracadabra", "5", 1, "Xâu dài hơn"),
        ],
    },
    {
        "code": "SL006",
        "name": "Tổng đoạn con lớn nhất",
        "difficulty": "nang-cao",
        "topic": "Quy hoạch động",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement": """YÊU CẦU
Cho một dãy gồm n số nguyên. Hãy tìm tổng lớn nhất của một đoạn con liên tiếp
khác rỗng trong dãy.

DỮ LIỆU VÀO
Dòng thứ nhất chứa số nguyên n.
Dòng thứ hai chứa n số nguyên, cách nhau ít nhất một dấu cách.

DỮ LIỆU RA
Một số nguyên duy nhất là tổng lớn nhất tìm được.

GIỚI HẠN
1 ≤ n ≤ 100 000.
Mỗi số trong dãy có giá trị tuyệt đối không vượt quá 10^9.

VÍ DỤ
Dữ liệu vào:
5
1 -2 3 4 -1

Dữ liệu ra:  7

GIẢI THÍCH
Đoạn con 3 4 có tổng bằng 7, là tổng lớn nhất.

LƯU Ý
Đoạn con bắt buộc phải khác rỗng, nên khi cả dãy đều âm thì đáp án là số âm
lớn nhất, chứ không phải 0. Đây là chỗ dễ sai nhất của bài này.

Với n tới 100 000, cách duyệt mọi đoạn con là quá chậm. Cần thuật toán một
vòng lặp (quy hoạch động Kadane).""",
        "tests": [
            ("5\n1 -2 3 4 -1", "7", 0, "Ví dụ trong đề"),
            ("3\n-1 -2 -3", "-1", 0, "Cả dãy đều âm, đáp án phải là số âm"),
            ("4\n2 -1 2 2", "5", 1, "Đoạn con dài, có phần tử âm ở giữa"),
            ("1\n-1000000000", "-1000000000", 1, "Dãy một phần tử"),
        ],
    },
]


# --------------------------------------------------------------------- kỳ thi
# `starts_at`/`ends_at` tính theo số ngày lệch so với lúc chạy script, để kỳ thi
# luôn nằm đúng trạng thái mong muốn bất kể chạy vào ngày nào.
CONTESTS = [
    {
        "name": "Kiểm tra giữa học kỳ I — Tin học 9",
        "description": "Bài kiểm tra trên máy, thời gian 45 phút. Được xem tài liệu, không trao đổi.",
        "start_offset_days": -7,
        "end_offset_days": 3,
        "status": "open",
        "problems": ["SL001", "SL002", "SL003"],
    },
    {
        "name": "Ôn tập đội tuyển — Vòng loại",
        "description": "Buổi ôn tập dành cho học sinh đăng ký đội tuyển Tin học. Làm bài tự do, không tính điểm kiểm tra.",
        "start_offset_days": 10,
        "end_offset_days": 17,
        "status": "upcoming",
        "problems": ["SL004", "SL005", "SL006"],
    },
]


# ---------------------------------------------------------------- bài nộp mẫu
# Mỗi bài nộp: tên đăng nhập, mã đề, mã nguồn, số giờ trước đây.
#
# Bộ này phủ đủ sáu loại kết quả và phủ **hai cơ chế chặn quá thời gian khác
# nhau** — đây là điểm quan trọng nhất:
#
#   * Bài "ngủ" tiêu tốn gần như không CPU. Trên máy chủ, RLIMIT_CPU sẽ không
#     bao giờ kích hoạt, nên chỉ có đồng hồ canh giờ thực mới cắt được nó. Nếu
#     ai đó xoá đồng hồ canh giờ vì tưởng giới hạn CPU đã đủ, bài này sẽ treo
#     hàng đợi chấm — và không có bài nào khác trong bộ này phát hiện ra.
#   * Bài đốt CPU kích hoạt RLIMIT_CPU. Nếu ai đó xoá giới hạn CPU, bài này
#     vẫn bị đồng hồ canh giờ cắt nên trông vẫn "đúng", nhưng thời gian chạy
#     sẽ sai lệch. Có cả hai bài thì mới kiểm chứng được cả hai đường.
DEMO_SUBMISSIONS = [
    # --- SL001 -------------------------------------------------------------
    ("9A01", "SL001", """#include <iostream>
using namespace std;
int main() {
    long long a, b;
    if (!(cin >> a >> b)) return 0;
    cout << a + b << "\\n";
    return 0;
}
""", 30),

    # In a - b. Đúng ở bộ 4 (0 0) nên vẫn được 25 điểm — cố ý, để thấy rằng
    # điểm từng phần hoạt động và "WA" không có nghĩa là 0 điểm.
    ("9A02", "SL001", """#include <iostream>
using namespace std;
int main() {
    long long a, b;
    cin >> a >> b;
    cout << a - b << "\\n";
    return 0;
}
""", 28),

    # Cấp phát tới khi hết bộ nhớ. Ghi đầy từng khối để trang thật sự được cấp,
    # nếu không thì chỉ địa chỉ ảo tăng còn bộ nhớ thật không đổi và bài sẽ bị
    # xếp nhầm thành lỗi khi chạy.
    ("9A05", "SL001", """#include <iostream>
#include <vector>
#include <cstring>
using namespace std;
int main() {
    vector<char*> keep;
    while (true) {
        char* p = new char[1024 * 1024];
        memset(p, 1, 1024 * 1024);
        keep.push_back(p);
    }
    return 0;
}
""", 26),

    # --- SL002 -------------------------------------------------------------
    ("9A03", "SL002", """#include <iostream>
using namespace std;
int main() {
    int a, b;
    cin >> a >> b;
    cout << a + b
    return 0;
}
""", 24),

    ("9B01", "SL002", """#include <iostream>
#include <vector>
using namespace std;
int main() {
    int a, b;
    if (!(cin >> a >> b)) return 0;
    vector<bool> hop(b + 1, false);
    int dem = 0;
    for (int i = 2; i <= b; i++) {
        if (!hop[i]) {
            if (i >= a) dem++;
            for (long long j = 1LL * i * i; j <= b; j += i) hop[j] = true;
        }
    }
    cout << dem << "\\n";
    return 0;
}
""", 22),

    # Đốt CPU: vòng lặp có volatile nên trình dịch không được thay bằng công
    # thức đóng. Đây là bài kiểm chứng RLIMIT_CPU.
    ("8A03", "SL002", """#include <iostream>
using namespace std;
int main() {
    int a, b;
    cin >> a >> b;
    volatile long long s = 0;
    for (long long i = 0; i < 4000000000LL; i++) s += i;
    cout << s << "\\n";
    return 0;
}
""", 20),

    # --- SL003 -------------------------------------------------------------
    ("9A06", "SL003", """#include <iostream>
using namespace std;
int main() {
    long long n;
    cin >> n;
    long long khong = 0;
    cout << n / khong << "\\n";
    return 0;
}
""", 18),

    ("9B02", "SL003", """#include <iostream>
#include <string>
using namespace std;
int main() {
    string s;
    if (!(cin >> s)) return 0;
    long long tong = 0;
    for (char c : s) tong += c - '0';
    cout << tong << "\\n";
    return 0;
}
""", 16),

    # --- SL004 -------------------------------------------------------------
    ("9B03", "SL004", """#include <iostream>
#include <string>
#include <algorithm>
using namespace std;
int main() {
    string s;
    if (!(cin >> s)) return 0;
    string r = s;
    reverse(r.begin(), r.end());
    cout << (s == r ? "YES" : "NO") << "\\n";
    return 0;
}
""", 14),

    # --- SL005 -------------------------------------------------------------
    ("9B04", "SL005", """#include <iostream>
#include <string>
using namespace std;
int main() {
    string s;
    if (!(cin >> s)) return 0;
    int dem = 0;
    for (char c : s) if (c == 'a') dem++;
    cout << dem << "\\n";
    return 0;
}
""", 12),

    # Đếm nhầm ký tự 'b'. Vẫn đúng ở bộ 2 (xyz) nên được 25 điểm.
    ("8B01", "SL005", """#include <iostream>
#include <string>
using namespace std;
int main() {
    string s;
    if (!(cin >> s)) return 0;
    int dem = 0;
    for (char c : s) if (c == 'b') dem++;
    cout << dem << "\\n";
    return 0;
}
""", 10),

    # --- SL006 -------------------------------------------------------------
    ("8A01", "SL006", """#include <iostream>
#include <algorithm>
#include <climits>
using namespace std;
int main() {
    int n;
    if (!(cin >> n)) return 0;
    long long best = LLONG_MIN, cur = 0;
    for (int i = 0; i < n; i++) {
        long long x;
        cin >> x;
        cur = max(x, cur + x);
        best = max(best, cur);
    }
    cout << best << "\\n";
    return 0;
}
""", 8),

    # Ngủ 60 giây. Tiêu tốn gần như không CPU, nên trên máy chủ chỉ có đồng hồ
    # canh giờ thực cắt được. Đây là bài kiểm chứng đường đó.
    ("8A02", "SL006", """#include <iostream>
#include <thread>
#include <chrono>
using namespace std;
int main() {
    int n;
    cin >> n;
    this_thread::sleep_for(chrono::seconds(60));
    cout << 0 << "\\n";
    return 0;
}
""", 6),
]


# ==========================================================================
# Các bước tạo dữ liệu
# ==========================================================================
def reset_database(path: Path) -> None:
    """Xoá CSDL và các tệp phụ của chế độ WAL.

    Phải xoá cả ``-wal`` và ``-shm``: để lại chúng mà xoá tệp chính sẽ khiến
    SQLite dựng lại CSDL từ nhật ký WAL cũ, và ta tưởng mình đã xoá sạch trong
    khi dữ liệu cũ vẫn quay về.
    """
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
            print(f"  đã xoá {p}")


def seed_users(conn) -> dict[str, int]:
    """Tạo tài khoản. Trả về bảng ánh xạ tên đăng nhập -> id."""
    now = db.utc_now()
    ids: dict[str, int] = {}

    for username, full_name, role in TEACHERS:
        row = db.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,))
        if row:
            ids[username] = row["id"]
            continue
        with conn:
            cur = conn.execute(
                """INSERT INTO users (username, full_name, class_name, role,
                                      password_hash, is_active, must_change_password, created_at)
                   VALUES (?, ?, '', ?, ?, 1, 0, ?)""",
                (username, full_name, role, hash_password(TEACHER_PASSWORD), now),
            )
        ids[username] = cur.lastrowid

    counters: dict[str, int] = {}
    for class_name, full_name in STUDENTS:
        counters[class_name] = counters.get(class_name, 0) + 1
        username = student_username(class_name, counters[class_name])

        row = db.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,))
        if row:
            ids[username] = row["id"]
            continue
        with conn:
            cur = conn.execute(
                """INSERT INTO users (username, full_name, class_name, role,
                                      password_hash, is_active, must_change_password, created_at)
                   VALUES (?, ?, ?, 'student', ?, 1, 1, ?)""",
                (username, full_name, class_name,
                 hash_password(STUDENT_PASSWORD), now),
            )
        ids[username] = cur.lastrowid

    print(f"  {len(TEACHERS)} giáo viên, {len(STUDENTS)} học sinh")
    return ids


def seed_problems(conn, author_id: int) -> dict[str, int]:
    now = db.utc_now()
    ids: dict[str, int] = {}

    for spec in PROBLEMS:
        row = db.query_one(conn, "SELECT id FROM problems WHERE code = ?", (spec["code"],))
        if row:
            ids[spec["code"]] = row["id"]
            continue

        with conn:
            cur = conn.execute(
                """INSERT INTO problems
                     (code, name, difficulty, topic, statement, time_limit_ms,
                      memory_limit_mb, points_mode, status, author_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'even', 'live', ?, ?, ?)""",
                (spec["code"], spec["name"], spec["difficulty"], spec["topic"],
                 spec["statement"], spec["time_limit_ms"], spec["memory_limit_mb"],
                 author_id, now, now),
            )
            problem_id = cur.lastrowid

            for ordinal, (data_in, data_out, hidden, note) in enumerate(spec["tests"], 1):
                conn.execute(
                    """INSERT INTO tests (problem_id, ordinal, input, output, is_hidden, points, note)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (problem_id, ordinal, data_in, data_out, hidden, note),
                )

        ids[spec["code"]] = problem_id
        public = sum(1 for t in spec["tests"] if not t[2])
        hidden_n = len(spec["tests"]) - public
        print(f"  {spec['code']}: {public} bộ công khai, {hidden_n} bộ ẩn")

    return ids


def seed_contests(conn, problem_ids: dict[str, int]) -> None:
    now = datetime.now(timezone.utc)

    for spec in CONTESTS:
        row = db.query_one(conn, "SELECT id FROM contests WHERE name = ?", (spec["name"],))
        if row:
            continue

        starts = (now + timedelta(days=spec["start_offset_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        ends = (now + timedelta(days=spec["end_offset_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")

        with conn:
            cur = conn.execute(
                """INSERT INTO contests (name, description, starts_at, ends_at, scoring, status, created_at)
                   VALUES (?, ?, ?, ?, 'ioi', ?, ?)""",
                (spec["name"], spec["description"], starts, ends,
                 spec["status"], db.utc_now()),
            )
            contest_id = cur.lastrowid
            for ordinal, code in enumerate(spec["problems"], 1):
                problem_id = problem_ids.get(code)
                if problem_id is None:
                    continue
                conn.execute(
                    """INSERT INTO contest_problems (contest_id, problem_id, ordinal, points)
                       VALUES (?, ?, ?, 100)""",
                    (contest_id, problem_id, ordinal),
                )
        print(f"  {spec['name']} ({spec['status']}, {len(spec['problems'])} đề)")


def seed_submissions(conn, user_ids: dict[str, int], problem_ids: dict[str, int]) -> int:
    """Chèn bài nộp ở trạng thái chờ chấm. Worker sẽ chấm thật."""
    now = datetime.now(timezone.utc)
    inserted = 0

    for username, code, source, hours_ago in DEMO_SUBMISSIONS:
        user_id = user_ids.get(username)
        problem_id = problem_ids.get(code)
        if user_id is None or problem_id is None:
            print(f"  bỏ qua: không có {username} hoặc {code}", file=sys.stderr)
            continue

        created = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Không tạo trùng khi chạy lại: nhận diện theo (người nộp, đề, mã nguồn).
        exists = db.query_one(
            conn,
            "SELECT id FROM submissions WHERE user_id = ? AND problem_id = ? AND source = ?",
            (user_id, problem_id, source),
        )
        if exists:
            continue

        with conn:
            conn.execute(
                """INSERT INTO submissions
                     (problem_id, user_id, language, source, status, created_at)
                   VALUES (?, ?, 'cpp17', ?, 'pending', ?)""",
                (problem_id, user_id, source, created),
            )
        inserted += 1

    print(f"  {inserted} bài nộp mới ở trạng thái chờ chấm")
    return inserted


# ==========================================================================
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tạo dữ liệu mẫu cho Song Lo OJ")
    parser.add_argument("--database", default="server/var/songlo.db")
    parser.add_argument("--reset", action="store_true",
                        help="xoá CSDL hiện có rồi tạo lại từ đầu")
    parser.add_argument("--no-submissions", action="store_true",
                        help="không tạo bài nộp mẫu")
    args = parser.parse_args(argv)

    path = Path(args.database)

    if args.reset:
        print("Xoá CSDL cũ:")
        reset_database(path)

    print(f"Khởi tạo lược đồ trong {path}")
    db.init_db(path)
    conn = db.connect(path)

    try:
        print("Tài khoản:")
        user_ids = seed_users(conn)

        author_id = user_ids.get("cophang") or next(iter(user_ids.values()))
        print("Đề bài và bộ dữ liệu:")
        problem_ids = seed_problems(conn, author_id)

        print("Kỳ thi:")
        seed_contests(conn, problem_ids)

        if not args.no_submissions:
            print("Bài nộp mẫu (sẽ được chấm thật):")
            seed_submissions(conn, user_ids, problem_ids)
    finally:
        conn.close()

    print()
    print("Xong. Bước tiếp theo — chấm các bài nộp vừa tạo:")
    print(f"  python -m server.worker --database {path} --once")
    print()
    print("Tài khoản để đăng nhập:")
    print(f"  Giáo viên : cophang / {TEACHER_PASSWORD}   (quản trị)")
    print(f"              thaydung / {TEACHER_PASSWORD}")
    print(f"  Học sinh  : 9A01, 9B01, 8A01, 7A01, … / {STUDENT_PASSWORD}")
    print()
    print("Mật khẩu trên chỉ dùng để chạy thử. Đổi hết trước khi đưa lên máy chủ trường.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
