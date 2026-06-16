// app.js

// ==========================================================================
// Global State
// ==========================================================================
let sessionId = "";
let sessionInfo = null;
let documents = []; // Flat list of ReviewDocument objects
let activeDocIdx = -1;
let debounceTimer = null;
let pendingSave = null;
let mappings = []; // Global mappings cache

// BASE URL for API endpoints (handles relative paths correctly)
const API_BASE = ""; 

// ==========================================================================
// Initialization & Session Loading
// ==========================================================================
document.addEventListener("DOMContentLoaded", async () => {
    sessionId = getSessionIdFromUrl();
    if (!sessionId) {
        showNoSessionState();
        return;
    }
    
    document.getElementById("session-id-text").textContent = sessionId;
    await loadSessionData();
});

function getSessionIdFromUrl() {
    const pathname = window.location.pathname; // Expected: /review/session_id
    const parts = pathname.split('/');
    if (parts.length >= 3 && parts[1] === 'review' && parts[2]) {
        return parts[2];
    }
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('session');
}

function showNoSessionState() {
    document.getElementById("loading-overlay").classList.add("hidden");
    const errContainer = document.getElementById("error-container");
    errContainer.classList.remove("hidden");
    
    errContainer.innerHTML = `
        <span class="error-icon">🔍</span>
        <h2>No Active Session</h2>
        <p>Please enter a session ID to review compliance documents.</p>
        <div style="margin-top: 1rem; display: flex; gap: 0.5rem; justify-content: center;">
            <input type="text" id="manual-session-id" class="input-field" placeholder="Enter session ID..." style="max-width: 250px;">
            <button class="btn btn-primary" onclick="loadManualSession()">Load</button>
        </div>
    `;
}

function loadManualSession() {
    const inputVal = document.getElementById("manual-session-id").value.trim();
    if (inputVal) {
        window.location.href = `/review/${inputVal}`;
    }
}

async function loadSessionData() {
    showLoading();
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
        if (!response.ok) {
            throw new Error(`Session not found (Status: ${response.status})`);
        }
        const data = await response.json();
        sessionInfo = data.session;
        
        // The API returns documents in groups (list[list[dict]]). 
        // We will flatten them for editing indexing but keep track of indices.
        // Wait, app.py also has a flat GET /api/sessions/{session_id}/documents endpoint.
        // Let's use the flat list endpoint to be 100% sure we match backend indexing.
        const docsResponse = await fetch(`${API_BASE}/api/sessions/${sessionId}/documents`);
        if (!docsResponse.ok) {
            throw new Error("Failed to load session documents");
        }
        documents = await docsResponse.json();
        
        updateSessionBadge();
        renderDocumentList();
        updateProgressAndValidation();
        
        // Select first document by default
        if (documents.length > 0) {
            selectDocument(0);
        }
        
        document.getElementById("dashboard-content").classList.remove("hidden");
        document.getElementById("action-bar").classList.remove("hidden");
        hideLoading();
    } catch (error) {
        console.error(error);
        hideLoading();
        document.getElementById("error-container").classList.remove("hidden");
        document.getElementById("error-message").textContent = error.message;
    }
}

function updateSessionBadge() {
    const status = sessionInfo.status;
    const badge = document.getElementById("session-status-badge");
    badge.className = `badge badge-${status}`;
    badge.textContent = status;
    
    // Disable editing if session is not pending
    if (status !== 'pending') {
        disableAllInputs();
    }
}

function disableAllInputs() {
    const inputs = document.querySelectorAll(".input-field");
    inputs.forEach(input => input.setAttribute("disabled", "true"));
    document.getElementById("btn-approve").setAttribute("disabled", "true");
    document.getElementById("btn-reject").setAttribute("disabled", "true");
    showToast(`This session is ${sessionInfo.status.toUpperCase()} and cannot be edited.`, "info");
}

function showLoading() {
    document.getElementById("loading-overlay").classList.remove("hidden");
}

function hideLoading() {
    document.getElementById("loading-overlay").classList.add("hidden");
}

