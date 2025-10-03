// Thema Ads Processing Frontend
let currentJobId = null;
let pollInterval = null;
let pollRetries = 0;
const MAX_POLL_RETRIES = 3;
const POLL_TIMEOUT = 10000; // 10 seconds

// CSV File Validation
function validateCSVFile(file) {
    const errors = [];

    // Check if file exists
    if (!file) {
        errors.push('No file selected');
        return errors;
    }

    // Check file type
    const validTypes = ['text/csv', 'application/vnd.ms-excel', 'text/plain'];
    const validExtensions = ['.csv'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

    if (!validTypes.includes(file.type) && !validExtensions.includes(fileExtension)) {
        errors.push('Invalid file type. Please upload a CSV file (.csv)');
    }

    // Check file size (max 30MB)
    const maxSize = 30 * 1024 * 1024; // 30MB
    if (file.size > maxSize) {
        errors.push('File too large. Maximum size is 30MB');
    }

    if (file.size === 0) {
        errors.push('File is empty');
    }

    return errors;
}

// Validate CSV content (quick check - only reads first few lines)
async function validateCSVContent(file) {
    return new Promise((resolve, reject) => {
        console.log('Setting up FileReader for validation...');

        // Add timeout for validation
        const validationTimeout = setTimeout(() => {
            console.warn('Validation timeout - skipping detailed validation');
            resolve({ valid: true, rowCount: 'unknown' });
        }, 3000); // 3 second timeout

        const reader = new FileReader();

        reader.onload = (e) => {
            clearTimeout(validationTimeout);
            console.log('FileReader loaded successfully');

            try {
                const text = e.target.result;
                console.log('CSV text length:', text.length);

                // Only check first 100 lines for performance
                const allLines = text.split('\n');
                const lines = allLines.slice(0, Math.min(100, allLines.length)).filter(line => line.trim());
                console.log('CSV total lines:', allLines.length, 'checking first:', lines.length);

                if (lines.length < 2) {
                    console.error('Not enough lines in CSV');
                    reject('CSV file must contain headers and at least one data row');
                    return;
                }

                // Check headers
                const headers = lines[0].toLowerCase().split(',').map(h => h.trim());
                console.log('CSV headers:', headers);
                const requiredHeaders = ['customer_id', 'ad_group_id'];
                const missingHeaders = requiredHeaders.filter(h => !headers.includes(h));

                if (missingHeaders.length > 0) {
                    console.error('Missing headers:', missingHeaders);
                    reject(`Missing required columns: ${missingHeaders.join(', ')}. Required: customer_id, ad_group_id`);
                    return;
                }

                const totalRows = allLines.length - 1;
                console.log('CSV validation successful, estimated row count:', totalRows);
                resolve({ valid: true, rowCount: totalRows });
            } catch (error) {
                clearTimeout(validationTimeout);
                console.error('CSV parsing error:', error);
                reject('Failed to parse CSV file: ' + error.message);
            }
        };

        reader.onerror = (error) => {
            clearTimeout(validationTimeout);
            console.error('FileReader error:', error);
            reject('Failed to read file');
        };

        console.log('Starting readAsText...');
        reader.readAsText(file);
    });
}

// Upload CSV - simplified without client-side validation
async function uploadCSV() {
    const fileInput = document.getElementById('csvFile');
    const file = fileInput.files[0];
    const uploadButton = document.querySelector('button[onclick="uploadCSV()"]');

    // Basic file check only
    if (!file) {
        showAlert('uploadResult', 'Please select a CSV file', 'warning');
        return;
    }

    // Check file extension
    const fileName = file.name.toLowerCase();
    if (!fileName.endsWith('.csv')) {
        showAlert('uploadResult', 'Please upload a .csv file', 'danger');
        return;
    }

    // Check file size (max 30MB)
    const maxSize = 30 * 1024 * 1024;
    if (file.size > maxSize) {
        showAlert('uploadResult', 'File too large. Maximum size is 30MB', 'danger');
        return;
    }

    if (file.size === 0) {
        showAlert('uploadResult', 'File is empty', 'danger');
        return;
    }

    // Show uploading state immediately
    if (uploadButton) {
        uploadButton.disabled = true;
        uploadButton.textContent = 'Uploading...';
    }

    const fileSizeMB = (file.size / 1024 / 1024).toFixed(2);
    const uploadMsg = file.size > 5 * 1024 * 1024
        ? `Uploading ${fileSizeMB}MB CSV file... This may take a few minutes for large files.`
        : 'Uploading CSV file...';
    showAlert('uploadResult', uploadMsg, 'info');

    try {
        // Get batch size from input field
        const batchSizeInput = document.getElementById('csvBatchSize');
        const batchSize = batchSizeInput ? parseInt(batchSizeInput.value) || 7500 : 7500;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('batch_size', batchSize);

        console.log('Sending file to server with batch_size:', batchSize);

        // Upload with dynamic timeout based on file size
        // Base timeout: 2 minutes, plus 30 seconds per 5MB
        const baseTimeout = 120000; // 2 minutes
        const extraTimeout = Math.floor(file.size / (5 * 1024 * 1024)) * 30000; // 30s per 5MB
        const uploadTimeout = Math.min(baseTimeout + extraTimeout, 600000); // Max 10 minutes

        console.log(`Upload timeout set to ${uploadTimeout / 1000} seconds for ${(file.size / 1024 / 1024).toFixed(2)}MB file`);

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), uploadTimeout);

        const response = await fetch('/api/thema-ads/upload', {
            method: 'POST',
            body: formData,
            signal: controller.signal
        });

        clearTimeout(timeoutId);
        console.log('Upload response received:', response.status);

        let data;
        try {
            data = await response.json();
        } catch (e) {
            console.error('Failed to parse response:', e);
            throw new Error(`Server returned ${response.status}: ${response.statusText}`);
        }

        if (response.ok) {
            console.log('Upload successful:', data);
            showAlert('uploadResult',
                `✅ Upload successful! Processing started automatically.<br>Job ID: ${data.job_id}<br>Total items: ${data.total_items}`,
                'success'
            );
            fileInput.value = '';
            currentJobId = data.job_id;
            await refreshJobs();
            await showJobDetail(data.job_id);
        } else {
            const errorMsg = data.detail || data.message || JSON.stringify(data) || 'Unknown error occurred';
            console.error('Upload failed. Status:', response.status, 'Data:', data);
            showAlert('uploadResult', `❌ Upload failed (${response.status}): ${errorMsg}`, 'danger');
        }
    } catch (error) {
        let errorMessage = 'Upload failed: ';

        if (error.name === 'AbortError') {
            errorMessage += 'Request timed out. Please try again.';
        } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
            errorMessage += 'Network error. Please check your connection and try again.';
        } else {
            errorMessage += error.message || error;
        }

        showAlert('uploadResult', `❌ ${errorMessage}`, 'danger');
        console.error('Upload error:', error);
    } finally {
        if (uploadButton) {
            uploadButton.disabled = false;
            uploadButton.textContent = 'Upload & Create Job';
        }
    }
}

