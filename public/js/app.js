/* Enhanced Classics — single-page reader */
(function () {
  'use strict';

  const main        = document.getElementById('main-content');
  const backBtn     = document.getElementById('back-btn');
  const homeBtn     = document.getElementById('home-btn');
  const headerTitle = document.getElementById('header-title');
  let catalog           = null;
  let scrollHandler     = null;
  let _installPrompt    = null;

  /* ── Install-to-homescreen helpers ── */
  function _isIos() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
  }
  function _isSilk() {
    return navigator.userAgent.indexOf('Silk') !== -1;
  }
  function _isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches ||
           window.navigator.standalone === true;
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    _installPrompt = e;
    var btn = document.getElementById('install-btn');
    if (btn) btn.style.display = 'inline-flex';
  });

  window.addEventListener('appinstalled', function () {
    _installPrompt = null;
    var btn = document.getElementById('install-btn');
    if (btn) btn.remove();
  });

  /* ── Offline cache helpers ── */
  function _chKey(bookSlug, chapterSlug) {
    return 'offline_ch_' + bookSlug + '_' + chapterSlug;
  }
  function getStoredChapter(bookSlug, chapterSlug) {
    return localStorage.getItem(_chKey(bookSlug, chapterSlug));
  }
  function storeChapter(bookSlug, chapterSlug, text) {
    try { localStorage.setItem(_chKey(bookSlug, chapterSlug), text); } catch (e) {}
  }
  function isChapterCached(bookSlug, chapterSlug) {
    return localStorage.getItem(_chKey(bookSlug, chapterSlug)) !== null;
  }

  function saveScrollFor(key) {
    if (scrollHandler) window.removeEventListener('scroll', scrollHandler);
    var t;
    scrollHandler = function () {
      clearTimeout(t);
      t = setTimeout(function () { localStorage.setItem(key, window.scrollY); }, 150);
    };
    window.addEventListener('scroll', scrollHandler);
  }

  function clearScrollHandler() {
    if (scrollHandler) { window.removeEventListener('scroll', scrollHandler); scrollHandler = null; }
    window.scrollTo(0, 0);
    document.querySelector('header').classList.remove('header-hidden');
  }

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
    try {
      const r = await fetch('/catalog.json', { cache: 'no-cache' });
      if (r.ok) {
        catalog = await r.json();
        try { localStorage.setItem('offline_catalog', JSON.stringify(catalog)); } catch (e) {}
        return catalog;
      }
    } catch (e) { /* offline */ }
    const stored = localStorage.getItem('offline_catalog');
    if (stored) { catalog = JSON.parse(stored); return catalog; }
    throw new Error('Library unavailable offline.');
  }

  /* ── Shelf ── */
  async function showShelf() {
    clearScrollHandler();
    backBtn.style.display = 'none';
    homeBtn.style.display = 'none';
    headerTitle.textContent = 'Enhanced Classics';
    let cat;
    try { cat = await loadCatalog(); } catch (e) { showError(e.message); return; }
    var installBtn = '';
    if (!_isStandalone()) {
      if (_installPrompt) {
        installBtn = '<button id="install-btn" class="install-btn">Add to Home Screen</button>';
      } else if (_isIos()) {
        installBtn = '<button id="install-btn" class="install-btn">Add to Home Screen</button>';
      } else if (_isSilk()) {
        installBtn = '<button id="install-btn" class="install-btn">Add to Home Screen</button>';
      }
    }
    main.innerHTML = '<div id="shelf"><h2>Library</h2>' + installBtn +
      cat.books.map(b =>
        '<div class="book-card" onclick="location.hash=\'#/' + b.slug + '\'">' +
        '<h3>' + b.title + '</h3>' +
        '<div class="meta">' + b.author + ' &middot; ' + b.year + '</div>' +
        '<p>' + b.description + '</p></div>'
      ).join('') + '</div>';
    var installEl = document.getElementById('install-btn');
    if (installEl) installEl.addEventListener('click', _handleInstallClick);
    var saved = localStorage.getItem('scroll_shelf');
    if (saved) requestAnimationFrame(function () { window.scrollTo(0, parseInt(saved, 10)); });
    saveScrollFor('scroll_shelf');
  }

  /* ── Chapter list ── */
  async function showChapterList(bookSlug) {
    clearScrollHandler();
    let cat;
    try { cat = await loadCatalog(); } catch (e) { showError(e.message); return; }
    const book = cat.books.find(b => b.slug === bookSlug);
    if (!book) { showError('Book not found.'); return; }
    backBtn.style.display = 'inline-block';
    backBtn.onclick = function () { location.hash = '#/'; };
    homeBtn.style.display = 'none';
    headerTitle.textContent = book.title;
    main.innerHTML = '<div id="chapter-list"><h2>' + book.title + '</h2>' +
      '<div class="book-meta">' + book.author + ' &middot; ' + book.year + '</div>' +
      book.chapters.map(function (ch) {
        var cached = isChapterCached(bookSlug, ch.slug);
        return '<div class="chapter-item' + (cached ? ' chapter-item--cached' : '') +
          '" onclick="location.hash=\'#/' + bookSlug + '/' + ch.slug + '\'">' +
          '<span class="chapter-num">' + ch.number + '</span>' +
          '<span class="chapter-title">' + ch.title + '</span></div>';
      }).join('') +
      '<button id="download-btn" class="download-btn"></button>' +
      '<p class="offline-legend"><span class="offline-legend-dot">↓</span> Saved for offline reading</p>' +
      '</div>';
    var dlBtn = document.getElementById('download-btn');
    updateDownloadBtn(book, dlBtn);
    dlBtn.addEventListener('click', function () { downloadBook(book, dlBtn); });
    var saved = localStorage.getItem('scroll_list_' + bookSlug);
    if (saved) requestAnimationFrame(function () { window.scrollTo(0, parseInt(saved, 10)); });
    saveScrollFor('scroll_list_' + bookSlug);
  }

  function updateDownloadBtn(book, btn) {
    var all = book.chapters.every(function (ch) { return isChapterCached(book.slug, ch.slug); });
    if (all) {
      btn.textContent = '✓ Available offline';
      btn.classList.add('download-btn--done');
      btn.disabled = true;
    } else {
      btn.textContent = '↓ Download for offline reading';
      btn.classList.remove('download-btn--done');
      btn.disabled = false;
    }
  }

  async function downloadBook(book, btn) {
    btn.disabled = true;
    var total = book.chapters.length, done = 0;
    for (var i = 0; i < book.chapters.length; i++) {
      var ch = book.chapters[i];
      if (!isChapterCached(book.slug, ch.slug)) {
        try {
          var r = await fetch('/books/' + book.slug + '/' + ch.slug + '.md');
          if (r.ok) storeChapter(book.slug, ch.slug, await r.text());
        } catch (e) { /* skip on error */ }
      }
      done++;
      btn.textContent = 'Downloading… ' + done + '/' + total;
      var item = document.querySelector('.chapter-item[onclick*="' + ch.slug + '"]');
      if (item && isChapterCached(book.slug, ch.slug)) item.classList.add('chapter-item--cached');
    }
    updateDownloadBtn(book, btn);
  }

  /* ── Reader ── */
  async function showReader(bookSlug, chapterSlug) {
    main.innerHTML = '<div id="loading">Loading chapter\u2026</div>';
    backBtn.style.display = 'inline-block';
    backBtn.onclick = function () { location.hash = '#/' + bookSlug; };
    homeBtn.style.display = 'inline-block';
    homeBtn.onclick = function () { location.hash = '#/'; };
    try {
      let text = null, fromCache = false;
      try {
        const r = await fetch('/books/' + bookSlug + '/' + chapterSlug + '.md', { cache: 'no-cache' });
        if (r.ok) {
          text = await r.text();
          storeChapter(bookSlug, chapterSlug, text);
        }
      } catch (e) { /* offline */ }
      if (!text) {
        text = getStoredChapter(bookSlug, chapterSlug);
        fromCache = text !== null;
      }
      if (!text) {
        showError('This chapter isn\u2019t saved for offline reading yet. Open it while connected to save it.');
        return;
      }
      const cat = await loadCatalog();
      const { meta, body } = parseFrontmatter(text);
      headerTitle.innerHTML = meta.title + '<span class="header-chapter">Chapter\u00a0' + meta.chapter + ': ' + meta.chapter_title + '</span>';
      const scrollKey = 'scroll_' + bookSlug + '_' + chapterSlug;
      const book = cat.books.find(b => b.slug === bookSlug);
      let nextChapter = null;
      if (book) {
        const idx = book.chapters.findIndex(ch => ch.slug === chapterSlug);
        if (idx >= 0 && idx < book.chapters.length - 1) nextChapter = book.chapters[idx + 1];
      }
      renderReader(meta, body, bookSlug, nextChapter, fromCache);
      const saved = localStorage.getItem(scrollKey);
      if (saved) requestAnimationFrame(function () { window.scrollTo(0, parseInt(saved, 10)); });
      saveScrollFor(scrollKey);
    } catch (e) {
      showError('Could not load chapter: ' + e.message);
    }
  }

  /* ── YAML frontmatter parser ── */
  function parseFrontmatter(raw) {
    raw = raw.replace(/\r\n/g, '\n');
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
  function normTypo(s) {
    return s.replace(/[‘’]/g, "'")
            .replace(/[“”]/g, '"')
            .replace(/[–—]/g, '-')
            .replace(/ /g, ' ')
            .replace(/…/g, '...')
            .replace(/\n/g, ' ');
  }

  function mdToHtml(md, enhancements) {
    const triggerMap = {};
    (enhancements || []).forEach(e => { if (e.trigger) triggerMap[e.trigger] = e.id; });
    const triggers = Object.keys(triggerMap).sort((a, b) => b.length - a.length);

    return md.split(/\n\n+/).map(para => {
      let p = para.trim();
      if (!p) return '';
      p = p.replace(/\*\*([\s\S]+?)\*\*/g, (_, text) => {
        const normText = normTypo(text);
        const t = triggers.find(tr => normText.includes(normTypo(tr)));
        if (t) return '<span class="enhance-trigger" onclick="togglePanel(\'' + triggerMap[t] + '\')">' + text + '</span>';
        return '<strong>' + text + '</strong>';
      });
      p = p.replace(/_(.+?)_/g, (_, t) => '<em>' + t + '</em>');
      p = p.replace(/\*(.+?)\*/g, (_, t) => '<em>' + t + '</em>');
      return '<p>' + p + '</p>';
    }).join('\n');
  }

  /* ── Wikimedia Commons attribution ── */
  function commonsUrl(imageUrl) {
    if (!imageUrl) return null;
    var m = imageUrl.match(/\/thumb\/[0-9a-f]\/[0-9a-f]{2}\/(.+?)\/\d+px-/);
    if (m) return 'https://commons.wikimedia.org/wiki/File:' + m[1];
    var m2 = imageUrl.match(/\/wikipedia\/commons\/[0-9a-f]\/[0-9a-f]{2}\/(.+)$/);
    if (m2) return 'https://commons.wikimedia.org/wiki/File:' + m2[1];
    return null;
  }

  /* ── Render reader ── */
  function renderReader(meta, body, bookSlug, nextChapter, fromCache) {
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
        (e.image_url ? '<figure class="panel-image"><img src="' + e.image_url + '" alt="' + (e.image_caption || '') + '" loading="eager">' +
        '<figcaption>' + (e.image_caption || '') +
        (commonsUrl(e.image_url) ? ' <a href="' + commonsUrl(e.image_url) + '" target="_blank" rel="noopener" class="commons-link">via Wikimedia Commons</a>' : '') +
        '</figcaption></figure>' : '') +
        '</div></details>';
    });

    let prose = mdToHtml(body, enhancements);
    const insertions = [];
    enhancements.forEach(e => {
      const marker = 'togglePanel(\'' + e.id + '\')';
      const idx    = prose.indexOf(marker);
      if (idx >= 0) {
        const after = prose.indexOf('</p>', idx) + 4;
        insertions.push({ after, triggerIdx: idx, html: panels[e.id] });
      }
    });
    // Place each panel after the paragraph containing its trigger word.
    // Build the list of paragraph-end positions in the rendered prose string.
    const paraEnds = [];
    for (let pp = 0; ; ) {
      const pi = prose.indexOf('</p>', pp);
      if (pi < 0) break;
      paraEnds.push(pi + 4);
      pp = pi + 4;
    }
    if (paraEnds.length && insertions.length) {
      // Tag each insertion with the paragraph index of its trigger.
      insertions.forEach(ins => {
        let pi = paraEnds.indexOf(ins.after);
        if (pi < 0) pi = paraEnds.filter(pe => pe <= ins.after).length - 1;
        ins.paraIdx = Math.max(0, pi);
      });
      // Sort in reading order; stagger panels that share the same paragraph.
      insertions.sort((a, b) => a.paraIdx !== b.paraIdx ? a.paraIdx - b.paraIdx : a.triggerIdx - b.triggerIdx);
      let lastPara = -1;
      insertions.forEach(ins => {
        let t = ins.paraIdx;
        if (t <= lastPara) t = lastPara + 1;   // stagger same-paragraph clusters by 1
        t = Math.min(t, paraEnds.length - 1);
        ins.after = paraEnds[t];
        lastPara = t;
      });
    }

    // Insert end-to-start so earlier offsets stay valid; within the same paragraph,
    // insert later triggers first so the first trigger's panel ends up first.
    insertions.sort((a, b) => b.after !== a.after ? b.after - a.after : b.triggerIdx - a.triggerIdx);
    insertions.forEach(ins => {
      prose = prose.slice(0, ins.after) + ins.html + prose.slice(ins.after);
    });

    const summaryHtml = summary.length
      ? '<div class="chapter-summary"><h3>&#128214; Key Points</h3>' +
        summary.map(s =>
          '<div class="summary-item"><span>' + s.point +
          (s.link ? ' <a href="' + s.link + '" target="_blank" rel="noopener">' + (s.link_label || 'Learn more') + ' \u2192</a>' : '') +
          '</span></div>'
        ).join('') + '</div>'
      : '';

    const nextHtml = nextChapter
      ? '<div class="next-chapter"><a href="#/' + bookSlug + '/' + nextChapter.slug + '">Chapter ' + nextChapter.number + ': ' + nextChapter.title + ' \u2192</a></div>'
      : '';

    main.innerHTML =
      '<div id="reader">' +
      '<div class="reader-header">' +
      '<div class="book-name">' + meta.author + ' &middot; ' + meta.year +
      (fromCache ? '<span class="offline-badge">Offline</span>' : '') + '</div>' +
      '<h2>Chapter ' + meta.chapter + ': ' + meta.chapter_title + '</h2></div>' +
      '<div class="prose">' + prose + '</div>' +
      summaryHtml + nextHtml + '</div>';

    // Force-fetch all panel images by placing real <img> elements in a
    // hidden off-screen container. This is more reliable than <link rel="preload">
    // on iOS Safari for cross-origin images inside closed <details> panels.
    var old = document.getElementById('img-prefetch');
    if (old) old.remove();
    var prefetch = document.createElement('div');
    prefetch.id = 'img-prefetch';
    prefetch.setAttribute('aria-hidden', 'true');
    prefetch.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none;';
    enhancements.forEach(function (e) {
      if (!e.image_url) return;
      var img = document.createElement('img');
      img.src = e.image_url;
      img.loading = 'eager';
      img.decoding = 'async';
      prefetch.appendChild(img);
    });
    document.body.appendChild(prefetch);
  }

  window.togglePanel = function (id) {
    const p = document.getElementById('panel-' + id);
    if (!p) return;
    p.open = !p.open;
    if (p.open) {
      // iOS/WebKit defers painting images inside <details> until a compositing
      // flush occurs. Reading offsetHeight forces that flush.
      // If the image is still downloading when the panel opens, the flush must
      // also run after load completes — otherwise it paints nothing and never
      // retries.
      var img = p.querySelector('.panel-image img');
      if (img) {
        img.offsetHeight;
        if (!img.complete) {
          img.addEventListener('load', function() { img.offsetHeight; }, { once: true });
        }
      }
    }
  };

  // Highlight the trigger word whenever its panel is open, and un-highlight when
  // closed. Using capture-phase toggle (which doesn't bubble) catches both
  // togglePanel() calls and direct <summary> clicks.
  document.addEventListener('toggle', function (e) {
    if (!e.target.classList.contains('enhancement-panel')) return;
    var id      = e.target.id.replace('panel-', '');
    var trigger = document.querySelector('.enhance-trigger[onclick="togglePanel(\'' + id + '\')"]');
    if (trigger) trigger.classList.toggle('enhance-trigger--active', e.target.open);
  }, true);

  /* ── Install modal ── */
  function _handleInstallClick() {
    if (_installPrompt) {
      _installPrompt.prompt();
      _installPrompt.userChoice.then(function () { _installPrompt = null; });
      return;
    }
    var body = document.getElementById('install-modal-body');
    if (_isIos()) {
      body.innerHTML =
        '<ol class="install-steps">' +
        '<li>Tap the <strong>Share</strong> button in Safari’s toolbar</li>' +
        '<li>Scroll down and tap <strong>Add to Home Screen</strong></li>' +
        '<li>Tap <strong>Add</strong></li>' +
        '</ol>';
    } else {
      body.innerHTML =
        '<ol class="install-steps">' +
        '<li>Tap the <strong>Menu</strong> button <strong>⋮</strong> in Silk’s toolbar</li>' +
        '<li>Tap <strong>Add to Home Screen</strong></li>' +
        '<li>Tap <strong>Add</strong></li>' +
        '</ol>';
    }
    var modal = document.getElementById('install-modal');
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  document.getElementById('install-modal-close').addEventListener('click', function () {
    var modal = document.getElementById('install-modal');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  });
  document.getElementById('install-modal').addEventListener('click', function (e) {
    if (e.target === this) {
      this.classList.remove('open');
      this.setAttribute('aria-hidden', 'true');
    }
  });

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

  /* ── Theme control ── */
  const themes = ['', 'theme-white'];
  const savedTheme = localStorage.getItem('theme') || '';
  if (savedTheme) document.body.classList.add(savedTheme);
  document.querySelectorAll('.theme-btn').forEach(function (btn) {
    if (btn.dataset.theme === savedTheme) btn.classList.add('active');
    btn.addEventListener('click', function () {
      themes.forEach(function (t) { if (t) document.body.classList.remove(t); });
      document.querySelectorAll('.theme-btn').forEach(function (b) { b.classList.remove('active'); });
      if (btn.dataset.theme) document.body.classList.add(btn.dataset.theme);
      btn.classList.add('active');
      localStorage.setItem('theme', btn.dataset.theme);
    });
  });

  /* ── Word lookup ── */
  var _ctxWord = '', _ctxX = 0, _ctxY = 0;
  var _lpTimer = null, _lpMoved = false, _lpX = 0, _lpY = 0, _cmAt = 0;

  function _wordAtPoint(x, y) {
    var node, offset;
    if (document.caretRangeFromPoint) {
      var rng = document.caretRangeFromPoint(x, y);
      if (!rng) return '';
      node = rng.startContainer; offset = rng.startOffset;
    } else if (document.caretPositionFromPoint) {
      var cpos = document.caretPositionFromPoint(x, y);
      if (!cpos) return '';
      node = cpos.offsetNode; offset = cpos.offset;
    } else { return ''; }
    if (!node || node.nodeType !== Node.TEXT_NODE) return '';
    var txt = node.textContent;
    var sm = txt.slice(0, offset).match(/[a-zA-ZÀ-ž'-]+$/);
    var em = txt.slice(offset).match(/^[a-zA-ZÀ-ž'-]+/);
    var ws = sm ? offset - sm[0].length : offset;
    var we = em ? offset + em[0].length : offset;
    return txt.slice(ws, we).replace(/^['-]+|['-]+$/g, '');
  }

  function _getWord(x, y) {
    var sel = window.getSelection ? window.getSelection() : null;
    var s = sel ? sel.toString().trim() : '';
    if (s && s.length < 40 && /^[\wÀ-ž' -]+$/.test(s)) return s.split(/\s+/)[0];
    return _wordAtPoint(x, y);
  }

  function _inProse(el) { var p = document.querySelector('.prose'); return !!(p && p.contains(el)); }

  function _showMenu(x, y) {
    var m = document.getElementById('word-menu');
    m.style.display = 'block';
    var mw = m.offsetWidth, mh = m.offsetHeight;
    var left = Math.max(8, Math.min(x, window.innerWidth - mw - 8));
    var top  = y + 8;
    if (top + mh > window.innerHeight - 8) top = y - mh - 8;
    m.style.left = left + 'px';
    m.style.top  = Math.max(8, top) + 'px';
  }

  function _hideMenu() { document.getElementById('word-menu').style.display = 'none'; }

  function _showDef(word, ax, ay) {
    var popup = document.getElementById('def-popup');
    var card  = document.getElementById('def-popup-card');
    document.getElementById('def-popup-word').textContent = word;
    document.getElementById('def-popup-body').innerHTML = '<p class="def-msg">Looking up…</p>';
    document.getElementById('def-popup-mw').href =
      'https://www.merriam-webster.com/dictionary/' + encodeURIComponent(word.toLowerCase());
    popup.classList.add('open');

    requestAnimationFrame(function () {
      var cw = card.offsetWidth, ch = card.offsetHeight;
      var vw = window.innerWidth,  vh = window.innerHeight;
      var left, top;
      if (vw <= 600) {
        left = Math.max(12, (vw - cw) / 2);
        top  = Math.max(12, (vh - ch) / 3);
      } else {
        left = Math.min(ax, vw - cw - 12); left = Math.max(left, 12);
        top  = ay + 12;
        if (top + ch > vh - 12) top = ay - ch - 12;
        top  = Math.max(top, 12);
      }
      card.style.left = left + 'px';
      card.style.top  = top  + 'px';
    });

    fetch('https://api.dictionaryapi.dev/api/v2/entries/en/' + encodeURIComponent(word.replace(/[^a-zA-Z'-]/g, '').toLowerCase()))
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        var html = '';
        data.slice(0, 2).forEach(function (entry) {
          (entry.meanings || []).slice(0, 3).forEach(function (m) {
            html += '<div class="def-pos">' + m.partOfSpeech + '</div>';
            (m.definitions || []).slice(0, 2).forEach(function (d) {
              html += '<div class="def-text">' + d.definition + '</div>';
              if (d.example) html += '<div class="def-example">“' + d.example + '”</div>';
            });
          });
        });
        document.getElementById('def-popup-body').innerHTML =
          html || '<p class="def-msg">No definitions found.</p>';
      })
      .catch(function () {
        document.getElementById('def-popup-body').innerHTML =
          '<p class="def-msg">No definition found. Try Merriam-Webster below.</p>';
      });
  }

  function _hideDef() { document.getElementById('def-popup').classList.remove('open'); }

  document.addEventListener('contextmenu', function (e) {
    if (!_inProse(e.target)) return;
    e.preventDefault();
    _cmAt = Date.now();
    clearTimeout(_lpTimer);
    var word = _getWord(e.clientX, e.clientY);
    if (!word) return;
    _ctxWord = word; _ctxX = e.clientX; _ctxY = e.clientY;
    _showMenu(e.clientX, e.clientY);
  });

  document.addEventListener('touchstart', function (e) {
    if (!_inProse(e.target)) return;
    _lpMoved = false;
    var t = e.touches[0]; _lpX = t.clientX; _lpY = t.clientY;
    _lpTimer = setTimeout(function () {
      if (_lpMoved || Date.now() - _cmAt < 800) return;
      var word = _getWord(_lpX, _lpY);
      if (!word) return;
      _ctxWord = word; _ctxX = _lpX; _ctxY = _lpY;
      if (navigator.vibrate) navigator.vibrate(40);
      _showMenu(_lpX, _lpY);
    }, 550);
  }, { passive: true });

  document.addEventListener('touchmove', function (e) {
    var t = e.touches[0];
    if (Math.abs(t.clientX - _lpX) > 8 || Math.abs(t.clientY - _lpY) > 8) {
      _lpMoved = true; clearTimeout(_lpTimer);
    }
  }, { passive: true });

  ['touchend', 'touchcancel'].forEach(function (ev) {
    document.addEventListener(ev, function () { clearTimeout(_lpTimer); }, { passive: true });
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('#word-menu')) _hideMenu();
    if (document.getElementById('def-popup').classList.contains('open') &&
        !e.target.closest('#def-popup-card') && !e.target.closest('#word-menu')) _hideDef();
  });

  document.addEventListener('scroll', _hideMenu, { passive: true });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { _hideMenu(); _hideDef(); } });

  document.getElementById('word-menu-define').addEventListener('click', function () {
    var word = _ctxWord, ax = _ctxX, ay = _ctxY;
    _hideMenu();
    if (word) _showDef(word, ax, ay);
  });

  document.getElementById('def-popup-close').addEventListener('click', _hideDef);

  loadCatalog().then(route);

  /* ── Header hide/show on scroll ── */
  var hdr = document.querySelector('header');
  var lastScrollY = 0;
  var scrollTicking = false;
  window.addEventListener('scroll', function () {
    if (scrollTicking) return;
    scrollTicking = true;
    requestAnimationFrame(function () {
      var y = window.scrollY;
      if (y < 80) {
        hdr.classList.remove('header-hidden');
      } else if (y < lastScrollY - 4) {
        hdr.classList.remove('header-hidden');
      } else if (y > lastScrollY + 4) {
        hdr.classList.add('header-hidden');
      }
      lastScrollY = y;
      scrollTicking = false;
    });
  }, { passive: true });
})();
