/* ==========================================================================
   Registry — catalogue logic (search, filter, sort, render, viewer)
   ========================================================================== */

/* ---- state ---- */
var registryData = null;
var filter = { search: '', language: 'all', sort: 'name' };
var PAGE_SIZE = 20;
var currentPage = 1;

/* ---- icons (inline SVG snippets) ---- */
var ICONS = {
  search:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  x:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  chevron:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  calendar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>',
  eye:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>',
  pkg:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 9.4 7.55 4.24"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.29 7 12 12 20.71 7"/><line x1="12" y1="22" x2="12" y2="12"/></svg>',
};

/* ---- helpers ---- */
function esc(s) {
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function fmtDate(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function downloadUrl(rawBase, pkg, file) {
  return rawBase + '/' + pkg.path + '/' + file;
}

/* ---- init ---- */
async function initRegistry() {
  try {
    var res = await fetch('data/registry.json');
    if (!res.ok) throw new Error('Failed to load registry data');
    registryData = await res.json();
  } catch (e) {
    console.error('[registry]', e);
    document.getElementById('packages-table-wrap').innerHTML =
      '<div class="empty-state"><p class="empty-state__title">Unable to load registry</p><p class="empty-state__text">Please try again later.</p></div>';
    return;
  }

  renderStats();
  renderLanguageChips();
  renderPackages();
  bindSearch();
  bindSort();
}

/* ---- stats ---- */
function renderStats() {
  var pkgs = registryData.packages;
  var langs = new Set(pkgs.map(function (p) { return p.language; }));
  var versions = pkgs.reduce(function (n, p) { return n + p.versions.length; }, 0);

  setText('stat-packages', pkgs.length);
  setText('stat-languages', langs.size);
  setText('stat-versions', versions);
}

function setText(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}

/* ---- language filter chips ---- */
function renderLanguageChips() {
  var container = document.getElementById('language-chips');
  if (!container) return;

  var counts = {};
  registryData.packages.forEach(function (p) {
    counts[p.language] = (counts[p.language] || 0) + 1;
  });

  var html = '<button class="chip is-active" data-lang="all">All <span class="chip__count">' + registryData.packages.length + '</span></button>';
  Object.keys(counts).sort().forEach(function (lang) {
    html += '<button class="chip" data-lang="' + lang + '">' + capitalize(lang) + ' <span class="chip__count">' + counts[lang] + '</span></button>';
  });
  container.innerHTML = html;

  container.addEventListener('click', function (e) {
    var chip = e.target.closest('.chip');
    if (!chip) return;
    container.querySelectorAll('.chip').forEach(function (c) { c.classList.remove('is-active'); });
    chip.classList.add('is-active');
    filter.language = chip.getAttribute('data-lang');
    currentPage = 1;
    renderPackages();
  });
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

/* ---- search ---- */
function bindSearch() {
  var input = document.getElementById('search-input');
  var clear = document.getElementById('search-clear');
  if (!input) return;

  input.addEventListener('input', function () {
    filter.search = input.value.trim().toLowerCase();
    currentPage = 1;
    renderPackages();
  });

  if (clear) {
    clear.addEventListener('click', function () {
      input.value = '';
      filter.search = '';
      currentPage = 1;
      renderPackages();
      input.focus();
    });
  }
}

/* ---- sort ---- */
function bindSort() {
  var sel = document.getElementById('sort-select');
  if (!sel) return;
  sel.addEventListener('change', function () {
    filter.sort = sel.value;
    currentPage = 1;
    renderPackages();
  });
}

/* ---- sorting ---- */
function sortPackages(pkgs) {
  var list = pkgs.slice();
  switch (filter.sort) {
    case 'name':
      list.sort(function (a, b) { return a.name.localeCompare(b.name); });
      break;
    case 'recent':
      list.sort(function (a, b) { return (b.generatedDate || '').localeCompare(a.generatedDate || ''); });
      break;
    case 'versions':
      list.sort(function (a, b) { return b.versions.length - a.versions.length; });
      break;
  }
  return list;
}

/* ---- render packages (table + pagination) ---- */
function renderPackages() {
  var wrap  = document.getElementById('packages-table-wrap');
  var empty = document.getElementById('empty-state');
  var count = document.getElementById('results-count');
  if (!wrap) return;

  var pkgs = registryData.packages.filter(function (p) {
    if (filter.language !== 'all' && p.language !== filter.language) return false;
    if (filter.search) {
      var q = filter.search;
      return p.name.toLowerCase().includes(q) || p.qualifiedName.toLowerCase().includes(q);
    }
    return true;
  });

  pkgs = sortPackages(pkgs);

  if (count) count.textContent = pkgs.length + ' of ' + registryData.packages.length + ' packages';

  /* empty state */
  if (pkgs.length === 0) {
    wrap.innerHTML = '';
    if (empty) empty.style.display = '';
    renderPagination(0);
    return;
  }
  if (empty) empty.style.display = 'none';

  /* pagination bounds */
  var totalPages = Math.ceil(pkgs.length / PAGE_SIZE);
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;
  var start = (currentPage - 1) * PAGE_SIZE;
  var page  = pkgs.slice(start, start + PAGE_SIZE);

  /* build table */
  var html =
    '<div class="packages-table-wrap">' +
    '<table class="packages-table">' +
    '<thead><tr>' +
      '<th style="width:40px"></th>' +
      '<th>Package</th>' +
      '<th>Language</th>' +
      '<th>Distribution</th>' +
      '<th>Latest</th>' +
      '<th>Updated</th>' +
      '<th>Actions</th>' +
    '</tr></thead><tbody>';

  page.forEach(function (pkg) {
    var raw = registryData.rawUrl;
    var latest = pkg.versions[0] || {};
    var latestUrl = downloadUrl(raw, pkg, latest.file);

    html +=
      '<tr class="pkg-row" data-pkg="' + esc(pkg.name) + '">' +
        '<td><svg class="pkg-row__expand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg></td>' +
        '<td><div class="pkg-row__name">' + esc(pkg.name) + '</div><div class="pkg-row__qualified">' + esc(pkg.qualifiedName) + '</div></td>' +
        '<td><span class="badge badge--' + esc(pkg.language) + '">' + capitalize(esc(pkg.language)) + '</span></td>' +
        '<td><span class="badge badge--' + esc(pkg.distribution) + '">' + esc(pkg.distribution) + '</span></td>' +
        '<td><span class="pkg-row__version">' + esc(pkg.latestVersion) + '</span></td>' +
        '<td><span class="pkg-row__date">' + fmtDate(pkg.generatedDate) + '</span></td>' +
        '<td>' +
          '<div class="pkg-row__actions">' +
            '<a class="btn btn--sm btn--secondary" href="' + latestUrl + '" download title="Download latest manifest" onclick="event.stopPropagation()">' + ICONS.download + '</a>' +
            '<button class="btn btn--sm btn--ghost explore-btn" data-pkg-name="' + esc(pkg.name) + '" data-version="' + esc(latest.version) + '" title="Explore manifest" onclick="event.stopPropagation()">' + ICONS.eye + '</button>' +
          '</div>' +
        '</td>' +
      '</tr>';

    /* expanded versions sub-row (hidden by default) */
    html +=
      '<tr class="pkg-versions-row" data-versions-for="' + esc(pkg.name) + '" style="display:none">' +
        '<td colspan="7">' + versionsPanel(pkg) + '</td>' +
      '</tr>';
  });

  html += '</tbody></table></div>';
  wrap.innerHTML = html;

  renderPagination(totalPages);
  bindTableActions();
}

function versionsPanel(pkg) {
  var raw = registryData.rawUrl;
  var rows = pkg.versions.map(function (v) {
    var url = downloadUrl(raw, pkg, v.file);
    var isLatest = v.version === pkg.latestVersion;
    return (
      '<div class="version-row">' +
        '<span class="version-row__name">' + esc(v.version) + '</span>' +
        (isLatest ? '<span class="badge badge--latest">latest</span>' : '') +
        '<span class="version-row__date">' + fmtDate(v.date) + '</span>' +
        '<span class="version-row__actions">' +
          '<a class="btn btn--sm btn--ghost" href="' + url + '" download title="Download" onclick="event.stopPropagation()">' + ICONS.download + '</a>' +
          '<button class="btn btn--sm btn--ghost explore-btn" data-pkg-name="' + esc(pkg.name) + '" data-version="' + esc(v.version) + '" title="Explore" onclick="event.stopPropagation()">' + ICONS.eye + '</button>' +
        '</span>' +
      '</div>'
    );
  }).join('');

  return '<div class="pkg-versions"><div class="pkg-versions__title">All versions</div><div class="pkg-versions__list">' + rows + '</div></div>';
}

/* ---- pagination ---- */
function renderPagination(totalPages) {
  var container = document.getElementById('pagination');
  if (!container) return;

  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  var prevIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>';
  var nextIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';

  var html = '<button class="pagination__btn" data-page="prev"' + (currentPage <= 1 ? ' disabled' : '') + '>' + prevIcon + '</button>';

  /* page numbers — show max 7 with ellipsis */
  var pages = paginationRange(currentPage, totalPages);
  pages.forEach(function (p) {
    if (p === '…') {
      html += '<span class="pagination__info">…</span>';
    } else {
      html += '<button class="pagination__btn' + (p === currentPage ? ' is-active' : '') + '" data-page="' + p + '">' + p + '</button>';
    }
  });

  html += '<button class="pagination__btn" data-page="next"' + (currentPage >= totalPages ? ' disabled' : '') + '>' + nextIcon + '</button>';

  container.innerHTML = html;

  container.querySelectorAll('.pagination__btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var val = btn.getAttribute('data-page');
      if (val === 'prev') currentPage--;
      else if (val === 'next') currentPage++;
      else currentPage = parseInt(val, 10);
      renderPackages();
      window.scrollTo({ top: document.querySelector('.filter-bar').offsetTop - 80, behavior: 'smooth' });
    });
  });
}

