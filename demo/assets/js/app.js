/* Song Lo OJ — demo interactions. Vanilla JS, no dependencies. */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Tabs ---------- */
  function initTabs() {
    document.querySelectorAll('[data-tabs]').forEach(function (group) {
      var tabs = Array.prototype.slice.call(group.querySelectorAll('[role="tab"]'));
      if (!tabs.length) return;

      function select(tab) {
        tabs.forEach(function (t) {
          var selected = t === tab;
          t.setAttribute('aria-selected', String(selected));
          t.tabIndex = selected ? 0 : -1;
          var panel = document.getElementById(t.getAttribute('aria-controls'));
          if (panel) panel.hidden = !selected;
        });
      }

      tabs.forEach(function (tab, i) {
        tab.addEventListener('click', function () { select(tab); });
        tab.addEventListener('keydown', function (e) {
          var next = null;
          if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
          if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
          if (e.key === 'Home') next = tabs[0];
          if (e.key === 'End') next = tabs[tabs.length - 1];
          if (next) { e.preventDefault(); next.focus(); select(next); }
        });
      });

      var initial = tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0];

      /* Deep link: /problem.html#panel-submit opens the submit tab directly */
      var hash = (window.location.hash || '').replace('#', '');
      var deepLinked = false;
      if (hash) {
        var linked = tabs.filter(function (t) { return t.getAttribute('aria-controls') === hash; })[0];
        if (linked) { initial = linked; deepLinked = true; }
      }

      select(initial);

      /* A tab panel is not a page section — keep the view at the top so the
         page title and tab bar stay visible instead of jumping past them. */
      if (deepLinked) {
        requestAnimationFrame(function () { window.scrollTo(0, 0); });
      }

      window.addEventListener('hashchange', function () {
        var h = (window.location.hash || '').replace('#', '');
        var target = tabs.filter(function (t) { return t.getAttribute('aria-controls') === h; })[0];
        if (target) select(target);
      });
    });
  }

  /* ---------- Sortable tables ---------- */
  function initSort() {
    document.querySelectorAll('table[data-sortable]').forEach(function (table) {
      var body = table.tBodies[0];
      if (!body) return;

      table.querySelectorAll('th').forEach(function (th, index) {
        if (th.hasAttribute('data-nosort')) return;
        var label = th.textContent.trim();
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'table__sort';
        btn.textContent = label;
        th.textContent = '';
        th.appendChild(btn);

        btn.addEventListener('click', function () {
          var current = th.getAttribute('aria-sort');
          var dir = current === 'ascending' ? 'descending' : 'ascending';

          table.querySelectorAll('th[aria-sort]').forEach(function (o) {
            if (o !== th) o.removeAttribute('aria-sort');
          });
          th.setAttribute('aria-sort', dir);

          var rows = Array.prototype.slice.call(body.rows);
          var numeric = th.hasAttribute('data-numeric');

          rows.sort(function (a, b) {
            var av = cellValue(a, index);
            var bv = cellValue(b, index);
            if (numeric) {
              av = parseFloat(av.replace(/[^\d.-]/g, '')) || 0;
              bv = parseFloat(bv.replace(/[^\d.-]/g, '')) || 0;
              return dir === 'ascending' ? av - bv : bv - av;
            }
            return dir === 'ascending'
              ? av.localeCompare(bv, 'vi')
              : bv.localeCompare(av, 'vi');
          });

          rows.forEach(function (r) { body.appendChild(r); });
        });
      });

      function cellValue(row, index) {
        var cell = row.cells[index];
        if (!cell) return '';
        var input = cell.querySelector('input');
        return (input ? input.value : cell.textContent).trim();
      }
    });
  }

  /* ---------- Code editor ---------- */
  var HL_KEYWORDS = ('alignas alignof asm break case catch class const constexpr continue '
    + 'decltype default delete do else enum explicit export extern for friend goto if '
    + 'inline mutable namespace new noexcept operator private protected public register '
    + 'return sizeof static struct switch template this throw try typedef typename union '
    + 'using virtual volatile while true false nullptr').split(' ');

  var HL_TYPES = ('auto bool char double float int long short signed unsigned void size_t '
    + 'wchar_t string vector map set unordered_map unordered_set pair queue stack deque '
    + 'priority_queue array list bitset tuple complex iterator istream ostream '
    + 'stringstream ifstream ofstream').split(' ');

  var HL_KEY = {}, HL_TYPE = {};
  HL_KEYWORDS.forEach(function (w) { HL_KEY[w] = 1; });
  HL_TYPES.forEach(function (w) { HL_TYPE[w] = 1; });

  /* One alternation, matched left to right. Group order defines priority:
     comments beat strings, strings beat numbers, and so on. */
  var HL_RE = new RegExp([
    '(\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/)',        // 1 comment
    '("(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\')', // 2 string / char
    '(^[ \\t]*#[^\\n]*)',                            // 3 preprocessor
    '(\\b(?:0[xX][0-9a-fA-F]+|\\d+\\.?\\d*)\\b)',    // 4 number
    '(\\b[A-Za-z_]\\w*\\b)(?=[ \\t]*\\()',           // 5 call
    '(\\b[A-Za-z_]\\w*\\b)'                          // 6 identifier
  ].join('|'), 'gm');

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function highlightCpp(src) {
    var out = '';
    var last = 0;
    var m;
    HL_RE.lastIndex = 0;

    while ((m = HL_RE.exec(src)) !== null) {
      if (m.index > last) out += escHtml(src.slice(last, m.index));

      var text = m[0];
      var cls = '';
      if (m[1]) cls = 'tok-com';
      else if (m[2]) cls = 'tok-str';
      else if (m[3]) cls = 'tok-pp';
      else if (m[4]) cls = 'tok-num';
      else if (m[5]) cls = 'tok-fn';
      else if (m[6]) {
        if (HL_KEY[m[6]]) cls = 'tok-key';
        else if (HL_TYPE[m[6]]) cls = 'tok-type';
      }

      out += cls ? '<span class="' + cls + '">' + escHtml(text) + '</span>' : escHtml(text);
      last = m.index + text.length;
      if (text.length === 0) HL_RE.lastIndex++;   // guard against a zero-length match
    }

    return out + escHtml(src.slice(last));
  }

  function initEditor() {
    document.querySelectorAll('[data-editor]').forEach(function (wrap) {
      var area = wrap.querySelector('.editor__area');
      var gutter = wrap.querySelector('.editor__gutter');
      var counter = wrap.querySelector('[data-editor-lines]');
      var layer = wrap.querySelector('.editor__hl');
      if (!area) return;

      /* The editor grows with its content instead of leaving a dead dark
         block under short programs, and caps out at a readable height. */
      var MIN_H = 210, MAX_H = 620;

      function autoGrow() {
        area.style.height = 'auto';
        var h = Math.max(area.scrollHeight, MIN_H);
        if (h >= MAX_H) {
          area.style.height = MAX_H + 'px';
          area.style.overflowY = 'auto';
        } else {
          area.style.height = h + 'px';
          area.style.overflowY = 'hidden';
        }
      }

      function refresh() {
        var lines = area.value.split('\n').length;
        if (gutter) {
          var html = '';
          for (var i = 1; i <= lines; i++) html += i + '\n';
          gutter.textContent = html;
        }
        if (counter) counter.textContent = lines + ' dòng';
        if (layer) {
          layer.innerHTML = highlightCpp(area.value) + '\n';
          wrap.classList.add('is-hl');
        }
        autoGrow();
      }

      /* Keep the two layers locked together. The textarea owns the scroll;
         the gutter and the highlight layer follow it. */
      function sync() {
        if (gutter) gutter.scrollTop = area.scrollTop;
        if (layer) { layer.scrollTop = area.scrollTop; layer.scrollLeft = area.scrollLeft; }
      }

      area.addEventListener('input', function () { refresh(); sync(); });
      area.addEventListener('scroll', sync);
      area.addEventListener('change', sync);

      /* Tab inserts spaces instead of moving focus — but Escape releases it */
      area.addEventListener('keydown', function (e) {
        if (e.key === 'Tab' && !e.shiftKey) {
          e.preventDefault();
          var s = area.selectionStart, en = area.selectionEnd;
          area.value = area.value.slice(0, s) + '    ' + area.value.slice(en);
          area.selectionStart = area.selectionEnd = s + 4;
          refresh();
        }
        if (e.key === 'Escape') area.blur();
      });

      refresh();
      sync();
    });
  }

  /* ---------- Table filter (search + chips + selects) ---------- */
  function initFilter() {
    var search = document.querySelector('[data-filter-search]');
    var rows = document.querySelectorAll('[data-filter-row]');
    var countEl = document.querySelector('[data-filter-count]');
    var chips = document.querySelectorAll('[data-filter-tag]');
    var selects = document.querySelectorAll('[data-filter-select]');
    if (!rows.length) return;

    var activeTag = 'all';

    function apply() {
      var q = (search && search.value || '').trim().toLowerCase();
      var shown = 0;

      rows.forEach(function (row) {
        var text = row.textContent.toLowerCase();
        var tags = (row.getAttribute('data-tags') || '').split(/\s+/);
        var ok = (!q || text.indexOf(q) !== -1) &&
                 (activeTag === 'all' || tags.indexOf(activeTag) !== -1);

        /* Each <select data-filter-select data-filter-key="verdict"> is matched
           against the row's data-verdict attribute. */
        if (ok) {
          for (var i = 0; i < selects.length; i++) {
            var key = selects[i].getAttribute('data-filter-key');
            var val = selects[i].value;
            if (val && val !== 'all' && (row.getAttribute('data-' + key) || '') !== val) {
              ok = false;
              break;
            }
          }
        }

        row.hidden = !ok;
        if (ok) shown++;
      });

      if (countEl) countEl.textContent = shown;

      var empty = document.querySelector('[data-filter-empty]');
      if (empty) empty.hidden = shown !== 0;
    }

    if (search) search.addEventListener('input', apply);

    selects.forEach(function (sel) {
      sel.addEventListener('change', apply);
    });

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (c) { c.setAttribute('aria-pressed', 'false'); });
        chip.setAttribute('aria-pressed', 'true');
        activeTag = chip.getAttribute('data-filter-tag');
        apply();
      });
    });

    apply();
  }

  /* ---------- Countdown ---------- */
  function initCountdown() {
    var all = document.querySelectorAll('[data-countdown], [data-countdown-relative]');
    if (!all.length) return;

    Array.prototype.forEach.call(all, function (el) {
      var target;

      /* data-countdown-relative="47m" — demo helper so the sample contest
         always looks live no matter when the page is opened. */
      var rel = el.getAttribute('data-countdown-relative');
      if (rel) {
        var n = parseInt(rel, 10) || 0;
        var unit = rel.replace(/[0-9]/g, '').trim();
        var ms = unit === 'h' ? n * 3600000 : unit === 'd' ? n * 86400000 : n * 60000;
        target = Date.now() + ms;
      } else {
        target = new Date(el.getAttribute('data-countdown')).getTime();
      }

      var out = {
        d: el.querySelector('[data-cd="d"]'),
        h: el.querySelector('[data-cd="h"]'),
        m: el.querySelector('[data-cd="m"]'),
        s: el.querySelector('[data-cd="s"]')
      };

      var scope = el.closest('section, article') || document;
      var status = scope.querySelector('[data-countdown-status]');

      function pad(v) { return String(v).padStart(2, '0'); }

      function tick() {
        var diff = target - Date.now();
        if (diff <= 0) {
          ['d', 'h', 'm', 's'].forEach(function (k) { if (out[k]) out[k].textContent = '00'; });
          if (status) status.textContent = 'Đã kết thúc';
          clearInterval(timer);
          return;
        }
        var s = Math.floor(diff / 1000);
        if (out.d) out.d.textContent = pad(Math.floor(s / 86400));
        if (out.h) out.h.textContent = pad(Math.floor(s % 86400 / 3600));
        if (out.m) out.m.textContent = pad(Math.floor(s % 3600 / 60));
        if (out.s) out.s.textContent = pad(s % 60);
      }

      tick();
      var timer = setInterval(tick, 1000);
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) { clearInterval(timer); }
        else { clearInterval(timer); tick(); timer = setInterval(tick, 1000); }
      });
    });
  }

  /* ---------- Fake submit feedback (demo only) ---------- */
  function initSubmit() {
    var form = document.querySelector('[data-submit-form]');
    if (!form) return;

    /* Cùng một `app.js` phục vụ cả bản demo tĩnh lẫn backend thật (Flask trỏ
       static_folder vào `demo/assets`). Khối này chặn sự kiện mặc định, nên nếu
       một mẫu template thật lỡ mang `data-submit-form` thì học sinh bấm "Nộp bài"
       và không có gì được gửi đi — im lặng, không lỗi. Biểu mẫu thật luôn có
       `action` trỏ tới route nộp bài; biểu mẫu demo thì không. */
    if (form.getAttribute('action')) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = form.querySelector('button[type="submit"]');
      var status = document.querySelector('[data-submit-status]');
      if (!btn || btn.disabled) return;

      btn.disabled = true;
      btn.textContent = 'Đang chấm…';
      if (status) { status.hidden = false; status.className = 'alert alert--info'; status.innerHTML = '<div><p class="alert__title mb-0">Đang chấm bài…</p><p class="mb-0 text-sm">Hàng đợi: vị trí 3. Bản demo chưa có backend nên sẽ không có kết quả thật.</p></div>'; }

      setTimeout(function () {
        btn.disabled = false;
        btn.textContent = 'Nộp bài';
        if (status) {
          status.className = 'alert alert--warn';
          status.innerHTML = '<div><p class="alert__title mb-0">Đây là bản demo giao diện</p>' +
            '<p class="mb-0 text-sm">Chưa có backend chấm bài. Kết quả sẽ hiển thị ở đây sau khi nối với judge.</p></div>';
        }
      }, reduceMotion ? 200 : 1400);
    });
  }

  /* ---------- Login form (demo) ---------- */
  function initLogin() {
    var form = document.getElementById('login-form');
    if (!form) return;

    var summary = document.getElementById('login-errors');
    var list = document.getElementById('login-errors-list');
    var fields = ['username', 'password'];

    function clear(id) {
      var input = document.getElementById(id);
      var err = document.getElementById(id + '-error');
      if (input) input.removeAttribute('aria-invalid');
      if (err) { err.hidden = true; err.textContent = ''; }
    }

    function mark(id, message) {
      var input = document.getElementById(id);
      var err = document.getElementById(id + '-error');
      if (input) input.setAttribute('aria-invalid', 'true');
      if (err) { err.hidden = false; err.textContent = message; }
    }

    fields.forEach(function (id) {
      var input = document.getElementById(id);
      if (input) input.addEventListener('input', clear.bind(null, id));
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      fields.forEach(clear);

      var u = document.getElementById('username');
      var p = document.getElementById('password');
      var problems = [];

      if (!u.value.trim()) {
        mark('username', 'Nhập tên đăng nhập.');
        problems.push({ id: 'username', msg: 'Nhập tên đăng nhập.' });
      }
      if (!p.value) {
        mark('password', 'Nhập mật khẩu.');
        problems.push({ id: 'password', msg: 'Nhập mật khẩu.' });
      } else if (p.value.length < 8) {
        mark('password', 'Mật khẩu phải có ít nhất 8 ký tự.');
        problems.push({ id: 'password', msg: 'Mật khẩu phải có ít nhất 8 ký tự.' });
      }

      if (problems.length) {
        list.innerHTML = '';
        problems.forEach(function (item) {
          var li = document.createElement('li');
          var a = document.createElement('a');
          a.href = '#' + item.id;
          a.textContent = item.msg;
          a.addEventListener('click', function (ev) {
            ev.preventDefault();
            var target = document.getElementById(item.id);
            if (target) target.focus();
          });
          li.appendChild(a);
          list.appendChild(li);
        });
        summary.hidden = false;
        summary.focus();
        return;
      }

      summary.hidden = true;
      var btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      btn.textContent = 'Đang đăng nhập…';
      setTimeout(function () { window.location.href = 'index.html'; }, reduceMotion ? 150 : 650);
    });
  }

  /* ---------- Theme (light / dark) ---------- */
  function initTheme() {
    var root = document.documentElement;
    var btns = document.querySelectorAll('[data-theme-toggle]');
    if (!btns.length) return;

    function label(dark) {
      return dark ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối';
    }

    function apply(dark) {
      if (dark) root.setAttribute('data-theme', 'dark');
      else root.removeAttribute('data-theme');
      btns.forEach(function (b) {
        b.setAttribute('aria-pressed', String(dark));
        b.setAttribute('aria-label', label(dark));
        b.title = label(dark);
      });
    }

    /* The inline <head> script already resolved the stored choice (or the OS
       preference) before first paint — this only syncs the button labels. */
    var dark = root.getAttribute('data-theme') === 'dark';
    apply(dark);

    btns.forEach(function (b) {
      b.addEventListener('click', function () {
        dark = root.getAttribute('data-theme') !== 'dark';
        apply(dark);
        try { localStorage.setItem('sl-theme', dark ? 'dark' : 'light'); } catch (e) {}
      });
    });

    /* Keep following the OS, but only until the user picks a side. */
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onChange = function (e) {
      var stored = null;
      try { stored = localStorage.getItem('sl-theme'); } catch (err) {}
      if (!stored) apply(e.matches);
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  /* ---------- Read-only code viewer ---------- */
  function initViewer() {
    document.querySelectorAll('[data-code-view]').forEach(function (view) {
      var pre = view.querySelector('.viewer__pre');
      var gutter = view.querySelector('.viewer__gutter');
      var scroller = view.querySelector('.viewer__code');
      if (!pre) return;

      var src = pre.textContent.replace(/\n+$/, '');
      var lang = view.getAttribute('data-lang') || 'cpp';

      /* Highlighting is opt-in per block: a compiler log must stay verbatim. */
      if (lang === 'cpp' && pre.hasAttribute('data-highlight')) {
        pre.innerHTML = highlightCpp(src);
      }

      if (gutter) {
        var lines = src.split('\n').length;
        var html = '';
        for (var i = 1; i <= lines; i++) html += i + '\n';
        gutter.textContent = html;

        if (scroller) {
          scroller.addEventListener('scroll', function () {
            gutter.scrollTop = scroller.scrollTop;
          });
        }
      }
    });
  }

  /* ---------- Morph page transitions ----------
     Xem mục 35 trong style.css. Tóm tắt: phần tử mang `data-morph` trùng tên ở
     hai trang sẽ được trình duyệt nội suy vị trí và kích thước khi chuyển
     trang — đó là hiệu ứng morph. Phần ở đây lo ba việc: đặt tên, chặn tên
     trùng, và dựng lại hiệu ứng cho trình duyệt chưa hỗ trợ. */

  var MORPH_STORE_KEY = 'sl-morph';

  /* `document.startViewTransition` có từ Chrome 111, còn chuyển cảnh giữa hai
     trang (thứ ta cần) chỉ có từ Chrome 126. Đây là phép thử gần đúng: trong
     khoảng 111–125 hiệu ứng sẽ không chạy và cũng không có dự phòng, vì dự
     phòng FLIP không thể chạy chồng lên một chuyển cảnh thật. Chấp nhận được —
     đó là khoảng phiên bản ngắn, và bản thân trang vẫn hoạt động bình thường. */
  var hasViewTransitions = 'startViewTransition' in document;

  /* Đặt view-transition-name từ data-morph, đồng thời chặn tên trùng.

     Vì sao phải chặn: khi gặp hai phần tử cùng một view-transition-name trong
     một trang, trình duyệt **huỷ toàn bộ** hiệu ứng chuyển cảnh của cả trang,
     chứ không chỉ bỏ qua phần tử trùng. Nó không hiện gì ra giao diện, chỉ ghi
     một dòng vào console. Nghĩa là một lỗi template sẽ làm hiệu ứng biến mất
     trên mọi lần chuyển trang mà không ai biết vì sao. Bộ chặn này biến một
     thất bại im lặng thành một phần tử mất hiệu ứng, và có cảnh báo trong
     console để lần ra chỗ sai. */
  function initMorphNames() {
    var seen = Object.create(null);

    document.querySelectorAll('[data-morph]').forEach(function (el) {
      var name = el.getAttribute('data-morph');
      if (!name) return;

      /* Phần tử đang bị ẩn — ví dụ nằm trong tab chưa mở — thì không chiếm tên.
         Tên phải thuộc về phần tử thật sự được chụp ảnh. */
      if (!el.getClientRects().length) return;

      if (seen[name]) {
        el.removeAttribute('data-morph');
        if (window.console && console.warn) {
          console.warn('[morph] Bỏ tên trùng "' + name +
                       '": tên trùng làm hỏng hiệu ứng chuyển cảnh của cả trang.');
        }
        return;
      }
      seen[name] = true;
      el.style.viewTransitionName = name;
    });
  }

  /* Ghi lại vị trí và kích thước của mọi phần tử morph trước khi rời trang.
     Cất vào sessionStorage chứ không phải localStorage: dữ liệu này chỉ có
     nghĩa trong một phiên duyệt web, và để lại sẽ khiến lần mở sau đó chạy một
     hiệu ứng dựa trên vị trí của phiên trước. */
  function captureMorphRects() {
    var rects = {};

    document.querySelectorAll('[data-morph]').forEach(function (el) {
      var name = el.getAttribute('data-morph');
      if (!name) return;
      var r = el.getBoundingClientRect();
      if (!r.width && !r.height) return;
      rects[name] = [r.left, r.top, r.width, r.height];
    });

    try {
      sessionStorage.setItem(MORPH_STORE_KEY, JSON.stringify({
        url: window.location.pathname + window.location.search,
        rects: rects
      }));
    } catch (err) {
      /* Chế độ riêng tư của một số trình duyệt chặn sessionStorage. Mất hiệu
         ứng dự phòng, không ảnh hưởng gì tới việc dùng trang. */
    }
  }

  /* Dựng lại hiệu ứng morph cho trình duyệt chưa có View Transitions, bằng
     kỹ thuật FLIP: đo vị trí cũ, để phần tử hiện ở vị trí mới, rồi chạy ngược
     từ vị trí cũ về vị trí mới bằng transform. */
  function runMorphFallback() {
    var raw = null;
    try {
      raw = sessionStorage.getItem(MORPH_STORE_KEY);
      sessionStorage.removeItem(MORPH_STORE_KEY);
    } catch (err) {
      return;
    }
    if (!raw) return;

    var saved = null;
    try {
      saved = JSON.parse(raw);
    } catch (err) {
      return;
    }
    if (!saved || !saved.rects) return;

    /* Tải lại cùng một địa chỉ thì không phải chuyển trang, nên không diễn. */
    if (saved.url === window.location.pathname + window.location.search) return;

    document.querySelectorAll('[data-morph]').forEach(function (el) {
      var from = saved.rects[el.getAttribute('data-morph')];
      if (!from) return;
      if (!from[2] && !from[3]) return;

      var to = el.getBoundingClientRect();
      if (!to.width && !to.height) return;

      /* Phép biến đổi không áp dụng cho phần tử inline. Đổi sang inline-block
         rồi **đo lại**, vì việc đổi kiểu hiển thị có thể làm phần tử xê dịch
         vài pixel — đo trước khi đổi sẽ cho một vị trí đích sai. */
      var wasInline = false;
      if (window.getComputedStyle(el).display === 'inline') {
        el.style.display = 'inline-block';
        wasInline = true;
        to = el.getBoundingClientRect();
      }

      var dx = from[0] - to.left;
      var dy = from[1] - to.top;
      var sx = to.width ? from[2] / to.width : 1;
      var sy = to.height ? from[3] / to.height : 1;

      /* Lệch không đáng kể thì thôi: một hiệu ứng nhúc nhích nửa pixel còn tệ
         hơn không có hiệu ứng nào. */
      if (Math.abs(dx) < 4 && Math.abs(dy) < 4 &&
          Math.abs(sx - 1) < 0.05 && Math.abs(sy - 1) < 0.05) {
        if (wasInline) el.style.display = '';
        return;
      }

      el.style.transformOrigin = 'top left';
      el.style.transition = 'none';
      el.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(' + sx + ',' + sy + ')';
      el.style.opacity = '0.4';

      /* Buộc trình duyệt ghi nhận trạng thái xuất phát trước khi mở animation.
         Thiếu bước này thì hai lệnh gán bị gộp làm một và không có gì chuyển
         động. */
      void el.offsetWidth;

      el.style.transition = 'transform .42s cubic-bezier(.22,1,.36,1), opacity .3s ease';
      el.style.transform = 'translate(0,0) scale(1,1)';
      el.style.opacity = '';

      /* Dọn bằng hẹn giờ chứ không bằng `transitionend`: nếu hiệu ứng bị cắt
         giữa chừng (người dùng cuộn, phần tử bị vẽ lại), sự kiện không bao giờ
         tới và thuộc tính inline sẽ nằm lại trên phần tử. */
      window.setTimeout(function () {
        el.style.transition = '';
        el.style.transform = '';
        el.style.transformOrigin = '';
        el.style.opacity = '';
        if (wasInline) el.style.display = '';
      }, 520);
    });
  }

  /* Chụp vị trí ngay trước khi rời trang. Bắt ở sự kiện `click` thay vì
     `beforeunload`: `beforeunload` bắt cả lúc đóng tab và lúc tải lại, mà tải
     lại thì không phải chuyển trang nên không nên diễn hiệu ứng. */
  function initMorphCapture() {
    document.addEventListener('click', function (e) {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

      var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!a) return;
      if (a.target && a.target !== '_self') return;

      var href = a.getAttribute('href') || '';
      if (!href || href.charAt(0) === '#' || /^(mailto:|tel:|javascript:)/i.test(href)) return;

      var url;
      try {
        url = new URL(a.href, window.location.href);
      } catch (err) {
        return;
      }
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname &&
          url.search === window.location.search) return;

      captureMorphRects();
    }, true);
  }

  /* Hộp thoại xác nhận cho các thao tác không hoàn tác được. Dùng thuộc tính
     `data-confirm` trên biểu mẫu thay vì `onsubmit` viết thẳng trong HTML, để
     phần đánh dấu không phải chứa mã. */
  function initConfirm() {
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (!window.confirm(form.getAttribute('data-confirm'))) e.preventDefault();
      });
    });
  }

  /* Bộ đếm ký tự cho các ô có giới hạn độ dài.

     `maxlength` một mình chặn được việc gõ quá, nhưng không cho biết còn bao
     nhiêu chỗ — học sinh chỉ phát hiện ra khi đã gõ tới ký tự cuối và thấy không
     gõ thêm được nữa, lúc đó phải tự xoá bớt mà không biết xoá bao nhiêu. Bộ đếm
     biến giới hạn thành thứ nhìn thấy được.

     Đích đến lấy từ `data-count-for` nên cùng một hàm dùng được cho mọi ô sau
     này, không phải sửa JavaScript mỗi lần thêm một ô đếm. */
  function initCharCount() {
    document.querySelectorAll('[data-count-for]').forEach(function (field) {
      var target = document.querySelector(field.getAttribute('data-count-for'));
      if (!target) return;
      var update = function () { target.textContent = field.value.length; };
      field.addEventListener('input', update);
      update();
    });
  }

  /* ---------- Boot ---------- */
  function boot() {
    initTheme();
    initTabs();
    initSort();
    initEditor();
    initViewer();
    initFilter();
    initCountdown();
    initSubmit();
    initLogin();
    initConfirm();
    initLatexBar();
    initMath();
    initCharCount();

    if (!reduceMotion && !hasViewTransitions) {
      runMorphFallback();
      initMorphCapture();
    }
  }

  /* ---------- 40. Công thức LaTeX (KaTeX) ----------

     Đề bài lưu dạng văn bản thuần. Giáo viên gõ công thức giữa hai dấu `$`
     (giữa dòng) hoặc `$$` (riêng một dòng), KaTeX đổi thành công thức thật.

     Vì sao đổi ở trình duyệt chứ không ở máy chủ: máy chủ chỉ có Python, không
     có LaTeX. KaTeX là bản dựng lại bằng JavaScript nên chạy được ngay trên máy
     học sinh, không phải cài thêm gì.

     Vì sao KaTeX nằm trong `assets/vendor/katex` chứ không lấy từ CDN: máy chủ
     trường có thể không ra được Internet, và khi đó công thức vẫn phải hiện. */
  /* ---------- 40b. Đổi LaTeX văn bản thành HTML ----------

     Vì sao cần phần này: giáo viên dán **cả một tệp .tex** vào ô soạn đề — đúng
     thứ mà Themis và mọi kho đề của trường đang dùng. Nếu chỉ cho KaTeX xử lý
     `$…$` thì phần toán hiện ra đẹp, còn `\documentclass`, `\subsection*{…}`,
     `\begin{tabular}` hiện nguyên văn. Nhìn vào chỉ thấy một đống lệnh, không ra
     đề bài — chính là cảm giác "preview không khác gì chữ thường".

     Cách làm: **che phần toán đi trước**, biến đổi phần chữ, rồi trả phần toán
     về chỗ cũ. Nếu làm ngược lại — biến đổi chữ trước — thì các lệnh trong công
     thức (`\frac`, `\begin{cases}`) cũng bị coi là lệnh văn bản và bị ăn mất.

     Thứ tự này là bắt buộc, không phải tùy chọn:
       1. che toán            → chỗ giữ chỗ
       2. bỏ chú thích        → `%` tới hết dòng
       3. bỏ phần mào đầu     → mọi thứ trước `\begin{document}`
       4. `\&` → ký tự đánh dấu riêng (`TEX_AMP`)
       5. mở các ký tự LaTeX  → `\%` → `%`, …
       6. bảng                → HTML, cất vào chỗ giữ chỗ
       7. thoát HTML          → `&` `<` `>` thành thực thể
       8. môi trường, tiêu đề, lệnh định dạng → thẻ HTML
       9. trả toán và bảng về

     Ba chỗ dễ làm hỏng, đều đã trả giá bằng một lần sửa:

     - **Bước 4 và 5 phải đứng trước bước 7.** Đảo lại thì dấu `&` của LaTeX
       thành `&amp;amp;` và hiện ra thành "&amp;" trên màn hình.
     - **Bước 6 phải đứng trước bước 7.** Dấu `&` ngăn cách hai ô của bảng và
       dấu `&` thật (`\&`) đều thành `&amp;` sau bước 7, nên tách ô sẽ sai: một
       ô chứa "Tom \& Jerry" bị cắt thành ba ô, ô giữa hiện ra chữ "amp;".
       Vì vậy bảng được dựng trước, rồi cất vào chỗ giữ chỗ để bước 7 không
       thoát luôn các thẻ `<table>` vừa sinh ra.
     - **Bước 0 (cổng an toàn, xem `texLooksLikeLatex`) phải đứng trước tất cả.**
       Bước 2 và bước 8 xoá chữ không thương tiếc: "50%" mất đuôi dòng, và
       `C:\Users` chỉ còn `C:`. Văn bản không phải LaTeX thì không được đi vào
       đường ống này. */
  var TEX_MARK = '\u0001';

  /* Ký tự đánh dấu cho một dấu `&` **thật** — thứ giáo viên viết là `\&` trong
     LaTeX. Phải tách nó ra khỏi dấu `&` ngăn cách ô của bảng **trước** khi thoát
     HTML, vì sau bước đó cả hai đều là `&amp;` và không còn phân biệt được nữa.
     `\u0002` là ký tự điều khiển, không gõ được từ bàn phím. */
  var TEX_AMP = '\u0002';

  function texEscapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* `\&`, `\%`, `\$`… là cách LaTeX viết một ký tự thật. `\&` đã được tách ra
     thành `TEX_AMP` từ trước nên ở đây không còn nó. */
  function texUnescapeChars(s) {
    return s.replace(/\\textbackslash\b/g, '\\')
            .replace(/\\textasciitilde\b/g, '~')
            .replace(/\\([&%$#_{}])/g, '$1');
  }

  /* Nội dung một ô của bảng: trả dấu `&` thật về, rồi thoát HTML.

     Ô của bảng phải tự thoát HTML lấy, vì `texTabular` chạy **trước** bước thoát
     HTML chung — nếu không thì dấu `&` ngăn cách ô đã thành `&amp;` mất rồi. */
  function texCellHtml(cell) {
    return texEscapeHtml(texUnescapeChars(cell.trim()).split(TEX_AMP).join('&'));
  }

  function texProtectMath(src, store) {
    /* Bốn dấu phân cách giống hệt cấu hình của KaTeX ở dưới, để chỗ nào KaTeX
       định render thì chỗ đó cũng được che. `$$` phải đứng trước `$` trong biểu
       thức, nếu không `$$x$$` bị cắt thành hai công thức rỗng. */
    return src.replace(
      /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]*?\$/g,
      function (m) {
        store.push(texEscapeHtml(m));
        return TEX_MARK + (store.length - 1) + TEX_MARK;
      });
  }

  /* Văn bản này có phải LaTeX thật không?

     Đây là **cổng an toàn**, không phải chi tiết trang trí. Cả đường ống ở dưới
     được thiết kế cho một tệp .tex, và hai bước của nó rất phá hoại nếu áp lên
     văn bản thường:

       - bước 2 xoá từ dấu `%` tới hết dòng (chú thích của LaTeX). Một đề văn
         bản thuần viết "Điểm tối đa 50%" sẽ mất luôn phần đuôi dòng.
       - bước 6d xoá mọi `\lệnh`. Một đề có đường dẫn `C:\Users\an` sẽ còn `C:`.

     Cả hai đều là mất chữ **im lặng**: không lỗi, không cảnh báo, chỉ là đề bài
     ngắn đi. Nên chỉ khi văn bản mang dấu hiệu cấu trúc của LaTeX — môi trường,
     khai báo gói, lệnh định dạng có ngoặc — thì mới coi là LaTeX.

     Dấu hiệu cố tình chọn loại **hẹp**: chỉ những lệnh gần như không bao giờ
     xuất hiện trong văn xuôi tiếng Việt. Các lệnh một chữ như `\par`, `\item`,
     `\hline` vẫn nhận vì chúng đi kèm dấu `\` mà văn xuôi không dùng.

     Bỏ sót (đoán nhầm LaTeX thành văn thường) chỉ khiến vài lệnh hiện nguyên
     văn — khó chịu nhưng không mất gì. Nhận nhầm theo chiều ngược lại thì mất
     chữ của đề. Vì vậy thà bỏ sót.

     Toán giữa hai dấu `$` không tính là dấu hiệu: đề văn bản thuần có công thức
     vẫn phải đi đường văn bản thuần, rồi KaTeX render `$…$` như trước nay. */
  var TEX_SIGNAL = new RegExp(
    '\\\\(' +
      'documentclass|usepackage|RequirePackage|textbackslash' +
      '|begin\\{(document|tabular|tabularx|longtable|itemize|enumerate|center' +
        '|flushleft|flushright|verbatim|figure|table|thebibliography)\\}' +
      '|end\\{(document|tabular|itemize|enumerate|center|verbatim)\\}' +
      '|(section|subsection|subsubsection)\\*?\\{' +
      '|item\\b|hline\\b|noindent\\b|par\\b|newline\\b|linebreak\\b' +
      '|(textbf|textit|emph|underline|texttt|textnormal|text|mathrm|mathbf)\\s*\\{' +
      '|(vspace|hspace|vskip|hskip)\\b' +
      '|includegraphics|bibliography|cite\\b|label\\b' +
    ')'
  );

  function texLooksLikeLatex(src) {
    return TEX_SIGNAL.test(src);
  }

  function texRestoreMath(out, store) {
    return out.replace(new RegExp(TEX_MARK + '(\\d+)' + TEX_MARK, 'g'), function (_m, i) {
      return store[+i];
    });
  }

  /* Cất một đoạn HTML đã dựng sẵn vào `store` và để lại một chỗ giữ chỗ trong
     văn bản. Dùng chung `store` với phần toán: cả hai đều là "HTML đã xong, đừng
     đụng vào nữa", và `texRestoreMath` trả tất cả về cùng một lượt.

     Cần hàm này cho bảng: bảng phải dựng **trước** bước thoát HTML (xem
     `texToHtml`), mà bước đó sẽ thoát luôn các thẻ `<table>` vừa sinh ra nếu
     chúng còn nằm trong văn bản. */
  function texProtectHtml(src, store, re, build) {
    return src.replace(re, function () {
      store.push(build.apply(null, arguments));
      return TEX_MARK + (store.length - 1) + TEX_MARK;
    });
  }

  /* Bảng `tabular`. Đây là thứ hay gặp nhất trong đề Themis vì phần "dữ liệu
     vào / dữ liệu ra" luôn được trình bày bằng bảng, và nếu không đổi thì cả
     khối `\begin{tabular}{|c|c|}` hiện nguyên văn giữa đề. */
  function texTabular(spec, body) {
    var cols = [];
    /* `p{3cm}` là MỘT cột, không phải bốn ký tự — phải thay nó bằng một ký tự
       đại diện trước khi đếm, nếu không số cột sai và bảng lệch. */
    var s = spec.replace(/p\{[^}]*\}/g, 'l').replace(/\|[^lcrp|]*/g, '');
    for (var i = 0; i < s.length; i++) {
      if ('lcr'.indexOf(s[i]) >= 0) cols.push(s[i]);
    }
    var html = '<table class="tex-table">';
    body.split(/\\\\/).forEach(function (row) {
      var rule = /\\hline/.test(row);
      row = row.replace(/\\hline/g, '').trim();
      if (!row) {
        if (rule) html += '<tr class="tex-rule"><td colspan="' + Math.max(cols.length, 1) + '"></td></tr>';
        return;
      }
      html += '<tr>';
      row.split('&').forEach(function (cell, i) {
        var cls = cols[i] === 'r' ? ' class="ta-r"' : (cols[i] === 'c' ? ' class="ta-c"' : '');
        html += '<td' + cls + '>' + texCellHtml(cell) + '</td>';
      });
      html += '</tr>';
    });
    return html + '</table>';
  }

  function texToHtml(src) {
    if (!src) return '';
    var text = String(src).replace(/\r\n?/g, '\n');

    /* Cổng an toàn — xem chú thích ở `texLooksLikeLatex`. Văn bản không mang
       dấu hiệu LaTeX thì chỉ được thoát HTML, y như trước khi có phần này:
       giữ nguyên chữ, giữ nguyên `%`, giữ nguyên đường dẫn, và KaTeX vẫn render
       `$…$` như thường. */
    if (!texLooksLikeLatex(text)) return texEscapeHtml(text);

    var store = [];
    var out = texProtectMath(text, store);

    // 2. Chú thích. `\%` là ký tự phần trăm thật nên phải chừa ra.
    out = out.replace(/(^|[^\\])%.*$/gm, '$1');

    // 3. Phần mào đầu. Một tệp .tex hoàn chỉnh có cả chục dòng khai báo gói mà
    //    đề bài không cần — và chúng chính là thứ chiếm chỗ trong khung xem trước.
    if (out.indexOf('\\begin{document}') !== -1) {
      out = out.slice(out.indexOf('\\begin{document}') + '\\begin{document}'.length);
    }
    out = out.replace(/\\end\{document\}[\s\S]*$/, '');
    out = out.replace(/\\(documentclass|usepackage|RequirePackage)(\[[^\]]*\])?\{[^}]*\}/g, '');
    out = out.replace(/\\(input|include)\{[^}]*\}/g, '');

    // 4. Dấu `&` thật của LaTeX (`\&`) -> ký tự đánh dấu riêng.
    /* Phải làm ở đây: sau bước thoát HTML thì `\&` và dấu `&` ngăn cách ô của
       bảng đều là `&amp;`, không còn phân biệt được nữa. */
    out = out.replace(/\\&/g, TEX_AMP);

    // 5. Ký tự LaTeX -> ký tự thật
    out = texUnescapeChars(out);

    // 6. Bảng. Phải chạy TRƯỚC bước thoát HTML, vì bước đó biến dấu `&` ngăn
    //    cách ô thành `&amp;` và việc tách ô sẽ sai. Bảng dựng ra được cất vào
    //    `store` nên bước thoát HTML không đụng tới nó.
    /* Spec của `tabular` có thể chứa ngoặc lồng: `{|p{3cm}|r|}`. Dùng `[^}]*`
       thì nó dừng ngay ở dấu `}` của `{3cm}` và phần còn lại của spec trôi vào
       thân bảng — số cột sai, cả bảng lệch. Cho phép đúng một mức ngoặc lồng là
       đủ cho mọi spec thật gặp trong đề của trường. */
    out = texProtectHtml(out, store,
      /\\begin\{tabular\}\{((?:[^{}]|\{[^{}]*\})*)\}([\s\S]*?)\\end\{tabular\}/g,
      function (_m, spec, body) { return texTabular(spec, body); });

    // 6b. Phần `&` thật còn lại (ngoài bảng) trở về ký tự `&` để bước sau thoát.
    out = out.split(TEX_AMP).join('&');

    // 7. Thoát HTML
    out = texEscapeHtml(out);

    // 8. Các môi trường còn lại
    /* `verbatim` chỉ bỏ dấu xuống dòng ở hai đầu khối, không `trim()` cả khối:
       thụt đầu dòng trong khối mã là thứ có nghĩa, cắt đi là làm sai nội dung.
       Hai dấu xuống dòng đó chỉ là hệ quả của việc `\begin{verbatim}` và
       `\end{verbatim}` được viết trên dòng riêng — để nguyên thì khối mã có thêm
       một dòng trống ở đầu và một ở cuối. */
    out = out.replace(/\\begin\{verbatim\}([\s\S]*?)\\end\{verbatim\}/g,
      function (_m, body) {
        return '<pre class="tex-pre">' + body.replace(/^\n/, '').replace(/\n$/, '') + '</pre>';
      });
    out = out.replace(/\\begin\{(itemize|enumerate)\}([\s\S]*?)\\end\{\1\}/g,
      function (_m, env, body) {
        var tag = env === 'enumerate' ? 'ol' : 'ul';
        var items = body.split(/\\item\b/).slice(1);
        if (!items.length) items = [body];
        return '<' + tag + ' class="tex-list">' + items.map(function (t) {
          return '<li>' + t.trim() + '</li>';
        }).join('') + '</' + tag + '>';
      });
    /* `trim()` ở đây là bắt buộc, không phải cho gọn: trong tệp .tex, `\begin{center}`
       luôn được viết trên dòng riêng, nên thân khối luôn mở đầu và kết thúc bằng
       một dấu xuống dòng. Khung hiển thị đặt `white-space: pre-wrap`, nên hai dấu
       đó hiện ra thành hai dòng trống — mỗi khối căn giữa lại đội thêm một
       khoảng trắng không ai muốn. */
    out = out.replace(/\\begin\{(center|flushleft|flushright)\}([\s\S]*?)\\end\{\1\}/g,
      function (_m, env, body) { return '<div class="tex-' + env + '">' + body.trim() + '</div>'; });
    // Môi trường không nhận ra: bỏ vỏ, giữ ruột. Thà hiện nội dung còn hơn hiện
    // nguyên dòng `\begin{figure}` giữa đề bài.
    out = out.replace(/\\(begin|end)\{[^}]*\}/g, '');

    // 8b. Tiêu đề mục
    out = out.replace(/\\(section|subsection|subsubsection)\*?\{([\s\S]*?)\}/g,
      function (_m, lvl, body) {
        var tag = lvl === 'section' ? 'h3' : (lvl === 'subsection' ? 'h4' : 'h5');
        return '<' + tag + ' class="tex-head">' + body + '</' + tag + '>';
      });

    // 8c. Lệnh định dạng chữ. Lặp vài lượt để xử lý được lồng nhau
    //     (`\textbf{\textit{…}}`) mà không cần bộ phân tích cú pháp thật.
    var pairs = [
      [/\\textbf\{([^{}]*)\}/g, '<strong>$1</strong>'],
      [/\\textit\{([^{}]*)\}/g, '<em>$1</em>'],
      [/\\emph\{([^{}]*)\}/g, '<em>$1</em>'],
      [/\\underline\{([^{}]*)\}/g, '<u>$1</u>'],
      [/\\texttt\{([^{}]*)\}/g, '<code>$1</code>'],
      [/\\text\{([^{}]*)\}/g, '$1'],
      [/\\textnormal\{([^{}]*)\}/g, '$1']
    ];
    for (var pass = 0; pass < 3; pass++) {
      pairs.forEach(function (p) { out = out.replace(p[0], p[1]); });
    }

    // 8d. Lệnh còn lại
    out = out.replace(/\\(newline|linebreak)\b/g, '<br>')
             .replace(/\\\\/g, '<br>')
             .replace(/\\par\b/g, '<br><br>')
             .replace(/\\(noindent|centering|smallskip|medskip|bigskip|hfill|clearpage|newpage)\b/g, '')
             .replace(/\\(vspace|hspace|vskip|hskip)\*?\{[^}]*\}/g, '')
             .replace(/\\(label|ref|cite|includegraphics|bibliography)\*?(\[[^\]]*\])?\{[^}]*\}/g, '')
             .replace(/\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^{}]*\})?/g, '')   // lệnh lạ: bỏ
             .replace(/~+/g, '&nbsp;')
             .replace(/---/g, '&mdash;')
             .replace(/--/g, '&ndash;');

    // 9. Trả toán và bảng về chỗ cũ
    return texRestoreMath(out, store);
  }

  /* Đổi một lần cho mỗi phần tử. Đánh dấu để lần gọi sau không xử lý lại chính
     phần HTML vừa sinh ra — `\begin` đã bị đổi thành thẻ, nhưng nếu chạy lần hai
     thì mọi thứ nằm trong `<` `>` lại bị thoát HTML và hiện ra thành mã. */
  function renderLatex(root) {
    var targets = (root || document).querySelectorAll('[data-math]');
    Array.prototype.forEach.call(targets, function (el) {
      if (el.getAttribute('data-tex-done')) return;
      el.setAttribute('data-tex-done', '1');
      el.innerHTML = texToHtml(el.textContent);
    });
    return targets.length;
  }

  function renderMath(root) {
    if (!window.renderMathInElement) return 0;   // KaTeX chưa nạp xong
    var targets = (root || document).querySelectorAll('[data-math]');
    Array.prototype.forEach.call(targets, function (el) {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '\\[', right: '\\]', display: true },
          { left: '$', right: '$', display: false },
          { left: '\\(', right: '\\)', display: false }
        ],
        /* Không đụng vào khối mã. Một đề bài hoàn toàn có thể chứa dấu `$`
           trong ví dụ C++, và nếu để KaTeX nuốt thì nó ăn mất cả đoạn giữa hai
           dấu đó — lỗi im lặng, chỉ thấy là đoạn văn biến mất. */
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
        /* Đừng ném lỗi ra ngoài: một công thức gõ sai chỉ nên hiện đỏ tại chỗ,
           không được làm hỏng cả trang. */
        throwOnError: false,
        errorColor: '#d9534f'
      });
    });
    return targets.length;
  }

  function initMath() {
    var run = function () {
      renderLatex(document);
      renderMath(document);
    };
    if (window.renderMathInElement) {
      run();
      return;
    }
    /* KaTeX nạp bằng `defer`, mà tệp này là script thường ở cuối <body> nên
       chạy TRƯỚC nó. `load` là mốc muộn nhất và chắc chắn KaTeX đã có mặt. */
    window.addEventListener('load', run);
  }

  /* ---------- 41. Thanh chèn LaTeX ----------

     Mỗi nút mang một mẫu trong `data-tex`, dùng `@` để đánh dấu chỗ con trỏ dừng
     lại — và cũng là chỗ vùng đang bôi đen được đặt vào. Nhờ vậy cùng một cơ chế
     phục vụ cả hai việc: bấm nút để chèn ký hiệu, và bôi đen rồi bấm nút để bọc
     ký hiệu quanh phần đã chọn.

     Vì sao là `@` chứ không phải `%s`: mẫu `\text{@}` nằm trong một template
     Jinja, và `%s` sẽ thành `{%s}` — mà `{%` chính là cú pháp mở khối của Jinja.
     Jinja sẽ cố phân tích nó thành một câu lệnh và làm vỡ cả trang. `@` không
     xuất hiện trong LaTeX thông thường nên không đụng ai. */
  function latexApply(ta, tpl) {
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    var sel = ta.value.slice(start, end);
    var at = tpl.indexOf('@');
    var text = at === -1 ? tpl : tpl.replace('@', sel);

    ta.focus();
    if (typeof ta.setRangeText === 'function') {
      ta.setRangeText(text, start, end, 'end');
    } else {
      ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    }
    var caret = start + (at === -1 ? text.length : at);
    ta.setSelectionRange(caret, caret + sel.length);
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function updateLatexPreview(ta) {
    var sel = ta.getAttribute('data-latex-preview');
    if (!sel) return;
    var box = document.querySelector(sel);
    if (!box) return;
    var body = box.querySelector('[data-latex-preview-body]') || box;
    /* Nội dung đi qua `texToHtml`, không đổ thẳng `ta.value` vào `innerHTML`.
       Đây là điểm quan trọng: `texToHtml` **thoát HTML trước rồi mới dựng thẻ**,
       nên phần chữ do giáo viên gõ không thể chèn thẻ vào trang. Đổ thẳng
       `innerHTML = ta.value` mới là lỗ hổng — và nó cũng không cho ra bản xem
       trước có nghĩa, vì `\subsection*{…}` vẫn hiện nguyên văn. */
    body.removeAttribute('data-tex-done');
    body.innerHTML = texToHtml(ta.value);
    renderMath(box);
  }

  function initLatexBar() {
    var areas = document.querySelectorAll('textarea[data-latex]');
    if (!areas.length) return;

    Array.prototype.forEach.call(areas, function (ta) {
      var bar = ta.id ? document.querySelector('[data-latex-bar="' + ta.id + '"]') : null;
      if (bar) {
        bar.addEventListener('click', function (ev) {
          var btn = ev.target.closest ? ev.target.closest('[data-tex]') : null;
          if (!btn || !bar.contains(btn)) return;
          ev.preventDefault();
          latexApply(ta, btn.getAttribute('data-tex'));
          updateLatexPreview(ta);
        });
      }

      /* Hẹn giờ chứ không vẽ ngay từng phím: mỗi lần KaTeX dựng lại cả khối là
         một lần phân tích cú pháp, và gõ nhanh thì việc đó làm giật ô soạn. */
      var timer = null;
      ta.addEventListener('input', function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () { updateLatexPreview(ta); }, 220);
      });
      updateLatexPreview(ta);
    });
  }

  /* Đặt tên morph ngay lập tức, không đợi DOMContentLoaded.

     Với chuyển cảnh giữa hai trang, trình duyệt chụp ảnh trang mới ở lần vẽ
     đầu tiên. Nếu tên được đặt sau đó thì ảnh chụp đã lấy xong và phần tử không
     bay được. Tệp này nằm ở cuối <body> nên mọi phần tử trong trang đều đã có
     mặt; chỉ chờ tới DOMContentLoaded khi tệp được nạp từ <head>. */
  if (document.body) {
    initMorphNames();
  } else {
    document.addEventListener('DOMContentLoaded', initMorphNames);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
