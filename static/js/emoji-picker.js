// Lightweight, fast emoji picker with search, tags and recent
// Global API: window.EmojiPicker.open(anchorEl, { initial }) -> Promise<string|null>
// - Renders a floating panel near anchorEl
// - Keyboard navigable; ESC closes
// - Recent persists in localStorage

(function () {
  const STORAGE_KEY = 'emoji_picker_recent_v1';
  const MAX_RECENT = 18;
  let EMOJI_DATA = getCuratedDefaults();
  let FULL_DATASET = null;
  let FULL_LOAD_PROMISE = null;
  let CURATED_LIST = [];
  const CURATED_INDEX = new Map(); // emoji -> index for pinning order
  const CURATED_NAME = new Map();  // emoji -> curated name for hover text
  const UNICODE_CACHE_KEY = 'emoji_picker_unicode_emoji_test_v1';
  let panel, input, grid, recentRow, tagRow, resolver;
  let activeIndex = -1;
  let currentItems = [];
  let currentToneHex = null; // null => default yellow (no modifier), else '1F3FB'..'1F3FF'

  // Canonical tag normalization and synonyms
  const TAG_SYNONYMS = {
    map: ['maps', 'navigation', 'nav', 'location', 'pin', 'marker', 'geo'],
    parking: ['park', 'carpark', 'car', 'lot'],
    climb: ['climbing', 'climber', 'rock', 'boulder', 'route'],
    water: ['drink', 'potable', 'fountain', 'tap', 'spring'],
    toilet: ['restroom', 'wc', 'bathroom', 'loo'],
    camp: ['camping', 'tent', 'fire', 'campfire'],
    photo: ['camera', 'viewpoint', 'view', 'scenic'],
    warning: ['caution', 'danger', 'hazard', 'notice'],
  };
  const CANONICAL_TAGS = new Set(Object.keys(TAG_SYNONYMS));
  function canonicalizeTag(tag) {
    const t = String(tag || '').toLowerCase();
    if (!t) return null;
    if (CANONICAL_TAGS.has(t)) return t;
    for (const [canon, syns] of Object.entries(TAG_SYNONYMS)) {
      if (syns.includes(t)) return canon;
    }
    return t; // keep unknown tags as-is so JSON-managed tags are preserved
  }

  function ensureStyles() {
    if (document.getElementById('emoji-picker-styles')) return;
    const s = document.createElement('style');
    s.id = 'emoji-picker-styles';
    s.textContent = `
      .emoji-panel { position: fixed; z-index: 3000; width: min(420px, 92vw); background: #1b1b1b; color: #eee; border:1px solid #333; border-radius:12px; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }
      .emoji-header { display:flex; gap:.5rem; align-items:center; padding:.5rem .6rem; border-bottom:1px solid #2b2b2b; }
      .emoji-search { flex:1; padding:.45rem .6rem; border-radius:10px; border:1px solid #3a3a3a; background:#121212; color:#f0f0f0; }
      .emoji-tags { display:flex; gap:.35rem; padding:.4rem .6rem; overflow-x:auto; }
      .emoji-tag { padding:.2rem .5rem; border:1px solid #333; border-radius:999px; background:#222; color:#bbb; cursor:pointer; white-space:nowrap; font-size:.8rem; }
      .emoji-tag.active { color:#03dac6; border-color:#03dac6; box-shadow:0 0 0 1px rgba(3,218,198,0.35) inset; }
      .emoji-recent { display:flex; gap:.25rem; padding:.25rem .6rem; border-bottom:1px solid #2b2b2b; flex-wrap:wrap; }
      .emoji-grid { display:grid; grid-template-columns: repeat(10, 1fr); gap:.25rem; padding:.5rem; max-height: 280px; overflow:auto; }
      .emoji-cell { position:relative; display:flex; align-items:center; justify-content:center; border-radius:8px; height:36px; cursor:pointer; border:1px solid transparent; }
      .emoji-cell:hover, .emoji-cell.active { background:#252525; border-color:#3a3a3a; }
      .emoji-item { font-size: 20px; line-height:1; }
      .tone-panel { position: fixed; z-index: 3001; background:#1b1b1b; border:1px solid #333; border-radius:10px; padding:4px; display:flex; gap:4px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
      .tone-btn { width:32px; height:32px; display:flex; align-items:center; justify-content:center; border-radius:8px; border:1px solid #333; background:#222; cursor:pointer; }
      .tone-btn:hover { border-color:#03dac6; }
      .tone-filter-btn { width:36px; height:36px; display:flex; align-items:center; justify-content:center; border-radius:10px; border:1px solid #3a3a3a; background:#1f1f1f; color:#eee; cursor:pointer; }
      .tone-filter-btn:hover { border-color:#03dac6; }
    `;
    document.head.appendChild(s);
  }

  function readRecent() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch { return []; }
  }
  function writeRecent(list) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_RECENT))); } catch {}
  }
  function bumpRecent(emoji) {
    const rec = readRecent().filter(e => e !== emoji);
    rec.unshift(emoji);
    writeRecent(rec);
  }

  function positionPanel(anchor) {
    const r = anchor.getBoundingClientRect();
    panel.style.top = Math.min(window.innerHeight - panel.offsetHeight - 10, r.bottom + 8) + 'px';
    panel.style.left = Math.min(window.innerWidth - panel.offsetWidth - 10, r.left) + 'px';
  }

  function bindReposition(anchor) {
    const handler = () => {
      try { positionPanel(anchor); } catch {}
    };
    window.addEventListener('scroll', handler, true);
    window.addEventListener('resize', handler);
    panel._cleanup = () => {
      try { window.removeEventListener('scroll', handler, true); } catch {}
      try { window.removeEventListener('resize', handler); } catch {}
    };
  }

  function renderRecent() {
    recentRow.innerHTML = '';
    const rec = readRecent();
    rec.forEach(e => recentRow.appendChild(cell(e, null)));
  }

  function cell(emoji, item) {
    const el = document.createElement('div');
    el.className = 'emoji-cell';
    el.innerHTML = `<span class="emoji-item">${emoji}</span>`;
    el.addEventListener('click', () => choose(emoji));
    // Tone selector: right-click or long-press
    if (supportsTone(item, emoji)) {
      el.addEventListener('contextmenu', (e) => { e.preventDefault(); openTonePanel(e.clientX, e.clientY, emoji); });
      let pressTimer;
      el.addEventListener('touchstart', (e) => { pressTimer = setTimeout(() => { try { const t = e.touches[0]; openTonePanel(t.clientX, t.clientY, emoji); } catch(_) {} }, 450); }, { passive: true });
      ['touchend','touchcancel','touchmove'].forEach(evt => el.addEventListener(evt, () => clearTimeout(pressTimer)));
    }
    return el;
  }

  function choose(emoji) {
    bumpRecent(emoji);
    const r = resolver;
    if (typeof r === 'function') {
      try { r(emoji); } catch {}
    }
    closePanel();
  }

  function closePanel() {
    try { document.removeEventListener('keydown', onKey); } catch {}
    try { if (panel && panel._cleanup) panel._cleanup(); } catch {}
    if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
    panel = null; input = null; grid = null; recentRow = null; tagRow = null; resolver = null; activeIndex = -1; currentItems = [];
  }

  function onKey(e) {
    if (!panel) return;
    if (e.key === 'Escape') { e.preventDefault(); return closePanel(); }
    if (e.key === 'Enter') { e.preventDefault(); if (currentItems[activeIndex]) choose(currentItems[activeIndex].emoji); return; }
    const cols = 10;
    if (['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].includes(e.key)) e.preventDefault();
    if (e.key === 'ArrowRight') activeIndex = Math.min(currentItems.length - 1, activeIndex + 1);
    if (e.key === 'ArrowLeft') activeIndex = Math.max(0, activeIndex - 1);
    if (e.key === 'ArrowDown') activeIndex = Math.min(currentItems.length - 1, activeIndex + cols);
    if (e.key === 'ArrowUp') activeIndex = Math.max(0, activeIndex - cols);
    highlightActive();
  }

  function highlightActive() {
    const cells = grid.querySelectorAll('.emoji-cell');
    cells.forEach((c, i) => c.classList.toggle('active', i === activeIndex));
  }

  function renderGrid(items) {
    grid.innerHTML = '';
    // Apply tone filter to display if selected
    const toneChar = currentToneHex ? String.fromCodePoint(parseInt(currentToneHex, 16)) : '';
    currentItems = items.map(it => {
      if (!currentToneHex) return it;
      try {
        if (supportsTone(it, it.emoji)) {
          return { ...it, emoji: applyTone(it.emoji, toneChar) };
        }
      } catch(_) {}
      return it;
    });
    currentItems.forEach(e => grid.appendChild(cell(e.emoji, e)));
    activeIndex = items.length ? 0 : -1;
    highlightActive();
  }

  function filter(query, tag) {
    query = (query || '').toLowerCase().trim();
    const pool = FULL_DATASET || EMOJI_DATA;
    const canonTag = tag ? canonicalizeTag(tag) : null;
    let result = pool.filter(e => {
      const allKeywords = (e.keywords || []).concat(e.tags || []).join(' ').toLowerCase();
      const matchText = allKeywords + ' ' + (e.name || '').toLowerCase();
      const normalizedTags = (e.tags || []).map(canonicalizeTag);
      const matchTag = !canonTag || normalizedTags.includes(canonTag);
      return (!query || matchText.includes(query)) && matchTag;
    });
    // Pin curated items (from emoji.json) to the top, preserving their order
    try {
      result.sort((a, b) => {
        const ia = CURATED_INDEX.has(a.emoji) ? CURATED_INDEX.get(a.emoji) : Number.POSITIVE_INFINITY;
        const ib = CURATED_INDEX.has(b.emoji) ? CURATED_INDEX.get(b.emoji) : Number.POSITIVE_INFINITY;
        if (ia !== ib) return ia - ib;
        // Stable fallback by code point
        try { return (a.emoji.codePointAt(0) || 0) - (b.emoji.codePointAt(0) || 0); } catch { return 0; }
      });
    } catch (_) {}
    return result.slice(0, 300); // cap for speed
  }

  function renderTags() {
    const dyn = new Set();
    (FULL_DATASET || EMOJI_DATA).forEach(e => (e.tags || []).forEach(t => dyn.add(canonicalizeTag(t))));
    // Ensure at most 10 categories; the dataset is already normalized to <=10
    const catTags = Array.from(dyn).filter(Boolean).slice(0, 10);
    const tags = ['all'].concat(catTags);
    tagRow.innerHTML = '';
    tags.forEach((t, idx) => {
      const b = document.createElement('button');
      b.className = 'emoji-tag' + (idx === 0 ? ' active' : '');
      b.textContent = t;
      b.addEventListener('click', () => {
        Array.from(tagRow.children).forEach(c => c.classList.remove('active'));
        b.classList.add('active');
        renderRecent(); // keep recent visible
        renderGrid(filter(input.value, t === 'all' ? null : t));
      });
      tagRow.appendChild(b);
    });
  }

  function buildPanel(anchor, initial) {
    ensureStyles();
    panel = document.createElement('div'); panel.className = 'emoji-panel';
    panel.innerHTML = `
      <div class="emoji-header">
        <input class="emoji-search" placeholder="Search emojis, tags..." />
        <button class="tone-filter-btn" title="Skin tone filter">✋</button>
      </div>
      <div class="emoji-tags"></div>
      <div class="emoji-recent"></div>
      <div class="emoji-grid"></div>
    `;
    document.body.appendChild(panel);
    input = panel.querySelector('.emoji-search');
    grid = panel.querySelector('.emoji-grid');
    recentRow = panel.querySelector('.emoji-recent');
    tagRow = panel.querySelector('.emoji-tags');
    input.addEventListener('input', () => renderGrid(filter(input.value)));
    const toneBtn = panel.querySelector('.tone-filter-btn');
    toneBtn.addEventListener('click', (e) => {
      const r = toneBtn.getBoundingClientRect();
      openToneFilterPanel(Math.floor(r.left), Math.floor(r.bottom + 4));
    });
    setTimeout(() => document.addEventListener('keydown', onKey), 0);
    renderTags();
    renderRecent();
    // Default to 'all' visually selected; already set by renderTags
    renderGrid(filter('', null));
    input.value = '';
    setTimeout(() => input.focus(), 0);
    positionPanel(anchor);
    bindReposition(anchor);

    // Load curated list from local JSON and a generated full set, then merge
    try {
      if (!FULL_LOAD_PROMISE) {
        FULL_LOAD_PROMISE = Promise.all([
          loadCuratedFromJson(),
          loadAllEmojisJsonDataset()
        ]).then(([curated, allSet]) => {
          // Record curated for pinning and naming
          CURATED_LIST = Array.isArray(curated) ? curated : [];
          CURATED_INDEX.clear(); CURATED_NAME.clear();
          CURATED_LIST.forEach((it, idx) => {
            CURATED_INDEX.set(it.emoji, idx);
            if (it && it.emoji && it.name) CURATED_NAME.set(it.emoji, it.name);
          });
          // Merge curated + all into one dataset without duplicates, keep curated order at front
          const seen = new Set();
          const merged = [];
          CURATED_LIST.forEach(it => { if (it && it.emoji && !seen.has(it.emoji)) { merged.push(it); seen.add(it.emoji); } });
          (Array.isArray(allSet) ? allSet : []).forEach(it => { if (it && it.emoji && !seen.has(it.emoji)) { merged.push(it); seen.add(it.emoji); } });
          return merged;
        });
      }
      FULL_LOAD_PROMISE.then(merged => {
        if (Array.isArray(merged) && merged.length) {
          FULL_DATASET = merged;
          renderTags();
          renderGrid(filter(input.value, null));
        }
      }).catch(() => {});
    } catch(_) {}
  }

  function getCuratedDefaults() { return []; }

  async function loadCuratedFromJson() {
    try {
      const res = await fetch('/static/emoji/emoji.json');
      if (!res.ok) return null;
      const raw = await res.json();
      const mapped = [];
      for (const item of raw) {
        const ch = item.char || item.emoji || '';
        if (!ch) continue;
        const name = (item.name || item.name_en || item.text || '').toString();
        const category = (item.category || item.group || '').toString().toLowerCase();
        const sub = (item.subgroup || '').toString().toLowerCase();
        const tagsFromJson = Array.isArray(item.tags) ? item.tags.map(canonicalizeTag) : [];
        const keywords = Array.isArray(item.keywords) ? item.keywords.slice() : [];
        const supportsTones = !!item.supportsTones;
        mapped.push({ emoji: ch, name: name || ch, tags: tagsFromJson, keywords: keywords.concat([name, category, sub]).filter(Boolean), supportsTones });
      }
      return mapped;
    } catch { return null; }
  }

  async function loadAllEmojisJsonDataset() {
    try {
      const res = await fetch('/static/emoji/all-emojis.json', { cache: 'force-cache' });
      if (!res.ok) return null;
      const raw = await res.json();
      const items = Array.isArray(raw) ? raw : [];
      try { localStorage.setItem(UNICODE_CACHE_KEY, JSON.stringify(items)); } catch {}
      return items;
    } catch(_) { return null; }
  }
  

  function supportsTone(item, emojiChar) {
    if (item && item.supportsTones) return true;
    const name = (item && item.name ? item.name : '').toLowerCase();
    if (/hand|thumb|person|man|woman|people|climb|runner|walk|arm|leg|family|police|guard|detective|cook/.test(name)) return true;
    try {
      const cp = emojiChar.codePointAt(0) || 0;
      return cp >= 0x1F3C3 && cp <= 0x1F9FF;
    } catch { return false; }
  }

  function openTonePanel(x, y, baseEmoji) {
    closeTonePanel();
    const panelEl = document.createElement('div');
    panelEl.className = 'tone-panel';
    const tones = ['1F3FB','1F3FC','1F3FD','1F3FE','1F3FF'];
    tones.forEach(hex => {
      const b = document.createElement('button');
      b.className = 'tone-btn';
      b.textContent = String.fromCodePoint(parseInt(hex, 16));
      b.addEventListener('click', () => {
        choose(applyTone(baseEmoji, b.textContent));
        closeTonePanel();
      });
      panelEl.appendChild(b);
    });
    document.body.appendChild(panelEl);
    panelEl.style.top = Math.min(window.innerHeight - 60, y + 8) + 'px';
    panelEl.style.left = Math.min(window.innerWidth - 180, x - 80) + 'px';
    function onDoc(e) { if (!panelEl.contains(e.target)) { closeTonePanel(); document.removeEventListener('mousedown', onDoc); } }
    setTimeout(()=>document.addEventListener('mousedown', onDoc), 0);
    window._currentTonePanel = panelEl;
  }

  function closeTonePanel() {
    const p = window._currentTonePanel;
    if (p && p.parentNode) p.parentNode.removeChild(p);
    window._currentTonePanel = null;
  }

  function applyTone(baseEmoji, toneChar) {
    try { return baseEmoji + toneChar; } catch { return baseEmoji; }
  }

  function openToneFilterPanel(x, y) {
    closeTonePanel();
    const panelEl = document.createElement('div');
    panelEl.className = 'tone-panel';
    const options = [
      { hex: null, label: '✋' },
      { hex: '1F3FB', label: String.fromCodePoint(0x270B) + String.fromCodePoint(0x1F3FB) },
      { hex: '1F3FC', label: String.fromCodePoint(0x270B) + String.fromCodePoint(0x1F3FC) },
      { hex: '1F3FD', label: String.fromCodePoint(0x270B) + String.fromCodePoint(0x1F3FD) },
      { hex: '1F3FE', label: String.fromCodePoint(0x270B) + String.fromCodePoint(0x1F3FE) },
      { hex: '1F3FF', label: String.fromCodePoint(0x270B) + String.fromCodePoint(0x1F3FF) },
    ];
    options.forEach(opt => {
      const b = document.createElement('button');
      b.className = 'tone-btn';
      b.textContent = opt.label;
      b.addEventListener('click', () => {
        currentToneHex = opt.hex;
        try {
          const btn = panel.querySelector('.tone-filter-btn');
          btn.textContent = opt.hex ? String.fromCodePoint(0x270B) + String.fromCodePoint(parseInt(opt.hex, 16)) : '✋';
        } catch {}
        renderGrid(filter(input.value));
        closeTonePanel();
      });
      panelEl.appendChild(b);
    });
    document.body.appendChild(panelEl);
    panelEl.style.top = Math.min(window.innerHeight - 60, y) + 'px';
    panelEl.style.left = Math.min(window.innerWidth - 220, x) + 'px';
    function onDoc(e) { if (!panelEl.contains(e.target)) { closeTonePanel(); document.removeEventListener('mousedown', onDoc); } }
    setTimeout(()=>document.addEventListener('mousedown', onDoc), 0);
    window._currentTonePanel = panelEl;
  }

  window.EmojiPicker = {
    open(anchorEl, opts = {}) {
      return new Promise((resolve) => {
        resolver = resolve;
        buildPanel(anchorEl, opts.initial || '📍');
      });
    },
    curatedName(emojiChar) {
      try { return CURATED_NAME.get(emojiChar) || null; } catch(_) { return null; }
    }
  };
})();


