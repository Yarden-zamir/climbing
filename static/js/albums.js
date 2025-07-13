document.addEventListener("DOMContentLoaded", () => {
	const container = document.getElementById("albums-container");
	let allAlbums = []; // Store all album cards for filtering
	let allPeople = new Set(); // Store all unique people
	
	// Make allPeople globally accessible for edit functions
	window.allPeople = allPeople;
	let selectedPeople = new Set(); // Store currently selected people

	// Cropping variables
	let currentCropper = null;
	let currentOriginalFile = null;
	let activeCropTarget = null; // 'add' or 'edit'

	// Initialize cropping modal
	function initCropModal() {
		const cropModalOverlay = document.getElementById('crop-modal-overlay');
		const cropModal = document.getElementById('crop-modal');
		const cropCloseBtn = document.getElementById('crop-modal-close');
		const cropCancelBtn = document.getElementById('crop-cancel-btn');
		const cropConfirmBtn = document.getElementById('crop-confirm-btn');
		const cropImage = document.getElementById('crop-image');

		function openCropModal(file, target) {
			currentOriginalFile = file;
			activeCropTarget = target;
			
			const reader = new FileReader();
			reader.onload = (e) => {
				cropImage.src = e.target.result;
				cropModalOverlay.classList.add('active');
				
				// Initialize cropper after modal is visible
				setTimeout(() => {
					if (currentCropper) {
						currentCropper.destroy();
					}
					
					currentCropper = new Cropper(cropImage, {
						aspectRatio: 1, // Force 1:1 aspect ratio
						viewMode: 1,
						dragMode: 'move',
						autoCropArea: 0.8,
						restore: false,
						guides: false, // Hide grid lines
						center: false, // Hide center indicator
						highlight: false,
						cropBoxMovable: true,
						cropBoxResizable: true,
						toggleDragModeOnDblclick: false
					});
				}, 100);
			};
			reader.readAsDataURL(file);
		}

		function closeCropModal() {
			cropModalOverlay.classList.remove('active');
			if (currentCropper) {
				currentCropper.destroy();
				currentCropper = null;
			}
			currentOriginalFile = null;
			activeCropTarget = null;
		}

		function confirmCrop() {
			if (!currentCropper) return;
			
			// Get cropped canvas
			const canvas = currentCropper.getCroppedCanvas({
				width: 400,
				height: 400,
				imageSmoothingEnabled: true,
				imageSmoothingQuality: 'high'
			});
			
			// Convert canvas to blob
			canvas.toBlob((blob) => {
				if (blob) {
					// Create a new File object from the blob
					const croppedFile = new File([blob], currentOriginalFile.name, {
						type: currentOriginalFile.type,
						lastModified: Date.now()
					});
					
					// Apply the cropped image based on the target
					if (activeCropTarget === 'add') {
						if (typeof window.applyImageToAdd === 'function') {
							window.applyImageToAdd(croppedFile, canvas.toDataURL());
						} else {
							console.error('window.applyImageToAdd is not a function');
						}
					} else if (activeCropTarget === 'edit') {
						applyImageToEdit(croppedFile, canvas.toDataURL());
					} else if (activeCropTarget === 'edit-album') {
						if (typeof window.applyImageToEditAlbum === 'function') {
							window.applyImageToEditAlbum(croppedFile, canvas.toDataURL());
						} else {
							console.error('window.applyImageToEditAlbum is not a function');
						}
					}
					
					closeCropModal();
				}
			}, currentOriginalFile.type, 0.9);
		}

		// Event listeners
		cropCloseBtn.addEventListener('click', closeCropModal);
		cropCancelBtn.addEventListener('click', closeCropModal);
		cropConfirmBtn.addEventListener('click', confirmCrop);
		
		// Close on overlay click
		cropModalOverlay.addEventListener('click', (e) => {
			if (e.target === cropModalOverlay) {
				closeCropModal();
			}
		});

		return { openCropModal, closeCropModal };
	}

	const cropModal = initCropModal();
	
	// Make cropModal globally accessible for edit functions
	window.cropModal = cropModal;



	function applyImageToEdit(croppedFile, dataUrl) {
		editCurrentPersonImage = croppedFile;
		const uploadContent = document.getElementById('edit-upload-content');
		uploadContent.innerHTML = `
			<img src="${dataUrl}" class="image-preview" alt="Preview">
			<div class="upload-text">
				✅ Image uploaded (cropped)<br>
				<small>Click to change</small>
			</div>
		`;
	}

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
	
	// Add data attributes for edit functionality
	card.dataset.albumUrl = meta.url;
	card.albumMeta = meta;

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
		
		// The crew data now comes enriched with 'is_new' status
		renderCrewFaces(meta.crew, faceStack);
		
		card.style.position = 'relative';
		card.appendChild(faceStack);
	}
	
	function renderCrewFaces(crewWithStatus, faceStack) {
		crewWithStatus.forEach(climber => {
			const climberName = climber.name;
			const isNew = climber.is_new;

			const faceLink = document.createElement('a');
			faceLink.href = `/crew?highlight=${encodeURIComponent(climberName)}`;
			faceLink.className = 'album-crew-face-link';
			faceLink.title = climberName;
			faceLink.tabIndex = 0;
			
			const faceImg = document.createElement('img');
			faceImg.src = climber.image_url || `/redis-image/climber/${encodeURIComponent(climberName)}/face`;
			faceImg.alt = climberName;
			faceImg.className = `album-crew-face${isNew ? ' new-climber' : ''}`;
			
			faceLink.appendChild(faceImg);
			faceStack.appendChild(faceLink);
		});
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
				// Case-insensitive matching: find the person in allPeople
				const matchingPerson = Array.from(allPeople).find(p => 
					p.toLowerCase() === person.toLowerCase()
				);
				if (matchingPerson) {
					selectedPeople.add(matchingPerson);
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
		
		// Initialize clear all button
		document.getElementById('clear-all-btn').addEventListener('click', clearAllPeople);
	};
	
	const updateFilterFab = () => {
		const filterFab = document.getElementById('filter-fab');
		if (selectedPeople.size > 0) {
			filterFab.classList.add('has-filters');
		} else {
			filterFab.classList.remove('has-filters');
		}
	};

	const populatePersonFilters = () => {
		const filtersContainer = document.getElementById('people-filters');
		const sortedPeople = Array.from(allPeople).sort();
		
		filtersContainer.innerHTML = sortedPeople.map(person => `
			<div class="person-filter">
				<input type="checkbox" value="${person}" onchange="handleFilterChange()">
				<img src="/redis-image/climber/${encodeURIComponent(person)}/face" alt="${person}" class="person-face" onerror="this.style.display='none'">
				<span>${person}</span>
			</div>
		`).join('');
		
		// Add click handlers to person filters
		document.querySelectorAll('.person-filter').forEach(filter => {
			filter.addEventListener('click', () => {
				const checkbox = filter.querySelector('input[type="checkbox"]');
				checkbox.checked = !checkbox.checked;
				handleFilterChange();
			});
		});
		
		// Sync with current URL filters
		loadFiltersFromUrl();
		syncFiltersWithUI();
	};
	
	const handleFilterChange = () => {
		// Update selectedPeople based on checked checkboxes
		selectedPeople.clear();
		document.querySelectorAll('#people-filters input[type="checkbox"]:checked').forEach(checkbox => {
			selectedPeople.add(checkbox.value);
			checkbox.closest('.person-filter').classList.add('checked');
		});
		
		// Remove checked class from unchecked items
		document.querySelectorAll('#people-filters input[type="checkbox"]:not(:checked)').forEach(checkbox => {
			checkbox.closest('.person-filter').classList.remove('checked');
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
				// Check if album contains all selected people (case-insensitive)
				const albumCrewNames = (meta.crew || []).map(crew => 
					typeof crew === 'string' ? crew : crew.name
				);
				
				const hasAllSelectedPeople = Array.from(selectedPeople).every(selectedPerson => 
					albumCrewNames.some(crewName => 
						crewName.toLowerCase() === selectedPerson.toLowerCase()
					)
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
	
	const clearAllPeople = () => {
		document.querySelectorAll('#people-filters input[type="checkbox"]').forEach(checkbox => {
			checkbox.checked = false;
		});
		handleFilterChange();
	};

	function showSkeletonCards() {
		// Skeleton cards are created in processAlbums
	}

	function hideSkeletonCards() {
		// Remove any existing skeleton cards
		document.querySelectorAll('.album-card.loading').forEach(card => {
			card.remove();
		});
	}

	function showError(message) {
		container.innerHTML = `<p style="color: #cf6679; text-align: center; padding: 2rem;">${message}</p>`;
	}

	async function processAlbums(urls) {
		const placeholders = urls.map((_, index) => {
			const card = createPlaceholderCard(index);
			container.appendChild(card);
			return card;
		});

		// Fetch crew participation data from albums.json
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
	}

	async function processEnrichedAlbums(enrichedAlbums) {
		const placeholders = document.querySelectorAll(".album-card.loading");
		
		// Extract all unique people from the enriched data
		enrichedAlbums.forEach(({ metadata }) => {
			if (metadata.crew && Array.isArray(metadata.crew)) {
				metadata.crew.forEach(person => {
					if (person && person.name) {
						allPeople.add(person.name); // Add the name string, not the object
					}
				});
			}
		});

		// Initialize filter functionality
		initFilterPopup();
		populatePersonFilters();
		
		// Load filters from URL parameters
		loadFiltersFromUrl();

		// Process enriched albums (no need to fetch metadata, it's already included)
		enrichedAlbums.forEach((album, index) => {
			const placeholder = placeholders[index];
			const meta = album.metadata;
			
			if (meta && !meta.error && meta.imageUrl) {
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
	}

	// Auto-refresh function for albums data
	async function autoRefreshAlbums(showLoadingState = true) {
		try {
			if (showLoadingState) {
				// Show loading indicator
				container.innerHTML = `
					<div class="refresh-loading" style="text-align: center; padding: 2rem; color: #03dac6;">
						<div style="font-size: 1.2em; margin-bottom: 1rem;">
							<span class="refresh-spinner">🔄</span> Refreshing albums...
						</div>
						<div style="font-size: 0.9em; color: #ccc;">Please wait while we update the latest albums</div>
					</div>
				`;
			}
			
			// Use the new enriched endpoint that returns albums with pre-loaded metadata
			const response = await fetch("/api/albums/enriched");
			if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			
			const enrichedAlbums = await response.json();
			
			// Clear existing content
			container.innerHTML = '';
			
			// Reset global variables
			allAlbums = [];
			allPeople.clear();
			
			// Create placeholder cards for all albums
			for (let i = 0; i < enrichedAlbums.length; i++) {
				container.appendChild(createPlaceholderCard(i));
			}
			
			await processEnrichedAlbums(enrichedAlbums);
			
			return true;
		} catch (error) {
			console.error("Error refreshing albums:", error);
			
			// Show error message
			container.innerHTML = `
				<div class="refresh-error" style="text-align: center; padding: 2rem; color: #cf6679;">
					<div style="font-size: 1.2em; margin-bottom: 1rem;">❌ Failed to refresh albums</div>
					<div style="font-size: 0.9em; color: #ccc; margin-bottom: 1rem;">
						Error: ${error.message}
					</div>
					<button onclick="autoRefreshAlbums()" style="
						background: #03dac6;
						color: #1a1a1a;
						border: none;
						padding: 0.5rem 1rem;
						border-radius: 8px;
						cursor: pointer;
						font-weight: 600;
					">
						Try Again
					</button>
				</div>
			`;
			
			return false;
		}
	}

	async function loadAlbums() {
		try {
			showSkeletonCards();
			
			// Use the new enriched endpoint that returns albums with pre-loaded metadata
			const response = await fetch("/api/albums/enriched");
			if (!response.ok) throw new Error("Could not load enriched album data");
			
			const enrichedAlbums = await response.json();
			
			// Ensure we have enough skeleton cards for all albums
			const existingPlaceholders = container.querySelectorAll('.album-card.loading').length;
			if (enrichedAlbums.length > existingPlaceholders) {
				for (let i = existingPlaceholders; i < enrichedAlbums.length; i++) {
					container.appendChild(createPlaceholderCard(i));
				}
			}
			
			await processEnrichedAlbums(enrichedAlbums);
			
		} catch (error) {
			console.error("Error loading albums:", error);
			hideSkeletonCards();
			showError("Failed to load albums. Please try refreshing the page.");
		}
	}

	// Particle Animation System for Albums
	class AlbumParticleSystem {
		constructor() {
			this.container = null;
			this.init();
		}
		
		init() {
			// Create particle container if it doesn't exist
			if (!document.querySelector('.particle-container')) {
				this.container = document.createElement('div');
				this.container.className = 'particle-container';
				document.body.appendChild(this.container);
			} else {
				this.container = document.querySelector('.particle-container');
			}
		}
		
		createParticles(element, type, count = 15) {
			if (!element || !this.container) return;
			
			const rect = element.getBoundingClientRect();
			const centerX = rect.left + rect.width / 2;
			const centerY = rect.top + rect.height / 2;
			
			for (let i = 0; i < count; i++) {
				const particle = document.createElement('div');
				particle.className = `particle ${type}`;
				
							// Random offset from center - more focused for new items
			const multiplier = type.includes('created') ? 0.6 : 1.2;
			const offsetX = (Math.random() - 0.5) * rect.width * multiplier;
			const offsetY = (Math.random() - 0.5) * rect.height * multiplier;
				
				particle.style.left = (centerX + offsetX) + 'px';
				particle.style.top = (centerY + offsetY) + 'px';
				
				// Add random delay for staggered effect
				particle.style.animationDelay = (Math.random() * 0.4) + 's';
				
				// Add rotation for variety
				const randomRotation = Math.random() * 360;
				particle.style.transform = `rotate(${randomRotation}deg)`;
				
				this.container.appendChild(particle);
				
				// Remove particle after animation
				setTimeout(() => {
					if (particle.parentNode) {
						particle.parentNode.removeChild(particle);
					}
				}, 2500);
			}
		}

		// Create a horizontal red line of particles (for deletions)
		createLineParticles(target, count = 40) {
			if (!this.container) return;
			const rect = target instanceof Element ? target.getBoundingClientRect() : target;
			const centerY = rect.top + rect.height / 2;
			for (let i = 0; i < count; i++) {
				const particle = document.createElement('div');
				particle.className = 'particle red';
				const x = rect.left + Math.random() * rect.width;
				const y = centerY + (Math.random() - 0.5) * 6;
				particle.style.left = `${x}px`;
				particle.style.top = `${y}px`;
				particle.style.animationDelay = (Math.random() * 0.2) + 's';
				this.container.appendChild(particle);
				setTimeout(() => particle.remove(), 2000);
			}
		}
		
		animateItemChange(element, changeType) {
			if (!element) return;
			
			// Add highlight animation to the item itself
			element.classList.add(`item-being-${changeType}`);
			
			// Remove class after animation
			setTimeout(() => {
				element.classList.remove(`item-being-${changeType}`);
			}, changeType === 'deleted' ? 500 : changeType === 'updated' ? 600 : 1000);
		}
	}
	
	// Global album particle system instance
	const albumParticleSystem = new AlbumParticleSystem();
	
	// Enhanced auto-refresh function with change detection and particles for albums
	let previousAlbumData = [];
	
	async function autoRefreshAlbumsWithParticles(showLoadingState = true, detectChanges = true) {
		try {
			if (showLoadingState) {
				// Show loading indicator
				container.innerHTML = `
					<div class="refresh-loading" style="text-align: center; padding: 2rem; color: #03dac6;">
						<div style="font-size: 1.2em; margin-bottom: 1rem;">
							<span class="refresh-spinner">🔄</span> Refreshing albums...
						</div>
						<div style="font-size: 0.9em; color: #ccc;">Please wait while we update the latest albums</div>
					</div>
				`;
			}
			
					// Save scroll position before refresh
		const scrollPosition = window.pageYOffset || document.documentElement.scrollTop;
		
		// Use the new enriched endpoint that returns albums with pre-loaded metadata
		const response = await fetch("/api/albums/enriched");
		if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
		
		const enrichedAlbums = await response.json();
		
		// Detect changes and create particles before updating DOM
		if (detectChanges && previousAlbumData.length > 0) {
			await detectAlbumChangesAndAnimate(previousAlbumData, enrichedAlbums);
		}
		
		// Clear existing content
		container.innerHTML = '';
		
		// Reset global variables
		allAlbums = [];
		allPeople.clear();
		
		// Create placeholder cards for all albums
		for (let i = 0; i < enrichedAlbums.length; i++) {
			container.appendChild(createPlaceholderCard(i));
		}
		
		await processEnrichedAlbums(enrichedAlbums);
		
		// Restore scroll position after refresh
		setTimeout(() => {
			window.scrollTo(0, scrollPosition);
		}, 50);
		
		// Store current data for next comparison
		previousAlbumData = [...enrichedAlbums];
			
			return true;
		} catch (error) {
			console.error("Error refreshing albums:", error);
			
			// Show error message
			container.innerHTML = `
				<div class="refresh-error" style="text-align: center; padding: 2rem; color: #cf6679;">
					<div style="font-size: 1.2em; margin-bottom: 1rem;">❌ Failed to refresh albums</div>
					<div style="font-size: 0.9em; color: #ccc; margin-bottom: 1rem;">
						Error: ${error.message}
					</div>
					<button onclick="autoRefreshAlbums()" style="
						background: #03dac6;
						color: #1a1a1a;
						border: none;
						padding: 0.5rem 1rem;
						border-radius: 8px;
						cursor: pointer;
						font-weight: 600;
					">
						Try Again
					</button>
				</div>
			`;
			
			return false;
		}
	}
	
	async function detectAlbumChangesAndAnimate(oldData, newData) {
		// Wait a bit for DOM to be ready
		await new Promise(resolve => setTimeout(resolve, 100));
		
		const oldUrls = new Set(oldData.map(album => album.url));
		const newUrls = new Set(newData.map(album => album.url));
		
		// Find added albums (blue particles)
		const addedAlbums = newData.filter(album => !oldUrls.has(album.url));
		
		// Find deleted albums (red particles) 
		const deletedAlbums = oldData.filter(album => !newUrls.has(album.url));
		
		// Find updated albums (green particles)
		const updatedAlbums = newData.filter(newAlbum => {
			const oldAlbum = oldData.find(old => old.url === newAlbum.url);
			if (!oldAlbum) return false;
			
			// Check if crew changed
			const oldCrew = JSON.stringify((oldAlbum.metadata?.crew || []).map(c => c.name).sort());
			const newCrew = JSON.stringify((newAlbum.metadata?.crew || []).map(c => c.name).sort());
			
			return oldCrew !== newCrew;
		});
		
		// Animate deletions first (with red particles) - small delay so they're visible
		setTimeout(() => {
			for (const album of deletedAlbums) {
				const albumCard = document.querySelector(`[data-album-url="${album.url}"]`);
				if (albumCard) {
					const rect = albumCard.getBoundingClientRect();
					albumCard.remove();
					albumParticleSystem.createLineParticles(rect, 40);
				}
			}
		}, 300);
		
		// Then animate additions (with blue particles)
		setTimeout(() => {
			for (const album of addedAlbums) {
				const albumCard = document.querySelector(`[data-album-url="${album.url}"]`);
				if (albumCard) {
					albumParticleSystem.animateItemChange(albumCard, 'added');
					
					// Scroll to the new album if it's visible
					albumCard.scrollIntoView({ behavior: "smooth", block: "center" });
					
					// Create particles after scroll animation
					setTimeout(() => {
						albumParticleSystem.createParticles(albumCard, 'blue created', 25);
					}, 800);
				}
			}
		}, 500);
		
		// Finally animate updates (with green particles)
		setTimeout(() => {
			for (const album of updatedAlbums) {
				const albumCard = document.querySelector(`[data-album-url="${album.url}"]`);
				if (albumCard) {
					albumParticleSystem.animateItemChange(albumCard, 'updated');
					albumParticleSystem.createParticles(albumCard, 'green updated', 10);
				}
			}
		}, 700);
	}

	// Make both functions available globally for error buttons
	window.autoRefreshAlbums = autoRefreshAlbumsWithParticles;
	window.albumParticleSystem = albumParticleSystem;
	
	// Initial load (store initial data for comparison)
	loadAlbums().then(() => {
		// Store initial album data for future comparisons
		fetch("/api/albums/enriched")
			.then(response => response.json())
			.then(data => {
				previousAlbumData = [...data];
			})
			.catch(e => console.warn('Could not store initial album data:', e));
	});
});

let editNewPeople = [];
let editAllSkills = [];
let editSelectedSkills = [];
let editCurrentPersonImage = null;

// Fetch skills for edit modal
fetch('/api/skills')
    .then(r => r.json())
    .then(skills => {
        editAllSkills = skills;
        initEditSkillsAutocomplete();
        // Trigger initial render of edit skills badges
        const editSkillsBadgesContainer = document.getElementById('edit-album-skills-badges-container');
        if (editSkillsBadgesContainer) {
            editSkillsBadgesContainer.innerHTML = editAllSkills.map(skill => `
                <div class="skill-badge-toggleable ${editSelectedSkills.includes(skill) ? 'selected' : ''}" data-skill="${skill}">${skill}</div>
            `).join('');
        }
        // Initialize form after skills are loaded
        initEditNewPersonForm();
    });

function initEditNewPersonForm() {
    const showBtn = document.getElementById('edit-show-new-person-btn');
    const cancelBtn = document.getElementById('edit-cancel-person-btn');
    const addBtn = document.getElementById('edit-add-person-btn');
    const form = document.getElementById('edit-new-person-form');
    const nameInput = document.getElementById('edit-new-person-name');
    const skillsInput = document.getElementById('edit-skills-input');
    const imageUploadArea = document.getElementById('edit-image-upload-area');
    const imageUploadInput = document.getElementById('edit-image-upload-input');

    showBtn.addEventListener('click', () => {
        showBtn.style.display = 'none';
        form.style.display = 'block';
        nameInput.setAttribute('required', '');
    });
    cancelBtn.addEventListener('click', () => {
        resetEditNewPersonForm();
        form.style.display = 'none';
        showBtn.style.display = 'block';
        nameInput.removeAttribute('required');
    });
    // Image upload
    initEditImageUpload();
    // Add person
    addBtn.addEventListener('click', () => {
        const name = nameInput.value.trim();
        if (!name) {
            alert('Please enter a name');
            return;
        }
        // Check if person already exists
        if (Array.from(window.allPeople).some(p => p.toLowerCase() === name.toLowerCase()) || 
            editNewPeople.some(p => p.name.toLowerCase() === name.toLowerCase())) {
            alert('This person already exists');
            return;
        }
        const newPerson = {
            name: name,
            skills: [...editSelectedSkills],
            image: editCurrentPersonImage
        };
        editNewPeople.push(newPerson);
        updateEditNewPeopleList();
        // Reset and hide form
        resetEditNewPersonForm();
        form.style.display = 'none';
        showBtn.style.display = 'block';
        nameInput.removeAttribute('required');
    });
}

function initEditSkillsAutocomplete() {
    const editSkillsBadgesContainer = document.getElementById('edit-album-skills-badges-container');
    
    function renderEditSkillsBadges() {
        editSkillsBadgesContainer.innerHTML = editAllSkills.map(skill => `
            <div class="skill-badge-toggleable ${editSelectedSkills.includes(skill) ? 'selected' : ''}" 
                 data-skill="${skill}">${skill}</div>
        `).join('');
    }
    
    // Handle badge clicks
    editSkillsBadgesContainer.addEventListener('click', (e) => {
        if (e.target.classList.contains('skill-badge-toggleable')) {
            const skill = e.target.dataset.skill;
            
            if (editSelectedSkills.includes(skill)) {
                // Remove skill
                const index = editSelectedSkills.indexOf(skill);
                editSelectedSkills.splice(index, 1);
            } else {
                // Add skill
                editSelectedSkills.push(skill);
            }
            
            renderEditSkillsBadges();
        }
    });
    
    function addEditSkill(skill) {
        if (editSelectedSkills.includes(skill)) return;
        editSelectedSkills.push(skill);
        renderEditSkillsBadges();
    }
    
    // Store render function for external use
    window.renderEditSkillsBadges = renderEditSkillsBadges;
    
    // Initial render once skills are loaded
    if (editAllSkills.length > 0) {
        renderEditSkillsBadges();
    }
}

function initEditImageUpload() {
    const uploadArea = document.getElementById('edit-image-upload-area');
    const uploadInput = document.getElementById('edit-image-upload-input');
    const uploadContent = document.getElementById('edit-upload-content');
    uploadArea.addEventListener('click', () => {
        uploadInput.click();
    });
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleEditImageUpload(files[0]);
        }
    });
    uploadInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleEditImageUpload(e.target.files[0]);
        }
    });
    function handleEditImageUpload(file) {
        if (!file.type.startsWith('image/')) {
            alert('Please select an image file');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            alert('Image size must be less than 5MB');
            return;
        }
        // Open cropping modal instead of directly setting the image
        window.cropModal.openCropModal(file, 'edit');
    }
}

function resetEditNewPersonForm() {
    document.getElementById('edit-new-person-name').value = '';
    editSelectedSkills = [];
    editCurrentPersonImage = null;
    
    // Reset edit skills badges
    const editSkillsBadgesContainer = document.getElementById('edit-album-skills-badges-container');
    if (editSkillsBadgesContainer && editAllSkills.length > 0) {
        editSkillsBadgesContainer.innerHTML = editAllSkills.map(skill => `
            <div class="skill-badge-toggleable ${editSelectedSkills.includes(skill) ? 'selected' : ''}" data-skill="${skill}">${skill}</div>
        `).join('');
    }
    

    document.getElementById('edit-upload-content').innerHTML = `
        <div class="upload-text">
            📷 Click or drag to upload profile image<br>
            <small>(JPG, PNG, max 5MB)</small>
        </div>
    `;
}

function updateEditNewPeopleList() {
    const list = document.getElementById('edit-new-people-list');
    list.innerHTML = '';
    editNewPeople.forEach((person, index) => {
        const item = document.createElement('div');
        item.style.cssText = `
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: #333;
            border-radius: 12px;
            margin-bottom: 0.5rem;
            border: 2px solid #444;
        `;
        const imagePreview = person.image ? 
            `<img src="${URL.createObjectURL(person.image)}" style="
                width: 40px;
                height: 40px;
                border-radius: 50%;
                object-fit: cover;
                border: 2px solid #ffae52;
            " alt="${person.name}">` : 
            `<div style="
                width: 40px;
                height: 40px;
                border-radius: 50%;
                background: #555;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #ccc;
                font-size: 1.2rem;
            ">👤</div>`;
        const skillsDisplay = person.skills && person.skills.length > 0 ? 
            person.skills.map(skill => 
                `<span style="
                    background: #ffae52;
                    color: #1a1a1a;
                    padding: 0.2rem 0.5rem;
                    border-radius: 12px;
                    font-size: 0.8rem;
                    font-weight: 600;
                ">${skill}</span>`
            ).join(' ') : 
            '<span style="color: #888; font-size: 0.9rem;">No skills</span>';
        item.innerHTML = `
            ${imagePreview}
            <div style="flex: 1;">
                <div style="color: #ffae52; font-weight: 600; margin-bottom: 0.3rem;">${person.name}</div>
                <div style="display: flex; flex-wrap: wrap; gap: 0.3rem;">${skillsDisplay}</div>
            </div>
            <button type="button" style="
                background: #cf6679;
                color: white;
                border: none;
                padding: 0.4rem 0.8rem;
                border-radius: 6px;
                cursor: pointer;
                font-size: 0.9rem;
                font-weight: 600;
            " onclick="window.removeEditNewPerson(${index})">Remove</button>
        `;
        list.appendChild(item);
    });
}
window.removeEditNewPerson = function(index) {
    editNewPeople.splice(index, 1);
    updateEditNewPeopleList();
};
