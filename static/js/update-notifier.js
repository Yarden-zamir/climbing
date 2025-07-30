/**
 * Simple Update Notifier - Shows subtle notification when content is updated in background
 * This is optional and much simpler than version tracking
 */

class UpdateNotifier {
    constructor() {
        this.notification = null;
        this.init();
    }

    init() {
        // Listen for content update messages from service worker
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                if (event.data && event.data.type === 'CONTENT_UPDATED') {
                    console.log('Content updated in background:', event.data.url);
                    
                    // Only show notification for HTML pages, not API calls
                    if (event.data.url.includes('.html') || 
                        event.data.url === location.origin + '/' ||
                        ['/crew', '/albums', '/memes', '/knowledge', '/admin'].some(path => 
                            event.data.url === location.origin + path)) {
                        this.showUpdateNotification();
                    }
                }
            });
        }
    }

    showUpdateNotification() {
        // Don't show multiple notifications
        if (this.notification && document.body.contains(this.notification)) {
            return;
        }

        console.log('Showing update notification');

        this.notification = document.createElement('div');
        this.notification.className = 'update-notification';
        this.notification.innerHTML = `
            <div class="update-content">
                <span class="update-text">New content available</span>
                <button class="update-refresh" onclick="location.reload()">
                    Refresh
                </button>
                <button class="update-dismiss" onclick="updateNotifier.dismiss()">
                    ×
                </button>
            </div>
        `;

        document.body.appendChild(this.notification);
        this.addStyles();

        // Auto-show with animation
        setTimeout(() => {
            this.notification.classList.add('update-show');
        }, 100);

        // Auto-hide after 10 seconds
        setTimeout(() => {
            this.dismiss();
        }, 10000);
    }

    dismiss() {
        if (this.notification) {
            this.notification.classList.remove('update-show');
            setTimeout(() => {
                if (this.notification && this.notification.parentElement) {
                    this.notification.remove();
                }
                this.notification = null;
            }, 300);
        }
    }

    addStyles() {
        if (document.getElementById('update-notifier-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'update-notifier-styles';
        styles.textContent = `
            .update-notification {
                position: fixed;
                bottom: 20px;
                left: 20px;
                z-index: 1000;
                background: #333;
                color: white;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                transform: translateY(100px);
                transition: transform 0.3s ease-out;
                font-size: 14px;
            }

            .update-notification.update-show {
                transform: translateY(0);
            }

            .update-content {
                display: flex;
                align-items: center;
                padding: 12px 16px;
                gap: 12px;
            }

            .update-text {
                flex: 1;
                min-width: 0;
            }

            .update-refresh {
                background: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                color: white;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 13px;
                cursor: pointer;
                transition: background 0.2s;
            }

            .update-refresh:hover {
                background: rgba(255,255,255,0.3);
            }

            .update-dismiss {
                background: none;
                border: none;
                color: white;
                font-size: 18px;
                cursor: pointer;
                padding: 0 4px;
                opacity: 0.7;
                transition: opacity 0.2s;
                line-height: 1;
            }

            .update-dismiss:hover {
                opacity: 1;
            }

            @media (max-width: 480px) {
                .update-notification {
                    left: 10px;
                    right: 10px;
                    bottom: 10px;
                }
            }
        `;
        
        document.head.appendChild(styles);
    }
}

// Initialize update notifier globally
window.updateNotifier = new UpdateNotifier();

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UpdateNotifier;
}