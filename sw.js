/**
 * Simple Service Worker with Stale-While-Revalidate for HTML and Network-First for API
 * No version tracking, just smart caching strategies
 */

const CACHE_NAME = 'climbing-app-cache';
const NOTIFICATION_TAG = 'climbing-notification';

// Resources to cache on install (static assets only)
const STATIC_RESOURCES = [
    '/static/css/styles.css',
    '/static/js/pwa-manager.js',
    '/static/js/notification-health-manager.js',
    '/static/js/notifications.js',
    '/static/js/auth.js',
    '/static/js/memes.js',
    '/static/js/update-notifier.js',
    '/static/manifest.json',
    '/static/favicon/android-chrome-192x192.png',
    '/static/favicon/android-chrome-512x512.png',
    '/static/favicon/favicon-32x32.png',
    '/static/favicon/favicon.ico'
];

// Install event - cache static resources
self.addEventListener('install', (event) => {
    console.log('Service Worker: Installing...');
    
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('Service Worker: Caching static resources');
            // Cache resources individually to avoid complete failure
            return Promise.allSettled(
                STATIC_RESOURCES.map(url => 
                    cache.add(url).catch(err => 
                        console.warn(`Failed to cache ${url}:`, err)
                    )
                )
            );
        })
    );
    
    // Activate immediately
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
            // Take control of all pages
            return self.clients.claim();
        })
    );
});

// Fetch event - smart caching strategies
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);
    
    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }
    
    // Skip non-HTTP protocols
    if (!url.protocol.startsWith('http')) {
        return;
    }
    
    // Bypass caching and offline fallback for external geocoding (Nominatim)
    if (url.hostname.includes('nominatim.openstreetmap.org')) {
        // Network-only for geocoding; do not cache and do not serve stale
        event.respondWith(fetch(request));
        return;
    }

    // Determine caching strategy based on request type
    if (url.pathname.startsWith('/api/')) {
        // API: Network-first (always try to get fresh data)
        event.respondWith(networkFirst(request));
    } else if (url.pathname.endsWith('.html') || url.pathname === '/' || 
               ['/crew', '/albums', '/memes', '/knowledge', '/admin'].includes(url.pathname)) {
        // HTML pages: Stale-while-revalidate (instant load + background update)
        event.respondWith(staleWhileRevalidate(request));
    } else if (url.pathname.startsWith('/static/') || 
               url.pathname.match(/\.(css|js|png|jpg|jpeg|gif|webp|svg|ico)$/i) ||
               url.hostname.includes('googleusercontent.com')) {
        // Static assets and Google Photos images: Cache-first with long expiry
        event.respondWith(cacheFirst(request));
    } else {
        // Everything else: Network-first
        event.respondWith(networkFirst(request));
    }
});

/**
 * Stale-While-Revalidate strategy
 * Serve from cache immediately, update cache in background
 */
async function staleWhileRevalidate(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);
    
    // Fetch fresh version in background
    const fetchPromise = fetch(request).then(async (networkResponse) => {
        if (networkResponse && networkResponse.ok) {
            // Check if content actually changed before notifying
            let contentChanged = false;
            
            if (cachedResponse) {
                // Compare content (simple check using content-length or etag)
                const oldEtag = cachedResponse.headers.get('etag');
                const newEtag = networkResponse.headers.get('etag');
                const oldLength = cachedResponse.headers.get('content-length');
                const newLength = networkResponse.headers.get('content-length');
                
                if (oldEtag && newEtag) {
                    contentChanged = oldEtag !== newEtag;
                } else if (oldLength && newLength) {
                    contentChanged = oldLength !== newLength;
                } else {
                    // If no headers to compare, assume changed only if we had no cache
                    contentChanged = false;
                }
            }
            
            // Update cache
            await cache.put(request, networkResponse.clone());
            console.log('SW: Updated cache in background:', request.url);
            
            // Only notify if content actually changed
            if (contentChanged) {
                console.log('SW: Content changed, notifying clients');
                const clients = await self.clients.matchAll();
                clients.forEach(client => {
                    client.postMessage({
                        type: 'CONTENT_UPDATED',
                        url: request.url,
                        timestamp: Date.now()
                    });
                });
            }
        }
        return networkResponse;
    }).catch(error => {
        console.log('SW: Background update failed:', error);
        return cachedResponse;
    });
    
    // Return cached version immediately if available
    return cachedResponse || fetchPromise;
}

/**
 * Network-First strategy
 * Try network, fall back to cache if offline
 */
async function networkFirst(request) {
    try {
        const networkResponse = await fetch(request);
        
        // Cache successful responses (exclude auth endpoints)
        if (networkResponse && networkResponse.ok && 
            !request.url.includes('/auth/') && 
            !request.url.includes('/login')) {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        // Network failed, try cache
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            console.log('SW: Served from cache (offline):', request.url);
            return cachedResponse;
        }
        
        // No cache available
        throw error;
    }
}

/**
 * Cache-First strategy
 * Serve from cache, only fetch if not cached
 */
async function cacheFirst(request) {
    const cache = await caches.open(CACHE_NAME);
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse) {
        return cachedResponse;
    }
    
    // Not in cache, fetch from network
    try {
        const networkResponse = await fetch(request);
        if (networkResponse && networkResponse.ok) {
            await cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.error('SW: Failed to fetch:', request.url, error);
        throw error;
    }
}

// Push notification handling (unchanged)
self.addEventListener('push', (event) => {
    console.log('Service Worker: Push event received');
    
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
        try {
            const pushData = event.data.json();
            notificationData = {
                ...notificationData,
                ...pushData
            };
        } catch (error) {
            console.error('Service Worker: Failed to parse push data:', error);
        }
    }
    
    event.waitUntil(
        self.registration.showNotification(notificationData.title, notificationData)
    );
});

// Notification click handling (unchanged)
self.addEventListener('notificationclick', (event) => {
    console.log('Service Worker: Notification clicked');
    event.notification.close();
    
    const urlToOpen = event.notification.data?.url || '/';
    
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then((clientList) => {
            // Check if we already have the app open
            for (const client of clientList) {
                if (client.url.startsWith(self.location.origin) && 'focus' in client) {
                    return client.focus();
                }
            }
            // No existing window found, open a new one
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});

// Simple message handling
self.addEventListener('message', (event) => {
    console.log('Service Worker: Message received:', event.data);
    
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

console.log('Service Worker: Script loaded');
