/**
 * PWA Installation and Notification Management
 * Handles PWA installation prompts and enforces PWA-only notifications
 */

class PWAManager {
    constructor() {
        this.deferredPrompt = null;
        this.isInstalled = false;
        this.installCallbacks = [];
        
        this.init();
    }

    init() {
        // Check if already installed
        this.checkInstallationStatus();
        
        // Listen for installation events
        this.setupEventListeners();
        
        // Setup installation prompt detection
        this.setupInstallPrompt();
        
        // Handle URL parameters for redirects
        this.handleRedirectParameters();
    }

    handleRedirectParameters() {
        const urlParams = new URLSearchParams(window.location.search);
        
        if (urlParams.get('pwa') === 'true' || urlParams.get('pwa') === 'installed') {
            // Remove the parameter from URL
            window.history.replaceState({}, document.title, window.location.pathname);
            
            // Show welcome message for PWA users
            if (this.isInstalled) {
                this.showPWAWelcomeMessage();
            }
        }
        
        if (urlParams.get('source') === 'browser-redirect') {
            // Remove the parameter from URL
            window.history.replaceState({}, document.title, window.location.pathname);
            
            // Show message about better experience in PWA
            if (this.isInstalled) {
                this.showPWAWelcomeMessage();
            } else {
                this.showBrowserRedirectMessage();
            }
        }
    }

    showPWAWelcomeMessage() {
        // Only show if we're actually in PWA mode
        if (this.isInstalled) {
            const message = document.createElement('div');
            message.className = 'pwa-success-message';
            message.innerHTML = `
                <div class="pwa-success-content">
                    🎉 Welcome to the Climbing App! You can now enable reliable notifications in settings.
                    <button onclick="this.parentElement.parentElement.remove()">Got it</button>
                </div>
            `;
            
            document.body.appendChild(message);
            
            // Auto-remove after 5 seconds
            setTimeout(() => {
                if (message.parentElement) {
                    message.remove();
                }
            }, 5000);
        }
    }

    showBrowserRedirectMessage() {
        const message = document.createElement('div');
        message.className = 'pwa-success-message';
        message.innerHTML = `
            <div class="pwa-success-content" style="background: linear-gradient(135deg, #f39c12, #e67e22);">
                ⚠️ For best notification reliability, please open the Climbing app from your home screen instead of the browser.
                <button onclick="this.parentElement.parentElement.remove()">Got it</button>
            </div>
        `;
        
        document.body.appendChild(message);
        
        // Auto-remove after 8 seconds (longer for important message)
        setTimeout(() => {
            if (message.parentElement) {
                message.remove();
            }
        }, 8000);
    }

    setupEventListeners() {
        // PWA installation prompt
        window.addEventListener('beforeinstallprompt', (e) => {
            console.log('PWA: Install prompt available');
            e.preventDefault();
            this.deferredPrompt = e;
            // Install button now only available through user dropdown
        });

        // PWA installed
        window.addEventListener('appinstalled', (evt) => {
            console.log('PWA: App was installed');
            this.isInstalled = true;
            this.hideInstallButton();
            this.onInstallationComplete();
        });

        // Detect standalone mode (already installed)
        if (window.matchMedia('(display-mode: standalone)').matches || 
            window.navigator.standalone === true) {
            this.isInstalled = true;
            console.log('PWA: Running in standalone mode');
        }
    }

    checkInstallationStatus() {
        // Check if running as PWA
        const isStandalone = window.matchMedia('(display-mode: standalone)').matches || 
                           window.navigator.standalone === true;
        
        // Check if installation prompt was shown before
        const hasPromptBeenShown = localStorage.getItem('pwa-prompt-shown') === 'true';
        
        this.isInstalled = isStandalone;
        
        console.log('PWA Status:', {
            isStandalone: isStandalone,
            hasPromptBeenShown: hasPromptBeenShown,
            userAgent: navigator.userAgent
        });
    }