function paginationRange(current, total) {
  if (total <= 7) {
    var arr = [];
    for (var i = 1; i <= total; i++) arr.push(i);
    return arr;
  }
  if (current <= 3) return [1, 2, 3, 4, '…', total];
  if (current >= total - 2) return [1, '…', total - 3, total - 2, total - 1, total];
  return [1, '…', current - 1, current, current + 1, '…', total];
}

/* ---- table interactions ---- */
function bindTableActions() {
  /* row click → expand versions */
  document.querySelectorAll('.pkg-row').forEach(function (row) {
    row.addEventListener('click', function () {
      var name = row.getAttribute('data-pkg');
      var sub = document.querySelector('[data-versions-for="' + name + '"]');
      if (!sub) return;
      var open = row.classList.toggle('is-expanded');
      sub.style.display = open ? '' : 'none';
    });
  });

  /* explore buttons */
  document.querySelectorAll('.explore-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var name = btn.getAttribute('data-pkg-name');
      var version = btn.getAttribute('data-version');
      var pkg = registryData.packages.find(function (p) { return p.name === name; });
      if (pkg) openViewer(pkg, version);
    });
  });

  initAnimations();
}

/* ==========================================================================
   Manifest viewer (slide-in panel)
   ========================================================================== */

var viewerCache = {};
var SYMBOLS_PER_PAGE = 80;

