import os
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List

from ..database import get_session
from ..models import Document
from ..schemas import DocumentCreate, DocumentResponse, DocumentUpdate, ImportPreviewItem, BulkImportResult

router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)

# ---------------------------------------------------------
# ⚙️ CONFIGURATION VARIABLE: Dynamic Scraped File Path
# ---------------------------------------------------------
# 1. Get the absolute path of the 'routers' folder
CURRENT_DIR = Path(__file__).resolve().parent

# 2. Navigate UP three levels to reach the 'ComplianceAgent' root folder
# routers -> api -> src -> ComplianceAgent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent

# 3. Define the exact path to your JSON file
# If your file is inside a 'data' folder in the root:
SCRAPED_JSON_PATH = PROJECT_ROOT / "output_1.json"


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def add_document(doc_in: DocumentCreate, session: Session = Depends(get_session)):
    """Add a new document to the database with strict integrity checks."""
    
    # 1. INTEGRITY CHECK: Is the Title completely unique?
    existing_title = session.exec(select(Document).where(Document.title == doc_in.title)).first()
    if existing_title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"A document with the title '{doc_in.title}' already exists."
        )
    
    # 2. INTEGRITY CHECK: Is the Category + Subcategory combination unique?
    existing_combo = session.exec(
        select(Document)
        .where(Document.category == doc_in.category)
        .where(Document.subcategory == doc_in.subcategory)
    ).first()
    
    if existing_combo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"The combination of Category '{doc_in.category}' and Subcategory '{doc_in.subcategory}' is already in use."
        )
    
    # 3. Convert Schema to DB Model and Save
    db_doc = Document.model_validate(doc_in)
    session.add(db_doc)
    session.commit()
    session.refresh(db_doc)
    
    return db_doc

@router.post("/bulk-import", response_model=BulkImportResult)
def bulk_import_documents(selected_docs: List[DocumentCreate], session: Session = Depends(get_session)):
    """
    Takes an array of documents and saves them all at once.
    Includes integrity checks to safely skip duplicates without crashing.
    """
    success_count = 0
    fail_count = 0
    error_messages = []
    
    for doc_in in selected_docs:
        try:
            # 1. Check Title Collision
            title_exists = session.exec(select(Document).where(Document.title == doc_in.title)).first()
            
            # 2. Check Category/Subcategory Collision
            combo_exists = session.exec(
                select(Document)
                .where(Document.category == doc_in.category)
                .where(Document.subcategory == doc_in.subcategory)
            ).first()
            
            # If it's a duplicate, log the error and SKIP to the next file
            if title_exists or combo_exists:
                fail_count += 1
                error_messages.append(f"Skipped '{doc_in.title}': Duplicate title or category combo.")
                continue
                
            # If it's safe, queue it for the database
            db_doc = Document.model_validate(doc_in)
            session.add(db_doc)
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            error_messages.append(f"Failed '{doc_in.title}': {str(e)}")
            
    # Commit all successful additions to SQLite at once
    session.commit()
    
    return BulkImportResult(
        successful=success_count,
        failed=fail_count,
        errors=error_messages
    )



@router.delete("/title/{title}")
def delete_document_by_title(title: str, session: Session = Depends(get_session)):
    """Delete a document by its exact unique title."""
    doc = session.exec(select(Document).where(Document.title == title)).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    session.delete(doc)
    session.commit()
    return {"message": f"Document '{title}' deleted successfully."}

@router.delete("/category/{category}/subcategory/{subcategory}")
def delete_document_by_category(category: str, subcategory: str, session: Session = Depends(get_session)):
    """Delete a document where the combination of category and subcategory is unique."""
    doc = session.exec(
        select(Document)
        .where(Document.category == category)
        .where(Document.subcategory == subcategory)
    ).first()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    session.delete(doc)
    session.commit()
    return {"message": f"Document in {category}/{subcategory} deleted successfully."}



@router.put("/{doc_id}", response_model=DocumentResponse)
def update_document(doc_id: int, doc_in: DocumentUpdate, session: Session = Depends(get_session)):
    """Update a document while enforcing uniqueness on Title and Category/Subcategory."""
    
    # 1. Fetch the existing document
    db_doc = session.get(Document, doc_id)
    if not db_doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # 2. INTEGRITY CHECK: Is the new Title unique?
    if doc_in.title is not None and doc_in.title != db_doc.title:
        existing_title = session.exec(select(Document).where(Document.title == doc_in.title)).first()
        if existing_title:
            raise HTTPException(status_code=400, detail="A document with this title already exists.")

    # 3. INTEGRITY CHECK: Is the new Category + Subcategory combo unique?
    # Determine what the final category/subcategory will be after this update
    new_cat = doc_in.category if doc_in.category is not None else db_doc.category
    new_subcat = doc_in.subcategory if doc_in.subcategory is not None else db_doc.subcategory
    
    # If either of them is being changed, verify the new combination doesn't clash with another file
    if doc_in.category is not None or doc_in.subcategory is not None:
        existing_combo = session.exec(
            select(Document)
            .where(Document.category == new_cat)
            .where(Document.subcategory == new_subcat)
            .where(Document.id != doc_id) # VERY IMPORTANT: Ignore the current document we are updating!
        ).first()
        
        if existing_combo:
            raise HTTPException(
                status_code=400, 
                detail=f"The combination of Category '{new_cat}' and Subcategory '{new_subcat}' is already in use by another document."
            )

    # 4. Apply the updates using Pydantic's exclude_unset feature
    # exclude_unset=True ensures we ONLY update fields the user actually sent in the JSON body
    update_data = doc_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_doc, key, value)

    # 5. Save and return
    session.add(db_doc)
    session.commit()
    session.refresh(db_doc)
    
    return db_doc





