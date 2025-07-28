/**
 * Service Worker for Push Notifications
 * Handles background push messages and notification clicks
 */

// Version will be fetched from server during install
let CURRENT_VERSION = 'climbing-app-fallback';
const STATIC_CACHE = () => `climbing-static-${CURRENT_VERSION}`;
const API_CACHE = () => `climbing-api-${CURRENT_VERSION}`;
const IMAGE_CACHE = () => `climbing-images-${CURRENT_VERSION}`;
const NOTIFICATION_TAG = 'climbing-notification';

// Cache strategies
const CACHE_STRATEGIES = {
    CACHE_FIRST: 'cache-first',
    NETWORK_FIRST: 'network-first',
    STALE_WHILE_REVALIDATE: 'stale-while-revalidate',
    NETWORK_ONLY: 'network-only',
    CACHE_ONLY: 'cache-only'
};

// Resources to cache on install
const ESSENTIAL_RESOURCES = [
    '/',
    '/crew',
    '/albums',
    '/memes',
    '/knowledge',
    '/static/css/styles.css',
    '/static/js/pwa-manager.js',
    '/static/js/notification-health-manager.js',
    '/static/js/notifications.js',
    '/static/js/auth.js',
    '/static/js/memes.js',
    '/static/manifest.json',
    '/static/favicon/android-chrome-192x192.png',
    '/static/favicon/android-chrome-512x512.png',
    '/static/favicon/favicon-32x32.png',
    '/static/favicon/favicon.ico'
];

// Fetch version from server
async function fetchCurrentVersion() {
    try {
        // Add cache-busting parameter to ensure fresh version info
        const timestamp = Date.now();
        const response = await fetch(`/api/version?_t=${timestamp}`, {
            cache: 'no-cache'
        });
        if (response.ok) {
            const data = await response.json();
            CURRENT_VERSION = data.version;
            console.log('Service Worker: Fetched version:', CURRENT_VERSION);
            return CURRENT_VERSION;
        }
    } catch (error) {
        console.warn('Service Worker: Failed to fetch version:', error);
    }
    return CURRENT_VERSION;
}

// Install event - cache essential resources
self.addEventListener('install', (event) => {
    console.log('Service Worker: Installing...');
    
    event.waitUntil(
        fetchCurrentVersion().then(() => {
            return Promise.all([
                // Cache essential app shell resources
                caches.open(STATIC_CACHE()).then((cache) => {
                    console.log('Service Worker: Caching essential resources with version:', CURRENT_VERSION);
                    return cache.addAll(ESSENTIAL_RESOURCES).catch((error) => {
                        console.warn('Service Worker: Failed to cache some essential resources:', error);
                        // Cache resources individually to avoid complete failure
                        return Promise.allSettled(
                            ESSENTIAL_RESOURCES.map(url => 
                                cache.add(url).catch(err => 
                                    console.warn(`Failed to cache ${url}:`, err)
                                )
                            )
                        );
                    });
                }),
                // Initialize other caches
                caches.open(API_CACHE()),
                caches.open(IMAGE_CACHE())
            ]);
        })
    );
    
    // Force activate immediately
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('Service Worker: Activating...');
    
    const expectedCaches = [STATIC_CACHE(), API_CACHE(), IMAGE_CACHE()];
    
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (!expectedCaches.includes(cacheName)) {
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

// Fetch event - handle all network requests with caching strategies
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);
    
    // Skip non-GET requests for caching
    if (request.method !== 'GET') {
        return;
    }
    
    // Skip chrome-extension and other protocol requests
    if (!url.protocol.startsWith('http')) {
        return;
    }
    
    // Route requests based on URL patterns
    if (url.pathname.startsWith('/api/')) {
        // Special handling for version endpoint - always fetch fresh
        if (url.pathname === '/api/version') {
            event.respondWith(fetch(request, { cache: 'no-cache' }));
        } else {
            // Other API requests - network first with cache fallback
            event.respondWith(handleApiRequest(request));
        }
    } else if (url.pathname === '/static/manifest.json') {
        // Always fetch manifest fresh to get updated theme colors, etc.
        event.respondWith(fetch(request, { cache: 'no-cache' }));
    } else if (url.pathname.startsWith('/static/') || url.pathname.includes('.css') || url.pathname.includes('.js')) {
        // Static assets - cache first
        event.respondWith(handleStaticAsset(request));
    } else if (url.pathname.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i)) {
        // Images - stale while revalidate
        event.respondWith(handleImageRequest(request));
    } else {
        // HTML pages - network first with offline fallback
        event.respondWith(handlePageRequest(request));
    }
});

/**
 * Handle API requests with network-first strategy
 */