// Auto-discover ad groups from Google Ads
async function discoverAdGroups() {
    const discoverBtn = document.getElementById('discoverBtn');
    const resultDiv = document.getElementById('discoverResult');
    const limitInput = document.getElementById('discoverLimit');
    const batchSizeInput = document.getElementById('discoverBatchSize');

    discoverBtn.disabled = true;
    discoverBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Discovering...';
    resultDiv.innerHTML = '';

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 600000); // 10 minutes timeout for large discovery operations

        // Build URL with optional limit and batch_size parameters
        let url = '/api/thema-ads/discover';
        const params = new URLSearchParams();

        const limit = limitInput.value ? parseInt(limitInput.value) : null;
        if (limit) {
            params.append('limit', limit);
        }

        const batchSize = batchSizeInput ? parseInt(batchSizeInput.value) || 7500 : 7500;
        params.append('batch_size', batchSize);

        if (params.toString()) {
            url += `?${params.toString()}`;
        }

        const response = await fetch(url, {
            method: 'POST',
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        const data = await response.json();

        if (response.ok) {
            if (data.status === 'no_ad_groups_found') {
                showAlert('discoverResult',
                    `ℹ️ No ad groups found matching the criteria.<br>
                     Checked ${data.customers_found || 0} Beslist.nl accounts.`,
                    'info'
                );
            } else {
                showAlert('discoverResult',
                    `✅ Discovery successful! Processing started automatically.<br>
                     Job ID: ${data.job_id}<br>
                     Found ${data.ad_groups_discovered} ad groups in ${data.customers_found} accounts.<br>
                     <small>Check the "Processing Jobs" section below for progress.</small>`,
                    'success'
                );

                // Refresh jobs list to show new job
                refreshJobs();

                // Switch to CSV Upload tab after a delay
                setTimeout(() => {
                    document.getElementById('csv-tab').click();
                }, 3000);
            }
        } else {
            const errorMsg = data.detail || 'Discovery failed';
            showAlert('discoverResult', `❌ ${errorMsg}`, 'danger');
        }
    } catch (error) {
        let errorMsg = 'Discovery failed: ';

        if (error.name === 'AbortError') {
            errorMsg += 'Request timed out. Discovery can take a while for large accounts.';
        } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
            errorMsg += 'Network error. Please check your connection.';
        } else {
            errorMsg += error.message || error;
        }

        showAlert('discoverResult', `❌ ${errorMsg}`, 'danger');
        console.error('Discovery error:', error);
    } finally {
        discoverBtn.disabled = false;
        discoverBtn.innerHTML = '<i class="bi bi-search"></i> Discover & Process Ad Groups';
    }
}

