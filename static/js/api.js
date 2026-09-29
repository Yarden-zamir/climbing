/**
 * Shared fetch wrapper and toast. Loaded on every page before auth.js and page scripts.
 *
 * window.ApiError            - Error with `status` (0 for network failure) and `detail` (user-facing text)
 * window.apiFetch(url, opts) - fetch that returns parsed JSON (null for an empty body) or throws ApiError.
 *                              On 401 it calls authManager.requireLogin(opts.pending) before throwing.
 * window.showToast(message, { type, action, duration })
 */

class ApiError extends Error {
    constructor(status, detail) {
        super(detail);
        this.name = 'ApiError';
        this.status = status;
        this.detail = detail;
    }
}

const NETWORK_ERROR_MESSAGE = 'Could not reach the server. Check your connection and try again.';
const SIGN_IN_MESSAGE = 'Please sign in to continue';

function formatErrorDetail(body, response) {
    const detail = body && typeof body === 'object' ? body.detail : undefined;
    if (typeof detail === 'string' && detail.trim()) return detail;
    // FastAPI 422 validation errors: [{ loc: ['body', 'field'], msg: '...' }, ...]
    if (Array.isArray(detail) && detail.length) {
        return detail.map((item) => {
            const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body' && part !== 'query').join('.') : '';
            return field ? `${field}: ${item.msg}` : String(item.msg || item);
        }).join('; ');
    }
    // Some routes return a structured detail object (for example { blocked_by_albums: 3 }); keep its message if any
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
    return `HTTP ${response.status} ${response.statusText}`.trim();
}

async function apiFetch(url, options = {}) {
    const { pending, ...fetchOptions } = options;
    if (!('credentials' in fetchOptions)) fetchOptions.credentials = 'same-origin';

    let response;
    try {
        response = await fetch(url, fetchOptions);
    } catch (error) {
        console.error('apiFetch network error:', url, error);
        throw new ApiError(0, NETWORK_ERROR_MESSAGE);
    }

    let body = null;
    const text = await response.text().catch(() => '');
    if (text) {
        try {
            body = JSON.parse(text);
        } catch (_) {
            if (response.ok) {
                console.error('apiFetch: response is not JSON:', url, text.slice(0, 200));
                throw new ApiError(0, NETWORK_ERROR_MESSAGE);
            }
            body = { detail: text };
        }
    }

    if (response.ok) return body;

    if (response.status === 401) {
        if (window.authManager) window.authManager.requireLogin(pending);
        throw new ApiError(401, SIGN_IN_MESSAGE);
    }

    const error = new ApiError(response.status, formatErrorDetail(body, response));
    error.body = body;
    throw error;
}

function getToastContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.setAttribute('role', 'status');
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
    }
    return container;
}

/**
 * @param {string} message
 * @param {{ type?: 'info'|'success'|'error', action?: { label: string, onClick: () => void } | null, duration?: number }} [options]
 */
function showToast(message, { type = 'info', action = null, duration } = {}) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const text = document.createElement('span');
    text.className = 'toast-message';
    text.textContent = message;
    toast.appendChild(text);

    const dismiss = () => {
        if (!toast.parentNode) return;
        toast.classList.add('toast-hide');
        setTimeout(() => toast.remove(), 250);
    };

    if (action && typeof action.onClick === 'function') {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'toast-action';
        button.textContent = action.label;
        button.addEventListener('click', () => {
            dismiss();
            action.onClick();
        });
        toast.appendChild(button);
    }

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', dismiss);
    toast.appendChild(close);

    getToastContainer().appendChild(toast);

    const ms = typeof duration === 'number' ? duration : (type === 'error' || action ? 8000 : 4000);
    if (ms > 0) setTimeout(dismiss, ms);
    return toast;
}

window.ApiError = ApiError;
window.apiFetch = apiFetch;
window.showToast = showToast;