// ==========================================================================
// Sidebar Document Listing & Filtering
// ==========================================================================
function renderDocumentList() {
    const container = document.getElementById("doc-list-container");
    container.innerHTML = "";
    
    documents.forEach((doc, idx) => {
        const card = createDocCard(doc, idx);
        container.appendChild(card);
    });
}

function createDocCard(doc, idx) {
    const card = document.createElement("div");
    card.className = "doc-card";
    card.id = `doc-card-${idx}`;
    card.onclick = () => selectDocument(idx);
    
    // Validation status check
    const isValid = validateDocument(doc);
    card.classList.add(isValid ? "valid-state" : "invalid-state");
    
    // Badges HTML
    let badgesHtml = "";
    if (doc.cached) {
        badgesHtml += `<span class="badge badge-success">CACHED</span> `;
    }
    
    if (isValid) {
        badgesHtml += `<span class="badge badge-complete">VALID</span>`;
    } else {
        badgesHtml += `<span class="badge badge-warning">INCOMPLETE</span>`;
    }
    
    // Display ID (important first)
    const idDisplay = doc.id 
        ? `<span class="doc-card-id">${escapeHtml(doc.id)}</span>` 
        : `<span class="doc-card-id missing">[NO ID ASSIGNED]</span>`;
        
    const titleDisplay = doc.title || doc.pdf_name || "Untitled Document";
    
    // Extract file name or short URL
    let displayUrl = "";
    try {
        const urlObj = new URL(doc.file_url);
        displayUrl = urlObj.pathname.split('/').pop() || urlObj.hostname;
    } catch {
        displayUrl = doc.file_url;
    }

    card.innerHTML = `
        <div class="doc-card-header">
            ${idDisplay}
            <div class="card-badges">${badgesHtml}</div>
        </div>
        <div class="doc-card-title">${escapeHtml(titleDisplay)}</div>
        <div class="doc-card-footer">
            <span class="doc-card-url" title="${escapeHtml(doc.file_url)}">🔗 ${escapeHtml(displayUrl)}</span>
            <span class="text-muted">Doc #${idx + 1}</span>
        </div>
    `;
    
    return card;
}

function updateDocumentCard(idx) {
    const doc = documents[idx];
    const oldCard = document.getElementById(`doc-card-${idx}`);
    if (!oldCard) return;
    
    const newCard = createDocCard(doc, idx);
    if (idx === activeDocIdx) {
        newCard.classList.add("active");
    }
    
    oldCard.replaceWith(newCard);
}

function filterDocuments() {
    const query = document.getElementById("doc-search").value.toLowerCase();
    const filter = document.getElementById("doc-status-filter").value;
    
    documents.forEach((doc, idx) => {
        const card = document.getElementById(`doc-card-${idx}`);
        if (!card) return;
        
        const matchesSearch = 
            (doc.id && doc.id.toLowerCase().includes(query)) ||
            (doc.title && doc.title.toLowerCase().includes(query)) ||
            (doc.file_url.toLowerCase().includes(query));
            
        const isValid = validateDocument(doc);
        let matchesFilter = true;
        if (filter === "incomplete") matchesFilter = !isValid;
        else if (filter === "cached") matchesFilter = doc.cached;
        else if (filter === "complete") matchesFilter = isValid;
        
        if (matchesSearch && matchesFilter) {
            card.classList.remove("hidden");
        } else {
            card.classList.add("hidden");
        }
    });
}

