document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("memes-container");

	const createCard = (img) => {
		const card = document.createElement("a");
		card.className = "album-card grid-item";
		card.href = img.url;
		card.target = "_blank";
		card.rel = "noopener noreferrer";

		// ✅ Simplified HTML: Only the image container and the image itself.
		// The .album-card-content div has been completely removed.
		card.innerHTML = `
			<div class="img-container">
				<img src="${img.url}" alt="${img.name}" loading="lazy">
			</div>
		`;

		// This part handles the individual image fade-in animation
		const image = card.querySelector("img");
		function fadeInImage() {
			requestAnimationFrame(() => image.classList.add("loaded"));
		}
		if (image.complete && image.naturalWidth !== 0) {
			fadeInImage();
		} else {
			image.onload = fadeInImage;
			image.onerror = fadeInImage;
		}
		return card;
	};

	const loadMemes = async () => {
		try {
			const response = await fetch("/api/memes");
			if (!response.ok) throw new Error("Could not load memes");
			const images = await response.json();

			// Create all card elements
			const cards = images.map(createCard);
			// Append them to the container so images can start loading
			container.append(...cards);

			// ✅ Wait for ALL images to load, THEN initialize Masonry
			imagesLoaded(container, function () {
				new Masonry(container, {
					itemSelector: ".grid-item",
					percentPosition: true,
				});
			});
		} catch (error) {
			container.innerHTML = `<p style="color: #cf6679;">${error.message}</p>`;
			console.error("Error loading memes:", error);
		}
	};

	loadMemes();
});
