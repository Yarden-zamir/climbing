// Page script for /static/admin.html, moved out of the HTML unchanged.
// Notification Admin Functions
let notificationStatsData = null;
let reliabilityData = null;

// Load stats when notifications section is shown
document.addEventListener('DOMContentLoaded', function() {
    // Listen for section changes
    const navButtons = document.querySelectorAll('.admin-nav-btn');
    navButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            if (this.dataset.section === 'notifications') {
                setTimeout(refreshNotificationStats, 500);
            }
        });
    });
});

async function refreshNotificationStats() {
    try {
        showNotificationError('');
        
        // Update button state
        const refreshBtn = document.querySelector('button[onclick="refreshNotificationStats()"]');
        if (refreshBtn) {
            refreshBtn.disabled = true;
            refreshBtn.textContent = '🔄 Loading...';
        }

        [notificationStatsData, reliabilityData] = await Promise.all([
            apiFetch('/api/notifications/admin/stats'),
            apiFetch('/api/notifications/admin/reliability?days=7')
        ]);

        updateNotificationDashboard();

    } catch (error) {
        console.error('Error fetching notification stats:', error);
        showNotificationError('Could not load notification statistics: ' + (error.detail || error.message));
    } finally {
        // Reset button state
        const refreshBtn = document.querySelector('button[onclick="refreshNotificationStats()"]');
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = '🔄 Refresh Stats';
        }
    }
}

function updateNotificationDashboard() {
    if (!notificationStatsData || !reliabilityData) return;

    // Update main stats
    document.getElementById('total-subscriptions').textContent = notificationStatsData.device_subscriptions.total;
    document.getElementById('subscription-detail').textContent = 
        `${notificationStatsData.device_subscriptions.healthy} healthy, ${notificationStatsData.device_subscriptions.stale} stale`;

    document.getElementById('reliability-rate').textContent = `${reliabilityData.reliability_percentage.toFixed(1)}%`;
    
    document.getElementById('failed-sends').textContent = reliabilityData.failed_sends;
    
    document.getElementById('active-users').textContent = notificationStatsData.user_stats.users_with_notifications;

    // Update browser stats
    updateBrowserStats();
}

function updateBrowserStats() {
    const container = document.getElementById('browser-stats');
    const browserData = notificationStatsData.device_subscriptions.by_browser;

    container.innerHTML = '';

    if (Object.keys(browserData).length === 0) {
        container.innerHTML = '<div class="loading">No browser data available</div>';
        return;
    }

    Object.entries(browserData).forEach(([browser, count]) => {
        const percentage = ((count / notificationStatsData.device_subscriptions.total) * 100).toFixed(1);
        
        const item = document.createElement('div');
        item.className = 'browser-item';
        item.innerHTML = `
            <span><strong>${browser}</strong></span>
            <span>${count} (${percentage}%)</span>
        `;
        
        container.appendChild(item);
    });
}

async function validateAllSubscriptions() {
    try {
        const result = await apiFetch('/api/notifications/validate-subscriptions', { method: 'POST' });
        showToast(`Validation started for ${result.total} subscription(s). Invalid subscriptions will be cleaned up automatically.`, { type: 'success' });
        // Refresh stats after validation
        setTimeout(refreshNotificationStats, 5000);
    } catch (error) {
        if (error.status !== 401) showNotificationError('Could not validate subscriptions: ' + (error.detail || error.message));
    }
}

async function sendTestNotification() {
    try {
        const result = await apiFetch('/api/notifications/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: '🧪 Admin Test',
                body: 'This is a test notification from the admin panel',
                icon: '/static/favicon/android-chrome-192x192.png'
            })
        });
        showToast(`Test notification sent to ${result.devices} device(s)`, { type: 'success' });
    } catch (error) {
        if (error.status !== 401) showNotificationError('Could not send test notification: ' + (error.detail || error.message));
    }
}

function showNotificationError(message) {
    const errorDiv = document.getElementById('notification-admin-error');
    if (message) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    } else {
        errorDiv.style.display = 'none';
    }
}
    
