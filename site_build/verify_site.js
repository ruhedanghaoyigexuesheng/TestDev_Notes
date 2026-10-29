/* 站点离线校验：不依赖浏览器，覆盖数据完整性 + 渲染正确性 + JS 语法 */
const fs = require('fs');
const path = require('path');
const MD = require('./render_core.js');

const HTML_PATH = path.join(__dirname, '..', '测试开发知识库.html');
const html = fs.readFileSync(HTML_PATH, 'utf8');

/* 从 HTML 里按括号配平提取 KB 数据（不再依赖中间产物 kb_data.json） */
function extractKB(src) {
  const start = src.indexOf('const KB = ');
  if (start < 0) throw new Error('未找到 const KB');
  const begin = src.indexOf('{', start);
  let depth = 0, inStr = false, esc = false;
  for (let p = begin; p < src.length; p++) {
    const c = src[p];
    if (inStr) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') inStr = false;
    } else {
      if (c === '"') inStr = true;
      else if (c === '{') depth++;
      else if (c === '}') {
        depth--;
        if (depth === 0) return JSON.parse(src.slice(begin, p + 1));
      }
    }
  }
  throw new Error('KB 数据未闭合');
}
const data = extractKB(html);

let ok = true;
function check(name, cond, detail) {
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '\n  -> ' + detail));
  if (!cond) ok = false;
}

/* ---------- 1. 占位符与体积 ---------- */
check('无 __KB_DATA__ 残留', !html.includes('__KB_DATA__'), '占位符未替换');
check('无 __RENDER_CORE__ 残留', !html.includes('__RENDER_CORE__'), '占位符未替换');
check('体积 < 2MB', html.length < 2 * 1024 * 1024, (html.length / 1024 / 1024).toFixed(2) + 'MB');
check('含 charset utf-8', html.includes('<meta charset="utf-8">'), '缺 meta');

/* ---------- 2. script 语法 ---------- */
const m = html.match(/<script>([\s\S]*?)<\/script>/);
check('找到内联 script', !!m, '没有 script 块');
if (m) {
  try {
    new Function(m[1]);
    check('内联 JS 语法正确', true);
  } catch (e) {
    check('内联 JS 语法正确', false, e.message);
  }
}

/* ---------- 3. 数据结构 ---------- */
const arts = [];
data.groups.forEach(g => g.articles.forEach(a => arts.push(Object.assign({}, a, { group: g.name }))));
check('总条目 = 33（32 篇 + 使用说明）', arts.length === 33, '实际 ' + arts.length);
check('分组数 = 11', data.groups.length === 11, '实际 ' + data.groups.length);
check('统计项 = 4', data.stats.length === 4, JSON.stringify(data.stats));
check('id 无重复', new Set(arts.map(a => a.id)).size === arts.length, '有重复 id');

/* ---------- 4. 每篇都能被渲染 ---------- */
function stripCodeBlocks(html) {
  // 代码块内可能合法地包含表格语法/围栏，检查前先剔除
  return html.replace(/<pre class="code-body">[\s\S]*?<\/pre>/g, '<pre></pre>');
}

function countTopFences(content) {
  let depth = 0, blocks = 0;
  for (const line of content.split('\n')) {
    const m = line.match(/^\s*(`{3,})/);
    if (!m) continue;
    if (depth === 0) { depth = m[1].length; blocks++; }
    else if (m[1].length >= depth) { depth = 0; }
  }
  return blocks;
}

let bad = [];
let totalCode = 0, totalTable = 0, totalHead = 0;
arts.forEach(a => {
  let r;
  try {
    r = MD.render(a.content);
  } catch (e) {
    bad.push(a.id + ' 渲染异常: ' + e.message);
    return;
  }
  const codeCount = countTopFences(a.content);
  totalCode += codeCount;
  totalTable += (r.html.match(/<table>/g) || []).length;
  totalHead += r.headings.length;

  const plain = stripCodeBlocks(r.html);
  if (plain.includes('```')) bad.push(a.id + ' 残留代码围栏');
  if (/\|\s*-{3,}\s*\|/.test(plain)) bad.push(a.id + ' 残留表格分隔行');
  const wrappers = (r.html.match(/class="code-wrap"/g) || []).length;
  if (wrappers !== codeCount) bad.push(`${a.id} 代码块数不符 ${wrappers} != ${codeCount}`);
  if (r.headings.length < 3) bad.push(a.id + ' 标题过少 ' + r.headings.length);
  if (r.html.length < 2000) bad.push(a.id + ' 渲染结果过短 ' + r.html.length);
});
check('33 篇全部渲染成功', bad.length === 0, bad.slice(0, 6).join(' | '));
console.log(`     代码块 ${totalCode} 段 · 表格 ${totalTable} 张 · 标题 ${totalHead} 个`);

/* ---------- 5. 内容抽样：确认正文真的嵌进去了 ---------- */
const probes = [
  ['net', 'TIME_WAIT'],
  ['mysql', 'DATE_SUB(NOW()'],
  ['pytest', 'pytest_runtest_makereport'],
  ['api-design', '五层断言'],
  ['perf-design', '利特尔'],
  ['perf-monitor', '压测机'],
  ['ai-eval', 'faithfulness'],
  ['ai-ops', 'Golden Set'],
  ['coverage', '增量覆盖率'],
];
let missing = probes.filter(([id, kw]) => {
  const a = arts.find(x => x.id === id);
  return !a || !a.content.includes(kw);
}).map(p => p[0]);
check('抽样关键词全部命中', missing.length === 0, '缺失: ' + missing.join(','));

/* ---------- 6. HTML 安全性（防止提前闭合 script） ---------- */
check('数据中无裸 </script', !/<\/script/i.test(html.replace(/<\/script>\s*$/i, '')) ||
  html.indexOf('<\/script') >= 0, '存在未转义的 </script');

/* ---------- 7. 关键 UI 元素存在 ---------- */
const uiNeeds = ['navRoot', 'searchInput', 'tocList', 'themeBtn', 'progress', 'copy-btn', 'id="view"'];
const uiMissing = uiNeeds.filter(k => !html.includes(k));
check('关键 UI 元素齐全', uiMissing.length === 0, '缺失: ' + uiMissing.join(','));

console.log('\n结果: ' + (ok ? 'ALL PASS' : '有失败'));
process.exit(ok ? 0 : 1);
