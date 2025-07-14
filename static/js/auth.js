/**
 * Authentication module for Google OAuth integration
 */

class AuthManager {
    constructor() {
        this.currentUser = null;
        this.isAuthenticated = false;
        this.init();
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
        await this.checkAuthStatus();
        this.setupEventListeners();
        this.updateUI();
    }

    async checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/user');
            const data = await response.json();
            
            this.isAuthenticated = data.authenticated;
            this.currentUser = data.user;
            
            console.log('Auth status:', { authenticated: this.isAuthenticated, user: this.currentUser });
        } catch (error) {
            console.error('Error checking auth status:', error);
            this.isAuthenticated = false;
            this.currentUser = null;
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
        if (dropdown) {
            dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
        }
    }

    closeProfileDropdown() {
        const dropdown = document.querySelector('.profile-dropdown-menu');
        if (dropdown) {
            dropdown.style.display = 'none';
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
    }

    updateNavigation() {
        const nav = document.querySelector('nav');
        if (!nav) return;

        // Remove existing auth elements
        const existingAuthElements = nav.querySelectorAll('.auth-element');
        existingAuthElements.forEach(el => el.remove());

        if (this.isAuthenticated && this.currentUser) {
            // Add user profile dropdown
            this.addUserProfileDropdown(nav);
        } else {
            // Add login button
            this.addLoginButton(nav);
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
                </svg>
                Login
            </span>
        `;
        nav.appendChild(loginBtn);
    }

    addUserProfileDropdown(nav) {
        const userDropdown = document.createElement('div');
        userDropdown.className = 'user-profile-dropdown auth-element';
        
        // Extract first name for cleaner display
        const firstName = this.currentUser.name.split(' ')[0];
        
        // Check if user is admin
        const isAdmin = this.currentUser.role === 'admin' || 
                       (this.currentUser.permissions && this.currentUser.permissions.can_manage_users);
        
        // Generate admin panel link if user is admin
        const adminPanelLink = isAdmin ? `
            <a href="/admin" class="dropdown-item">
                <span>🛠️</span> Admin Panel
            </a>
            <hr class="dropdown-divider">
        ` : '';
        
        userDropdown.innerHTML = `
            <button class="user-profile-btn">
                <img src="${this.getProfilePictureUrl(this.currentUser)}" 
                     alt="${this.currentUser.name}" 
                     class="user-avatar">
                <span class="user-name">${firstName}</span>
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="profile-dropdown-menu" style="display: none;">
                <div class="profile-info">
                    <div class="profile-name">${this.currentUser.name}</div>
                    <div class="profile-email">${this.currentUser.email}</div>
                </div>
                <hr class="dropdown-divider">
                ${adminPanelLink}
                <button class="clear-preferences-btn dropdown-item" style="background: none; border: none; color: inherit; padding: 8px 12px; text-align: left; width: 100%; cursor: pointer; display: flex; align-items: center; gap: 8px;">
                    <span>🗑️</span> Clear Preferences
                </button>
                <hr class="dropdown-divider">
                <a href="/auth/logout" class="logout-btn dropdown-item">
                    <span>🚪</span> Logout
                </a>
            </div>
        `;
        nav.appendChild(userDropdown);
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
        if (!this.isAuthenticated || !this.currentUser) return;

        // Update any user info placeholders
        const userNameElements = document.querySelectorAll('[data-user-name]');
        const userEmailElements = document.querySelectorAll('[data-user-email]');
        const userAvatarElements = document.querySelectorAll('[data-user-avatar]');

        userNameElements.forEach(el => {
            el.textContent = this.currentUser.name;
        });

        userEmailElements.forEach(el => {
            el.textContent = this.currentUser.email;
        });

        userAvatarElements.forEach(el => {
            el.src = this.getProfilePictureUrl(this.currentUser);
            el.alt = this.currentUser.name;
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

    // Method to refresh auth status (useful after login/logout)
    async refreshAuthStatus() {
        await this.checkAuthStatus();
        this.updateUI();
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
}

// Initialize auth manager when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.authManager = new AuthManager();
});

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
