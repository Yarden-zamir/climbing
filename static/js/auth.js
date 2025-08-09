/**
 * Authentication module for Google OAuth integration
 */

class AuthManager {
    constructor() {
        this.currentUser = null;
        this.isAuthenticated = false;
        // Eager initialize for instant header render
        this.loadCachedUser();
        this.setupEventListeners();
        this.updateUI();
        // Refresh in background
        this.refreshAuthStatus();
    }

    // Helper method to get profile picture URL
    getProfilePictureUrl(user) {
        if (!user || !user.id) return '/static/favicon/favicon-32x32.png';
        
        // If picture starts with /redis-image/ or /api/profile-picture/, use it as is
        if (user.picture && (
            user.picture.startsWith('/redis-image/') || 
            user.picture.startsWith('/api/profile-picture/')
        )) {
            return user.picture;
        }
        
        // Otherwise use our cached endpoint
        return `/api/profile-picture/${user.id}`;
    }

    async init() {
        // No-op: constructor performs eager init and background refresh
        return;
    }

    async checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/user');
            const data = await response.json();
            
            this.isAuthenticated = data.authenticated;
            this.currentUser = data.user;
            
            console.log('Auth status:', { authenticated: this.isAuthenticated, user: this.currentUser });
            this.saveCachedUser();
        } catch (error) {
            console.error('Error checking auth status:', error);
            this.isAuthenticated = false;
            this.currentUser = null;
            this.clearCachedUser();
        }
    }

    setupEventListeners() {
        // Login button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.login-btn, .google-login-btn')) {
                e.preventDefault();
                this.login();
            }
        });

        // Logout button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.logout-btn')) {
                e.preventDefault();
                this.logout();
            }
        });

        // Token management button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.manage-tokens-btn, .manage-tokens-btn *')) {
                e.preventDefault();
                this.showTokenManagement();
            }
        });

        // Profile dropdown toggle
        document.addEventListener('click', (e) => {
            if (e.target.matches('.user-profile-btn, .user-profile-btn *')) {
                e.preventDefault();
                this.toggleProfileDropdown();
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.user-profile-dropdown')) {
                this.closeProfileDropdown();
            }
        });

        // Clear preferences button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.clear-preferences-btn, .clear-preferences-btn *')) {
                e.preventDefault();
                this.clearUserPreferences();
            }
        });

        // Notification management button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.notification-management-btn, .notification-management-btn *')) {
                e.preventDefault();
                this.openNotificationManagement();
            }
        });

        // Install app button click
        document.addEventListener('click', (e) => {
            if (e.target.matches('.install-app-btn, .install-app-btn *')) {
                e.preventDefault();
                if (window.pwaManager) {
                    window.pwaManager.showInstallPrompt();
                }
            }
        });

        // Token modal event listeners
        document.addEventListener('click', (e) => {
            // Close token modal
            if (e.target.matches('.token-modal-close, .token-modal-overlay')) {
                this.closeTokenModal();
            }
            
            // Create new token button
            if (e.target.matches('.create-token-btn')) {
                this.showCreateTokenForm();
            }
            
            // Cancel create token
            if (e.target.matches('.cancel-create-token')) {
                this.hideCreateTokenForm();
            }
            
            // Submit create token
            if (e.target.matches('.submit-create-token')) {
                this.createToken();
            }
            
            // Revoke token
            if (e.target.matches('.revoke-token-btn')) {
                const tokenId = e.target.getAttribute('data-token-id');
                this.revokeToken(tokenId);
            }
            
            // Toggle permission badge
            if (e.target.matches('.permission-badge-toggleable:not(.disabled)')) {
                e.target.classList.toggle('selected');
            }
            
            // API documentation button
            if (e.target.matches('.api-docs-btn, .api-docs-btn *')) {
                e.preventDefault();
                window.open('/docs', '_blank');
            }
        });
    }

    login() {
        // Redirect to OAuth login endpoint
        window.location.href = '/auth/login';
    }

    logout() {
        // Redirect to logout endpoint
        window.location.href = '/auth/logout';
    }

    toggleProfileDropdown() {
        const dropdown = document.querySelector('.profile-dropdown-menu');
        const dropdownContainer = document.querySelector('.user-profile-dropdown');
        if (dropdown && dropdownContainer) {
            const isOpen = dropdown.classList.contains('show');
            if (isOpen) {
                dropdown.classList.remove('show');
                dropdownContainer.classList.remove('open');
            } else {
                dropdown.classList.add('show');
                dropdownContainer.classList.add('open');
            }
        }
    }

    closeProfileDropdown() {
        const dropdown = document.querySelector('.profile-dropdown-menu');
        const dropdownContainer = document.querySelector('.user-profile-dropdown');
        if (dropdown) {
            dropdown.classList.remove('show');
        }
        if (dropdownContainer) {
            dropdownContainer.classList.remove('open');
        }
    }

    updateUI() {
        // Update navigation
        this.updateNavigation();
        
        // Show/hide auth-specific content
        this.updateAuthContent();
        
        // Update any user info displays
        this.updateUserInfo();
        
        // Show pending approval notification if user is pending
        this.updatePendingNotification();
        
        // Update notifications UI
        this.updateNotificationsUI();
    }

    updateNavigation() {
        const nav = document.querySelector('nav');
        if (!nav) return;

        const existingDropdown = nav.querySelector('.user-profile-dropdown.auth-element');
        const existingLogin = nav.querySelector('.login-btn.auth-element');

        if (this.isAuthenticated && this.currentUser) {
            if (existingDropdown) {
                // Update in place to avoid jarring transition
                this.updateUserProfileDropdown(existingDropdown);
            } else {
                // Ensure login button is removed
                if (existingLogin) existingLogin.remove();
                // Create and append dropdown once
                const dropdown = this.createUserProfileDropdown();
                nav.appendChild(dropdown);
            }
        } else {
            // Not authenticated: ensure dropdown removed and login button present
            if (existingDropdown) existingDropdown.remove();
            if (!existingLogin) this.addLoginButton(nav);
        }
    }

    addLoginButton(nav) {
        const loginBtn = document.createElement('a');
        loginBtn.href = '/auth/login';
        loginBtn.className = 'login-btn auth-element';
        loginBtn.innerHTML = `
            <span style="display: flex; align-items: center; gap: 8px;">
                <svg class="google-icon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                </svg></span>
        `;
        nav.appendChild(loginBtn);
    }

    addUserProfileDropdown(nav) {
        const dropdown = this.createUserProfileDropdown();
        nav.appendChild(dropdown);
    }

    createUserProfileDropdown() {
        const userDropdown = document.createElement('div');
        userDropdown.className = 'user-profile-dropdown auth-element';
        userDropdown.innerHTML = this.buildUserProfileDropdownHTML();
        return userDropdown;
    }

    buildUserProfileDropdownHTML() {
        const firstName = (this.currentUser?.name || '').split(' ')[0] || '';
        const isAdmin = this.currentUser && (this.currentUser.role === 'admin' || (this.currentUser.permissions && this.currentUser.permissions.can_manage_users));
        const adminPanelLink = isAdmin ? `
            <a href="/admin" class="dropdown-item">
                <span>🛠️</span> Admin Panel
            </a>
            <hr class="dropdown-divider">
        ` : '';
        const pendingApprovalItem = this.currentUser && this.currentUser.role === 'pending' ? `
            <div class="dropdown-item pending-status-item">
                <span>⏳</span> Account Pending Approval
            </div>
            <hr class="dropdown-divider">
        ` : '';
        const installAppItem = (window.pwaManager && window.pwaManager.canInstall()) ? `
            <button class="install-app-btn dropdown-item">
                <span>📱</span> Install App
            </button>
            <hr class="dropdown-divider">
        ` : '';

        return `
            <button class="user-profile-btn">
                <img src="${this.getProfilePictureUrl(this.currentUser)}" 
                     alt="${this.currentUser?.name || ''}" 
                     class="user-avatar" loading="eager" decoding="async">
                <span class="user-name">${firstName}</span>
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="profile-dropdown-menu">
                <div class="profile-info">
                    <div class="profile-name">${this.currentUser?.name || ''}</div>
                    <div class="profile-email">${this.currentUser?.email || ''}</div>
                </div>
                <hr class="dropdown-divider">
                ${pendingApprovalItem}
                ${installAppItem}
                ${adminPanelLink}
                <button class="manage-tokens-btn dropdown-item">
                    <span>⚙️</span> Manage Tokens
                </button>
                <a href="https://photos.google.com/albums" target="_blank" class="dropdown-item">
                    <svg width="16" height="16" viewBox="0 0 176 192" style="flex-shrink: 0;">
                        <path fill="#F6B704" d="M45.6,49.8C69,49.8,88,68.8,88,92.2v3.9H7.1c-2.1,0-3.8-1.7-3.9-3.9C3.2,68.8,22.2,49.8,45.6,49.8z"/>
                        <path fill="#E54335" d="M134.2,53.6c0,23.4-19,42.4-42.4,42.4H88V15.1c0-2.1,1.7-3.9,3.8-3.9C115.3,11.2,134.2,30.2,134.2,53.6L134.2,53.6z"/>
                        <path fill="#4280EF" d="M130.4,142.3c-23.4,0-42.4-19-42.4-42.4V96h80.9c2.1,0,3.9,1.7,3.9,3.8C172.8,123.3,153.8,142.3,130.4,142.3z"/>
                        <path fill="#34A353" d="M41.8,138.4c0-23.4,19-42.4,42.4-42.4H88v80.9c0,2.1-1.7,3.8-3.9,3.9C60.7,180.8,41.8,161.8,41.8,138.4z"/>
                    </svg> Google Photos
                </a>
                <button class="notification-management-btn dropdown-item">
                    <span>🔔</span> Notification Settings
                </button>
                <hr class="dropdown-divider">
                <button class="clear-preferences-btn dropdown-item">
                    <span>🗑️</span> Clear Preferences
                </button>
                <hr class="dropdown-divider">
                <a href="/auth/logout" class="logout-btn dropdown-item">
                    <span>🚪</span> Logout
                </a>
            </div>
        `;
    }

    updateUserProfileDropdown(dropdownContainer) {
        try {
            // Update simple fields in place without rebuilding container
            const firstName = (this.currentUser?.name || '').split(' ')[0] || '';
            const avatar = dropdownContainer.querySelector('.user-avatar');
            const nameShort = dropdownContainer.querySelector('.user-name');
            const nameFull = dropdownContainer.querySelector('.profile-name');
            const email = dropdownContainer.querySelector('.profile-email');
            const newSrc = this.getProfilePictureUrl(this.currentUser);

            if (avatar && avatar.src !== newSrc) {
                avatar.src = newSrc;
            }
            if (nameShort && nameShort.textContent !== firstName) {
                nameShort.textContent = firstName;
            }
            if (nameFull && nameFull.textContent !== (this.currentUser?.name || '')) {
                nameFull.textContent = this.currentUser?.name || '';
            }
            if (email && email.textContent !== (this.currentUser?.email || '')) {
                email.textContent = this.currentUser?.email || '';
            }

            // Optionally refresh admin/pending/install section by replacing the menu content if role/install state changed significantly
            // Keep it minimal to avoid reflow/animations
        } catch (_) { /* noop */ }
    }

    updateAuthContent() {
        // Show/hide elements based on auth state
        const authOnlyElements = document.querySelectorAll('[data-auth-required="true"]');
        const noAuthElements = document.querySelectorAll('[data-auth-required="false"]');

        authOnlyElements.forEach(el => {
            el.style.display = this.isAuthenticated ? '' : 'none';
        });

        noAuthElements.forEach(el => {
            el.style.display = this.isAuthenticated ? 'none' : '';
        });
    }

    updateUserInfo() {
        // Update user info displays based on authentication status
        const userNameElements = document.querySelectorAll('[data-user-name]');
        const userEmailElements = document.querySelectorAll('[data-user-email]');
        const userAvatarElements = document.querySelectorAll('[data-user-avatar]');
        
        if (this.isAuthenticated && this.currentUser) {
            userNameElements.forEach(el => el.textContent = this.currentUser.name);
            userEmailElements.forEach(el => el.textContent = this.currentUser.email);
            userAvatarElements.forEach(el => el.src = this.getProfilePictureUrl(this.currentUser));
        } else {
            userNameElements.forEach(el => el.textContent = '');
            userEmailElements.forEach(el => el.textContent = '');
            userAvatarElements.forEach(el => el.src = '');
        }
    }

    updatePendingNotification() {
        // Remove existing pending notification
        const existingNotification = document.querySelector('.pending-approval-notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        if (this.isAuthenticated && this.currentUser) {
            const notificationKey = `pending_notification_shown_${this.currentUser.id}`;
            
            if (this.currentUser.role === 'pending') {
                // Show pending notification if user has pending status and hasn't seen it before
                const hasSeenNotification = localStorage.getItem(notificationKey);
                
                if (!hasSeenNotification) {
                    this.showPendingApprovalNotification();
                    // Mark as shown in localStorage
                    localStorage.setItem(notificationKey, 'true');
                }
            } else {
                // User is no longer pending, clear the notification flag so they can see it again if needed
                localStorage.removeItem(notificationKey);
            }
        }
    }

    showPendingApprovalNotification() {
        // Create notification banner
        const notification = document.createElement('div');
        notification.className = 'pending-approval-notification';
        notification.innerHTML = `
            <div class="pending-notification-content">
                <div class="pending-notification-icon">⏳</div>
                <div class="pending-notification-text">
                    <h3>Account Pending Approval</h3>
                    <p>Your account is currently under review. An administrator will approve your access soon. You can browse the site but cannot create or edit content yet.</p>
                </div>
                <div class="pending-notification-status">
                    <span class="status-badge">PENDING</span>
                </div>
            </div>
        `;

        // Insert at the top of the body
        document.body.insertBefore(notification, document.body.firstChild);

        // Auto-hide after 8 seconds (but user can dismiss manually)
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.add('fade-out');
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.remove();
                    }
                }, 500);
            }
        }, 8000);

        // Add click to dismiss
        notification.addEventListener('click', () => {
            notification.classList.add('fade-out');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, 500);
        });
    }

    // Utility method to check if user is authenticated
    isUserAuthenticated() {
        return this.isAuthenticated;
    }

    // Get current user data
    getCurrentUser() {
        return this.currentUser;
    }

    // Cache helpers for fast initial paint
    loadCachedUser() {
        try {
            const raw = localStorage.getItem('auth_user_cache_v1');
            if (!raw) return;
            const parsed = JSON.parse(raw);
            const ts = typeof parsed.ts === 'number' ? parsed.ts : 0;
            // Fresh for 10 minutes
            if (Date.now() - ts < 10 * 60 * 1000) {
                this.isAuthenticated = !!parsed.authenticated && !!parsed.user;
                this.currentUser = parsed.user || null;
            }
        } catch (_) {}
    }

    saveCachedUser() {
        try {
            if (this.isAuthenticated && this.currentUser) {
                const snapshot = {
                    authenticated: true,
                    user: {
                        id: this.currentUser.id,
                        email: this.currentUser.email,
                        name: this.currentUser.name,
                        picture: this.currentUser.picture,
                        role: this.currentUser.role,
                        permissions: this.currentUser.permissions || {}
                    },
                    ts: Date.now()
                };
                localStorage.setItem('auth_user_cache_v1', JSON.stringify(snapshot));
            } else {
                this.clearCachedUser();
            }
        } catch (_) {}
    }

    clearCachedUser() {
        try { localStorage.removeItem('auth_user_cache_v1'); } catch (_) {}
    }

    // Method to refresh auth status (useful after login/logout)
    async refreshAuthStatus() {
        await this.checkAuthStatus();
        this.updateUI();
    }

    // Notification management methods
    updateNotificationsUI() {
        const icon = document.getElementById('notifications-icon');
        const text = document.getElementById('notifications-text');
        
        if (!icon || !text) return;
        
        // Check if notifications manager is available
        if (window.notificationsManager) {
            const isEnabled = window.notificationsManager.enabled;
            const isSupported = window.notificationsManager.supported;
            
            if (!isSupported) {
                icon.textContent = '🚫';
                text.textContent = 'Notifications Not Supported';
                document.querySelector('.notifications-toggle-btn').disabled = true;
            } else if (isEnabled) {
                icon.textContent = '🔔';
                text.textContent = 'Disable Notifications';
            } else {
                icon.textContent = '🔕';
                text.textContent = 'Enable Notifications';
            }
        } else {
            icon.textContent = '⏳';
            text.textContent = 'Loading Notifications...';
        }
    }

    async openNotificationManagement() {
        try {
            // Get user's devices and their notification preferences
            const response = await fetch('/api/notifications/devices', {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch devices: ${response.status}`);
            }

            const devicesData = await response.json();
            this.showNotificationManagementModal(devicesData.devices || []);

        } catch (error) {
            console.error('Error opening notification management:', error);
            this.showNotification('Failed to load notification settings', 'error');
        }
    }

    showNotificationManagementModal(devices) {
        // Determine if current device is already subscribed
        const currentDeviceId = notificationsManager.deviceId;
        const currentDevice = devices.find(d => d.full_device_id === currentDeviceId);
        const deviceName = notificationsManager.getDeviceInfo().browserName;
        let enableButtonHtml = '';
        if (!currentDevice) {
            enableButtonHtml = `
                <div class="enable-notifications-banner">
                    <p>Subscribe to notifications on this device <strong>(${deviceName})</strong>:</p>
                    <button class="enable-notifications-btn">🔔 Enable Notifications</button>
                </div>
            `;
        }
        // Create modal HTML
        const modalHTML = `
            <div class="notification-management-modal-overlay">
                <div class="notification-management-modal">
                    <div class="modal-header">
                        <h2>Notification Settings</h2>
                        <button class="close-btn" onclick="authManager.closeNotificationManagement()">&times;</button>
                    </div>
                    <div class="modal-content">
                        ${enableButtonHtml}
                        <p class="modal-description">
                            Manage notification preferences for each of your devices. You can enable or disable specific types of notifications per device.
                        </p>
                        <div class="devices-table-container">
                            ${this.renderDevicesTable(devices)}
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Add modal to DOM
        document.body.insertAdjacentHTML('beforeend', modalHTML);

        // Add event listeners for preference toggles
        this.setupNotificationPreferenceListeners();

        // Enable notifications button event
        const enableBtn = document.querySelector('.enable-notifications-btn');
        if (enableBtn) {
            enableBtn.addEventListener('click', async () => {
                await notificationsManager.enableNotifications();
                this.closeNotificationManagement();
                // Optionally, re-open the modal to refresh the device list
                setTimeout(() => this.openNotificationManagement(), 500);
            });
        }

        // Close on overlay click
        document.querySelector('.notification-management-modal-overlay').addEventListener('click', (e) => {
            if (e.target.classList.contains('notification-management-modal-overlay')) {
                this.closeNotificationManagement();
            }
        });
    }

    renderDevicesTable(devices) {
        if (!devices || devices.length === 0) {
            return `
                <div class="no-devices">
                    <p>🔔 No notification devices found</p>
                    <p>Enable notifications on a device to manage preferences here.</p>
                </div>
            `;
        }

        const notificationTypes = [
            { key: 'album_created', label: 'New Albums', icon: '📸' },
            { key: 'crew_member_added', label: 'New Crew Members', icon: '👥' },
            { key: 'meme_uploaded', label: 'New Memes', icon: '😂' },
            { key: 'system_announcements', label: 'System Updates', icon: '📢' }
        ];

        return `
            <table class="devices-table">
                <thead>
                    <tr>
                        <th>Device</th>
                        ${notificationTypes.map(type => `<th>${type.icon}<br>${type.label}</th>`).join('')}
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${devices.map(device => `
                        <tr data-device-id="${device.full_device_id}">
                            <td class="device-info">
                                <div class="device-name">
                                    <strong>${device.browser_name}</strong>
                                    <small>${device.platform}</small>
                                </div>
                                <div class="device-details">
                                    <small>Added: ${new Date(device.created_at).toLocaleDateString()}</small>
                                    <br>
                                    <small>Last used: ${device.last_used ? new Date(device.last_used).toLocaleDateString() : 'Never'}</small>
                                </div>
                            </td>
                            ${notificationTypes.map(type => `
                                <td class="checkbox-cell">
                                    <label class="switch">
                                        <input type="checkbox" 
                                               data-device-id="${device.full_device_id}"
                                               data-notification-type="${type.key}"
                                               ${device.notification_preferences[type.key] ? 'checked' : ''}>
                                        <span class="slider"></span>
                                    </label>
                                </td>
                            `).join('')}
                            <td class="actions-cell">
                                <button class="remove-device-btn" data-device-id="${device.full_device_id}">
                                    🗑️ Remove
                                </button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    setupNotificationPreferenceListeners() {
        // Handle preference toggle changes
        document.querySelectorAll('.devices-table input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', async (e) => {
                const deviceId = e.target.dataset.deviceId;
                const notificationType = e.target.dataset.notificationType;
                const isEnabled = e.target.checked;

                await this.updateNotificationPreference(deviceId, notificationType, isEnabled);
            });
        });

        // Handle device removal
        document.querySelectorAll('.remove-device-btn').forEach(button => {
            button.addEventListener('click', async (e) => {
                const deviceId = e.target.dataset.deviceId;
                await this.removeDevice(deviceId);
            });
        });
    }

    async updateNotificationPreference(deviceId, notificationType, isEnabled) {
        try {
            // Get current preferences for this device
            const response = await fetch(`/api/notifications/devices/${deviceId}/preferences`, {
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch preferences: ${response.status}`);
            }

            const data = await response.json();
            const preferences = data.preferences;

            // Update the specific preference
            preferences[notificationType] = isEnabled;

            // Send updated preferences to server
            const updateResponse = await fetch(`/api/notifications/devices/${deviceId}/preferences`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify(preferences)
            });

            if (!updateResponse.ok) {
                throw new Error(`Failed to update preferences: ${updateResponse.status}`);
            }

            console.log(`✅ Updated ${notificationType} preference for device ${deviceId.substring(0, 15)}...`);

        } catch (error) {
            console.error('Error updating notification preference:', error);
            this.showNotification('Failed to update notification preference', 'error');
            
            // Revert checkbox state on error
            const checkbox = document.querySelector(`input[data-device-id="${deviceId}"][data-notification-type="${notificationType}"]`);
            if (checkbox) {
                checkbox.checked = !isEnabled;
            }
        }
    }

    async removeDevice(deviceId) {
        if (!confirm('Are you sure you want to remove this device from notifications?')) {
            return;
        }

        try {
            const response = await fetch(`/api/notifications/devices/${deviceId}`, {
                method: 'DELETE',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error(`Failed to remove device: ${response.status}`);
            }

            // Remove the row from the table
            const row = document.querySelector(`tr[data-device-id="${deviceId}"]`);
            if (row) {
                row.remove();
            }

            this.showNotification('Device removed successfully', 'success');
            console.log(`✅ Removed device ${deviceId.substring(0, 15)}...`);

        } catch (error) {
            console.error('Error removing device:', error);
            this.showNotification('Failed to remove device', 'error');
        }
    }

    closeNotificationManagement() {
        const modal = document.querySelector('.notification-management-modal-overlay');
        if (modal) {
            modal.remove();
        }
    }

    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;

        // Add to DOM
        document.body.appendChild(notification);

        // Remove after 3 seconds
        setTimeout(() => {
            notification.classList.add('fade-out');
            setTimeout(() => notification.remove(), 3000);
        }, 3000);
    }

    async toggleNotifications() {
        if (!this.isAuthenticated) {
            alert('Please log in to enable notifications');
            return;
        }

        if (!window.notificationsManager) {
            alert('Notification manager not available. Please refresh the page.');
            return;
        }

        if (!window.notificationsManager.supported) {
            alert('Push notifications are not supported in this browser');
            return;
        }

        this.closeProfileDropdown();

        try {
            const isCurrentlyEnabled = window.notificationsManager.enabled;
            
            if (isCurrentlyEnabled) {
                // Disable notifications
                const confirmed = confirm('Are you sure you want to disable notifications? You won\'t receive alerts for new albums, crew members, or memes.');
                if (!confirmed) return;
                
                await window.notificationsManager.disableNotifications();
                alert('Notifications disabled successfully');
                
            } else {
                // Enable notifications
                await window.notificationsManager.enableNotifications();
                alert('Notifications enabled successfully! You\'ll now receive alerts for new content.');
                
                // Send a test notification after a short delay
                setTimeout(async () => {
                    try {
                        await window.notificationsManager.sendTestNotification();
                    } catch (error) {
                        console.log('Test notification failed:', error);
                    }
                }, 1000);
            }
            
            // Update UI
            this.updateNotificationsUI();
            
        } catch (error) {
            console.error('Error toggling notifications:', error);
            
            if (error.message.includes('denied')) {
                alert('Notification permission was denied. Please enable notifications in your browser settings and try again.');
            } else if (error.message.includes('dismissed')) {
                alert('Notification permission was dismissed. Please try again and allow notifications.');
            } else {
                alert('Failed to toggle notifications: ' + error.message);
            }
        }
    }

    // Method to clear all user preferences
    async clearUserPreferences() {
        if (!this.isAuthenticated || !this.currentUser) {
            console.log('Cannot clear preferences: user not authenticated');
            return;
        }

        const confirmed = confirm('Are you sure you want to clear all your saved preferences? This cannot be undone.');
        if (!confirmed) return;

        try {
            console.log('Clearing user preferences...');
            
            // Get all current preferences
            const response = await fetch('/api/user/preferences', {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                const preferences = data.preferences || {};
                
                // Delete each preference
                const deletePromises = Object.keys(preferences).map(async (key) => {
                    const deleteResponse = await fetch(`/api/user/preferences/${key}`, {
                        method: 'DELETE',
                        credentials: 'include'
                    });
                    
                    if (!deleteResponse.ok) {
                        console.error(`Failed to delete preference: ${key}`);
                    }
                    return { key, success: deleteResponse.ok };
                });

                const results = await Promise.all(deletePromises);
                const successCount = results.filter(r => r.success).length;
                
                if (successCount > 0) {
                    alert(`Successfully cleared ${successCount} preference(s). The page will reload to apply changes.`);
                    // Reload the page to reset any UI state
                    window.location.reload();
                } else {
                    alert('No preferences found to clear.');
                }
            } else {
                throw new Error('Failed to fetch preferences');
            }
        } catch (error) {
            console.error('Error clearing preferences:', error);
            alert('Failed to clear preferences. Please try again.');
        } finally {
            this.closeProfileDropdown();
        }
    }

    // Token Management Methods
    async showTokenManagement() {
        this.closeProfileDropdown();
        
        try {
            // Fetch user's tokens and available permissions
            const [tokensResponse, permissionsResponse] = await Promise.all([
                fetch('/api/auth/tokens'),
                fetch('/api/auth/permissions')
            ]);
            
            const tokens = await tokensResponse.json();
            const permissionsData = await permissionsResponse.json();
            
            this.displayTokenModal(tokens, permissionsData);
        } catch (error) {
            console.error('Error loading token management:', error);
            alert('Failed to load token management. Please try again.');
        }
    }

    displayTokenModal(tokens, permissionsData) {
        // Remove existing modal
        const existingModal = document.querySelector('.token-management-modal');
        if (existingModal) {
            existingModal.remove();
        }

        const modal = document.createElement('div');
        modal.className = 'token-management-modal';
        modal.innerHTML = `
            <div class="token-modal-overlay"></div>
            <div class="token-modal-content">
                <div class="token-modal-header">
                    <h2>API Token Management</h2>
                    <button class="token-modal-close">&times;</button>
                </div>
                
                <div class="token-modal-body">
                    <div class="token-section">
                        <div class="token-section-header">
                            <h3>Your API Tokens</h3>
                            <div style="display: flex; gap: 8px;">
                                <button class="api-docs-btn" type="button">
                                    <span>📚</span> API Docs
                                </button>
                                <button class="create-token-btn">Create New Token</button>
                            </div>
                        </div>
                        
                        <div class="tokens-list">
                            ${this.renderTokensList(tokens)}
                        </div>
                    </div>
                    
                    <div class="create-token-section" style="display: none;">
                        ${this.renderCreateTokenForm(permissionsData)}
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        
        // Add styles if not already present
        this.addTokenModalStyles();
    }

    renderTokensList(tokens) {
        if (!tokens || tokens.length === 0) {
            return `
                <div class="no-tokens">
                    <p>You don't have any API tokens yet.</p>
                    <p>Create one to start using the API!</p>
                </div>
            `;
        }

        return tokens.map(token => {
            const createdDate = new Date(token.created_at).toLocaleDateString();
            const expiresDate = new Date(token.expires_at).toLocaleDateString();
            const lastUsed = token.last_used 
                ? new Date(token.last_used).toLocaleDateString()
                : 'Never';
            
            const permissionsList = Object.entries(token.permissions || {})
                .filter(([_, enabled]) => enabled)
                .map(([perm, _]) => perm.replace('can_', '').replace(/_/g, ' '))
                .join(', ');

            // Check if token is expiring soon (within 24 hours)
            const now = new Date();
            const expiryTime = new Date(token.expires_at);
            const hoursUntilExpiry = (expiryTime - now) / (1000 * 60 * 60);
            const isExpiringSoon = hoursUntilExpiry > 0 && hoursUntilExpiry <= 24;
            const isExpired = hoursUntilExpiry <= 0;

            let expiryStatus = '';
            if (isExpired) {
                expiryStatus = '<span style="color: #cf6679; font-weight: 600;">⚠️ EXPIRED</span>';
            } else if (isExpiringSoon) {
                expiryStatus = '<span style="color: #ff7a3d; font-weight: 600;">⏰ Expires soon</span>';
            }

            return `
                <div class="token-item ${isExpired ? 'token-expired' : ''}">
                    <div class="token-info">
                        <div class="token-name">
                            ${token.name}
                            ${expiryStatus}
                        </div>
                        <div class="token-details">
                            <span>Created: ${createdDate}</span>
                            <span>Expires: ${expiresDate}</span>
                            <span>Last used: ${lastUsed}</span>
                        </div>
                        <div class="token-permissions">
                            Permissions: ${permissionsList || 'None'}
                        </div>
                    </div>
                    <button class="revoke-token-btn" data-token-id="${token.id}">
                        Revoke
                    </button>
                </div>
            `;
        }).join('');
    }

    renderCreateTokenForm(permissionsData) {
        const { permissions, descriptions } = permissionsData;
        
        const permissionBadges = Object.entries(permissions)
            .map(([key, userHasPermission]) => {
                const description = descriptions[key] || key;
                const disabled = !userHasPermission ? 'disabled' : '';
                const selected = userHasPermission ? 'selected' : '';
                
                return `
                    <div class="permission-badge-toggleable ${disabled} ${selected}" 
                         data-permission="${key}"
                         title="${!userHasPermission ? 'Not available - you don\'t have this permission' : 'Click to toggle'}">
                        ${description}
                        ${!userHasPermission ? ' 🚫' : ''}
                    </div>
                `;
            }).join('');

        // Generate expiry options
        const expiryOptions = [
            { hours: 1, label: '1 Hour' },
            { hours: 6, label: '6 Hours' },
            { hours: 12, label: '12 Hours' },
            { hours: 24, label: '1 Day (Default)' },
            { hours: 48, label: '2 Days' },
            { hours: 168, label: '1 Week' },
            { hours: 720, label: '1 Month' },
            { hours: 2160, label: '3 Months' },
            { hours: 4320, label: '6 Months' },
            { hours: 8760, label: '1 Year (Maximum)' }
        ].map(option => 
            `<option value="${option.hours}" ${option.hours === 24 ? 'selected' : ''}>${option.label}</option>`
        ).join('');

        return `
            <div class="create-token-form">
                <h3>Create New API Token</h3>
                
                <div class="form-group">
                    <label for="token-name">Token Name</label>
                    <input type="text" 
                           id="token-name" 
                           placeholder="My App Token" 
                           maxlength="50">
                </div>
                
                <div class="form-group">
                    <label for="token-expiry">Token Expiry</label>
                    <select id="token-expiry" class="form-select">
                        ${expiryOptions}
                    </select>
                    <p style="color: #888; font-size: 0.85rem; margin-top: 6px;">
                        ⏰ Choose how long this token should remain valid. After expiry, you'll need to create a new token.
                    </p>
                </div>
                
                <div class="form-group">
                    <label>Select Permissions</label>
                    <p style="color: #888; font-size: 0.85rem; margin-bottom: 12px;">
                        Choose which permissions this token should have. You can only select permissions you currently possess.
                    </p>
                    <div class="permissions-list">
                        ${permissionBadges}
                    </div>
                </div>
                
                <div class="form-actions">
                    <button class="api-docs-btn" type="button">
                        <span>📚</span> API Documentation
                    </button>
                    <div style="flex: 1;"></div>
                    <button class="cancel-create-token">Cancel</button>
                    <button class="submit-create-token">Create Token</button>
                </div>
            </div>
        `;
    }

    showCreateTokenForm() {
        const section = document.querySelector('.create-token-section');
        if (section) {
            section.style.display = 'block';
        }
    }

    hideCreateTokenForm() {
        const section = document.querySelector('.create-token-section');
        if (section) {
            section.style.display = 'none';
        }
    }

    async createToken() {
        const tokenName = document.getElementById('token-name').value.trim();
        if (!tokenName) {
            alert('Please enter a token name');
            return;
        }

        // Get selected expiry hours
        const expiryHours = parseInt(document.getElementById('token-expiry').value);
        if (!expiryHours || expiryHours < 1 || expiryHours > 8760) {
            alert('Please select a valid expiry time');
            return;
        }

        // Get selected permissions from badges
        const allPermissionBadges = document.querySelectorAll('.create-token-form .permission-badge-toggleable');
        const permissions = {};
        
        // Process each permission badge
        allPermissionBadges.forEach(badge => {
            const permission = badge.getAttribute('data-permission');
            const isSelected = badge.classList.contains('selected') && !badge.classList.contains('disabled');
            permissions[permission] = isSelected;
        });

        try {
            const response = await fetch('/api/auth/token/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    token_name: tokenName,
                    permissions: permissions,
                    expires_in_hours: expiryHours
                })
            });

            if (response.ok) {
                const tokenData = await response.json();
                this.showTokenCreatedDialog(tokenData);
                // Refresh the token list
                this.showTokenManagement();
            } else {
                const error = await response.json();
                alert(`Failed to create token: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error creating token:', error);
            alert('Failed to create token. Please try again.');
        }
    }

    showTokenCreatedDialog(tokenData) {
        const baseUrl = window.location.origin;
        const exportStatement = `export CLIMBING_API_TOKEN="${tokenData.access_token}"`;
        const curlExampleWithEnv = `curl -H "Authorization: Bearer $CLIMBING_API_TOKEN" "${baseUrl}/api/crew?pretty=true"`;
        const curlExampleRaw = `curl -H "Authorization: Bearer ${tokenData.access_token}" "${baseUrl}/api/crew?pretty=true"`;

        // Format expiry date for display
        const expiryDate = new Date(tokenData.expires_at);
        const expiryString = expiryDate.toLocaleString();

        // Create dialog
        const dialog = document.createElement('div');
        dialog.className = 'token-created-dialog';
        
        // Create content with proper event handling
        const dialogContent = document.createElement('div');
        dialogContent.className = 'token-dialog-content';
        dialogContent.innerHTML = `
            <h3>🎉 API Token Created Successfully!</h3>
            <p style="color: #cf6679; font-weight: 600; margin-bottom: 20px;">
                <strong>⚠️ Important:</strong> Copy this token now. You won't be able to see it again!
            </p>
            
            <div class="token-display">
                <label>🔑 API Token:</label>
                <textarea readonly onclick="this.select()">${tokenData.access_token}</textarea>
                <div class="token-buttons">
                    <button class="copy-token-btn">📋 Copy Token</button>
                    <button class="download-token-btn">💾 Download Token</button>
                </div>
            </div>
            
            <div class="token-display">
                <label>🌍 Environment Variable:</label>
                <textarea readonly onclick="this.select()">${exportStatement}</textarea>
                <div class="token-buttons">
                    <button class="copy-export-btn">📋 Copy Export</button>
                </div>
            </div>
            
            <div class="token-display">
                <label>🛠️ Example Usage </label>
                <textarea readonly onclick="this.select()" style="height: 80px; font-size: 11px;">${curlExampleWithEnv}</textarea>
                <div class="token-buttons">
                    <button class="copy-env-example-btn">📋 Copy (Env)</button>
                    <button class="copy-raw-example-btn">📋 Copy (Raw)</button>
                </div>
            </div>
            
            <p class="token-expiry">⏰ Token expires on ${expiryString} (${Math.floor(tokenData.expires_in / 3600)} hours from now)</p>
            
            <div style="display: flex; gap: 12px; justify-content: center; margin-top: 24px;">
                <button class="api-docs-btn" style="background: linear-gradient(135deg, #03dac6 0%, #018786 100%); color: #121212; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-weight: 600;">
                    📚 API Documentation
                </button>
                <button class="close-dialog-btn" style="background: linear-gradient(135deg, #444 0%, #666 100%); color: #e0e0e0; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-weight: 600;">
                    ✅ Close
                </button>
            </div>
        `;

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'token-dialog-overlay';
        
        // Assemble dialog
        dialog.appendChild(overlay);
        dialog.appendChild(dialogContent);
        document.body.appendChild(dialog);

        // Add event listeners
        dialogContent.querySelector('.copy-token-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(tokenData.access_token);
            this.showCopyFeedback(dialogContent.querySelector('.copy-token-btn'));
        });

        dialogContent.querySelector('.download-token-btn').addEventListener('click', () => {
            this.downloadToken(tokenData.access_token);
        });

        dialogContent.querySelector('.copy-export-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(exportStatement);
            this.showCopyFeedback(dialogContent.querySelector('.copy-export-btn'));
        });

        dialogContent.querySelector('.copy-env-example-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(curlExampleWithEnv);
            this.showCopyFeedback(dialogContent.querySelector('.copy-env-example-btn'));
        });

        dialogContent.querySelector('.copy-raw-example-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(curlExampleRaw);
            this.showCopyFeedback(dialogContent.querySelector('.copy-raw-example-btn'));
        });

        dialogContent.querySelector('.api-docs-btn').addEventListener('click', () => {
            window.open('/docs', '_blank');
        });

        dialogContent.querySelector('.close-dialog-btn').addEventListener('click', () => {
            dialog.remove();
        });

        overlay.addEventListener('click', () => {
            dialog.remove();
        });
    }

    // Add visual feedback for copy operations
    showCopyFeedback(button) {
        const originalText = button.textContent;
        button.textContent = '✅ Copied!';
        button.style.background = 'linear-gradient(135deg, #4caf50 0%, #388e3c 100%)';
        
        setTimeout(() => {
            button.textContent = originalText;
            button.style.background = '';
        }, 2000);
    }

    // Helper function to download token as a file
    downloadToken(token) {
        const blob = new Blob([token], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'climbing_api_token.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }

    async revokeToken(tokenId) {
        if (!confirm('Are you sure you want to revoke this token? This action cannot be undone.')) {
            return;
        }

        try {
            const response = await fetch(`/api/auth/tokens/${tokenId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                // Refresh the token list
                this.showTokenManagement();
            } else {
                const error = await response.json();
                alert(`Failed to revoke token: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error revoking token:', error);
            alert('Failed to revoke token. Please try again.');
        }
    }

    closeTokenModal() {
        const modal = document.querySelector('.token-management-modal');
        if (modal) {
            modal.remove();
        }
        
        const dialog = document.querySelector('.token-created-dialog');
        if (dialog) {
            dialog.remove();
        }
    }

    addTokenModalStyles() {
        if (document.getElementById('token-modal-styles')) {
            return; // Styles already added
        }

        const styles = document.createElement('style');
        styles.id = 'token-modal-styles';
        styles.textContent = `
            .token-management-modal {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 10000;
                font-family: "Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                opacity: 0;
                animation: modal-fade-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            @keyframes modal-fade-in {
                from {
                    opacity: 0;
                }
                to {
                    opacity: 1;
                }
            }

            @keyframes modal-fade-out {
                from {
                    opacity: 1;
                }
                to {
                    opacity: 0;
                }
            }

            .token-modal-overlay {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.75);
                backdrop-filter: blur(8px);
            }

            .token-modal-content {
                position: relative;
                max-width: 800px;
                max-height: 90vh;
                margin: 5vh auto;
                background: linear-gradient(135deg, #1e1e1e 0%, #2d2d2d 100%);
                border-radius: 12px;
                overflow-y: auto;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
                border: 1px solid #333;
                color: #e0e0e0;
                transform: translateY(20px);
                animation: modal-slide-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            @keyframes modal-slide-in {
                from {
                    transform: translateY(20px);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }

            .token-modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 24px;
                border-bottom: 1px solid #333;
                background: linear-gradient(135deg, #232323 0%, #1a1a1a 100%);
                border-radius: 12px 12px 0 0;
            }

            .token-modal-header h2 {
                margin: 0;
                color: #bb86fc;
                font-size: 1.4rem;
                font-weight: 700;
            }

            .token-modal-close {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                padding: 8px;
                width: 40px;
                height: 40px;
                border-radius: 8px;
                color: #a0a0a0;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .token-modal-close:hover {
                background: rgba(187, 134, 252, 0.2);
                color: #bb86fc;
                transform: scale(1.1);
            }

            .token-modal-body {
                padding: 24px;
            }

            .token-section-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
            }

            .token-section-header h3 {
                margin: 0;
                color: #03dac6;
                font-size: 1.2rem;
                font-weight: 600;
            }

            .create-token-btn {
                background: linear-gradient(135deg, #bb86fc 0%, #6200ea 100%);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 4px 15px rgba(187, 134, 252, 0.3);
                position: relative;
                overflow: hidden;
            }

            .create-token-btn::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
                transition: left 0.5s;
            }

            .create-token-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(187, 134, 252, 0.4);
                background: linear-gradient(135deg, #cf6679 0%, #bb86fc 100%);
            }

            .create-token-btn:hover::before {
                left: 100%;
            }

            .token-item {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                padding: 20px;
                border: 1px solid #333;
                border-radius: 8px;
                margin-bottom: 12px;
                background: linear-gradient(135deg, #232323 0%, #1a1a1a 100%);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }

            .token-item:hover {
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
                border-color: rgba(187, 134, 252, 0.3);
            }

            .token-item.token-expired {
                opacity: 0.7;
                border-color: #cf6679;
                background: linear-gradient(135deg, #2d1b1e 0%, #1a1a1a 100%);
            }

            .token-item.token-expired:hover {
                border-color: #cf6679;
                box-shadow: 0 6px 20px rgba(207, 102, 121, 0.2);
            }

            .token-info {
                flex: 1;
            }

            .token-name {
                font-weight: 700;
                margin-bottom: 8px;
                color: #bb86fc;
                font-size: 1.1rem;
            }

            .token-details {
                font-size: 0.9rem;
                color: #a0a0a0;
                margin-bottom: 8px;
                line-height: 1.4;
            }

            .token-details span {
                margin-right: 16px;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }

            .token-permissions {
                font-size: 0.85rem;
                color: #03dac6;
                font-weight: 500;
            }

            .revoke-token-btn {
                background: linear-gradient(135deg, #cf6679 0%, #b00020 100%);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 2px 8px rgba(207, 102, 121, 0.3);
            }

            .revoke-token-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(207, 102, 121, 0.4);
                background: linear-gradient(135deg, #e91e63 0%, #c62828 100%);
            }

            .no-tokens {
                text-align: center;
                padding: 60px 20px;
                color: #888;
                font-style: italic;
                font-size: 1.1rem;
            }

            .create-token-form {
                border-top: 1px solid #333;
                padding-top: 24px;
                margin-top: 24px;
                background: linear-gradient(135deg, #1a1a1a 0%, #232323 100%);
                border-radius: 12px;
                padding: 24px;
                margin: 24px -24px -24px -24px;
            }

            .form-group {
                margin-bottom: 20px;
            }

            .form-group label {
                display: block;
                margin-bottom: 8px;
                font-weight: 600;
                color: #03dac6;
                font-size: 0.95rem;
            }

            .form-group input[type="text"] {
                width: 100%;
                padding: 12px;
                border: 1px solid #444;
                border-radius: 8px;
                background: #2a2a2a;
                color: #e0e0e0;
                font-size: 1rem;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-sizing: border-box;
            }

            .form-group input[type="text"]:focus {
                outline: none;
                border-color: #bb86fc;
                box-shadow: 0 0 0 2px rgba(187, 134, 252, 0.2);
                background: #333;
            }

            .form-select {
                width: 100%;
                padding: 12px;
                border: 1px solid #444;
                border-radius: 8px;
                background: #2a2a2a;
                color: #e0e0e0;
                font-size: 1rem;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-sizing: border-box;
                cursor: pointer;
            }

            .form-select:focus {
                outline: none;
                border-color: #bb86fc;
                box-shadow: 0 0 0 2px rgba(187, 134, 252, 0.2);
                background: #333;
            }

            .form-select option {
                background: #2a2a2a;
                color: #e0e0e0;
                padding: 8px;
            }

            .permissions-list {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                padding: 16px;
                border: 1px solid #444;
                border-radius: 8px;
                max-height: 200px;
                overflow-y: auto;
                background: #2a2a2a;
            }

            .permission-badge-toggleable {
                display: inline-block;
                background: #444;
                color: #e0e0e0;
                border: 2px solid #555;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 0.9rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                user-select: none;
                position: relative;
                overflow: hidden;
            }

            .permission-badge-toggleable::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
                transition: left 0.5s;
            }

            .permission-badge-toggleable:hover {
                background: #555;
                border-color: #bb86fc;
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(187, 134, 252, 0.2);
            }

            .permission-badge-toggleable:hover::before {
                left: 100%;
            }

            .permission-badge-toggleable.selected {
                background: linear-gradient(135deg, #bb86fc 0%, #6200ea 100%);
                color: #fff;
                border-color: #bb86fc;
                font-weight: 700;
                box-shadow: 0 4px 15px rgba(187, 134, 252, 0.3);
            }

            .permission-badge-toggleable.selected:hover {
                background: linear-gradient(135deg, #cf6679 0%, #bb86fc 100%);
                transform: translateY(-2px);
                box-shadow: 0 6px 20px rgba(187, 134, 252, 0.4);
            }

            .permission-badge-toggleable.disabled {
                opacity: 0.4;
                cursor: not-allowed;
                background: #333;
                border-color: #444;
            }

            .permission-badge-toggleable.disabled:hover {
                transform: none;
                box-shadow: none;
                background: #333;
                border-color: #444;
            }

            .form-actions {
                display: flex;
                gap: 12px;
                justify-content: flex-end;
                align-items: center;
                margin-top: 24px;
            }

            .api-docs-btn {
                background: linear-gradient(135deg, #03dac6 0%, #018786 100%);
                color: #121212;
                border: none;
                padding: 12px 20px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-size: 0.95rem;
                display: flex;
                align-items: center;
                gap: 8px;
                box-shadow: 0 2px 8px rgba(3, 218, 198, 0.3);
                position: relative;
                overflow: hidden;
            }

            .api-docs-btn::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
                transition: left 0.5s;
            }

            .api-docs-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(3, 218, 198, 0.4);
                background: linear-gradient(135deg, #26c6da 0%, #00acc1 100%);
            }

            .api-docs-btn:hover::before {
                left: 100%;
            }

            .form-actions button {
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-size: 0.95rem;
            }

            .cancel-create-token {
                background: linear-gradient(135deg, #444 0%, #666 100%);
                color: #e0e0e0;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            }

            .cancel-create-token:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.4);
                background: linear-gradient(135deg, #555 0%, #777 100%);
            }

            .submit-create-token {
                background: linear-gradient(135deg, #03dac6 0%, #018786 100%);
                color: #121212;
                box-shadow: 0 2px 8px rgba(3, 218, 198, 0.3);
            }

            .submit-create-token:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(3, 218, 198, 0.4);
                background: linear-gradient(135deg, #26c6da 0%, #00acc1 100%);
            }

            .token-created-dialog {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 10001;
                font-family: "Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                opacity: 0;
                animation: modal-fade-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            .token-dialog-overlay {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.8);
                backdrop-filter: blur(12px);
            }

            .token-dialog-content {
                position: relative;
                max-width: 600px;
                margin: 10vh auto;
                background: linear-gradient(135deg, #1e1e1e 0%, #2d2d2d 100%);
                border-radius: 12px;
                padding: 24px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
                border: 1px solid #333;
                color: #e0e0e0;
                transform: translateY(20px);
                animation: modal-slide-in 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            .token-dialog-content h3 {
                margin: 0 0 20px 0;
                color: #bb86fc;
                font-size: 1.3rem;
                font-weight: 700;
                text-align: center;
            }

            .token-display {
                margin: 20px 0;
            }

            .token-display label {
                display: block;
                font-weight: 600;
                margin-bottom: 8px;
                color: #03dac6;
                font-size: 0.95rem;
            }

            .token-display textarea {
                width: 100%;
                height: 80px;
                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                font-size: 12px;
                resize: vertical;
                margin-bottom: 8px;
                background: #2a2a2a;
                border: 1px solid #444;
                border-radius: 8px;
                color: #e0e0e0;
                padding: 12px;
                box-sizing: border-box;
                line-height: 1.4;
            }

            .token-display textarea:focus {
                outline: none;
                border-color: #bb86fc;
                box-shadow: 0 0 0 2px rgba(187, 134, 252, 0.2);
            }

            .token-buttons {
                display: flex;
                gap: 8px;
                margin-top: 8px;
                flex-wrap: wrap;
            }

            .token-display button {
                background: linear-gradient(135deg, #bb86fc 0%, #6200ea 100%);
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 2px 8px rgba(187, 134, 252, 0.3);
                font-size: 0.85rem;
                flex: 1;
                min-width: 120px;
            }

            .token-display button:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 15px rgba(187, 134, 252, 0.4);
            }

            .token-display .download-token-btn, 
            .token-display .copy-export-btn,
            .token-display .copy-raw-example-btn {
                background: linear-gradient(135deg, #03dac6 0%, #018786 100%);
                color: #121212;
                box-shadow: 0 2px 8px rgba(3, 218, 198, 0.3);
            }

            .token-display .download-token-btn:hover, 
            .token-display .copy-export-btn:hover,
            .token-display .copy-raw-example-btn:hover {
                box-shadow: 0 4px 15px rgba(3, 218, 198, 0.4);
                background: linear-gradient(135deg, #26c6da 0%, #00acc1 100%);
            }

            .token-expiry {
                font-style: italic;
                color: #888;
                text-align: center;
                font-size: 0.9rem;
                margin-top: 16px;
                padding: 12px;
                background: rgba(3, 218, 198, 0.1);
                border-radius: 8px;
                border: 1px solid rgba(3, 218, 198, 0.2);
            }

            .manage-tokens-btn {
                background: none;
                border: none;
                color: inherit;
                padding: 8px 12px;
                text-align: left;
                width: 100%;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            /* Notification Management Modal Styles */
.notification-management-modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 10000;
}

.notification-management-modal {
    background: white;
    border-radius: 8px;
    max-width: 900px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.notification-management-modal .modal-header {
    padding: 20px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.notification-management-modal .modal-header h2 {
    margin: 0;
    color: #333;
    font-size: 24px;
}

.notification-management-modal .close-btn {
    background: none;
    border: none;
    font-size: 24px;
    cursor: pointer;
    color: #999;
    padding: 0;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.notification-management-modal .close-btn:hover {
    color: #333;
}

.notification-management-modal .modal-content {
    padding: 20px;
}

.notification-management-modal .modal-description {
    margin-bottom: 20px;
    color: #666;
    font-size: 14px;
}

.devices-table-container {
    overflow-x: auto;
}

.devices-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}

.devices-table th,
.devices-table td {
    padding: 12px 8px;
    text-align: left;
    border-bottom: 1px solid #eee;
}

.devices-table th {
    background-color: #f8f9fa;
    font-weight: 600;
    color: #333;
    font-size: 12px;
    text-align: center;
}

.devices-table .device-info {
    min-width: 200px;
}

.devices-table .device-name {
    margin-bottom: 4px;
}

.devices-table .device-name strong {
    color: #333;
    font-size: 14px;
}

.devices-table .device-name small {
    color: #666;
    font-size: 12px;
    display: block;
}

.devices-table .device-details {
    font-size: 11px;
    color: #999;
}

.checkbox-cell {
    text-align: center;
    width: 80px;
}

.actions-cell {
    text-align: center;
    width: 100px;
}

/* Toggle Switch Styles */
.switch {
    position: relative;
    display: inline-block;
    width: 40px;
    height: 20px;
}

.switch input {
    opacity: 0;
    width: 0;
    height: 0;
}

.slider {
    position: absolute;
    cursor: pointer;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: #ccc;
    transition: .4s;
    border-radius: 20px;
}

.slider:before {
    position: absolute;
    content: "";
    height: 16px;
    width: 16px;
    left: 2px;
    bottom: 2px;
    background-color: white;
    transition: .4s;
    border-radius: 50%;
}

input:checked + .slider {
    background-color: #2196F3;
}

input:checked + .slider:before {
    transform: translateX(20px);
}

.remove-device-btn {
    background: #ff4757;
    color: white;
    border: none;
    padding: 6px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    transition: background-color 0.3s;
}

.remove-device-btn:hover {
    background: #ff3742;
}

.no-devices {
    text-align: center;
    padding: 40px 20px;
    color: #666;
}

.no-devices p:first-child {
    font-size: 18px;
    margin-bottom: 10px;
}

/* Responsive design */
@media (max-width: 768px) {
    .notification-management-modal {
        width: 95%;
        max-height: 90vh;
    }
    
    .devices-table {
        font-size: 12px;
    }
    
    .devices-table th,
    .devices-table td {
        padding: 8px 4px;
    }
    
    .checkbox-cell,
    .actions-cell {
        width: auto;
    }
    
    .switch {
        width: 35px;
        height: 18px;
    }
    
    .slider:before {
        height: 14px;
        width: 14px;
    }
    
    input:checked + .slider:before {
        transform: translateX(17px);
    }
}

/* User Profile Dropdown Styles */
.user-profile-dropdown {
                position: relative;
                display: inline-block;
            }

            .user-profile-btn {
                background: none;
                border: none;
                color: #a0a0a0;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 8px;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-family: inherit;
                font-weight: 500;
            }

            .user-profile-btn:hover {
                background: rgba(187, 134, 252, 0.1);
                color: #bb86fc;
            }

            .user-avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                object-fit: cover;
                border: 2px solid #bb86fc;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .user-profile-btn:hover .user-avatar {
                border-color: #03dac6;
                transform: scale(1.05);
            }

            .user-name {
                font-size: 0.95rem;
                font-weight: 600;
            }

            .dropdown-arrow {
                font-size: 0.8rem;
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .user-profile-dropdown.open .dropdown-arrow {
                transform: rotate(180deg);
            }

            .profile-dropdown-menu {
                position: absolute;
                top: 100%;
                right: 0;
                background: linear-gradient(135deg, #1e1e1e 0%, #2d2d2d 100%);
                border: 1px solid #333;
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
                backdrop-filter: blur(12px);
                min-width: 240px;
                z-index: 10000;
                margin-top: 8px;
                opacity: 0;
                transform: translateY(-10px);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                pointer-events: none;
                padding: 8px;
            }

            .profile-dropdown-menu.show {
                opacity: 1;
                transform: translateY(0);
                pointer-events: auto;
            }

            .profile-info {
                padding: 12px 16px 16px 16px;
                border-bottom: 1px solid #333;
                margin: 0 4px 8px 4px;
                border-radius: 8px;
                background: rgba(187, 134, 252, 0.05);
            }

            .profile-name {
                font-weight: 700;
                color: #bb86fc;
                margin-bottom: 6px;
                font-size: 1.05rem;
                text-shadow: 0 1px 2px rgba(187, 134, 252, 0.3);
            }

            .profile-email {
                color: #a0a0a0;
                font-size: 0.85rem;
                font-weight: 500;
            }

            .dropdown-divider {
                border: none;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                margin: 8px 8px;
                opacity: 0.6;
            }

            .dropdown-item {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 12px 16px;
                color: #e0e0e0;
                text-decoration: none;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-size: 0.95rem;
                font-weight: 500;
                cursor: pointer;
                border: none;
                background: none;
                width: 100%;
                text-align: left;
                box-sizing: border-box;
                border-radius: 6px;
                margin: 2px 4px;
                position: relative;
                overflow: hidden;
            }

            .dropdown-item::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
                transition: left 0.5s;
            }

            .dropdown-item:hover {
                background: rgba(187, 134, 252, 0.1);
                color: #bb86fc;
                transform: translateX(2px);
                border-left: 3px solid #bb86fc;
                padding-left: 13px;
            }

            .dropdown-item:hover::before {
                left: 100%;
            }

            .manage-tokens-btn:hover {
                background: rgba(3, 218, 198, 0.1);
                color: #03dac6;
                border-left-color: #03dac6;
            }

            .logout-btn:hover {
                background: rgba(207, 102, 121, 0.1);
                color: #cf6679;
                border-left-color: #cf6679;
            }

            .clear-preferences-btn:hover {
                background: rgba(255, 174, 82, 0.1);
                color: #ff7a3d;
                border-left-color: #ff7a3d;
            }

            /* Pending Notification Styles */
            .pending-approval-notification {
                position: fixed;
                top: 70px;
                left: 50%;
                transform: translateX(-50%);
                background: linear-gradient(135deg, #2d1b1e 0%, #1a1a1a 100%);
                border: 2px solid #cf6679;
                border-radius: 12px;
                padding: 20px;
                box-shadow: 0 8px 32px rgba(207, 102, 121, 0.4);
                z-index: 9999;
                max-width: 600px;
                width: 90%;
                color: #e0e0e0;
                animation: notification-slide-in 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;
                cursor: pointer;
            }

            @keyframes notification-slide-in {
                from {
                    opacity: 0;
                    transform: translateX(-50%) translateY(-20px);
                }
                to {
                    opacity: 1;
                    transform: translateX(-50%) translateY(0);
                }
            }

            .pending-approval-notification.fade-out {
                animation: notification-fade-out 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }

            @keyframes notification-fade-out {
                from {
                    opacity: 1;
                    transform: translateX(-50%) translateY(0);
                }
                to {
                    opacity: 0;
                    transform: translateX(-50%) translateY(-20px);
                }
            }

            .pending-notification-content {
                display: flex;
                align-items: flex-start;
                gap: 16px;
            }

            .pending-notification-icon {
                font-size: 2rem;
                color: #ff7a3d;
                flex-shrink: 0;
            }

            .pending-notification-text h3 {
                margin: 0 0 8px 0;
                color: #cf6679;
                font-size: 1.2rem;
                font-weight: 700;
            }

            .pending-notification-text p {
                margin: 0;
                line-height: 1.4;
                color: #a0a0a0;
            }

            .pending-notification-status {
                margin-left: auto;
                flex-shrink: 0;
            }

            .status-badge {
                background: linear-gradient(135deg, #ff7a3d 0%, #ff7a3d 100%);
                color: #121212;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 0.8rem;
                font-weight: 700;
                letter-spacing: 0.05em;
            }
        `;
        
        document.head.appendChild(styles);
    }
}

// Initialize auth manager as early as possible
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.authManager = new AuthManager();
    });
} else {
    window.authManager = new AuthManager();
}

// Handle URL parameters for auth errors
document.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const error = urlParams.get('error');
    
    if (error) {
        let errorMessage = 'Authentication failed. Please try again.';
        
        switch (error) {
            case 'oauth_error':
                errorMessage = 'OAuth authorization failed.';
                break;
            case 'no_code':
                errorMessage = 'No authorization code received.';
                break;
            case 'no_token':
                errorMessage = 'Failed to get access token.';
                break;
            case 'auth_failed':
                errorMessage = 'Authentication process failed.';
                break;
        }
        
        // Show error message (you can customize this)
        console.error('Auth error:', errorMessage);
        
        // Remove error from URL
        const newUrl = new URL(window.location);
        newUrl.searchParams.delete('error');
        window.history.replaceState({}, document.title, newUrl);
    }
}); 
