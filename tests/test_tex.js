/* Kiểm tra phần LaTeX của app.js bằng cách trích thẳng source thật.

   Vì sao trích chứ không chép lại: chép lại thì bài kiểm tra và mã đang chạy là
   hai bản khác nhau, và bản kiểm tra sẽ mãi mãi xanh trong khi trang thật hỏng.
   Ở đây cắt đúng đoạn giữa `var TEX_MARK` và `function renderLatex`, nên thứ
   được kiểm chính là thứ trình duyệt sẽ chạy.

   Chạy:  node tests/test_tex.js
*/
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', 'demo', 'assets', 'js', 'app.js');
const src = fs.readFileSync(SRC, 'utf8');

const from = src.indexOf('var TEX_MARK');
const to = src.indexOf('/* Đổi một lần cho mỗi phần tử');
if (from < 0 || to < 0 || to <= from) {
  console.error('Khong cat duoc doan LaTeX trong app.js — moc da doi.');
  process.exit(2);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(src.slice(from, to) + '\nthis.texToHtml = texToHtml; this.texLooksLikeLatex = texLooksLikeLatex;', sandbox);
const { texToHtml, texLooksLikeLatex } = sandbox;

let pass = 0, fail = 0;
function check(name, got, want) {
  if (got === want) { pass++; return; }
  fail++;
  console.log('FAIL  ' + name);
  console.log('   mong doi: ' + JSON.stringify(want));
  console.log('   nhan duoc: ' + JSON.stringify(got));
}
function contains(name, hay, needle) {
  if (hay.indexOf(needle) !== -1) { pass++; return; }
  fail++;
  console.log('FAIL  ' + name + '\n   phai chua: ' + JSON.stringify(needle) +
              '\n   trong     : ' + JSON.stringify(hay));
}
function missing(name, hay, needle) {
  if (hay.indexOf(needle) === -1) { pass++; return; }
  fail++;
  console.log('FAIL  ' + name + '\n   khong duoc chua: ' + JSON.stringify(needle) +
              '\n   trong          : ' + JSON.stringify(hay));
}

/* ---- 1. Cổng an toàn: văn bản thuần không được mất chữ ---------------- */

check('van ban rong', texToHtml(''), '');

// Dấu phần trăm: đây là ca nguy hiem nhat. Bước 2 của đường ống xoá từ `%` tới
// hết dòng, nên "50%" sẽ ăn mất đuôi dòng nếu cổng an toàn không chặn.
check('dau phan tram giu nguyen chu',
  texToHtml('Điểm tối đa 50% và không hơn.'),
  'Điểm tối đa 50% và không hơn.');

check('duong dan Windows giu nguyen',
  texToHtml('Lưu tệp vào C:\\Users\\an\\bai.cpp rồi nộp.'),
  'Lưu tệp vào C:\\Users\\an\\bai.cpp rồi nộp.');

// `<` `>` phải được thoát, nếu không trình duyệt ăn mất phần còn lại của đề.
check('the HTML duoc thoat',
  texToHtml('Khai báo vector<int> a; rồi dùng.'),
  'Khai báo vector&lt;int&gt; a; rồi dùng.');

check('dau & duoc thoat', texToHtml('a & b'), 'a &amp; b');

// Đề văn bản thuần có công thức: đi đường văn bản thuần, KaTeX lo phần `$…$`.
check('cong thuc trong van ban thuan giu nguyen',
  texToHtml('Với $1 \\le n \\le 10^6$ thì in ra $n$.'),
  'Với $1 \\le n \\le 10^6$ thì in ra $n$.');

check('xuong dong giu nguyen', texToHtml('dong 1\ndong 2'), 'dong 1\ndong 2');
check('CRLF ve LF', texToHtml('a\r\nb'), 'a\nb');

check('cổng an toàn: văn bản thường là false',
  texLooksLikeLatex('Đếm số nguyên tố nhỏ hơn n.'), false);
check('cổng an toàn: chỉ có toán là false',
  texLooksLikeLatex('Tính $\\frac{a}{b}$ xem.'), false);

/* ---- 2. Tệp .tex thật phải được dựng ---------------------------------- */

check('cổng an toàn: documentclass là true',
  texLooksLikeLatex('\\documentclass[12pt]{article}'), true);
check('cổng an toàn: tabular là true',
  texLooksLikeLatex('\\begin{tabular}{|c|c|}'), true);
check('cổng an toàn: section là true',
  texLooksLikeLatex('\\subsection*{Dữ liệu vào}'), true);

const texDoc = [
  '\\documentclass[12pt]{article}',
  '\\usepackage[utf8]{inputenc}',
  '% dòng chú thích này phải biến mất',
  '\\begin{document}',
  '\\section*{Yêu cầu}',
  'Đếm số nguyên tố nhỏ hơn $n$.',
  '',
  '\\subsection*{Dữ liệu vào}',
  '\\begin{itemize}',
  '\\item Dòng đầu ghi $n$ với $1 \\le n \\le 10^6$.',
  '\\item \\textbf{Lưu ý:} $n$ là số nguyên dương.',
  '\\end{itemize}',
  '',
  '\\begin{tabular}{|c|c|}',
  '\\hline',
  'Dữ liệu vào & Dữ liệu ra \\\\',
  '\\hline',
  '5 & 3 \\\\',
  '\\hline',
  '\\end{tabular}',
  '\\end{document}'
].join('\n');

const html = texToHtml(texDoc);

missing('bo documentclass', html, 'documentclass');
missing('bo usepackage', html, 'usepackage');
missing('bo begin{document}', html, 'begin{document}');
missing('bo end{document}', html, 'end{document}');
missing('bo chu thich', html, 'chú thích này');
missing('bo lenh begin/end con lai', html, '\\begin');
missing('bo \\\\ thanh the', html, '\\\\');
missing('bo \\item', html, '\\item');
contains('section thanh h3', html, '<h3 class="tex-head">Yêu cầu</h3>');
contains('subsection thanh h4', html, '<h4 class="tex-head">Dữ liệu vào</h4>');
contains('itemize thanh ul', html, '<ul class="tex-list">');
contains('textbf thanh strong', html, '<strong>Lưu ý:</strong>');
contains('tabular thanh table', html, '<table class="tex-table">');
contains('co hang ke hline', html, '<tr class="tex-rule">');
contains('toan duoc tra ve nguyen ven', html, '$1 \\le n \\le 10^6$');
contains('dau $n$ giu nguyen', html, '$n$');

/* ---- 3. `&` của LaTeX: đảo bước 4 và 5 là sai ------------------------- */

// `\&` phải ra `&` (thực thể HTML `&amp;`), KHÔNG phải `&amp;amp;`.
const amp = texToHtml('\\begin{document}\nA \\& B\n\\end{document}');
contains('\\& thanh &amp; mot lan', amp, 'A &amp; B');
missing('khong bi thoát hai lan', amp, '&amp;amp;');

/* ---- 4. `p{3cm}` là một cột, không phải bốn --------------------------- */

const pcol = texToHtml(
  '\\begin{document}\n\\begin{tabular}{|p{3cm}|r|}\n\\hline\na & b \\\\\n\\hline\n\\end{tabular}\n\\end{document}');
contains('p{3cm} dem la mot cot', pcol, '<td colspan="2">');
contains('cot r can phai', pcol, 'class="ta-r"');
missing('spec khong troi vao than bang', pcol, '3cm}|r|');

/* ---- 4b. `&` và `<` bên trong một ô không được cắt đôi ---------------- */

// Đến lúc dựng bảng thì `&` đã thành `&amp;`. Cắt thẳng theo `&` là chặt đôi
// thực thể và ô hiện ra chữ "amp;".
const ampCell = texToHtml(
  '\\begin{document}\n\\begin{tabular}{|c|c|}\n\\hline\nTom \\& Jerry & 5 \\\\\n\\hline\n\\end{tabular}\n\\end{document}');
contains('o chua & giu nguyen', ampCell, '<td class="ta-c">Tom &amp; Jerry</td>');
missing('khong sinh ra chu amp; le', ampCell, '>amp;');

const ltCell = texToHtml(
  '\\begin{document}\n\\begin{tabular}{|c|}\n\\hline\na < b \\\\\n\\hline\n\\end{tabular}\n\\end{document}');
contains('o chua < giu nguyen', ltCell, '<td class="ta-c">a &lt; b</td>');
missing('khong sinh ra chu lt; le', ltCell, '>lt;');

/* ---- 5. Lệnh lạ: bỏ vỏ, giữ ruột -------------------------------------- */

const unknown = texToHtml('\\begin{document}\n\\begin{figure}\nHình minh hoạ\n\\end{figure}\n\\end{document}');
missing('bo vo moi truong la', unknown, 'figure');
contains('giu ruot moi truong la', unknown, 'Hình minh hoạ');

/* ---- 6. Dòng trống lơ lửng trong khối căn giữa ------------------------- */

// Trong tệp .tex, `\begin{center}` luôn nằm trên dòng riêng nên thân khối luôn
// có dấu xuống dòng ở hai đầu. Khung hiển thị dùng `pre-wrap`, nên không cắt đi
// thì mỗi khối căn giữa đội thêm hai dòng trống.
const centered = texToHtml(
  '\\begin{document}\n\\begin{center}\nSÔNG LÔ\n\\end{center}\n\\end{document}');
contains('khoi can giua khong co dong trong', centered,
  '<div class="tex-center">SÔNG LÔ</div>');

// `verbatim` chỉ bỏ dấu xuống dòng đầu, giữ nguyên thụt đầu dòng của khối mã.
const verb = texToHtml(
  '\\begin{document}\n\\begin{verbatim}\n  int main() { return 0; }\n\\end{verbatim}\n\\end{document}');
contains('verbatim bo xuong dong dau', verb,
  '<pre class="tex-pre">  int main() { return 0; }</pre>');

console.log('\n' + pass + ' dat, ' + fail + ' hong');
process.exit(fail ? 1 : 0);