    setupInstallPrompt() {
        // Don't show automatic popup - only available through user dropdown
        // The install option will be available in the user profile dropdown
        return;
    }

    // Check if PWA can be installed (for dropdown visibility)
    canInstall() {
        return !this.isInstalled;
    }

    showInstallButton() {
        // Remove any existing install buttons
        this.hideInstallButton();
        
        const installButton = document.createElement('div');
        installButton.id = 'pwa-install-button';
        installButton.className = 'pwa-install-button';
        installButton.innerHTML = `
            <div class="pwa-install-content">
                <div class="pwa-install-icon">📱</div>
                <div class="pwa-install-text">
                    <strong>Install App</strong>
                    <small>For reliable notifications</small>
                </div>
                <button class="pwa-install-btn" onclick="pwaManager.installApp()">Install</button>
                <button class="pwa-install-close" onclick="pwaManager.dismissInstallPrompt()">×</button>
            </div>
        `;
        
        document.body.appendChild(installButton);
        
        // Add CSS if not already added
        this.addInstallButtonStyles();
    }

    hideInstallButton() {
        const existingButton = document.getElementById('pwa-install-button');
        if (existingButton) {
            existingButton.remove();
        }
    }

    showInstallPrompt() {
        if (this.isInstalled || localStorage.getItem('pwa-prompt-dismissed')) {
            return;
        }

        const modal = document.createElement('div');
        modal.id = 'pwa-install-modal';
        modal.className = 'pwa-install-modal';
        modal.innerHTML = `
            <div class="pwa-modal-backdrop" onclick="pwaManager.dismissInstallPrompt()"></div>
            <div class="pwa-modal-content">
                <div class="pwa-modal-header">
                    <h3>🧗‍♂️ Install Climbing App</h3>
                    <button class="pwa-modal-close" onclick="pwaManager.dismissInstallPrompt()">×</button>
                </div>
                <div class="pwa-modal-body">
                    <p><strong>Get reliable notifications!</strong></p>
                    <ul>
                        <li>✅ Instant climbing updates</li>
                        <li>✅ Works offline</li>
                        <li>✅ App-like experience</li>
                        <li>✅ No browser tabs needed</li>
                    </ul>
                    <p><em>Notifications only work with the installed app.</em></p>
                </div>
                <div class="pwa-modal-actions">
                    <button class="pwa-modal-install" onclick="pwaManager.installApp()">Install Now</button>
                    <button class="pwa-modal-later" onclick="pwaManager.dismissInstallPrompt()">Maybe Later</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.addModalStyles();
    }

    async installApp() {
        if (!this.deferredPrompt) {
            // Fallback: show manual installation instructions
            this.showManualInstallInstructions();
            return;
        }

        try {
            this.deferredPrompt.prompt();
            const result = await this.deferredPrompt.userChoice;
            
            console.log('PWA: User choice:', result.outcome);
            
            if (result.outcome === 'accepted') {
                console.log('PWA: User accepted installation');
                localStorage.setItem('pwa-prompt-shown', 'true');
                this.deferredPrompt = null;
                // Refresh user dropdown to hide install option
                if (window.authManager) {
                    window.authManager.updateNavigation();
                }
            } else {
                console.log('PWA: User dismissed installation');
                localStorage.setItem('pwa-prompt-dismissed', 'true');
                // Keep deferredPrompt available for future attempts from dropdown
            }
            this.hideInstallButton();
            this.hideInstallModal();
            
        } catch (error) {
            console.error('PWA: Installation failed:', error);
            this.showManualInstallInstructions();
        }
    }

    showManualInstallInstructions() {
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        const isAndroid = /Android/.test(navigator.userAgent);
        
        let instructions = '';
        
        if (isIOS) {
            instructions = `
                <p><strong>To install on iOS:</strong></p>
                <ol>
                    <li>Tap the Share button <span style="font-size: 1.2em;">⎋</span></li>
                    <li>Scroll down and tap "Add to Home Screen"</li>
                    <li>Tap "Add" to install</li>
                </ol>
            `;
        } else if (isAndroid) {
            instructions = `
                <p><strong>To install on Android:</strong></p>
                <ol>
                    <li>Tap the menu button (⋮) in Chrome</li>
                    <li>Tap "Add to Home screen"</li>
                    <li>Tap "Add" to install</li>
                </ol>
            `;
        } else {
            instructions = `
                <p><strong>To install:</strong></p>
                <ol>
                    <li>Look for an install icon in your address bar</li>
                    <li>Or check your browser menu for "Install" option</li>
                </ol>
            `;
        }

        this.showModal('Manual Installation', instructions);
    }

    dismissInstallPrompt() {
        localStorage.setItem('pwa-prompt-dismissed', 'true');
        this.hideInstallButton();
        this.hideInstallModal();
        
        // Keep deferredPrompt available for future attempts from dropdown
        // Don't refresh navigation since install option should remain available
    }

    hideInstallModal() {
        const modal = document.getElementById('pwa-install-modal');
        if (modal) {
            modal.remove();
        }
    }

    onInstallationComplete() {
        // Notify callbacks that installation is complete
        this.installCallbacks.forEach(callback => callback());
        this.installCallbacks = [];
        
        // Show success message briefly, then redirect
        this.showSuccessMessage();
        
        // Redirect to the PWA after a short delay
        setTimeout(() => {
            this.redirectToPWA();
        }, 2000);
    }

    redirectToPWA() {
        // Close the current browser tab/window and open the PWA
        try {
            // For Chrome/Edge - try to launch the PWA directly
            if ('getInstalledRelatedApps' in navigator) {
                // Modern approach - let the browser handle the transition
                window.location.href = window.location.origin + '?pwa=true';
            } else {
                // Fallback - show instructions to open the PWA
                this.showPWAOpenInstructions();
            }
        } catch (error) {
            console.log('PWA redirect fallback:', error);
            this.showPWAOpenInstructions();
        }
    }

    showPWAOpenInstructions() {
        this.showModal(
            '📱 App Installed Successfully!',
            `
                <p><strong>Your Climbing App is now installed!</strong></p>
                <p>To get the best experience with reliable notifications:</p>
                <ol style="text-align: left; margin: 16px 0;">
                    <li><strong>Look for the Climbing app icon</strong> on your home screen</li>
                    <li><strong>Tap the icon</strong> to open the app</li>
                    <li><strong>Enable notifications</strong> in the app for best reliability</li>
                </ol>
                <p><em>The app works offline and provides much better notification delivery!</em></p>
                <div style="margin: 20px 0;">
                    <button class="pwa-modal-install" onclick="window.location.href = window.location.origin + '?pwa=installed'; this.closest('.pwa-install-modal').remove();">
                        Open App Now
                    </button>
                </div>
            `
        );
    }

    showSuccessMessage() {
        const message = document.createElement('div');
        message.className = 'pwa-success-message';
        message.innerHTML = `
            <div class="pwa-success-content">
                ✅ App installed successfully! You can now enable notifications.
                <button onclick="this.parentElement.parentElement.remove()">Got it</button>
            </div>
        `;
        
        document.body.appendChild(message);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (message.parentElement) {
                message.remove();
            }
        }, 5000);
    }

    showModal(title, content) {
        const modal = document.createElement('div');
        modal.className = 'pwa-install-modal';
        modal.innerHTML = `
            <div class="pwa-modal-backdrop" onclick="this.closest('.pwa-install-modal').remove()"></div>
            <div class="pwa-modal-content">
                <div class="pwa-modal-header">
                    <h3>${title}</h3>
                    <button class="pwa-modal-close" onclick="this.closest('.pwa-install-modal').remove()">×</button>
                </div>
                <div class="pwa-modal-body">
                    ${content}
                </div>
                <div class="pwa-modal-actions">
                    <button class="pwa-modal-close-btn" onclick="this.closest('.pwa-install-modal').remove()">Close</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.addModalStyles();
    }

