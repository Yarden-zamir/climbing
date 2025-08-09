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

  init();

  async function init() {
    try {
      // Load canonical locations and enriched albums
      const [userRes, locRes, albumsRes] = await Promise.all([
        fetch('/api/auth/user?_t=' + Date.now()),
        fetch('/api/locations?_t=' + Date.now()),
        fetch('/api/albums/enriched?_t=' + Date.now()),
      ]);
      if (userRes.ok) {
        const u = await userRes.json();
        currentUser = u && u.authenticated ? (u.user || null) : null;
      }
      if (!locRes.ok) throw new Error('Failed to load locations');
      if (!albumsRes.ok) throw new Error('Failed to load albums');

      const locs = await locRes.json();
      const enrichedAlbums = await albumsRes.json();

      // Normalize locations: [{ name, description }]
      locations = (Array.isArray(locs) ? locs : []).map(l => ({
        name: l.name || String(l || ''),
        description: l.description || '',
        approach: l.approach || '',
        latitude: parseFloat(l.latitude || ''),
        longitude: parseFloat(l.longitude || ''),
        owners: Array.isArray(l.owners) ? l.owners : [],
      })).filter(l => l.name);

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

    function enterEditMode() {
      if (isEditing) return;
      isEditing = true;
      if (editBtn) editBtn.textContent = '💾';
      if (cancelBtn) cancelBtn.style.display = '';
      // Hide albums counter/link while editing to reduce header clutter on mobile
      const albumsLinkEl = title.querySelector('[data-role="albums-link"]');
      if (albumsLinkEl) {
        albumsLinkEl.dataset.prevDisplay = albumsLinkEl.style.display || '';
        albumsLinkEl.style.display = 'none';
      }
      // Replace name with input and text with textareas (re-query current read-only nodes each time)
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
    }

    async function saveEdit() {
      const desc = (descTextarea?.value || '').trim();
      const approachVal = (approachTextarea?.value || '').trim();
      const payload = { description: desc, approach: approachVal };
      const trimmedNewName = (nameInput?.value || '').trim();
      const isRenaming = !!trimmedNewName && trimmedNewName !== loc.name;
      if (isRenaming) {
        payload.new_name = trimmedNewName;
      }
      if (typeof section._getMarkerLatLng === 'function') {
        const pos = section._getMarkerLatLng();
        if (pos && Number.isFinite(pos.lat) && Number.isFinite(pos.lng)) {
          payload.latitude = pos.lat;
          payload.longitude = pos.lng;
        }
      }
      const targetName = encodeURIComponent(loc.name);
      const res = await fetch(`/api/locations?name=${targetName}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Failed to save');
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
      if (typeof payload.latitude === 'number' && typeof payload.longitude === 'number') {
        loc.latitude = payload.latitude;
        loc.longitude = payload.longitude;
      }
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
      // Restore albums counter/link visibility
      const albumsLinkEl = title.querySelector('[data-role="albums-link"]');
      if (albumsLinkEl) {
        albumsLinkEl.style.display = albumsLinkEl.dataset.prevDisplay ?? '';
        delete albumsLinkEl.dataset.prevDisplay;
      }
      if (typeof section._setMarkerDraggable === 'function') {
        section._setMarkerDraggable(false);
      }
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
      const hasCoords = Number.isFinite(loc.latitude) && Number.isFinite(loc.longitude);
      let marker = null;
      let tilesAdded = false;
      if (hasCoords) {
        const start = [loc.latitude, loc.longitude];
        const zoom = 13;
        map.setView(start, zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap'
        }).addTo(map);
        tilesAdded = true;
        marker = L.marker(start, { draggable: false }).addTo(map);
        marker.bindPopup(`<b>${escapeHtml(loc.name)}</b>`);
        if (isLocationEditableByCurrentUser(loc)) {
          const updateInputs = () => {
            const { lat, lng } = marker.getLatLng();
            const latInput = document.getElementById(`lat-${cssId(loc.name)}`);
            const lngInput = document.getElementById(`lng-${cssId(loc.name)}`);
            if (latInput) latInput.value = lat.toFixed(6);
            if (lngInput) lngInput.value = lng.toFixed(6);
          };
          marker.on('drag', updateInputs);
          marker.on('dragend', updateInputs);
        }
      } else {
        // Show cooler loading animation until geocoding resolves
        try {
          ensureLoadingStyles();
          if (mapOverlay) mapOverlay.innerHTML = '<div class="loading-container"><div class="spinner"></div></div>';
        } catch(_) {}
      }
      // Provide a toggler and getter to control dragging only during edit
      section._setMarkerDraggable = function(enabled) {
        try {
          if (marker && marker.dragging) {
            if (enabled && isLocationEditableByCurrentUser(loc)) marker.dragging.enable(); else marker.dragging.disable();
          }
        } catch (_) {}
      };
      section._getMarkerLatLng = function() {
        try { return marker && marker.getLatLng ? marker.getLatLng() : null; } catch (_) { return null; }
      };
      section._setMarkerDraggable(false);
      // Resize map when section becomes visible
      setTimeout(() => map.invalidateSize(), 200);
      window.addEventListener('resize', () => map.invalidateSize());

      // If no coords present, geocode by name and set view & inputs (no incorrect default view)
      if (!hasCoords) {
        geocodeByName(loc.name).then(result => {
          if (!result) return;
          const lat = parseFloat(result.lat), lon = parseFloat(result.lon);
          if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
          // Add tiles if not already added
          if (!tilesAdded) {
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
              maxZoom: 19,
              attribution: '&copy; OpenStreetMap'
            }).addTo(map);
            tilesAdded = true;
          }
          map.setView([lat, lon], 13);
          if (marker) map.removeLayer(marker);
          marker = L.marker([lat, lon], { draggable: false }).addTo(map);
          marker.bindPopup(`<b>${escapeHtml(loc.name)}</b>`);
          if (isLocationEditableByCurrentUser(loc)) {
            const latInput = document.getElementById(`lat-${cssId(loc.name)}`);
            const lngInput = document.getElementById(`lng-${cssId(loc.name)}`);
            if (latInput) latInput.value = lat.toFixed(6);
            if (lngInput) lngInput.value = lon.toFixed(6);
            const updateInputs = () => {
              const { lat: dlat, lng: dlng } = marker.getLatLng();
              if (latInput) latInput.value = dlat.toFixed(6);
              if (lngInput) lngInput.value = dlng.toFixed(6);
            };
            marker.on('drag', updateInputs);
            marker.on('dragend', updateInputs);
          }
          section._setMarkerDraggable = function(enabled) {
            try {
              if (marker && marker.dragging) {
                if (enabled && isLocationEditableByCurrentUser(loc)) marker.dragging.enable(); else marker.dragging.disable();
              }
            } catch (_) {}
          };
          section._getMarkerLatLng = function() {
            try { return marker.getLatLng(); } catch (_) { return null; }
          };
          section._setMarkerDraggable(false);
          // Switch overlay back to interaction hint
          try { if (mapOverlay) mapOverlay.innerHTML = '<div class="hint">Tap to interact</div>'; } catch(_) {}
        }).catch(() => {});
      }

      async function geocodeByName(name) {
        try {
          const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(name)}`;
          const res = await fetch(url, { headers: { 'Accept': 'application/json', 'User-Agent': 'ClimbingApp/1.0 (locations page)' } });
          if (!res.ok) return null;
          const arr = await res.json();
          return Array.isArray(arr) && arr.length > 0 ? arr[0] : null;
        } catch {
          return null;
        }
      }
      // Map activation: require tap/click to enable panning/zooming
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
        
        if (mapOverlay && mapOverlay.parentNode) {
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
      mapOverlay.addEventListener('click', activateMap);
      mapOverlay.addEventListener('touchstart', activateMap, { passive: true });

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
    if (isSelected) {
      section.classList.remove('selected');
      url.searchParams.delete('highlight');
      history.pushState({}, '', url.toString());
      return;
    }
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
    if (highlight) {
      const norm = normalizeName(highlight);
      const sections = Array.from(container.querySelectorAll('.location-section'));
      for (const sec of sections) {
        const name = sec.getAttribute('data-name') || '';
        if (normalizeName(name) === norm) {
          clearAllSelections();
          sec.classList.add('selected');
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

  async function saveLocation(loc) {
    try {
      const desc = document.getElementById(`desc-${cssId(loc.name)}`)?.value || '';
      const approachVal = document.getElementById(`approach-${cssId(loc.name)}`)?.value || '';
      const latVal = document.getElementById(`lat-${cssId(loc.name)}`)?.value;
      const lngVal = document.getElementById(`lng-${cssId(loc.name)}`)?.value;
      const payload = { description: desc, approach: approachVal };
      if (latVal !== '' && lngVal !== '') {
        payload.latitude = parseFloat(latVal);
        payload.longitude = parseFloat(lngVal);
      }
      const res = await fetch(`/api/locations?name=${encodeURIComponent(loc.name)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Failed to save');
      // Soft refresh UI
      loc.description = desc;
      loc.approach = approachVal;
      const approachEl = section.querySelector('.approach-text');
      if (approachEl) {
        const text = (approachVal && approachVal.trim()) || `No approach info yet for ${loc.name}. Add a note when you tag albums here.`;
        approachEl.textContent = text;
      }
      if (payload.latitude && payload.longitude) {
        loc.latitude = payload.latitude;
        loc.longitude = payload.longitude;
      }
    } catch (e) { alert(e.message || 'Failed to save'); }
  }

  async function claimLocation(loc) {
    try {
      const res = await fetch('/api/locations/claim', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: loc.name })
      });
      if (!res.ok) throw new Error('Failed to claim');
      if (!Array.isArray(loc.owners)) loc.owners = [];
      if (currentUser && !loc.owners.includes(currentUser.id)) loc.owners.push(currentUser.id);
    } catch (e) { alert(e.message || 'Failed to claim'); }
  }

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


