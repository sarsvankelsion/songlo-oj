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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
