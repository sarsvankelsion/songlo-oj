-- ============================================================================
-- Song Lo OJ — schema
--
-- SQLite. Chạy lại nhiều lần được (mọi câu lệnh đều có IF NOT EXISTS) nên
-- `db.init()` gọi lúc khởi động là an toàn.
--
-- Quy ước:
--   * Thời gian lưu bằng TEXT ISO-8601 UTC ("2026-09-30T12:34:56Z") để sắp xếp
--     bằng so sánh chuỗi là đúng thứ tự. Đổi sang giờ Việt Nam chỉ ở tầng hiển thị.
--   * Thời gian chạy lưu bằng mili giây (INTEGER), bộ nhớ bằng KB (INTEGER).
--     Dùng số nguyên thay vì số thực để không phải lo sai số khi so sánh.
--   * Bộ dữ liệu lưu thẳng trong CSDL dạng TEXT. Với quy mô một trường, bộ dữ
--     liệu vài chục KB một đề thì đây là cách đơn giản nhất và sao lưu chỉ cần
--     copy một tệp.
-- ============================================================================

PRAGMA journal_mode = WAL;      -- cho phép tiến trình web đọc trong khi worker ghi
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- người dùng
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT    NOT NULL UNIQUE,          -- tên đăng nhập, không dấu
  full_name     TEXT    NOT NULL,
  class_name    TEXT    NOT NULL DEFAULT '',      -- '9A', '8B', …  rỗng = không thuộc lớp
  role          TEXT    NOT NULL DEFAULT 'student'
                        CHECK (role IN ('student', 'teacher', 'admin')),
  password_hash TEXT    NOT NULL,
  is_active     INTEGER NOT NULL DEFAULT 1,       -- 0 = bị khoá
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT    NOT NULL,
  last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_class ON users(class_name);
CREATE INDEX IF NOT EXISTS idx_users_role  ON users(role);

-- -------------------------------------------------------------------- đề bài
CREATE TABLE IF NOT EXISTS problems (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  code            TEXT    NOT NULL UNIQUE,        -- 'SL001'
  name            TEXT    NOT NULL,
  difficulty      TEXT    NOT NULL DEFAULT 'co-ban'
                          CHECK (difficulty IN ('co-ban', 'trung-binh', 'nang-cao')),
  topic           TEXT    NOT NULL DEFAULT '',
  statement       TEXT    NOT NULL DEFAULT '',    -- văn bản thuần, hiển thị trong <pre>-like
  time_limit_ms   INTEGER NOT NULL DEFAULT 1000,
  memory_limit_mb INTEGER NOT NULL DEFAULT 256,
  points_mode     TEXT    NOT NULL DEFAULT 'even'
                          CHECK (points_mode IN ('even', 'custom')),
  status          TEXT    NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'review', 'live')),
  author_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_problems_status ON problems(status);

-- ---------------------------------------------------------------- bộ dữ liệu
-- is_hidden = 1: học sinh chỉ thấy đúng/sai, không thấy nội dung vào–ra.
CREATE TABLE IF NOT EXISTS tests (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,                    -- 1, 2, 3…
  input      TEXT    NOT NULL DEFAULT '',
  output     TEXT    NOT NULL DEFAULT '',
  is_hidden  INTEGER NOT NULL DEFAULT 0,
  points     INTEGER NOT NULL DEFAULT 0,          -- chỉ dùng khi points_mode = 'custom'
  note       TEXT    NOT NULL DEFAULT '',
  UNIQUE (problem_id, ordinal)
);

-- -------------------------------------------------------------------- kỳ thi
-- Tạo trước `submissions` vì bảng đó có khoá ngoại trỏ tới đây. SQLite chấp
-- nhận khoá ngoại trỏ tới bảng chưa tồn tại, nhưng chỉ tới lúc dùng mới báo lỗi
-- — nên thứ tự đúng vẫn rõ ràng hơn là dựa vào việc nó "vẫn chạy".
CREATE TABLE IF NOT EXISTS contests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT    NOT NULL,
  description TEXT    NOT NULL DEFAULT '',
  starts_at   TEXT    NOT NULL,
  ends_at     TEXT    NOT NULL,
  scoring     TEXT    NOT NULL DEFAULT 'ioi' CHECK (scoring IN ('ioi', 'acm')),
  status      TEXT    NOT NULL DEFAULT 'upcoming'
                      CHECK (status IN ('draft', 'upcoming', 'open', 'closed')),
  created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contest_time ON contests(starts_at);

