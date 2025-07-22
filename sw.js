/**
 * Service Worker for Push Notifications
 * Handles background push messages and notification clicks
 */

const CACHE_NAME = 'climbing-app-v1';
const NOTIFICATION_TAG = 'climbing-notification';

// Install event - cache essential resources
self.addEventListener('install', (event) => {
    console.log('Service Worker: Installing...');
    
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('Service Worker: Caching essential resources');
            return cache.addAll([
                '/',
                '/static/favicon/android-chrome-192x192.png',
                '/static/favicon/favicon-32x32.png',
                '/static/css/styles.css'
            ]).catch((error) => {
                console.warn('Service Worker: Failed to cache some resources:', error);
            });
        })
    );
    
    // Force activate immediately
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('Service Worker: Activating...');
    
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Service Worker: Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        }).then(() => {
            // Take control of all open pages
            return self.clients.claim();
        })
    );
});

// Push event - handle incoming push notifications
self.addEventListener('push', (event) => {
    console.log('🚨 Service Worker: Push event received!');
    console.log('Service Worker: Event details:', {
        hasData: !!event.data,
        dataType: event.data ? typeof event.data : 'no data',
        timestamp: new Date().toISOString()
    });
    
    // Try multiple ways to read the data
    let notificationData = {
        title: 'Climbing App',
        body: 'You have a new notification',
        icon: '/static/favicon/android-chrome-192x192.png',
        badge: '/static/favicon/favicon-32x32.png',
        tag: NOTIFICATION_TAG,
        requireInteraction: false,
        data: {
            url: '/'
        }
    };
    
    // Parse push data if available
    if (event.data) {
        console.log('Service Worker: Raw event.data object:', event.data);
        
        // Try different parsing methods
        try {
            const pushData = event.data.json();
            console.log('Service Worker: ✅ Successfully parsed as JSON:', pushData);
            notificationData = {
                ...notificationData,
                ...pushData
            };
        } catch (jsonError) {
            console.error('Service Worker: ❌ Failed to parse as JSON:', jsonError);
            
            // Try as text
            try {
                const textData = event.data.text();
                console.log('Service Worker: Text data received:', textData);
                if (textData) {
                    // Try to parse the text as JSON
                    try {
                        const parsedText = JSON.parse(textData);
                        console.log('Service Worker: ✅ Text parsed as JSON:', parsedText);
                        notificationData = {
                            ...notificationData,
                            ...parsedText
                        };
                    } catch (textJsonError) {
                        console.log('Service Worker: Text is not JSON, using as body');
                        notificationData.body = textData;
                    }
                }
            } catch (textError) {
                console.error('Service Worker: ❌ Failed to parse as text:', textError);
            }
            
            // Try arrayBuffer as last resort
            try {
                const arrayBuffer = event.data.arrayBuffer();
                const decoder = new TextDecoder();
                const decodedText = decoder.decode(arrayBuffer);
                console.log('Service Worker: ArrayBuffer decoded text:', decodedText);
                if (decodedText) {
                    try {
                        const parsedBuffer = JSON.parse(decodedText);
                        console.log('Service Worker: ✅ ArrayBuffer parsed as JSON:', parsedBuffer);
                        notificationData = {
                            ...notificationData,
                            ...parsedBuffer
                        };
                    } catch (bufferJsonError) {
                        console.log('Service Worker: ArrayBuffer text is not JSON');
                        notificationData.body = decodedText;
                    }
                }
            } catch (bufferError) {
                console.error('Service Worker: ❌ Failed to parse as ArrayBuffer:', bufferError);
            }
        }
    } else {
        console.warn('Service Worker: ⚠️ No push data received - this might be the issue!');
    }
    
    console.log('Service Worker: Final notification data to display:', notificationData);
    
    // Show notification with detailed error handling
    event.waitUntil(
        showNotificationWithLogging(notificationData)
    );
});

async function showNotificationWithLogging(notificationData) {
    console.log('Service Worker: 📢 showNotificationWithLogging called with:', notificationData);
    
    // Notify clients that we received a push
    try {
        const clients = await self.clients.matchAll();
        clients.forEach(client => {
            client.postMessage({
                type: 'PUSH_RECEIVED',
                data: notificationData,
                timestamp: Date.now()
            });
        });
    } catch (clientError) {
        console.error('Service Worker: Failed to notify clients:', clientError);
    }
    
    try {
        const result = await showNotification(notificationData);
        console.log('Service Worker: ✅ showNotification completed successfully');
        
        // Notify clients of success
        try {
            const clients = await self.clients.matchAll();
            clients.forEach(client => {
                client.postMessage({
                    type: 'NOTIFICATION_SHOWN',
                    data: notificationData,
                    timestamp: Date.now()
                });
            });
        } catch (clientError) {
            console.error('Service Worker: Failed to notify clients of success:', clientError);
        }
        
        return result;
    } catch (error) {
        console.error('Service Worker: ❌ showNotification failed:', error);
        
        // Notify clients of error
        try {
            const clients = await self.clients.matchAll();
            clients.forEach(client => {
                client.postMessage({
                    type: 'NOTIFICATION_ERROR',
                    error: error.message,
                    data: notificationData,
                    timestamp: Date.now()
                });
            });
        } catch (clientError) {
            console.error('Service Worker: Failed to notify clients of error:', clientError);
        }
        
        throw error;
    }
}

