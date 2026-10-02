// Knowledge page: pan-and-zoom viewer for the pre-rendered diagram image.
// Inputs: mouse drag, touch drag, pen; mouse wheel zooms; trackpad two-finger scroll pans and
// pinch (arrives as wheel with ctrlKey) zooms; two-finger touch pinch zooms; double-click or
// double-tap zooms in; keyboard: + - 0 and arrows.
(() => {
	const stage = document.getElementById('knowledge-stage');
	const canvas = document.getElementById('knowledge-canvas');
	const image = document.getElementById('knowledge-image');
	if (!stage || !canvas || !image) return;

	const MIN_SCALE_FACTOR = 0.5; // relative to "fit"
	const MAX_SCALE = 6;
	let scale = 1, x = 0, y = 0, fitScale = 1;
	const width = Number(image.getAttribute('width')), height = Number(image.getAttribute('height'));

	const render = () => { canvas.style.transform = `translate(${x}px, ${y}px) scale(${scale})`; };
	const clampScale = (s) => Math.min(MAX_SCALE, Math.max(fitScale * MIN_SCALE_FACTOR, s));
	const keepInView = () => {
		// keep at least a third of the image inside the stage so it cannot be lost off-screen
		const w = width * scale, h = height * scale, sw = stage.clientWidth, sh = stage.clientHeight;
		x = Math.min(sw - w / 3, Math.max(w / 3 - w, x));
		y = Math.min(sh - h / 3, Math.max(h / 3 - h, y));
	};
	const fit = () => {
		const sw = stage.clientWidth, sh = stage.clientHeight;
		fitScale = Math.min(sw / width, sh / height);
		scale = fitScale;
		x = (sw - width * scale) / 2;
		y = 0;
		render();
	};
	// zoom around a point given in stage coordinates
	const zoomAt = (factor, px, py) => {
		const next = clampScale(scale * factor);
		const ratio = next / scale;
		x = px - (px - x) * ratio;
		y = py - (py - y) * ratio;
		scale = next;
		keepInView();
		render();
	};
	const stagePoint = (e) => { const r = stage.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

	// Wheel: ctrl/meta (trackpad pinch, ctrl+wheel) zooms; a mouse wheel zooms; two-finger trackpad scroll pans
	const looksLikeMouseWheel = (e) => e.deltaMode !== 0 || (Math.abs(e.deltaY) >= 40 && e.deltaX === 0 && Number.isInteger(e.deltaY));
	stage.addEventListener('wheel', (e) => {
		e.preventDefault();
		const [px, py] = stagePoint(e);
		if (e.ctrlKey || e.metaKey) {
			zoomAt(Math.exp(-e.deltaY * 0.01), px, py);
		} else if (looksLikeMouseWheel(e)) {
			zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, px, py);
		} else {
			x -= e.deltaX; y -= e.deltaY; keepInView(); render();
		}
	}, { passive: false });

	// Pointers: one drags, two pinch
	const pointers = new Map();
	let lastPinchDistance = 0, lastTap = 0, moved = 0;
	stage.addEventListener('pointerdown', (e) => {
		if ((e.button !== undefined && e.button !== 0) || e.target.closest('.knowledge-controls')) return;
		try { stage.setPointerCapture(e.pointerId); } catch (_) {}
		moved = 0;
		pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
		if (pointers.size === 1) stage.classList.add('dragging');
		if (pointers.size === 2) {
			const [a, b] = [...pointers.values()];
			lastPinchDistance = Math.hypot(a.x - b.x, a.y - b.y);
		}
	});
	stage.addEventListener('pointermove', (e) => {
		const prev = pointers.get(e.pointerId);
		if (!prev) return;
		if (pointers.size === 1) {
			moved += Math.abs(e.clientX - prev.x) + Math.abs(e.clientY - prev.y);
			x += e.clientX - prev.x; y += e.clientY - prev.y;
			keepInView(); render();
		} else if (pointers.size === 2) {
			pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
			const [a, b] = [...pointers.values()];
			const distance = Math.hypot(a.x - b.x, a.y - b.y);
			const r = stage.getBoundingClientRect();
			if (lastPinchDistance) zoomAt(distance / lastPinchDistance, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
			lastPinchDistance = distance;
			return;
		}
		pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
	});
	const release = (e) => {
		pointers.delete(e.pointerId);
		if (pointers.size < 2) lastPinchDistance = 0;
		if (pointers.size === 0) stage.classList.remove('dragging');
	};
	stage.addEventListener('pointerup', (e) => {
		if (!pointers.has(e.pointerId)) return;
		// double tap / double click (without dragging) zooms in on that spot
		const now = Date.now();
		if (pointers.size === 1 && moved < 10 && now - lastTap < 350) { const [px, py] = stagePoint(e); zoomAt(2, px, py); lastTap = 0; }
		else lastTap = moved < 10 ? now : 0;
		release(e);
	});
	stage.addEventListener('pointercancel', release);
	stage.addEventListener('lostpointercapture', release);
	stage.addEventListener('dblclick', (e) => e.preventDefault());

	// Buttons and keyboard
	stage.querySelectorAll('[data-zoom]').forEach((button) => button.addEventListener('click', (e) => {
		e.stopPropagation();
		const cx = stage.clientWidth / 2, cy = stage.clientHeight / 2;
		if (button.dataset.zoom === 'in') zoomAt(1.4, cx, cy);
		else if (button.dataset.zoom === 'out') zoomAt(1 / 1.4, cx, cy);
		else fit();
	}));
	stage.addEventListener('keydown', (e) => {
		const cx = stage.clientWidth / 2, cy = stage.clientHeight / 2, step = 60;
		if (e.key === '+' || e.key === '=') zoomAt(1.3, cx, cy);
		else if (e.key === '-') zoomAt(1 / 1.3, cx, cy);
		else if (e.key === '0') fit();
		else if (e.key === 'ArrowLeft') x += step;
		else if (e.key === 'ArrowRight') x -= step;
		else if (e.key === 'ArrowUp') y += step;
		else if (e.key === 'ArrowDown') y -= step;
		else return;
		e.preventDefault(); keepInView(); render();
	});

	// Swap the small preview for the lossless image once it has loaded
	const full = new Image();
	full.onload = () => { image.src = full.src; };
	full.src = '/static/knowledge-full.webp';

	new ResizeObserver(() => { if (scale === fitScale) fit(); else { keepInView(); render(); } }).observe(stage);
	fit();
})();
