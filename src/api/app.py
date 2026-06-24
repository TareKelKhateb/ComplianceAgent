"""
app.py
------
Dashboard API gateway for the Compliance Agent.

Provides endpoints to:
  1. Trigger URL scraping via the Orchestrator
  2. Upload multiple PDF files and create review sessions
  3. Stream log files for monitoring

Static UI files are served from ``src/UI``.
"""

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import requests as http_requests

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("dashboard_api")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_ADJUSTMENTS_API_URL = os.getenv("USER_ADJUSTMENTS_API_URL", "http://localhost:8080")
UPLOAD_DIR = os.path.join(ROOT_DIR, "data", "uploads")
LOGS_DIR = os.path.join(ROOT_DIR, "logs")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Compliance Agent Dashboard API",
    description=(
        "Dashboard gateway for document ingestion. "
        "Supports URL scraping and multi-file upload with review session creation."
    ),
    version="1.0.0",
)

# CORS — wide-open for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Serve UI
# ---------------------------------------------------------------------------

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "UI")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the main dashboard page."""
    index_path = os.path.join(UI_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="UI index.html not found")
    return FileResponse(index_path, media_type="text/html")


# Mount static UI assets (CSS, JS)
if os.path.exists(UI_DIR):
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


# ===================================================================
# Request / Response models
# ===================================================================

class ScrapeRequest(BaseModel):
    """Payload for URL scraping."""
    url: str
    is_crawl: bool = False
    limit: int = 1


class ScrapeResponse(BaseModel):
    """Response after triggering a scrape."""
    success: bool
    message: str
    review_url: Optional[str] = None


class UploadResponse(BaseModel):
    """Response after uploading files."""
    success: bool
    message: str
    review_url: Optional[str] = None
    file_count: int = 0


class LogEntry(BaseModel):
    """A single log file entry."""
    name: str
    size_bytes: int
    modified_at: str


# ===================================================================
# 1. POST /api/scrape — Trigger URL scraping
# ===================================================================

def run_orchestrator_background(url: str, is_crawl: bool, limit: int):
    """Background task to run URL scraping via Orchestrator."""
    logger.info("Background scrape task starting: url=%s, crawl=%s, limit=%d", url, is_crawl, limit)
    try:
        from src.Orchetrator.Orchestrator import Orchestrator
        orchestrator = Orchestrator(push_to_dagshub=False, use_adjustments=True)
        review_url = orchestrator.run(
            url=url,
            is_crawl=is_crawl,
            limit=limit,
        )
        if review_url:
            logger.info("Background scrape task completed. Review URL: %s", review_url)
        else:
            logger.info("Background scrape task completed. No review URL generated.")
    except Exception as exc:
        logger.exception("Background scrape task failed: %s", exc)


@app.post(
    "/api/scrape",
    response_model=ScrapeResponse,
    summary="Scrape a URL in the background and create a review session",
)
async def scrape_url(body: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Trigger the Orchestrator to scrape a URL in the background.
    Creates a review session on the User Adjustments API and sends
    a notification email with the review link.
    """
    logger.info("Scrape request received: url=%s, crawl=%s, limit=%d", body.url, body.is_crawl, body.limit)

    background_tasks.add_task(
        run_orchestrator_background,
        body.url,
        body.is_crawl,
        body.limit,
    )

    return ScrapeResponse(
        success=True,
        message="Scraping has started in the background. You will receive an email notification with the review link once it finishes.",
        review_url=None,
    )


# ===================================================================
# 2. POST /api/upload — Upload multiple PDF files
# ===================================================================

