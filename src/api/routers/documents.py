from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

# Notice the relative imports using '..' to go up one folder level
from ..database import get_session
from ..models import Document
from ..schemas import DocumentCreate, DocumentResponse, DocumentUpdate # Ensure you import the new schema

# Create the router with a prefix and a tag for the Swagger UI
router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)

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