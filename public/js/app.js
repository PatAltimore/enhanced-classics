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
  let _blobUrls         = [];

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

  /* ── Image caching ── */
  function _extractImageUrls(text) {
    var urls = [], m;
    var re = /image_url:\s*["']([^"'\s]+)["']/g;
    while ((m = re.exec(text)) !== null) {
      if (m[1] && m[1].startsWith('http')) urls.push(m[1]);
    }
    return urls;
  }

  function _cacheImages(text) {
    if (!('caches' in window)) return;
    var urls = _extractImageUrls(text);
    if (!urls.length) return;
    caches.open('ec-images').then(function (cache) {
      urls.forEach(function (url) {
        caches.match(url).then(function (hit) {
          if (hit) return;
          fetch(url, { mode: 'cors' }).then(function (res) {
            if (res.ok) cache.put(url, res);
          }).catch(function () {});
        });
      });
    }).catch(function () {});
  }

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
    _blobUrls.forEach(function (u) { URL.revokeObjectURL(u); });
    _blobUrls = [];
  }

  /* ── Anchor-based reader bookmarks ──
     We record the reading position relative to a prose paragraph (its index plus
     how far we've scrolled past its top) rather than as an absolute pixel offset.
     Absolute offsets break when enhancement panels are expanded at save time but
     collapsed on return, which pushes the restored position further into the
     chapter. Anchors are recomputed against the current layout, so they're stable
     regardless of which panels are open. */
  function _proseParas() {
    var prose = document.querySelector('.prose');
    if (!prose) return [];
    return Array.prototype.filter.call(prose.children, function (el) {
      return el.tagName === 'P';
    });
  }

  function _currentAnchor() {
    var paras = _proseParas();
    if (!paras.length) return null;
    // Anchor to the first paragraph still reaching the viewport top (bottom > 0),
    // with the offset measured WITHIN that paragraph. Using the last paragraph
    // above the top instead would fold an expanded panel's height into the offset,
    // so a collapsed panel on return would overshoot further into the chapter.
    for (var k = 0; k < paras.length; k++) {
      var rect = paras[k].getBoundingClientRect();
      if (rect.bottom > 0) {
        return { i: k, o: Math.max(0, Math.round(-rect.top)) };
      }
    }
    return { i: paras.length - 1, o: 0 };   // scrolled past all prose (summary/footer)
  }

  function _scrollToAnchor(a) {
    if (!a) return;
    var paras = _proseParas();
    if (!paras.length) return;
    var idx  = Math.min(a.i, paras.length - 1);
    var top  = paras[idx].getBoundingClientRect().top;
    window.scrollTo(0, Math.max(0, window.scrollY + top + (a.o || 0)));
  }

  function saveReaderScroll(bookSlug, chapterSlug) {
    if (scrollHandler) window.removeEventListener('scroll', scrollHandler);
    var t;
    var posKey = 'pos_' + bookSlug + '_' + chapterSlug;
    scrollHandler = function () {
      clearTimeout(t);
      t = setTimeout(function () {
        var a = _currentAnchor();
        if (!a) return;
        try { localStorage.setItem(posKey, JSON.stringify(a)); } catch (e) {}
      }, 150);
    };
    window.addEventListener('scroll', scrollHandler);
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
    var lastSlug = localStorage.getItem('last_chapter_' + bookSlug);
    var lastCh   = lastSlug ? book.chapters.find(function (c) { return c.slug === lastSlug; }) : null;
    var continueHtml = lastCh
      ? '<button id="continue-btn" class="continue-btn">Continue reading → Chapter ' +
        lastCh.number + ': ' + lastCh.title + '</button>'
      : '';
    main.innerHTML = '<div id="chapter-list"><h2>' + book.title + '</h2>' +
      '<div class="book-meta">' + book.author + ' &middot; ' + book.year + '</div>' +
      continueHtml +
      book.chapters.map(function (ch) {
        var cached = isChapterCached(bookSlug, ch.slug);
        return '<div class="chapter-item' + (cached ? ' chapter-item--cached' : '') +
          '" onclick="location.hash=\'#/' + bookSlug + '/' + ch.slug + '\'">' +
          '<span class="chapter-num">' + ch.number + '</span>' +
          '<span class="chapter-title">' + ch.title + '</span></div>';
      }).join('') +
      '<button id="download-btn" class="download-btn"></button>' +
      '<p class="offline-legend"><span class="offline-legend-dot">↓</span> = Chapter downloaded for offline reading</p>' +
      '</div>';
    var contBtn = document.getElementById('continue-btn');
    if (contBtn && lastCh) contBtn.addEventListener('click', function () {
      location.hash = '#/' + bookSlug + '/' + lastCh.slug;
    });
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
          if (r.ok) {
            var chText = await r.text();
            storeChapter(book.slug, ch.slug, chText);
            _cacheImages(chText);
          }
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
          _cacheImages(text);
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
      try { localStorage.setItem('last_chapter_' + bookSlug, chapterSlug); } catch (e) {}
      const book = cat.books.find(b => b.slug === bookSlug);
      let nextChapter = null;
      if (book) {
        const idx = book.chapters.findIndex(ch => ch.slug === chapterSlug);
        if (idx >= 0 && idx < book.chapters.length - 1) nextChapter = book.chapters[idx + 1];
      }
      renderReader(meta, body, bookSlug, nextChapter, fromCache);
      // Restore the last reading position (anchor-based, so panel state is safe).
      let anchor = null;
      try { anchor = JSON.parse(localStorage.getItem('pos_' + bookSlug + '_' + chapterSlug) || 'null'); } catch (e) {}
      if (anchor) requestAnimationFrame(function () { _scrollToAnchor(anchor); });
      saveReaderScroll(bookSlug, chapterSlug);
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

    return md.split(/\n\n+/).map(block => {
      if (!block.trim()) return '';
      // A block whose every non-empty line is indented is set-off verse or a
      // block quotation in the source (e.g. Gutenberg poetry). Render it as a
      // blockquote with its line breaks preserved, instead of letting the lines
      // collapse into one running prose line.
      // Require 2+ indented lines: genuine verse/quotation spans multiple lines,
      // whereas a single indented line is usually a scene heading or stage cue.
      const lines   = block.split('\n').filter(l => l.trim());
      const isVerse = lines.length >= 2 && lines.every(l => /^\s/.test(l));
      let p = block.trim();
      p = p.replace(/\*\*([\s\S]+?)\*\*/g, (_, text) => {
        const normText = normTypo(text);
        const t = triggers.find(tr => normText.includes(normTypo(tr)));
        if (t) return '<span class="enhance-trigger" onclick="togglePanel(\'' + triggerMap[t] + '\')">' + text + '</span>';
        return '<strong>' + text + '</strong>';
      });
      p = p.replace(/_(.+?)_/g, (_, t) => '<em>' + t + '</em>');
      p = p.replace(/\*(.+?)\*/g, (_, t) => '<em>' + t + '</em>');
      if (isVerse) return '<blockquote class="verse">' + p.replace(/\n[ \t]*/g, '<br>') + '</blockquote>';
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
        (e.image_url ? '<figure class="panel-image"><img data-src="' + e.image_url + '" alt="' + (e.image_caption || '') + '">' +
        '<figcaption>' + (e.image_caption || '') +
        (commonsUrl(e.image_url) ? ' <a href="' + commonsUrl(e.image_url) + '" target="_blank" rel="noopener" class="commons-link">via Wikimedia Commons</a>' : '') +
        '</figcaption></figure>' : '') +
        '</div></details>';
    });

    let prose = mdToHtml(body, enhancements);
    // Block boundaries are the end of each rendered <p> or verse <blockquote>.
    const paraEnds = [];
    for (let m, re = /<\/(?:p|blockquote)>/g; (m = re.exec(prose)); ) paraEnds.push(m.index + m[0].length);

    // Place each panel after the block containing its trigger word.
    const insertions = [];
    enhancements.forEach(e => {
      const marker = 'togglePanel(\'' + e.id + '\')';
      const idx    = prose.indexOf(marker);
      if (idx < 0) return;
      const after = paraEnds.find(pe => pe > idx);   // end of the block holding the trigger
      if (after != null) insertions.push({ after, triggerIdx: idx, html: panels[e.id] });
    });
    // Does paragraph `i` end on sentence-terminating punctuation? Markdown
    // paragraph breaks don't always coincide with sentence ends (a clause can
    // wrap into a following verse quote), so we avoid dropping a panel on a
    // boundary that would split a sentence.
    const endsSentence = i => {
      const start = i === 0 ? 0 : paraEnds[i - 1];
      const txt = prose.slice(start, paraEnds[i])
        .replace(/<[^>]+>/g, '').replace(/&[^;]+;/g, ' ').trim();
      return /[.!?:”’"')\]]$/.test(txt);
    };
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
        // Advance past boundaries that fall mid-sentence (e.g. a clause wrapping
        // into the next verse-quote paragraph), so the panel lands on a real break.
        while (t < paraEnds.length - 1 && !endsSentence(t)) t++;
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

    // Load each image via fetch → blob URL so WebKit treats it as same-origin.
    // Cross-origin images inside closed <details> panels are not reliably painted
    // by iOS Safari; blob URLs bypass that restriction entirely.
    document.querySelectorAll('.panel-image img[data-src]').forEach(function (img) {
      var url = img.dataset.src;
      fetch(url).then(function (r) { return r.blob(); }).then(function (blob) {
        var blobUrl = URL.createObjectURL(blob);
        _blobUrls.push(blobUrl);
        img.src = blobUrl;
      }).catch(function () {
        img.src = url; // fallback to direct URL if fetch fails
      });
    });
  }

  window.togglePanel = function (id) {
    const p = document.getElementById('panel-' + id);
    if (!p) return;
    p.open = !p.open;
    if (p.open) {
      var img = p.querySelector('.panel-image img');
      if (img) {
        // Blob URLs are same-origin so WebKit paints them without a compositing
        // flush, but we keep the offsetHeight read as a safety measure for any
        // image that hasn't resolved its src yet.
        if (!img.src) {
          img.addEventListener('load', function () { img.offsetHeight; }, { once: true });
        } else {
          img.offsetHeight;
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
        var body = document.getElementById('def-popup-body');
        body.textContent = '';
        function add(cls, text) {
          var div = document.createElement('div');
          div.className = cls;
          div.textContent = text;
          body.appendChild(div);
        }
        data.slice(0, 2).forEach(function (entry) {
          (entry.meanings || []).slice(0, 3).forEach(function (m) {
            add('def-pos', m.partOfSpeech);
            (m.definitions || []).slice(0, 2).forEach(function (d) {
              add('def-text', d.definition);
              if (d.example) add('def-example', '“' + d.example + '”');
            });
          });
        });
        if (!body.childNodes.length) {
          body.innerHTML = '<p class="def-msg">No definitions found.</p>';
        }
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
    _showDef(word, e.clientX, e.clientY);
  });

  document.addEventListener('mouseup', function (e) {
    if (!_inProse(e.target)) return;
    var sel = window.getSelection ? window.getSelection() : null;
    if (!sel || sel.isCollapsed || !sel.toString().trim()) return;
    var word = _getWord(e.clientX, e.clientY);
    if (!word) return;
    _showDef(word, e.clientX, e.clientY);
  });

  document.addEventListener('touchstart', function (e) {
    if (!_inProse(e.target)) return;
    _lpMoved = false;
    var t = e.touches[0]; _lpX = t.clientX; _lpY = t.clientY;
    _lpTimer = setTimeout(function () {
      if (_lpMoved || Date.now() - _cmAt < 800) return;
      var word = _getWord(_lpX, _lpY);
      if (!word) return;
      if (navigator.vibrate) navigator.vibrate(40);
      _showDef(word, _lpX, _lpY);
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
    if (e.target.closest('#def-popup-card')) return;
    // A word selection (e.g. double-click) leaves an active range and just
    // opened the popup — don't let the trailing click dismiss it.
    var sel = window.getSelection ? window.getSelection() : null;
    if (sel && !sel.isCollapsed && _inProse(e.target)) return;
    if (document.getElementById('def-popup').classList.contains('open')) _hideDef();
  });

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') _hideDef(); });

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
