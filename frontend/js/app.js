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

let processingActive = false;
let shouldStop = false;

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
        btn.textContent = 'Process 2 URLs';
    }
}

async function processAllUrls() {
    const processBtn = document.getElementById('processBtn');
    const processAllBtn = document.getElementById('processAllBtn');
    const stopBtn = document.getElementById('stopBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const progressPercent = document.getElementById('progressPercent');
    const resultDiv = document.getElementById('processResult');

    // Disable buttons and show stop button
    processBtn.disabled = true;
    processAllBtn.disabled = true;
    stopBtn.classList.remove('d-none');
    progressContainer.classList.remove('d-none');

    processingActive = true;
    shouldStop = false;

    let totalProcessed = 0;
    let totalFailed = 0;
    let batchCount = 0;

    resultDiv.innerHTML = '<div class="alert alert-info">Starting batch processing...</div>';

    try {
        // Get initial status
        const statusResponse = await fetch(`${API_BASE}/api/status`);
        const initialStatus = await statusResponse.json();
        const totalToProcess = initialStatus.pending;

        if (totalToProcess === 0) {
            resultDiv.innerHTML = '<div class="alert alert-warning"><strong>No URLs to process</strong></div>';
            return;
        }

        // Process in batches until done or stopped
        while (processingActive && !shouldStop) {
            batchCount++;

            // Update progress text
            progressText.textContent = `Batch ${batchCount} - Processing...`;

            const response = await fetch(`${API_BASE}/api/process-urls`, {
                method: 'POST'
            });

            const data = await response.json();

            if (data.status === 'complete' && data.processed === 0) {
                // No more URLs to process
                break;
            }

            totalProcessed += data.processed;
            totalFailed += (data.total_attempted - data.processed);

            // Update progress
            const currentStatus = await fetch(`${API_BASE}/api/status`);
            const status = await currentStatus.json();
            const progress = Math.round((status.processed / status.total_urls) * 100);

            progressBar.style.width = progress + '%';
            progressPercent.textContent = progress + '%';
            progressText.textContent = `Processed ${status.processed} of ${status.total_urls} URLs`;

            // Show batch results
            let batchHtml = `<div class="alert alert-info">`;
            batchHtml += `<strong>Batch ${batchCount} Complete:</strong> `;
            batchHtml += `${data.processed} successful, ${data.total_attempted - data.processed} failed/skipped<br>`;
            batchHtml += `<strong>Total Progress:</strong> ${status.processed} of ${status.total_urls} URLs (${progress}%)`;
            batchHtml += `</div>`;
            resultDiv.innerHTML = batchHtml;

            // Refresh status display
            await refreshStatus();

            // Check if we're done
            if (status.pending === 0) {
                break;
            }

            // Small delay between batches
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        // Final update
        const finalStatus = await fetch(`${API_BASE}/api/status`);
        const final = await finalStatus.json();

        progressBar.style.width = '100%';
        progressPercent.textContent = '100%';
        progressText.textContent = 'Processing complete!';
        progressBar.classList.remove('progress-bar-animated');

        resultDiv.innerHTML = `
            <div class="alert alert-success">
                <strong>Processing Complete!</strong><br>
                Total batches: ${batchCount}<br>
                Total processed: ${final.processed} URLs<br>
                Pending: ${final.pending} URLs
            </div>
        `;

    } catch (error) {
        resultDiv.innerHTML = `<div class="alert alert-danger">Error: ${error.message}</div>`;
    } finally {
        processingActive = false;
        processBtn.disabled = false;
        processAllBtn.disabled = false;
        stopBtn.classList.add('d-none');
    }
}

function stopProcessing() {
    shouldStop = true;
    document.getElementById('progressText').textContent = 'Stopping after current batch...';
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
