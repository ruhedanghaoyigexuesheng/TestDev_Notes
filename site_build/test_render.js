const MD = require('./render_core.js');

function check(name, cond, detail) {
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '\n  -> ' + detail));
  return cond;
}

let ok = true;

// 1) 代码块 + 高亮
const md1 = [
  '## 标题一',
  '',
  '```python',
  'def fetch(url: str, timeout=10):  # 注释',
  '    r = requests.get(url, timeout=timeout)',
  '    return r.json()["code"], 200',
  '```',
  '',
  '正文段落，含 `inline code` 和 **加粗**。'
].join('\n');

const r1 = MD.render(md1);
ok &= check('代码块生成 code-wrap', r1.html.includes('class="code-wrap"'), r1.html.slice(0, 300));
ok &= check('代码块带语言标签', r1.html.includes('class="lang">python<'), r1.html);
ok &= check('代码块带复制按钮', r1.html.includes('class="copy-btn"'), r1.html);
ok &= check('关键字高亮 def', r1.html.includes('<span class="tok-k">def</span>'), r1.html);
ok &= check('字符串高亮', r1.html.includes('tok-s'), r1.html);
ok &= check('注释高亮', r1.html.includes('tok-c'), r1.html);
ok &= check('数字高亮', r1.html.includes('tok-n'), r1.html);
ok &= check('标题生成 h2 + 锚点', /<h2 id="[^"]+">标题一<a class="anchor"/.test(r1.html), r1.html);
ok &= check('headings 收集', r1.headings.length === 1 && r1.headings[0].level === 2, JSON.stringify(r1.headings));
ok &= check('行内代码', r1.html.includes('<code class="ic">inline code</code>'), r1.html);
ok &= check('加粗', r1.html.includes('<strong>加粗</strong>'), r1.html);

// 2) 表格
const md2 = [
  '| 列A | 列B |',
  '| --- | --- |',
  '| 1 | `x` |',
  '| 2 | **y** |'
].join('\n');
const r2 = MD.render(md2);
ok &= check('表格生成', r2.html.includes('<table>') && r2.html.includes('<th>列A</th>'), r2.html);
ok &= check('表格行数', (r2.html.match(/<tr>/g) || []).length === 3, r2.html);

// 3) 嵌套列表
const md3 = [
  '- 一级 A',
  '  - 二级 A1',
  '  - 二级 A2',
  '- 一级 B',
  '',
  '1. 有序一',
  '2. 有序二'
].join('\n');
const r3 = MD.render(md3);
ok &= check('嵌套 ul', /<ul><li>一级 A<ul><li>二级 A1<\/li><li>二级 A2<\/li><\/ul><\/li><li>一级 B<\/li><\/ul>/.test(r3.html), r3.html);
ok &= check('有序 ol', r3.html.includes('<ol><li>有序一</li><li>有序二</li></ol>'), r3.html);

// 4) 任务列表
const r4 = MD.render('- [ ] 待办\n- [x] 已完成');
ok &= check('任务列表', r4.html.includes('type="checkbox"') && r4.html.includes('checked'), r4.html);

// 5) 引用 + 分隔线
const r5 = MD.render('> 引用一行\n> 引用两行\n\n---\n');
ok &= check('引用', r5.html.includes('<blockquote>'), r5.html);
ok &= check('分隔线', r5.html.includes('<hr>'), r5.html);

// 6) HTML 转义（防注入）
const r6 = MD.render('段落里有 <script>alert(1)</script>');
ok &= check('HTML 转义', !r6.html.includes('<script>') && r6.html.includes('&lt;script&gt;'), r6.html);

// 7) SQL 高亮大小写
const r7 = MD.render('```sql\nSELECT id FROM users WHERE id = 1; -- note\n```');
ok &= check('SQL 关键字大写', r7.html.includes('tok-k">SELECT<'), r7.html);
ok &= check('SQL 注释 --', r7.html.includes('tok-c'), r7.html);

// 8) 真实文档抽样
const fs = require('fs');
const real = fs.readFileSync('../测试开发-计算机网络篇.md', 'utf8');
const rr = MD.render(real);
ok &= check('真实文档：标题数 > 10', rr.headings.length > 10, 'headings=' + rr.headings.length);
ok &= check('真实文档：表格 > 5', (rr.html.match(/<table>/g) || []).length > 5,
  'tables=' + (rr.html.match(/<table>/g) || []).length);
ok &= check('真实文档：代码块 > 10', (rr.html.match(/code-wrap/g) || []).length > 10,
  'codes=' + (rr.html.match(/code-wrap/g) || []).length);
ok &= check('真实文档：无残留围栏', !rr.html.includes('```'), '残留 ```');
ok &= check('真实文档：无残留表格分隔符', !/\|\s*-{3,}\s*\|/.test(rr.html), '残留表格分隔');

console.log('\n结果: ' + (ok ? 'ALL PASS' : '有失败'));
process.exit(ok ? 0 : 1);
