document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("albums-container");
	const SERVER_URL = "http://localhost:8002";

	const createPlaceholderCard = (index) => {
		const card = document.createElement("div");
		card.className = "album-card loading";
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

	const populateCard = (card, meta) => {
		card.classList.remove("loading");
		card.classList.add("loaded");

		const linkCard = document.createElement("a");
		linkCard.href = meta.url;
		linkCard.className = card.className;
		linkCard.style.animationDelay = card.style.animationDelay;
		linkCard.target = "_blank";
		linkCard.rel = "noopener noreferrer";

		const proxyImageUrl = `${SERVER_URL}/get-image?url=${encodeURIComponent(
			meta.imageUrl
		)}`;

		linkCard.innerHTML = `
      <img src="${proxyImageUrl}" alt="${meta.title}" loading="lazy" onerror="this.style.display='none'">
      <div class="album-card-content">
        <h3>${meta.title}</h3>
        <p>${meta.description}</p>
      </div>
    `;
		card.replaceWith(linkCard);
	};

	const fetchAlbumMeta = async (albumUrl) => {
		const apiUrl = `${SERVER_URL}/get-meta?url=${encodeURIComponent(
			albumUrl
		)}`;
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
			const response = await fetch("albums.txt");
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