async function openViewer(pkg, version) {
  var overlay = document.getElementById('viewer-overlay');
  var modal   = document.getElementById('viewer-modal');
  var body    = document.getElementById('viewer-body');
  var title   = document.getElementById('viewer-title');

  if (!overlay || !modal) return;

  title.textContent = pkg.name;
  document.title = pkg.name + ' | LCP Registry';
  body.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading manifest…</span></div>';

  overlay.classList.add('is-open');
  modal.classList.add('is-open');
  document.body.style.overflow = 'hidden';

  try {
    var data = await fetchManifest(pkg, version);
    renderViewer(pkg, version, data);
  } catch (e) {
    body.innerHTML = '<div class="empty-state"><p class="empty-state__title">Failed to load manifest</p><p class="empty-state__text">' + esc(e.message) + '</p></div>';
  }
}

function closeViewer() {
  var overlay = document.getElementById('viewer-overlay');
  var modal   = document.getElementById('viewer-modal');
  overlay.classList.remove('is-open');
  modal.classList.remove('is-open');
  document.body.style.overflow = '';
  document.title = 'Home | LCP Registry';
}

async function fetchManifest(pkg, version) {
  var key = pkg.name + '@' + version;
  if (viewerCache[key]) return viewerCache[key];

  var v = pkg.versions.find(function (vv) { return vv.version === version; });
  if (!v) throw new Error('Version not found');

  var url = registryData.rawUrl + '/' + pkg.path + '/' + v.file;
  var res = await fetch(url);
  if (!res.ok) throw new Error('HTTP ' + res.status);

  var ds = new DecompressionStream('gzip');
  var decompressed = res.body.pipeThrough(ds);
  var data = await new Response(decompressed).json();

  viewerCache[key] = data;
  return data;
}

