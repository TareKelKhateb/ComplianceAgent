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



// Status
const statusIndicator = $('#status-indicator');

// Toast
const toastContainer = $('#toast-container');

// ===================================================================
// State
// ===================================================================
let selectedFiles = [];

// ===================================================================
// View / Tab Switching
// ===================================================================
const VIEW_META = {
    data: { title: 'Data Ingestion', subtitle: 'Scrape URLs or upload compliance documents for processing' },
    approvals: { title: 'Regulatory Approvals', subtitle: 'Review and approve modifications to active law segments' },
    chatbot: { title: 'Compliance Assistant', subtitle: 'Ask questions about regulatory policies, compliance requirements, and legal documents' },
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
    if (viewName === 'approvals') {
        loadPendingApprovals();
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
// Approvals Tab (Diff Review & Approval)
// ===================================================================

const approvalsList = $('#approvals-list');
const approvalsEmpty = $('#approvals-empty');
const pendingCountEl = $('#pending-count');

async function loadPendingApprovals() {
    try {
        approvalsList.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-secondary);"><div class="loading-spinner" style="margin: 0 auto 16px;"></div>Loading pending approvals...</div>';
        approvalsEmpty.style.display = 'none';

        const response = await fetch(`${API_BASE}/api/approvals`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const chunks = await response.json();

        renderApprovals(chunks);
    } catch (err) {
        showToast('error', 'Failed to load approvals', err.message);
        approvalsList.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error);">Error loading approvals: ${err.message}</div>`;
    }
}

function renderApprovals(chunks) {
    approvalsList.innerHTML = '';
    pendingCountEl.textContent = chunks.length;

    if (chunks.length === 0) {
        approvalsEmpty.style.display = 'flex';
        return;
    }

    approvalsEmpty.style.display = 'none';

    chunks.forEach(chunk => {
        const card = document.createElement('div');
        card.className = 'approval-card';
        card.id = `approval-card-${chunk.id}`;

        const isModified = chunk.change_type === 'modified';
        const badgeClass = isModified ? 'badge-modified' : 'badge-added';
        const badgeText = isModified ? 'Modified' : 'Added';

        // Meta text
        const pageText = chunk.page_number ? `Page ${chunk.page_number}` : 'Unknown Page';
        const metaText = `Segment Index: ${chunk.chunk_index} | ${pageText} | Version ${chunk.version}`;

        // Construct HTML for comparison
        let diffHtml = '';
        if (isModified) {
            diffHtml = `
                <div class="diff-container side-by-side">
                    <div class="diff-box diff-deleted">
                        <div class="diff-box-header">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                            <span>Previous Version</span>
                        </div>
                        <div class="diff-box-content">${escapeHTML(chunk.old_content || '')}</div>
                    </div>
                    <div class="diff-box diff-inserted">
                        <div class="diff-box-header">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20,6 9,17 4,12"/></svg>
                            <span>Proposed Version</span>
                        </div>
                        <div class="diff-box-content">${escapeHTML(chunk.content)}</div>
                    </div>
                </div>
            `;
        } else {
            diffHtml = `
                <div class="diff-container">
                    <div class="diff-box diff-inserted">
                        <div class="diff-box-header">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20,6 9,17 4,12"/></svg>
                            <span>Proposed New Provision</span>
                        </div>
                        <div class="diff-box-content">${escapeHTML(chunk.content)}</div>
                    </div>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="approval-card-header">
                <div class="approval-card-title-group">
                    <div class="approval-doc-title">${escapeHTML(chunk.title || 'Untitled Document')}</div>
                    <div class="approval-doc-meta">${metaText}</div>
                </div>
                <div class="approval-badge-group">
                    <span class="badge ${badgeClass}">${badgeText}</span>
                </div>
            </div>
            <div class="approval-card-body">
                ${diffHtml}
                
                <!-- Policy Impact Analysis Section -->
                <div class="policy-analysis-section" id="analysis-section-${chunk.id}">
                    <div class="analysis-section-header">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                        </svg>
                        <span>Policy Impact Analysis</span>
                    </div>
                    <div class="analysis-section-content" id="analysis-content-${chunk.id}" dir="auto">
                        <div class="analysis-loading">
                            <div class="loading-spinner-small"></div>
                            <span>Analyzing policy impact...</span>
                        </div>
                    </div>
                    <div class="analysis-sources" id="analysis-sources-${chunk.id}" style="display: none;"></div>
                </div>
            </div>
            <div class="approval-card-actions">
                <button type="button" class="btn btn-primary btn-approve" data-id="${chunk.id}">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                        <polyline points="22,4 12,14.01 9,11.01"/>
                    </svg>
                    <span>Approve Change</span>
                </button>
            </div>
        `;

        // Wire up approve click
        card.querySelector('.btn-approve').addEventListener('click', async (e) => {
            const btn = e.currentTarget;
            btn.disabled = true;
            await submitApproval(chunk.id, card);
        });

        approvalsList.appendChild(card);
        
        // Trigger policy impact analysis from chatbot
        loadPolicyAnalysis(chunk);
    });
}

async function loadPolicyAnalysis(chunk) {
    const contentEl = $(`#analysis-content-${chunk.id}`);
    const sourcesEl = $(`#analysis-sources-${chunk.id}`);
    if (!contentEl) return;

    try {
        const prompt = `You are an elite Regulatory Compliance & Policy Mapping Assistant.
Please analyze how the following regulation change affects our internal company policies and guidelines.
We need to map this law segment to our internal policy guidelines to identify any necessary adjustments or compliance gaps.

CRITICAL INSTRUCTION: You MUST write the entire analysis, headings, comparisons, and explanation in Arabic (اللغة العربية). Do NOT write any part of the answer in English. Ensure that technical, financial, and compliance terminology matches professional Arabic standards.

Here are the details of the regulation change:
- Regulation Document Title: ${chunk.title || 'Untitled Document'}
- Change Type: ${chunk.change_type === 'modified' ? 'Modification of an existing segment' : 'Addition of a new segment'}
- Segment Index: ${chunk.chunk_index}
- Page Number: ${chunk.page_number || 'N/A'}
- Regulation Version: ${chunk.version}
- Document ID: ${chunk.doc_id}

Proposed Segment Content (Current Proposed Version):
"""
${chunk.content}
"""
${chunk.change_type === 'modified' ? `
Previous Segment Content (Old Version):
"""
${chunk.old_content}
"""` : ''}

Please perform the following tasks in Arabic:
1. Search our internal company policies for similar or related rules.
2. Compare the proposed regulation change with our internal policies.
3. Explicitly identify any gaps, conflicts, or required adjustments in our internal policies to remain compliant with this new regulation.
4. Formulate the response as a clear, structured compliance mapping report (including tables if necessary).`;

        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: prompt,
                thread_id: 'approval_' + chunk.id + '_' + Date.now() // Unique thread per evaluation
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        
        // Render answer markdown
        contentEl.innerHTML = renderMarkdown(data.answer);
        
        // Render matching source documents evaluated inside a collapsible dropdown
        if (data.sources_used && data.sources_used.length > 0) {
            let sourcesHtml = `
                <div class="chat-sources" style="margin-top: 12px;">
                    <button class="chat-sources-toggle" onclick="toggleSources(this)">
                        <span>📎 ${data.sources_used.length} Matching Policies Evaluated</span>
                        <span class="toggle-arrow">▼</span>
                    </button>
                    <div class="chat-sources-list" style="margin-top: 10px;">
            `;
            
            data.sources_used.forEach((src, idx) => {
                const uniqueId = `analysis-src-${chunk.id}-${idx}`;
                const truncatedContent = src.content.length > 180 
                    ? escapeHTML(src.content.substring(0, 180)) + '...'
                    : escapeHTML(src.content);
                const hasMore = src.content.length > 180;

                sourcesHtml += `
                    <div class="analysis-source-item" onclick="toggleSourceExpand(this)">
                        <div class="analysis-source-header">
                            <span class="analysis-source-title">📄 Policy ID: ${escapeHTML(src.source_id)}</span>
                        </div>
                        <div class="source-chip-content truncated" id="${uniqueId}">
                            ${truncatedContent}
                            ${hasMore ? `<span class="source-chip-expand">Show more</span>` : ''}
                        </div>
                        <div class="source-chip-full-content" style="display:none;">${escapeHTML(src.content)}</div>
                    </div>
                `;
            });
            
            sourcesHtml += `
                    </div>
                </div>
            `;
            sourcesEl.innerHTML = sourcesHtml;
            sourcesEl.style.display = 'block';
        } else {
            sourcesEl.style.display = 'none';
        }

    } catch (err) {
        contentEl.innerHTML = `
            <div class="analysis-error">
                <span>⚠️ Failed to load analysis: ${escapeHTML(err.message)}</span>
                <button type="button" class="btn btn-secondary btn-retry" style="padding: 4px 10px; font-size: 0.75rem; width: auto;" onclick="retryPolicyAnalysis(${JSON.stringify(chunk).replace(/"/g, '&quot;')})">Retry</button>
            </div>
        `;
    }
}

window.retryPolicyAnalysis = function(chunk) {
    const contentEl = $(`#analysis-content-${chunk.id}`);
    const sourcesEl = $(`#analysis-sources-${chunk.id}`);
    if (contentEl) {
        contentEl.innerHTML = `
            <div class="analysis-loading">
                <div class="loading-spinner-small"></div>
                <span>Analyzing policy impact...</span>
            </div>
        `;
    }
    if (sourcesEl) {
        sourcesEl.style.display = 'none';
    }
    loadPolicyAnalysis(chunk);
};

async function submitApproval(chunkId, cardElement) {
    try {
        const response = await fetch(`${API_BASE}/api/approvals/${chunkId}/approve`, {
            method: 'POST'
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || `HTTP ${response.status}`);
        }

        // Animate out
        cardElement.classList.add('removing');
        showToast('success', 'Approved Successfully', 'Regulatory chunk has been marked as active and approved.');
        
        setTimeout(() => {
            cardElement.remove();
            
            // Recalculate count
            const remainingCount = approvalsList.querySelectorAll('.approval-card').length;
            pendingCountEl.textContent = remainingCount;
            if (remainingCount === 0) {
                approvalsEmpty.style.display = 'flex';
            }
        }, 400); // match CSS transition-slow duration

    } catch (err) {
        showToast('error', 'Approval Failed', err.message);
        cardElement.querySelector('.btn-approve').disabled = false;
    }
}

function escapeHTML(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ===================================================================
// Chatbot Logic
// ===================================================================
const chatMessagesEl = $('#chat-messages');
const chatInputEl = $('#chat-input');
const chatSendBtn = $('#chat-send-btn');

// Generate unique thread ID for LangGraph session
const chatThreadId = 'thread_' + Math.random().toString(36).substring(2, 15);
let isChatLoading = false;

// Auto-resize chat textarea
window.autoResizeChatInput = function(el) {
    el.style.height = 'auto';
    el.style.height = (el.scrollHeight) + 'px';
};

// Keyboard handler
window.handleChatKeydown = function(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage();
    }
};

// Quick questions handler
window.sendQuickQuestion = function(btn) {
    if (isChatLoading) return;
    const text = btn.textContent.trim();
    chatInputEl.value = text;
    autoResizeChatInput(chatInputEl);
    sendChatMessage();
};

// Send message to backend proxy
window.sendChatMessage = async function() {
    const text = chatInputEl.value.trim();
    if (!text || isChatLoading) return;

    isChatLoading = true;
    chatInputEl.value = '';
    autoResizeChatInput(chatInputEl);
    chatInputEl.disabled = true;
    chatSendBtn.disabled = true;

    // Remove welcome screen if it's there
    const welcomeScreen = $('#chat-welcome');
    if (welcomeScreen) {
        welcomeScreen.remove();
    }

    // Render User Message
    renderMessage('user', text);
    scrollToBottom();

    // Show typing indicator
    showTypingIndicator();
    scrollToBottom();

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: text,
                thread_id: chatThreadId
            })
        });

        const data = await response.json();

        // Remove typing indicator
        removeTypingIndicator();

        if (!response.ok) {
            throw new Error(data.detail || `HTTP ${response.status}`);
        }

        // Render Bot Message
        renderMessage('bot', data.answer, data.sources_used, data.routed_destinations);
    } catch (err) {
        removeTypingIndicator();
        renderErrorMessage(err.message || 'Something went wrong.');
    } finally {
        isChatLoading = false;
        chatInputEl.disabled = false;
        chatSendBtn.disabled = false;
        chatInputEl.focus();
        scrollToBottom();
    }
};

