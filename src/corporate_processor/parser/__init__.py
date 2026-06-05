"""
src/corporate_processor/parser/__init__.py
------------------------------------------
Public surface of the corporate PDF parser package.

The orchestrator (DocumentParser) is the ONLY interface the rest of the
project should interact with.  Import the specialist components only when
you need to unit-test or extend them individually.

Quick-start
-----------
::

    from src.corporate_processor.parser import DocumentParser

    parser = DocumentParser()
    result = parser.route("path/to/document.pdf")
    if result.success:
        store.insert_document(result.data)
"""

# pyrefly: ignore [missing-import]
from .models import ParseResult, ParserConfig, PdfType
from .orchestrator import DocumentParser

__all__ = [
    # Primary interface
    "DocumentParser",
    # Shared contracts (re-exported for type hints in callers)
    "ParseResult",
    "ParserConfig",
    "PdfType",
]
