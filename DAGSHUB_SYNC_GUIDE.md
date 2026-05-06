# DagsHub Integration & sync_to_dagshub() Guide

## Overview
The enhanced `sync_to_dagshub()` method now provides **end-to-end workflow** orchestration:
1. Copies PDF to DVC vault
2. Adds file to DVC tracking
3. Commits .dvc pointer to Git
4. Pushes heavy file to DagsHub remote
5. **Updates metadata database** with 'uploaded' status

---

## Usage Examples

### Example 1: Sync with Database Integration (Recommended)
```python
from src.metadata_manager.metadata_store import MetadataStore

# Initialize the metadata store
store = MetadataStore()

# Insert document metadata first
result = store.insert_document({
    "file_url": "https://cbe.org.eg/law194.pdf",
    "sha256_hash": "a3f9b7e2c...",
    "title": "CBE Law No. 194",
    "year": "2020",
    "document_type": "LAW",
    "issuing_entity": "Central Bank of Egypt"
})

if result.success:
    document = result.data
    print(f"Document inserted: id={document.id}, status={document.download_status}")
    
    # Now sync the actual PDF file
    local_pdf = "/path/to/law194.pdf"
    success = store.sync_to_dagshub(
        local_pdf_path=local_pdf,
        file_url="https://cbe.org.eg/law194.pdf"  # Links to DB record
    )
    
    if success:
        print("✓ File synced AND database updated to 'uploaded'")
        
        # Verify status was updated
        updated = store.get_latest_document_by_url("https://cbe.org.eg/law194.pdf")
        print(f"Current status: {updated.data.download_status}")  # Should be 'uploaded'
```

### Example 2: Sync Without Database Integration
```python
# If you only want to sync files without metadata (not recommended)
success = store.sync_to_dagshub(
    local_pdf_path="/path/to/document.pdf"
    # file_url omitted - DB won't be updated
)

if success:
    print("File synced to DagsHub (metadata not updated)")
```

---

## New Features

### 1. **Database-Aware Sync**
```python
# BEFORE: sync_to_dagshub(local_pdf_path) -> bool
# AFTER:  sync_to_dagshub(local_pdf_path, file_url=None) -> bool

# With file_url, database is automatically updated
store.sync_to_dagshub(pdf_path, file_url="https://example.com/doc.pdf")
```

### 2. **Robust Error Handling**
- If database lookup fails: warns but returns True (file was synced)
- If database update fails: logs warning but confirms sync success
- Graceful degradation: prioritizes file sync over metadata updates

### 3. **Enhanced Logging**
```
✓ File moved to vault: data/law194.pdf
✓ File added to DVC: data/law194.pdf.dvc
✓ Committed to Git
✓ Pushed to DagsHub
✓ Database updated: document 5 marked as 'uploaded'
```

---

## Integration Workflow

### Step 1: Insert Document Metadata
```python
result = store.insert_document({
    "file_url": "https://source.com/doc.pdf",
    "sha256_hash": "computed_by_tier_1b",
    "title": "Document Title",
    # ... other fields
})
doc_record = result.data  # Use this for next step
```

### Step 2: Download/Obtain PDF
```python
# Tier 1B downloads the PDF to local storage
# local_pdf_path = "/tmp/document.pdf"
```

### Step 3: Sync to DagsHub
```python
# Sync AND update database in one call
success = store.sync_to_dagshub(
    local_pdf_path=local_pdf_path,
    file_url="https://source.com/doc.pdf"
)
```

### Step 4: Verify Status
```python
if success:
    doc = store.get_latest_document_by_url("https://source.com/doc.pdf")
    assert doc.data.download_status == "uploaded"
    assert doc.data.file_path == "data/document.pdf"
    print(f"✓ Document {doc.data.id} ready for Tier 2 processing")
```

---

## Database Status Tracking

### Download Status Field
The `download_status` field tracks the document lifecycle:

| Status | Meaning | Set By |
|--------|---------|--------|
| `pending` | Inserted, awaiting sync | `insert_document()` |
| `uploaded` | Successfully synced to DagsHub | `sync_to_dagshub()` |
| `failed` | Sync or download failed | `mark_download_failed()` |

### Query Documents by Status
```python
# Find all uploaded documents ready for Tier 2
uploaded = store.search_documents(download_status="uploaded", latest_only=True)
print(f"Ready for chunking: {len(uploaded.data)} documents")

# Find documents that failed
failed = store.search_documents(download_status="failed", latest_only=True)
print(f"Failed uploads: {len(failed.data)} documents")
```

---

## Collaboration & DagsHub Sharing

### Team Sync Workflow
```powershell
# Step 1: Your team member uploads files
python main.py  # Uses sync_to_dagshub() internally

# Step 2: Commit and push .dvc pointers to Git
git push origin feature/metadata-ingestion

# Step 3: Your teammate pulls the pointers
git pull origin feature/metadata-ingestion

# Step 4: Your teammate retrieves the actual PDFs
uv run dvc pull  # Restores files from DagsHub

# Step 5: Your teammate syncs metadata locally
python -c "from src.metadata_manager.metadata_store import MetadataStore; \
           store = MetadataStore(); \
           store.import_from_json()"  # Syncs from shared export
```

---

## Troubleshooting

### "Document with URL not found in DB"
```
⚠ Warning: Document with URL 'https://...' not found in DB
```
**Solution:** Ensure document was inserted before calling sync_to_dagshub()
```python
# CORRECT ORDER:
store.insert_document({"file_url": "https://...", ...})  # First
store.sync_to_dagshub(pdf_path, file_url="https://...")  # Then
```

### "Database update failed"
```
⚠ Warning: Database update failed: ...
```
**Meaning:** File was synced to DagsHub, but metadata wasn't updated
**Action:** Manually update via:
```python
store.update_document_by_url(
    "https://source.com/doc.pdf",
    {"download_status": "uploaded"}
)
```

### "CLI Error during DagsHub sync"
**Likely causes:**
- DVC not installed: `pip install dvc`
- DagsHub credentials expired
- Git not configured

**Fix:**
```powershell
uv run dvc remote list  # Verify remote is set
uv run dvc status      # Check connection
```

---

## Security Best Practices

✅ **SECURE:**
- Credentials in `.dvc/config.local` (ignored by Git)
- `.dvc/cache` in `.gitignore` (never committed)
- Only `.dvc` pointers committed to Git

✅ **RECOMMENDED:**
```bash
# Use environment variables for credentials
export DVC_HTTP_BASIC_ORIGIN_USERNAME="your_username"
export DVC_HTTP_BASIC_ORIGIN_PASSWORD="your_token"
```

❌ **NEVER:**
- Commit `.dvc/config.local` to Git
- Hard-code credentials in Python files
- Commit `.dvc/cache` directory

---

## Files Changed

✅ `src/metadata_manager/metadata_store.py`
- Enhanced `sync_to_dagshub()` with database integration
- Added `file_url` parameter for DB lookup
- Improved error handling and logging

✅ `.dvc/config`
- DagsHub remote configured: `origin`
- Points to: `https://dagshub.com/tarekelkhateb31/ComplianceAgent.dvc`

✅ `.gitignore`
- All `/data/**` files ignored (except `.dvc` pointers)
- `.dvc/cache` and `.dvc/tmp` ignored
- Python and IDE artifacts ignored

✅ `.dvcignore`
- Database files ignored by DVC
- Python cache ignored
- Temp files ignored

---

## Next Steps

1. Test the enhanced sync with a sample document
2. Verify database updates in SQLite
3. Push commits to remote: `git push origin feature/metadata-ingestion`
4. Collaborate with team on DagsHub shared repo
