// Page script for /static/albums.html, moved out of the HTML unchanged.
// Global variables for modals
let editAlbumCurrentPersonImage = null;
let addAlbumCurrentPersonImage = null;

// Global function to handle cropped image result for edit album modal
window.applyImageToEditAlbum = function(croppedFile, dataUrl) {
	editAlbumCurrentPersonImage = croppedFile;
	const uploadContent = document.getElementById('edit-upload-content');
	if (uploadContent) {
		uploadContent.innerHTML = `
			<img src="${dataUrl}" class="image-preview" alt="Preview">
			<div class="upload-text">
				✅ Image uploaded (cropped)<br>
				<small>Click to change</small>
			</div>
		`;
	}
};

// Global function to handle cropped image result for add album modal
window.applyImageToAdd = function(croppedFile, dataUrl) {
	addAlbumCurrentPersonImage = croppedFile;
	const uploadContent = document.getElementById('upload-content');
	if (uploadContent) {
		uploadContent.innerHTML = `
			<img src="${dataUrl}" class="image-preview" alt="Preview">
			<div class="upload-text">
				✅ Image uploaded (cropped)<br>
				<small>Click to change</small>
			</div>
		`;
	}
};

document.addEventListener("DOMContentLoaded", () => {
	document.querySelectorAll('nav a').forEach(link => {
		link.addEventListener('click', function (e) {
			const href = this.getAttribute('href');
			if (href && !href.startsWith('#') && !this.classList.contains('active')) {
				e.preventDefault();
				const main = document.querySelector('main.page-fade');
				main.classList.add('fade-out');
				setTimeout(() => {
					window.location.href = href;
				}, 100);
			}
		});
	});
	
	// Initialize add album functionality
	initAddAlbumModal();
	
	// Check for PWA shortcut action parameter
	const urlParams = new URLSearchParams(window.location.search);
	if (urlParams.get('action') === 'add') {
		// Wait a moment for the page to fully load, then open the add album modal
		setTimeout(() => {
			const addAlbumFab = document.getElementById('add-album-fab');
			if (addAlbumFab) {
				addAlbumFab.click();
			}
		}, 500);
	}
	
	// Initialize edit album functionality
	initEditAlbumModal();
	
	// Function to smoothly update just one album's crew display
	window.refreshSingleAlbumCrew = async function(albumUrl) {
		try {
			// Fetch updated enriched albums data  
			const response = await fetch("/api/albums/enriched?_t=" + Date.now());
			if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			
			const enrichedAlbums = await response.json();
			
			// Find the updated album data - try both metadata.url and url
			const updatedAlbum = enrichedAlbums.find(album => 
				(album.metadata && album.metadata.url === albumUrl) || 
				album.url === albumUrl
			);
			
			if (!updatedAlbum) {
				return;
			}
			
			// Find the album card on the page
			const albumCard = document.querySelector(`[data-album-url="${albumUrl}"]`);
			if (!albumCard) {
				return;
			}
			
			// Get the correct metadata
			const newMetadata = updatedAlbum.metadata || updatedAlbum;
			
			// Force update regardless of perceived changes
			forceUpdateAlbumCrewDisplay(albumCard, newMetadata);
			
		} catch (error) {
			window.location.reload();
		}
	};
	
	// Force update album crew display (no change detection)
	function forceUpdateAlbumCrewDisplay(albumCard, newMetadata) {
		// Always remove any existing crew stack
		const existingCrewStack = albumCard.querySelector('.album-crew-stack');
		
		if (existingCrewStack) {
			existingCrewStack.remove();
		}
		
		// Always add new crew stack with animation
		if (newMetadata.crew && Array.isArray(newMetadata.crew) && newMetadata.crew.length > 0) {
			addNewCrewStack(albumCard, newMetadata);
		}
		
		// Always update metadata
		albumCard.albumMeta = newMetadata;
	}
	
	function addNewCrewStack(albumCard, metadata) {
		const faceStack = document.createElement('div');
		faceStack.className = 'album-crew-stack';
		
		// Initially hidden for animation
		faceStack.style.opacity = '0';
		faceStack.style.transform = 'scale(0.8)';
		faceStack.style.transition = 'opacity 0.4s ease-out, transform 0.4s ease-out';
		
		// Render the new crew faces
		metadata.crew.forEach((climber, index) => {
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
		
		albumCard.appendChild(faceStack);
		
		// Animate in the new crew stack
		setTimeout(() => {
			faceStack.style.opacity = '1';
			faceStack.style.transform = 'scale(1)';
		}, 50);
		
		// Add a subtle highlight effect to show the change
		albumCard.style.transition = 'box-shadow 0.5s ease-out';
		albumCard.style.boxShadow = '0 8px 25px rgba(3, 218, 198, 0.4)';
		setTimeout(() => {
			albumCard.style.boxShadow = '';
		}, 2000);
	}
});

// Add Album Modal Functionality
function escapeHtml(value) {
	return String(value)
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;');
}

// One shared "Learned something new?" dialog. A picker (one per album modal)
// opens it for a crew member; the dialog edits that picker's selection in place.
const learnedModal = (() => {
	const overlay = document.getElementById('learned-modal-overlay');
	const personEl = document.getElementById('learned-modal-person');
	const skillsEl = document.getElementById('learned-skills-container');
	const achievementsEl = document.getElementById('learned-achievements-container');
	let allAchievements = [];
	let session = null; // { name, allSkills, owned: {skills, achievements}, picked: {skills:Set, achievements:Set}, onChange }

	const achievementsLoaded = apiGetShared('/api/achievements')
		.then(list => { allAchievements = Array.isArray(list) ? list : []; })
		.catch(() => { allAchievements = []; });

	function renderList(container, kind, items, badgeClass) {
		const owned = session.owned[kind];
		const picked = session.picked[kind];
		if (items.length === 0) {
			container.innerHTML = `<div class="learned-hint">No ${kind} defined yet.</div>`;
			return;
		}
		container.innerHTML = items.map(item => {
			const classes = [badgeClass];
			if (owned.includes(item)) classes.push('owned');
			if (picked.has(item)) classes.push('selected');
			const label = kind === 'achievements' ? `🏆 ${escapeHtml(item)}` : escapeHtml(item);
			return `<div class="${classes.join(' ')}" data-kind="${kind}" data-item="${escapeHtml(item)}">${label}</div>`;
		}).join('');
	}

	function render() {
		if (!session) return;
		personEl.textContent = `${session.name} came back from this climb with…`;
		renderList(skillsEl, 'skills', session.allSkills, 'skill-badge-toggleable');
		renderList(achievementsEl, 'achievements', allAchievements, 'achievement-badge-toggleable');
	}

	function onBadgeClick(e) {
		const badge = e.target.closest('[data-item]');
		if (!badge || !session || badge.classList.contains('owned')) return;
		const kind = badge.dataset.kind;
		const item = badge.dataset.item;
		const picked = session.picked[kind];
		if (picked.has(item)) picked.delete(item); else picked.add(item);
		session.onChange();
		render();
	}

	function close() {
		overlay.classList.remove('active');
		session = null;
	}

	skillsEl.addEventListener('click', onBadgeClick);
	achievementsEl.addEventListener('click', onBadgeClick);
	document.getElementById('learned-done-btn').addEventListener('click', close);
	document.getElementById('learned-modal-close').addEventListener('click', close);
	overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
	document.addEventListener('keydown', e => { if (e.key === 'Escape' && session) close(); });

	return {
		async open(newSession) {
			session = newSession;
			await achievementsLoaded;
			if (session !== newSession) return;
			render();
			overlay.classList.add('active');
		}
	};
})();

// Tracks, per crew member, what they learned in the album being added or edited.
function createLearnedPicker({ getCrewData, getAllSkills }) {
	const learned = new Map(); // name -> { skills: Set, achievements: Set }
	const buttons = new Map(); // name -> button element

	function entry(name) {
		if (!learned.has(name)) learned.set(name, { skills: new Set(), achievements: new Set() });
		return learned.get(name);
	}

	function refreshButton(name) {
		const button = buttons.get(name);
		if (!button) return;
		const e = learned.get(name);
		const n = e ? e.skills.size + e.achievements.size : 0;
		button.classList.toggle('has-learned', n > 0);
		button.textContent = n > 0 ? `⚡${n}` : '⚡';
		button.title = n > 0 ? `${n} new ${n === 1 ? 'thing' : 'things'} learned in this climb` : 'Learned something new?';
	}

	return {
		attachToChip(option, name) {
			const button = document.createElement('button');
			button.type = 'button';
			button.className = 'learned-btn';
			button.setAttribute('aria-label', `What did ${name} learn in this climb?`);
			button.addEventListener('click', e => {
				e.preventDefault();
				e.stopPropagation();
				const person = getCrewData().find(p => p.name === name) || {};
				learnedModal.open({
					name,
					allSkills: getAllSkills(),
					owned: { skills: person.skills || [], achievements: person.achievements || [] },
					picked: entry(name),
					onChange: () => refreshButton(name)
				});
			});
			option.appendChild(button);
			buttons.set(name, button);
			refreshButton(name);
		},
		// Only crew members still in the album count; unchecking a chip drops their items.
		collect(selectedNames) {
			return selectedNames
				.map(name => ({ name, entry: learned.get(name) }))
				.filter(({ entry }) => entry && (entry.skills.size || entry.achievements.size))
				.map(({ name, entry }) => ({
					name,
					skills: Array.from(entry.skills),
					achievements: Array.from(entry.achievements)
				}));
		},
		reset() {
			learned.clear();
			buttons.forEach((_, name) => refreshButton(name));
		},
		forgetButtons() {
			buttons.clear();
		}
	};
}

function describeLearned(learned) {
	const parts = Object.entries(learned || {})
		.map(([name, items]) => {
			const gained = [...(items.skills || []), ...(items.achievements || [])];
			return gained.length ? `${name}: ${gained.join(', ')}` : '';
		})
		.filter(Boolean);
	return parts.length ? `⚡ Learned: ${parts.join(' · ')}` : '';
}

function initAddAlbumModal() {
	const addAlbumFab = document.getElementById('add-album-fab');
	const modalOverlay = document.getElementById('add-album-modal-overlay');
	const modal = document.getElementById('add-album-modal');
	const closeBtn = document.getElementById('add-album-modal-close');
	const form = document.getElementById('add-album-form');
	const urlInput = document.getElementById('album-url');
	const submitBtn = document.getElementById('submit-album-btn');
	
	let crewData = [];
	let selectedCrew = new Set();
	let newPeople = [];
	let urlValidationTimeout;
	let allSkills = [];
	let selectedSkills = [];
	const addLearned = createLearnedPicker({ getCrewData: () => crewData, getAllSkills: () => allSkills });

	function populateAddLocationSelector(locationNames) {
		try {
			const container = document.getElementById('location-selector');
			const input = document.getElementById('album-location');
			if (!container || !input) return;

			const unique = Array.from(new Set((locationNames || []).filter(Boolean))).sort();
			container.innerHTML = '';

			unique.forEach(name => {
				const option = document.createElement('div');
				option.className = 'location-option';
				option.innerHTML = `
					<input type="radio" name="album-location-radio" value="${name}">
					<div class="location-pin">📍</div>
					<span class="location-option-name">${name}</span>
				`;

				option.addEventListener('click', () => {
					input.value = name;
					container.querySelectorAll('.location-option').forEach(o => {
						o.classList.remove('selected');
						const r = o.querySelector('input');
						if (r) r.checked = false;
					});
					option.classList.add('selected');
					const radio = option.querySelector('input');
					if (radio) radio.checked = true;
				});

				container.appendChild(option);
			});


			// Add the "Add new…" control at the end
			const addNew = document.createElement('div');
			addNew.className = 'location-option';
			addNew.innerHTML = `
				<div class="location-pin">➕</div>
				<span class="location-option-name">Add new location…</span>
			`;
			addNew.addEventListener('click', () => {
				// Replace this option with an inline text input for new value
				const editor = document.createElement('div');
				editor.className = 'location-option selected';
				editor.innerHTML = `
					<div class="location-pin">📍</div>
					<input id="album-location-inline" type="text" class="form-input" placeholder="Type new location" style="flex:1;">
				`;
				container.replaceChild(editor, addNew);
				const inline = editor.querySelector('#album-location-inline');
				inline.focus();
				inline.addEventListener('input', () => {
					input.value = inline.value;
				});
				inline.addEventListener('keydown', (e) => {
					if (e.key === 'Enter') {
						input.value = inline.value.trim();
					}
				});

				// Unselect other options when entering new value mode
				container.querySelectorAll('.location-option').forEach(o => {
					if (o !== editor) {
						o.classList.remove('selected');
						const r = o.querySelector('input');
						if (r) r.checked = false;
					}
				});
			});
			container.appendChild(addNew);
		} catch (_) {}
	}
	
          // Fetch crew data, skills, and canonical locations
	Promise.all([
              apiGetShared('/api/crew'),
              apiGetShared('/api/skills'),
              apiGetShared('/api/locations')
          ]).then(([crew, skills, locations]) => {
		crewData = crew;
		allSkills = skills;
		const locationNames = Array.isArray(locations) ? locations.map(l => l.name || l) : [];
		if (window.fillLocationsDataList) window.fillLocationsDataList(locationNames);
		populateAddLocationSelector(locationNames);
		populateCrewSelector();
		initNewPersonForm();
		// Trigger initial render of skills badges
		const skillsBadgesContainer = document.getElementById('skills-badges-container');
		if (skillsBadgesContainer) {
			skillsBadgesContainer.innerHTML = allSkills.map(skill => `
				<div class="skill-badge-toggleable ${selectedSkills.includes(skill) ? 'selected' : ''}" data-skill="${skill}">${skill}</div>
			`).join('');
		}
	});
	
	// Open modal
	const openAddModal = () => {
		modalOverlay.classList.add('active');
		setTimeout(() => modal.classList.add('active'), 50);
	};
	addAlbumFab.addEventListener('click', () => {
		const pending = { page: location.pathname + location.search, hint: 'reopen:add-album-modal' };
		if (window.authManager && !window.authManager.requireAuth(pending)) return;
		openAddModal();
	});
	window.addEventListener('auth:pending-action', e => {
		if (e.detail && e.detail.hint === 'reopen:add-album-modal') openAddModal();
	});
	
	// Close modal
	const closeModal = () => {
		modal.classList.remove('active');
		setTimeout(() => {
			modalOverlay.classList.remove('active');
			resetForm();
		}, 300);
	};
	
	closeBtn.addEventListener('click', closeModal);
	modalOverlay.addEventListener('click', (e) => {
		if (e.target === modalOverlay) closeModal();
	});
	
	// URL validation
	urlInput.addEventListener('input', () => {
		clearTimeout(urlValidationTimeout);
		const url = urlInput.value.trim();
		
		if (!url) {
			hideUrlFeedback();
			updateSubmitButton();
			return;
		}
		
		urlValidationTimeout = setTimeout(() => validateUrl(url), 500);
	});
	
	async function validateUrl(url) {
		showUrlLoading();
		
		try {
			const response = await fetch(`/api/albums/validate-url?url=${encodeURIComponent(url)}`);
			const data = await response.json();
			
			if (data.valid) {
				if (data.exists) {
					showUrlError('This album already exists in the collection');
				} else if (data.title) {
					showUrlSuccess('Album found and accessible!');
					showAlbumPreview(data);
				} else {
					showUrlError('Album metadata could not be loaded. Please check the URL.');
				}
			} else {
				showUrlError(data.error || 'Invalid URL');
			}
		} catch (error) {
			showUrlError('Failed to validate URL');
		}
		
		updateSubmitButton();
	}
	
	function showUrlLoading() {
		const errorEl = document.getElementById('url-error');
		const successEl = document.getElementById('url-success');
		errorEl.style.display = 'none';
		successEl.style.display = 'block';
		successEl.textContent = 'Validating...';
		successEl.style.color = '#ff7a3d';
	}
	
	function showUrlError(message) {
		const errorEl = document.getElementById('url-error');
		const successEl = document.getElementById('url-success');
		urlInput.classList.add('error');
		urlInput.classList.remove('success');
		errorEl.textContent = message;
		errorEl.style.display = 'block';
		successEl.style.display = 'none';
		hideAlbumPreview();
	}
	
	function showUrlSuccess(message) {
		const errorEl = document.getElementById('url-error');
		const successEl = document.getElementById('url-success');
		urlInput.classList.remove('error');
		urlInput.classList.add('success');
		successEl.textContent = message;
		successEl.style.display = 'block';
		successEl.style.color = '#03dac6';
		errorEl.style.display = 'none';
	}
	
	function hideUrlFeedback() {
		const errorEl = document.getElementById('url-error');
		const successEl = document.getElementById('url-success');
		urlInput.classList.remove('error', 'success');
		errorEl.style.display = 'none';
		successEl.style.display = 'none';
		hideAlbumPreview();
	}
	
	function showAlbumPreview(metadata) {
		const preview = document.getElementById('album-preview');
		const proxyImageUrl = `/get-image?url=${encodeURIComponent(metadata.imageUrl)}`;
		
		preview.innerHTML = `
			<img src="${proxyImageUrl}" alt="${metadata.title}" class="album-preview-image" onerror="this.style.display='none'">
			<div class="album-preview-title">${metadata.title}</div>
			<div class="album-preview-description">${metadata.description}</div>
		`;
		preview.style.display = 'block';
	}
	
	function hideAlbumPreview() {
		document.getElementById('album-preview').style.display = 'none';
	}
	
	function populateCrewSelector() {
		const selector = document.getElementById('crew-selector');
		selector.innerHTML = '';
		addLearned.forgetButtons();
		
		crewData.forEach(person => {
			const option = document.createElement('div');
			option.className = 'crew-option';
			option.innerHTML = `
				<input type="checkbox" value="${person.name}" id="crew-${person.name.replace(/\s+/g, '-')}">
				<img src="${person.face}" alt="${person.name}" class="crew-face" onerror="this.style.display='none'">
				<span class="crew-option-name">${person.name}</span>
			`;
			addLearned.attachToChip(option, person.name);
			
			option.addEventListener('click', () => {
				const checkbox = option.querySelector('input');
				checkbox.checked = !checkbox.checked;
				
				if (checkbox.checked) {
					selectedCrew.add(person.name);
					option.classList.add('selected');
				} else {
					selectedCrew.delete(person.name);
					option.classList.remove('selected');
				}
				
				updateSubmitButton();
			});
			
			selector.appendChild(option);
		});
	}
	
	// New person form functionality
	function initNewPersonForm() {
		const showBtn = document.getElementById('show-new-person-btn');
		const cancelBtn = document.getElementById('cancel-person-btn');
		const addBtn = document.getElementById('add-person-btn');
		const form = document.getElementById('new-person-form');
		const nameInput = document.getElementById('new-person-name');
		const skillsInput = document.getElementById('skills-input');
		const imageUploadArea = document.getElementById('image-upload-area');
		const imageUploadInput = document.getElementById('image-upload-input');
		
		// Show/hide form
		showBtn.addEventListener('click', () => {
			showBtn.style.display = 'none';
			form.style.display = 'block';
			// Add required attribute when form is visible
			nameInput.setAttribute('required', '');
		});
		
		cancelBtn.addEventListener('click', () => {
			resetNewPersonForm();
			form.style.display = 'none';
			showBtn.style.display = 'block';
			// Remove required attribute when form is hidden
			nameInput.removeAttribute('required');
		});
		
		// Skills autocomplete
		initSkillsAutocomplete();
		
		// Image upload
		initImageUpload();
		
		// Add person
		addBtn.addEventListener('click', () => {
			const name = nameInput.value.trim();
			
			if (!name) {
				alert('Please enter a name');
				return;
			}
			
			// Check if person already exists
			if (crewData.some(p => p.name.toLowerCase() === name.toLowerCase()) || 
				newPeople.some(p => p.name.toLowerCase() === name.toLowerCase())) {
				alert('This person already exists');
				return;
			}
			
			const newPerson = {
				name: name,
				skills: [...selectedSkills],
				image: addAlbumCurrentPersonImage
			};
			
			newPeople.push(newPerson);
			selectedCrew.add(name);
			
			updateNewPeopleList();
			updateSubmitButton();
			
			// Reset and hide form
			resetNewPersonForm();
			form.style.display = 'none';
			showBtn.style.display = 'block';
			// Remove required attribute when form is hidden
			nameInput.removeAttribute('required');
		});
	}
	
	function initSkillsAutocomplete() {
		const skillsBadgesContainer = document.getElementById('skills-badges-container');
		
		function renderSkillsBadges() {
			skillsBadgesContainer.innerHTML = allSkills.map(skill => `
				<div class="skill-badge-toggleable ${selectedSkills.includes(skill) ? 'selected' : ''}" 
					 data-skill="${skill}">${skill}</div>
			`).join('');
		}
		
		// Handle badge clicks
		skillsBadgesContainer.addEventListener('click', (e) => {
			if (e.target.classList.contains('skill-badge-toggleable')) {
				const skill = e.target.dataset.skill;
				
				if (selectedSkills.includes(skill)) {
					// Remove skill
					const index = selectedSkills.indexOf(skill);
					selectedSkills.splice(index, 1);
				} else {
					// Add skill
					selectedSkills.push(skill);
				}
				
				renderSkillsBadges();
			}
		});
		
		function addSkill(skill) {
			if (selectedSkills.includes(skill)) return;
			
			selectedSkills.push(skill);
			renderSkillsBadges();
		}
		
		// Store render function for external use
		window.renderSkillsBadges = renderSkillsBadges;
		
		// Initial render once skills are loaded
		if (allSkills.length > 0) {
			renderSkillsBadges();
		}
	}
	
	function initImageUpload() {
		const uploadArea = document.getElementById('image-upload-area');
		const uploadInput = document.getElementById('image-upload-input');
		const uploadContent = document.getElementById('upload-content');
		
		// Click to upload
		uploadArea.addEventListener('click', () => {
			uploadInput.click();
		});
		
		// Drag and drop
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
				handleImageUpload(files[0]);
			}
		});
		
		uploadInput.addEventListener('change', (e) => {
			if (e.target.files.length > 0) {
				handleImageUpload(e.target.files[0]);
			}
		});
		
		function handleImageUpload(file) {
			if (!file.type.startsWith('image/')) {
				alert('Please select an image file');
				return;
			}
			
			if (file.size > 5 * 1024 * 1024) {
				alert('Image size must be less than 5MB');
				return;
			}
			
			// Open cropping modal instead of directly setting the image
			window.cropModal.openCropModal(file, 'add');
		}
	}
	
	function resetNewPersonForm() {
		document.getElementById('new-person-name').value = '';
		selectedSkills = [];
		addAlbumCurrentPersonImage = null;
		
		// Reset skills badges
		const skillsBadgesContainer = document.getElementById('skills-badges-container');
		if (skillsBadgesContainer && allSkills.length > 0) {
			skillsBadgesContainer.innerHTML = allSkills.map(skill => `
				<div class="skill-badge-toggleable ${selectedSkills.includes(skill) ? 'selected' : ''}" data-skill="${skill}">${skill}</div>
			`).join('');
		}
		

		document.getElementById('upload-content').innerHTML = `
			<div class="upload-text">
				📷 Click or drag to upload profile image<br>
				<small>(JPG, PNG, max 5MB)</small>
			</div>
		`;
	}
	
	function updateNewPeopleList() {
		const list = document.getElementById('new-people-list');
		list.innerHTML = '';
		
		newPeople.forEach((person, index) => {
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
					border: 2px solid #ff7a3d;
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
						background: #ff7a3d;
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
					<div style="color: #ff7a3d; font-weight: 600; margin-bottom: 0.3rem;">${person.name}</div>
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
				" onclick="removeNewPerson(${index})">Remove</button>
			`;
			
			list.appendChild(item);
		});
	}
	
	// Make removeNewPerson available globally
	window.removeNewPerson = function(index) {
		const person = newPeople[index];
		selectedCrew.delete(person.name);
		newPeople.splice(index, 1);
		updateNewPeopleList();
		updateSubmitButton();
	};
	
	function updateSubmitButton() {
		const url = urlInput.value.trim();
		const hasValidUrl = url && !urlInput.classList.contains('error') && 
						   document.getElementById('url-success').style.display === 'block';
		const hasSelectedCrew = selectedCrew.size > 0;
		
		submitBtn.disabled = !(hasValidUrl && hasSelectedCrew);
	}
	
	// Form submission
	form.addEventListener('submit', async (e) => {
		e.preventDefault();
		
		const url = urlInput.value.trim();
		const locationField = document.getElementById('album-location');
		const albumLocation = locationField ? locationField.value.trim() : '';
		const crew = Array.from(selectedCrew);
		
		submitBtn.disabled = true;
		submitBtn.textContent = 'Submitting...';
		
		try {
			// Upload images for new people first
			const processedNewPeople = [];
			
			for (const person of newPeople) {
				let processedPerson = {
					name: person.name,
					skills: person.skills || [],
					location: [],
					achievements: []
				};
				
				// Upload image if provided
				if (person.image) {
					try {
						const formData = new FormData();
						formData.append('file', person.image);
						formData.append('person_name', person.name);
						
						const uploadResponse = await fetch('/api/upload-face', {
							method: 'POST',
							body: formData
						});
						
						if (uploadResponse.ok) {
							const uploadData = await uploadResponse.json();
							processedPerson.temp_image_path = uploadData.temp_path;
						}
					} catch (uploadError) {
						console.warn('Failed to upload image for', person.name, uploadError);
					}
				}
				
				processedNewPeople.push(processedPerson);
			}
			
			const response = await fetch('/api/albums/submit', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					url,
					crew,
					location: albumLocation || null,
					new_people: processedNewPeople,
					learned: addLearned.collect(crew)
				})
			});
			
			const data = await response.json();
			
			if (response.ok) {
				showSubmissionSuccess(data);
			} else if (response.status === 401) {
				showSubmissionError('You are signed out. Sign in and submit again; your entries stay in this form.');
				if (window.authManager) window.authManager.requireLogin({ page: location.pathname + location.search, hint: 'reopen:add-album-modal' });
			} else {
				showSubmissionError(data.detail || 'Submission failed');
			}
		} catch (error) {
			showSubmissionError('Could not reach the server. Check your connection and try again.');
		} finally {
			submitBtn.textContent = 'Add Album';
			updateSubmitButton();
		}
	});
	
	async function showSubmissionSuccess(data) {
		const learnedSummary = describeLearned(data.learned);
		if (learnedSummary && window.showToast) window.showToast(learnedSummary, { type: 'success', duration: 6000 });
		
		// Close modal immediately
		closeModal();
		
		// Store the submitted album URL for later scrolling
		const submittedAlbumUrl = urlInput.value.trim();
		
		// Trigger refresh with retry logic to ensure new album appears
		await refreshWithRetry(submittedAlbumUrl);
	}
	
	async function refreshWithRetry(expectedAlbumUrl, maxRetries = 5, delayBetweenRetries = 200) {
		for (let attempt = 1; attempt <= maxRetries; attempt++) {
			try {
				// Check if album exists in the API before refreshing UI
				const response = await fetch("/api/albums/enriched");
				if (response.ok) {
					const enrichedAlbums = await response.json();
					const albumExists = enrichedAlbums.some(album => 
						(album.metadata && album.metadata.url === expectedAlbumUrl) || 
						album.url === expectedAlbumUrl
					);
					
					if (albumExists) {
						// Album is available, now refresh the UI with animations
						if (window.autoRefreshAlbums) {
							await window.autoRefreshAlbums(false, true); // showLoadingState=false, detectChanges=true
						} else {
							window.location.reload();
						}
						return; // Success - exit retry loop
					}
				}
				
				// Album not ready yet, wait before next attempt
				if (attempt < maxRetries) {
					await new Promise(resolve => setTimeout(resolve, delayBetweenRetries));
					delayBetweenRetries *= 1.5; // Exponential backoff
				}
			} catch (error) {
				console.warn(`Refresh attempt ${attempt} failed:`, error);
				if (attempt === maxRetries) {
					// Final fallback after all retries failed
					window.location.reload();
				}
			}
		}
		
		// If we get here, album wasn't found after all retries - do a final refresh
		if (window.autoRefreshAlbums) {
			await window.autoRefreshAlbums(false, true);
		} else {
			window.location.reload();
		}
	}
	
	function showSubmissionError(message) {
		const status = document.getElementById('submission-status');
		status.innerHTML = `
			<div style="color: #cf6679; font-weight: 600;">
				❌ ${message}
			</div>
		`;
		submitBtn.disabled = false;
		submitBtn.textContent = 'Add Album';
	}
	
	function resetForm() {
		form.reset();
		selectedCrew.clear();
		addLearned.reset();
		newPeople = [];
		selectedSkills = [];
		addAlbumCurrentPersonImage = null;
		hideUrlFeedback();
		hideAlbumPreview();
		updateNewPeopleList();
		updateSubmitButton();
		document.getElementById('submission-status').innerHTML = '';
		submitBtn.textContent = 'Add Album';
		
		// Reset crew selector
		document.querySelectorAll('.crew-option').forEach(option => {
			option.classList.remove('selected');
			option.querySelector('input').checked = false;
		});
		
		// Reset new person form
		const newPersonForm = document.getElementById('new-person-form');
		const showBtn = document.getElementById('show-new-person-btn');
		const nameInput = document.getElementById('new-person-name');
		if (newPersonForm.style.display === 'block') {
			resetNewPersonForm();
			newPersonForm.style.display = 'none';
			showBtn.style.display = 'block';
			// Remove required attribute when form is hidden
			nameInput.removeAttribute('required');
		}
	}
}

// Edit Album Modal Functionality
function initEditAlbumModal() {
	const editAlbumFab = document.getElementById('edit-album-fab');
	const editModeOverlay = document.getElementById('edit-mode-overlay');
	const editModeMessage = document.getElementById('edit-mode-message');
	const editModalOverlay = document.getElementById('edit-album-modal-overlay');
	const editModal = document.getElementById('edit-album-modal');
	const editCloseBtn = document.getElementById('edit-album-modal-close');
	const editForm = document.getElementById('edit-album-form');
	const editSubmitBtn = document.getElementById('edit-submit-btn');
	const deleteAlbumBtn = document.getElementById('delete-album-btn');
	
	let isEditMode = false;
	let currentEditAlbum = null;
	let crewData = [];
	let selectedCrew = new Set();
	let editNewPeople = [];
	let editAllSkills = [];
	const editLearned = createLearnedPicker({ getCrewData: () => crewData, getAllSkills: () => editAllSkills });

	function populateEditLocationSelector(locationNames) {
		try {
			const container = document.getElementById('edit-location-selector');
			const input = document.getElementById('edit-album-location');
			if (!container || !input) return;

			const unique = Array.from(new Set((locationNames || []).filter(Boolean))).sort();
			container.innerHTML = '';

			unique.forEach(name => {
				const option = document.createElement('div');
				option.className = 'location-option';
				option.innerHTML = `
					<input type="radio" name="edit-album-location-radio" value="${name}">
					<div class=\"location-pin\">📍</div>
					<span class=\"location-option-name\">${name}</span>
				`;

				option.addEventListener('click', () => {
					input.value = name;
					container.querySelectorAll('.location-option').forEach(o => {
						o.classList.remove('selected');
						const r = o.querySelector('input');
						if (r) r.checked = false;
					});
					option.classList.add('selected');
					const radio = option.querySelector('input');
					if (radio) radio.checked = true;
				});

				container.appendChild(option);
			});


			// Add the "Add new…" control at the end
			const addNew = document.createElement('div');
			addNew.className = 'location-option';
			addNew.innerHTML = `
				<div class="location-pin">➕</div>
				<span class="location-option-name">Add new location…</span>
			`;
			addNew.addEventListener('click', () => {
				// Replace this option with an inline text input for new value
				const editor = document.createElement('div');
				editor.className = 'location-option selected';
				editor.innerHTML = `
					<div class="location-pin">📍</div>
					<input id="edit-album-location-inline" type="text" class="form-input" placeholder="Type new location" style="flex:1;">
				`;
				container.replaceChild(editor, addNew);
				const inline = editor.querySelector('#edit-album-location-inline');
				inline.focus();
				inline.addEventListener('input', () => {
					input.value = inline.value;
				});
				inline.addEventListener('keydown', (e) => {
					if (e.key === 'Enter') {
						input.value = inline.value.trim();
					}
				});

				// Unselect other options when entering new value mode
				container.querySelectorAll('.location-option').forEach(o => {
					if (o !== editor) {
						o.classList.remove('selected');
						const r = o.querySelector('input');
						if (r) r.checked = false;
					}
				});
			});
			container.appendChild(addNew);

			// Pre-select current value if present
			const current = (input.value || '').trim().toLowerCase();
			if (current) {
				container.querySelectorAll('.location-option').forEach(o => {
					const text = (o.querySelector('.location-option-name')?.textContent || '').toLowerCase();
					const match = text === current;
					o.classList.toggle('selected', match);
					const r = o.querySelector('input');
					if (r) r.checked = match;
				});
			}
		} catch (_) {}
	}
	
	// Fetch crew data and the skill catalogue (for the learned-something-new picker)
	apiGetShared('/api/crew')
		.then(crew => {
			crewData = crew;
		})
		.catch(e => console.warn('Could not load crew:', e));
	apiGetShared('/api/skills')
		.then(skills => { editAllSkills = Array.isArray(skills) ? skills : []; })
		.catch(() => {});

	// Also load canonical locations for edit selector
	apiGetShared('/api/locations')
		.then(locs => {
			const names = Array.isArray(locs) ? locs.map(l => l.name || l) : [];
			if (window.fillLocationsDataList) window.fillLocationsDataList(names);
			populateEditLocationSelector(names);
		})
		.catch(() => {});
	
	// Delete album functionality
	deleteAlbumBtn.addEventListener('click', async () => {
		if (!currentEditAlbum) return;
		
		const albumTitle = currentEditAlbum.meta.title || 'this album';
		const confirmed = confirm(`Are you sure you want to delete "${albumTitle}"?\n\nThis action cannot be undone and will:\n- Remove the album from the collection\n- Update all crew members' climb counts\n- Remove all references to this album\n\nProceed with deletion?`);
		
		if (!confirmed) return;
		
		deleteAlbumBtn.disabled = true;
		deleteAlbumBtn.textContent = '🗑️ Deleting...';
		
		try {
			const response = await fetch(`/api/albums/delete?album_url=${encodeURIComponent(currentEditAlbum.url)}`, {
				method: 'DELETE'
			});
			
			const data = await response.json();
			
			if (response.ok) {
				showEditSubmissionSuccess({
					message: data.message,
					isDeleted: true
				});
			} else {
				showEditSubmissionError(data.detail || 'Delete failed');
			}
		} catch (error) {
			showEditSubmissionError('Network error occurred during deletion');
		} finally {
			deleteAlbumBtn.disabled = false;
			deleteAlbumBtn.textContent = '🗑️ Delete Album';
		}
	});
	
	// Initialize new person form functionality
	initEditNewPersonFormModal();
	
	// Initialize image upload for edit modal
	initEditImageUploadModal();
	
	// Toggle edit mode
	editAlbumFab.addEventListener('click', () => {
		if (!isEditMode) {
			const pending = { page: location.pathname + location.search, hint: 'reopen:edit-album-mode' };
			if (window.authManager && !window.authManager.requireAuth(pending)) return;
		}
		isEditMode = !isEditMode;
		toggleEditMode();
	});
	window.addEventListener('auth:pending-action', e => {
		if (e.detail && e.detail.hint === 'reopen:edit-album-mode' && !isEditMode) {
			isEditMode = true;
			toggleEditMode();
		}
	});
	
	function toggleEditMode() {
		if (isEditMode) {
			// Enter edit mode
			editAlbumFab.classList.add('active');
			editModeOverlay.classList.add('active');
			editModeMessage.classList.add('active');
			
			// Make album cards clickable
			document.querySelectorAll('.album-card').forEach(card => {
				card.classList.add('edit-mode');
				card.addEventListener('click', handleAlbumClick);
			});
		} else {
			// Exit edit mode
			editAlbumFab.classList.remove('active');
			editModeOverlay.classList.remove('active');
			editModeMessage.classList.remove('active');
			
			// Remove edit mode from album cards
			document.querySelectorAll('.album-card').forEach(card => {
				card.classList.remove('edit-mode');
				card.removeEventListener('click', handleAlbumClick);
			});
		}
	}
	
	function handleAlbumClick(e) {
		if (!isEditMode) return;
		
		e.preventDefault();
		e.stopPropagation();
		
		const albumCard = e.currentTarget;
		const albumUrl = albumCard.dataset.albumUrl;
		const albumMeta = albumCard.albumMeta; // This should be attached when creating cards
		
		if (albumUrl && albumMeta) {
			openEditModal(albumUrl, albumMeta);
		}
	}
	
	function openEditModal(albumUrl, albumMeta) {
		currentEditAlbum = {
			url: albumUrl,
			meta: albumMeta
		};
		
		// Exit edit mode
		isEditMode = false;
		toggleEditMode();
		
		// Populate modal with album info
		populateEditModal(albumMeta);
		
		// Show modal
		editModalOverlay.classList.add('active');
		setTimeout(() => editModal.classList.add('active'), 50);
	}
	
	function populateEditModal(albumMeta) {
		// Populate album info
		const albumInfo = document.getElementById('edit-album-info');
		const proxyImageUrl = `/get-image?url=${encodeURIComponent(albumMeta.imageUrl)}`;
		
		albumInfo.innerHTML = `
			<img src="${proxyImageUrl}" alt="${albumMeta.title}" class="album-info-image" onerror="this.style.display='none'">
			<div class="album-info-title">${albumMeta.title}</div>
			<div class="album-info-url">${currentEditAlbum.url}</div>
		`;

		// Pre-fill location
		const editLocationInput = document.getElementById('edit-album-location');
              if (editLocationInput) {
                  // Try to load canonical locations for autocomplete
                  apiGetShared('/api/locations').then(locs => {
                      const names = Array.isArray(locs) ? locs.map(l => l.name || l) : [];
                      if (window.fillLocationsDataList) window.fillLocationsDataList(names);
                      populateEditLocationSelector(names);
                  }).catch(() => {});
                  editLocationInput.value = albumMeta.location || '';
                  // After setting value, reflect selection in custom selector if present
                  try {
                      const container = document.getElementById('edit-location-selector');
                      if (container) {
                          const val = (editLocationInput.value || '').trim().toLowerCase();
                          container.querySelectorAll('.location-option').forEach(o => {
                              const text = (o.querySelector('.location-option-name')?.textContent || '').toLowerCase();
                              const match = val && text === val;
                              o.classList.toggle('selected', match);
                              const r = o.querySelector('input');
                              if (r) r.checked = match;
                          });
                      }
                  } catch (_) {}
              }
		
					// Get current crew for this album
	const currentCrew = albumMeta.crew || [];
	selectedCrew.clear();
	currentCrew.forEach(member => {
		// Ensure we only add the name string, not the full object
		const memberName = typeof member === 'string' ? member : member.name;
		selectedCrew.add(memberName);
	});
		
		// Populate crew selector
		populateEditCrewSelector();
	}
	
	function populateEditCrewSelector() {
		const selector = document.getElementById('edit-crew-selector');
		selector.innerHTML = '';
		editLearned.forgetButtons();
		
		crewData.forEach(person => {
			const isSelected = selectedCrew.has(person.name);
			const option = document.createElement('div');
			option.className = `crew-option ${isSelected ? 'selected' : ''}`;
			option.innerHTML = `
				<input type="checkbox" value="${person.name}" id="edit-crew-${person.name.replace(/\s+/g, '-')}" ${isSelected ? 'checked' : ''}>
				<img src="${person.face}" alt="${person.name}" class="crew-face" onerror="this.style.display='none'">
				<span class="crew-option-name">${person.name}</span>
			`;
			editLearned.attachToChip(option, person.name);
			
			option.addEventListener('click', () => {
				const checkbox = option.querySelector('input');
				checkbox.checked = !checkbox.checked;
				
				if (checkbox.checked) {
					// Ensure we only add the name string, never the full object
					const memberName = typeof person === 'string' ? person : person.name;
					selectedCrew.add(memberName);
					option.classList.add('selected');
				} else {
					// Ensure we delete the name string, never the full object
					const memberName = typeof person === 'string' ? person : person.name;
					selectedCrew.delete(memberName);
					option.classList.remove('selected');
				}
			});
			
			selector.appendChild(option);
		});
	}
	
	// Close modal
	const closeEditModal = () => {
		editModal.classList.remove('active');
		setTimeout(() => {
			editModalOverlay.classList.remove('active');
			resetEditForm();
		}, 300);
	};
	
	editCloseBtn.addEventListener('click', closeEditModal);
	editModalOverlay.addEventListener('click', (e) => {
		if (e.target === editModalOverlay) closeEditModal();
	});
	
	// Form submission
	editForm.addEventListener('submit', async (e) => {
		e.preventDefault();
		
		const newCrew = Array.from(selectedCrew);
		
		// Validate crew selection
		if (newCrew.length === 0) {
			showEditSubmissionError('Please select at least one crew member');
			return;
		}
		
		// Validate crew limit
		if (newCrew.length > 10) {
			showEditSubmissionError('Maximum 10 crew members allowed');
			return;
		}
		
		editSubmitBtn.disabled = true;
		editSubmitBtn.textContent = 'Updating...';
		
		try {
			// Upload images for new people first
			const processedNewPeople = [];
			let imageUploadErrors = [];
			
			for (const person of editNewPeople) {
				let tempImagePath = null;
				
				// Upload image if provided
				if (person.image) {
					try {
						const formData = new FormData();
						formData.append('file', person.image);
						formData.append('person_name', person.name);
						
						const uploadResponse = await fetch('/api/upload-face', {
							method: 'POST',
							body: formData
						});
						
						if (uploadResponse.ok) {
							const uploadData = await uploadResponse.json();
							tempImagePath = uploadData.temp_path;
						} else {
							const errorData = await uploadResponse.json().catch(() => ({ detail: 'Unknown error' }));
							imageUploadErrors.push(`Failed to upload image for ${person.name}: ${errorData.detail}`);
						}
					} catch (uploadError) {
						console.error('Image upload error:', uploadError);
						imageUploadErrors.push(`Failed to upload image for ${person.name}: Network error`);
					}
				}
				
				processedNewPeople.push({
					name: person.name,
					skills: person.skills || [],
					location: person.location || [],
					achievements: person.achievements || [],
					temp_image_path: tempImagePath
				});
			}
			
			// Show warnings for image upload failures but continue
			if (imageUploadErrors.length > 0) {
				console.warn('Image upload errors:', imageUploadErrors);
			}
			
												// Ensure crew is always an array of strings
			const cleanCrew = newCrew.map(member => {
				if (typeof member === 'string') {
					return member;
				} else if (member && typeof member === 'object' && member.name) {
					return member.name;
				} else {
					console.warn('Invalid crew member:', member);
					return String(member);
				}
			});
			
			const requestPayload = {
				album_url: currentEditAlbum.url,
				crew: cleanCrew,
				new_people: processedNewPeople,
				learned: editLearned.collect(cleanCrew)
			};

			// Include metadata edits (location only for now)
			const editLocationField = document.getElementById('edit-album-location');
			if (editLocationField) {
				const newLoc = editLocationField.value.trim();
				if (newLoc !== ((currentEditAlbum && currentEditAlbum.meta && currentEditAlbum.meta.location) || '')) {
					// Ensure location exists (idempotent), then update album metadata
					fetch('/api/locations', {
						method: 'POST',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({ name: newLoc })
					}).catch(() => {});
					fetch('/api/albums/edit-metadata', {
						method: 'POST',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({ album_url: currentEditAlbum.url, location: newLoc })
					}).catch(() => {});
				}
			}
		
		console.log('Selected crew before processing:', Array.from(selectedCrew));
		console.log('New crew after Array.from:', newCrew);
		console.log('Clean crew after processing:', cleanCrew);
		console.log('Submitting edit request:', requestPayload);
			
			const response = await fetch('/api/albums/edit-crew', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify(requestPayload)
			});
			
			const data = await response.json();
			
			if (response.ok) {
				let successMessage = data.message;
				
				// Add info about created climbers
				if (data.created_climbers && data.created_climbers.length > 0) {
					successMessage += `\n\nNew climbers created: ${data.created_climbers.join(', ')}`;
				}
				const learnedSummary = describeLearned(data.learned);
				if (learnedSummary) successMessage += `\n\n${learnedSummary}`;
				
				// Add warnings about image uploads if any failed
				if (imageUploadErrors.length > 0) {
					successMessage += `\n\nNote: Some images failed to upload:\n${imageUploadErrors.join('\n')}`;
				}
				
				showEditSubmissionSuccess({ ...data, message: successMessage });
			} else {
				// Handle different error types
				let errorMessage = data.detail || 'Update failed';
				
				// If it's a validation error (422), pass the whole response for better error display
				if (response.status === 422) {
					try {
						errorMessage = JSON.stringify(data);
					} catch (e) {
						errorMessage = `Invalid data: ${errorMessage}`;
					}
				} else if (response.status === 400) {
					errorMessage = `Validation error: ${errorMessage}`;
				} else if (response.status === 403) {
					errorMessage = `Permission denied: ${errorMessage}`;
				} else if (response.status === 404) {
					errorMessage = `Album not found: ${errorMessage}`;
				} else if (response.status >= 500) {
					errorMessage = `Server error: ${errorMessage}`;
				}
				
				showEditSubmissionError(errorMessage);
			}
		} catch (error) {
			console.error('Edit submission error:', error);
			
			let errorMessage = 'Network error occurred';
			if (error.name === 'TypeError' && error.message.includes('fetch')) {
				errorMessage = 'Unable to connect to server. Please check your internet connection.';
			} else if (error.name === 'AbortError') {
				errorMessage = 'Request timed out. Please try again.';
			}
			
			showEditSubmissionError(errorMessage);
		} finally {
			editSubmitBtn.disabled = false;
			editSubmitBtn.textContent = 'Update Crew';
		}
	});
	
	async function showEditSubmissionSuccess(data) {
		const status = document.getElementById('edit-submission-status');
		
		if (data.isDeleted) {
			// Special handling for deletion
		status.innerHTML = `
			<div class="refresh-success" style="color: #03dac6; font-weight: 600; margin-bottom: 1rem;">
				✅ ${data.message}
			</div>
			<div style="color: #ccc; font-size: 0.9rem;">
					The album has been permanently removed from the collection.
			</div>
			`;
			
			// Find and animate the album card immediately before refresh
			if (currentEditAlbum) {
				const albumCard = document.querySelector(`[data-album-url="${currentEditAlbum.url}"]`);
				if (albumCard && window.albumParticleSystem) {
					const rect = albumCard.getBoundingClientRect();
					albumCard.remove();
					window.albumParticleSystem.createLineParticles(rect, 40);
					// Update data arrays immediately
					if (window.allAlbums) {
						window.allAlbums = window.allAlbums.filter(album => album.meta.url !== currentEditAlbum.url);
					}
					if (window.previousAlbumData) {
						window.previousAlbumData = window.previousAlbumData.filter(album => album.url !== currentEditAlbum.url);
					}
					currentEditAlbum = null;
				}
			}
			
			// Create immediate delete particles from the modal
			const modal = document.getElementById('edit-album-modal');
			if (modal && window.albumParticleSystem) {
				window.albumParticleSystem.createParticles(modal, 'red deleted', 18);
			}
		} else {
			// Regular update success
			status.innerHTML = `
				<div class="refresh-success" style="color: #03dac6; font-weight: 600; margin-bottom: 1rem;">
					✅ ${data.message}
				</div>
				<div style="color: #ccc; font-size: 0.9rem;">
					Album crew has been updated and is now live!
				</div>
		`;
		
			// Create immediate update particles from the modal
			const modal = document.getElementById('edit-album-modal');
			if (modal && window.albumParticleSystem) {
				window.albumParticleSystem.createParticles(modal, 'green updated', 15);
			}
		}
		
		// Close modal immediately and refresh in background
		closeEditModal();
		
		// For deletions, do smooth removal instead of hard refresh
		if (data.isDeleted && currentEditAlbum) {
			// Smooth deletion: find and fade out the album card
			const albumCard = document.querySelector(`[data-album-url="${currentEditAlbum.url}"]`);
			
			if (albumCard) {
				// Add smooth fade-out animation
				albumCard.style.transition = 'all 0.8s ease-out';
				albumCard.style.opacity = '0';
				albumCard.style.transform = 'scale(0.8) translateY(20px)';
				
				// After fade-out, remove and let grid auto-adjust
				setTimeout(() => {
					albumCard.remove();
					
					// Update data arrays
					if (window.allAlbums) {
						window.allAlbums = window.allAlbums.filter(album => album.meta.url !== currentEditAlbum.url);
					}
					if (window.previousAlbumData) {
						window.previousAlbumData = window.previousAlbumData.filter(album => album.url !== currentEditAlbum.url);
					}
					
					// Clear current edit album
					currentEditAlbum = null;
				}, 800);
			}
		} else {
			// Store URL before clearing currentEditAlbum
			const albumUrlToRefresh = currentEditAlbum.url;
			// Smoothly update just the edited album's crew display  
			setTimeout(() => {
				refreshSingleAlbumCrew(albumUrlToRefresh);
			}, 1500);
		}
	}
	
	function showEditSubmissionError(message) {
		const status = document.getElementById('edit-submission-status');
		
		// Handle validation errors from server
		let errorHtml = `<div style="color: #cf6679; font-weight: 600;">❌ ${message}</div>`;
		
		// Parse validation errors if it's JSON
		try {
			const parsedError = JSON.parse(message);
			if (parsedError.detail && Array.isArray(parsedError.detail)) {
				errorHtml = `<div style="color: #cf6679; font-weight: 600;">❌ Validation Errors:</div>`;
				parsedError.detail.forEach(error => {
					const field = error.loc ? error.loc.join('.') : 'unknown';
					errorHtml += `<div style="color: #cf6679; font-size: 0.9rem; margin-top: 0.5rem; padding-left: 1rem;">• ${field}: ${error.msg}</div>`;
				});
			}
		} catch (e) {
			// If it's not JSON, check if it contains validation error structure
			if (message.includes('"detail":[') && message.includes('"type"')) {
				try {
					const match = message.match(/\{\"detail\":\[(.*?)\]\}/);
					if (match) {
						const fullJson = `{"detail":[${match[1]}]}`;
						const parsedError = JSON.parse(fullJson);
						if (parsedError.detail && Array.isArray(parsedError.detail)) {
							errorHtml = `<div style="color: #cf6679; font-weight: 600;">❌ Validation Errors:</div>`;
							parsedError.detail.forEach(error => {
								const field = error.loc ? error.loc.join('.') : 'unknown';
								errorHtml += `<div style="color: #cf6679; font-size: 0.9rem; margin-top: 0.5rem; padding-left: 1rem;">• ${field}: ${error.msg}</div>`;
							});
						}
					}
				} catch (e2) {
					// Fall back to original message
				}
			}
		}
		
		status.innerHTML = errorHtml;
		editSubmitBtn.disabled = false;
		editSubmitBtn.textContent = 'Update Crew';
	}
	
	function resetEditForm() {
		selectedCrew.clear();
		editLearned.reset();
		currentEditAlbum = null;
		editNewPeople = [];
		editAlbumCurrentPersonImage = null;
		document.getElementById('edit-submission-status').innerHTML = '';
		editSubmitBtn.textContent = 'Update Crew';
		editSubmitBtn.disabled = false;
		
		// Reset new people list
		document.getElementById('edit-new-people-list').innerHTML = '';
		
		// Reset new person form
		const editNewPersonForm = document.getElementById('edit-new-person-form');
		const editShowBtn = document.getElementById('edit-show-new-person-btn');
		if (editNewPersonForm.style.display === 'block') {
			editNewPersonForm.style.display = 'none';
			editShowBtn.style.display = 'block';
		}
		
		// Reset image upload area
		resetEditNewPersonFormModal();
	}
	
	function initEditNewPersonFormModal() {
		const showBtn = document.getElementById('edit-show-new-person-btn');
		const cancelBtn = document.getElementById('edit-cancel-person-btn');
		const addBtn = document.getElementById('edit-add-person-btn');
		const form = document.getElementById('edit-new-person-form');
		const nameInput = document.getElementById('edit-new-person-name');
		
		// Show form
		showBtn.addEventListener('click', () => {
			showBtn.style.display = 'none';
			form.style.display = 'block';
		});
		
		// Cancel form
		cancelBtn.addEventListener('click', () => {
			form.style.display = 'none';
			showBtn.style.display = 'block';
			resetEditNewPersonFormModal();
		});
		
		// Add person
		addBtn.addEventListener('click', () => {
			const name = nameInput.value.trim();
			if (!name) {
				alert('Please enter a name');
				return;
			}
			
			// Validate name length
			if (name.length < 2) {
				alert('Name must be at least 2 characters long');
				return;
			}
			
			if (name.length > 50) {
				alert('Name must be less than 50 characters');
				return;
			}
			
			// Check if person already exists
			if (crewData.some(p => p.name.toLowerCase() === name.toLowerCase()) || 
				editNewPeople.some(p => p.name.toLowerCase() === name.toLowerCase()) ||
				selectedCrew.has(name)) {
				alert('This person already exists');
				return;
			}
			
			const newPerson = {
				name: name,
				skills: editSelectedSkills || [],
				location: [], // TODO: Add location input fields to the form
				achievements: [], // TODO: Add achievements input fields to the form
				image: editAlbumCurrentPersonImage
			};
			
			editNewPeople.push(newPerson);
			// Ensure we only add the name string to selectedCrew
			selectedCrew.add(name);
			updateEditNewPeopleList();
			
			// Reset and hide form
			resetEditNewPersonFormModal();
			form.style.display = 'none';
			showBtn.style.display = 'block';
		});
	}
	
	function resetEditNewPersonFormModal() {
		document.getElementById('edit-new-person-name').value = '';
		editAlbumCurrentPersonImage = null;
		
		// Reset image upload area
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
					border: 2px solid #ff7a3d;
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
			
			item.innerHTML = `
				${imagePreview}
				<div style="flex: 1;">
					<div style="color: #ff7a3d; font-weight: 600;">${person.name}</div>
					<div style="color: #888; font-size: 0.9rem;">New person</div>
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
				" onclick="removeEditNewPerson(${index})">Remove</button>
			`;
			list.appendChild(item);
		});
	}
	
	// Global function to remove new person
	window.removeEditNewPerson = function(index) {
		const person = editNewPeople[index];
		selectedCrew.delete(person.name);
		editNewPeople.splice(index, 1);
		updateEditNewPeopleList();
	};
	
	function initEditImageUploadModal() {
		const uploadArea = document.getElementById('edit-image-upload-area');
		const uploadInput = document.getElementById('edit-image-upload-input');
		
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
				handleEditImageUploadModal(files[0]);
			}
		});
		
		uploadInput.addEventListener('change', (e) => {
			if (e.target.files.length > 0) {
				handleEditImageUploadModal(e.target.files[0]);
			}
		});
	}
	
	function handleEditImageUploadModal(file) {
		if (!file.type.startsWith('image/')) {
			alert('Please select an image file');
			return;
		}
		if (file.size > 5 * 1024 * 1024) {
			alert('Image size must be less than 5MB');
			return;
		}
		// Open cropping modal
		window.cropModal.openCropModal(file, 'edit-album');
	}
	

}
	
