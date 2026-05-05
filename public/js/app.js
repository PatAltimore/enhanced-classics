/* Enhanced Classics — single-page reader */
(function () {
  'use strict';

  const main        = document.getElementById('main-content');
  const backBtn     = document.getElementById('back-btn');
  const headerTitle = document.getElementById('header-title');
  let catalog       = null;

  /* ── Routing ── */
  function route() {
    const hash  = location.hash.replace('#', '') || '/';
    const parts = hash.split('/').filter(Boolean);
    if (parts.length === 0)       showShelf();
    else if (parts.length === 1)  showChapterList(parts[0]);
    else                          showReader(parts[0], parts[1]);
  }
  window.addEventListener('hashchange', route);

  async function loadCatalog() {
    if (catalog) return catalog;
    catalog = await fetch('/catalog.json').then(r => r.json());
    return catalog;
  }

  /* ── Shelf ── */
  async function showShelf() {
    backBtn.style.display = 'none';
    headerTitle.textContent = 'Enhanced Classics';
    const cat = await loadCatalog();
    main.innerHTML = '<div id="shelf"><h2>Library</h2>' +
      cat.books.map(b =>
        '<div class="book-card" onclick="location.hash=\'#/' + b.slug + '\'">' +
        '<h3>' + b.title + '</h3>' +
        '<div class="meta">' + b.author + ' &middot; ' + b.year + '</div>' +
        '<p>' + b.description + '</p></div>'
      ).join('') + '</div>';
  }

  /* ── Chapter list ── */
  async function showChapterList(bookSlug) {
    const cat  = await loadCatalog();
    const book = cat.books.find(b => b.slug === bookSlug);
    if (!book) { showError('Book not found.'); return; }
    backBtn.style.display = 'inline-block';
    backBtn.onclick = () => { location.hash = '#/'; };
    headerTitle.textContent = book.title;
    main.innerHTML = '<div id="chapter-list"><h2>' + book.title + '</h2>' +
      '<div class="book-meta">' + book.author + ' &middot; ' + book.year + '</div>' +
      book.chapters.map(ch =>
        '<div class="chapter-item" onclick="location.hash=\'#/' + bookSlug + '/' + ch.slug + '\'">' +
        '<span class="chapter-num">' + ch.number + '</span>' +
        '<span class="chapter-title">' + ch.title + '</span></div>'
      ).join('') + '</div>';
  }

  /* ── Reader ── */
  async function showReader(bookSlug, chapterSlug) {
    main.innerHTML = '<div id="loading">Loading chapter\u2026</div>';
    backBtn.style.display = 'inline-block';
    backBtn.onclick = () => { location.hash = '#/' + bookSlug; };
    try {
      const text = await fetch('/books/' + bookSlug + '/' + chapterSlug + '.md').then(r => r.text());
      const { meta, body } = parseFrontmatter(text);
      headerTitle.textContent = meta.title + ' \u2014 ' + meta.chapter_title;
      renderReader(meta, body);
    } catch (e) {
      showError('Could not load chapter: ' + e.message);
    }
  }

  /* ── YAML frontmatter parser ── */
  function parseFrontmatter(raw) {
    const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
    if (!m) return { meta: {}, body: raw };
    return { meta: parseYaml(m[1]), body: m[2].trim() };
  }

  function parseYaml(src) {
    const lines = src.split('\n');
    let i = 0;

    function readObj(minIndent) {
      const obj = {};
      while (i < lines.length) {
        const raw     = lines[i];
        const trimmed = raw.trimStart();
        const indent  = raw.length - trimmed.length;
        if (!trimmed || trimmed[0] === '#') { i++; continue; }
        if (indent < minIndent) break;
        if (trimmed[0] === '-') break;
        const colon = trimmed.indexOf(':');
        if (colon < 0) { i++; continue; }
        const key = trimmed.slice(0, colon).trim();
        const val = trimmed.slice(colon + 1).trim();
        if (!val) {
          i++;
          if (i < lines.length) {
            const nt = lines[i].trimStart();
            const ni = lines[i].length - nt.length;
            obj[key] = nt[0] === '-' ? readArr(ni) : readObj(ni);
          }
        } else {
          obj[key] = val.replace(/^["']|["']$/g, '').replace(/\\"/g, '"');
          i++;
        }
      }
      return obj;
    }

    function readArr(minIndent) {
      const arr = [];
      while (i < lines.length) {
        const raw     = lines[i];
        const trimmed = raw.trimStart();
        const indent  = raw.length - trimmed.length;
        if (!trimmed) { i++; continue; }
        if (indent < minIndent || trimmed[0] !== '-') break;
        const item = {};
        const first = trimmed.slice(2).trim();
        if (first.includes(':')) {
          const c = first.indexOf(':');
          item[first.slice(0, c).trim()] = first.slice(c + 1).trim().replace(/^["']|["']$/g, '').replace(/\\"/g, '"');
        }
        i++;
        while (i < lines.length) {
          const r2 = lines[i], t2 = r2.trimStart(), i2 = r2.length - t2.length;
          if (!t2) { i++; continue; }
          if (i2 <= indent || t2[0] === '-') break;
          const c2 = t2.indexOf(':');
          if (c2 >= 0) item[t2.slice(0, c2).trim()] = t2.slice(c2 + 1).trim().replace(/^["']|["']$/g, '').replace(/\\"/g, '"');
          i++;
        }
        arr.push(item);
      }
      return arr;
    }

    return readObj(0);
  }

  /* ── Markdown → HTML ── */
  function mdToHtml(md, enhancements) {
    const triggerMap = {};
    (enhancements || []).forEach(e => { if (e.trigger) triggerMap[e.trigger] = e.id; });
    const triggers = Object.keys(triggerMap).sort((a, b) => b.length - a.length);

    return md.split(/\n\n+/).map(para => {
      let p = para.trim();
      if (!p) return '';
      p = p.replace(/\*\*(.+?)\*\*/g, (_, text) => {
        const t = triggers.find(tr => text.includes(tr));
        if (t) return '<span class="enhance-trigger" onclick="togglePanel(\'' + triggerMap[t] + '\')">' + text + '</span>';
        return '<strong>' + text + '</strong>';
      });
      p = p.replace(/_(.+?)_/g, (_, t) => '<em>' + t + '</em>');
      p = p.replace(/\*(.+?)\*/g, (_, t) => '<em>' + t + '</em>');
      return '<p>' + p + '</p>';
    }).join('\n');
  }

  /* ── Render reader ── */
  function renderReader(meta, body) {
    const enhancements = meta.enhancements || [];
    const summary      = meta.summary      || [];

    const panels = {};
    enhancements.forEach(e => {
      panels[e.id] =
        '<details class="enhancement-panel" id="panel-' + e.id + '">' +
        '<summary>' + e.title + '</summary>' +
        '<div class="panel-body">' +
        '<div class="panel-text"><p>' + e.content + '</p>' +
        '<div class="panel-link"><a href="' + e.wikipedia_url + '" target="_blank" rel="noopener">Read more on Wikipedia \u2192</a></div></div>' +
        (e.image_url ? '<figure class="panel-image"><img src="' + e.image_url + '" alt="' + (e.image_caption || '') + '">' +
        (e.image_caption ? '<figcaption>' + e.image_caption + '</figcaption>' : '') + '</figure>' : '') +
        '</div></details>';
    });

    let prose = mdToHtml(body, enhancements);
    enhancements.forEach(e => {
      const marker = 'togglePanel(\'' + e.id + '\')';
      const idx    = prose.indexOf(marker);
      if (idx >= 0) {
        const after = prose.indexOf('</p>', idx) + 4;
        prose = prose.slice(0, after) + panels[e.id] + prose.slice(after);
      }
    });

    const summaryHtml = summary.length
      ? '<div class="chapter-summary"><h3>&#128214; Key Points</h3>' +
        summary.map(s =>
          '<div class="summary-item"><span>' + s.point +
          (s.link ? ' <a href="' + s.link + '" target="_blank" rel="noopener">' + (s.link_label || 'Learn more') + ' \u2192</a>' : '') +
          '</span></div>'
        ).join('') + '</div>'
      : '';

    main.innerHTML =
      '<div id="reader">' +
      '<div class="reader-header">' +
      '<div class="book-name">' + meta.author + ' &middot; ' + meta.year + '</div>' +
      '<h2>Chapter ' + meta.chapter + ': ' + meta.chapter_title + '</h2></div>' +
      '<div class="prose">' + prose + '</div>' +
      summaryHtml + '</div>';
  }

  window.togglePanel = function (id) {
    const p = document.getElementById('panel-' + id);
    if (p) p.open = !p.open;
  };

  function showError(msg) { main.innerHTML = '<div id="error">' + msg + '</div>'; }

  /* ── Font size control ── */
  const fontSizes = ['', 'font-md', 'font-lg'];
  const savedSize = localStorage.getItem('fontSize') || '';
  if (savedSize) document.body.classList.add(savedSize);
  document.querySelectorAll('.fs-btn').forEach(function (btn) {
    if (btn.dataset.size === savedSize) btn.classList.add('active');
    btn.addEventListener('click', function () {
      fontSizes.forEach(function (s) { if (s) document.body.classList.remove(s); });
      document.querySelectorAll('.fs-btn').forEach(function (b) { b.classList.remove('active'); });
      if (btn.dataset.size) document.body.classList.add(btn.dataset.size);
      btn.classList.add('active');
      localStorage.setItem('fontSize', btn.dataset.size);
    });
  });

  loadCatalog().then(route);
})();
