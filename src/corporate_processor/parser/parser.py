"""
parser.py — backward-compatibility shim
----------------------------------------
This file is kept so that any existing code importing directly from
``src.corporate_processor.parser.parser`` continues to work unchanged.

All implementation has moved to the modular architecture:
    models.py       → ParserConfig, ParseResult, PdfType
    router.py       → PDFRouter
    text_extractor.py → TextExtractor
    llama_client.py → LlamaClient
    orchestrator.py → DocumentParser  (main entry-point)

New code should import from the package directly:
    from src.corporate_processor.parser import DocumentParser
"""

# pyrefly: ignore [missing-import]
# Re-export everything that was previously defined here.
from .models import ParseResult, ParserConfig, PdfType, EXTRACTION_PROMPT  # noqa: F401
from .router import PDFRouter                                                # noqa: F401
from .text_extractor import TextExtractor                                   # noqa: F401
from .llama_client import LlamaClient                                       # noqa: F401
from .orchestrator import DocumentParser                                    # noqa: F401

__all__ = [
    "DocumentParser",
    "ParseResult",
    "ParserConfig",
    "PdfType",
    "PDFRouter",
    "TextExtractor",
    "LlamaClient",
    "EXTRACTION_PROMPT",
]
