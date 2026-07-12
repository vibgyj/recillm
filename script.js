// Shared helpers used by receipt-scan.html and receipt-list.html
const API_BASE_URL = "http://localhost:8000";

// Fetch a URL and return parsed JSON, throwing a descriptive Error on failure.
async function fetchJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned error status ${response.status}`);
    }
    return response.json();
}