function renderMessage(sender, text, sources = [], routes = []) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-msg ${sender}`;

    let avatarSvg = '';
    if (sender === 'user') {
        avatarSvg = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
            </svg>
        `;
    } else {
        avatarSvg = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
        `;
    }

    const avatarHtml = `<div class="chat-msg-avatar">${avatarSvg}</div>`;
    
    let contentHtml = `<div class="chat-msg-content">${sender === 'user' ? escapeHTML(text) : renderMarkdown(text)}</div>`;

    // Add route badges & sources if bot message
    let extraHtml = '';
    if (sender === 'bot') {
        let routesHtml = '';
        if (routes && routes.length > 0) {
            const badges = routes.map(r => `<span class="route-badge">📁 ${escapeHTML(r.replace('_', ' '))}</span>`).join('');
            routesHtml = `<div class="chat-route-badges">${badges}</div>`;
        }

        let sourcesHtml = '';
        if (sources && sources.length > 0) {
            const chips = sources.map((src, idx) => {
                const uniqueId = `src-${Date.now()}-${idx}`;
                const truncatedContent = src.content.length > 200 
                    ? escapeHTML(src.content.substring(0, 200)) + '...'
                    : escapeHTML(src.content);
                const hasMore = src.content.length > 200;

                return `
                    <div class="source-chip" onclick="toggleSourceExpand(this)">
                        <div class="source-chip-header">
                            <span class="source-chip-id">📄 ${escapeHTML(src.source_id)}</span>
                        </div>
                        <div class="source-chip-content truncated" id="${uniqueId}">
                            ${truncatedContent}
                            ${hasMore ? `<span class="source-chip-expand">Show more</span>` : ''}
                        </div>
                        <div class="source-chip-full-content" style="display:none;">${escapeHTML(src.content)}</div>
                    </div>
                `;
            }).join('');

            sourcesHtml = `
                <div class="chat-sources">
                    <button class="chat-sources-toggle" onclick="toggleSources(this)">
                        <span>📎 ${sources.length} Sources Referenced</span>
                        <span class="toggle-arrow">▼</span>
                    </button>
                    <div class="chat-sources-list">
                        ${chips}
                    </div>
                </div>
            `;
        }
        
        extraHtml = routesHtml + sourcesHtml;
    }

    msgDiv.innerHTML = `
        ${sender === 'bot' ? avatarHtml : ''}
        <div class="chat-msg-bubble">
            ${contentHtml}
            ${extraHtml}
        </div>
        ${sender === 'user' ? avatarHtml : ''}
    `;

    chatMessagesEl.appendChild(msgDiv);
}

function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'chat-typing';
    indicator.id = 'chat-typing-indicator';
    indicator.innerHTML = `
        <div class="chat-msg-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
        </div>
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    chatMessagesEl.appendChild(indicator);
}