async function handleApiRequest(request) {
    const cacheKey = request.url;
    
    try {
        // Try network first
        const networkResponse = await fetch(request);
        
        if (networkResponse.ok) {
            // Cache successful responses (exclude auth-related endpoints)
            if (!request.url.includes('/auth/') && !request.url.includes('/login')) {
                const cache = await caches.open(API_CACHE());
                // Clone response before caching
                await cache.put(cacheKey, networkResponse.clone());
                console.log('Service Worker: Cached API response:', cacheKey);
            }
        }
        
        return networkResponse;
    } catch (error) {
        console.log('Service Worker: Network failed for API request, trying cache:', cacheKey);
        
        // Network failed, try cache
        const cachedResponse = await caches.match(cacheKey);
        if (cachedResponse) {
            console.log('Service Worker: Served from cache:', cacheKey);
            // Add a header to indicate it's from cache
            const response = cachedResponse.clone();
            response.headers.set('X-Served-From', 'cache');
            return response;
        }
        
        // No cache available, return network error
        throw error;
    }
}

/**
 * Handle static assets with cache-first strategy
 */
async function handleStaticAsset(request) {
    const cache = await caches.open(STATIC_CACHE());
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse) {
        console.log('Service Worker: Served static asset from cache:', request.url);
        return cachedResponse;
    }
    
    // Not in cache, fetch from network and cache
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            await cache.put(request, networkResponse.clone());
            console.log('Service Worker: Cached static asset:', request.url);
        }
        return networkResponse;
    } catch (error) {
        console.error('Service Worker: Failed to fetch static asset:', request.url, error);
        throw error;
    }
}

/**
 * Handle image requests with stale-while-revalidate strategy
 */
async function handleImageRequest(request) {
    const cache = await caches.open(IMAGE_CACHE());
    const cachedResponse = await cache.match(request);
    
    // Always return cached version immediately if available
    if (cachedResponse) {
        console.log('Service Worker: Served image from cache:', request.url);
        
        // Update cache in background (stale-while-revalidate)
        fetch(request).then(async (networkResponse) => {
            if (networkResponse.ok) {
                await cache.put(request, networkResponse.clone());
                console.log('Service Worker: Updated cached image:', request.url);
            }
        }).catch((error) => {
            console.log('Service Worker: Background image update failed:', request.url, error);
        });
        
        return cachedResponse;
    }
    
    // Not in cache, fetch from network and cache
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            await cache.put(request, networkResponse.clone());
            console.log('Service Worker: Cached new image:', request.url);
        }
        return networkResponse;
    } catch (error) {
        console.error('Service Worker: Failed to fetch image:', request.url, error);
        throw error;
    }
}

/**
 * Handle page requests with network-first and offline fallback
 */
async function handlePageRequest(request) {
    try {
        // Try network first
        const networkResponse = await fetch(request);
        
        if (networkResponse.ok) {
            // Cache successful page responses
            const cache = await caches.open(STATIC_CACHE());
            await cache.put(request, networkResponse.clone());
            console.log('Service Worker: Cached page:', request.url);
        }
        
        return networkResponse;
    } catch (error) {
        console.log('Service Worker: Network failed for page request, trying cache:', request.url);
        
        // Network failed, try cache
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            console.log('Service Worker: Served page from cache:', request.url);
            return cachedResponse;
        }
        
        // No cache available, try to serve the main page as fallback
        const fallbackResponse = await caches.match('/');
        if (fallbackResponse) {
            console.log('Service Worker: Served fallback page for:', request.url);
            return fallbackResponse;
        }
        
        // No fallback available, return error
        throw error;
    }
}

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
            
            // Also send notification received event for health tracking
            client.postMessage({
                type: 'NOTIFICATION_RECEIVED',
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
    } else if (event.tag === 'offline-requests-sync') {
        event.waitUntil(processOfflineQueue());
    }
});

/**
 * Store failed requests for later retry
 */
async function storeOfflineRequest(request, data = null) {
    try {
        const offlineRequest = {
            url: request.url,
            method: request.method,
            headers: Object.fromEntries(request.headers.entries()),
            body: data || (await request.clone().text()),
            timestamp: Date.now()
        };
        
        await storeValue('offlineQueue', await getOfflineQueue().then(queue => {
            queue.push(offlineRequest);
            return queue;
        }));
        
        console.log('Service Worker: Stored offline request:', request.url);
        
        // Register for background sync
        if ('serviceWorker' in self && 'sync' in self.registration) {
            await self.registration.sync.register('offline-requests-sync');
        }
    } catch (error) {
        console.error('Service Worker: Failed to store offline request:', error);
    }
}

/**
 * Get offline request queue
 */
async function getOfflineQueue() {
    try {
        const queue = await getStoredValue('offlineQueue');
        return queue || [];
    } catch (error) {
        console.error('Service Worker: Failed to get offline queue:', error);
        return [];
    }
}

/**
 * Process offline request queue
 */
