/**
 * Cache Manager - Client-side interface for service worker cache management
 * Provides utilities for managing offline functionality and cache statistics
 */

class CacheManager {
    constructor() {
        this.serviceWorker = null;
        this.isOnline = navigator.onLine;
        this.init();
    }

    async init() {
        // Check if service worker is supported
        if ('serviceWorker' in navigator) {
            try {
                // Get the active service worker
                this.serviceWorker = await navigator.serviceWorker.ready;
                console.log('Cache Manager: Service worker ready');
                
                // Listen for online/offline events
                this.setupConnectivityListeners();
                
                // Listen for service worker messages
                this.setupServiceWorkerListener();
                
            } catch (error) {
                console.error('Cache Manager: Failed to initialize:', error);
            }
        } else {
            console.warn('Cache Manager: Service workers not supported');
        }
    }

    setupConnectivityListeners() {
        window.addEventListener('online', () => {
            this.isOnline = true;
            console.log('Cache Manager: App is online');
            this.showConnectivityStatus('online');
            
            // Trigger offline queue processing
            if (this.serviceWorker) {
                this.serviceWorker.sync.register('offline-requests-sync').catch(error => {
                    console.log('Cache Manager: Background sync not supported:', error);
                });
            }
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            console.log('Cache Manager: App is offline');
            this.showConnectivityStatus('offline');
        });
    }