// Load jobs list with error handling
async function refreshJobs() {
    const jobsList = document.getElementById('jobsList');

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // Increased to 30s for large datasets

        const response = await fetch('/api/thema-ads/jobs', {
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (!data.jobs || data.jobs.length === 0) {
            jobsList.innerHTML = '<p class="text-muted">No jobs yet. Upload a CSV to get started.</p>';
            return;
        }

        let html = '<div class="table-responsive"><table class="table table-hover">';
        html += '<thead><tr><th>Job ID</th><th>Status</th><th>Progress</th><th>Success/Failed/Skipped</th><th>Created</th><th>Actions</th></tr></thead><tbody>';

        data.jobs.forEach(job => {
            const progress = job.total_ad_groups > 0
                ? Math.round((job.processed_ad_groups / job.total_ad_groups) * 100)
                : 0;

            const statusBadge = getStatusBadge(job.status);

            html += `<tr onclick="showJobDetail(${job.id})" style="cursor:pointer;">
                <td>${job.id}</td>
                <td>${statusBadge}</td>
                <td>
                    <div class="progress" style="width: 100px;">
                        <div class="progress-bar" style="width: ${progress}%">${progress}%</div>
                    </div>
                </td>
                <td>${job.successful_ad_groups} / ${job.failed_ad_groups} / ${job.skipped_ad_groups || 0}</td>
                <td>${formatDate(job.created_at)}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); showJobDetail(${job.id})">
                        View
                    </button>
                    ${(job.failed_ad_groups > 0 || job.skipped_ad_groups > 0) ? `
                    <button class="btn btn-sm btn-warning" onclick="event.stopPropagation(); downloadFailedItems(${job.id})" title="Download failed and skipped items CSV">
                        <i class="bi bi-download"></i> CSV
                    </button>
                    ` : ''}
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob(${job.id})" ${job.status === 'running' ? 'disabled' : ''}>
                        Delete
                    </button>
                </td>
            </tr>`;
        });

        html += '</tbody></table></div>';
        jobsList.innerHTML = html;

    } catch (error) {
        console.error('Error loading jobs:', error);
        let errorMsg = 'Failed to load jobs list';

        if (error.name === 'AbortError') {
            errorMsg += ' (request timed out)';
        } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
            errorMsg += ' (network error)';
        }

        jobsList.innerHTML = `<div class="alert alert-danger">${errorMsg}. <button class="btn btn-sm btn-outline-danger" onclick="refreshJobs()">Retry</button></div>`;
    }
}

// Show job detail
async function showJobDetail(jobId) {
    currentJobId = jobId;
    document.getElementById('currentJobId').textContent = jobId;
    document.getElementById('currentJobCard').style.display = 'block';

    // Start polling for updates
    if (pollInterval) clearInterval(pollInterval);
    await updateJobStatus();
    pollInterval = setInterval(updateJobStatus, 2000); // Poll every 2 seconds
}

