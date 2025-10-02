// Vanilla JavaScript - no build tools, no transpilation!

const API_BASE = 'http://localhost:8001';

// Check system status on load
window.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    refreshStatus();
});

async function checkStatus() {
    try {
        const response = await fetch(`${API_BASE}/`);
        const data = await response.json();
        document.getElementById('status').innerHTML = `
            <span class="status-ok">✓ Connected</span> |
            Project: ${data.project} |
            Server Time: ${new Date(data.timestamp).toLocaleTimeString()}
        `;
    } catch (error) {
        document.getElementById('status').innerHTML =
            '<span class="status-error">✗ Cannot connect to backend</span>';
    }
}

async function testAPI() {
    const prompt = document.getElementById('promptInput').value;
    const resultDiv = document.getElementById('result');

    if (!prompt) {
        alert('Please enter a prompt');
        return;
    }

    resultDiv.textContent = 'Thinking...';
    resultDiv.classList.add('show');

    try {
        const response = await fetch(`${API_BASE}/api/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ prompt })
        });

        const data = await response.json();
        resultDiv.textContent = data.response || 'No response';
    } catch (error) {
        resultDiv.textContent = `Error: ${error.message}`;
    }
}

async function processUrls() {
    const btn = document.getElementById('processBtn');
    const resultDiv = document.getElementById('processResult');

    btn.disabled = true;
    btn.textContent = 'Processing...';
    resultDiv.innerHTML = '<div class="alert alert-info">Processing URLs... This may take a minute.</div>';

    try {
        const response = await fetch(`${API_BASE}/api/process-urls`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.status === 'complete' && data.processed === 0) {
            resultDiv.innerHTML = `
                <div class="alert alert-warning">
                    <strong>No URLs to process</strong><br>
                    ${data.message}
                </div>
            `;
        } else {
            let resultsHtml = `
                <div class="alert alert-success">
                    <strong>Processed ${data.processed} of ${data.total_attempted} URLs</strong>
                </div>
                <ul class="list-group mt-2">
            `;

            data.results.forEach(r => {
                let badgeClass = r.status === 'success' ? 'success' :
                               r.status === 'skipped' ? 'warning' : 'danger';
                resultsHtml += `
                    <li class="list-group-item">
                        <span class="badge bg-${badgeClass}">${r.status}</span>
                        <small class="text-muted d-block">${r.url}</small>
                        ${r.content_preview ? `<small>${r.content_preview}</small>` : ''}
                        ${r.reason ? `<small class="text-danger">${r.reason}</small>` : ''}
                    </li>
                `;
            });

            resultsHtml += '</ul>';
            resultDiv.innerHTML = resultsHtml;
        }

        // Refresh status counts
        refreshStatus();

    } catch (error) {
        resultDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Process URLs';
    }
}

async function refreshStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/status`);
        const data = await response.json();

        document.getElementById('totalUrls').textContent = data.total_urls;
        document.getElementById('processedUrls').textContent = data.processed;
        document.getElementById('pendingUrls').textContent = data.pending;

        // Display recent results
        const recentDiv = document.getElementById('recentResults');
        if (data.recent_results && data.recent_results.length > 0) {
            let html = '';
            data.recent_results.forEach(item => {
                html += `
                    <div class="list-group-item">
                        <div class="d-flex w-100 justify-content-between">
                            <h6 class="mb-1">${item.url}</h6>
                            <small>${new Date(item.created_at).toLocaleString()}</small>
                        </div>
                        <p class="mb-1 small">${item.content.substring(0, 150)}...</p>
                    </div>
                `;
            });
            recentDiv.innerHTML = html;
        } else {
            recentDiv.innerHTML = '<p class="text-muted">No results yet</p>';
        }

    } catch (error) {
        console.error('Status refresh error:', error);
    }
}

// Auto-refresh status every 30 seconds
setInterval(checkStatus, 30000);