    // Check if PWA is installed (for notification gating)
    isPWAInstalled() {
        return this.isInstalled;
    }

    // Register callback for when PWA gets installed
    onInstall(callback) {
        if (this.isInstalled) {
            callback();
        } else {
            this.installCallbacks.push(callback);
        }
    }

    // Prompt user to install PWA for notifications
    promptForNotifications() {
        if (this.isInstalled) {
            return true; // Already installed, can proceed
        }

        // Check if PWA is installed but user is in browser
        this.checkIfPWAInstalledButInBrowser().then(pwaInstalled => {
            if (pwaInstalled) {
                this.showOpenPWAForNotifications();
            } else {
                this.showInstallPWAForNotifications();
            }
        }).catch(() => {
            this.showInstallPWAForNotifications();
        });

        return false; // Installation required
    }

    async checkIfPWAInstalledButInBrowser() {
        // Check if PWA is installed using getInstalledRelatedApps API
        if ('getInstalledRelatedApps' in navigator) {
            try {
                const relatedApps = await navigator.getInstalledRelatedApps();
                return relatedApps.length > 0;
            } catch (error) {
                console.log('Could not check installed apps:', error);
            }
        }
        
        // Fallback: check if we're in browser mode but have indicators of PWA installation
        const hasBeenInstalled = localStorage.getItem('pwa-prompt-shown') === 'true';
        const isInBrowser = !window.matchMedia('(display-mode: standalone)').matches && 
                           window.navigator.standalone !== true;
        
        return hasBeenInstalled && isInBrowser;
    }

