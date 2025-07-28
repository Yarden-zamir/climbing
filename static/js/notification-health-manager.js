/**
 * Notification Health Manager
 * Handles aggressive token refresh and subscription validation
 */

class NotificationHealthManager {
    constructor() {
        this.isMonitoring = false;
        this.healthCheckInterval = null;
        this.lastSuccessfulNotification = localStorage.getItem('lastNotificationReceived');
        this.subscriptionStats = this.loadStats();
        
        this.init();
    }

    init() {
        // Start monitoring when page becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                this.performHealthCheck();
                this.startMonitoring();
            } else {
                this.stopMonitoring();
            }
        });

        // Initial health check
        if (!document.hidden) {
            setTimeout(() => this.performHealthCheck(), 2000);
            this.startMonitoring();
        }

        // Listen for notification received events
        this.setupNotificationReceiptTracking();
    }

    startMonitoring() {
        if (this.isMonitoring) return;
        
        this.isMonitoring = true;
        
        // Check every 5 minutes when app is active
        this.healthCheckInterval = setInterval(() => {
            this.performHealthCheck();
        }, 5 * 60 * 1000);

        console.log('Notification health monitoring started');
    }

    stopMonitoring() {
        if (!this.isMonitoring) return;
        
        this.isMonitoring = false;
        
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
            this.healthCheckInterval = null;
        }

        console.log('Notification health monitoring stopped');
    }

    async performHealthCheck() {
        try {
            // Skip health checks when offline
            if (!navigator.onLine) {
                console.log('Offline mode - skipping notification health check');
                return;
            }

            console.log('Performing notification health check...');
            
            // Check if PWA is installed
            if (!window.pwaManager?.isPWAInstalled()) {
                console.log('PWA not installed - skipping health check');
                return;
            }

            // Get current subscription
            const registration = await navigator.serviceWorker.ready;
            let subscription = await registration.pushManager.getSubscription();

            if (!subscription) {
                console.log('No subscription found - user needs to resubscribe');
                this.handleNoSubscription();
                return;
            }

            // Test subscription health
            const isHealthy = await this.testSubscriptionHealth(subscription);
            
            if (!isHealthy) {
                console.log('Subscription unhealthy - refreshing token');
                await this.refreshSubscription(subscription);
            } else {
                console.log('Subscription healthy');
                this.updateStats('health_check_passed');
            }

        } catch (error) {
            console.error('Health check failed:', error);
            this.updateStats('health_check_failed');
        }
    }

    async testSubscriptionHealth(subscription) {
        try {
            // Skip health test when offline
            if (!navigator.onLine) {
                console.log('Offline mode - assuming subscription is healthy');
                return true;
            }

            const response = await fetch('/api/notifications/test-subscription', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    endpoint: subscription.endpoint,
                    keys: {
                        p256dh: this.arrayBufferToBase64(subscription.getKey('p256dh')),
                        auth: this.arrayBufferToBase64(subscription.getKey('auth'))
                    }
                })
            });

            const result = await response.json();
            return result.valid === true;

        } catch (error) {
            // If offline, don't treat network errors as subscription failures
            if (!navigator.onLine) {
                console.log('Network error during health test (offline) - assuming healthy');
                return true;
            }
            
            console.error('Subscription health test failed:', error);
            return false;
        }
    }

    async refreshSubscription(oldSubscription) {
        try {
            // Skip refresh when offline
            if (!navigator.onLine) {
                console.log('Offline mode - skipping subscription refresh');
                return;
            }

            console.log('Refreshing subscription token...');
            
            // Unsubscribe from old subscription
            await oldSubscription.unsubscribe();
            
            // Wait a moment for cleanup
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Create new subscription
            const registration = await navigator.serviceWorker.ready;
            const newSubscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: await this.getVapidPublicKey()
            });

            if (!newSubscription) {
                throw new Error('Failed to create new subscription');
            }

            // Send new subscription to server
            await this.updateSubscriptionOnServer(newSubscription);
            
            console.log('Subscription successfully refreshed');
            this.updateStats('subscription_refreshed');
            
            // Show user notification about refresh
            this.showRefreshNotification();

        } catch (error) {
            console.error('Failed to refresh subscription:', error);
            this.updateStats('refresh_failed');
            this.handleRefreshFailure();
        }
    }

    async updateSubscriptionOnServer(subscription) {
        const deviceId = await this.getDeviceId();
        const deviceInfo = await this.getDeviceInfo();

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
            body: JSON.stringify({
                subscription: subscriptionData,
                deviceInfo: deviceInfo
            })
        });

        if (!response.ok) {
            throw new Error(`Server rejected subscription: ${response.status}`);
        }

        return await response.json();
    }

    async getVapidPublicKey() {
        try {
            const response = await fetch('/api/notifications/vapid-public-key');
            const data = await response.json();
            return data.publicKey;
        } catch (error) {
            console.error('Failed to get VAPID key:', error);
            throw error;
        }
    }

    async getDeviceId() {
        // Get device ID from localStorage or generate new one
        let deviceId = localStorage.getItem('deviceId');
        if (!deviceId) {
            deviceId = 'device_' + Math.random().toString(36).substr(2, 16) + Date.now().toString(36);
            localStorage.setItem('deviceId', deviceId);
        }
        return deviceId;
    }

    async getDeviceInfo() {
        return {
            deviceId: await this.getDeviceId(),
            browserName: this.getBrowserName(),
            platform: navigator.platform || 'unknown',
            userAgent: navigator.userAgent,
            lastActive: new Date().toISOString()
        };
    }

    getBrowserName() {
        const userAgent = navigator.userAgent;
        if (userAgent.includes('Chrome')) return 'Chrome';
        if (userAgent.includes('Firefox')) return 'Firefox';
        if (userAgent.includes('Safari')) return 'Safari';
        if (userAgent.includes('Edge')) return 'Edge';
        return 'Unknown';
    }

    handleNoSubscription() {
        // Show notification to user that they need to re-enable notifications
        this.showResubscribePrompt();
    }

    handleRefreshFailure() {
        // Show error message and prompt manual resubscription
        this.showRefreshErrorPrompt();
    }

    showRefreshNotification() {
        this.showToast('✅ Notifications refreshed automatically', 'success');
    }

    showResubscribePrompt() {
        this.showToast('⚠️ Please re-enable notifications in settings', 'warning', 0);
    }

    showRefreshErrorPrompt() {
        this.showToast('❌ Notification refresh failed. Please re-enable notifications.', 'error', 0);
    }

    showToast(message, type = 'info', duration = 5000) {
        // Remove existing toasts
        const existingToasts = document.querySelectorAll('.notification-health-toast');
        existingToasts.forEach(toast => toast.remove());

        const toast = document.createElement('div');
        toast.className = `notification-health-toast notification-health-toast-${type}`;
        toast.innerHTML = `
            <div class="notification-health-toast-content">
                <span class="notification-health-toast-message">${message}</span>
                <button class="notification-health-toast-close" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;

        document.body.appendChild(toast);

        // Add styles if not already added
        this.addToastStyles();

        // Auto-remove after duration (0 = permanent)
        if (duration > 0) {
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.remove();
                }
            }, duration);
        }
    }

    setupNotificationReceiptTracking() {
        // Listen for service worker messages about received notifications
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                if (event.data.type === 'NOTIFICATION_RECEIVED') {
                    this.recordNotificationReceived();
                }
            });
        }

        // Track page focus as potential notification interaction
        window.addEventListener('focus', () => {
            // If user focused from a notification, consider it received
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('from') === 'notification') {
                this.recordNotificationReceived();
            }
        });
    }

    recordNotificationReceived() {
        const now = Date.now();
        localStorage.setItem('lastNotificationReceived', now.toString());
        this.lastSuccessfulNotification = now.toString();
        this.updateStats('notification_received');
        
        console.log('Notification receipt recorded');
    }

    updateStats(eventType) {
        const now = Date.now();
        this.subscriptionStats.events.push({
            type: eventType,
            timestamp: now
        });

        // Keep only last 100 events
        if (this.subscriptionStats.events.length > 100) {
            this.subscriptionStats.events = this.subscriptionStats.events.slice(-100);
        }

        // Update counters
        if (!this.subscriptionStats.counters[eventType]) {
            this.subscriptionStats.counters[eventType] = 0;
        }
        this.subscriptionStats.counters[eventType]++;

        this.saveStats();
    }

    loadStats() {
        try {
            const stored = localStorage.getItem('notificationHealthStats');
            if (stored) {
                return JSON.parse(stored);
            }
        } catch (error) {
            console.error('Failed to load notification stats:', error);
        }

        return {
            events: [],
            counters: {},
            created: Date.now()
        };
    }

    saveStats() {
        try {
            localStorage.setItem('notificationHealthStats', JSON.stringify(this.subscriptionStats));
        } catch (error) {
            console.error('Failed to save notification stats:', error);
        }
    }

    getHealthReport() {
        const now = Date.now();
        const lastWeek = now - (7 * 24 * 60 * 60 * 1000);
        const recentEvents = this.subscriptionStats.events.filter(e => e.timestamp > lastWeek);
        
        const healthChecks = recentEvents.filter(e => e.type === 'health_check_passed').length;
        const refreshes = recentEvents.filter(e => e.type === 'subscription_refreshed').length;
        const failures = recentEvents.filter(e => e.type === 'health_check_failed' || e.type === 'refresh_failed').length;
        const received = recentEvents.filter(e => e.type === 'notification_received').length;

        const lastNotificationAge = this.lastSuccessfulNotification 
            ? now - parseInt(this.lastSuccessfulNotification)
            : null;

        return {
            healthChecks,
            refreshes,
            failures,
            received,
            lastNotificationAge,
            lastNotificationAgeHours: lastNotificationAge ? Math.round(lastNotificationAge / (60 * 60 * 1000)) : null,
            totalEvents: recentEvents.length,
            reliability: healthChecks > 0 ? ((healthChecks - failures) / healthChecks * 100) : 0
        };
    }

    arrayBufferToBase64(buffer) {
        if (!buffer) return '';
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }

    addToastStyles() {
        if (document.getElementById('notification-health-toast-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'notification-health-toast-styles';
        styles.textContent = `
            .notification-health-toast {
                position: fixed;
                top: 20px;
                left: 20px;
                right: 20px;
                z-index: 10000;
                animation: slideInDown 0.3s ease-out;
            }

            .notification-health-toast-content {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 16px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                font-size: 14px;
                gap: 12px;
            }

            .notification-health-toast-success .notification-health-toast-content {
                background: linear-gradient(135deg, #34a853, #4285f4);
                color: white;
            }

            .notification-health-toast-warning .notification-health-toast-content {
                background: linear-gradient(135deg, #fbbc04, #ea4335);
                color: white;
            }

            .notification-health-toast-error .notification-health-toast-content {
                background: linear-gradient(135deg, #ea4335, #d33b2c);
                color: white;
            }

            .notification-health-toast-info .notification-health-toast-content {
                background: linear-gradient(135deg, #4285f4, #34a853);
                color: white;
            }

            .notification-health-toast-message {
                flex: 1;
                font-weight: 500;
            }

            .notification-health-toast-close {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                cursor: pointer;
                transition: background 0.2s;
            }

            .notification-health-toast-close:hover {
                background: rgba(255,255,255,0.3);
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

            @media (max-width: 480px) {
                .notification-health-toast {
                    top: 10px;
                    left: 10px;
                    right: 10px;
                }
                
                .notification-health-toast-content {
                    flex-direction: column;
                    align-items: stretch;
                    text-align: center;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }
}

// Initialize Notification Health Manager
window.notificationHealthManager = new NotificationHealthManager();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = NotificationHealthManager;
}