    setupServiceWorkerListener() {
        if (navigator.serviceWorker) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                console.log('Cache Manager: Message from service worker:', event.data);
                
                switch (event.data.type) {
                    case 'OFFLINE_REQUESTS_PROCESSED':
                        this.showOfflineRequestsProcessed(event.data.count);
                        break;
                    case 'CACHE_STATS':
                        this.handleCacheStats(event.data.stats);
                        break;
                    case 'CACHE_CLEANUP_COMPLETE':
                        console.log('Cache Manager: Cache cleanup completed');
                        break;
                }
            });
        }
    }

    showConnectivityStatus(status) {
        // Create or update connectivity indicator
        let indicator = document.getElementById('connectivity-indicator');
        
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.id = 'connectivity-indicator';
            indicator.className = 'connectivity-indicator';
            document.body.appendChild(indicator);
        }

        indicator.className = `connectivity-indicator ${status}`;
        
        if (status === 'online') {
            indicator.innerHTML = '🟢 Back online <span class="close-btn">×</span>';
            indicator.style.background = 'linear-gradient(135deg, #4caf50, #2e7d32)';
        } else {
            indicator.innerHTML = '🔴 Offline mode <span class="close-btn">×</span>';
            indicator.style.background = 'linear-gradient(135deg, #ff9800, #f57c00)';
        }
        
        // Add click to close functionality
        indicator.style.cursor = 'pointer';
        indicator.onclick = () => {
            indicator.style.opacity = '0';
            setTimeout(() => {
                if (indicator && indicator.parentNode) {
                    indicator.parentNode.removeChild(indicator);
                }
            }, 300);
        };
        
        // Auto-hide after delay
        setTimeout(() => {
            if (status === 'online' && indicator) {
                indicator.style.opacity = '0';
                setTimeout(() => {
                    if (indicator && indicator.parentNode) {
                        indicator.parentNode.removeChild(indicator);
                    }
                }, 300);
            }
        }, 3000);
        
        this.addConnectivityStyles();
    }

    showOfflineRequestsProcessed(count) {
        const message = document.createElement('div'); 
        message.className = 'offline-sync-message';
        message.innerHTML = `
            <div class="offline-sync-content">
                ✅ Synced ${count} offline ${count === 1 ? 'request' : 'requests'}
                <button onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
        `;
        
        document.body.appendChild(message);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (message.parentElement) {
                message.remove();
            }
        }, 5000);
        
        this.addSyncMessageStyles();
    }

    addConnectivityStyles() {
        if (document.getElementById('connectivity-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'connectivity-styles';
        styles.textContent = `
            .connectivity-indicator {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                color: white;
                padding: 12px 20px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 14px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                transition: all 0.3s ease;
                animation: slideInRight 0.3s ease-out;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            
            .connectivity-indicator:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 16px rgba(0,0,0,0.4);
            }
            
            .connectivity-indicator .close-btn {
                background: rgba(255,255,255,0.2);
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                line-height: 1;
                flex-shrink: 0;
                transition: background 0.2s ease;
            }
            
            .connectivity-indicator .close-btn:hover {
                background: rgba(255,255,255,0.3);
            }
            
            .connectivity-indicator.offline {
                animation: pulse 2s infinite;
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
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }
            
            @media (max-width: 480px) {
                .connectivity-indicator {
                    top: 10px;
                    right: 10px;
                    left: 10px;
                    text-align: left;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }

    addSyncMessageStyles() {
        if (document.getElementById('sync-message-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'sync-message-styles';
        styles.textContent = `
            .offline-sync-message {
                position: fixed;
                top: 80px;
                right: 20px;
                z-index: 10000;
                animation: slideInRight 0.3s ease-out;
            }
            
            .offline-sync-content {
                background: linear-gradient(135deg, #4caf50, #2e7d32);
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 14px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                display: flex;
                align-items: center;
                gap: 12px;
            }
            
            .offline-sync-content button {
                background: rgba(255,255,255,0.2);
                border: none;
                color: white;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                cursor: pointer;
                font-size: 16px;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .offline-sync-content button:hover {
                background: rgba(255,255,255,0.3);
            }
            
            @media (max-width: 480px) {
                .offline-sync-message {
                    top: 70px;
                    right: 10px;
                    left: 10px;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }

    /**
     * Get cache statistics from service worker
     */
    async getCacheStats() {
        if (!this.serviceWorker) {
            throw new Error('Service worker not available');
        }

        return new Promise((resolve, reject) => {
            const messageChannel = new MessageChannel();
            
            messageChannel.port1.onmessage = (event) => {
                if (event.data.type === 'CACHE_STATS') {
                    resolve(event.data.stats);
                } else if (event.data.type === 'CACHE_STATS_ERROR') {
                    reject(new Error(event.data.error));
                }
            };

            this.serviceWorker.active.postMessage(
                { type: 'GET_CACHE_STATS' },
                [messageChannel.port2]
            );
        });
    }

    /**
     * Trigger cache cleanup
     */
    async cleanupCaches() {
        if (!this.serviceWorker) {
            throw new Error('Service worker not available');
        }

        return new Promise((resolve, reject) => {
            const messageChannel = new MessageChannel();
            
            messageChannel.port1.onmessage = (event) => {
                if (event.data.type === 'CACHE_CLEANUP_COMPLETE') {
                    resolve();
                } else if (event.data.type === 'CACHE_CLEANUP_ERROR') {
                    reject(new Error(event.data.error));
                }
            };

            this.serviceWorker.active.postMessage(
                { type: 'CLEANUP_CACHES' },
                [messageChannel.port2]
            );
        });
    }

    /**
     * Clear offline request queue
     */
    async clearOfflineQueue() {
        if (!this.serviceWorker) {
            throw new Error('Service worker not available');
        }

        return new Promise((resolve, reject) => {
            const messageChannel = new MessageChannel();
            
            messageChannel.port1.onmessage = (event) => {
                if (event.data.type === 'OFFLINE_QUEUE_CLEARED') {
                    resolve();
                } else if (event.data.type === 'OFFLINE_QUEUE_CLEAR_ERROR') {
                    reject(new Error(event.data.error));
                }
            };

            this.serviceWorker.active.postMessage(
                { type: 'CLEAR_OFFLINE_QUEUE' },
                [messageChannel.port2]
            );
        });
    }

    /**
     * Check if the app is currently offline
     */
    isOffline() {
        return !this.isOnline;
    }

    /**
     * Show cache management debug info (for development)
     */
    async showCacheDebugInfo() {
        try {
            const stats = await this.getCacheStats();
            console.group('🗄️ Cache Statistics');
            
            Object.entries(stats).forEach(([cacheName, cacheData]) => {
                if (cacheName === 'offlineQueue') {
                    console.log(`📤 Offline Queue: ${cacheData.count} pending requests`);
                    if (cacheData.count > 0) {
                        console.log('Pending requests:', cacheData.requests);
                    }
                } else {
                    console.log(`📦 ${cacheName}: ${cacheData.count} cached items`);
                    if (cacheData.count > 0 && cacheData.urls.length <= 10) {
                        console.log('Cached URLs:', cacheData.urls);
                    }
                }
            });
            
            console.groupEnd();
            return stats;
        } catch (error) {
            console.error('Failed to get cache debug info:', error);
            throw error;
        }
    }

    handleCacheStats(stats) {
        // Override this method in specific implementations
        console.log('Cache Manager: Received cache stats:', stats);
    }
}

// Create global instance
window.cacheManager = new CacheManager();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CacheManager;
}

// Development helpers
window.debugCache = {
    async stats() {
        return window.cacheManager.showCacheDebugInfo();
    },
    
    async cleanup() {
        try {
            await window.cacheManager.cleanupCaches();
            console.log('✅ Cache cleanup completed');
        } catch (error) {
            console.error('❌ Cache cleanup failed:', error);
        }
    },
    
    async clearOfflineQueue() {
        try {
            await window.cacheManager.clearOfflineQueue();
            console.log('✅ Offline queue cleared');
        } catch (error) {
            console.error('❌ Failed to clear offline queue:', error);
        }
    },
    
    connectivity: () => {
        console.log(`📡 Connection status: ${navigator.onLine ? 'Online' : 'Offline'}`);
        return navigator.onLine;
    }
};

console.log('💾 Cache Manager loaded. Try: debugCache.stats(), debugCache.cleanup(), debugCache.connectivity()');