// ==========================================================================
// Document Selection & Editor Binding
// ==========================================================================
async function selectDocument(idx) {
    if (idx < 0 || idx >= documents.length) return;
    
    // Flush any pending save before switching
    if (pendingSave) {
        await executePendingSave();
    }
    
    // Remove active class from previous
    if (activeDocIdx !== -1) {
        const prevCard = document.getElementById(`doc-card-${activeDocIdx}`);
        if (prevCard) prevCard.classList.remove("active");
    }
    
    activeDocIdx = idx;
    
    // Set active class to new
    const activeCard = document.getElementById(`doc-card-${activeDocIdx}`);
    if (activeCard) activeCard.classList.add("active");
    
    // Populate form
    const doc = documents[idx];
    document.getElementById("editor-empty").classList.add("hidden");
    document.getElementById("editor-form-container").classList.remove("hidden");
    
    document.getElementById("editor-doc-index").textContent = `Doc #${idx + 1}`;
    document.getElementById("editor-doc-title-display").textContent = doc.title || doc.pdf_name || "Untitled Document";
    
    // Set field values
    document.getElementById("field-id").value = doc.id || "";
    document.getElementById("field-title").value = doc.title || "";
    document.getElementById("field-document-type").value = doc.document_type || "LAW";
    document.getElementById("field-issuing-entity").value = doc.issuing_entity || "";
    document.getElementById("field-document-number").value = doc.document_number || "";
    document.getElementById("field-year").value = doc.year || "";
    document.getElementById("field-language").value = doc.language || "English";
    document.getElementById("field-category").value = doc.category || "";
    document.getElementById("field-subcategory").value = doc.subcategory || "";
    
    // Set PDF link
    const pdfLink = document.getElementById("editor-pdf-link");
    pdfLink.href = doc.file_url;
    pdfLink.title = doc.file_url;
    
    // Badges
    const cachedBadge = document.getElementById("editor-cached-badge");
    if (doc.cached) {
        cachedBadge.classList.remove("hidden");
    } else {
        cachedBadge.classList.add("hidden");
    }
    
    updateEditorValidationBadges();
    
    // Scroll to top of editor pane
    document.getElementById("editor-pane").scrollTop = 0;
}

// ==========================================================================
// Inline Editing, Validation & Debounced Auto-saving
// ==========================================================================
function handleFieldInput(field, value) {
    if (!sessionInfo || sessionInfo.status !== 'pending') return;
    
    // Update local state immediately for fast validation feedback
    documents[activeDocIdx][field] = value;
    
    // Update display title if changing title
    if (field === 'title') {
        document.getElementById("editor-doc-title-display").textContent = value || "Untitled Document";
    }
    
    // Visual validation on active inputs
    updateEditorValidationBadges();
    
    // Debounce the PUT request to the backend
    queueSave(activeDocIdx, field, value);
}

function updateEditorValidationBadges() {
    const doc = documents[activeDocIdx];
    const isValid = validateDocument(doc);
    
    const validBadge = document.getElementById("editor-valid-badge");
    if (isValid) {
        validBadge.className = "badge badge-complete";
        validBadge.textContent = "COMPLETE";
    } else {
        validBadge.className = "badge badge-warning";
        validBadge.textContent = "INCOMPLETE";
    }
    
    // Highlight missing required inputs visually
    highlightFieldValidation("field-id", doc.id);
    highlightFieldValidation("field-category", doc.category);
    highlightFieldValidation("field-subcategory", doc.subcategory);
}

function highlightFieldValidation(elementId, value) {
    const input = document.getElementById(elementId);
    if (!value || value.trim() === "") {
        input.classList.add("input-invalid");
    } else {
        input.classList.remove("input-invalid");
    }
}

function validateDocument(doc) {
    // Required: ID, Category, Subcategory
    return (
        doc.id && doc.id.trim() !== "" &&
        doc.category && doc.category.trim() !== "" &&
        doc.subcategory && doc.subcategory.trim() !== ""
    );
}

function updateProgressAndValidation() {
    let completeCount = 0;
    documents.forEach(doc => {
        if (validateDocument(doc)) {
            completeCount++;
        }
    });
    
    const progressText = document.getElementById("progress-text");
    progressText.textContent = `${completeCount} / ${documents.length} Documents Completed`;
    
    const progressBar = document.getElementById("progress-bar");
    const percentage = documents.length > 0 ? (completeCount / documents.length) * 100 : 0;
    progressBar.style.width = `${percentage}%`;
    
    // Action bar warning
    const warning = document.getElementById("validation-warning");
    const warningText = document.getElementById("warning-text");
    const approveBtn = document.getElementById("btn-approve");
    
    if (completeCount < documents.length) {
        warningText.textContent = `${documents.length - completeCount} document(s) need attention`;
        warning.classList.add("visible");
        approveBtn.setAttribute("disabled", "true");
        approveBtn.title = "Please complete all required fields (ID, Category, Subcategory) before approving.";
    } else {
        warning.classList.remove("visible");
        if (sessionInfo && sessionInfo.status === 'pending') {
            approveBtn.removeAttribute("disabled");
            approveBtn.title = "Approve adjustments and continue compliance pipeline";
        }
    }
}