# ---------------------------------------------------------
# 🚀 NEW: Auto-Read Local Scraped File
# ---------------------------------------------------------
from ..schemas import ScrapedDocument, ImportPreviewItem, MapAndImportRequest

# ... (Keep your SCRAPED_JSON_PATH variable where it is) ...

@router.get("/preview-local-file", response_model=List[ImportPreviewItem])
def preview_local_scraped_file(session: Session = Depends(get_session)):
    """Reads local JSON and checks which files are new based on Title."""
    if not os.path.exists(SCRAPED_JSON_PATH):
        raise HTTPException(status_code=404, detail=f"File not found: {SCRAPED_JSON_PATH}")
    
    try:
        with open(SCRAPED_JSON_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            if isinstance(raw_data, list) and len(raw_data) > 0 and isinstance(raw_data[0], list):
                raw_data = raw_data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading JSON: {str(e)}")

    # Parse using the NEW ScrapedDocument schema (no categories required)
    try:
        scraped_docs = [ScrapedDocument(**item) for item in raw_data]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"JSON structure error: {str(e)}")

    preview_results = []
    for idx, doc in enumerate(scraped_docs):
        # We can ONLY check Title uniqueness at this stage
        title_exists = session.exec(select(Document).where(Document.title == doc.title)).first()
        
        if title_exists:
            preview_results.append(ImportPreviewItem(
                index=idx, document=doc, status="TITLE_CONFLICT", 
                message=f"Duplicate: '{doc.title}' is already in the vault."
            ))
        else:
            preview_results.append(ImportPreviewItem(
                index=idx, document=doc, status="READY_TO_MAP", 
                message="New file. Requires Category mapping."
            ))
            
    return preview_results


@router.post("/map-and-import", response_model=DocumentResponse)
def map_and_import_document(req: MapAndImportRequest, session: Session = Depends(get_session)):
    """Takes a raw scraped document, maps it to a category, optionally renames it, and saves it."""
    
    # 1. Convert the raw scraped data into a dictionary
    combined_data = req.scraped_data.model_dump()
    
    # 2. Inject the User's Mapping Data
    combined_data["category"] = req.category
    combined_data["subcategory"] = req.subcategory
    
    # 3. Handle Title Override (If the user wants to rename it)
    if req.override_title:
        combined_data["title"] = req.override_title
    
    # 4. Convert it into our official database creation schema
    doc_in = DocumentCreate(**combined_data)
    
    # 5. Final Integrity Checks
    # Check if our (potentially updated) title is unique
    title_exists = session.exec(select(Document).where(Document.title == doc_in.title)).first()
    if title_exists:
        raise HTTPException(
            status_code=400, 
            detail=f"Title conflict: The title '{doc_in.title}' is already in the database."
        )
        
    combo_exists = session.exec(
        select(Document)
        .where(Document.category == doc_in.category)
        .where(Document.subcategory == doc_in.subcategory)
    ).first()
    if combo_exists:
        raise HTTPException(
            status_code=400, 
            detail=f"Category conflict: '{doc_in.category} / {doc_in.subcategory}' is already in use."
        )
    
    # 6. Save to Database
    db_doc = Document.model_validate(doc_in)
    session.add(db_doc)
    session.commit()
    session.refresh(db_doc)
    
    return db_doc


@router.get("/export-for-pipeline", response_model=List[List[DocumentResponse]])
def export_for_pipeline(session: Session = Depends(get_session)):
    """
    Exports all approved database documents into the exact nested JSON array format 
    required by the downstream parsing and metadata extraction pipelines.
    """
    # 1. Fetch ALL documents currently saved in the database
    all_documents = session.exec(select(Document)).all()
    
    # 2. Wrap the list of documents in an outer list to match the pipeline requirement
    # Format becomes: [ [ {doc1}, {doc2}, ... ] ]
    pipeline_payload = [all_documents]
    
    return pipeline_payload