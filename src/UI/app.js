/**
 * Compliance Agent Dashboard — Frontend Logic
 * =============================================
 * Handles:
 *   - Tab/view switching
 *   - URL scraping form submission
 *   - Multi-file drag-and-drop / upload
 *   - Log file viewing with auto-refresh
 *   - Toast notifications
 *   - Service health checks
 */

// ===================================================================
// Configuration
// ===================================================================
const API_BASE = '';  // Same origin
const LOG_REFRESH_INTERVAL = 5000;  // ms

// ===================================================================
// DOM References
// ===================================================================
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Navigation
const navItems = $$('.nav-item');

// Header
const pageTitle = $('#page-title');
const pageSubtitle = $('#page-subtitle');
const headerTime = $('#header-time');

// Scrape form
const scrapeForm = $('#scrape-form');
const scrapeUrl = $('#scrape-url');
const scrapeCrawl = $('#scrape-crawl');
const scrapeLimit = $('#scrape-limit');
const crawlLabel = $('#crawl-label');
const btnScrape = $('#btn-scrape');
const scrapeLoading = $('#scrape-loading');

// Upload
const dropZone = $('#drop-zone');
const fileInput = $('#file-input');
const fileList = $('#file-list');
const btnUpload = $('#btn-upload');
const uploadLoading = $('#upload-loading');

// Logs
const logFileSelect = $('#log-file-select');
const logTailLines = $('#log-tail-lines');
const btnRefreshLog = $('#btn-refresh-log');
const logAutoRefresh = $('#log-auto-refresh');
const logViewer = $('#log-viewer');

// Status
const statusIndicator = $('#status-indicator');

// Toast
const toastContainer = $('#toast-container');

// ===================================================================
// State
// ===================================================================
let selectedFiles = [];
let logRefreshTimer = null;

// ===================================================================
// View / Tab Switching
// ===================================================================
const VIEW_META = {
    data: { title: 'Data Ingestion', subtitle: 'Scrape URLs or upload compliance documents for processing' },
    logs: { title: 'System Logs', subtitle: 'Monitor orchestrator activity and email notifications' },
};

function switchView(viewName) {
    // Update nav
    navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewName);
    });

    // Update views
    $$('.view').forEach(v => {
        v.classList.toggle('active', v.id === `view-${viewName}`);
    });

    // Update header
    const meta = VIEW_META[viewName] || {};
    pageTitle.textContent = meta.title || viewName;
    pageSubtitle.textContent = meta.subtitle || '';

    // Trigger view-specific init
    if (viewName === 'logs') {
        loadLogFileList();
    }
}

navItems.forEach(item => {
    item.addEventListener('click', () => switchView(item.dataset.view));
});

// ===================================================================
// Clock
// ===================================================================
function updateClock() {
    const now = new Date();
    headerTime.textContent = now.toLocaleString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}
updateClock();
setInterval(updateClock, 1000);

// ===================================================================
// Toast Notifications
// ===================================================================
function showToast(type, title, message, duration = 6000) {
    const icons = {
        success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22,4 12,14.01 9,11.01"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-icon">${icons[type] || icons.info}</div>
        <div class="toast-body">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
    `;

    const closeBtn = toast.querySelector('.toast-close');
    const removeToast = () => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    };
    closeBtn.addEventListener('click', removeToast);

    toastContainer.appendChild(toast);

    if (duration > 0) {
        setTimeout(removeToast, duration);
    }
}

// ===================================================================
// URL Scraping
// ===================================================================
scrapeCrawl.addEventListener('change', () => {
    crawlLabel.textContent = scrapeCrawl.checked ? 'On' : 'Off';
});

scrapeForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const url = scrapeUrl.value.trim();
    if (!url) return;

    // Show loading
    scrapeLoading.classList.add('active');
    btnScrape.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/api/scrape`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                is_crawl: scrapeCrawl.checked,
                limit: parseInt(scrapeLimit.value, 10) || 1,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || `HTTP ${response.status}`);
        }

        if (data.review_url) {
            showToast('success', 'Scraping Complete',
                `Review session created. <a href="${data.review_url}" target="_blank" style="color: var(--gold); font-weight: 600;">Open Review →</a><br>An email notification has been sent.`,
                10000
            );
        } else {
            showToast('success', 'Scraping Started', data.message);
        }

        scrapeForm.reset();
        crawlLabel.textContent = 'Off';

    } catch (err) {
        showToast('error', 'Scraping Failed', err.message);
    } finally {
        scrapeLoading.classList.remove('active');
        btnScrape.disabled = false;
    }
});

// ===================================================================
// File Upload — Drag & Drop + File Selection
// ===================================================================

// Click to browse
dropZone.addEventListener('click', () => fileInput.click());

// Drag events
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files).filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if (files.length === 0) {
        showToast('warning', 'Invalid Files', 'Only PDF files are accepted.');
        return;
    }
    addFiles(files);
});

// File input change
fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files);
    addFiles(files);
    fileInput.value = ''; // Reset so same file can be re-added
});

