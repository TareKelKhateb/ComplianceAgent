"""
models.py
---------
Shared data contracts, configuration models, and prompt templates for the
corporate document parser.

Extracted to prevent circular dependencies across the parser components.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class PdfType(Enum):
    """Classification of a PDF document based on density heuristics."""
    TEXT    = auto()
    IMAGE   = auto()
    UNKNOWN = auto()


@dataclass
class ParserConfig:
    """
    Configuration for the DocumentParser pipeline.

    Reads from environment variables by default to ensure zero-side-effect
    integration.
    """
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("LLAMA_API_KEY")
    )
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "LLAMA_API_BASE_URL", "https://api.llama-api.com"
        )
    )
    model: str = field(
        default_factory=lambda: os.getenv("LLAMA_MODEL", "llama3.3-70b")
    )
    ocr_threshold: int = field(
        default_factory=lambda: int(os.getenv("PARSER_OCR_THRESHOLD", "80"))
    )

    def validate(self) -> None:
        """
        Validate that the configuration is complete.

        Raises
        ------
        ValueError
            If the Llama API key is missing.
        """
        if not self.api_key:
            raise ValueError(
                "Llama API key is required. Set LLAMA_API_KEY in the environment."
            )


@dataclass
class ParseResult:
    """
    Standardised output contract for the DocumentParser pipeline.

    When ``success`` is True, ``data`` contains the fully extracted metadata
    dictionary ready to be passed to ``MetadataStore.insert_document()``.
    """
    success: bool
    message: str
    data: Optional[dict[str, Any]] = None
    parse_method: str = "unknown"
    raw_text: Optional[str] = None
    pdf_type: PdfType = PdfType.UNKNOWN


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """
You are a highly accurate corporate compliance document metadata extractor.
Analyze the following document text and extract the key metadata fields into a
strict JSON object.

Text:
---
{text}
---

Return ONLY a valid JSON object matching the following structure. Do not wrap
the JSON in markdown formatting (e.g. no ```json blocks). If a field cannot be
found, use null.

JSON Structure:
{{
  "title": "string",
  "document_type": "string",
  "issuing_entity": "string",
  "document_number": "string",
  "year": "string (YYYY)",
  "date": "string (YYYY-MM-DD)",
  "language": "string",
  "category": "string",
  "subcategory": "string"
}}
"""