// Update job status with retry logic
async function updateJobStatus() {
    if (!currentJobId) return;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), POLL_TIMEOUT);

        const response = await fetch(`/api/thema-ads/jobs/${currentJobId}`, {
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const job = await response.json();
        pollRetries = 0; // Reset retry counter on success

        // Update statistics
        document.getElementById('totalItems').textContent = job.total_ad_groups;
        document.getElementById('successfulItems').textContent = job.successful_ad_groups;
        document.getElementById('skippedItems').textContent = job.skipped_ad_groups || 0;
        document.getElementById('failedItems').textContent = job.failed_ad_groups;

        const pendingCount = (job.items_by_status?.pending || 0) +
                            (job.items_by_status?.processing || 0);
        document.getElementById('pendingItems').textContent = pendingCount;

        // Update progress bar
        const progress = job.total_ad_groups > 0
            ? Math.round((job.processed_ad_groups / job.total_ad_groups) * 100)
            : 0;

        const progressBar = document.getElementById('progressBar');
        progressBar.style.width = progress + '%';
        progressBar.textContent = progress + '%';

        document.getElementById('progressText').textContent =
            `${job.processed_ad_groups} / ${job.total_ad_groups}`;

        // Update status
        const statusBadge = document.getElementById('jobStatus');
        statusBadge.textContent = job.status.toUpperCase();
        statusBadge.className = 'badge ' + getStatusClass(job.status);

        // Update started time
        document.getElementById('jobStarted').textContent =
            job.started_at ? formatDate(job.started_at) : 'Not started';

        // Update action buttons
        updateActionButtons(job.status);

        // Show failures if any
        if (job.recent_failures && job.recent_failures.length > 0) {
            document.getElementById('failuresSection').style.display = 'block';
            const failuresList = document.getElementById('failuresList');
            failuresList.innerHTML = job.recent_failures.map(f => `
                <div class="list-group-item">
                    <small class="text-muted">Customer: ${f.customer_id}, Ad Group: ${f.ad_group_id}</small><br>
                    <small class="text-danger">${f.error_message || 'Unknown error'}</small>
                </div>
            `).join('');
        } else {
            document.getElementById('failuresSection').style.display = 'none';
        }

        // Stop polling if job is completed or failed
        if (job.status === 'completed' || job.status === 'failed') {
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        }

    } catch (error) {
        console.error('Error updating job status:', error);
        pollRetries++;

        if (pollRetries >= MAX_POLL_RETRIES) {
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }

            const errorMsg = error.name === 'AbortError'
                ? 'Connection timeout. Click refresh to reconnect.'
                : 'Lost connection to server. Click refresh to reconnect.';

            document.getElementById('progressText').textContent = '⚠️ ' + errorMsg;
        }
    }
}

// Update action buttons based on job status
function updateActionButtons(status) {
    const startBtn = document.getElementById('startBtn');
    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');

    startBtn.style.display = 'none';
    pauseBtn.style.display = 'none';
    resumeBtn.style.display = 'none';

    if (status === 'pending') {
        startBtn.style.display = 'inline-block';
    } else if (status === 'running') {
        pauseBtn.style.display = 'inline-block';
    } else if (status === 'paused' || status === 'failed') {
        resumeBtn.style.display = 'inline-block';
    }
}

// Start job with error handling
async function startJob() {
    if (!currentJobId) return;

    const startBtn = document.getElementById('startBtn');
    startBtn.disabled = true;
    startBtn.textContent = 'Starting...';

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        const response = await fetch(`/api/thema-ads/jobs/${currentJobId}/start`, {
            method: 'POST',
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (response.ok) {
            pollRetries = 0; // Reset retries
            await updateJobStatus();
        } else {
            const data = await response.json();
            const errorMsg = data.detail || 'Failed to start job';
            showAlert('uploadResult', `❌ ${errorMsg}`, 'danger');
        }
    } catch (error) {
        let errorMsg = 'Failed to start job';

        if (error.name === 'AbortError') {
            errorMsg += ' (request timed out)';
        } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
            errorMsg += ' (network error)';
        }

        showAlert('uploadResult', `❌ ${errorMsg}`, 'danger');
    } finally {
        startBtn.disabled = false;
        startBtn.textContent = 'Start';
    }
}