// Notification click event - handle user interactions
self.addEventListener('notificationclick', (event) => {
    console.log('Service Worker: Notification clicked');
    
    // Close the notification
    event.notification.close();
    
    let urlToOpen = event.notification.data?.url || '/';
    let actionHandled = false;
    
    // Handle action button clicks
    if (event.action) {
        console.log('Service Worker: Action clicked:', event.action);
        
        // Find the corresponding action from the notification
        const actions = event.notification.actions || [];
        const clickedAction = actions.find(action => action.action === event.action);
        
        if (clickedAction) {
            console.log('Service Worker: Processing action:', clickedAction);
            
            // Check if action has custom URL in the original notification data
            const originalActions = event.notification.data?.originalActions || 
                                   event.notification.data?.webNotificationFeatures?.originalActions || [];
            const originalAction = originalActions.find(action => action.action === event.action);
            
            if (originalAction && originalAction.data && originalAction.data.url) {
                urlToOpen = originalAction.data.url;
                console.log('Service Worker: Using action-specific URL:', urlToOpen);
            }
            
            // Handle special action types
            switch (event.action) {
                case 'dismiss':
                case 'action_2':
                    // Don't open any URL for dismiss actions
                    if (clickedAction.title.toLowerCase().includes('dismiss') || 
                        clickedAction.title.toLowerCase().includes('close')) {
                        console.log('Service Worker: Dismiss action - not opening URL');
                        actionHandled = true;
                        return;
                    }
                    break;
                case 'view':
                case 'action_1':
                    // Default behavior for view actions
                    break;
                default:
                    console.log('Service Worker: Unknown action type:', event.action);
            }
        }
    }
    
    // Only open URL if action wasn't a dismiss-type action
    if (!actionHandled) {
        const fullUrl = new URL(urlToOpen, self.location.origin).href;
        console.log('Service Worker: Opening URL:', fullUrl);
        
        // Open or focus the app
        event.waitUntil(
            handleNotificationClick(fullUrl)
        );
    }
});

// Push subscription change event - handle automatic subscription replacements
self.addEventListener('pushsubscriptionchange', (event) => {
    console.log('Service Worker: Push subscription changed');
    
    // Handle subscription replacement
    event.waitUntil(
        handlePushSubscriptionChange(event)
    );
});

// Background sync (for offline actions)
self.addEventListener('sync', (event) => {
    console.log('Service Worker: Background sync triggered:', event.tag);
    
    if (event.tag === 'background-notification-sync') {
        event.waitUntil(handleBackgroundSync());
    }
});

/**
 * Show a notification with proper error handling
 */