    showOpenPWAForNotifications() {
        this.showModal(
            '📱 Open App for Reliable Notifications',
            `
                <p><strong>You already have the Climbing App installed!</strong></p>
                <p>For the most reliable notifications, please:</p>
                <ol style="text-align: left; margin: 16px 0;">
                    <li><strong>Close this browser tab</strong></li>
                    <li><strong>Open the Climbing app</strong> from your home screen</li>
                    <li><strong>Enable notifications</strong> in the app</li>
                </ol>
                <p><em>Browser notifications are less reliable than app notifications.</em></p>
                <div style="margin: 20px 0;">
                    <button class="pwa-modal-install" onclick="window.location.href = window.location.origin + '?source=browser-redirect'; this.closest('.pwa-install-modal').remove();">
                        Open App Instead
                    </button>
                </div>
                <p><small>Or continue in browser with limited reliability</small></p>
            `
        );
    }

    showInstallPWAForNotifications() {
        this.showModal(
            '📱 Install Required for Notifications',
            `
                <p><strong>Notifications require the app to be installed.</strong></p>
                <p>This ensures reliable delivery of climbing updates.</p>
                <div style="margin: 20px 0;">
                    <button class="pwa-modal-install" onclick="pwaManager.installApp(); this.closest('.pwa-install-modal').remove();">
                        Install App Now
                    </button>
                </div>
                <p><small>You can enable notifications after installation.</small></p>
            `
        );
    }