// Pause job with error handling
async function pauseJob() {
    if (!currentJobId) return;

    const pauseBtn = document.getElementById('pauseBtn');
    pauseBtn.disabled = true;
    pauseBtn.textContent = 'Pausing...';

    try {
        const response = await fetch(`/api/thema-ads/jobs/${currentJobId}/pause`, {
            method: 'POST'
        });

        if (response.ok) {
            await updateJobStatus();
        } else {
            const data = await response.json();
            showAlert('uploadResult', `❌ Failed to pause: ${data.detail || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        showAlert('uploadResult', `❌ Failed to pause job: ${error.message}`, 'danger');
    } finally {
        pauseBtn.disabled = false;
        pauseBtn.textContent = 'Pause';
    }
}

// Resume job with error handling
async function resumeJob() {
    if (!currentJobId) return;

    const resumeBtn = document.getElementById('resumeBtn');
    resumeBtn.disabled = true;
    resumeBtn.textContent = 'Resuming...';

    try {
        const response = await fetch(`/api/thema-ads/jobs/${currentJobId}/resume`, {
            method: 'POST'
        });

        if (response.ok) {
            pollRetries = 0; // Reset retries
            await updateJobStatus();
        } else {
            const data = await response.json();
            showAlert('uploadResult', `❌ Failed to resume: ${data.detail || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        showAlert('uploadResult', `❌ Failed to resume job: ${error.message}`, 'danger');
    } finally {
        resumeBtn.disabled = false;
        resumeBtn.textContent = 'Resume';
    }
}

// Delete job with error handling
async function deleteJob(jobId) {
    if (!confirm(`Are you sure you want to delete job ${jobId}? This cannot be undone.`)) {
        return;
    }

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        const response = await fetch(`/api/thema-ads/jobs/${jobId}`, {
            method: 'DELETE',
            signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (response.ok) {
            showAlert('uploadResult', `✅ Job ${jobId} deleted successfully`, 'success');
            await refreshJobs();

            // Clear current job if it was the deleted one
            if (currentJobId === jobId) {
                document.getElementById('currentJobCard').style.display = 'none';
                currentJobId = null;
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
            }
        } else {
            const data = await response.json();
            showAlert('uploadResult', `❌ Delete failed: ${data.detail || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        let errorMsg = 'Failed to delete job';

        if (error.name === 'AbortError') {
            errorMsg += ' (request timed out)';
        } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
            errorMsg += ' (network error)';
        } else {
            errorMsg += `: ${error.message}`;
        }

        showAlert('uploadResult', `❌ ${errorMsg}`, 'danger');
    }
}

// Download failed and skipped items as CSV
async function downloadFailedItems(jobId) {
    try {
        const response = await fetch(`/api/thema-ads/jobs/${jobId}/failed-items-csv`);

        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `job_${jobId}_failed_and_skipped_items.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } else {
            const data = await response.json();
            showAlert('uploadResult', `❌ Download failed: ${data.detail || 'Unknown error'}`, 'danger');
        }
    } catch (error) {
        console.error('Error downloading failed items:', error);
        showAlert('uploadResult', `❌ Download failed: ${error.message}`, 'danger');
    }
}

// Helper functions
function getStatusBadge(status) {
    const badges = {
        'pending': '<span class="badge bg-secondary">Pending</span>',
        'running': '<span class="badge bg-primary">Running</span>',
        'paused': '<span class="badge bg-warning">Paused</span>',
        'completed': '<span class="badge bg-success">Completed</span>',
        'failed': '<span class="badge bg-danger">Failed</span>',
        'cancelled': '<span class="badge bg-dark">Cancelled</span>'
    };
    return badges[status] || '<span class="badge bg-secondary">Unknown</span>';
}

function getStatusClass(status) {
    const classes = {
        'pending': 'bg-secondary',
        'running': 'bg-primary',
        'paused': 'bg-warning',
        'completed': 'bg-success',
        'failed': 'bg-danger',
        'cancelled': 'bg-dark'
    };
    return classes[status] || 'bg-secondary';
}

function formatDate(dateString) {
    if (!dateString) return '-';
    // Database stores timestamps in UTC, append 'Z' to indicate UTC timezone
    const date = new Date(dateString + 'Z');
    return date.toLocaleString();
}

function showAlert(elementId, message, type) {
    const element = document.getElementById(elementId);
    element.innerHTML = `<div class="alert alert-${type} alert-dismissible fade show" role="alert">
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshJobs();
});