function queueSave(docIdx, field, value) {
    pendingSave = { docIdx, field, value };
    showSavingIndicator();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        executePendingSave();
    }, 450); // 450ms debounce
}

async function executePendingSave() {
    if (!pendingSave) return;
    const { docIdx, field, value } = pendingSave;
    pendingSave = null;
    clearTimeout(debounceTimer);
    
    try {
        const updatePayload = { [field]: value || null };
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/documents/${docIdx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatePayload)
        });
        
        if (!response.ok) {
            throw new Error(`Server returned code ${response.status}`);
        }
        
        const updatedDoc = await response.json();
        documents[docIdx] = updatedDoc;
        
        // UI feedback
        showSavedIndicator();
        updateDocumentCard(docIdx);
        updateProgressAndValidation();
        
        // Add subtle flash animation to indicate saved
        const fieldEl = document.getElementById(`field-${field}`);
        if (fieldEl) {
            fieldEl.classList.add("flash-success");
            setTimeout(() => fieldEl.classList.remove("flash-success"), 1000);
        }
    } catch (err) {
        console.error(err);
        showErrorToast(`Auto-save failed: ${err.message}`);
        showErrorIndicator();
    }
}

function showSavingIndicator() {
    const indicator = document.getElementById("auto-save-status");
    indicator.innerHTML = `<span class="status-indicator saving"></span> Saving changes...`;
}

function showSavedIndicator() {
    const indicator = document.getElementById("auto-save-status");
    indicator.innerHTML = `<span class="status-indicator"></span> Auto-saved`;
}

function showErrorIndicator() {
    const indicator = document.getElementById("auto-save-status");
    indicator.innerHTML = `<span class="status-indicator" style="background-color: var(--color-danger)"></span> Save Error`;
}

// ==========================================================================
// Approval & Rejection Handlers
// ==========================================================================
async function approveSession() {
    // Double check local validation
    let incompleteIdx = -1;
    for (let i = 0; i < documents.length; i++) {
        if (!validateDocument(documents[i])) {
            incompleteIdx = i;
            break;
        }
    }
    
    if (incompleteIdx !== -1) {
        showToast("Cannot approve: Some documents are missing required fields.", "error");
        selectDocument(incompleteIdx);
        return;
    }
    
    if (!confirm("Are you sure you want to approve this metadata review session? This will cache the mappings and run OCR in the background.")) {
        return;
    }
    
    // Flush any last pending save
    if (pendingSave) {
        await executePendingSave();
    }
    
    showLoading();
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/approve`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail?.message || "Approve request failed");
        }
        
        const result = await response.json();
        sessionInfo = result.session;
        updateSessionBadge();
        disableAllInputs();
        
        showToast("Session approved! Mappings cached and compliance pipeline triggered.", "success");
    } catch (error) {
        console.error(error);
        showToast(`Approval failed: ${error.message}`, "error");
    } finally {
        hideLoading();
    }
}

async function confirmReject() {
    if (!confirm("Are you sure you want to reject and discard this review session? No data will be sent to the pipeline.")) {
        return;
    }
    
    showLoading();
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/reject`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error("Reject request failed");
        }
        
        sessionInfo = await response.json();
        updateSessionBadge();
        disableAllInputs();
        
        showToast("Session rejected & discarded.", "info");
    } catch (error) {
        console.error(error);
        showToast(`Rejection failed: ${error.message}`, "error");
    } finally {
        hideLoading();
    }
}