function removeTypingIndicator() {
    const indicator = $('#chat-typing-indicator');
    if (indicator) {
        indicator.remove();
    }
}

function renderErrorMessage(msg) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'chat-msg bot';
    errorDiv.innerHTML = `
        <div class="chat-msg-avatar" style="background: rgba(231, 76, 60, 0.1); border-color: rgba(231, 76, 60, 0.3); color: var(--error);">
            ⚠️
        </div>
        <div class="chat-msg-bubble">
            <div class="chat-error">
                <span><strong>Error:</strong> ${escapeHTML(msg)}</span>
            </div>
        </div>
    `;
    chatMessagesEl.appendChild(errorDiv);
}

window.toggleSources = function(btn) {
    const parent = btn.closest('.chat-sources');
    const list = parent.querySelector('.chat-sources-list');
    const isExpanded = btn.classList.toggle('expanded');
    list.classList.toggle('visible', isExpanded);
};

window.toggleSourceExpand = function(chip) {
    const content = chip.querySelector('.source-chip-content');
    const fullContentEl = chip.querySelector('.source-chip-full-content');
    
    if (!content || !fullContentEl) return;
    
    if (content.classList.contains('truncated')) {
        content.classList.remove('truncated');
        content.classList.add('expanded');
        content.innerHTML = fullContentEl.innerHTML + ` <span class="source-chip-expand">Show less</span>`;
    } else {
        content.classList.add('truncated');
        content.classList.remove('expanded');
        const originalText = fullContentEl.innerHTML;
        const truncatedText = originalText.length > 200 
            ? originalText.substring(0, 200) + '...'
            : originalText;
        content.innerHTML = truncatedText + ` <span class="source-chip-expand">Show more</span>`;
    }
};

