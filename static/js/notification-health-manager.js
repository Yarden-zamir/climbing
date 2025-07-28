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
        this.lastHealthCheckTime = 0;
        
        this.init();
    }

    init() {
        // Start monitoring when page becomes visible
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                // Only perform health check if we haven't done one recently
                const lastCheckTime = this.lastHealthCheckTime || 0;
                const timeSinceLastCheck = Date.now() - lastCheckTime;
                
                // Only check if it's been more than 30 seconds since last check
                if (timeSinceLastCheck > 30000) {
                    this.performHealthCheck();
                }
                this.startMonitoring();
            } else {
                this.stopMonitoring();
            }
        });

        // Initial health check (only when online)
        if (!document.hidden && navigator.onLine) {
            setTimeout(() => {
                if (navigator.onLine) {
                    this.performHealthCheck();
                }
            }, 2000);
            this.startMonitoring();
        }

        // Listen for notification received events
        this.setupNotificationReceiptTracking();
        
        // Listen for online/offline events
        window.addEventListener('online', () => {
            console.log('NotificationHealthManager: Back online - starting monitoring');
            if (!document.hidden) {
                setTimeout(() => {
                    if (navigator.onLine) {
                        this.performHealthCheck();
                    }
                }, 2000);
                this.startMonitoring();
            }
        });
        
        window.addEventListener('offline', () => {
            console.log('NotificationHealthManager: Going offline - stopping monitoring');
            this.stopMonitoring();
        });
    }

    startMonitoring() {
        if (this.isMonitoring) return;
        
        // Don't start monitoring when offline
        if (!navigator.onLine) {
            console.log('Offline mode - not starting notification health monitoring');
            return;
        }
        
        this.isMonitoring = true;
        
        // Check every 5 minutes when app is active
        this.healthCheckInterval = setInterval(() => {
            // Skip health check if offline
            if (!navigator.onLine) {
                console.log('Offline during interval - skipping health check');
                return;
            }
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

            // Track when we perform health checks
            this.lastHealthCheckTime = Date.now();
            
            // Add stack trace to see where health check is being called from
            console.log('Performing notification health check...', new Error().stack.split('\n')[2].trim());
            
            // Check if PWA is installed
            if (!window.pwaManager?.isPWAInstalled()) {
                console.log('PWA not installed - skipping health check');
                return;
            }

            // Get current subscription
            const registration = await navigator.serviceWorker.ready;
            let subscription = await registration.pushManager.getSubscription();

            if (!subscription) {
                console.log('No subscription found - notifications not enabled');
                
                // Check if notification permission was granted but subscription is missing
                const permission = Notification.permission;
                
                if (permission === 'granted' && this.hadPreviousSubscription()) {
                    // User had notifications and permission is still granted - this is unexpected
                    console.log('Permission granted but subscription missing - user needs to resubscribe');
                    this.handleNoSubscription();
                } else if (permission === 'denied') {
                    console.log('Notification permission denied - user must re-enable in browser settings');
                    // Don't show prompt - user explicitly denied
                } else {
                    console.log('User never enabled notifications or permission not granted - skipping prompt');
                }
                return;
            }

            // Mark that we have an active subscription
            this.markSubscriptionActive();

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
        // Skip server update when offline
        if (!navigator.onLine) {
            console.log('Offline mode - skipping subscription server update');
            throw new Error('Cannot update subscription while offline');
        }

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
        // Skip VAPID key fetch when offline
        if (!navigator.onLine) {
            console.log('Offline mode - skipping VAPID key fetch');
            throw new Error('Cannot fetch VAPID key while offline');
        }

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

    hadPreviousSubscription() {
        // Check if user had a subscription in the past
        const lastSubscriptionTime = localStorage.getItem('lastNotificationSubscription');
        const hadSubscription = localStorage.getItem('hadNotificationSubscription') === 'true';
        
        // If we have evidence of previous subscription
        if (hadSubscription || lastSubscriptionTime) {
            // Check if it was recent (within last 30 days)
            if (lastSubscriptionTime) {
                const daysSinceLastSubscription = (Date.now() - parseInt(lastSubscriptionTime)) / (1000 * 60 * 60 * 24);
                return daysSinceLastSubscription < 30;
            }
            return true;
        }
        
        return false;
    }

    markSubscriptionActive() {
        // Call this whenever we confirm an active subscription
        localStorage.setItem('hadNotificationSubscription', 'true');
        localStorage.setItem('lastNotificationSubscription', Date.now().toString());
    }

    handleNoSubscription() {
        // Don't show resubscribe prompts when offline
        if (!navigator.onLine) {
            console.log('Offline mode - skipping resubscribe prompt');
            return;
        }
        
        // Show notification to user that they need to re-enable notifications
        this.showResubscribePrompt();
    }

    handleRefreshFailure() {
        // Don't show error messages when offline
        if (!navigator.onLine) {
            console.log('Offline mode - skipping refresh failure notification');
            return;
        }
        
        // Show error message and prompt manual resubscription
        this.showRefreshErrorPrompt();
    }

    showRefreshNotification() {
        this.showToast('✅ Notifications refreshed automatically', 'success');
    }

    showResubscribePrompt() {
        // Double-check offline status before showing toast
        if (!navigator.onLine) {
            console.log('showResubscribePrompt called but offline - skipping');
            return;
        }

        // Check if we've shown this recently (within last hour)
        const lastPromptTime = localStorage.getItem('lastResubscribePromptTime');
        if (lastPromptTime) {
            const hoursSinceLastPrompt = (Date.now() - parseInt(lastPromptTime)) / (1000 * 60 * 60);
            if (hoursSinceLastPrompt < 1) {
                console.log('Resubscribe prompt shown recently - skipping');
                return;
            }
        }

        // Update last prompt time
        localStorage.setItem('lastResubscribePromptTime', Date.now().toString());
        
        this.showToast('⚠️ Please re-enable notifications in settings', 'warning', 0);
    }

    showRefreshErrorPrompt() {
        // Double-check offline status before showing toast
        if (!navigator.onLine) {
            console.log('showRefreshErrorPrompt called but offline - skipping');
            return;
        }
        this.showToast('❌ Notification refresh failed. Please re-enable notifications.', 'error', 0);
    }

    showToast(message, type = 'info', duration = 5000) {
        // Final defensive check - don't show any notification-related toasts when offline
        if (!navigator.onLine && (message.includes('notification') || message.includes('Notification'))) {
            console.log(`Toast blocked (offline): ${message}`);
            return;
        }

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