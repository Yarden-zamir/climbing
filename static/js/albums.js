document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("albums-container");
	let allAlbums = []; // Store all album cards for filtering
	let allPeople = new Set(); // Store all unique people
	let selectedPeople = new Set(); // Store currently selected people

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
	const match = meta.date?.match(/(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s(\d+)/);
	if (match) {
		const MS_PER_DAY = 1000 * 60 * 60 * 24;
		const albumDate = new Date(`${match[1]} ${match[2]}, ${new Date().getFullYear()}`);
		const diffDays = (new Date() - albumDate) / MS_PER_DAY;

		if (diffDays >= 0 && diffDays <= 3) {
			card.classList.add("new-album");
		}
	}
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

	// --- Crew Faces Stack ---
	if (meta.crew && Array.isArray(meta.crew) && meta.crew.length > 0) {
		const faceStack = document.createElement('div');
		faceStack.className = 'album-crew-stack';
		meta.crew.forEach((climber, i) => {
			const faceLink = document.createElement('a');
			faceLink.href = `/crew?highlight=${encodeURIComponent(climber)}`;
			faceLink.className = 'album-crew-face-link';
			faceLink.title = climber;
			faceLink.tabIndex = 0;
			const faceImg = document.createElement('img');
			faceImg.src = `/climbers/${encodeURIComponent(climber)}/face.png`;
			faceImg.alt = climber;
			faceImg.className = 'album-crew-face';
			faceLink.appendChild(faceImg);
			faceStack.appendChild(faceLink);
		});
		card.style.position = 'relative';
		card.appendChild(faceStack);
	}
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

// --- Mobile card highlight on scroll into view ---
function enableMobileCardHighlight() {
	if (window.matchMedia('(max-width: 700px)').matches) {
		const observer = new window.IntersectionObserver((entries) => {
			entries.forEach(entry => {
				if (entry.isIntersecting) {
					entry.target.classList.add('hover');
				} else {
					entry.target.classList.remove('hover');
				}
			});
		}, { threshold: 0.5 });
		document.querySelectorAll('.album-card').forEach(card => {
			observer.observe(card);
		});
	}
}

	// URL parameter handling
	const updateUrlParams = () => {
		const url = new URL(window.location);
		if (selectedPeople.size > 0) {
			const peopleArray = Array.from(selectedPeople).sort();
			url.searchParams.set('people', peopleArray.join(','));
		} else {
			url.searchParams.delete('people');
		}
		history.pushState({}, '', url.toString());
	};
	
	const loadFiltersFromUrl = () => {
		const params = new URLSearchParams(window.location.search);
		const peopleParam = params.get('people');
		if (peopleParam) {
			const peopleFromUrl = peopleParam.split(',').map(p => p.trim()).filter(p => p);
			peopleFromUrl.forEach(person => {
				if (allPeople.has(person)) {
					selectedPeople.add(person);
				}
			});
		}
	};
	
	const syncFiltersWithUI = () => {
		// Update checkbox states based on selectedPeople
		document.querySelectorAll('#people-filters input[type="checkbox"]').forEach(checkbox => {
			const filterDiv = checkbox.closest('.person-filter');
			checkbox.checked = selectedPeople.has(checkbox.value);
			if (checkbox.checked) {
				filterDiv.classList.add('checked');
			} else {
				filterDiv.classList.remove('checked');
			}
		});
		
		// Apply filters and update UI
		applyFilters();
		updateFilterStatus();
		updateFilterFab();
	};
	
	// Handle browser back/forward navigation
	window.addEventListener('popstate', () => {
		selectedPeople.clear();
		loadFiltersFromUrl();
		syncFiltersWithUI();
	});

	// Filter popup functionality
	const initFilterPopup = () => {
		const filterFab = document.getElementById('filter-fab');
		const filterPopup = document.getElementById('filter-popup');
		const filterOverlay = document.getElementById('filter-popup-overlay');
		const filterClose = document.getElementById('filter-popup-close');
		
		const openPopup = () => {
			filterOverlay.classList.add('active');
			filterPopup.classList.add('active');
			filterFab.classList.add('active');
		};
		
		const closePopup = () => {
			filterOverlay.classList.remove('active');
			filterPopup.classList.remove('active');
			filterFab.classList.remove('active');
		};
		
		// Toggle popup when FAB is clicked
		filterFab.addEventListener('click', () => {
			if (filterPopup.classList.contains('active')) {
				closePopup();
			} else {
				openPopup();
			}
		});
		
		// Close popup when overlay is clicked
		filterOverlay.addEventListener('click', closePopup);
		
		// Close popup when close button is clicked
		filterClose.addEventListener('click', closePopup);
		
		// Close popup when ESC key is pressed
		document.addEventListener('keydown', (e) => {
			if (e.key === 'Escape' && filterPopup.classList.contains('active')) {
				closePopup();
			}
		});
	};
	
	// Update filter FAB appearance
	const updateFilterFab = () => {
		const filterFab = document.getElementById('filter-fab');
		
		if (selectedPeople.size > 0) {
			filterFab.style.background = 'linear-gradient(135deg, #03dac6 0%, #018786 100%)';
		} else {
			filterFab.style.background = 'linear-gradient(135deg, #bb86fc 0%, #6200ea 100%)';
		}
	};

	// Filter functionality
	const populatePersonFilters = () => {
		const peopleFiltersContainer = document.getElementById('people-filters');
		const sortedPeople = Array.from(allPeople).sort();
		
		peopleFiltersContainer.innerHTML = '';
		
		sortedPeople.forEach(person => {
			const filterDiv = document.createElement('div');
			filterDiv.className = 'person-filter';
			
			const checkbox = document.createElement('input');
			checkbox.type = 'checkbox';
			checkbox.id = `person-${person.replace(/\s+/g, '-')}`;
			checkbox.value = person;
			
			const face = document.createElement('img');
			face.src = `/climbers/${encodeURIComponent(person)}/face.png`;
			face.alt = person;
			face.className = 'person-face';
			face.onerror = () => face.style.display = 'none';
			
			const label = document.createElement('span');
			label.textContent = person;
			
			filterDiv.appendChild(checkbox);
			filterDiv.appendChild(face);
			filterDiv.appendChild(label);
			
			// Add event listeners for both checkbox and div click
			checkbox.addEventListener('change', handleFilterChange);
			filterDiv.addEventListener('click', (e) => {
				if (e.target !== checkbox) {
					checkbox.checked = !checkbox.checked;
					handleFilterChange();
				}
			});
			
			peopleFiltersContainer.appendChild(filterDiv);
		});
		
		// Add event listeners for control buttons
		document.getElementById('select-all-btn').addEventListener('click', selectAllPeople);
		document.getElementById('clear-all-btn').addEventListener('click', clearAllPeople);
	};
	
	const handleFilterChange = () => {
		// Update selected people set
		selectedPeople.clear();
		document.querySelectorAll('#people-filters input[type="checkbox"]').forEach(checkbox => {
			const filterDiv = checkbox.closest('.person-filter');
			if (checkbox.checked) {
				selectedPeople.add(checkbox.value);
				filterDiv.classList.add('checked');
			} else {
				filterDiv.classList.remove('checked');
			}
		});
		
		// Apply filters
		applyFilters();
		updateFilterStatus();
		updateFilterFab();
		updateUrlParams();
	};
	
	const applyFilters = () => {
		const hasFilters = selectedPeople.size > 0;
		
		allAlbums.forEach(({ card, meta }) => {
			if (!hasFilters) {
				// No filters selected, show all
				card.style.display = '';
				card.classList.remove('filtered-out');
			} else {
				// Check if album contains all selected people
				const albumCrew = meta.crew || [];
				const hasAllSelectedPeople = Array.from(selectedPeople).every(person => 
					albumCrew.includes(person)
				);
				
				if (hasAllSelectedPeople) {
					card.style.display = '';
					card.classList.remove('filtered-out');
				} else {
					card.style.display = 'none';
					card.classList.add('filtered-out');
				}
			}
		});
	};
	
	const updateFilterStatus = () => {
		const statusEl = document.getElementById('filter-status');
		const visibleAlbums = allAlbums.filter(({ card }) => card.style.display !== 'none').length;
		const totalAlbums = allAlbums.length;
		
		if (selectedPeople.size === 0) {
			statusEl.style.display = 'none';
		} else {
			statusEl.style.display = 'block';
			const peopleList = Array.from(selectedPeople).join(', ');
			statusEl.innerHTML = `✨ Showing <strong>${visibleAlbums}</strong> of <strong>${totalAlbums}</strong> albums featuring: <strong>${peopleList}</strong>`;
		}
	};
	
	const selectAllPeople = () => {
		document.querySelectorAll('#people-filters input[type="checkbox"]').forEach(checkbox => {
			checkbox.checked = true;
		});
		handleFilterChange();
	};
	
	const clearAllPeople = () => {
		document.querySelectorAll('#people-filters input[type="checkbox"]').forEach(checkbox => {
			checkbox.checked = false;
		});
		handleFilterChange();
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

			// Fetch crew participation data
			let crewData = {};
			try {
				const crewRes = await fetch("static/albums.json");
				if (crewRes.ok) crewData = await crewRes.json();
			} catch (e) { crewData = {}; }

			// Extract all unique people from crew data
			Object.values(crewData).forEach(albumData => {
				if (albumData.crew && Array.isArray(albumData.crew)) {
					albumData.crew.forEach(person => allPeople.add(person));
				}
			});

			// Initialize filter functionality
			initFilterPopup();
			populatePersonFilters();
			
			// Load filters from URL parameters
			loadFiltersFromUrl();

			const metaPromises = urls.map((url) => fetchAlbumMeta(url));
			const allMetas = await Promise.all(metaPromises);

			allMetas.forEach((meta, index) => {
				const placeholder = placeholders[index];
				if (meta && !meta.error && meta.imageUrl) {
					// Attach crew info if available
					if (crewData[meta.url] && crewData[meta.url].crew) {
						meta.crew = crewData[meta.url].crew;
					}
					
					// Store album for filtering
					allAlbums.push({ card: placeholder, meta });
					
					populateCard(placeholder, meta);
				} else {
					placeholder.remove();
				}
			});
			
			// Apply initial filters if any were loaded from URL
			syncFiltersWithUI();
			
			enableMobileCardHighlight();
		} catch (error) {
			container.innerHTML = `<p style="color: #cf6679;">${error.message}</p>`;
			console.error("Error loading albums:", error);
		}
	};

	loadAlbums();
});
