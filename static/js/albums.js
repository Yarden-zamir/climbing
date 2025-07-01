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

	async function loadAlbums() {
		try {
			showSkeletonCards();
			
			// Load albums from albums.json instead of albums.txt
			const response = await fetch("static/albums.json");
			if (!response.ok) throw new Error("Could not load albums.json");
			
			const albumsData = await response.json();
			const urls = Object.keys(albumsData); // Extract URLs from object keys
			
			console.log(`Loaded ${urls.length} album URLs from albums.json`);
			
			await processAlbums(urls);
			
		} catch (error) {
			console.error("Error loading albums:", error);
			hideSkeletonCards();
			showError("Failed to load albums. Please try refreshing the page.");
		}
	}

	loadAlbums();
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
    });

initEditNewPersonForm();

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
    // Skills autocomplete
    initEditSkillsAutocomplete();
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
        if (crewData.some(p => p.name.toLowerCase() === name.toLowerCase()) || 
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
        selectedCrew.add(name);
        updateEditNewPeopleList();
        // Reset and hide form
        resetEditNewPersonForm();
        form.style.display = 'none';
        showBtn.style.display = 'block';
        nameInput.removeAttribute('required');
    });
}

function initEditSkillsAutocomplete() {
    const skillsInput = document.getElementById('edit-skills-input');
    const autocomplete = document.getElementById('edit-skills-autocomplete');
    const selectedSkillsContainer = document.getElementById('edit-selected-skills');
    skillsInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        if (!query) {
            autocomplete.style.display = 'none';
            return;
        }
        const filteredSkills = editAllSkills.filter(skill => 
            skill.toLowerCase().includes(query) && 
            !editSelectedSkills.includes(skill)
        );
        if (filteredSkills.length === 0) {
            autocomplete.style.display = 'none';
            return;
        }
        autocomplete.innerHTML = '';
        filteredSkills.forEach(skill => {
            const item = document.createElement('div');
            item.className = 'skills-autocomplete-item';
            item.textContent = skill;
            item.addEventListener('click', () => addEditSkill(skill));
            autocomplete.appendChild(item);
        });
        autocomplete.style.display = 'block';
    });
    skillsInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const query = e.target.value.trim();
            if (query && !editSelectedSkills.includes(query)) {
                addEditSkill(query);
            }
        }
    });
    document.addEventListener('click', (e) => {
        if (!skillsInput.contains(e.target) && !autocomplete.contains(e.target)) {
            autocomplete.style.display = 'none';
        }
    });
    function addEditSkill(skill) {
        if (editSelectedSkills.includes(skill)) return;
        editSelectedSkills.push(skill);
        skillsInput.value = '';
        autocomplete.style.display = 'none';
        updateEditSelectedSkills();
    }
    function updateEditSelectedSkills() {
        selectedSkillsContainer.innerHTML = '';
        editSelectedSkills.forEach((skill, index) => {
            const tag = document.createElement('div');
            tag.className = 'skill-tag';
            tag.innerHTML = `
                ${skill}
                <button type="button" class="skill-tag-remove" onclick="window.removeEditSkill(${index})">×</button>
            `;
            selectedSkillsContainer.appendChild(tag);
        });
    }
    window.removeEditSkill = function(index) {
        editSelectedSkills.splice(index, 1);
        updateEditSelectedSkills();
    };
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
        const reader = new FileReader();
        reader.onload = (e) => {
            uploadContent.innerHTML = `
                <img src="${e.target.result}" class="image-preview" alt="Preview">
                <div class="upload-text">
                    ✅ Image uploaded<br>
                    <small>Click to change</small>
                </div>
            `;
            editCurrentPersonImage = file;
        };
        reader.readAsDataURL(file);
    }
}

function resetEditNewPersonForm() {
    document.getElementById('edit-new-person-name').value = '';
    document.getElementById('edit-skills-input').value = '';
    document.getElementById('edit-skills-autocomplete').style.display = 'none';
    editSelectedSkills = [];
    editCurrentPersonImage = null;
    document.getElementById('edit-selected-skills').innerHTML = '';
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
    const person = editNewPeople[index];
    selectedCrew.delete(person.name);
    editNewPeople.splice(index, 1);
    updateEditNewPeopleList();
};