function scrollToBottom() {
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function renderMarkdown(md) {
    if (!md) return '';
    
    // Escape HTML first
    let html = escapeHTML(md);

    // LaTeX styled colored text (e.g. \color{red}{\text{...}})
    html = html.replace(/\$\\color\{([a-zA-Z]+)\}\{\\text\{([^\}]+)\}\}\$/g, (match, color, text) => {
        const mappedColor = color === 'red' ? 'var(--error)' : (color === 'green' ? 'var(--success)' : color);
        return `<span style="color: ${mappedColor}; font-weight: 600;">${text}</span>`;
    });

    // Parse Markdown tables before separating paragraphs
    const tableRegex = /^(?:\|[^\n]+\|\r?\n){2,}(?:\|[^\n]+\|(?:\r?\n|$))*/gm;
    html = html.replace(tableRegex, (tableBlock) => {
        const rows = tableBlock.trim().split(/\r?\n/);
        if (rows.length < 2) return tableBlock;
        
        let tableHtml = '<div style="overflow-x:auto; margin: 12px 0;"><table class="chat-markdown-table"><thead>';
        // Process header row
        const headerCols = rows[0].split('|').map(c => c.trim()).filter((c, i, arr) => i > 0 && i < arr.length - 1);
        tableHtml += '<tr>' + headerCols.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
        
        // Process data rows (skip rows[1] which is the separator)
        for (let i = 2; i < rows.length; i++) {
            const cols = rows[i].split('|').map(c => c.trim()).filter((c, i, arr) => i > 0 && i < arr.length - 1);
            if (cols.length === 0) continue;
            tableHtml += '<tr>' + cols.map(c => `<td>${c}</td>`).join('') + '</tr>';
        }
        tableHtml += '</tbody></table></div>';
        return tableHtml;
    });

    // Code blocks
    html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

    // Inline code
    html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');

    // Headings
    html = html.replace(/^#### (.*?)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');

    // Blockquotes
    html = html.replace(/^&gt;[ \t]?(.*?)$/gm, '<blockquote>$1</blockquote>');

    // Lists
    html = html.replace(/^\s*[-*+]\s+(.*?)$/gm, '<ul><li>$1</li></ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, ''); // Merge consecutive ul blocks

    html = html.replace(/^\s*\d+\.\s+(.*?)$/gm, '<ol><li>$1</li></ol>');
    html = html.replace(/<\/ol>\s*<ol>/g, ''); // Merge consecutive ol blocks

    // Bold
    html = html.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*([^\*]+)\*/g, '<em>$1</em>');
    html = html.replace(/_([^_]+)_/g, '<em>$1</em>');

    // Paragraphs & Line breaks:
    const lines = html.split(/\n/);
    let output = [];
    let inParagraph = false;

    for (let line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
            if (inParagraph) {
                output.push('</p>');
                inParagraph = false;
            }
            continue;
        }

        // If block-level tag, close paragraph
        if (/^<(h\d|pre|blockquote|ul|ol|li|table|thead|tbody|tr|th|td|div)/i.test(trimmed)) {
            if (inParagraph) {
                output.push('</p>');
                inParagraph = false;
            }
            output.push(line);
        } else {
            if (!inParagraph) {
                output.push('<p>');
                inParagraph = true;
            } else {
                output.push('<br>');
            }
            output.push(line);
        }
    }
    if (inParagraph) {
        output.push('</p>');
    }

    return output.join('\n')
        .replace(/<p>\s*<\/p>/g, '')
        .replace(/\n\s*\n/g, '\n');
}

// ===================================================================
// Initialization
// ===================================================================
switchView('data');

