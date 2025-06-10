document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("albums-container");
	const SERVER_URL = "http://localhost:8002";

	// 1️⃣ Creates a placeholder card with a loading animation
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

	// 2️⃣ Populates a card with the fetched metadata
	const populateCard = (card, meta) => {
		card.classList.remove("loading");
		card.classList.add("loaded");

		// Change the element to a link
		const linkCard = document.createElement("a");
		linkCard.href = meta.url;
		linkCard.className = card.className;
		linkCard.style.animationDelay = card.style.animationDelay;
		linkCard.target = "_blank";
		linkCard.rel = "noopener noreferrer";

		linkCard.innerHTML = `
      <img src="${meta.imageUrl}" alt="${meta.title}" loading="lazy" onerror="this.style.display='none'">
      <div class="album-card-content">
        <h3>${meta.title}</h3>
        <p>${meta.description}</p>
      </div>
    `;
		// Replace the placeholder div with the final link card
		card.replaceWith(linkCard);
	};

	// 3️⃣ Fetches metadata for a single album URL
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
			// Return a specific error object to handle it later
			return { error: true, url: albumUrl };
		}
	};

	// 4️⃣ Main function to orchestrate the loading process
	const loadAlbums = async () => {
		try {
			const response = await fetch("albums.txt");
			if (!response.ok) throw new Error("Could not load albums.txt");

			const text = await response.text();
			const urls = text.split("\n").filter((line) => line.trim() !== "");

			// Create and display all placeholder cards immediately
			const placeholders = urls.map((_, index) => {
				const card = createPlaceholderCard(index);
				container.appendChild(card);
				return card;
			});

			// Create an array of fetch promises to run in parallel
			const metaPromises = urls.map((url) => fetchAlbumMeta(url));

			// Wait for all fetch requests to complete
			const allMetas = await Promise.all(metaPromises);

			// Populate each placeholder with its corresponding data
			allMetas.forEach((meta, index) => {
				const placeholder = placeholders[index];
				if (meta && !meta.error && meta.imageUrl) {
					populateCard(placeholder, meta);
				} else {
					// If fetching failed for one, remove its placeholder
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
