// Page script for /static/admin-notifications.html, moved out of the HTML unchanged.
let statsData = null;
let reliabilityData = null;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    refreshStats();
    
    // Auto-refresh every 2 minutes
    setInterval(refreshStats, 2 * 60 * 1000);
});

async function refreshStats() {
    try {
        showLoading(true);
        clearError();

        [statsData, reliabilityData] = await Promise.all([
            apiFetch('/api/notifications/admin/stats'),
            apiFetch('/api/notifications/admin/reliability?days=7')
        ]);

        updateDashboard();
        showLoading(false);

    } catch (error) {
        console.error('Error fetching stats:', error);
        showError('Could not load notification statistics: ' + (error.detail || error.message));
        showLoading(false);
    }
}

function updateDashboard() {
    if (!statsData || !reliabilityData) return;

    // Update main stats
    document.getElementById('total-subscriptions').textContent = statsData.device_subscriptions.total;
    document.getElementById('subscription-detail').textContent = 
        `${statsData.device_subscriptions.healthy} healthy, ${statsData.device_subscriptions.stale} stale`;

    document.getElementById('reliability-rate').textContent = reliabilityData.reliability_percentage === null
        ? 'n/a'
        : `${reliabilityData.reliability_percentage.toFixed(1)}%`;
    document.getElementById('reliability-detail').textContent = reliabilityData.total_attempts === 0
        ? `No sends in the last ${reliabilityData.period_days} days`
        : `${reliabilityData.successful_sends} of ${reliabilityData.total_attempts} sent`;

    document.getElementById('failed-sends').textContent = reliabilityData.failed_sends;
    document.getElementById('failed-detail').textContent = 
        `${reliabilityData.cleaned_subscriptions} cleaned up`;

    document.getElementById('active-users').textContent = statsData.user_stats.users_with_notifications;
    document.getElementById('users-detail').textContent = 
        `${statsData.user_stats.avg_devices_per_user.toFixed(1)} devices avg`;

    // Update browser stats
    updateBrowserStats();
    updateDailyBreakdown();
}

function updateDailyBreakdown() {
    const container = document.querySelector('.reliability-chart');
    const days = reliabilityData.daily_breakdown.filter(day => day.attempts > 0);
    if (days.length === 0) {
        container.textContent = 'No notification sends recorded in this period';
        return;
    }
    container.innerHTML = days.map(day =>
        `<div class="browser-item"><span><strong>${day.date}</strong></span>` +
        `<span>${day.successful} sent, ${day.failed} failed, ${day.cleaned} cleaned (${day.rate.toFixed(1)}%)</span></div>`
    ).join('');
}

function updateBrowserStats() {
    const container = document.getElementById('browser-stats');
    const browserData = statsData.device_subscriptions.by_browser;

    container.innerHTML = '';

    Object.entries(browserData).forEach(([browser, count]) => {
        const percentage = ((count / statsData.device_subscriptions.total) * 100).toFixed(1);
        
        const item = document.createElement('div');
        item.className = 'browser-item';
        item.innerHTML = `
            <span><strong>${browser}</strong></span>
            <span>${count} (${percentage}%)</span>
        `;
        
        container.appendChild(item);
    });
}

async function testNotifications() {
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
        if (error.status !== 401) showToast('Could not send test notification: ' + (error.detail || error.message), { type: 'error' });
    }
}

async function validateSubscriptions() {
    try {
        const result = await apiFetch('/api/notifications/validate-subscriptions', { method: 'POST' });
        showToast(`Validation started for ${result.total} subscription(s). Invalid ones will be cleaned up automatically.`, { type: 'success' });
        // Refresh stats after validation
        setTimeout(refreshStats, 5000);
    } catch (error) {
        if (error.status !== 401) showToast('Could not validate subscriptions: ' + (error.detail || error.message), { type: 'error' });
    }
}

async function sendBroadcast() {
    const title = document.getElementById('broadcast-title').value.trim();
    const body = document.getElementById('broadcast-body').value.trim();

    if (!title || !body) {
        showToast('Enter both a title and a message for the broadcast', { type: 'error' });
        return;
    }

    if (!confirm(`Send broadcast notification to all ${statsData?.device_subscriptions?.total || 0} subscribers?`)) {
        return;
    }

    try {
        const result = await apiFetch('/api/notifications/admin/broadcast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                body: body,
                icon: '/static/favicon/android-chrome-192x192.png'
            })
        });
        showToast(`Broadcast sent to ${result.recipients} device(s)`, { type: 'success' });
        // Clear form
        document.getElementById('broadcast-title').value = '';
        document.getElementById('broadcast-body').value = '';
    } catch (error) {
        if (error.status !== 401) showToast('Could not send broadcast: ' + (error.detail || error.message), { type: 'error' });
    }
}

function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'block' : 'none';
    document.getElementById('stats-container').style.display = show ? 'none' : 'block';
}

function showError(message) {
    const container = document.getElementById('error-container');
    container.innerHTML = `<div class="error">${message}</div>`;
}

function clearError() {
    document.getElementById('error-container').innerHTML = '';
}
    
