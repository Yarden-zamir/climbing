/**
 * Version Manager - Handles version checking and update notifications
 * Checks for new versions after the page loads to provide fastest user experience
 */

class VersionManager {
    constructor() {
        this.currentVersion = null;
        this.serverVersion = null;
        this.checkInterval = null;
        this.updateNotification = null;
        
        this.init();
    }

    async init() {
        // Wait for the page to fully load before checking
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => this.startVersionChecking(), 2000); // Wait 2s after load
            });
        } else {
            setTimeout(() => this.startVersionChecking(), 2000);
        }
    }

    async startVersionChecking() {
        console.log('Version Manager: Starting version checking...');
        
        // Get current version from service worker if available
        await this.getCurrentVersion();
        
        // Do initial check
        await this.checkForUpdates();
        
        // Set up periodic checking (every 5 minutes)
        this.checkInterval = setInterval(() => {
            this.checkForUpdates();
        }, 5 * 60 * 1000);
    }

    async getCurrentVersion() {
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
            try {
                const messageChannel = new MessageChannel();
                const versionPromise = new Promise((resolve) => {
                    messageChannel.port1.onmessage = (event) => {
                        resolve(event.data.version);
                    };
                });

                navigator.serviceWorker.controller.postMessage(
                    { type: 'GET_VERSION' }, 
                    [messageChannel.port2]
                );

                this.currentVersion = await versionPromise;
                console.log('Version Manager: Current version from SW:', this.currentVersion);
            } catch (error) {
                console.warn('Version Manager: Failed to get version from service worker:', error);
            }
        }
    }

    async checkForUpdates() {
        try {
            console.log('Version Manager: Checking for updates...');
            
            // Fetch current server version
            const response = await fetch('/api/version', {
                cache: 'no-cache' // Always get fresh version info
            });
            
            if (!response.ok) {
                console.warn('Version Manager: Failed to fetch server version');
                return;
            }
            
            const data = await response.json();
            this.serverVersion = data.version;
            
            console.log('Version Manager: Server version:', this.serverVersion);
            console.log('Version Manager: Current version:', this.currentVersion);
            
            // Check if we have a new version
            if (this.currentVersion && 
                this.serverVersion && 
                this.currentVersion !== this.serverVersion) {
                
                console.log('Version Manager: New version detected!');
                this.showUpdateNotification();
            } else {
                console.log('Version Manager: No update needed');
            }
            
        } catch (error) {
            console.error('Version Manager: Error checking for updates:', error);
        }
    }

    showUpdateNotification() {
        // Don't show multiple notifications
        if (this.updateNotification && document.body.contains(this.updateNotification)) {
            return;
        }

        console.log('Version Manager: Showing update notification');

        this.updateNotification = document.createElement('div');
        this.updateNotification.className = 'version-update-notification';
        this.updateNotification.innerHTML = `
            <div class="version-update-content">
                <div class="version-update-icon">🚀</div>
                <div class="version-update-text">
                    <strong>New version available!</strong>
                    <small>Click to reload and get the latest features</small>
                </div>
                <button class="version-update-btn" onclick="versionManager.reloadWithNewVersion()">
                    Reload
                </button>
                <button class="version-update-close" onclick="versionManager.dismissUpdateNotification()">
                    ×
                </button>
            </div>
        `;

        document.body.appendChild(this.updateNotification);
        this.addNotificationStyles();

        // Auto-show with animation
        setTimeout(() => {
            this.updateNotification.classList.add('version-update-show');
        }, 100);
    }

    dismissUpdateNotification() {
        if (this.updateNotification) {
            this.updateNotification.classList.remove('version-update-show');
            setTimeout(() => {
                if (this.updateNotification && this.updateNotification.parentElement) {
                    this.updateNotification.remove();
                }
                this.updateNotification = null;
            }, 300);
        }
    }

    async reloadWithNewVersion() {
        console.log('Version Manager: Reloading with new version...');
        
        try {
            // Clear service worker cache to ensure fresh content
            if ('serviceWorker' in navigator) {
                const registration = await navigator.serviceWorker.ready;
                
                // Tell service worker to skip waiting and activate immediately
                if (registration.waiting) {
                    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                }
                
                // Clear caches
                if ('caches' in window) {
                    const cacheNames = await caches.keys();
                    await Promise.all(
                        cacheNames.map(name => caches.delete(name))
                    );
                }
            }
            
            // Show loading indicator
            this.showReloadingIndicator();
            
            // Reload the page
            setTimeout(() => {
                window.location.reload(true);
            }, 500);
            
        } catch (error) {
            console.error('Version Manager: Error during reload:', error);
            // Fallback to simple reload
            window.location.reload(true);
        }
    }

    showReloadingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'version-reloading-indicator';
        indicator.innerHTML = `
            <div class="version-reloading-content">
                <div class="version-reloading-spinner"></div>
                <div class="version-reloading-text">Loading new version...</div>
            </div>
        `;
        document.body.appendChild(indicator);

        setTimeout(() => indicator.classList.add('version-reloading-show'), 100);
    }

    addNotificationStyles() {
        if (document.getElementById('version-update-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'version-update-styles';
        styles.textContent = `
            .version-update-notification {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.3);
                max-width: 350px;
                transform: translateX(400px);
                transition: transform 0.3s ease-out;
                backdrop-filter: blur(10px);
            }

            .version-update-notification.version-update-show {
                transform: translateX(0);
            }

            .version-update-content {
                display: flex;
                align-items: center;
                padding: 16px 20px;
                gap: 12px;
            }

            .version-update-icon {
                font-size: 24px;
                flex-shrink: 0;
            }

            .version-update-text {
                flex: 1;
                min-width: 0;
            }

            .version-update-text strong {
                display: block;
                font-weight: 600;
                font-size: 14px;
                margin-bottom: 4px;
            }

            .version-update-text small {
                display: block;
                opacity: 0.9;
                font-size: 12px;
                line-height: 1.3;
            }

            .version-update-btn {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: white;
                padding: 8px 16px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
                backdrop-filter: blur(5px);
            }

            .version-update-btn:hover {
                background: rgba(255,255,255,0.3);
                transform: translateY(-1px);
            }

            .version-update-close {
                background: none;
                border: none;
                color: white;
                font-size: 20px;
                cursor: pointer;
                padding: 4px;
                margin-left: 8px;
                opacity: 0.8;
                transition: opacity 0.2s;
                width: 28px;
                height: 28px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .version-update-close:hover {
                opacity: 1;
                background: rgba(255,255,255,0.1);
            }

            .version-reloading-indicator {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                z-index: 20000;
                background: rgba(0,0,0,0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                opacity: 0;
                transition: opacity 0.3s ease-out;
                backdrop-filter: blur(5px);
            }

            .version-reloading-indicator.version-reloading-show {
                opacity: 1;
            }

            .version-reloading-content {
                background: white;
                padding: 32px;
                border-radius: 16px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            }

            .version-reloading-spinner {
                width: 40px;
                height: 40px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #667eea;
                border-radius: 50%;
                animation: version-spin 1s linear infinite;
                margin: 0 auto 16px;
            }

            .version-reloading-text {
                font-size: 16px;
                font-weight: 600;
                color: #333;
            }

            @keyframes version-spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            @media (max-width: 480px) {
                .version-update-notification {
                    top: 10px;
                    right: 10px;
                    left: 10px;
                    max-width: none;
                    transform: translateY(-100px);
                }

                .version-update-notification.version-update-show {
                    transform: translateY(0);
                }

                .version-update-content {
                    padding: 14px 16px;
                    gap: 10px;
                }

                .version-update-text strong {
                    font-size: 13px;
                }

                .version-update-text small {
                    font-size: 11px;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }

    // Cleanup method
    destroy() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }

        if (this.updateNotification && this.updateNotification.parentElement) {
            this.updateNotification.remove();
        }
    }
}

// Initialize version manager globally
window.versionManager = new VersionManager();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = VersionManager;
}