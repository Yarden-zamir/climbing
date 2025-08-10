document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('locations-container');
  const searchInput = document.getElementById('locations-filter');
  const countLabel = document.getElementById('locations-count');
  const headerEl = document.getElementById('locations-header');
  const searchFab = document.getElementById('locations-search-fab');
  const searchPopup = document.getElementById('locations-search-popup');
  const searchOverlay = document.getElementById('locations-search-overlay');
  const searchClose = document.getElementById('locations-search-close');
  const searchDone = document.getElementById('locations-search-done');
  const searchClear = document.getElementById('locations-search-clear');

  let locations = [];
  let albumsByLocation = new Map();
  let currentUser = null;
  let allLocationAttributes = [];
  let keysUsedWithValues = new Set();

  init();

  async function init() {
    try {
      // Load canonical locations and enriched albums
      const [userRes, locRes, albumsRes, attrsRes] = await Promise.all([
        fetch('/api/auth/user?_t=' + Date.now()),
        fetch('/api/locations?_t=' + Date.now()),
        fetch('/api/albums/enriched?_t=' + Date.now()),
        fetch('/api/location-attributes?_t=' + Date.now()),
      ]);
      if (userRes.ok) {
        const u = await userRes.json();
        currentUser = u && u.authenticated ? (u.user || null) : null;
      }
      if (!locRes.ok) throw new Error('Failed to load locations');
      if (!albumsRes.ok) throw new Error('Failed to load albums');
      if (!attrsRes.ok) throw new Error('Failed to load location attributes');

      const locs = await locRes.json();
      const enrichedAlbums = await albumsRes.json();
      allLocationAttributes = await attrsRes.json();

      // Normalize locations: [{ name, description }]
      locations = (Array.isArray(locs) ? locs : []).map(l => ({
        name: l.name || String(l || ''),
        description: l.description || '',
        approach: l.approach || '',
        latitude: parseFloat(l.latitude || ''),
        longitude: parseFloat(l.longitude || ''),
        owners: Array.isArray(l.owners) ? l.owners : [],
        attributes: Array.isArray(l.attributes) ? l.attributes : [],
        custom_markers: Array.isArray(l.custom_markers) ? l.custom_markers : [],
      })).filter(l => l.name);

      // Build a set of attribute keys that have ever been used with a value (kv style)
      try {
        keysUsedWithValues = new Set();
        (locations || []).forEach(loc => {
          (loc.attributes || []).forEach(a => {
            if (a && typeof a === 'object') {
              const k = String(a.key || '');
              const v = String(a.value || '');
              if (k && v.trim() !== '') keysUsedWithValues.add(k);
            }
          });
        });
      } catch (_) { keysUsedWithValues = new Set(); }

      // Group albums by metadata.location (exact match on canonical name)
      albumsByLocation = buildAlbumsByLocation(enrichedAlbums);

      render();
      wireSearch();
      wireSearchPopup();
    } catch (e) {
      container.innerHTML = `<div style="color:#cf6679; padding:1rem; text-align:center;">${e.message}</div>`;
    }
  }

  function buildAlbumsByLocation(enrichedAlbums) {
    const map = new Map();
    (Array.isArray(enrichedAlbums) ? enrichedAlbums : []).forEach(item => {
      const meta = item?.metadata || {};
      const loc = (meta.location || '').trim();
      if (!loc) return;
      if (!map.has(loc)) map.set(loc, []);
      map.get(loc).push(meta);
    });
    // Sort each location's albums newest first if date present
    for (const [loc, arr] of map.entries()) {
      arr.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
    }
    return map;
  }

  function wireSearch() {
    if (!searchInput) return;
    const apply = () => {
      const q = (searchInput.value || '').trim().toLowerCase();
      // Sync query to URL for shareability
      try {
        const url = new URL(window.location);
        if (q) url.searchParams.set('q', q); else url.searchParams.delete('q');
        history.replaceState({}, '', url.toString());
      } catch (_) {}
      const sections = Array.from(container.querySelectorAll('[data-location-section]'));
      let visible = 0;
      sections.forEach(section => {
        const name = (section.getAttribute('data-name') || '').toLowerCase();
        const desc = (section.getAttribute('data-desc') || '').toLowerCase();
        const matches = !q || name.includes(q) || desc.includes(q);
        section.style.display = matches ? '' : 'none';
        if (matches) visible += 1;
      });
      updateCount(visible, sections.length);
    };
    searchInput.addEventListener('input', apply);
    // Apply initial filter from URL param if present
    applyFilterFromUrl();
  }

  function wireSearchPopup() {
    if (!searchFab || !searchPopup || !searchOverlay) return;
    const openPopup = () => {
      searchOverlay.classList.add('active');
      searchPopup.classList.add('active');
      searchFab.classList.add('active');
      // Focus and select existing text for quick typing
      setTimeout(() => { try { searchInput?.focus(); searchInput?.select(); } catch (_) {} }, 10);
    };
    const closePopup = () => {
      searchOverlay.classList.remove('active');
      searchPopup.classList.remove('active');
      searchFab.classList.remove('active');
    };
    searchFab.addEventListener('click', () => {
      if (searchPopup.classList.contains('active')) closePopup(); else openPopup();
    });
    searchOverlay.addEventListener('click', closePopup);
    searchClose?.addEventListener('click', closePopup);
    searchDone?.addEventListener('click', closePopup);
    searchClear?.addEventListener('click', () => { if (searchInput) { searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); } });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && searchPopup.classList.contains('active')) closePopup();
    });
  }

  function applyFilterFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      const q = (params.get('q') || '').trim();
      if (q && searchInput) {
        searchInput.value = q;
        searchInput.dispatchEvent(new Event('input'));
      }
    } catch (_) {}
  }

  function updateCount(visible, total) {
    if (!countLabel) return;
    const hasQuery = !!(searchInput && (searchInput.value || '').trim());
    if (!hasQuery || total === 0) {
      countLabel.textContent = '';
      if (headerEl) headerEl.style.display = 'none';
      return;
    }
    countLabel.innerHTML = `🔎 <strong>${visible}</strong> of <strong>${total}</strong> locations`;
    if (headerEl) headerEl.style.display = '';
  }

  function render() {
    if (!Array.isArray(locations) || locations.length === 0) {
      container.innerHTML = `<div style="color:#aaa; padding:1rem; text-align:center;">No locations yet. Locations will appear as albums are tagged.</div>`;
      updateCount(0, 0);
      return;
    }

    const sections = locations.map((loc) => createLocationSection(loc));
    container.innerHTML = '';
    sections.forEach(sec => container.appendChild(sec));
    // Initialize maps after insertion
    sections.forEach(sec => { if (typeof sec._initMap === 'function') sec._initMap(); });
    // Update album scrollers to toggle single/full-bleed based on available width
    requestAnimationFrame(updateAllAlbumsScrollers);
    updateCount(sections.length, sections.length);

    // After render, apply selection from URL if present
    applySelectionFromUrl();
  }

  function updateAllAlbumsScrollers() {
    const scrollers = container.querySelectorAll('.albums-scroller');
    scrollers.forEach(scroller => {
      const hasOverflow = scroller.scrollWidth > scroller.clientWidth + 1;
      scroller.classList.toggle('single', !hasOverflow);
    });
  }

  function debounce(fn, wait = 120) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
  }

  // Scroll a location section so its top edge is visible beneath the fixed nav
  function scrollSectionIntoViewTop(section) {
    try {
      const nav = document.querySelector('nav');
      const navHeight = nav ? nav.getBoundingClientRect().height : 0;
      const top = window.scrollY + section.getBoundingClientRect().top - navHeight - 8;
      // Use rAF to ensure layout is settled before scrolling
      requestAnimationFrame(() => {
        window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
      });
    } catch (_) {
      // Fallback
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function ensureLoadingStyles() {
    if (document.getElementById('locations-loading-styles')) return;
    const style = document.createElement('style');
    style.id = 'locations-loading-styles';
    style.textContent = `
      @keyframes locSpin { 
        0% { transform: rotate(0deg); } 
        100% { transform: rotate(360deg); } 
      }
      @keyframes locGlow { 
        0%, 100% { box-shadow: 0 0 15px rgba(3, 218, 198, 0.4), 0 0 30px rgba(187, 134, 252, 0.2); } 
        50% { box-shadow: 0 0 25px rgba(3, 218, 198, 0.7), 0 0 50px rgba(187, 134, 252, 0.4); } 
      }
      .loading-container { 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        position: absolute; 
        inset: 0; 
        z-index: 10;
      }
      .loading-container .spinner { 
        width: 48px; 
        height: 48px; 
        border: 4px solid rgba(3, 218, 198, 0.2); 
        border-top: 4px solid #03dac6; 
        border-right: 4px solid #bb86fc;
        border-radius: 50%; 
        animation: locSpin 1.2s linear infinite, locGlow 2.5s ease-in-out infinite;
        display: block;
      }
    `;
    document.head.appendChild(style);
  }

  window.addEventListener('resize', debounce(updateAllAlbumsScrollers, 120));
  
  // Click outside to unselect location cards
  document.addEventListener('click', (e) => {
    // Check if click is outside all location sections
    if (!e.target.closest('.location-section')) {
      clearAllSelections();
      // Also clear URL highlight parameter
      const url = new URL(window.location);
      url.searchParams.delete('highlight');
      url.searchParams.delete('selected_map_icon');
      history.pushState({}, '', url.toString());
    }
  });

  function createLocationSection(loc) {
    const section = document.createElement('section');
    section.className = 'location-section';
    section.setAttribute('data-location-section', '');
    section.setAttribute('data-name', loc.name);
    section.setAttribute('data-desc', loc.description || '');
    section.id = cssId(loc.name);

    const title = document.createElement('div');
    title.className = 'location-header';
    const albumCountForHeader = (albumsByLocation.get(loc.name) || []).length;
    const albumsLabel = `${albumCountForHeader} album${albumCountForHeader === 1 ? '' : 's'}`;
    const actions = [
      `<a class="location-btn" data-role="albums-link" href="/albums?locations=${encodeURIComponent(loc.name)}">${albumsLabel}</a>`
    ];
    if (isLocationEditableByCurrentUser(loc)) {
      actions.push('<button class="location-btn" data-action="toggle-edit">Edit</button>');
      actions.push('<button class="location-btn" data-action="cancel-edit" style="display:none;">❌</button>');
    }
    if (isLocationDeletableByCurrentUser(loc)) {
      actions.push('<button class="location-btn" data-action="delete">Delete</button>');
    }
    title.innerHTML = `
      <div class="location-title">
        <span class="pin">📍</span>
        <span data-role="name-text">${escapeHtml(loc.name)}</span>
      </div>
        <div class="location-actions">${actions.join('')}</div>
    `;

    const body = document.createElement('div');
    body.className = 'location-body';

    // Left column wrapper to keep map and coords together
    const mapCol = document.createElement('div');
    mapCol.className = 'map-col';

    const mapDiv = document.createElement('div');
    mapDiv.className = 'location-map';
    const mapViewport = document.createElement('div');
    mapViewport.className = 'map-viewport';
    const mapOverlay = document.createElement('div');
    mapOverlay.className = 'map-activation-overlay';
    mapOverlay.innerHTML = '<div class="hint">Tap to interact</div>';
    mapDiv.appendChild(mapViewport);
    mapDiv.appendChild(mapOverlay);

    const infoDiv = document.createElement('div');
    infoDiv.className = 'location-info';
    const description = document.createElement('div');
    description.className = 'location-approach';
    const descText = (loc.description && String(loc.description).trim()) || `No description yet for ${loc.name}.`;
    description.innerHTML = `<div class="description-text" dir="auto">${escapeHtml(descText)}</div>`;
    const approach = document.createElement('div');
    approach.className = 'location-approach';
    const approachText = (loc.approach && String(loc.approach).trim()) || `No approach info yet for ${loc.name}. Add a note when you tag albums here.`;
    approach.innerHTML = `<div class="heading">Approach</div><div class="approach-text" dir="auto">${escapeHtml(approachText)}</div>`;

    const scroller = document.createElement('div');
    scroller.className = 'albums-scroller';
    const albums = albumsByLocation.get(loc.name) || [];
    if (albums.length === 0) {
      scroller.innerHTML = `<div style="color:#888; padding:0.4rem 0;">No albums yet.</div>`;
    } else {
      if (albums.length === 1) scroller.classList.add('single');
      albums.forEach(meta => scroller.appendChild(createMiniAlbumCard(meta)));
    }

    infoDiv.appendChild(description);
    // Approach placement handled below
    infoDiv.appendChild(scroller);

    // Attributes view and editor
    const attributesPanel = document.createElement('div');
    attributesPanel.className = 'location-attributes';
    const attributesList = document.createElement('div');
    attributesList.className = 'attributes-list';
    function renderAttributesList() {
      attributesList.innerHTML = '';
      const items = Array.isArray(loc.attributes) ? loc.attributes : [];
      if (items.length === 0) {
        attributesList.innerHTML = `<span style="color:#888;">No attributes yet.</span>`;
        return;
      }
      // items may be strings (legacy) or objects {key, value}
      const norm = items.map(it => {
        if (typeof it === 'string') return { key: it, value: '' };
        return { key: String(it.key || ''), value: String(it.value || '') };
      }).filter(it => it.key);
      norm.sort((a,b)=>a.key.localeCompare(b.key)).forEach(({key, value}) => {
        const badge = document.createElement('span');
        badge.className = 'attribute-badge';
        // Hint to GPU for smoother hover on heavy pages
        badge.style.willChange = 'transform';
        const content = document.createElement('span');
        content.className = 'attr-content';
        const keyEl = document.createElement('span'); keyEl.className = 'attr-key'; keyEl.textContent = key;
        content.appendChild(keyEl);
        if (value) {
          const valueEl = document.createElement('span'); valueEl.className = 'attr-value';
          // If numeric-ish, add count styling
          if (!isNaN(Number(value))) valueEl.classList.add('count');
          valueEl.textContent = String(value);
          content.appendChild(valueEl);
        }
        // Remove button in edit mode
        const removeBtn = document.createElement('button');
        removeBtn.className = 'attr-remove';
        removeBtn.type = 'button';
        removeBtn.title = 'Remove';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const list = Array.isArray(loc.attributes) ? loc.attributes : [];
          const idx = list.findIndex(it => (typeof it === 'string' ? it : String(it.key || '')) === key);
          if (idx >= 0) {
            list.splice(idx, 1);
            loc.attributes = list;
            // Particle effect
            try { createRemovalParticles(badge); } catch(_) {}
            renderAttributesList();
            renderAttributeBadges && renderAttributeBadges();
          }
        });
        // Place remove button before content so it visually sits on the left
        badge.appendChild(removeBtn);
        badge.appendChild(content);
        attributesList.appendChild(badge);
      });
    }
    renderAttributesList();
    attributesPanel.appendChild(attributesList);
    infoDiv.appendChild(attributesPanel);

    // Navigation app buttons under the map
    mapCol.appendChild(mapDiv);
    function openHereInApp(appKey) {
      const pos = (typeof section._getMarkerLatLng === 'function' && section._getMarkerLatLng()) ||
                  (Number.isFinite(loc.latitude) && Number.isFinite(loc.longitude)
                    ? { lat: Number(loc.latitude), lng: Number(loc.longitude) }
                    : null);
      const name = loc.name || '';
      let url = '';
      if (appKey === 'google') {
        url = pos
          ? `https://www.google.com/maps/search/?api=1&query=${pos.lat},${pos.lng}`
          : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(name)}`;
      } else if (appKey === 'apple') {
        url = pos
          ? `http://maps.apple.com/?ll=${pos.lat},${pos.lng}&q=${encodeURIComponent(name)}`
          : `http://maps.apple.com/?q=${encodeURIComponent(name)}`;
      } else if (appKey === 'waze') {
        url = pos
          ? `https://waze.com/ul?ll=${pos.lat},${pos.lng}&navigate=yes`
          : `https://waze.com/ul?q=${encodeURIComponent(name)}&navigate=yes`;
      } else if (appKey === 'moovit') {
        // Use Moovit Trip Planner endpoint
        const lang = (navigator.language || 'en').split('-')[0] || 'en';
        url = pos
          ? `https://moovitapp.com/tripplan/?to=${encodeURIComponent(name)}&tll=${pos.lat}_${pos.lng}&lang=${encodeURIComponent(lang)}`
          : `https://moovitapp.com/tripplan/?to=${encodeURIComponent(name)}&lang=${encodeURIComponent(lang)}`;
      } else if (appKey === 'whatsapp') {
        // Share only the URL via WhatsApp (no extra text)
        const shareUrlObj = new URL(window.location.origin + '/locations');
        shareUrlObj.searchParams.set('highlight', name);
        const shareUrl = shareUrlObj.href;
        url = `https://wa.me/?text=${encodeURIComponent(shareUrl)}`;
      }
      if (url) window.open(url, '_blank', 'noopener');
    }

    async function shareHere() {
      const name = loc.name || 'Location';
      // Use highlight query param to match crew selection pattern
      const urlObj = new URL(window.location.origin + '/locations');
      urlObj.searchParams.set('highlight', name);
      const shareUrl = urlObj.href;
      try {
        if (navigator.share) {
          await navigator.share({ url: shareUrl });
        } else if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(shareUrl);
          alert('Link copied to clipboard');
        } else {
          window.prompt('Copy this link', shareUrl);
        }
      } catch (_) {
        // Ignore share cancellation or errors silently
      }
    }
    const navRow = document.createElement('div');
    navRow.className = 'nav-apps-row';
    navRow.style.cssText = 'display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.5rem;';
    const iconPaths = {
      google: '/static/icons/google-maps.svg',
      apple: '/static/icons/apple-maps.svg',
      waze: '/static/icons/waze.svg',
      moovit: '/static/icons/moovit.svg',
      whatsapp: '/static/icons/whatsapp.svg',
      share: '/static/icons/share.svg'
    };
    [
      { key: 'google', label: 'Google Maps' },
      { key: 'apple', label: 'Apple Maps' },
      { key: 'waze', label: 'Waze' },
      { key: 'moovit', label: 'Moovit' },
      { key: 'whatsapp', label: 'WhatsApp' },
      { key: 'share', label: 'Share' },
    ].forEach(({ key, label }) => {
      const btn = document.createElement('button');
      btn.className = 'location-btn icon-btn';
      btn.setAttribute('aria-label', label);
      const img = document.createElement('img');
      img.alt = label;
      img.loading = 'lazy';
      img.src = iconPaths[key] || '';
      btn.appendChild(img);
      if (key === 'share') {
        btn.addEventListener('click', () => { shareHere(); });
      } else {
        btn.addEventListener('click', () => openHereInApp(key));
      }
      navRow.appendChild(btn);
    });
    mapCol.appendChild(navRow);
    body.appendChild(mapCol);
    body.appendChild(infoDiv);

    section.appendChild(title);
    const divider = document.createElement('div');
    divider.className = 'section-divider';
    section.appendChild(divider);
    section.appendChild(body);

    // Click-to-select: toggle selected class and sync URL
    section.addEventListener('click', (e) => {
      // Avoid selecting when clicking interactive elements (links, buttons, map controls)
      const target = e.target;
      if (target.closest && (target.closest('a') || target.closest('button') || target.closest('.leaflet-control') || target.closest('.map-activation-overlay'))) {
        return;
      }
      toggleSelection(section, loc.name);
    });

    // Actions
    // Map button removed

    // Place approach under map on desktop, in info on mobile
    const mqDesktop = window.matchMedia('(min-width: 901px)');
    function placeApproach() {
      if (mqDesktop.matches) {
        if (approach.parentElement !== mapCol) {
          mapCol.appendChild(approach);
        }
      } else {
        if (approach.parentElement !== infoDiv) {
          infoDiv.insertBefore(approach, scroller);
        }
      }
    }
    placeApproach();
    mqDesktop.addEventListener?.('change', placeApproach);
    window.addEventListener('resize', placeApproach);

    // Inline editing (no new panel)
    let isEditing = false;
    const editBtn = title.querySelector('[data-action="toggle-edit"]');
    const cancelBtn = title.querySelector('[data-action="cancel-edit"]');
    const deleteBtn = title.querySelector('[data-action="delete"]');
    // claim button removed
    let descTextarea, approachTextarea, nameInput;
    let attributesEditorEl, attributesBadgesEl, addAttributeInputEl;
    let valueRowEl, valueLabelEl, valueInputEl, valueSaveBtnEl, valueSkipBtnEl;
    let pendingValueKey = null;
    // Markers editor state
    let markersEditorEl, markersListEl, addMarkerBtn, markerLabelInput;
    let extraMarkers = Array.isArray(loc.custom_markers) ? JSON.parse(JSON.stringify(loc.custom_markers)) : [];
    let placeIconArmed = false;
    let pendingMarkerPos = null;
    let pendingEmoji = '📍';
    let pendingLabelValue = '';
    let selectedIndex = 0;
    let dragSrcIndex = null;
    let currentEmojiChoice = '📍';

    function enterEditMode() {
      if (isEditing) return;
      isEditing = true;
      try { section.classList.add('editing'); } catch(_) {}
      if (editBtn) editBtn.textContent = '💾';
      if (cancelBtn) cancelBtn.style.display = '';
      // Hide albums counter/link while editing to reduce header clutter on mobile
      const albumsLinkEl = title.querySelector('[data-role="albums-link"]');
      if (albumsLinkEl) {
        albumsLinkEl.dataset.prevDisplay = albumsLinkEl.style.display || '';
        albumsLinkEl.style.display = 'none';
      }
      // Replace name with input and text with textareas (re-query current read-only nodes each time)
      section.classList.add('editing');
      const nameTextEl = title.querySelector('[data-role="name-text"]');
      if (nameTextEl && nameTextEl.parentNode) {
        nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.inputMode = 'text';
        nameInput.autocapitalize = 'words';
        nameInput.spellcheck = true;
        nameInput.value = loc.name;
        nameInput.placeholder = 'Location name';
        nameInput.style.cssText = 'padding:0.35rem 0.5rem; border-radius:8px; border:1px solid #444; background:#1b1b1b; color:#fff; min-width:10ch; max-width:26ch; width:min(100%, 26ch); flex:0 1 auto;';
        nameTextEl.replaceWith(nameInput);
      }
      const descTextEl = description.querySelector('.description-text');
      const approachTextEl = approach.querySelector('.approach-text');

      descTextarea = document.createElement('textarea');
      descTextarea.id = `desc-${cssId(loc.name)}`;
      descTextarea.rows = 3;
      descTextarea.placeholder = 'Add description...';
      descTextarea.style.cssText = 'resize:vertical; padding:0.6rem; border-radius:8px; border:1px solid #444; background:#1b1b1b; color:#fff; width:100%';
      descTextarea.value = (loc.description || '').trim();
      if (descTextEl && descTextEl.parentNode) {
        descTextEl.replaceWith(descTextarea);
      }

      approachTextarea = document.createElement('textarea');
      approachTextarea.id = `approach-${cssId(loc.name)}`;
      approachTextarea.rows = 3;
      approachTextarea.placeholder = 'Add approach...';
      approachTextarea.style.cssText = 'resize:vertical; padding:0.6rem; border-radius:8px; border:1px solid #444; background:#1b1b1b; color:#fff; width:100%';
      approachTextarea.value = (loc.approach || '').trim();
      if (approachTextEl && approachTextEl.parentNode) {
        approachTextEl.replaceWith(approachTextarea);
      }

      // Enable marker dragging only during edit
      if (typeof section._setMarkerDraggable === 'function') {
        section._setMarkerDraggable(true);
      }
      // Ensure map is interactive for placing/dragging extra icons
      try {
        mapViewport.style.pointerEvents = 'auto';
        mapViewport.style.touchAction = 'auto';
        if (mapOverlay) {
          mapOverlay.style.pointerEvents = 'none';
          mapOverlay.style.opacity = '0';
        }
      } catch(_) {}
      // Make existing emoji markers draggable now
      try { if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers); } catch(_) {}

      // Attributes editor
      if (isLocationEditableByCurrentUser(loc)) {
        attributesEditorEl = document.createElement('div');
        attributesEditorEl.className = 'attributes-editor';
        const editorLabel = document.createElement('div');
        editorLabel.className = 'heading';
        editorLabel.textContent = 'Edit Attributes';
        attributesEditorEl.appendChild(editorLabel);

        attributesBadgesEl = document.createElement('div');
        attributesBadgesEl.className = 'attributes-badges-container';

        function currentKeys() {
          return (Array.isArray(loc.attributes) ? loc.attributes : []).map(it => typeof it === 'string' ? it : String(it.key || '')).filter(Boolean);
        }
        function ensureKVArray() {
          if (!Array.isArray(loc.attributes)) loc.attributes = [];
          // Normalize to objects
          loc.attributes = loc.attributes.map(it => typeof it === 'string' ? { key: it, value: '' } : { key: String(it.key || ''), value: String(it.value || '') }).filter(it => it.key);
        }
        function renderAttributeBadges() {
          ensureKVArray();
          const selectedKeys = new Set(currentKeys());
          const all = Array.isArray(allLocationAttributes) ? allLocationAttributes.slice() : [];
          // Ensure selected missing from global are still shown
          currentKeys().forEach(a => { if (!all.includes(a)) all.push(a); });
          all.sort((a,b)=>a.localeCompare(b));
          attributesBadgesEl.innerHTML = all.map(a => {
            const sel = selectedKeys.has(a) ? 'selected' : '';
            return `<div class="attribute-badge-toggleable ${sel}" data-attr="${escapeHtml(a)}">${escapeHtml(a)}</div>`;
          }).join('');
        }
        renderAttributeBadges();

        attributesBadgesEl.addEventListener('click', (e) => {
          const el = e.target.closest('.attribute-badge-toggleable');
          if (!el) return;
          const attr = el.getAttribute('data-attr') || '';
          ensureKVArray();
          const idx = loc.attributes.findIndex(it => it.key === attr);
          if (idx >= 0) {
            loc.attributes.splice(idx, 1);
            // If removing the pending one, reset inline editor
            if (pendingValueKey === attr) hideInlineValueEditor();
          } else {
            loc.attributes.push({ key: attr, value: '' });
            // If this key is commonly used with values, prompt inline input
            if (keysUsedWithValues && keysUsedWithValues.has(attr)) {
              showInlineValueEditor(attr);
            }
          }
          renderAttributeBadges();
          renderAttributesList();
        });

        const addRow = document.createElement('div');
        addRow.style.display = 'flex';
        addRow.style.gap = '0.5rem';
        addRow.style.alignItems = 'center';
        addAttributeInputEl = document.createElement('input');
        addAttributeInputEl.className = 'add-attribute-input';
        addAttributeInputEl.placeholder = 'Add new attribute (e.g., "sport routes" or "sport routes:26")';
        const addBtn = document.createElement('button');
        addBtn.className = 'location-btn';
        addBtn.textContent = 'Add';
        function handleAddFromInput() {
          const val = (addAttributeInputEl.value || '').trim();
          if (!val) return;
          // Parse potential key:value
          let key = val;
          let value = '';
          const colon = val.indexOf(':');
          if (colon > 0) {
            key = val.slice(0, colon).trim();
            value = val.slice(colon + 1).trim();
          }
          if (!key) return;
          // async fire-and-forget register globally
          try { fetch('/api/location-attributes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: key }) }); } catch (_) {}
          if (!allLocationAttributes.includes(key)) allLocationAttributes.push(key);
          ensureKVArray();
          if (!loc.attributes.some(it => it.key === key)) loc.attributes.push({ key, value });
          if (value && value.trim() !== '') keysUsedWithValues.add(key);
          addAttributeInputEl.value = '';
          renderAttributeBadges();
          renderAttributesList();
        }
        addBtn.addEventListener('click', handleAddFromInput);
        addAttributeInputEl.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            handleAddFromInput();
          }
        });
        addRow.appendChild(addAttributeInputEl);
        addRow.appendChild(addBtn);

        attributesEditorEl.appendChild(attributesBadgesEl);
        attributesEditorEl.appendChild(addRow);

        // Inline value editor for kv attributes
        valueRowEl = document.createElement('div');
        valueRowEl.style.display = 'none';
        valueRowEl.style.gap = '0.5rem';
        valueRowEl.style.alignItems = 'center';
        valueRowEl.style.marginTop = '0.25rem';
        valueRowEl.style.display = 'none';
        valueLabelEl = document.createElement('div');
        valueLabelEl.style.color = '#bbb';
        valueLabelEl.style.fontSize = '0.85rem';
        valueLabelEl.textContent = '';
        valueInputEl = document.createElement('input');
        valueInputEl.className = 'add-attribute-input';
        valueInputEl.placeholder = 'Enter value';
        valueSaveBtnEl = document.createElement('button');
        valueSaveBtnEl.className = 'location-btn';
        valueSaveBtnEl.textContent = 'Save';
        valueSkipBtnEl = document.createElement('button');
        valueSkipBtnEl.className = 'location-btn';
        valueSkipBtnEl.textContent = 'Skip';
        valueRowEl.appendChild(valueLabelEl);
        valueRowEl.appendChild(valueInputEl);
        valueRowEl.appendChild(valueSaveBtnEl);
        valueRowEl.appendChild(valueSkipBtnEl);
        attributesEditorEl.appendChild(valueRowEl);

        function showInlineValueEditor(key) {
          pendingValueKey = key;
          valueLabelEl.textContent = `Value for "${key}"`;
          const existing = (loc.attributes || []).find(it => it.key === key);
          valueInputEl.value = existing ? (existing.value || '') : '';
          valueRowEl.style.display = 'flex';
          try { valueInputEl.focus(); valueInputEl.select(); } catch(_) {}
        }
        function hideInlineValueEditor() {
          pendingValueKey = null;
          valueRowEl.style.display = 'none';
        }
        function commitInlineValue() {
          if (!pendingValueKey) return;
          ensureKVArray();
          const idx = loc.attributes.findIndex(it => it.key === pendingValueKey);
          if (idx >= 0) {
            const newVal = String(valueInputEl.value || '');
            loc.attributes[idx].value = newVal;
            if (newVal.trim() !== '') keysUsedWithValues.add(pendingValueKey);
          }
          hideInlineValueEditor();
          renderAttributesList();
        }
        valueSaveBtnEl.addEventListener('click', commitInlineValue);
        valueSkipBtnEl.addEventListener('click', () => hideInlineValueEditor());
        valueInputEl.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); commitInlineValue(); }
          if (e.key === 'Escape') { e.preventDefault(); hideInlineValueEditor(); }
        });
        
        // --- Custom markers (emoji) editor ---
        const markersHeading = document.createElement('div');
        markersHeading.className = 'heading';
        markersHeading.textContent = 'Map Icons';
        markersEditorEl = document.createElement('div');
        markersEditorEl.className = 'markers-editor';
        markersListEl = document.createElement('div');
        markersListEl.className = 'markers-list';
        const addRowMarkers = document.createElement('div');
        addRowMarkers.className = 'markers-add-row';
        // Emoji selector button opens a fast searchable picker
        const emojiButton = document.createElement('button');
        emojiButton.className = 'location-btn emoji-picker-btn';
        emojiButton.title = 'Choose icon';
        emojiButton.textContent = currentEmojiChoice;
        emojiButton.addEventListener('click', async (e) => {
          e.preventDefault();
          try {
            if (window.EmojiPicker && typeof window.EmojiPicker.open === 'function') {
              const chosen = await window.EmojiPicker.open(emojiButton, { initial: currentEmojiChoice });
              if (chosen) {
                currentEmojiChoice = chosen;
                emojiButton.textContent = currentEmojiChoice;
                // Update preview if present
                try {
                  if (map && map._tempPlaceMarker && map.hasLayer(map._tempPlaceMarker)) {
                    const html = `<div class=\"emoji-marker\">${escapeHtml(currentEmojiChoice)}</div>`;
                    const icon = L.divIcon({ html, className: 'emoji-marker-wrapper', iconSize: [24, 24], iconAnchor: [12, 12] });
                    map._tempPlaceMarker.setIcon(icon);
                  }
                  if (placeIconArmed) pendingEmoji = currentEmojiChoice;
                } catch(_) {}
              }
            } else {
              // Fallback: cycle common icons if picker not loaded
              const choices = ['📍','🅿️','🧗','🚰','🚻','🔥','⛺','📷','⚠️'];
              const idx = (choices.indexOf(currentEmojiChoice) + 1) % choices.length;
              currentEmojiChoice = choices[idx];
              emojiButton.textContent = currentEmojiChoice;
            }
          } catch(_) {}
        });
        markerLabelInput = document.createElement('input');
        markerLabelInput.placeholder = 'Hover text';
        markerLabelInput.className = 'add-attribute-input';
        // Replace manual lat/lng inputs with a map-click workflow
        const placeBtn = document.createElement('button');
        placeBtn.className = 'location-btn';
        placeBtn.textContent = 'Place on map';
        // No explicit Add button; adding happens on map click
        addMarkerBtn = null;
        addRowMarkers.appendChild(emojiButton);
        addRowMarkers.appendChild(markerLabelInput);
        addRowMarkers.appendChild(placeBtn);

        function renderMarkersList() {
          markersListEl.innerHTML = '';
          (extraMarkers || []).forEach((m, idx) => {
            const row = document.createElement('div');
            row.className = 'marker-row';
            row.innerHTML = `
              <span class="marker-emoji" title="${escapeHtml(m.label || '')}">${escapeHtml(m.emoji || '📍')}</span>
              <span class="marker-label" dir="auto">${escapeHtml(m.label || '')}</span>
              <button class="location-btn marker-remove">×</button>
            `;
            // selection highlight and click selection (view and edit modes)
            try { row.classList.toggle('selected', idx === selectedIndex); } catch(_) {}
            row.addEventListener('click', () => {
              selectedIndex = idx;
              renderMarkersList();
              if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
              try { createNavChangeParticles(navRow, 12); } catch(_) {}
            });
            // drag-and-drop reorder
            row.setAttribute('draggable', 'true');
            row.dataset.index = String(idx);
            row.addEventListener('dragstart', (e) => {
              dragSrcIndex = idx;
              try { if (e.dataTransfer) { e.dataTransfer.setData('text/plain', String(idx)); e.dataTransfer.effectAllowed = 'move'; } } catch(_) {}
              row.classList.add('dragging');
            });
            row.addEventListener('dragend', () => { row.classList.remove('dragging'); dragSrcIndex = null; });
            row.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('drag-over'); });
            row.addEventListener('dragleave', () => { row.classList.remove('drag-over'); });
            row.addEventListener('drop', (e) => {
              e.preventDefault();
              row.classList.remove('drag-over');
              const destAttr = row.dataset.index;
              const destIndex = destAttr ? parseInt(destAttr, 10) : -1;
              if (dragSrcIndex === null || destIndex < 0 || destIndex >= extraMarkers.length) return;
              const src = dragSrcIndex;
              let dest = destIndex;
              const [moved] = extraMarkers.splice(src, 1);
              if (dest > src) dest -= 1;
              extraMarkers.splice(dest, 0, moved);
              // ensure first is primary for compatibility
              try { extraMarkers = extraMarkers.map((it, i) => ({ ...it, primary: i === 0 })); } catch(_) {}
              if (typeof section._onMarkersChanged === 'function') section._onMarkersChanged(); else {
                renderMarkersList();
                if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
              }
            });
            row.querySelector('.marker-remove').addEventListener('click', () => {
              extraMarkers.splice(idx, 1);
              renderMarkersList();
              if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
            });
            markersListEl.appendChild(row);
          });
          // Clear temp preview after list changes
          try { if (map._tempPlaceMarker && map.hasLayer(map._tempPlaceMarker)) map.removeLayer(map._tempPlaceMarker); } catch(_) {}
        }
        function addMarkerFromInputs() {
          const emoji = pendingEmoji || currentEmojiChoice || '📍';
          const label = (pendingLabelValue || '').trim();
          if (!pendingMarkerPos) { alert('Click "Place on map" then tap the map to set a position.'); return; }
          extraMarkers.push({ emoji, label, lat: pendingMarkerPos.lat, lng: pendingMarkerPos.lng });
          markerLabelInput.value = '';
          pendingMarkerPos = null;
          pendingLabelValue = '';
          try { placeBtn.classList.remove('armed'); placeIconArmed = false; } catch(_) {}
          if (typeof section._onMarkersChanged === 'function') section._onMarkersChanged(); else {
            renderMarkersList();
            if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
          }
          // select newly added and hint nav change
          try { selectedIndex = Math.max(0, (extraMarkers?.length || 1) - 1); createNavChangeParticles(navRow, 14); } catch(_) {}
        }
        // Expose handlers so map click (defined elsewhere) can call them
        section._onMarkersChanged = function() {
          renderMarkersList();
          if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
        };
        section._addMarkerFromInputs = addMarkerFromInputs;
        placeBtn.addEventListener('click', () => {
          placeIconArmed = true;
          placeBtn.classList.add('armed');
          // Capture current inputs at the time of arming placement
          try {
            pendingLabelValue = (markerLabelInput.value || '').trim();
            pendingEmoji = currentEmojiChoice || '📍';
          } catch(_) {}
          // Ensure the map can receive clicks even if activation overlay is present
          try {
            mapViewport.style.pointerEvents = 'auto';
            mapViewport.style.touchAction = 'auto';
            if (mapOverlay) {
              mapOverlay.style.pointerEvents = 'none';
              mapOverlay.style.opacity = '0';
            }
          } catch(_) {}
        });
        // No add button; automatic add after map click (see map click handler)
        markersEditorEl.appendChild(markersHeading);
        markersEditorEl.appendChild(markersListEl);
        markersEditorEl.appendChild(addRowMarkers);
        renderMarkersList();
        // Mount the markers editor next to the map (under the map in the same column)
        try {
          mapCol.appendChild(markersEditorEl);
        } catch(_) { infoDiv.appendChild(markersEditorEl); }
        // Mount the attributes editor panel into the info column
        try {
          if (!attributesEditorEl.parentNode) infoDiv.appendChild(attributesEditorEl);
        } catch(_) {}
      }
    }
    
    function createNavChangeParticles(navRow, count = 12) {
      // Animate navigation buttons to show they've updated
      try {
        const buttons = navRow.querySelectorAll('.icon-btn');
        buttons.forEach((btn, idx) => {
          // Stagger the animation slightly for each button
          setTimeout(() => {
            btn.style.transform = 'scale(1.15)';
            btn.style.transition = 'transform 200ms ease-out';
            setTimeout(() => {
              btn.style.transform = 'scale(1)';
            }, 150);
            
            // Create particles from each button individually
            const btnRect = btn.getBoundingClientRect();
            const btnCx = btnRect.left + btnRect.width * 0.5;
            const btnCy = btnRect.top + btnRect.height * 0.5;
            const particlesPerButton = Math.max(2, Math.floor(count / buttons.length));
            
            for (let i = 0; i < particlesPerButton; i++) {
              const p = document.createElement('div');
              p.style.position = 'fixed';
              p.style.left = btnCx + 'px';
              p.style.top = btnCy + 'px';
              p.style.width = '4px';
              p.style.height = '4px';
              p.style.borderRadius = '50%';
              p.style.background = '#03dac6';
              p.style.pointerEvents = 'none';
              p.style.zIndex = '9999';
              p.style.opacity = '0.8';
              
              const ang = Math.random() * Math.PI * 2;
              const dist = 12 + Math.random() * 15;
              const dx = Math.cos(ang) * dist;
              const dy = Math.sin(ang) * dist;
              
              p.style.transform = 'translate(-50%, -50%) scale(1)';
              p.style.transition = 'transform 350ms ease-out, opacity 350ms ease-out';
              
              document.body.appendChild(p);
              
              // Slight delay for particles to create a burst effect
              setTimeout(() => {
                requestAnimationFrame(() => {
                  p.style.transform = `translate(${dx - 2}px, ${dy - 2}px) scale(0.2)`;
                  p.style.opacity = '0';
                });
              }, i * 20);
              
              setTimeout(() => { 
                if (p.parentNode) p.parentNode.removeChild(p); 
              }, 400);
            }
          }, idx * 30);
        });
      } catch(_) {}
    }

    function createRemovalParticles(container) {
      const rect = container.getBoundingClientRect();
      const cx = rect.width * 0.15; // left side burst
      const cy = rect.height * 0.5;
      const count = 10;
      
      // Create particles relative to viewport, not container
      for (let i = 0; i < count; i++) {
        const p = document.createElement('div');
        p.style.position = 'fixed';
        p.style.left = (rect.left + cx) + 'px';
        p.style.top = (rect.top + cy) + 'px';
        p.style.width = '8px';
        p.style.height = '8px';
        p.style.borderRadius = '50%';
        p.style.background = i % 2 ? '#ff4757' : '#ff6b6b';
        p.style.boxShadow = '0 0 12px rgba(255,71,87,0.9)';
        p.style.pointerEvents = 'none';
        p.style.zIndex = '9999';
        p.style.opacity = '1';
        
        const ang = Math.random() * Math.PI * 2;
        const dist = 20 + Math.random() * 25;
        const dx = Math.cos(ang) * dist;
        const dy = Math.sin(ang) * dist;
        
        p.style.transform = 'translate(-50%, -50%) scale(1)';
        p.style.transition = 'transform 300ms ease-out, opacity 300ms ease-out';
        
        document.body.appendChild(p);
        
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            p.style.transform = `translate(${dx - 4}px, ${dy - 4}px) scale(0.3)`;
            p.style.opacity = '0';
          });
        });
        
        setTimeout(() => { 
          if (p.parentNode) p.parentNode.removeChild(p); 
        }, 350);
      }
    }

      async function saveEdit() {
      const desc = (descTextarea?.value || '').trim();
      const approachVal = (approachTextarea?.value || '').trim();
        const payload = { description: desc, approach: approachVal, custom_markers: extraMarkers };
      const trimmedNewName = (nameInput?.value || '').trim();
      const isRenaming = !!trimmedNewName && trimmedNewName !== loc.name;
      if (isRenaming) {
        payload.new_name = trimmedNewName;
      }
        // latitude/longitude are now derived from primary emoji marker; do not send separately
      const targetName = encodeURIComponent(loc.name);
      const res = await fetch(`/api/locations?name=${targetName}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Failed to save');
      // Save attributes if changed
      try {
        if (Array.isArray(loc.attributes)) {
          // Ensure normalized payload as [{key,value}]
          const payloadAttrs = (loc.attributes || []).map(it => typeof it === 'string' ? { key: it, value: '' } : { key: String(it.key || ''), value: String(it.value || '') }).filter(it => it.key);
          const attrsTarget = isRenaming ? trimmedNewName : loc.name;
          await fetch(`/api/locations/attributes?name=${encodeURIComponent(attrsTarget)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ attributes: payloadAttrs })
          });
        }
      } catch (_) {}
      // Update local and UI
      if (isRenaming) {
        const oldName = loc.name;
        const newName = trimmedNewName;
        // Move albums mapping key
        if (albumsByLocation.has(oldName)) {
          const arr = albumsByLocation.get(oldName);
          albumsByLocation.delete(oldName);
          albumsByLocation.set(newName, arr);
        }
        // Update data and DOM identifiers
        loc.name = newName;
        section.setAttribute('data-name', newName);
        const newId = cssId(newName);
        section.id = newId;
        // Update title text and albums link
        const nameHolder = document.createElement('span');
        nameHolder.setAttribute('data-role', 'name-text');
        nameHolder.textContent = newName;
        if (nameInput && nameInput.parentNode) nameInput.replaceWith(nameHolder);
        const albumsLink = title.querySelector('[data-role="albums-link"]');
        if (albumsLink) albumsLink.href = `/albums?locations=${encodeURIComponent(newName)}`;
        // Update marker popup if present
        try { if (typeof section._initMap === 'function') { /* keep current marker; only update popup by re-init quickly */ } } catch(_) {}
      }
      loc.description = desc;
      loc.approach = approachVal;
      loc.custom_markers = Array.isArray(extraMarkers) ? JSON.parse(JSON.stringify(extraMarkers)) : [];
        // sync local primary coords for any consumers
        try {
          const p = section._getMarkerLatLng?.();
          if (p && Number.isFinite(p.lat) && Number.isFinite(p.lng)) { loc.latitude = p.lat; loc.longitude = p.lng; }
        } catch(_) {}
      exitEditMode();
    }

    function exitEditMode() {
      // Restore read-only view
      // Restore name input back to static span if still present
      if (nameInput && nameInput.parentNode) {
        const nameHolder = document.createElement('span');
        nameHolder.setAttribute('data-role', 'name-text');
        nameHolder.textContent = loc.name;
        nameInput.replaceWith(nameHolder);
      }
      const newDesc = document.createElement('div');
      newDesc.className = 'description-text';
      newDesc.setAttribute('dir', 'auto');
      newDesc.textContent = (loc.description && String(loc.description).trim()) || `No description yet for ${loc.name}.`;
      if (descTextarea && descTextarea.parentNode) {
        descTextarea.replaceWith(newDesc);
      }

      const newApproach = document.createElement('div');
      newApproach.className = 'approach-text';
      newApproach.setAttribute('dir', 'auto');
      newApproach.textContent = (loc.approach && String(loc.approach).trim()) || `No approach info yet for ${loc.name}. Add a note when you tag albums here.`;
      if (approachTextarea && approachTextarea.parentNode) {
        approachTextarea.replaceWith(newApproach);
      }

      isEditing = false;
      if (editBtn) editBtn.textContent = 'Edit';
      if (cancelBtn) cancelBtn.style.display = 'none';
      section.classList.remove('editing');
      // Remove attributes editor UI if present
      if (attributesEditorEl && attributesEditorEl.parentNode) {
        attributesEditorEl.parentNode.removeChild(attributesEditorEl);
      }
      // Ensure stray markers editor is removed if it was moved elsewhere
      if (markersEditorEl && markersEditorEl.parentNode) {
        markersEditorEl.parentNode.removeChild(markersEditorEl);
      }
      renderAttributesList();
      // Restore albums counter/link visibility
      const albumsLinkEl = title.querySelector('[data-role="albums-link"]');
      if (albumsLinkEl) {
        albumsLinkEl.style.display = albumsLinkEl.dataset.prevDisplay ?? '';
        delete albumsLinkEl.dataset.prevDisplay;
      }
      if (typeof section._setMarkerDraggable === 'function') {
        section._setMarkerDraggable(false);
      }
      // Cleanup edit-only state: remove preview, reset pending/armed, clear selection to primary
      try {
        if (map && map._tempPlaceMarker && map.hasLayer(map._tempPlaceMarker)) {
          map.removeLayer(map._tempPlaceMarker);
          map._tempPlaceMarker = null;
        }
      } catch(_) {}
      placeIconArmed = false; pendingMarkerPos = null; pendingLabelValue = ''; pendingEmoji = '📍';
      try {
        selectedIndex = 0;
        if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(loc.custom_markers || []);
      } catch(_) {}
    }

    if (editBtn) {
      editBtn.addEventListener('click', async () => {
        if (!isEditing) {
          enterEditMode();
        } else {
          try { await saveEdit(); } catch (e) { alert(e.message || 'Failed to save'); }
        }
      });
    }
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => exitEditMode());
    }

    if (deleteBtn) {
      deleteBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        try { await handleDeleteLocation(loc, section); } catch (err) { alert(err?.message || 'Failed to delete'); }
      });
    }

    // Expose map initializer to run after the element is in the DOM
    section._initMap = function initLeaflet() {
      // Initialize leaflet map; avoid showing a wrong default like London when coords are missing
      const map = L.map(mapViewport, { zoomControl: false, attributionControl: false });
      // Define marker refresh early so initial calls render markers in view mode too
      section._refreshExtraMarkers = function(markers) {
        try {
          // Clear only our emoji markers by tracking className on the icon
          map.eachLayer(layer => {
            try {
              if (layer instanceof L.Marker && layer.getIcon && layer.getIcon().options && layer.getIcon().options.className && layer.getIcon().options.className.includes('emoji-marker-wrapper')) {
                map.removeLayer(layer);
              }
            } catch(_) {}
          });
          const list = Array.isArray(markers) ? markers : [];
          list.forEach((m, idx) => {
            if (!Number.isFinite(m.lat) || !Number.isFinite(m.lng)) return;
            const isSelected = idx === selectedIndex;
            const html = `<div class="emoji-marker" title="${escapeHtml(m.label || '')}">${escapeHtml(m.emoji || '📍')}</div>`;
            const icon = L.divIcon({ html, className: 'emoji-marker-wrapper' + (isSelected ? ' selected' : ''), iconSize: [24, 24], iconAnchor: [12, 12] });
            const layer = L.marker([m.lat, m.lng], { icon, draggable: section.classList.contains('editing'), riseOnHover: true }).addTo(map);
            try {
              if (layer.dragging) {
                if (section.classList.contains('editing')) layer.dragging.enable(); else layer.dragging.disable();
              }
            } catch(_) {}
            layer._extraIdx = idx;
            if (m.label) layer.bindTooltip(m.label, { direction: 'top', offset: [0, -6] });
            layer.on('click', (ev) => {
              try {
                // Prevent bubbling to any global click handlers that might clear selection
                if (ev && ev.originalEvent && typeof ev.originalEvent.stopPropagation === 'function') {
                  ev.originalEvent.stopPropagation();
                }
                if (typeof L !== 'undefined' && L.DomEvent && typeof L.DomEvent.stopPropagation === 'function') {
                  L.DomEvent.stopPropagation(ev);
                }
              } catch(_) {}
              selectedIndex = idx;
              // Update both the editor list and map markers to show new selection
              if (typeof renderMarkersList === 'function') renderMarkersList();
              const currentList = (Array.isArray(extraMarkers) && extraMarkers.length) ? extraMarkers : (loc.custom_markers || []);
              if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(currentList);
              try { createNavChangeParticles(navRow, 14); } catch(_) {}
              
              // Select the location card and sync URL with both location and selected icon
              clearAllSelections();
              section.classList.add('selected');
              const url = new URL(window.location);
              url.searchParams.set('highlight', loc.name);
              if (m.label && m.label.trim()) {
                url.searchParams.set('selected_map_icon', m.label.trim());
              } else if (m.emoji) {
                url.searchParams.set('selected_map_icon', m.emoji);
              }
              history.pushState({}, '', url.toString());
              scrollSectionIntoViewTop(section);
            });
            layer.on('dragend', () => {
              try {
                const pos = layer.getLatLng();
                if (Array.isArray(extraMarkers) && typeof layer._extraIdx === 'number') {
                  if (!extraMarkers[layer._extraIdx]) return;
                  extraMarkers[layer._extraIdx].lat = pos.lat;
                  extraMarkers[layer._extraIdx].lng = pos.lng;
                  // Re-render to update tooltips/positions
                  if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
                }
              } catch(_) {}
            });
          });
        } catch (_) { /* ignore */ }
      };
      // Improve mobile scrolling: two-finger pan/zoom for map, single-finger scrolls page
      (function setupTouchGestureHandling() {
        try {
          const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
          if (!isTouch) return;
          // Make map viewport allow vertical page scroll by default
          mapViewport.style.touchAction = 'pan-y';
          mapViewport.style.pointerEvents = 'auto';
          // Disable overlay on touch devices; keep non-blocking hint if desired
          if (mapOverlay) {
            mapOverlay.style.pointerEvents = 'none';
            mapOverlay.style.opacity = '0';
          }
          // Disable map interactions until two fingers are used
          try { map.dragging.disable(); } catch(_) {}
          try { if (map.touchZoom) map.touchZoom.disable(); } catch(_) {}
          try { map.scrollWheelZoom.disable(); } catch(_) {}
          try { map.doubleClickZoom.disable(); } catch(_) {}
          // Toggle dragging/zoom on two-finger gesture
          const onTouchChange = (e) => {
            try {
              const touches = e.touches ? e.touches.length : 0;
              if (touches >= 2) {
                if (isLocationEditableByCurrentUser(loc)) {
                  // When editing we still respect emoji marker drag toggles, but allow map pan/zoom with two fingers
                  if (map.dragging && !map.dragging.enabled()) map.dragging.enable();
                  if (map.touchZoom && !map.touchZoom.enabled()) map.touchZoom.enable();
                } else {
                  if (map.dragging && !map.dragging.enabled()) map.dragging.enable();
                  if (map.touchZoom && !map.touchZoom.enabled()) map.touchZoom.enable();
                }
              } else {
                if (map.dragging && map.dragging.enabled()) map.dragging.disable();
                if (map.touchZoom && map.touchZoom.enabled()) map.touchZoom.disable();
              }
            } catch(_) {}
          };
          mapViewport.addEventListener('touchstart', onTouchChange, { passive: true });
          mapViewport.addEventListener('touchend', onTouchChange, { passive: true });
          mapViewport.addEventListener('touchcancel', onTouchChange, { passive: true });
        } catch(_) {}
      })();
      function getPrimaryMarkerIndex(list) {
        if (!Array.isArray(list)) return -1;
        let idx = list.findIndex(m => m && m.primary === true);
        if (idx >= 0) return idx;
        // Fallback: if any markers exist, treat first as primary
        return list.length > 0 ? 0 : -1;
      }
      function ensurePrimaryMarker(list, lat, lng) {
        if (!Array.isArray(list)) return [];
        const result = list.slice();
        let idx = getPrimaryMarkerIndex(result);
        if (idx === -1 && Number.isFinite(lat) && Number.isFinite(lng)) {
          result.push({ emoji: '🅿️', label: 'Parking', lat, lng, primary: true });
          idx = result.length - 1;
        } else if (idx >= 0) {
          // Backfill a sensible default label for primary if missing
          try {
            if (!result[idx].label || String(result[idx].label).trim() === '') {
              result[idx].label = 'Parking';
            }
          } catch(_) {}
        }
        return result;
      }
      function getStartLatLng() {
        const list = Array.isArray(loc.custom_markers) ? loc.custom_markers : [];
        const pidx = getPrimaryMarkerIndex(list);
        if (pidx >= 0) {
          const pm = list[pidx];
          if (Number.isFinite(pm.lat) && Number.isFinite(pm.lng)) return { lat: pm.lat, lng: pm.lng };
        }
        if (Number.isFinite(loc.latitude) && Number.isFinite(loc.longitude)) return { lat: loc.latitude, lng: loc.longitude };
        return null;
      }
      const startPos = getStartLatLng();
      const hasCoords = !!startPos;
      // initialize selection to primary/top on load only if markers exist
      try {
        const listForInit = Array.isArray(loc.custom_markers) ? loc.custom_markers : [];
        selectedIndex = listForInit.length > 0 ? 0 : -1;
      } catch(_) {}
      let marker = null; // legacy main marker not used anymore
      let tilesAdded = false;
      if (hasCoords) {
        const start = [startPos.lat, startPos.lng];
        const zoom = 13;
        map.setView(start, zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap'
        }).addTo(map);
        tilesAdded = true;
        // Ensure a primary emoji marker exists at start position if none
        try {
          const current = Array.isArray(loc.custom_markers) ? loc.custom_markers : [];
          loc.custom_markers = ensurePrimaryMarker(current, startPos.lat, startPos.lng);
          extraMarkers = JSON.parse(JSON.stringify(loc.custom_markers));
          if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
        } catch(_) {}
      } else {
        // No coords yet: initialize tiles immediately so the map is visible
        try {
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap'
          }).addTo(map);
          tilesAdded = true;
          // Neutral world view until geocode resolves
          map.setView([0, 0], 2);
          if (mapOverlay) mapOverlay.innerHTML = '<div class="hint">Tap to interact</div>';
        } catch(_) {}
      }
      // Provide a toggler and getter to control dragging only during edit
      section._setMarkerDraggable = function(enabled) {
        try {
          if (marker && marker.dragging) {
            if (enabled && isLocationEditableByCurrentUser(loc)) marker.dragging.enable(); else marker.dragging.disable();
          }
          // Sync emoji markers' dragging as well
          map.eachLayer(layer => {
            try {
              const isEmoji = (layer instanceof L.Marker) && layer.getIcon && layer.getIcon().options && String(layer.getIcon().options.className || '').includes('emoji-marker-wrapper');
              if (isEmoji && layer.dragging) {
                if (enabled && isLocationEditableByCurrentUser(loc)) layer.dragging.enable(); else layer.dragging.disable();
              }
            } catch(_) {}
          });
          // Keep selection visible in both modes
          if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
        } catch (_) {}
      };
      section._getMarkerLatLng = function() {
        try {
          const list = Array.isArray(extraMarkers) ? extraMarkers : (Array.isArray(loc.custom_markers) ? loc.custom_markers : []);
          const idx = Number.isFinite(selectedIndex) ? selectedIndex : getPrimaryMarkerIndex(list);
          if (idx >= 0 && idx < list.length) {
            const pm = list[idx];
            if (Number.isFinite(pm.lat) && Number.isFinite(pm.lng)) return { lat: pm.lat, lng: pm.lng };
          }
          return null;
        } catch (_) { return null; }
      };
      // Click-to-place for extra markers while editing
      map.on('click', (e) => {
        if (!section.classList.contains('editing')) return;
        if (!placeIconArmed) return;
        pendingMarkerPos = { lat: e.latlng.lat, lng: e.latlng.lng };
        try { placeIconArmed = false; } catch(_) {}
        // Give user visual feedback: drop a temporary preview marker
        try {
          const html = `<div class=\"emoji-marker\">${escapeHtml((pendingEmoji || currentEmojiChoice || '📍'))}</div>`;
          const icon = L.divIcon({ html, className: 'emoji-marker-wrapper', iconSize: [24, 24], iconAnchor: [12, 12] });
          // Remove previous temp if exists
          if (map._tempPlaceMarker && map.hasLayer(map._tempPlaceMarker)) map.removeLayer(map._tempPlaceMarker);
          map._tempPlaceMarker = L.marker([pendingMarkerPos.lat, pendingMarkerPos.lng], { icon, draggable: true, riseOnHover: true }).addTo(map);
          // Allow dragging preview to fine-tune
          if (map._tempPlaceMarker.dragging) map._tempPlaceMarker.dragging.enable();
          map._tempPlaceMarker.on('drag', () => {
            try {
              const p = map._tempPlaceMarker.getLatLng();
              pendingMarkerPos = { lat: p.lat, lng: p.lng };
            } catch(_) {}
          });
        } catch(_) {}
        // Automatically add the icon now that it has been placed
        try { if (typeof section._addMarkerFromInputs === 'function') section._addMarkerFromInputs(); else addMarkerFromInputs(); } catch(_) {}
      });
      section._setMarkerDraggable(false);
      // Ensure markers render (with selection) for current mode
      try {
        const list = (Array.isArray(extraMarkers) && extraMarkers.length) ? extraMarkers : (loc.custom_markers || []);
        if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(list);
      } catch(_) {}
      // Resize map when section becomes visible
      setTimeout(() => map.invalidateSize(), 200);
      window.addEventListener('resize', () => map.invalidateSize());

      // Geocoding utilities (must be defined before first use)
      const geocodeCache = (window.__geocodeCache ||= new Map());
      const geocodeFailures = (window.__geocodeFailures ||= new Map());
      let geocodeInFlight = 0;
      const GEOCODE_MAX_CONCURRENCY = 5;
      const GEOCODE_TIMEOUT_MS = 13000;
      const GEOCODE_RETRY_AFTER_MS = 20 * 1000; // shorter negative cache (20s)
      async function geocodeByName(name, opts = {}) {
        const key = String(name || '').trim();
        if (!key) return null;
        if (geocodeCache.has(key)) return geocodeCache.get(key);
        const ignoreFailureCache = !!opts.ignoreFailureCache;
        const failedAt = geocodeFailures.get(key);
        if (!ignoreFailureCache) {
          const GEOCODE_RETRY_AFTER_MS = 20000;
          if (failedAt && (Date.now() - failedAt) < GEOCODE_RETRY_AFTER_MS) {
            return null;
          }
        }
        // Build fallback queries similar to stage
        const queries = [];
        queries.push(key);
        if (!/\bIsrael\b/i.test(key)) queries.push(`${key} Israel`);
        if (/gilabon/i.test(key)) queries.push(key.replace(/gilabon/ig, 'Gilbon'));
        if (/gilbon/i.test(key)) queries.push(key.replace(/gilbon/ig, 'Gilabon'));
        const seenQ = new Set();
        const toTry = queries.filter(q => { const s = q.trim(); if (!s || seenQ.has(s.toLowerCase())) return false; seenQ.add(s.toLowerCase()); return true; });

        while (geocodeInFlight >= GEOCODE_MAX_CONCURRENCY) {
          await new Promise(r => setTimeout(r, 100));
        }
        geocodeInFlight++;
        try {
          for (const q of toTry) {
            try {
              const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`;
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), GEOCODE_TIMEOUT_MS);
              const res = await fetch(url, { headers: { 'Accept': 'application/json' }, cache: 'no-store', signal: controller.signal });
              clearTimeout(timeoutId);
              if (!res.ok) continue;
              const arr = await res.json();
              const result = Array.isArray(arr) && arr.length > 0 ? arr[0] : null;
              if (result) { geocodeCache.set(key, result); return result; }
            } catch (err) {
              // Timeout/abort or transient failure; try next fallback query
              continue;
            }
          }
          geocodeFailures.set(key, Date.now());
          return null;
        } finally {
          geocodeInFlight = Math.max(0, geocodeInFlight - 1);
        }
      }

      // If no coords present, geocode by name and set view & inputs (with timeout fallback)
      if (!hasCoords) {
        const ensureTiles = () => {
          if (!tilesAdded) {
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
              maxZoom: 19,
              attribution: '&copy; OpenStreetMap'
            }).addTo(map);
            tilesAdded = true;
          }
        };
        const fallbackTimer = setTimeout(() => {
          try {
            ensureTiles();
            // Set a gentle world view to avoid an empty container
            const z = map.getZoom();
            if (!Number.isFinite(z) || z <= 1) map.setView([0, 0], 2);
            if (mapOverlay) mapOverlay.innerHTML = '<div class="hint">Tap to interact</div>';
          } catch(_) {}
        }, 2000);
        geocodeByName(loc.name).then(result => {
          if (!result) return;
          const lat = parseFloat(result.lat), lon = parseFloat(result.lon);
          if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
          ensureTiles();
          map.setView([lat, lon], 13);
          // Ensure we have a primary emoji marker at geocoded position
          try {
            const current = Array.isArray(loc.custom_markers) ? loc.custom_markers : [];
            loc.custom_markers = ensurePrimaryMarker(current, lat, lon);
            extraMarkers = JSON.parse(JSON.stringify(loc.custom_markers));
            if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
          } catch(_) {}
          section._setMarkerDraggable = function(enabled) {
            try {
              // Toggle emoji marker dragging in edit mode
              map.eachLayer(layer => {
                try {
                  const isEmoji = (layer instanceof L.Marker) && layer.getIcon && layer.getIcon().options && String(layer.getIcon().options.className || '').includes('emoji-marker-wrapper');
                  if (isEmoji && layer.dragging) {
                    if (enabled && isLocationEditableByCurrentUser(loc)) layer.dragging.enable(); else layer.dragging.disable();
                  }
                } catch(_) {}
              });
            } catch (_) {}
          };
          section._getMarkerLatLng = function() {
            try {
              const list = Array.isArray(extraMarkers) ? extraMarkers : (Array.isArray(loc.custom_markers) ? loc.custom_markers : []);
              const pidx = getPrimaryMarkerIndex(list);
              if (pidx >= 0) {
                const pm = list[pidx];
                if (Number.isFinite(pm.lat) && Number.isFinite(pm.lng)) return { lat: pm.lat, lng: pm.lng };
              }
              return null;
            } catch (_) { return null; }
          };
          section._setMarkerDraggable(false);
        }).catch(() => {}).finally(() => { try { clearTimeout(fallbackTimer); } catch(_) {} });
        // After initial pass completes across all sections, schedule a re-try for misses
        try {
          const RETRY_DELAY_MS = 16000;
          setTimeout(async () => {
            try {
              const current = section._getMarkerLatLng?.();
              if (!current) {
                const again = await geocodeByName(loc.name, { ignoreFailureCache: true });
                if (again && Number.isFinite(parseFloat(again.lat)) && Number.isFinite(parseFloat(again.lon))) {
                  const lat = parseFloat(again.lat), lon = parseFloat(again.lon);
                  if (!tilesAdded) {
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                      maxZoom: 19,
                      attribution: '&copy; OpenStreetMap'
                    }).addTo(map);
                    tilesAdded = true;
                  }
                  map.setView([lat, lon], 13);
                  try {
                    const curr = Array.isArray(loc.custom_markers) ? loc.custom_markers : [];
                    loc.custom_markers = ensurePrimaryMarker(curr, lat, lon);
                    extraMarkers = JSON.parse(JSON.stringify(loc.custom_markers));
                    if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(extraMarkers);
                  } catch(_) {}
                }
              }
            } catch(_) {}
          }, RETRY_DELAY_MS);
        } catch(_) {}
      }

      // (geocoding helpers declared earlier in this function)
      // Map activation (desktop): require tap/click to enable panning/zooming
      let mapActive = false;
      function activateMap() {
        if (mapActive) return;
        // If still loading geocode, ignore activation clicks
        try {
          if (mapOverlay && mapOverlay.querySelector('.loading-container')) return;
        } catch(_) {}
        mapActive = true;
        mapViewport.style.pointerEvents = 'auto';
        mapViewport.style.touchAction = 'auto';
        // On touch devices we already handle gestures; skip overlay removal animation
        const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
        if (!isTouch && mapOverlay && mapOverlay.parentNode) {
          // Start fade out immediately but don't remove yet
          mapOverlay.style.pointerEvents = 'none';
          mapOverlay.style.transition = 'opacity 300ms ease-out';
          mapOverlay.style.opacity = '0';
          
          // Create burst particles after starting the fade, with higher z-index
          setTimeout(() => {
            createBurstParticles(mapDiv, 18);
          }, 50);
          
          // Remove overlay after burst animation completes
          setTimeout(() => { 
            if (mapOverlay && mapOverlay.parentNode) mapOverlay.remove(); 
          }, 700);
        } else {
          // No overlay, just create burst
          createBurstParticles(mapDiv, 18);
        }
      }
      try {
        const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
        if (!isTouch) {
          mapOverlay.addEventListener('click', activateMap);
        }
      } catch(_) {}

      function createBurstParticles(container, count = 12) {
        const rect = container.getBoundingClientRect();
        const cx = rect.width / 2, cy = rect.height / 2;
        for (let i = 0; i < count; i++) {
          const p = document.createElement('div');
          p.style.position = 'absolute';
          p.style.left = cx + 'px';
          p.style.top = cy + 'px';
          p.style.width = '12px'; 
          p.style.height = '12px'; 
          p.style.borderRadius = '50%';
          p.style.background = i % 2 ? '#bb86fc' : '#03dac6';
          p.style.boxShadow = '0 0 12px rgba(187,134,252,0.9)';
          p.style.zIndex = '999'; // Much higher z-index to ensure visibility
          p.style.pointerEvents = 'none';
          const ang = Math.random() * Math.PI * 2;
          const dist = 40 + Math.random() * 60;
          const dx = Math.cos(ang) * dist;
          const dy = Math.sin(ang) * dist;
          p.style.transform = `translate(-50%, -50%)`;
          p.style.transition = 'transform 500ms ease-out, opacity 500ms ease-out';
          container.appendChild(p);
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              p.style.transform = `translate(${dx}px, ${dy}px)`;
              p.style.opacity = '0';
            });
          });
          setTimeout(() => { if (p.parentNode) p.parentNode.removeChild(p); }, 600);
        }
      }
      // Initial markers render now happens via earlier-defined _refreshExtraMarkers when called above
      
      // Function to restore icon selection from URL
      section._restoreIconSelection = function(iconIdentifier) {
        try {
          const currentMarkers = (Array.isArray(extraMarkers) && extraMarkers.length) ? extraMarkers : (loc.custom_markers || []);
          let foundIndex = -1;
          
          // Try to find marker by label first, then by emoji
          for (let i = 0; i < currentMarkers.length; i++) {
            const marker = currentMarkers[i];
            if ((marker.label && marker.label.trim() === iconIdentifier) || 
                (marker.emoji === iconIdentifier)) {
              foundIndex = i;
              break;
            }
          }
          
          if (foundIndex >= 0) {
            selectedIndex = foundIndex;
            // Update both visual displays
            if (typeof renderMarkersList === 'function') renderMarkersList();
            if (typeof section._refreshExtraMarkers === 'function') section._refreshExtraMarkers(currentMarkers);
            // Trigger navigation button animation
            try { createNavChangeParticles(navRow, 14); } catch(_) {}
          }
        } catch(_) {}
      };
    }
    return section;
  }

  function clearAllSelections() {
    const all = container.querySelectorAll('.location-section.selected');
    all.forEach(s => s.classList.remove('selected'));
  }

  function normalizeName(name) {
    return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  function toggleSelection(section, name) {
    const isSelected = section.classList.contains('selected');
    const url = new URL(window.location);
    
    // Don't unselect if clicking the same card - just ensure it stays selected
    if (isSelected) {
      // Already selected, keep it selected
      return;
    }
    
    // Clear other selections and select this one
    clearAllSelections();
    section.classList.add('selected');
    url.searchParams.set('highlight', name);
    history.pushState({}, '', url.toString());
    // Bring the section's top into view (accounting for fixed nav)
    scrollSectionIntoViewTop(section);
  }

  function applySelectionFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const highlight = params.get('highlight');
    const selectedMapIcon = params.get('selected_map_icon');
    
    if (highlight) {
      const norm = normalizeName(highlight);
      const sections = Array.from(container.querySelectorAll('.location-section'));
      for (const sec of sections) {
        const name = sec.getAttribute('data-name') || '';
        if (normalizeName(name) === norm) {
          clearAllSelections();
          sec.classList.add('selected');
          
          // If there's a selected map icon, try to restore that selection too
          if (selectedMapIcon && typeof sec._initMap === 'function') {
            // Wait for map to be initialized, then find and select the matching icon
            setTimeout(() => {
              try {
                if (typeof sec._restoreIconSelection === 'function') {
                  sec._restoreIconSelection(selectedMapIcon);
                }
              } catch(_) {}
            }, 100);
          }
          
          scrollSectionIntoViewTop(sec);
          return;
        }
      }
    }
    // Backward compatibility: support hash deep link (#id)
    if (window.location.hash) {
      const id = window.location.hash.slice(1);
      if (id) {
        const sec = document.getElementById(id);
        if (sec && sec.classList.contains('location-section')) {
          clearAllSelections();
          sec.classList.add('selected');
          // Normalize URL to use highlight query param instead of hash
          const name = sec.getAttribute('data-name') || id;
          const url = new URL(window.location);
          url.hash = '';
          url.searchParams.set('highlight', name);
          history.replaceState({}, '', url.toString());
          scrollSectionIntoViewTop(sec);
        }
      }
    }
  }

  window.addEventListener('popstate', () => {
    clearAllSelections();
    applySelectionFromUrl();
    applyFilterFromUrl();
  });

  function createMiniAlbumCard(meta) {
    const a = document.createElement('a');
    a.className = 'mini-album-card';
    a.href = meta.url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';

    const proxyImageUrl = `/get-image?url=${encodeURIComponent(meta.imageUrl)}`;
    a.innerHTML = `
      <img class="mini-album-img" src="${proxyImageUrl}" alt="${escapeHtml(meta.title || '')}" loading="lazy" onerror="this.style.display='none'">
      <div class="mini-album-content">
        <div class="mini-album-title" dir="auto">${escapeHtml(meta.title || 'Album')}</div>
        <div class="mini-album-sub" dir="auto">${escapeHtml(meta.date || '')}</div>
      </div>
    `;
    return a;
  }

  function isLocationEditableByCurrentUser(loc) {
    if (!currentUser) return false;
    const role = (currentUser.role || 'user');
    if (role === 'admin') return true;
    const owners = Array.isArray(loc.owners) ? loc.owners : [];
    return owners.includes(currentUser.id);
  }

  function isLocationDeletableByCurrentUser(loc) {
    if (!currentUser) return false;
    const role = (currentUser.role || 'user');
    if (role === 'admin') return true;
    const owners = Array.isArray(loc.owners) ? loc.owners : [];
    return owners.includes(currentUser.id);
  }

  // Removed legacy saveLocation/claimLocation helpers (edit flow uses inline save and owner claim via API elsewhere)

  function cssId(name) { return String(name).replace(/[^a-z0-9]+/gi, '-').toLowerCase(); }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  async function handleDeleteLocation(loc, sectionEl) {
    const name = loc.name;
    const firstConfirm = window.confirm(`Delete location "${name}"? This action cannot be undone.`);
    if (!firstConfirm) return;

    const baseUrl = `/api/locations?name=${encodeURIComponent(name)}`;
    let res = await fetch(baseUrl, { method: 'DELETE' });
    if (res.ok) {
      await applyLocationDeletionClientSide(loc, sectionEl, null);
      return;
    }
    if (res.status === 409) {
      let detail;
      try { detail = await res.json(); } catch { detail = null; }
      const blocked = detail?.detail?.blocked_by_albums ?? detail?.blocked_by_albums ?? 0;
      const instruction = `There are ${blocked} album(s) tagged to this location.\n` +
        `- Type 'clear' to remove the location tag from those albums, OR\n` +
        `- Type another existing location name to reassign those albums, OR\n` +
        `- Leave blank to cancel.`;
      const answer = window.prompt(instruction, 'clear');
      if (!answer) return;
      let finalUrl = baseUrl;
      let reassignedTo = null;
      if (answer.trim().toLowerCase() === 'clear') {
        finalUrl += `&force_clear=true`;
      } else {
        // Validate target exists
        const target = (locations || []).find(l => String(l.name || '').toLowerCase() === answer.trim().toLowerCase());
        if (!target) { alert('Target location not found'); return; }
        if (target.name === name) { alert('Cannot reassign to the same location'); return; }
        reassignedTo = target.name;
        finalUrl += `&reassign_to=${encodeURIComponent(reassignedTo)}`;
      }
      res = await fetch(finalUrl, { method: 'DELETE' });
      if (!res.ok) {
        const msg = await res.text().catch(() => '');
        throw new Error(msg || 'Failed to delete');
      }
      await applyLocationDeletionClientSide(loc, sectionEl, reassignedTo);
      return;
    }
    const msg = await res.text().catch(() => '');
    throw new Error(msg || 'Failed to delete');
  }

  async function applyLocationDeletionClientSide(loc, sectionEl, reassignedTo) {
    // Update albumsByLocation mapping
    const oldName = loc.name;
    const movedAlbums = albumsByLocation.get(oldName) || [];
    if (reassignedTo) {
      const existing = albumsByLocation.get(reassignedTo) || [];
      const merged = existing.concat(movedAlbums);
      // De-duplicate by url if present
      const seen = new Set();
      const dedup = [];
      for (const meta of merged) {
        const key = meta.url || `${meta.title}|${meta.date}`;
        if (seen.has(key)) continue;
        seen.add(key);
        dedup.push(meta);
      }
      albumsByLocation.set(reassignedTo, dedup);
    }
    albumsByLocation.delete(oldName);

    // Remove from locations list
    locations = (locations || []).filter(l => l.name !== oldName);

    // Remove DOM section
    if (sectionEl && sectionEl.parentNode) sectionEl.parentNode.removeChild(sectionEl);

    // Update count label
    const sections = Array.from(container.querySelectorAll('[data-location-section]'));
    updateCount(sections.length, sections.length);
  }
});