// ==========================================================================
// Global Mappings Cache Modal Handler
// ==========================================================================
async function openMappingsModal() {
    const modal = document.getElementById("mappings-modal");
    modal.classList.add("active");
    await loadMappingsData();
}

function closeMappingsModal() {
    const modal = document.getElementById("mappings-modal");
    modal.classList.remove("active");
}

async function loadMappingsData() {
    const tableBody = document.getElementById("mappings-table-body");
    const emptyState = document.getElementById("mappings-empty");
    tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 2rem;">Loading cached mappings...</td></tr>`;
    emptyState.classList.add("hidden");
    
    try {
        const response = await fetch(`${API_BASE}/api/mappings`);
        if (!response.ok) throw new Error("Failed to fetch mappings");
        mappings = await response.json();
        
        tableBody.innerHTML = "";
        if (mappings.length === 0) {
            emptyState.classList.remove("hidden");
            return;
        }
        
        mappings.forEach(mapping => {
            const row = document.createElement("tr");
            
            // Shorten file url for display
            let urlText = mapping.file_url;
            try {
                const u = new URL(mapping.file_url);
                urlText = u.pathname.split('/').pop() || u.hostname;
            } catch {}
            
            row.innerHTML = `
                <td style="font-weight: 600; color: var(--text-cyan);">${escapeHtml(mapping.doc_id)}</td>
                <td title="${escapeHtml(mapping.file_url)}">
                    <a href="${escapeHtml(mapping.file_url)}" target="_blank" style="color: inherit; text-decoration: underline;">
                        ${escapeHtml(urlText)}
                    </a>
                </td>
                <td>
                    <span class="badge badge-complete">${escapeHtml(mapping.category)}</span>
                    <span class="badge badge-warning">${escapeHtml(mapping.subcategory)}</span>
                </td>
                <td><span class="badge badge-pending">${escapeHtml(mapping.document_type || 'LAW')}</span></td>
                <td>
                    <button class="btn btn-danger-outline btn-sm" onclick="deleteMapping('${escapeHtml(mapping.file_url)}')">Delete</button>
                </td>
            `;
            tableBody.appendChild(row);
        });
    } catch (error) {
        console.error(error);
        tableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--color-danger); padding: 2rem;">Error: ${error.message}</td></tr>`;
    }
}

async function deleteMapping(fileUrl) {
    if (!confirm(`Are you sure you want to delete the mapping for URL: ${fileUrl}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/mappings?file_url=${encodeURIComponent(fileUrl)}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error("Delete mapping failed");
        
        showToast("Mapping removed from cache", "success");
        await loadMappingsData();
        
        // Also update local documents cached state if their URL matches
        documents.forEach((doc, idx) => {
            if (doc.file_url === fileUrl) {
                doc.cached = false;
                updateDocumentCard(idx);
                if (idx === activeDocIdx) {
                    document.getElementById("editor-cached-badge").classList.add("hidden");
                }
            }
        });
    } catch (err) {
        console.error(err);
        showToast(`Delete failed: ${err.message}`, "error");
    }
}

async function clearAllCache() {
    if (!confirm("Are you sure you want to delete all cached mappings? This action cannot be undone.")) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/mappings/clear`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error("Clear all cache failed");
        
        const result = await response.json();
        showToast(result.detail || "All mappings cleared from cache", "success");
        await loadMappingsData();
        
        // Also update local documents cached state
        documents.forEach((doc, idx) => {
            doc.cached = false;
            updateDocumentCard(idx);
        });
        if (activeDocIdx !== -1) {
            document.getElementById("editor-cached-badge").classList.add("hidden");
        }
    } catch (err) {
        console.error(err);
        showToast(`Clear all failed: ${err.message}`, "error");
    }
}

// ==========================================================================
// Toasts & UI Helpers
// ==========================================================================
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let icon = "ℹ️";
    if (type === "success") icon = "✅";
    else if (type === "error") icon = "❌";
    
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(toast);
    
    // Auto-remove after 4 seconds
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(50px)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function showErrorToast(message) {
    showToast(message, "error");
}

function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
