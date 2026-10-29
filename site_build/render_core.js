/* ============================================================
 * render_core.js —— 轻量 Markdown 渲染 + 语法高亮（纯函数，无 DOM 依赖）
 * 针对本项目 32 篇文档的实际特性裁剪：
 *   标题 / 段落 / 嵌套列表 / 表格 / 代码块 / 引用 / 分隔线 / 任务列表
 *   行内代码 / 加粗 / 链接
 * ============================================================ */

var MD = (function () {
  'use strict';

  /* ---------------- 1. 语法高亮 ---------------- */

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var LANG_MAP = {
    python: 'py', py: 'py', python3: 'py',
    sql: 'sql', mysql: 'sql', psql: 'sql', plsql: 'sql',
    bash: 'sh', sh: 'sh', shell: 'sh', console: 'sh', zsh: 'sh', cmd: 'sh',
    powershell: 'sh', ps1: 'sh', pwsh: 'sh',
    json: 'json', jsonc: 'json',
    yaml: 'yaml', yml: 'yaml',
    js: 'js', javascript: 'js', ts: 'js', typescript: 'js', tsx: 'js', jsx: 'js',
    java: 'java', groovy: 'java', kotlin: 'java', scala: 'java',
    xml: 'xml', html: 'xml', xhtml: 'xml', vue: 'xml',
    docker: 'docker', dockerfile: 'docker',
    ini: 'ini', conf: 'ini', toml: 'ini', properties: 'ini', env: 'ini',
    gitignore: 'ini', nginx: 'ini', makefile: 'ini', dotenv: 'ini', cfg: 'ini',
    text: 'text', markdown: 'text', md: 'text', plaintext: 'text', log: 'text'
  };

  var KEYWORDS = {
    py: ('def class return if elif else for while try except finally with as import from ' +
      'raise yield lambda assert pass break continue in is not and or None True False ' +
      'async await global nonlocal del print len range str int float list dict ' +
      'set tuple bool open type isinstance').split(' '),
    sql: ('SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE INDEX ' +
      'PRIMARY KEY UNIQUE NOT NULL DEFAULT JOIN INNER LEFT RIGHT OUTER ON GROUP BY ' +
      'ORDER HAVING LIMIT OFFSET AS AND OR NOT IN IS BETWEEN LIKE DESC ASC COUNT SUM ' +
      'AVG MAX MIN DISTINCT ALTER ADD DROP EXISTS CASE WHEN THEN ELSE END UNION ' +
      'EXPLAIN SHOW DATABASES TABLES VIEW ENGINE CHARSET CONSTRAINT FOREIGN REFERENCES ' +
      'BEGIN COMMIT ROLLBACK TRANSACTION START').split(' '),
    sh: ('if then else elif fi for while do done case esac function return export ' +
      'local echo cd ls cat grep awk sed tail head curl docker git pytest pip python ' +
      'sudo chmod chown mkdir rm cp mv find ps top df du free ss netstat ping ' +
      'systemctl service kill nohup source set unset').split(' '),
    yaml: 'true false null yes no on off'.split(' '),
    json: 'true false null'.split(' '),
    js: ('function return if else for while const let var import export from default ' +
      'class extends new this async await try catch finally throw typeof instanceof ' +
      'true false null undefined').split(' '),
    java: ('public private protected class interface extends implements static final ' +
      'void int long double float boolean String new return if else for while try ' +
      'catch finally throw throws import package true false null this super').split(' '),
    docker: ('FROM RUN CMD ENTRYPOINT COPY ADD ENV ARG WORKDIR EXPOSE VOLUME USER ' +
      'HEALTHCHECK LABEL AS').split(' '),
    ini: 'true false yes no on off'.split(' '),
    xml: [],
    text: [],
    default: ('true false null None import from def class return function const let var ' +
      'if else for while').split(' ')
  };

  var KW_CACHE = {};

  function kwRegex(lang) {
    if (lang in KW_CACHE) return KW_CACHE[lang];
    var words = KEYWORDS[lang] || KEYWORDS.default;
    var re = null;
    if (words.length) {
      var ci = (lang === 'sql');
      re = new RegExp('\\b(?:' + words.join('|') + ')\\b', ci ? 'gi' : 'g');
    }
    KW_CACHE[lang] = re;
    return re;
  }

  function normLang(raw) {
    var l = String(raw || '').toLowerCase().trim();
    if (l === '' || l === 'code') return 'default';
    return LANG_MAP[l] || 'default';
  }

  var STRING_RE = /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/g;
  var STRING_SQL = /'(?:[^']|'')*'/g;
  var COMMENT_RE = {
    sql: /--[^\n]*/g,
    ini: /#[^\n]*/g,
    docker: /#[^\n]*/g,
    default: /#[^\n]*/g,
    sh: /#[^\n]*/g,
    py: /#[^\n]*/g,
    yaml: /#[^\n]*/g,
    js: /\/\/[^\n]*/g,
    java: /\/\/[^\n]*/g,
    json: null,
    xml: null
  };

  /**
   * highlight(code, lang) -> HTML
   * 关键顺序：先在【原文】上把 token 换成占位符（占位符用字母编码，
   * 避免被数字正则二次匹配），最后统一 esc + 还原。
   */
  function encodeIdx(n) {
    var s = '';
    do {
      s = String.fromCharCode(97 + (n % 26)) + s;
      n = Math.floor(n / 26);
    } while (n > 0);
    return s;
  }

  function decodeIdx(s) {
    var n = 0;
    for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 97);
    return n;
  }

  function highlight(code, lang) {
    var l = normLang(lang);
    if (l === 'text') return esc(code);

    var s = String(code);            // 注意：这里不 esc
    var store = [];
    function keep(html) {
      store.push(html);
      return '\u0000' + encodeIdx(store.length - 1) + '\u0000';
    }

    var cre = COMMENT_RE[l];
    if (cre) {
      s = s.replace(cre, function (m) { return keep('<span class="tok-c">' + esc(m) + '</span>'); });
    }

    var sre = (l === 'sql') ? STRING_SQL : STRING_RE;
    s = s.replace(sre, function (m) { return keep('<span class="tok-s">' + esc(m) + '</span>'); });

    s = s.replace(/\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b/g,
      function (m) { return keep('<span class="tok-n">' + esc(m) + '</span>'); });

    var kre = kwRegex(l);
    if (kre) {
      s = s.replace(kre, function (m) { return keep('<span class="tok-k">' + esc(m) + '</span>'); });
    }

    s = esc(s);                       // 剩余纯文本统一转义（占位符不含特殊字符，安全）

    for (var pass = 0; pass < 4; pass++) {
      if (s.indexOf('\u0000') === -1) break;
      s = s.replace(/\u0000([a-z]+)\u0000/g, function (_, code2) {
        return store[decodeIdx(code2)];
      });
    }
    return s;
  }

  /* ---------------- 2. 行内元素 ---------------- */

  function inline(text) {
    var s = String(text);
    var codes = [];
    s = s.replace(/`([^`\n]+)`/g, function (_, c) {
      codes.push('<code class="ic">' + esc(c) + '</code>');
      return '\u0001' + (codes.length - 1) + '\u0001';
    });
    s = esc(s);
    // 图片（必须放在链接之前，否则 ![alt](src) 会被当成 [alt](src)）
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (_, alt, src) {
      return '<img alt="' + alt + '" src="' + src + '" loading="lazy" decoding="async">';
    });
    s = s.replace(/\*\*([^\n*]+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (_, t, u) {
      return '<a href="' + u + '" target="_blank" rel="noopener">' + t + '</a>';
    });
    s = s.replace(/\u0001(\d+)\u0001/g, function (_, i) { return codes[+i]; });
    return s;
  }

  /* ---------------- 3. 块级解析 ---------------- */

  var HR_RE = /^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$/;
  var HEAD_RE = /^(#{1,6})\s+(.*)$/;
  var UL_RE = /^(\s*)([-*+])\s+(.*)$/;
  var OL_RE = /^(\s*)(\d+)\.\s+(.*)$/;
  var TABLE_SEP_RE = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function splitRow(row) {
    var r = row.trim();
    if (r.charAt(0) === '|') r = r.slice(1);
    if (r.charAt(r.length - 1) === '|') r = r.slice(0, -1);
    return r.split('|').map(function (c) { return c.trim(); });
  }

  function isTableStart(lines, i) {
    if (i + 1 >= lines.length) return false;
    if (lines[i].indexOf('|') === -1) return false;
    return TABLE_SEP_RE.test(lines[i + 1]);
  }

  function indentOf(s) {
    return s.replace(/\t/g, '    ').length - s.replace(/\t/g, '    ').replace(/^\s+/, '').length;
  }

  /* 列表：先收集块 -> 建树 -> 渲染 */
  function renderListBlock(blockLines) {
    var nodes = [];
    for (var i = 0; i < blockLines.length; i++) {
      var line = blockLines[i];
      var mu = line.match(UL_RE);
      var mo = mu ? null : line.match(OL_RE);
      var m = mu || mo;
      if (m) {
        var text = m[3];
        var box = '';
        var tm = text.match(/^\[( |x|X)\]\s+([\s\S]*)$/);
        if (tm) {
          box = tm[1].toLowerCase() === 'x';
          text = tm[2];
        }
        nodes.push({
          indent: indentOf(line),
          ordered: !!mo,
          text: text,
          checked: box === '' ? null : box
        });
      } else if (nodes.length) {
        nodes[nodes.length - 1].text += ' ' + line.trim();
      }
    }
    if (!nodes.length) return '';

    function buildTree(idx, indent) {
      var list = { ordered: nodes[idx].ordered, items: [] };
      while (idx < nodes.length && nodes[idx].indent >= indent) {
        if (nodes[idx].indent === indent) {
          list.items.push({
            text: nodes[idx].text,
            checked: nodes[idx].checked,
            children: null
          });
          idx++;
        } else {
          var sub = buildTree(idx, nodes[idx].indent);
          if (list.items.length) {
            list.items[list.items.length - 1].children = sub.tree;
          }
          idx = sub.idx;
        }
      }
      return { tree: list, idx: idx };
    }

    function renderTree(list) {
      var tag = list.ordered ? 'ol' : 'ul';
      return '<' + tag + '>' + list.items.map(function (it) {
        var box = '';
        if (it.checked !== null && it.checked !== undefined) {
          box = '<input type="checkbox" disabled' + (it.checked ? ' checked' : '') + '> ';
        }
        return '<li>' + box + inline(it.text) +
          (it.children ? renderTree(it.children) : '') + '</li>';
      }).join('') + '</' + tag + '>';
    }

    var built = buildTree(0, nodes[0].indent);
    return renderTree(built.tree);
  }

  /**
   * render(md) -> { html, headings }
   */
  function render(md) {
    var lines = String(md).replace(/\r\n/g, '\n').split('\n');
    var out = [];
    var headings = [];
    var slugCount = {};
    var i = 0;

    function slug(text) {
      var base = text.toLowerCase()
        .replace(/[`*_~\[\]()]/g, '')
        .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60) || 'h';
      slugCount[base] = (slugCount[base] || 0) + 1;
      return slugCount[base] > 1 ? base + '-' + slugCount[base] : base;
    }

    while (i < lines.length) {
      var line = lines[i];

      /* 代码块（支持 3 个及以上反引号，外层可包裹内层围栏） */
      var fence = line.match(/^\s*(`{3,})([^\s`]*)\s*$/);
      if (fence) {
        var tickLen = fence[1].length;
        var lang = fence[2] || 'code';
        var closeRe = new RegExp('^\\s*`{' + tickLen + ',}\\s*$');
        var buf = [];
        i++;
        while (i < lines.length && !closeRe.test(lines[i])) {
          buf.push(lines[i]);
          i++;
        }
        i++;
        out.push(
          '<div class="code-wrap" data-lang="' + esc(lang) + '">' +
            '<div class="code-head">' +
              '<span class="dots"><i class="d1"></i><i class="d2"></i><i class="d3"></i></span>' +
              '<span class="lang">' + esc(lang) + '</span>' +
              '<button class="copy-btn" type="button">复制</button>' +
            '</div>' +
            '<pre class="code-body"><code>' + highlight(buf.join('\n'), lang) + '</code></pre>' +
          '</div>'
        );
        continue;
      }
      if (!line.trim()) { i++; continue; }
      if (HR_RE.test(line)) { out.push('<hr>'); i++; continue; }

      /* 标题 */
      var h = line.match(HEAD_RE);
      if (h) {
        var level = h[1].length;
        var text = h[2].trim();
        var id = slug(text);
        headings.push({ level: level, id: id, text: text });
        out.push('<h' + level + ' id="' + id + '">' + inline(text) +
          '<a class="anchor" href="javascript:void(0)" data-anchor="' + id +
          '" aria-hidden="true">#</a></h' + level + '>');
        i++;
        continue;
      }

      /* 表格 */
      if (isTableStart(lines, i)) {
        var header = splitRow(lines[i]);
        i += 2;
        var rows = [];
        while (i < lines.length && lines[i].indexOf('|') !== -1 && lines[i].trim()) {
          rows.push(splitRow(lines[i]));
          i++;
        }
        var thead = '<thead><tr>' + header.map(function (c) {
          return '<th>' + inline(c) + '</th>';
        }).join('') + '</tr></thead>';
        var tbody = '<tbody>' + rows.map(function (r) {
          var tds = '';
          for (var k = 0; k < header.length; k++) {
            tds += '<td>' + inline(r[k] === undefined ? '' : r[k]) + '</td>';
          }
          return '<tr>' + tds + '</tr>';
        }).join('') + '</tbody>';
        out.push('<div class="table-wrap"><table>' + thead + tbody + '</table></div>');
        continue;
      }

      /* 引用 */
      if (/^\s*>/.test(line)) {
        var qbuf = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          qbuf.push(lines[i].replace(/^\s*>\s?/, ''));
          i++;
        }
        out.push('<blockquote>' + render(qbuf.join('\n')).html + '</blockquote>');
        continue;
      }

      /* 列表 */
      if (UL_RE.test(line) || OL_RE.test(line)) {
        var block = [];
        var headOrdered = !!line.match(OL_RE);
        while (i < lines.length) {
          var cur = lines[i];
          if (UL_RE.test(cur) || OL_RE.test(cur)) {
            block.push(cur); i++; continue;
          }
          if (!cur.trim()) {
            // 空行后：同类型列表才继续，类型变化则断开
            var j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && (UL_RE.test(lines[j]) || OL_RE.test(lines[j])) &&
              (!!lines[j].match(OL_RE)) === headOrdered) {
              i = j; continue;
            }
            break;
          }
          if (/^\s{2,}\S/.test(cur)) { block.push(cur); i++; continue; }
          break;
        }
        out.push(renderListBlock(block));
        continue;
      }

      /* 段落 */
      var pbuf = [line.trim()];
      i++;
      while (i < lines.length) {
        var nxt = lines[i];
        if (!nxt.trim()) break;
        if (/^\s*```/.test(nxt) || HEAD_RE.test(nxt) || HR_RE.test(nxt) ||
          /^\s*>/.test(nxt) || UL_RE.test(nxt) || OL_RE.test(nxt) ||
          isTableStart(lines, i)) break;
        pbuf.push(nxt.trim());
        i++;
      }
      out.push('<p>' + inline(pbuf.join(' ')) + '</p>');
    }

    return { html: out.join('\n'), headings: headings };
  }

  return {
    render: render,
    highlight: highlight,
    inline: inline,
    esc: esc,
    normLang: normLang
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = MD;
}
