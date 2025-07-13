class MemesManager {
	constructor() {
		this.memes = [];
		this.masonry = null;
		this.init();
	}

	init() {
		this.setupEventListeners();
		this.loadMemes();
	}

	setupEventListeners() {
		// FAB button
		const addMemeFab = document.getElementById('add-meme-fab');
		if (addMemeFab) {
			addMemeFab.addEventListener('click', () => this.showUploadModal());
		}

		// Modal close buttons
		const addMemeModalClose = document.getElementById('add-meme-modal-close');
		if (addMemeModalClose) {
			addMemeModalClose.addEventListener('click', () => this.hideUploadModal());
		}

		// Upload form
		const uploadForm = document.getElementById('add-meme-form');
		if (uploadForm) {
			uploadForm.addEventListener('submit', (e) => this.handleUpload(e));
		}

		// File input
		const imageInput = document.getElementById('meme-image');
		if (imageInput) {
			imageInput.addEventListener('change', (e) => this.handleImagePreview(e));
		}

		// Modal overlay close
		const modalOverlay = document.getElementById('add-meme-modal-overlay');
		if (modalOverlay) {
			modalOverlay.addEventListener('click', (e) => {
				if (e.target === modalOverlay) {
					this.hideUploadModal();
				}
			});
		}



		// Window resize handler for Masonry
		window.addEventListener('resize', this.debounce(() => {
			this.handleResize();
		}, 250));
	}

	handleResize() {
		if (this.masonry) {
			this.masonry.layout();
		}
	}

	debounce(func, wait) {
		let timeout;
		return function executedFunction(...args) {
			const later = () => {
				clearTimeout(timeout);
				func(...args);
			};
			clearTimeout(timeout);
			timeout = setTimeout(later, wait);
		};
	}

	async loadMemes() {
		try {
			const response = await fetch('/api/memes');
			const data = await response.json();
			
			this.memes = data || [];
			this.renderMemes();
		} catch (error) {
			console.error('Error loading memes:', error);
			this.showError('Failed to load memes');
		}
	}

	renderMemes() {
		const container = document.getElementById('memes-container');
		const loading = document.getElementById('loading');
		
		if (loading) {
			loading.style.display = 'none';
		}

		if (!container) return;

		if (this.memes.length === 0) {
			container.innerHTML = `
				<div class="empty-state">
					<h3>No memes yet</h3>
					<p>Be the first to share a meme!</p>
				</div>
			`;
			return;
		}

		container.innerHTML = this.memes.map(meme => this.createMemeCard(meme)).join('');
		
		// Add context menu and long-press listeners
		this.setupMemeInteractions();
		
		// Initialize masonry after images load
		this.initializeMasonry();
	}

	setupMemeInteractions() {
		const memeCards = document.querySelectorAll('.meme-card');
		
		memeCards.forEach(card => {
			const memeId = card.dataset.memeId;
			const meme = this.memes.find(m => m.id === memeId);
			const img = card.querySelector('img');
			
			// Add context menu prevention to ALL memes, but only show delete for authorized users
			const handleContextMenu = (e) => {
				e.preventDefault();
				e.stopPropagation();
				e.stopImmediatePropagation();
				
				if (meme && this.canDeleteMeme(meme)) {
					this.showDeleteConfirmation(memeId);
				}
				return false;
			};
			
			if (img) {
				card.addEventListener('contextmenu', handleContextMenu, true);
				img.addEventListener('contextmenu', handleContextMenu, true);
				
				// Long-press for mobile (only for deletable memes)
				if (meme && this.canDeleteMeme(meme)) {
					let longPressTimer;
					let isLongPress = false;
					
					const handleTouchStart = (e) => {
						isLongPress = false;
						longPressTimer = setTimeout(() => {
							isLongPress = true;
							this.showDeleteConfirmation(memeId);
						}, 500); // 500ms for long press
					};
					
					const handleTouchEnd = (e) => {
						clearTimeout(longPressTimer);
						if (isLongPress) {
							e.preventDefault();
							e.stopPropagation();
						}
					};
					
					const handleTouchMove = (e) => {
						clearTimeout(longPressTimer);
					};
					
					card.addEventListener('touchstart', handleTouchStart);
					img.addEventListener('touchstart', handleTouchStart);
					
					card.addEventListener('touchend', handleTouchEnd);
					img.addEventListener('touchend', handleTouchEnd);
					
					card.addEventListener('touchmove', handleTouchMove);
					img.addEventListener('touchmove', handleTouchMove);
				}
			}
		});
	}

	showDeleteConfirmation(memeId) {
		this.showCustomConfirmDialog(
			'Delete Meme',
			'Are you sure you want to delete this meme? This action cannot be undone.',
			() => this.deleteMeme(memeId)
		);
	}

	showCustomConfirmDialog(title, message, onConfirm) {
		// Remove any existing dialog
		const existingDialog = document.getElementById('custom-confirm-dialog');
		if (existingDialog) {
			existingDialog.remove();
		}

		// Create dialog HTML
		const dialogHtml = `
			<div id="custom-confirm-dialog" class="custom-dialog-overlay">
				<div class="custom-dialog">
					<h3 class="dialog-title">${title}</h3>
					<p class="dialog-message">${message}</p>
					<div class="dialog-actions">
						<button class="dialog-btn dialog-btn-cancel" id="dialog-cancel">Cancel</button>
						<button class="dialog-btn dialog-btn-confirm" id="dialog-confirm">Delete</button>
					</div>
				</div>
			</div>
		`;

		// Add dialog to body
		document.body.insertAdjacentHTML('beforeend', dialogHtml);

		// Add event listeners
		const dialog = document.getElementById('custom-confirm-dialog');
		const confirmBtn = document.getElementById('dialog-confirm');
		const cancelBtn = document.getElementById('dialog-cancel');

		const closeDialog = () => {
			dialog.remove();
		};

		const handleConfirm = () => {
			closeDialog();
			onConfirm();
		};

		const handleCancel = () => {
			closeDialog();
		};

		// Button event listeners
		confirmBtn.addEventListener('click', handleConfirm);
		cancelBtn.addEventListener('click', handleCancel);

		// Close on overlay click
		dialog.addEventListener('click', (e) => {
			if (e.target === dialog) {
				handleCancel();
			}
		});

		// Close on Escape key
		const handleKeydown = (e) => {
			if (e.key === 'Escape') {
				handleCancel();
				document.removeEventListener('keydown', handleKeydown);
			}
		};
		document.addEventListener('keydown', handleKeydown);

		// Focus the cancel button by default
		setTimeout(() => cancelBtn.focus(), 100);
	}

	createMemeCard(meme) {
		const imageUrl = `/redis-image/meme/${meme.id}`;
		const createdDate = this.formatDate(meme.created_at);
		
		return `
			<div class="meme-card" data-meme-id="${meme.id}">
				<div class="meme-image-container">
					<img src="${imageUrl}" alt="Meme" loading="lazy">
				</div>
				<div class="meme-meta">
					<span class="meme-date">${createdDate}</span>
				</div>
			</div>
		`;
	}

	canDeleteMeme(meme) {
		// Check if user is logged in and is the creator or admin
		const authManager = window.authManager;
		if (!authManager || !authManager.isAuthenticated || !authManager.currentUser) return false;
		
		const user = authManager.currentUser;
		return user.id === meme.creator_id || user.role === 'admin';
	}

	initializeMasonry() {
		if (this.masonry) {
			this.masonry.destroy();
		}

		const container = document.getElementById('memes-container');
		if (!container) return;

		// Wait for images to load
		const images = container.querySelectorAll('img');
		let loadedCount = 0;

		const checkAllLoaded = () => {
			loadedCount++;
			if (loadedCount === images.length) {
				container.classList.add('masonry-ready');
				this.masonry = new Masonry(container, {
					itemSelector: '.meme-card',
					columnWidth: '.meme-card',
					gutter: 20,
					fitWidth: false,
					horizontalOrder: true
				});
			}
		};

		if (images.length === 0) {
			container.classList.add('masonry-ready');
			return;
		}

		images.forEach(img => {
			if (img.complete) {
				checkAllLoaded();
			} else {
				img.addEventListener('load', checkAllLoaded);
				img.addEventListener('error', checkAllLoaded);
			}
		});
	}

	showUploadModal() {
		// Check authentication first
		const authManager = window.authManager;
		if (!authManager || !authManager.isAuthenticated) {
			this.showError('Please log in to upload memes');
			return;
		}

		const modalOverlay = document.getElementById('add-meme-modal-overlay');
		if (modalOverlay) {
			modalOverlay.classList.add('active');
		}
	}

	hideUploadModal() {
		const modalOverlay = document.getElementById('add-meme-modal-overlay');
		if (modalOverlay) {
			modalOverlay.classList.remove('active');
		}
		
		// Reset form
		this.resetUploadForm();
	}

	resetUploadForm() {
		const form = document.getElementById('add-meme-form');
		if (form) {
			form.reset();
		}
		
		const preview = document.getElementById('image-preview');
		if (preview) {
			preview.innerHTML = '';
		}
		
		const submitBtn = document.getElementById('submit-meme-btn');
		if (submitBtn) {
			submitBtn.disabled = true;
		}
	}

	handleImagePreview(event) {
		const file = event.target.files[0];
		const preview = document.getElementById('image-preview');
		const submitBtn = document.getElementById('submit-meme-btn');
		
		if (!file) {
			preview.innerHTML = '';
			submitBtn.disabled = true;
			return;
		}

		if (!file.type.startsWith('image/')) {
			this.showError('Please select an image file');
			return;
		}

		const reader = new FileReader();
		reader.onload = (e) => {
			preview.innerHTML = `
				<div class="preview-image">
					<img src="${e.target.result}" alt="Preview">
				</div>
			`;
			submitBtn.disabled = false;
		};
		reader.readAsDataURL(file);
	}

	async handleUpload(event) {
		event.preventDefault();
		
		const formData = new FormData(event.target);
		const submitBtn = document.getElementById('submit-meme-btn');
		
		if (submitBtn) {
			submitBtn.disabled = true;
			submitBtn.textContent = 'Uploading...';
		}

		try {
			const response = await fetch('/api/memes/submit', {
				method: 'POST',
				body: formData
			});

			const result = await response.json();

			if (response.ok) {
				this.showSuccess('Meme uploaded successfully!');
				this.hideUploadModal();
				this.loadMemes(); // Reload memes
			} else {
				this.showError(result.detail || 'Failed to upload meme');
			}
		} catch (error) {
			console.error('Upload error:', error);
			this.showError('Failed to upload meme');
		} finally {
			if (submitBtn) {
				submitBtn.disabled = false;
				submitBtn.textContent = 'Add Meme';
			}
		}
	}

	async deleteMeme(memeId) {
		try {
			const response = await fetch(`/api/memes/${memeId}`, {
				method: 'DELETE'
			});

			if (response.ok) {
				this.showSuccess('Meme deleted successfully!');
				this.loadMemes(); // Reload memes
			} else {
				const result = await response.json();
				this.showError(result.detail || 'Failed to delete meme');
			}
		} catch (error) {
			console.error('Delete error:', error);
			this.showError('Failed to delete meme');
		}
	}

	formatDate(dateString) {
		const date = new Date(dateString);
		return date.toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	}

	showSuccess(message) {
		this.showNotification(message, 'success');
	}

	showError(message) {
		this.showNotification(message, 'error');
	}

	showNotification(message, type) {
		const notification = document.createElement('div');
		notification.className = `notification ${type}`;
		notification.textContent = message;
		
		document.body.appendChild(notification);
		
		setTimeout(() => {
			notification.remove();
		}, 3000);
	}
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
	window.memesManager = new MemesManager();
});
