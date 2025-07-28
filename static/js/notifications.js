/**
 * Push Notifications Manager
 * Handles service worker registration, push subscriptions, and notification permissions
 */

class NotificationsManager {
    constructor() {
        this.registration = null;
        this.subscription = null;
        this.isSupported = this.checkSupport();
        this.vapidPublicKey = null;
        this.isEnabled = false;
        this.deviceId = this.getOrCreateDeviceId();
        this.init();
    }

    checkSupport() {
        return ('serviceWorker' in navigator && 
                'PushManager' in window && 
                'Notification' in window);
    }

    /**
     * Get or create a persistent device ID for this browser
     * This survives across sessions, logouts, etc.
     */
    getOrCreateDeviceId() {
        let deviceId = localStorage.getItem('climbing_device_id');
        if (!deviceId) {
            deviceId = 'device_' + crypto.randomUUID();
            localStorage.setItem('climbing_device_id', deviceId);
            console.log('🔧 Generated new device ID:', deviceId);
        } else {
            console.log('📱 Using existing device ID:', deviceId.substring(0, 15) + '...');
        }
        return deviceId;
    }

    /**
     * Get device information for server storage
     */
    getDeviceInfo() {
        const userAgent = navigator.userAgent;
        let browserName = 'Unknown';
        
        if (userAgent.includes('Chrome/') && !userAgent.includes('Edg/')) {
            const match = userAgent.match(/Chrome\/(\d+)/);
            browserName = `Chrome ${match ? match[1] : 'unknown'}`;
        } else if (userAgent.includes('Firefox/')) {
            const match = userAgent.match(/Firefox\/(\d+)/);
            browserName = `Firefox ${match ? match[1] : 'unknown'}`;
        } else if (userAgent.includes('Safari/') && !userAgent.includes('Chrome/')) {
            browserName = 'Safari';
        } else if (userAgent.includes('Edg/')) {
            browserName = 'Edge';
        }

        return {
            deviceId: this.deviceId,
            browserName: browserName,
            platform: navigator.platform,
            userAgent: userAgent.substring(0, 200), // Truncate for storage
            lastActive: new Date().toISOString()
        };
    }

    async init() {
        try {
            if (!this.isSupported) {
                console.log('Push notifications not supported');
                return;
            }

            // Register service worker
            this.registration = await navigator.serviceWorker.register('/sw.js');
            console.log('Service Worker registered successfully');

            // Wait for service worker to be ready
            await navigator.serviceWorker.ready;

            // Get VAPID public key from server
            await this.getVapidPublicKey();

            // Check existing subscription state
            await this.checkSubscriptionStatus();

            // Listen for service worker messages
            this.setupServiceWorkerListener();

            console.log('NotificationsManager initialized successfully');

        } catch (error) {
            console.error('Failed to initialize NotificationsManager:', error);
        }
    }

