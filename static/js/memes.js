class MemesManager {
	constructor() {
		this.memes = [];
		this.masonry = null;
		this.selectedFiles = [];
		this.currentContextMeme = null;
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

		// Context menu overlay close
		const contextMenuOverlay = document.getElementById('context-menu-modal');
		if (contextMenuOverlay) {
			contextMenuOverlay.addEventListener('click', (e) => {
				if (e.target === contextMenuOverlay) {
					this.hideContextMenu();
				}
			});
		}

		// Context menu actions
		const contextDownload = document.getElementById('context-download');
		const contextShare = document.getElementById('context-share');
		const contextDelete = document.getElementById('context-delete');

		if (contextDownload) {
			contextDownload.addEventListener('click', () => this.downloadMeme());
		}

		if (contextShare) {
			contextShare.addEventListener('click', () => this.shareMeme());
		}

		if (contextDelete) {
			contextDelete.addEventListener('click', () => this.confirmDeleteMeme());
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
			
			// Add context menu for ALL memes (download/share available to everyone)
			const handleContextMenu = (e) => {
				e.preventDefault();
				e.stopPropagation();
				e.stopImmediatePropagation();
				
				if (meme) {
					this.showContextMenu(meme, e.clientX, e.clientY);
				}
				return false;
			};
			
			if (img) {
				card.addEventListener('contextmenu', handleContextMenu, true);
				img.addEventListener('contextmenu', handleContextMenu, true);
				
				// Long-press for mobile
				let longPressTimer;
				let isLongPress = false;
				
				const handleTouchStart = (e) => {
					isLongPress = false;
					longPressTimer = setTimeout(() => {
						isLongPress = true;
						if (meme) {
							// Get touch position for context menu
							const touch = e.touches[0];
							this.showContextMenu(meme, touch.clientX, touch.clientY);
						}
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
		});
	}

	showContextMenu(meme, x, y) {
		this.currentContextMeme = meme;
		const contextMenu = document.getElementById('context-menu-modal');
		const deleteBtn = document.getElementById('context-delete');
		
		// Show/hide delete button based on permissions
		if (this.canDeleteMeme(meme)) {
			deleteBtn.style.display = 'flex';
		} else {
			deleteBtn.style.display = 'none';
		}
		
		contextMenu.classList.add('active');
	}

	hideContextMenu() {
		const contextMenu = document.getElementById('context-menu-modal');
		contextMenu.classList.remove('active');
		this.currentContextMeme = null;
	}

	async downloadMeme() {
		if (!this.currentContextMeme) return;
		
		try {
			const imageUrl = `/redis-image/meme/${this.currentContextMeme.id}`;
			const response = await fetch(imageUrl);
			const blob = await response.blob();
			
			const url = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `meme-${this.currentContextMeme.id}.jpg`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
			window.URL.revokeObjectURL(url);
			
			this.showSuccess('Meme downloaded successfully!');
		} catch (error) {
			console.error('Download error:', error);
			this.showError('Failed to download meme');
		}
		
		this.hideContextMenu();
	}

	async shareMeme() {
		if (!this.currentContextMeme) return;
		
		try {
			// Fetch the image file
			const imageUrl = `/redis-image/meme/${this.currentContextMeme.id}`;
			const response = await fetch(imageUrl);
			
			if (!response.ok) {
				throw new Error('Failed to fetch meme image');
			}
			
			const blob = await response.blob();
			const fileName = `climbing-meme-${this.currentContextMeme.id}.jpg`;
			const file = new File([blob], fileName, { type: blob.type });
			
			// Check if we can share files
			if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
				// Share the actual file
				try {
					await navigator.share({
						title: 'Climbing Meme',
						text: 'Check out this climbing meme!',
						files: [file]
					});
					this.showSuccess('Meme shared successfully!');
				} catch (error) {
					if (error.name !== 'AbortError') {
						console.error('File share error:', error);
						// Fallback to URL sharing
						this.fallbackUrlShare();
					}
				}
			} else if (navigator.share) {
				// Fallback to URL sharing if file sharing not supported
				this.fallbackUrlShare();
			} else {
				// No native sharing available, use clipboard fallback
				this.fallbackShare();
			}
		} catch (error) {
			console.error('Share error:', error);
			this.showError('Failed to prepare meme for sharing');
		}
		
		this.hideContextMenu();
	}

	fallbackUrlShare() {
		// Share URL instead of file when file sharing isn't supported
		const memeUrl = `${window.location.origin}/redis-image/meme/${this.currentContextMeme.id}`;
		const shareText = 'Check out this climbing meme!';
		
		if (navigator.share) {
			navigator.share({
				title: 'Climbing Meme',
				text: shareText,
				url: memeUrl
			}).then(() => {
				this.showSuccess('Meme link shared successfully!');
			}).catch((error) => {
				if (error.name !== 'AbortError') {
					console.error('URL share error:', error);
					this.fallbackShare();
				}
			});
		} else {
			this.fallbackShare();
		}
	}

	fallbackShare(url, text) {
		// If no URL provided, use the current meme URL
		if (!url && this.currentContextMeme) {
			url = `${window.location.origin}/redis-image/meme/${this.currentContextMeme.id}`;
			text = 'Check out this climbing meme!';
		}
		
		// Copy to clipboard
		if (navigator.clipboard && url) {
			navigator.clipboard.writeText(url).then(() => {
				this.showSuccess('Meme URL copied to clipboard!');
			}).catch(() => {
				this.showShareDialog(url, text);
			});
		} else if (url) {
			this.showShareDialog(url, text);
		} else {
			this.showError('Unable to share meme');
		}
	}

	showShareDialog(url, text) {
		// Create a simple share dialog
		const dialog = document.createElement('div');
		dialog.className = 'share-dialog-overlay';
		dialog.innerHTML = `
			<div class="share-dialog">
				<h3>Share Meme</h3>
				<p>Copy the link below to share this meme:</p>
				<input type="text" value="${url}" readonly style="width: 100%; padding: 0.5rem; margin: 1rem 0; background: #333; border: 1px solid #555; color: white; border-radius: 4px;">
				<div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
					<button onclick="this.parentElement.parentElement.parentElement.remove()" style="padding: 0.5rem 1rem; background: #666; border: none; color: white; border-radius: 4px; cursor: pointer;">Close</button>
					<button onclick="navigator.clipboard.writeText('${url}').then(() => { this.textContent = 'Copied!'; setTimeout(() => this.textContent = 'Copy Link', 1000); })" style="padding: 0.5rem 1rem; background: #bb86fc; border: none; color: white; border-radius: 4px; cursor: pointer;">Copy Link</button>
				</div>
			</div>
		`;
		
		// Add styles
		dialog.style.cssText = `
			position: fixed;
			top: 0;
			left: 0;
			right: 0;
			bottom: 0;
			background: rgba(0, 0, 0, 0.8);
			z-index: 2000;
			display: flex;
			align-items: center;
			justify-content: center;
		`;
		
		const dialogContent = dialog.querySelector('.share-dialog');
		dialogContent.style.cssText = `
			background: #1a1a1a;
			padding: 2rem;
			border-radius: 12px;
			border: 1px solid #333;
			max-width: 400px;
			width: 90%;
		`;
		
		document.body.appendChild(dialog);
		
		// Select the URL text
		const input = dialog.querySelector('input');
		input.select();
		input.focus();
	}

	confirmDeleteMeme() {
		if (!this.currentContextMeme) return;
		
		// Store the meme ID before hiding the context menu
		const memeId = this.currentContextMeme.id;
		this.hideContextMenu();
		this.showDeleteConfirmation(memeId);
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
		
		// Clear selected files array
		this.selectedFiles = [];
		
		// Clear file input
		const fileInput = document.getElementById('meme-image');
		if (fileInput) {
			fileInput.value = '';
		}
		
		// Clear image preview
		const preview = document.getElementById('image-preview');
		if (preview) {
			preview.innerHTML = '';
		}
		
		// Clear file count display
		const existingFileCount = document.querySelector('.file-count');
		if (existingFileCount) {
			existingFileCount.remove();
		}
		
		// Clear submission status
		const statusContainer = document.getElementById('submission-status');
		if (statusContainer) {
			statusContainer.innerHTML = '';
		}
		
		// Reset button state
		this.updateSubmitButton();
		
		// Reset button text
		const submitBtnText = document.getElementById('submit-btn-text');
		if (submitBtnText) {
			submitBtnText.textContent = 'Add Memes';
		}
	}

	handleImagePreview(event) {
		const files = Array.from(event.target.files);
		
		// Filter only image files
		const imageFiles = files.filter(file => file.type.startsWith('image/'));
		
		if (imageFiles.length !== files.length) {
			this.showError('Some files were not images and have been filtered out');
		}
		
		this.selectedFiles = imageFiles;
		this.updateImagePreview();
		this.updateSubmitButton();
	}

	updateImagePreview() {
		const preview = document.getElementById('image-preview');
		const submitBtn = document.getElementById('submit-meme-btn');
		const submitBtnText = document.getElementById('submit-btn-text');
		
		if (!preview) return;
		
		// Clear any existing file count
		const existingFileCount = preview.parentNode.querySelector('.file-count');
		if (existingFileCount) {
			existingFileCount.remove();
		}
		
		if (this.selectedFiles.length === 0) {
			preview.innerHTML = '';
			return;
		}

		// Update button text based on file count
		if (submitBtnText) {
			const fileCount = this.selectedFiles.length;
			submitBtnText.textContent = fileCount === 1 ? 'Add Meme' : `Add ${fileCount} Memes`;
		}

		// Add file count display ABOVE the images
		if (this.selectedFiles.length > 1) {
			preview.insertAdjacentHTML('beforebegin', `
				<div class="file-count">${this.selectedFiles.length} images selected</div>
			`);
		}

		preview.innerHTML = this.selectedFiles.map((file, index) => {
			const url = URL.createObjectURL(file);
			return `
				<div class="preview-image">
					<img src="${url}" alt="Preview ${index + 1}">
					<button type="button" class="preview-remove" onclick="window.memesManager.removePreviewImage(${index})" title="Remove image">×</button>
				</div>
			`;
		}).join('');
	}

	removePreviewImage(index) {
		// Revoke the URL to free memory
		const file = this.selectedFiles[index];
		if (file) {
			const url = URL.createObjectURL(file);
			URL.revokeObjectURL(url);
		}
		
		this.selectedFiles.splice(index, 1);
		this.updateImagePreview();
		this.updateSubmitButton();
		
		// Update the file input
		const fileInput = document.getElementById('meme-image');
		if (fileInput && this.selectedFiles.length === 0) {
			fileInput.value = '';
		}
	}

	updateSubmitButton() {
		const submitBtn = document.getElementById('submit-meme-btn');
		if (submitBtn) {
			submitBtn.disabled = this.selectedFiles.length === 0;
		}
	}

	async handleUpload(event) {
		event.preventDefault();
		
		if (this.selectedFiles.length === 0) {
			this.showError('Please select at least one image');
			return;
		}

		const submitBtn = document.getElementById('submit-meme-btn');
		const submitBtnText = document.getElementById('submit-btn-text');
		
		if (submitBtn) {
			submitBtn.disabled = true;
		}
		
		if (submitBtnText) {
			submitBtnText.textContent = 'Uploading...';
		}

		// Show upload progress
		this.showUploadProgress();

		try {
			let successCount = 0;
			let errorCount = 0;
			const errors = [];

			// Upload files one by one to show progress
			for (let i = 0; i < this.selectedFiles.length; i++) {
				const file = this.selectedFiles[i];
				this.updateUploadProgress(i, 'uploading', `Uploading ${file.name}...`);

				try {
					const formData = new FormData();
					formData.append('image', file);

					const response = await fetch('/api/memes/submit', {
						method: 'POST',
						body: formData
					});

					if (response.ok) {
						successCount++;
						this.updateUploadProgress(i, 'success', `${file.name} uploaded`);
					} else {
						const result = await response.json();
						errorCount++;
						errors.push(`${file.name}: ${result.detail || 'Unknown error'}`);
						this.updateUploadProgress(i, 'error', `Failed: ${file.name}`);
					}
				} catch (error) {
					console.error('Upload error:', error);
					errorCount++;
					errors.push(`${file.name}: Network error`);
					this.updateUploadProgress(i, 'error', `Failed: ${file.name}`);
				}
			}

			// Show final result
			setTimeout(() => {
				if (successCount > 0) {
					const message = successCount === 1 ? 
						'Meme uploaded successfully!' : 
						`${successCount} memes uploaded successfully!`;
					this.showSuccess(message);
					
					if (errorCount > 0) {
						this.showError(`${errorCount} uploads failed. Check console for details.`);
						console.error('Upload errors:', errors);
					}
					
					// Reset form completely before hiding modal
					this.resetUploadForm();
					this.hideUploadModal();
					this.loadMemes(); // Reload memes
				} else {
					this.showError('All uploads failed. Please try again.');
					console.error('All upload errors:', errors);
				}
			}, 1000);

		} catch (error) {
			console.error('Upload error:', error);
			this.showError('Failed to upload memes');
		} finally {
			// Reset button state
			setTimeout(() => {
				if (submitBtn) {
					submitBtn.disabled = false;
				}
				if (submitBtnText) {
					submitBtnText.textContent = this.selectedFiles.length === 1 ? 'Add Meme' : `Add ${this.selectedFiles.length} Memes`;
				}
			}, 2000);
		}
	}

	showUploadProgress() {
		const statusContainer = document.getElementById('submission-status');
		if (!statusContainer) return;

		const progressHtml = `
			<div class="upload-progress">
				${this.selectedFiles.map((file, index) => `
					<div class="upload-progress-item" id="progress-${index}">
						<span class="upload-progress-filename">${file.name}</span>
						<div class="upload-progress-bar">
							<div class="upload-progress-fill" style="width: 0%"></div>
						</div>
						<span class="upload-progress-status">Waiting...</span>
					</div>
				`).join('')}
			</div>
		`;

		statusContainer.innerHTML = progressHtml;
	}

	updateUploadProgress(index, status, message) {
		const progressItem = document.getElementById(`progress-${index}`);
		if (!progressItem) return;

		const progressBar = progressItem.querySelector('.upload-progress-fill');
		const statusSpan = progressItem.querySelector('.upload-progress-status');

		if (statusSpan) {
			statusSpan.textContent = message;
			// Clear previous status classes
			statusSpan.classList.remove('uploading', 'success', 'error');
			// Add current status class
			statusSpan.classList.add(status);
		}

		if (progressBar) {
			switch (status) {
				case 'uploading':
					progressBar.style.width = '50%';
					progressBar.style.background = 'linear-gradient(90deg, #ffae52, #ff6b35)';
					break;
				case 'success':
					progressBar.style.width = '100%';
					progressBar.style.background = 'linear-gradient(90deg, #03dac6, #018786)';
					break;
				case 'error':
					progressBar.style.width = '100%';
					progressBar.style.background = 'linear-gradient(90deg, #cf6679, #b71c1c)';
					break;
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
