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
        this.init();
    }

    checkSupport() {
        return ('serviceWorker' in navigator && 
                'PushManager' in window && 
                'Notification' in window);
    }

    async init() {
        if (!this.isSupported) {
            console.warn('Push notifications not supported in this browser');
            return;
        }

        try {
            // Register service worker
            await this.registerServiceWorker();
            
            // Get VAPID public key
            await this.getVapidPublicKey();
            
            // Check current subscription status
            await this.checkSubscriptionStatus();
            
            console.log('Notifications manager initialized');
        } catch (error) {
            console.error('Failed to initialize notifications manager:', error);
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
        if (!this.registration) return;

        try {
            this.subscription = await this.registration.pushManager.getSubscription();
            this.isEnabled = !!this.subscription;
            
            console.log('Subscription status:', this.isEnabled ? 'enabled' : 'disabled');
            
        } catch (error) {
            console.error('Failed to check subscription status:', error);
        }
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

        if (!this.registration || !this.vapidPublicKey) {
            throw new Error('Service worker or VAPID key not ready');
        }

        try {
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

            // Remove subscription from server
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

        const response = await fetch('/api/notifications/subscribe', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify(subscriptionData)
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
        // For simplicity, we'll get the subscription ID from the server
        try {
            const response = await fetch('/api/notifications/subscriptions', {
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                // This is a simplified approach - in a real app you'd track subscription IDs
                console.log('Would remove subscription from server');
            }
        } catch (error) {
            console.warn('Failed to remove subscription from server:', error);
        }
    }

    async sendTestNotification() {
        if (!this.isEnabled) {
            throw new Error('Notifications not enabled');
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