    addInstallButtonStyles() {
        if (document.getElementById('pwa-install-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'pwa-install-styles';
        styles.textContent = `
            .pwa-install-button {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1000;
                background: linear-gradient(135deg, #4285f4, #34a853);
                color: white;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                max-width: 280px;
                animation: slideInRight 0.3s ease-out;
            }

            .pwa-install-content {
                display: flex;
                align-items: center;
                padding: 12px 16px;
                gap: 12px;
            }

            .pwa-install-icon {
                font-size: 24px;
                flex-shrink: 0;
            }

            .pwa-install-text {
                flex: 1;
                min-width: 0;
            }

            .pwa-install-text strong {
                display: block;
                font-weight: 600;
                font-size: 14px;
            }

            .pwa-install-text small {
                display: block;
                opacity: 0.9;
                font-size: 12px;
                margin-top: 2px;
            }

            .pwa-install-btn {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: white;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.2s;
            }

            .pwa-install-btn:hover {
                background: rgba(255,255,255,0.3);
            }

            .pwa-install-close {
                background: none;
                border: none;
                color: white;
                font-size: 18px;
                cursor: pointer;
                padding: 4px;
                margin-left: 8px;
                opacity: 0.8;
                transition: opacity 0.2s;
            }

            .pwa-install-close:hover {
                opacity: 1;
            }

            @keyframes slideInRight {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }

            @media (max-width: 480px) {
                .pwa-install-button {
                    top: 10px;
                    right: 10px;
                    left: 10px;
                    max-width: none;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }

    addModalStyles() {
        if (document.getElementById('pwa-modal-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'pwa-modal-styles';
        styles.textContent = `
            .pwa-install-modal {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                z-index: 99999;
                display: flex;
                align-items: center;
                justify-content: center;
                animation: fadeIn 0.3s ease-out;
                pointer-events: auto;
            }

            .pwa-modal-backdrop {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                backdrop-filter: none;
            }

            .pwa-modal-content {
                position: relative;
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.3);
                max-width: 400px;
                width: 90%;
                max-height: 80vh;
                overflow: hidden;
                animation: slideInUp 0.3s ease-out;
                z-index: 100000;
            }

            .pwa-modal-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 20px 24px 0;
            }

            .pwa-modal-header h3 {
                margin: 0;
                font-size: 20px;
                font-weight: 600;
                color: #1a1a1a;
            }

            .pwa-modal-close {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                color: #666;
                padding: 4px;
                transition: color 0.2s;
                line-height: 1;
                width: 32px;
                height: 32px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .pwa-modal-close:hover {
                color: #333;
                background: #f0f0f0;
                border-radius: 50%;
            }

            .pwa-modal-body {
                padding: 20px 24px;
                color: #333;
            }

            .pwa-modal-body p {
                margin: 0 0 16px;
                line-height: 1.5;
                color: #333;
                font-size: 16px;
            }

            .pwa-modal-body strong {
                color: #1a1a1a;
                font-weight: 600;
            }

            .pwa-modal-body ul {
                margin: 16px 0;
                padding-left: 0;
                list-style: none;
            }

            .pwa-modal-body li {
                margin: 8px 0;
                padding-left: 0;
                color: #333;
            }

            .pwa-modal-actions {
                padding: 0 24px 24px;
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
            }

            .pwa-modal-install {
                flex: 1;
                background: linear-gradient(135deg, #4285f4, #34a853);
                color: white;
                border: none;
                padding: 14px 24px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 16px;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                min-height: 48px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .pwa-modal-install:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 16px rgba(66, 133, 244, 0.4);
            }

            .pwa-modal-install:active {
                transform: translateY(0);
            }

            .pwa-modal-later, .pwa-modal-close-btn {
                background: #f8f9fa;
                color: #5f6368;
                border: 1px solid #dadce0;
                padding: 14px 24px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                transition: all 0.2s;
                min-height: 48px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .pwa-modal-later:hover, .pwa-modal-close-btn:hover {
                background: #f1f3f4;
                border-color: #c4c7c5;
            }

            .pwa-success-message {
                position: fixed;
                top: 20px;
                left: 20px;
                right: 20px;
                z-index: 10001;
                animation: slideInDown 0.3s ease-out;
            }

            .pwa-success-content {
                background: linear-gradient(135deg, #34a853, #4285f4);
                color: white;
                padding: 16px 20px;
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                display: flex;
                align-items: center;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 12px;
            }

            .pwa-success-content button {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: white;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 12px;
                cursor: pointer;
                transition: background 0.2s;
            }

            .pwa-success-content button:hover {
                background: rgba(255,255,255,0.3);
            }

            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }

            @keyframes slideInUp {
                from {
                    transform: translateY(20px);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }

            @keyframes slideInDown {
                from {
                    transform: translateY(-100%);
                    opacity: 0;
                }
                to {
                    transform: translateY(0);
                    opacity: 1;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }
}

// Initialize PWA Manager
window.pwaManager = new PWAManager();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PWAManager;
}