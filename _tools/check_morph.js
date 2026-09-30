/* Kiểm tra các tên morph trong DOM đã render.
 *
 * Vì sao cần: trình duyệt huỷ TOÀN BỘ hiệu ứng chuyển cảnh khi gặp hai phần tử
 * cùng một view-transition-name trong một trang, và nó chỉ ghi một dòng vào
 * console. Kiểm tra bằng mắt trên giao diện không phát hiện được — trang vẫn
 * hiện bình thường, chỉ mất hiệu ứng. Script này đọc DOM sau khi JavaScript đã
 * chạy và xác nhận ba điều:
 *
 *   1. mọi phần tử mang `data-morph` đều đã được gán `view-transition-name`;
 *   2. không có tên nào xuất hiện hai lần;
 *   3. các tên đều có dạng `<loại>-<định danh>`.
 *
 * Chạy:
 *   node _tools/check_morph.js _shots/dom_leaderboard.html ...
 */

const fs = require('fs');

const files = process.argv.slice(2);
if (!files.length) {
  console.error('Cần ít nhất một tệp DOM đã render.');
  process.exit(2);
}

let problems = 0;

for (const file of files) {
  let html;
  try {
    html = fs.readFileSync(file, 'utf8');
  } catch (err) {
    console.error(`Không đọc được ${file}: ${err.message}`);
    problems++;
    continue;
  }

  const assigned = [...html.matchAll(/view-transition-name:\s*([^;"]+)/g)]
    .map((m) => m[1].trim())
    .filter(Boolean);
  const declared = [...html.matchAll(/data-morph="([^"]+)"/g)].map((m) => m[1]);

  const counts = new Map();
  for (const name of assigned) counts.set(name, (counts.get(name) || 0) + 1);

  const duplicates = [...counts.entries()].filter(([, n]) => n > 1);
  const unassigned = declared.filter((name) => !assigned.includes(name));
  const malformed = assigned.filter((name) => !/^[a-z][a-z0-9-]*-[A-Za-z0-9]+$/.test(name));

  const label = file.replace(/^.*[\\/]/, '');
  console.log(
    `${label.padEnd(24)} khai báo ${String(declared.length).padStart(3)}` +
    ` | đã gán ${String(assigned.length).padStart(3)}` +
    ` | tên duy nhất ${String(counts.size).padStart(3)}` +
    ` | trùng ${duplicates.length}` +
    ` | chưa gán ${unassigned.length}`
  );

  if (duplicates.length) {
    console.log(`   TRÙNG: ${duplicates.map(([n, c]) => `${n} ×${c}`).join(', ')}`);
    problems++;
  }
  if (unassigned.length) {
    console.log(`   CHƯA GÁN: ${unassigned.slice(0, 6).join(', ')}`);
    problems++;
  }
  if (malformed.length) {
    console.log(`   SAI DẠNG: ${malformed.slice(0, 6).join(', ')}`);
    problems++;
  }
  if (assigned.length) {
    console.log(`   ví dụ: ${assigned.slice(0, 5).join(' · ')}`);
  }
}

console.log();
if (problems) {
  console.log(`THẤT BẠI: ${problems} vấn đề.`);
  process.exit(1);
}
console.log('Tất cả tên morph đều duy nhất, đã gán và đúng dạng.');