function addFiles(files) {
    for (const file of files) {
        // Avoid duplicates by name
        if (!selectedFiles.find(f => f.name === file.name && f.size === file.size)) {
            selectedFiles.push(file);
        }
    }
    renderFileList();
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function renderFileList() {
    fileList.innerHTML = '';
    selectedFiles.forEach((file, idx) => {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.innerHTML = `
            <div class="file-item-icon">PDF</div>
            <div class="file-item-info">
                <div class="file-item-name" title="${file.name}">${file.name}</div>
                <div class="file-item-size">${formatFileSize(file.size)}</div>
            </div>
            <button class="file-item-remove" data-index="${idx}" aria-label="Remove file" title="Remove">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        `;
        item.querySelector('.file-item-remove').addEventListener('click', () => removeFile(idx));
        fileList.appendChild(item);
    });

    btnUpload.disabled = selectedFiles.length === 0;
}

// Upload button
btnUpload.addEventListener('click', async () => {
    if (selectedFiles.length === 0) return;

    uploadLoading.classList.add('active');
    btnUpload.disabled = true;

    try {
        const formData = new FormData();
        for (const file of selectedFiles) {
            formData.append('files', file);
        }

        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || `HTTP ${response.status}`);
        }

        if (data.review_url) {
            showToast('success', 'Upload Complete',
                `${data.file_count} file(s) uploaded. <a href="${data.review_url}" target="_blank" style="color: var(--gold); font-weight: 600;">Open Review →</a><br>An email notification has been sent.`,
                10000
            );
        } else {
            showToast('success', 'Upload Complete', data.message);
        }

        // Clear files
        selectedFiles = [];
        renderFileList();

    } catch (err) {
        showToast('error', 'Upload Failed', err.message);
    } finally {
        uploadLoading.classList.remove('active');
        btnUpload.disabled = selectedFiles.length === 0;
    }
});

// ===================================================================
// Logs
// ===================================================================
async function loadLogFileList() {
    try {
        const response = await fetch(`${API_BASE}/api/logs`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const logs = await response.json();

        // Preserve current selection
        const currentValue = logFileSelect.value;
        logFileSelect.innerHTML = '<option value="">Select a log file…</option>';

        for (const log of logs) {
            const opt = document.createElement('option');
            opt.value = log.name;
            const sizeStr = log.size_bytes < 1024
                ? `${log.size_bytes} B`
                : `${(log.size_bytes / 1024).toFixed(1)} KB`;
            opt.textContent = `${log.name} (${sizeStr})`;
            logFileSelect.appendChild(opt);
        }

        // Restore selection
        if (currentValue && logs.find(l => l.name === currentValue)) {
            logFileSelect.value = currentValue;
        }
    } catch (err) {
        console.error('Failed to load log file list:', err);
    }
}

async function loadLogContent() {
    const filename = logFileSelect.value;
    if (!filename) {
        logViewer.innerHTML = `
            <div class="log-empty">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>
                <p>Select a log file to view its contents</p>
            </div>
        `;
        return;
    }

    const tail = parseInt(logTailLines.value, 10) || 200;

    try {
        const response = await fetch(`${API_BASE}/api/logs/${encodeURIComponent(filename)}?tail=${tail}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        // Syntax highlight the log content
        const highlighted = highlightLog(data.content);
        logViewer.innerHTML = `<pre>${highlighted}</pre>`;

        // Auto-scroll to bottom
        logViewer.scrollTop = logViewer.scrollHeight;
    } catch (err) {
        logViewer.innerHTML = `<pre style="color: #F85149;">Error loading log: ${err.message}</pre>`;
    }
}

function highlightLog(content) {
    return content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .split('\n')
        .map(line => {
            if (/\[ERROR\]|ERROR|❌|FAIL/i.test(line)) {
                return `<span class="log-line-error">${line}</span>`;
            }
            if (/\[WARNING\]|WARNING|⚠️/i.test(line)) {
                return `<span class="log-line-warning">${line}</span>`;
            }
            if (/\[DEBUG\]/i.test(line)) {
                return `<span class="log-line-debug">${line}</span>`;
            }
            if (/\[INFO\]|INFO|✅|📄|📋|⚡|🔑/i.test(line)) {
                return `<span class="log-line-info">${line}</span>`;
            }
            return line;
        })
        .join('\n');
}

logFileSelect.addEventListener('change', loadLogContent);
btnRefreshLog.addEventListener('click', () => {
    loadLogFileList();
    loadLogContent();
});

logAutoRefresh.addEventListener('change', () => {
    if (logAutoRefresh.checked) {
        logRefreshTimer = setInterval(() => {
            loadLogContent();
        }, LOG_REFRESH_INTERVAL);
        showToast('info', 'Auto-Refresh', `Logs will refresh every ${LOG_REFRESH_INTERVAL / 1000}s.`, 3000);
    } else {
        clearInterval(logRefreshTimer);
        logRefreshTimer = null;
    }
});

// ===================================================================
// Health Check
// ===================================================================
async function checkHealth() {
    const dot = statusIndicator.querySelector('.status-dot');
    const text = statusIndicator.querySelector('.status-text');

    try {
        const response = await fetch(`${API_BASE}/api/health`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const status = await response.json();

        const allOk = status.user_adjustments_api === 'ok' && status.scraper_api === 'ok';
        const someOk = status.user_adjustments_api === 'ok' || status.scraper_api === 'ok';

        if (allOk) {
            dot.className = 'status-dot ok';
            text.textContent = 'All services online';
        } else if (someOk) {
            dot.className = 'status-dot partial';
            const parts = [];
            if (status.user_adjustments_api !== 'ok') parts.push('Adjustments API');
            if (status.scraper_api !== 'ok') parts.push('Scraper');
            text.textContent = `${parts.join(', ')} offline`;
        } else {
            dot.className = 'status-dot error';
            text.textContent = 'Services offline';
        }
    } catch {
        dot.className = 'status-dot error';
        text.textContent = 'API unreachable';
    }
}

// Check health on load and every 30s
checkHealth();
setInterval(checkHealth, 30000);

// ===================================================================
// Initialization
// ===================================================================
switchView('data');