CREATE TABLE IF NOT EXISTS contest_problems (
  contest_id INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
  problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,
  points     INTEGER NOT NULL DEFAULT 100,
  PRIMARY KEY (contest_id, problem_id)
);

CREATE TABLE IF NOT EXISTS contest_entries (
  contest_id    INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
  user_id       INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  registered_at TEXT    NOT NULL,
  PRIMARY KEY (contest_id, user_id)
);

-- ------------------------------------------------------------------ bài nộp
CREATE TABLE IF NOT EXISTS submissions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id  INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  contest_id  INTEGER REFERENCES contests(id)          ON DELETE SET NULL,
  language    TEXT    NOT NULL DEFAULT 'cpp17',
  source      TEXT    NOT NULL,
  -- pending | judging | done | error
  status      TEXT    NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'judging', 'done', 'error')),
  -- rỗng khi chưa chấm xong
  verdict     TEXT    NOT NULL DEFAULT ''
                      CHECK (verdict IN ('', 'AC', 'WA', 'TLE', 'MLE', 'RE', 'CE', 'IE')),
  score       INTEGER NOT NULL DEFAULT 0,
  max_score   INTEGER NOT NULL DEFAULT 0,
  time_ms     INTEGER NOT NULL DEFAULT 0,         -- lớn nhất trong các bộ
  memory_kb   INTEGER NOT NULL DEFAULT 0,         -- lớn nhất trong các bộ
  compile_log TEXT    NOT NULL DEFAULT '',
  judge_log   TEXT    NOT NULL DEFAULT '',        -- thông tin máy chấm, hàng đợi…
  created_at  TEXT    NOT NULL,
  judged_at   TEXT,
  claimed_at  TEXT,                               -- worker đã nhận việc lúc nào
  claimed_by  TEXT                                -- tên tiến trình chấm
);
CREATE INDEX IF NOT EXISTS idx_sub_pending ON submissions(status, id);
CREATE INDEX IF NOT EXISTS idx_sub_user    ON submissions(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_sub_problem ON submissions(problem_id, id DESC);
-- Đếm lượt nộp trong ngày của một học sinh cho một đề.
CREATE INDEX IF NOT EXISTS idx_sub_rate    ON submissions(user_id, problem_id, created_at);

-- ------------------------------------------------- kết quả từng bộ dữ liệu
CREATE TABLE IF NOT EXISTS test_results (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  ordinal       INTEGER NOT NULL,
  verdict       TEXT    NOT NULL,
  time_ms       INTEGER NOT NULL DEFAULT 0,
  memory_kb     INTEGER NOT NULL DEFAULT 0,
  points        INTEGER NOT NULL DEFAULT 0,
  message       TEXT    NOT NULL DEFAULT '',
  -- Bản chụp nội dung tại thời điểm chấm. Rỗng với bộ ẩn: nội dung ẩn không bao
  -- giờ được ghi ra bảng này, để một lỗi ở tầng hiển thị cũng không thể làm lộ đề.
  input_seen    TEXT    NOT NULL DEFAULT '',
  expected_seen TEXT    NOT NULL DEFAULT '',
  actual_seen   TEXT    NOT NULL DEFAULT '',
  UNIQUE (submission_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_tr_sub ON test_results(submission_id, ordinal);

-- --------------------------------------------------------------- nhật ký chấm
-- Một dòng cho mỗi lần worker xử lý một bài nộp. Dùng để chẩn đoán khi có bài
-- nộp kẹt ở trạng thái "đang chấm".
CREATE TABLE IF NOT EXISTS judge_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER REFERENCES submissions(id) ON DELETE CASCADE,
  at            TEXT    NOT NULL,
  level         TEXT    NOT NULL DEFAULT 'info',
  message       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jlog_sub ON judge_log(submission_id, id);