@app.post(
    "/api/upload",
    response_model=UploadResponse,
    summary="Upload PDF files and create a review session",
)
async def upload_files(files: list[UploadFile] = File(...)):
    """
    Accept multiple uploaded PDF files, save them locally,
    create a review session on the User Adjustments API,
    and send a notification email.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    # Create a unique batch directory
    batch_id = uuid.uuid4().hex[:12]
    batch_dir = os.path.join(UPLOAD_DIR, batch_id)
    os.makedirs(batch_dir, exist_ok=True)

    logger.info("Upload batch %s: receiving %d file(s).", batch_id, len(files))

    # Save files and build document records
    documents: list[dict] = []
    for uploaded_file in files:
        filename = uploaded_file.filename or f"upload_{uuid.uuid4().hex[:8]}.pdf"
        # Sanitize filename
        safe_filename = filename.replace(" ", "_").replace("/", "-").replace("\\", "-")
        if not safe_filename.lower().endswith(".pdf"):
            safe_filename += ".pdf"

        file_path = os.path.join(batch_dir, safe_filename)

        try:
            content = await uploaded_file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            logger.info("Saved uploaded file: %s (%d bytes)", safe_filename, len(content))
        except Exception as exc:
            logger.error("Failed to save file '%s': %s", safe_filename, exc)
            continue

        # Build a document record matching the ScrapedDocument schema
        title = os.path.splitext(filename)[0]
        doc_record = {
            "title": title,
            "document_type": None,
            "issuing_entity": None,
            "document_number": None,
            "year": None,
            "date": None,
            "language": None,
            "file_url": f"local://{batch_id}/{safe_filename}",
            "local_path": batch_dir,
            "pdf_name": safe_filename,
        }
        documents.append(doc_record)

    if not documents:
        raise HTTPException(status_code=400, detail="No files were successfully saved.")

    # Create a review session on the User Adjustments API
    try:
        payload = {"documents": [documents]}  # Wrap in a single group (list[list[dict]])
        response = http_requests.post(
            f"{USER_ADJUSTMENTS_API_URL}/api/sessions",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        session_data = response.json()

        session_id = session_data["session_id"]
        review_url = f"{USER_ADJUSTMENTS_API_URL.rstrip('/')}{session_data['review_url']}"

        logger.info("Created review session %s for %d uploaded file(s).", session_id, len(documents))

        # Send email notification
        try:
            from src.Orchetrator.email_sender import send_review_email
            send_review_email(review_url)
        except Exception as email_exc:
            logger.error("Failed to send review email: %s", email_exc)

        return UploadResponse(
            success=True,
            message=f"Uploaded {len(documents)} file(s). Review session created and email notification sent.",
            review_url=review_url,
            file_count=len(documents),
        )

    except http_requests.exceptions.ConnectionError:
        logger.error(
            "Cannot reach User Adjustments API at '%s'. "
            "Make sure the server is running.",
            USER_ADJUSTMENTS_API_URL,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cannot reach User Adjustments API at '{USER_ADJUSTMENTS_API_URL}'. "
                "Make sure the server is running: python -m src.user_adjustments_apis.api.run_server"
            ),
        )
    except Exception as exc:
        logger.exception("Failed to create review session: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create review session: {exc}")


# ===================================================================
# 3. GET /api/logs — List available log files
# ===================================================================

@app.get(
    "/api/logs",
    response_model=list[LogEntry],
    summary="List available log files",
)
async def list_logs():
    """Return a list of log files with their sizes and modification times."""
    if not os.path.exists(LOGS_DIR):
        return []

    entries = []
    for name in sorted(os.listdir(LOGS_DIR)):
        filepath = os.path.join(LOGS_DIR, name)
        if os.path.isfile(filepath):
            stat = os.stat(filepath)
            entries.append(LogEntry(
                name=name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            ))
    return entries


# ===================================================================
# 4. GET /api/logs/{filename} — Read a specific log file
# ===================================================================

@app.get(
    "/api/logs/{filename}",
    summary="Read the contents of a log file",
)
async def read_log(
    filename: str,
    tail: int = Query(200, ge=1, le=5000, description="Number of lines to return from the end"),
):
    """
    Read and return the last N lines of a log file.
    Supports ``orchestrator.log``, ``email_notifications.log``, etc.
    """
    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    filepath = os.path.join(LOGS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Log file '{filename}' not found.")

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Return the last `tail` lines
        tail_lines = lines[-tail:]
        return {
            "filename": filename,
            "total_lines": len(lines),
            "returned_lines": len(tail_lines),
            "content": "".join(tail_lines),
        }
    except Exception as exc:
        logger.error("Failed to read log file '%s': %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read log: {exc}")


# ===================================================================
# 5. GET /api/health — Health check
# ===================================================================

@app.get("/api/health", summary="Health check")
async def health_check():
    """Return the health status of the dashboard API and downstream services."""
    status = {
        "dashboard_api": "ok",
        "user_adjustments_api": "unknown",
        "scraper_api": "unknown",
    }

    # Check User Adjustments API
    try:
        r = http_requests.get(f"{USER_ADJUSTMENTS_API_URL}/api/sessions", timeout=3)
        status["user_adjustments_api"] = "ok" if r.status_code == 200 else f"error ({r.status_code})"
    except Exception:
        status["user_adjustments_api"] = "unreachable"

    # Check Scraper API
    try:
        r = http_requests.get("http://localhost:8000/health", timeout=3)
        status["scraper_api"] = "ok" if r.status_code == 200 else f"error ({r.status_code})"
    except Exception:
        status["scraper_api"] = "unreachable"

    return status


# ===================================================================
# 6. GET /api/approvals — Fetch pending chunk approvals (version > 1)
# ===================================================================

@app.get(
    "/api/approvals",
    summary="Get all modified chunks that require user approval (version > 1)",
)
async def get_approvals():
    """
    Fetch all modified or added law chunks that have not yet been approved
    by the user, and are not single-version chunks (version > 1).
    """
    try:
        from src.metadata_manager.db import get_unapproved_chunks
        db_path = os.path.join(ROOT_DIR, "data", "legal_vault.db")
        chunks = get_unapproved_chunks(db_path)
        return chunks
    except Exception as exc:
        logger.exception("Failed to fetch pending approvals: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch approvals: {exc}")


# ===================================================================
# 7. POST /api/approvals/{chunk_id}/approve — Approve a chunk change
# ===================================================================

@app.post(
    "/api/approvals/{chunk_id}/approve",
    summary="Approve a document chunk modification",
)
async def approve_chunk(chunk_id: int):
    """
    Mark a specific document chunk as approved.
    """
    try:
        from src.metadata_manager.db import approve_chunk_by_id
        db_path = os.path.join(ROOT_DIR, "data", "legal_vault.db")
        success = approve_chunk_by_id(db_path, chunk_id)
        if not success:
            raise HTTPException(status_code=500, detail="Database update failed.")
        return {"success": True, "message": f"Chunk {chunk_id} successfully approved."}
    except Exception as exc:
        logger.exception("Failed to approve chunk %d: %s", chunk_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to approve chunk: {exc}")