function renderViewer(pkg, version, data) {
  var body = document.getElementById('viewer-body');
  var symbols = data.symbols || {};
  var entries = Object.keys(symbols).map(function (k) { return { key: k, data: symbols[k] }; });

  /* count by kind */
  var kindCounts = {};
  entries.forEach(function (e) {
    var k = e.data.kind || 'unknown';
    kindCounts[k] = (kindCounts[k] || 0) + 1;
  });

  /* build version selector */
  var versionOptions = pkg.versions.map(function (v) {
    return '<option value="' + esc(v.version) + '"' + (v.version === version ? ' selected' : '') + '>' +
      'v' + esc(v.version) + (v.version === pkg.latestVersion ? ' (latest)' : '') + '</option>';
  }).join('');

  /* build stats */
  var statsHtml = Object.keys(kindCounts).sort().map(function (k) {
    return '<span class="viewer__stat"><span class="badge badge--' + k + '">' + k + '</span> <strong>' + kindCounts[k] + '</strong></span>';
  }).join('');

  /* build kind filter chips */
  var kinds = Object.keys(kindCounts).sort();
  var kindChips = '<button class="chip is-active" data-kind="all">All</button>';
  kinds.forEach(function (k) {
    kindChips += '<button class="chip" data-kind="' + k + '">' + k + '</button>';
  });

  body.innerHTML =
    '<div class="viewer__meta">' +
      '<select class="select viewer__version-select" id="viewer-version">' + versionOptions + '</select>' +
      '<span class="badge badge--' + esc(pkg.language) + '">' + capitalize(esc(pkg.language)) + '</span>' +
      '<span class="badge badge--' + esc(pkg.distribution) + '">' + esc(pkg.distribution) + '</span>' +
    '</div>' +
    '<div class="viewer__stats">' + statsHtml + '</div>' +
    '<div class="viewer__toolbar">' +
      '<div class="search-box">' +
        '<span class="search-box__icon">' + ICONS.search + '</span>' +
        '<input type="text" class="search-box__input" id="viewer-search" placeholder="Filter symbols…">' +
      '</div>' +
      '<div class="chip-group" id="viewer-kind-chips">' + kindChips + '</div>' +
    '</div>' +
    '<div class="viewer__symbols-count" id="viewer-symbols-count"></div>' +
    '<div id="viewer-symbols"></div>';

  /* state for symbol rendering */
  var viewerState = { search: '', kind: 'all', shown: SYMBOLS_PER_PAGE };

  function filteredEntries() {
    return entries.filter(function (e) {
      if (viewerState.kind !== 'all' && e.data.kind !== viewerState.kind) return false;
      if (viewerState.search) {
        var q = viewerState.search;
        return e.key.toLowerCase().includes(q) ||
               (e.data.semantics && e.data.semantics.summary && e.data.semantics.summary.toLowerCase().includes(q));
      }
      return true;
    });
  }

  function renderSymbolList() {
    var filtered = filteredEntries();
    var page = filtered.slice(0, viewerState.shown);
    var container = document.getElementById('viewer-symbols');
    var countEl = document.getElementById('viewer-symbols-count');
    if (countEl) countEl.textContent = 'Showing ' + Math.min(viewerState.shown, filtered.length) + ' of ' + filtered.length + ' symbols';

    var html = '<div class="symbol-list">';
    page.forEach(function (e) {
      var name = shortName(e.key);
      var kind = e.data.kind || 'unknown';
      var summary = (e.data.semantics && e.data.semantics.summary) || '';
      var module = e.data.module || '';
      var sig = formatSignature(e.data);
      var desc = (e.data.semantics && e.data.semantics.description) || '';

      html += '<div class="symbol-item" data-sym-key="' + esc(e.key) + '">' +
        '<span class="symbol-item__kind badge badge--' + kind + '">' + kind + '</span>' +
        '<div class="symbol-item__info">' +
          '<div class="symbol-item__name">' + esc(name) + '</div>' +
          (module ? '<div class="symbol-item__module">' + esc(module) + '</div>' : '') +
          (summary ? '<div class="symbol-item__summary">' + esc(summary) + '</div>' : '') +
          '<div class="symbol-item__details">' +
            (sig ? '<pre class="symbol-item__signature">' + esc(sig) + '</pre>' : '') +
            (desc ? '<div class="symbol-item__description">' + esc(desc) + '</div>' : '') +
          '</div>' +
        '</div>' +
      '</div>';
    });

    if (filtered.length > viewerState.shown) {
      html += '<div class="show-more"><button class="btn btn--sm btn--secondary" id="viewer-show-more">Show more (' + (filtered.length - viewerState.shown) + ' remaining)</button></div>';
    }

    html += '</div>';
    container.innerHTML = html;

    /* bind expand */
    container.querySelectorAll('.symbol-item').forEach(function (item) {
      item.addEventListener('click', function () {
        item.classList.toggle('is-expanded');
      });
    });

    var moreBtn = document.getElementById('viewer-show-more');
    if (moreBtn) {
      moreBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        viewerState.shown += SYMBOLS_PER_PAGE;
        renderSymbolList();
      });
    }
  }

  /* bind search */
  var searchInput = document.getElementById('viewer-search');
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      viewerState.search = searchInput.value.trim().toLowerCase();
      viewerState.shown = SYMBOLS_PER_PAGE;
      renderSymbolList();
    });
  }

  /* bind kind chips */
  var kindContainer = document.getElementById('viewer-kind-chips');
  if (kindContainer) {
    kindContainer.addEventListener('click', function (ev) {
      var chip = ev.target.closest('.chip');
      if (!chip) return;
      kindContainer.querySelectorAll('.chip').forEach(function (c) { c.classList.remove('is-active'); });
      chip.classList.add('is-active');
      viewerState.kind = chip.getAttribute('data-kind');
      viewerState.shown = SYMBOLS_PER_PAGE;
      renderSymbolList();
    });
  }

  /* bind version switch */
  var versionSel = document.getElementById('viewer-version');
  if (versionSel) {
    versionSel.addEventListener('change', async function () {
      var newVer = versionSel.value;
      body.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>Loading manifest…</span></div>';
      try {
        var newData = await fetchManifest(pkg, newVer);
        renderViewer(pkg, newVer, newData);
      } catch (err) {
        body.innerHTML = '<div class="empty-state"><p class="empty-state__title">Failed to load</p><p class="empty-state__text">' + esc(err.message) + '</p></div>';
      }
    });
  }

  renderSymbolList();
}

