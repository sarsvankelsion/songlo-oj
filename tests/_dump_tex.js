/* In ra HTML ma duong ong LaTeX sinh ra cho mot doan .tex that.
   Dung de nhin bang mat, khong phai bai kiem tra.

   Chay:  node tests/_dump_tex.js
*/
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'demo', 'assets', 'js', 'app.js'), 'utf8');
const from = src.indexOf('var TEX_MARK');
const to = src.indexOf('/* Đổi một lần cho mỗi phần tử');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(src.slice(from, to) + '\nthis.texToHtml = texToHtml;', sandbox);

// Doc doan .tex that tu chinh bai kiem tra, de hai noi khong lech nhau.
const testSrc = fs.readFileSync(path.join(__dirname, 'test_tex.js'), 'utf8');
const m = testSrc.match(/const realDoc = \[([\s\S]*?)\]\.join\('\\n'\);/);
if (!m) {
  console.error('Khong tim thay realDoc trong test_tex.js');
  process.exit(2);
}
const realDoc = eval('[' + m[1] + "]").join('\n');

console.log(sandbox.texToHtml(realDoc));