async function processOfflineQueue() {
    try {
        const queue = await getOfflineQueue();
        console.log(`Service Worker: Processing ${queue.length} offline requests`);
        
        const processedRequests = [];
        const failedRequests = [];
        
        for (const offlineRequest of queue) {
            try {
                const request = new Request(offlineRequest.url, {
                    method: offlineRequest.method,
                    headers: offlineRequest.headers,
                    body: offlineRequest.method !== 'GET' ? offlineRequest.body : null
                });
                
                const response = await fetch(request);
                
                if (response.ok) {
                    console.log('Service Worker: Successfully processed offline request:', offlineRequest.url);
                    processedRequests.push(offlineRequest);
                } else {
                    console.warn('Service Worker: Offline request failed with status:', response.status, offlineRequest.url);
                    // Keep in queue for retry if it's been less than 24 hours
                    if (Date.now() - offlineRequest.timestamp < 24 * 60 * 60 * 1000) {
                        failedRequests.push(offlineRequest);
                    }
                }
            } catch (error) {
                console.error('Service Worker: Error processing offline request:', error, offlineRequest.url);
                // Keep in queue for retry if it's been less than 24 hours
                if (Date.now() - offlineRequest.timestamp < 24 * 60 * 60 * 1000) {
                    failedRequests.push(offlineRequest);
                }
            }
        }
        
        // Update queue with only failed requests
        await storeValue('offlineQueue', failedRequests);
        
        // Notify clients about processed requests
        if (processedRequests.length > 0) {
            const clients = await self.clients.matchAll();
            clients.forEach(client => {
                client.postMessage({
                    type: 'OFFLINE_REQUESTS_PROCESSED',
                    count: processedRequests.length,
                    requests: processedRequests,
                    timestamp: Date.now()
                });
            });
        }
        
    } catch (error) {
        console.error('Service Worker: Failed to process offline queue:', error);
    }
}

/**
 * Clean up old cache entries to prevent storage bloat
 */
async function cleanupCaches() {
    try {
        const cacheConfigs = [
            { name: STATIC_CACHE(), maxAge: 7 * 24 * 60 * 60 * 1000 }, // 7 days
            { name: API_CACHE(), maxAge: 24 * 60 * 60 * 1000 },       // 1 day
            { name: IMAGE_CACHE(), maxAge: 30 * 24 * 60 * 60 * 1000 } // 30 days
        ];
        
        for (const cacheConfig of cacheConfigs) {
            const cache = await caches.open(cacheConfig.name);
            const requests = await cache.keys();
            
            for (const request of requests) {
                const response = await cache.match(request);
                if (response) {
                    const dateHeader = response.headers.get('date');
                    if (dateHeader) {
                        const cacheDate = new Date(dateHeader);
                        const age = Date.now() - cacheDate.getTime();
                        
                        if (age > cacheConfig.maxAge) {
                            await cache.delete(request);
                            console.log(`Service Worker: Cleaned up old cache entry: ${request.url}`);
                        }
                    }
                }
            }
        }
    } catch (error) {
        console.error('Service Worker: Cache cleanup failed:', error);
    }
}

/**
 * Get cache statistics
 */
async function getCacheStats() {
    try {
        const stats = {};
        const cacheNames = [STATIC_CACHE(), API_CACHE(), IMAGE_CACHE()];
        
        for (const cacheName of cacheNames) {
            const cache = await caches.open(cacheName);
            const requests = await cache.keys();
            stats[cacheName] = {
                count: requests.length,
                urls: requests.map(req => req.url)
            };
        }
        
        const offlineQueue = await getOfflineQueue();
        stats.offlineQueue = {
            count: offlineQueue.length,
            requests: offlineQueue
        };
        
        return stats;
    } catch (error) {
        console.error('Service Worker: Failed to get cache stats:', error);
        return {};
    }
}

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
            version: CURRENT_VERSION,
            timestamp: Date.now()
        });
    }
    
    if (event.data && event.data.type === 'GET_CACHE_STATS') {
        getCacheStats().then(stats => {
            event.ports[0].postMessage({
                type: 'CACHE_STATS',
                stats: stats,
                timestamp: Date.now()
            });
        }).catch(error => {
            event.ports[0].postMessage({
                type: 'CACHE_STATS_ERROR',
                error: error.message,
                timestamp: Date.now()
            });
        });
    }
    
    if (event.data && event.data.type === 'CLEANUP_CACHES') {
        cleanupCaches().then(() => {
            event.ports[0].postMessage({
                type: 'CACHE_CLEANUP_COMPLETE',
                timestamp: Date.now()
            });
        }).catch(error => {
            event.ports[0].postMessage({
                type: 'CACHE_CLEANUP_ERROR',
                error: error.message,
                timestamp: Date.now()
            });
        });
    }
    
    if (event.data && event.data.type === 'CLEAR_OFFLINE_QUEUE') {
        storeValue('offlineQueue', []).then(() => {
            event.ports[0].postMessage({
                type: 'OFFLINE_QUEUE_CLEARED',
                timestamp: Date.now()
            });
        }).catch(error => {
            event.ports[0].postMessage({
                type: 'OFFLINE_QUEUE_CLEAR_ERROR',
                error: error.message,
                timestamp: Date.now()
            });
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
