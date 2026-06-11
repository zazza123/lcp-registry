/* ==========================================================================
   Component loader — injects header.html & footer.html
   ========================================================================== */

async function loadComponents() {
  var slots = [
    { id: 'header-placeholder', path: 'components/header.html' },
    { id: 'footer-placeholder', path: 'components/footer.html' },
  ];

  await Promise.all(
    slots.map(async function (slot) {
      var el = document.getElementById(slot.id);
      if (!el) return;
      try {
        var res = await fetch(slot.path);
        if (!res.ok) throw new Error(res.statusText);
        el.outerHTML = await res.text();
      } catch (e) {
        console.warn('[components] Failed to load ' + slot.path, e);
      }
    })
  );
}

function initMobileMenu() {
  var btn = document.querySelector('.header__menu-btn');
  var nav = document.querySelector('.header__nav');
  if (!btn || !nav) return;

  btn.addEventListener('click', function () {
    var open = nav.classList.toggle('is-open');
    btn.setAttribute('aria-expanded', open);
  });

  nav.querySelectorAll('.nav__link').forEach(function (link) {
    link.addEventListener('click', function () {
      nav.classList.remove('is-open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
}

/* ==========================================================================
   GitHub repo facts — populate the navbar repo widget (stars / forks / tag)
   from the GitHub API, cached in localStorage to respect the rate limit.
   ========================================================================== */

async function initRepoFacts() {
  var el = document.querySelector('.header__repo');
  if (!el) return;
  var repo = el.getAttribute('data-repo');
  if (!repo) return;

  var stats = await fetchRepoStats(repo);
  if (!stats) return;

  setRepoFact(el, 'stars', formatCount(stats.stars));
  setRepoFact(el, 'forks', formatCount(stats.forks));
  if (stats.version) {
    setRepoFact(el, 'version', stats.version);
    var versionFact = el.querySelector('[data-fact="version"]');
    if (versionFact) versionFact.hidden = false;
  }
}

function setRepoFact(root, name, value) {
  // textContent only: never interpolate API strings as HTML.
  var slot = root.querySelector('[data-fact="' + name + '"] .header__repo-fact-value');
  if (slot) slot.textContent = value;
}

function formatCount(n) {
  if (n == null) return '–';
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n);
}

async function fetchRepoStats(repo) {
  var cacheKey = 'lcp-repo-stats:' + repo;
  var TTL = 60 * 60 * 1000; // 1 hour

  try {
    var cached = JSON.parse(localStorage.getItem(cacheKey) || 'null');
    if (cached && (Date.now() - cached.ts) < TTL) return cached.data;
  } catch (e) { /* ignore malformed cache */ }

  try {
    var res = await fetch('https://api.github.com/repos/' + repo);
    if (!res.ok) throw new Error(res.statusText);
    var json = await res.json();
    var data = {
      stars: json.stargazers_count,
      forks: json.forks_count,
      version: null,
    };

    // Latest release tag is optional: a repo without releases returns 404.
    try {
      var rel = await fetch('https://api.github.com/repos/' + repo + '/releases/latest');
      if (rel.ok) {
        var relJson = await rel.json();
        if (relJson && relJson.tag_name) data.version = relJson.tag_name;
      }
    } catch (e) { /* no release info */ }

    try {
      localStorage.setItem(cacheKey, JSON.stringify({ ts: Date.now(), data: data }));
    } catch (e) { /* storage unavailable */ }
    return data;
  } catch (e) {
    console.warn('[repo] Failed to fetch GitHub stats', e);
    return null;
  }
}
