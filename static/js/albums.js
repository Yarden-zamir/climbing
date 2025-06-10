document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("albums-container");

const typewriter = (element, text, speed = 20) => {
	return new Promise((resolve) => {
		if (speed <= 0) {
			element.innerHTML = text;
			resolve();
			return;
		}
		let i = 0;
		element.innerHTML = "";
		function type() {
			// Type 1-3 chars per frame for long text
			let charsThisFrame = Math.max(1, Math.floor(16 / speed));
			for (let j = 0; j < charsThisFrame && i < text.length; ++j, ++i) {
				element.innerHTML += text.charAt(i);
			}
			if (i < text.length) {
				requestAnimationFrame(type);
			} else {
				resolve();
			}
		}
		type();
	});
};

	const createPlaceholderCard = (index) => {
		const card = document.createElement("a");
		card.className = "album-card loading";
		card.href = "#";
		card.style.animationDelay = `${index * 100}ms`;
		card.innerHTML = `
      <div class="placeholder placeholder-img"></div>
      <div class="placeholder-content">
        <div class="placeholder placeholder-text"></div>
        <div class="placeholder placeholder-text short"></div>
        <div class="placeholder placeholder-text short"></div>
      </div>
    `;
		return card;
	};

const populateCard = async (card, meta) => {
	card.href = meta.url;
	card.target = "_blank";
	card.rel = "noopener noreferrer";

	const proxyImageUrl = `/get-image?url=${encodeURIComponent(meta.imageUrl)}`;

	card.innerHTML = `
      <div class="img-container">
        <img src="${proxyImageUrl}" alt="${meta.title}" loading="lazy" onerror="this.style.display='none'">
      </div>
      <div class="album-card-content">
        <h3 dir="auto"></h3>
        <p dir="auto"></p>
        <div class="album-date"></div>
      </div>
    `;

	card.classList.remove("loading");
	card.classList.add("loaded");

	const img = card.querySelector("img");
	img.onload = () => img.classList.add("loaded");

	const titleEl = card.querySelector("h3");
	const descriptionEl = card.querySelector("p");
	const dateEl = card.querySelector(".album-date");

	await typewriter(titleEl, meta.title);
	await typewriter(descriptionEl, meta.description);

	// Set date (no animation)
	dateEl.textContent = meta.date || "";
};

	const fetchAlbumMeta = async (albumUrl) => {
		const apiUrl = `/get-meta?url=${encodeURIComponent(albumUrl)}`;
		try {
			const response = await fetch(apiUrl);
			if (!response.ok) throw new Error("Server error");
			return await response.json();
		} catch (error) {
			console.error(`Failed to fetch meta for ${albumUrl}:`, error);
			return { error: true, url: albumUrl };
		}
	};

	const loadAlbums = async () => {
		try {
			const response = await fetch("static/albums.txt");
			if (!response.ok) throw new Error("Could not load albums.txt");

			const text = await response.text();
			const urls = text.split("\n").filter((line) => line.trim() !== "");

			const placeholders = urls.map((_, index) => {
				const card = createPlaceholderCard(index);
				container.appendChild(card);
				return card;
			});

			const metaPromises = urls.map((url) => fetchAlbumMeta(url));
			const allMetas = await Promise.all(metaPromises);

			allMetas.forEach((meta, index) => {
				const placeholder = placeholders[index];
				if (meta && !meta.error && meta.imageUrl) {
					populateCard(placeholder, meta);
				} else {
					placeholder.remove();
				}
			});
		} catch (error) {
			container.innerHTML = `<p style="color: #cf6679;">${error.message}</p>`;
			console.error("Error loading albums:", error);
		}
	};

	loadAlbums();
});