async function showNotification(notificationData) {
    try {
        console.log('Service Worker: Attempting to show notification with data:', notificationData);
        
        // Check if we have permission
        if (Notification.permission !== 'granted') {
            console.error('Service Worker: No notification permission - current permission:', Notification.permission);
            return;
        }
        
        // Validate required fields
        if (!notificationData.title) {
            console.warn('Service Worker: No title provided, using default');
            notificationData.title = 'Climbing App';
        }
        
        if (!notificationData.body) {
            console.warn('Service Worker: No body provided, using default');
            notificationData.body = 'You have a new notification';
        }
        
        // Extract advanced features from data section (for FCM compatibility)
        const webFeatures = notificationData.data?.webNotificationFeatures || {};
        
        // Prepare comprehensive notification options
        const options = {
            body: notificationData.body,
            icon: notificationData.data?.customIcon || notificationData.icon || '/static/favicon/android-chrome-192x192.png',
            badge: notificationData.badge || '/static/favicon/favicon-32x32.png',
            tag: notificationData.tag || NOTIFICATION_TAG,
            requireInteraction: notificationData.requireInteraction || false,
            data: notificationData.data || {},
            silent: notificationData.silent || false,
            renotify: notificationData.renotify || false
        };

        // Add optional visual content
        if (notificationData.data?.customImage) {
            // Use custom uploaded image from data section
            options.image = notificationData.data.customImage;
        } else if (notificationData.image) {
            // Use regular image URL
            options.image = notificationData.image;
        }

        // Add internationalization options from advanced features
        if (webFeatures.lang) {
            options.lang = webFeatures.lang;
        }
        if (webFeatures.dir) {
            options.dir = webFeatures.dir;
        }

        // Add custom timestamp from advanced features
        if (webFeatures.timestamp) {
            options.timestamp = webFeatures.timestamp;
        }

        // Add vibration pattern from advanced features (mobile devices)
        if (webFeatures.vibrate && Array.isArray(webFeatures.vibrate) && webFeatures.vibrate.length > 0) {
            options.vibrate = webFeatures.vibrate;
        } else {
            // Default vibration pattern
            options.vibrate = [200, 100, 200];
        }
        
        // Add action buttons from advanced features (limit to 2 per Web API spec)
        if (webFeatures.actions && Array.isArray(webFeatures.actions) && webFeatures.actions.length > 0) {
            options.actions = webFeatures.actions.slice(0, 2).map(action => {
                const actionObj = {
                    action: action.action,
                    title: action.title
                };
                
                // Add icon if provided (limited browser support)
                if (action.icon) {
                    actionObj.icon = action.icon;
                }
                
                return actionObj;
            });
            
            // Store original actions with URLs in data for click handling
            options.data.originalActions = webFeatures.originalActions;
        }
        
        console.log('Service Worker: Notification options:', options);
        
        // Show the notification
        await self.registration.showNotification(notificationData.title, options);
        console.log('Service Worker: Notification shown successfully');
        
        // Also log to help with debugging
        console.log('Service Worker: Active clients count:', (await self.clients.matchAll()).length);
        
    } catch (error) {
        console.error('Service Worker: Failed to show notification:', error);
        console.error('Service Worker: Error details:', {
            name: error.name,
            message: error.message,
            stack: error.stack
        });
        
        // Try to show a basic fallback notification
        try {
            await self.registration.showNotification('Climbing App', {
                body: 'New notification (fallback)',
                icon: '/static/favicon/android-chrome-192x192.png',
                tag: 'fallback'
            });
            console.log('Service Worker: Fallback notification shown');
        } catch (fallbackError) {
            console.error('Service Worker: Even fallback notification failed:', fallbackError);
        }
    }
}

/**
 * Handle notification click - open or focus the app
 */
async function handleNotificationClick(urlToOpen) {
    try {
        // Get all open clients (tabs/windows)
        const clients = await self.clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        });
        
        // Check if we already have the app open
        for (const client of clients) {
            if (client.url.startsWith(self.location.origin)) {
                // Focus existing window and navigate if needed
                await client.focus();
                
                // Navigate to the specific URL if different
                if (client.url !== urlToOpen) {
                    return client.navigate(urlToOpen);
                }
                
                return;
            }
        }
        
        // No existing window found, open a new one
        return self.clients.openWindow(urlToOpen);
        
    } catch (error) {
        console.error('Service Worker: Failed to handle notification click:', error);
        // Fallback: just try to open a new window
        return self.clients.openWindow(urlToOpen);
    }
}

/**
 * Handle background sync for offline actions
 */
async function handleBackgroundSync() {
    try {
        console.log('Service Worker: Handling background sync');
        
        // Here you could implement offline notification queueing
        // For now, we'll just log that sync happened
        
        // Send a message to all open clients
        const clients = await self.clients.matchAll();
        clients.forEach(client => {
            client.postMessage({
                type: 'BACKGROUND_SYNC_COMPLETE',
                timestamp: Date.now()
            });
        });
        
    } catch (error) {
        console.error('Service Worker: Background sync failed:', error);
    }
}

/**
 * Handle push subscription change - replace expired/changed subscription
 */