/* ---- format helpers ---- */
function shortName(key) {
  var parts = key.split(':');
  return parts.length > 1 ? parts[parts.length - 1] || parts[0] : key;
}

function formatSignature(sym) {
  if (!sym.signatures || !sym.signatures.length) return '';
  var sig = sym.signatures[0];
  var params = (sig.params || []).map(function (p) {
    var s = p.name;
    if (p.type) s += ': ' + p.type;
    if (!p.required) s += ' = ...';
    return s;
  }).join(', ');
  var prefix = sig.async ? 'async ' : '';
  var name = shortName(sym.module ? sym.module + ':' + (sym.kind === 'function' ? shortName(sym.module + ':' + params) : '') : '');
  var ret = sig.returns ? ' -> ' + sig.returns : '';
  return prefix + 'def(' + params + ')' + ret;
}

/* ==========================================================================
   Boot
   ========================================================================== */

document.addEventListener('DOMContentLoaded', async function () {
  await loadComponents();
  initThemeToggle();
  initMobileMenu();
  initAnimations();
  await initRegistry();

  /* close viewer */
  var overlay = document.getElementById('viewer-overlay');
  var closeBtn = document.getElementById('viewer-close');
  if (overlay) overlay.addEventListener('click', closeViewer);
  if (closeBtn) closeBtn.addEventListener('click', closeViewer);

  /* prevent modal content clicks from closing */
  var modal = document.getElementById('viewer-modal');
  if (modal) modal.addEventListener('click', function (e) { e.stopPropagation(); });

  /* esc key */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeViewer();
  });
});