    setupServiceWorkerListener() {
        if (navigator.serviceWorker) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                console.log('📨 Message from Service Worker:', event.data);
                
                if (event.data.type === 'PUSH_RECEIVED') {
                    console.log('🔔 Push notification received by service worker:', event.data);
                } else if (event.data.type === 'NOTIFICATION_SHOWN') {
                    console.log('✅ Notification successfully shown:', event.data);
                } else if (event.data.type === 'NOTIFICATION_ERROR') {
                    console.error('❌ Notification error:', event.data);
                }
            });
            
            console.log('📡 Service worker message listener set up');
        }
    }

    async registerServiceWorker() {
        try {
            this.registration = await navigator.serviceWorker.register('/sw.js', {
                scope: '/'
            });

            console.log('Service Worker registered successfully:', this.registration);

            // Handle service worker updates
            this.registration.addEventListener('updatefound', () => {
                console.log('Service Worker update found');
                const newWorker = this.registration.installing;
                
                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        console.log('New Service Worker installed');
                        // Could show update notification here
                    }
                });
            });

            // Wait for service worker to be ready
            await navigator.serviceWorker.ready;
            
        } catch (error) {
            console.error('Service Worker registration failed:', error);
            throw error;
        }
    }

    async getVapidPublicKey() {
        try {
            const response = await fetch('/api/notifications/vapid-public-key');
            if (!response.ok) {
                throw new Error(`Failed to get VAPID key: ${response.status}`);
            }
            
            const data = await response.json();
            this.vapidPublicKey = data.publicKey;
            console.log('VAPID public key retrieved');
            
        } catch (error) {
            console.error('Failed to get VAPID public key:', error);
            throw error;
        }
    }

    async checkSubscriptionStatus() {
        if (!this.isSupported || !this.registration) {
            return false;
        }

        try {
            // Check if we have an active subscription
            const subscription = await this.registration.pushManager.getSubscription();
            
            if (subscription) {
                // If offline, assume subscription is valid without server verification
                if (!navigator.onLine) {
                    console.log('Offline mode - assuming existing subscription is valid');
                    this.subscription = subscription;
                    this.isEnabled = true;
                    return true;
                }

                // Verify the subscription is still valid by checking with server
                const response = await fetch('/api/notifications/subscriptions', {
                    headers: {
                        'X-Device-ID': this.deviceId
                    },
                    credentials: 'include'
                });

                if (response.ok) {
                    const data = await response.json();
                    if (data.subscription) {
                        this.subscription = subscription;
                        this.isEnabled = true;
                        console.log('Valid subscription found:', data.subscription.subscription_id);
                        return true;
                    }
                }

                // Subscription not found on server, clean up local subscription
                console.log('Local subscription not found on server, cleaning up...');
                await subscription.unsubscribe();
                this.subscription = null;
                this.isEnabled = false;
            }

        } catch (error) {
            // If offline, assume existing subscription is still valid
            if (!navigator.onLine && this.subscription) {
                console.log('Network error during subscription check (offline) - assuming valid');
                return this.isEnabled;
            }
            
            console.error('Error checking subscription state:', error);
            this.subscription = null;
            this.isEnabled = false;
        }

        return false;
    }

    async requestPermission() {
        if (!this.isSupported) {
            throw new Error('Push notifications not supported');
        }

        let permission = Notification.permission;

        if (permission === 'default') {
            permission = await Notification.requestPermission();
        }

        if (permission === 'granted') {
            console.log('Notification permission granted');
            return true;
        } else if (permission === 'denied') {
            console.warn('Notification permission denied');
            throw new Error('Notification permission denied');
        } else {
            console.warn('Notification permission dismissed');
            throw new Error('Notification permission dismissed');
        }
    }



    async enableNotifications() {
        if (!this.isSupported) {
            throw new Error('Push notifications not supported');
        }

        // Check if we're offline
        if (!navigator.onLine) {
            throw new Error('Cannot enable notifications while offline. Please try again when connected.');
        }

        // Enforce PWA installation requirement
        if (!window.pwaManager?.isPWAInstalled()) {
            console.log('PWA not installed - prompting user');
            window.pwaManager?.promptForNotifications();
            throw new Error('PWA installation required for notifications');
        }

        if (!this.registration || !this.vapidPublicKey) {
            throw new Error('Service worker or VAPID key not ready');
        }

        try {
            // Check if we already have a valid subscription
            const hasValidSubscription = await this.checkSubscriptionStatus();
            if (hasValidSubscription) {
                console.log('Already subscribed to notifications');
                return true;
            }

            // Request permission first
            await this.requestPermission();

            // Create push subscription
            const applicationServerKey = this.urlBase64ToUint8Array(this.vapidPublicKey);
            
            this.subscription = await this.registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });

            console.log('Push subscription created:', this.subscription);

            // Send subscription to server
            await this.sendSubscriptionToServer(this.subscription);

            this.isEnabled = true;
            console.log('Push notifications enabled successfully');

            // Mark subscription as active in health manager
            if (window.notificationHealthManager) {
                window.notificationHealthManager.markSubscriptionActive();
            }

            return true;

        } catch (error) {
            console.error('Failed to enable notifications:', error);
            throw error;
        }
    }

    async disableNotifications() {
        if (!this.subscription) {
            console.log('No active subscription to disable');
            return true;
        }

        try {
            // Unsubscribe from push manager
            await this.subscription.unsubscribe();
            console.log('Unsubscribed from push notifications');

            // Remove subscription from server with proper device ID
            await this.removeSubscriptionFromServer();

            this.subscription = null;
            this.isEnabled = false;
            console.log('Push notifications disabled successfully');

            return true;

        } catch (error) {
            console.error('Failed to disable notifications:', error);
            throw error;
        }
    }

    async sendSubscriptionToServer(subscription) {
        const subscriptionData = {
            endpoint: subscription.endpoint,
            keys: {
                p256dh: this.arrayBufferToBase64(subscription.getKey('p256dh')),
                auth: this.arrayBufferToBase64(subscription.getKey('auth'))
            },
            expirationTime: subscription.expirationTime
        };

        // Include device information for device-based subscriptions
        const deviceInfo = this.getDeviceInfo();
        
        const requestData = {
            subscription: subscriptionData,
            deviceInfo: deviceInfo
        };

        console.log('📱 Sending subscription with device info:', deviceInfo);

        const response = await fetch('/api/notifications/subscribe', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Device-ID': this.deviceId // Add device ID header
            },
            credentials: 'include',
            body: JSON.stringify(requestData)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Server error: ${response.status}`);
        }

        const result = await response.json();
        console.log('Subscription sent to server:', result);
        return result;
    }

    async removeSubscriptionFromServer() {
        try {
            console.log('🗑️ Removing subscription from server for device:', this.deviceId);

            const response = await fetch(`/api/notifications/devices/${this.deviceId}`, {
                method: 'DELETE',
                headers: {
                    'X-Device-ID': this.deviceId
                },
                credentials: 'include'
            });

            if (!response.ok) {
                // If it's a 404, the subscription might already be gone
                if (response.status === 404) {
                    console.log('Subscription already removed or not found');
                    return true;
                }
                
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Server error: ${response.status}`);
            }

            const result = await response.json();
            console.log('✅ Subscription removed from server:', result.message);
            return true;

        } catch (error) {
            console.error('❌ Failed to remove subscription from server:', error);
            // Don't throw here - we still want to consider local unsubscribe successful
            // The server-side cleanup can happen via validation/cleanup mechanisms
            return false;
        }
    }

    async sendTestNotification() {
        if (!this.isEnabled) {
            throw new Error('Notifications not enabled');
        }

        // Check if we're offline
        if (!navigator.onLine) {
            throw new Error('Cannot send test notification while offline. Please try again when connected.');
        }

        const testPayload = {
            title: '🧗‍♂️ Test Notification',
            body: 'This is a test notification from the climbing app!',
            icon: '/static/favicon/android-chrome-192x192.png',
            data: { url: '/' }
        };

        const response = await fetch('/api/notifications/test', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify(testPayload)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Test notification failed: ${response.status}`);
        }

        const result = await response.json();
        console.log('Test notification sent:', result);
        return result;
    }

    // === DEBUGGING METHODS ===

    async getNotificationDiagnostics() {
        const diagnostics = {
            supported: this.isSupported,
            permission: Notification.permission,
            serviceWorkerReady: !!this.registration,
            vapidKeyLoaded: !!this.vapidPublicKey,
            subscriptionActive: !!this.subscription,
            enabled: this.isEnabled,
            deviceId: this.deviceId
        };

        if (this.registration) {
            diagnostics.serviceWorkerState = this.registration.active?.state;
            diagnostics.serviceWorkerScope = this.registration.scope;
        }

        if (this.subscription) {
            diagnostics.subscriptionEndpoint = this.subscription.endpoint;
            diagnostics.subscriptionKeys = {
                p256dh: !!this.subscription.getKey('p256dh'),
                auth: !!this.subscription.getKey('auth')
            };
        }

        console.log('📋 Notification Diagnostics:', diagnostics);
        return diagnostics;
    }

    async testNotificationDisplay() {
        try {
            console.log('🧪 Testing notification display...');
            
            // Check permission
            if (Notification.permission !== 'granted') {
                console.error('❌ No notification permission');
                return false;
            }

            // Test service worker registration
            if (!this.registration) {
                console.error('❌ No service worker registration');
                return false;
            }

            // Test basic notification
            const testNotification = await this.registration.showNotification('🧪 Test Notification', {
                body: 'This is a test notification from the climbing app',
                icon: '/static/favicon/android-chrome-192x192.png',
                badge: '/static/favicon/favicon-32x32.png',
                tag: 'test-notification',
                requireInteraction: false,
                data: { test: true },
                silent: false,
                renotify: true,
                vibrate: [200, 100, 200]
            });

            console.log('✅ Test notification should be visible');
            
            // Auto-close after 5 seconds
            setTimeout(async () => {
                const notifications = await this.registration.getNotifications({ tag: 'test-notification' });
                notifications.forEach(n => n.close());
                console.log('🗑️ Test notification auto-closed');
            }, 5000);

            return true;

        } catch (error) {
            console.error('❌ Test notification failed:', error);
            return false;
        }
    }

    async logServiceWorkerState() {
        if (!navigator.serviceWorker) {
            console.log('❌ Service Worker not supported');
            return;
        }

        console.log('📡 Service Worker State:');
        console.log('  - Registration:', !!this.registration);
        console.log('  - Controller:', !!navigator.serviceWorker.controller);
        
        if (this.registration) {
            console.log('  - Active:', !!this.registration.active);
            console.log('  - Installing:', !!this.registration.installing);
            console.log('  - Waiting:', !!this.registration.waiting);
            console.log('  - Scope:', this.registration.scope);
        }

        // List all active notifications
        if (this.registration) {
            try {
                const notifications = await this.registration.getNotifications();
                console.log('  - Active notifications count:', notifications.length);
                if (notifications.length > 0) {
                    notifications.forEach((notif, i) => {
                        console.log(`    ${i + 1}. "${notif.title}" - tag: ${notif.tag}`);
                    });
                }
            } catch (error) {
                console.log('  - Error getting notifications:', error.message);
            }
        }
    }

    async clearAllNotifications() {
        try {
            if (!this.registration) {
                console.log('No service worker registration');
                return 0;
            }

            const notifications = await this.registration.getNotifications();
            console.log(`🗑️ Found ${notifications.length} active notifications to clear`);
            
            notifications.forEach((notification, index) => {
                console.log(`  ${index + 1}. "${notification.title}" (tag: ${notification.tag})`);
                notification.close();
            });

            console.log('✅ All notifications cleared');
            return notifications.length;

        } catch (error) {
            console.error('❌ Failed to clear notifications:', error);
            return 0;
        }
    }

    async checkIfBrowserFocused() {
        const isFocused = !document.hidden;
        const visibilityState = document.visibilityState;
        
        console.log(`🔍 Browser focus state:`, {
            focused: isFocused,
            visibilityState: visibilityState,
            hasFocus: document.hasFocus()
        });

        return isFocused;
    }

    async troubleshootMacOSNotifications() {
        console.log('🍎 macOS Notification Troubleshooting Guide:');
        console.log('');
        
        // Check browser focus
        const isFocused = !document.hidden;
        console.log(`1. Browser Tab Focus: ${isFocused ? '🔍 FOCUSED' : '👀 NOT FOCUSED'}`);
        if (isFocused) {
            console.log('   ⚠️  Chrome often hides notifications when the tab is focused!');
            console.log('   💡 Try switching to another tab/app and then send a notification');
        }
        
        // Check if we're in localhost
        const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
        console.log(`2. Running on localhost: ${isLocalhost ? '✅ YES' : '❌ NO'}`);
        if (isLocalhost) {
            console.log('   ⚠️  Some macOS versions have issues with localhost notifications');
        }
        
        // Check notification permission
        console.log(`3. Notification Permission: ${Notification.permission}`);
        
        // Test multiple notification approaches
        console.log('');
        console.log('🧪 Testing different notification approaches...');
        
        try {
            // Test 1: Basic notification
            console.log('Test 1: Basic notification...');
            await this.registration.showNotification('Test 1: Basic', {
                body: 'Simple notification test',
                tag: 'test-basic-' + Date.now()
            });
            
            // Test 2: With requireInteraction false
            console.log('Test 2: Non-persistent notification...');
            await this.registration.showNotification('Test 2: Non-Persistent', {
                body: 'This should not require interaction',
                requireInteraction: false,
                tag: 'test-non-persistent-' + Date.now()
            });
            
            // Test 3: With requireInteraction true
            console.log('Test 3: Persistent notification...');
            await this.registration.showNotification('Test 3: Persistent', {
                body: 'This should stay visible until clicked',
                requireInteraction: true,
                tag: 'test-persistent-' + Date.now()
            });
            
            // Test 4: Silent notification (should not show)
            console.log('Test 4: Silent notification (should NOT show)...');
            await this.registration.showNotification('Test 4: Silent', {
                body: 'This should be silent',
                silent: true,
                tag: 'test-silent-' + Date.now()
            });
            
        } catch (error) {
            console.error('❌ Notification tests failed:', error);
        }
        
        console.log('');
        console.log('📋 macOS System Settings to Check:');
        console.log('1. System Preferences → Notifications & Focus');
        console.log('2. Find "Google Chrome" in the left list');
        console.log('3. Make sure:');
        console.log('   - ✅ Allow Notifications is ON');
        console.log('   - ✅ Show previews: Always');
        console.log('   - ✅ Notification style: Alerts (not Banners)');
        console.log('   - ✅ Show in Notification Center is checked');
        console.log('');
        console.log('🎯 Chrome Settings to Check:');
        console.log('1. chrome://settings/content/notifications');
        console.log('2. Make sure localhost:8001 is in ALLOWED list');
        console.log('');
        console.log('💡 Focus Test:');
        console.log('1. Switch to another app (like Finder)');
        console.log('2. Send an admin notification');
        console.log('3. See if notification appears');
        
        return true;
    }

    // Utility methods
    urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, '+')
            .replace(/_/g, '/');

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }

    // Getters
    get supported() {
        return this.isSupported;
    }

    get enabled() {
        return this.isEnabled;
    }

    get permissionStatus() {
        return Notification.permission;
    }
}

// Create global instance
window.notificationsManager = new NotificationsManager();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = NotificationsManager;
} 

// Utility functions for debugging Chrome push notification issues
window.debugNotifications = {
    async checkBrowserSupport() {
        const results = {
            serviceWorker: 'serviceWorker' in navigator,
            pushManager: 'PushManager' in window,
            notifications: 'Notification' in window,
            permissions: Notification.permission,
            browser: this.getBrowserInfo()
        };
        
        console.log('🔍 Browser Support Check:', results);
        return results;
    },
    
    getBrowserInfo() {
        const ua = navigator.userAgent;
        if (ua.includes('Chrome/') && !ua.includes('Edg/')) {
            const match = ua.match(/Chrome\/(\d+)/);
            return `Chrome ${match ? match[1] : 'unknown'}`;
        } else if (ua.includes('Firefox/')) {
            const match = ua.match(/Firefox\/(\d+)/);
            return `Firefox ${match ? match[1] : 'unknown'}`;
        } else if (ua.includes('Safari/') && !ua.includes('Chrome/')) {
            return 'Safari';
        } else if (ua.includes('Edg/')) {
            return 'Edge';
        }
        return 'Unknown';
    },
    
    async checkSubscriptionHealth() {
        try {
            const response = await fetch('/api/notifications/health', {
                credentials: 'include'
            });
            
            if (response.ok) {
                const health = await response.json();
                console.log('🏥 Subscription Health:', health);
                return health;
            } else {
                console.error('❌ Failed to check subscription health:', response.status);
                return null;
            }
        } catch (error) {
            console.error('❌ Error checking subscription health:', error);
            return null;
        }
    },

    async checkDeviceSubscriptions() {
        try {
            const response = await fetch('/api/notifications/devices', {
                credentials: 'include'
            });
            
            if (response.ok) {
                const devices = await response.json();
                console.log('📱 User Devices:', devices);
                return devices;
            } else {
                console.error('❌ Failed to check user devices:', response.status);
                return null;
            }
        } catch (error) {
            console.error('❌ Error checking user devices:', error);
            return null;
        }
    },
    
    async validateAllSubscriptions() {
        try {
            const response = await fetch('/api/notifications/validate-subscriptions', {
                method: 'POST',
                credentials: 'include'
            });
            
            if (response.ok) {
                const result = await response.json();
                console.log('✅ Subscription validation started:', result);
                return result;
            } else {
                console.error('❌ Failed to validate subscriptions:', response.status);
                return null;
            }
        } catch (error) {
            console.error('❌ Error validating subscriptions:', error);
            return null;
        }
    },
    
    async fullDiagnostic() {
        console.log('🧗‍♂️ Starting Climbing App Push Notification Diagnostic...');
        
        const browserSupport = await this.checkBrowserSupport();
        const subscriptionHealth = await this.checkSubscriptionHealth();
        
        const diagnostic = {
            timestamp: new Date().toISOString(),
            browserSupport,
            subscriptionHealth,
            recommendations: []
        };
        
        // Add recommendations based on findings
        if (!browserSupport.serviceWorker) {
            diagnostic.recommendations.push('Your browser does not support Service Workers - notifications require a modern browser');
        }
        
        if (!browserSupport.pushManager) {
            diagnostic.recommendations.push('Your browser does not support Push API - please update your browser');
        }
        
        if (browserSupport.permissions === 'denied') {
            diagnostic.recommendations.push('Notifications are blocked. Please enable them in your browser settings');
        }
        
        if (browserSupport.browser.includes('Chrome') && subscriptionHealth?.current_session_subscriptions === 0) {
            diagnostic.recommendations.push('Chrome detected but no active subscriptions. Try subscribing again or check if notifications are enabled');
        }
        
        if (subscriptionHealth?.browser_breakdown?.['Chrome/Chromium']?.old > 0) {
            diagnostic.recommendations.push('You have old Chrome subscriptions that may be causing 410 errors. Consider running validateAllSubscriptions() to clean them up');
        }
        
        console.log('📊 Full Diagnostic Results:', diagnostic);
        return diagnostic;
    }
};

// Add helper text for users experiencing Chrome 410 errors
console.log('🚨 Experiencing Chrome notification issues?');
console.log('Run: await debugNotifications.fullDiagnostic()');
console.log('Or: await debugNotifications.validateAllSubscriptions()'); 