async function handlePushSubscriptionChange(event) {
    try {
        console.log('Service Worker: Handling push subscription change');
        
        const oldSubscription = event.oldSubscription;
        if (!oldSubscription) {
            console.warn('Service Worker: No old subscription provided');
            return;
        }
        
        // Get a new subscription using the same options as the old one
        const newSubscription = await self.registration.pushManager.subscribe(
            oldSubscription.options || {
                userVisibleOnly: true,
                applicationServerKey: oldSubscription.options?.applicationServerKey
            }
        );
        
        if (!newSubscription) {
            console.error('Service Worker: Failed to get new push subscription');
            return;
        }
        
        // Prepare subscription data for the API
        const oldSubscriptionData = {
            endpoint: oldSubscription.endpoint,
            keys: {
                p256dh: arrayBufferToBase64(oldSubscription.getKey('p256dh')),
                auth: arrayBufferToBase64(oldSubscription.getKey('auth'))
            },
            expirationTime: oldSubscription.expirationTime
        };
        
        const newSubscriptionData = {
            endpoint: newSubscription.endpoint,
            keys: {
                p256dh: arrayBufferToBase64(newSubscription.getKey('p256dh')),
                auth: arrayBufferToBase64(newSubscription.getKey('auth'))
            },
            expirationTime: newSubscription.expirationTime
        };
        
        // Get device info (simplified version for service worker)
        const deviceInfo = await getDeviceInfo();
        
        // Send replacement request to server
        const response = await fetch('/api/notifications/replace-subscription', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                oldSubscription: oldSubscriptionData,
                newSubscription: newSubscriptionData,
                deviceInfo: deviceInfo
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            console.log('Service Worker: Successfully replaced push subscription:', result.new_subscription_id);
            
            // Notify clients about the subscription change
            const clients = await self.clients.matchAll();
            clients.forEach(client => {
                client.postMessage({
                    type: 'PUSH_SUBSCRIPTION_REPLACED',
                    oldSubscription: oldSubscriptionData,
                    newSubscription: newSubscriptionData,
                    newSubscriptionId: result.new_subscription_id,
                    timestamp: Date.now()
                });
            });
        } else {
            console.error('Service Worker: Failed to replace push subscription:', response.status, response.statusText);
        }
        
    } catch (error) {
        console.error('Service Worker: Error handling push subscription change:', error);
    }
}

/**
 * Convert ArrayBuffer to base64 string
 */
function arrayBufferToBase64(buffer) {
    if (!buffer) return '';
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

/**
 * Get simplified device info for service worker context
 */
async function getDeviceInfo() {
    // In service worker context, we have limited access to device info
    // We'll create a simplified version
    return {
        deviceId: await getOrCreateDeviceId(),
        browserName: getBrowserName(),
        platform: navigator.platform || 'unknown',
        userAgent: navigator.userAgent,
        lastActive: new Date().toISOString()
    };
}

/**
 * Get or create a persistent device ID
 */
async function getOrCreateDeviceId() {
    try {
        // Try to get existing device ID from storage
        const existingId = await getStoredValue('deviceId');
        if (existingId) {
            return existingId;
        }
        
        // Generate new device ID
        const newDeviceId = generateDeviceId();
        await storeValue('deviceId', newDeviceId);
        return newDeviceId;
    } catch (error) {
        console.error('Service Worker: Error managing device ID:', error);
        return generateDeviceId(); // Fallback to ephemeral ID
    }
}

/**
 * Generate a unique device ID
 */
function generateDeviceId() {
    return 'device_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
}

/**
 * Get browser name from user agent
 */
function getBrowserName() {
    const userAgent = navigator.userAgent;
    if (userAgent.includes('Chrome')) return 'Chrome';
    if (userAgent.includes('Firefox')) return 'Firefox';
    if (userAgent.includes('Safari')) return 'Safari';
    if (userAgent.includes('Edge')) return 'Edge';
    return 'Unknown';
}

/**
 * Store a value in IndexedDB (service worker compatible)
 */
async function storeValue(key, value) {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('serviceWorkerStorage', 1);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['keyValue'], 'readwrite');
            const store = transaction.objectStore('keyValue');
            const putRequest = store.put({ key, value });
            
            putRequest.onerror = () => reject(putRequest.error);
            putRequest.onsuccess = () => resolve();
        };
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('keyValue')) {
                db.createObjectStore('keyValue', { keyPath: 'key' });
            }
        };
    });
}

/**
 * Get a value from IndexedDB (service worker compatible)
 */
async function getStoredValue(key) {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('serviceWorkerStorage', 1);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['keyValue'], 'readonly');
            const store = transaction.objectStore('keyValue');
            const getRequest = store.get(key);
            
            getRequest.onerror = () => reject(getRequest.error);
            getRequest.onsuccess = () => {
                resolve(getRequest.result ? getRequest.result.value : null);
            };
        };
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('keyValue')) {
                db.createObjectStore('keyValue', { keyPath: 'key' });
            }
        };
    });
}

// Handle messages from the main thread
self.addEventListener('message', (event) => {
    console.log('Service Worker: Message received:', event.data);
    
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
    
    if (event.data && event.data.type === 'GET_VERSION') {
        event.ports[0].postMessage({
            version: CACHE_NAME,
            timestamp: Date.now()
        });
    }
});

// Error handling
self.addEventListener('error', (event) => {
    console.error('Service Worker: Error occurred:', event.error);
});

self.addEventListener('unhandledrejection', (event) => {
    console.error('Service Worker: Unhandled promise rejection:', event.reason);
});

console.log('Service Worker: Script loaded and event listeners registered'); 
