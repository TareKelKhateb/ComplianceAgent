"""
test_pipeline.py
----------------
Integration tests for PipelineManager.

What is tested
~~~~~~~~~~~~~~
- process() routes to the TEXT path (TextExtractor) when PDFRouter returns PdfType.TEXT.
- process() routes to the OCR path (CorporateOCREngine with Mistral) when PDFRouter
  returns PdfType.IMAGE — this is the primary focus per the task requirements.
- The LlamaClient receives the raw text from whichever extractor ran.
- The returned ParseResult is store-compatible (all required keys present).
- Failure modes: file not found, extraction failure, Llama API failure.
- process_batch() handles a mixed list of successes and failures.

Mocking strategy
~~~~~~~~~~~~~~~~
Three subsystems are mocked so the test suite runs without any real PDF files,
API keys, or external services:

  1. PDFRouter.detect()         — controls which branch the pipeline takes.
  2. CorporateOCREngine.process_document() — simulates Mistral OCR output.
  3. LlamaClient.extract_metadata()        — simulates structured JSON from the LLM.

TextExtractor.extract() is also patched where the TEXT path is exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_FAKE_KEY       = "test-llama-key-pipeline"
_FAKE_OCR_TEXT  = "## Page 1\n\nAML Policy for corporate compliance — scanned document."
_FAKE_TEXT_TEXT = "## Page 1\n\nAML Policy for corporate compliance — selectable text."
_FAKE_METADATA  = {
    "title":           "AML Corporate Policy 2024",
    "document_type":   "POLICY",
    "issuing_entity":  "Compliance Department",
    "document_number": "CP-2024-001",
    "year":            "2024",
    "date":            "2024-01-15",
    "language":        "English",
    "category":        "banking",
    "subcategory":     "anti_money_laundering",
}

_ROUTER_PATH   = "src.corporate_processor.pipeline_manager.PDFRouter.detect"
_OCR_PATH      = "src.corporate_processor.pipeline_manager.CorporateOCREngine.process_document"
_TEXT_PATH     = "src.corporate_processor.pipeline_manager.TextExtractor.extract"
_LLAMA_PATH    = "src.corporate_processor.pipeline_manager.LlamaClient.extract_metadata"
_MISTRAL_SDK   = "src.document_processor.extractors.mistral_extractor.Mistral"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def patched_mistral_sdk():
    """Suppress Mistral SDK construction to avoid EnvironmentError."""
    with patch(_MISTRAL_SDK) as MockMistral:
        MockMistral.return_value = MagicMock()
        yield MockMistral


@pytest.fixture()
def pipeline(patched_mistral_sdk, monkeypatch):
    """
    Return a PipelineManager with a fake Llama API key.
    MISTRAL_API_KEY is set so CorporateMistralExtractor can initialise.
    """
    monkeypatch.setenv("LLAMA_API_KEY",   _FAKE_KEY)
    monkeypatch.setenv("MISTRAL_API_KEY", _FAKE_KEY)
    from src.corporate_processor.pipeline_manager import PipelineManager
    return PipelineManager()


@pytest.fixture()
def dummy_pdf(tmp_path) -> Path:
    """Create a minimal PDF-like file that passes path-existence checks."""
    pdf = tmp_path / "corporate_policy.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy content")
    return pdf


# ---------------------------------------------------------------------------
# Tests: IMAGE path (primary focus — Mistral OCR)
# ---------------------------------------------------------------------------

class TestPipelineManagerOCRPath:
    """
    Full integration tests for the IMAGE branch:
    PDFRouter → CorporateOCREngine (Mistral) → LlamaClient → ParseResult
    """

    def test_routes_to_ocr_engine_for_image_pdf(self, pipeline, dummy_pdf):
        """
        When PDFRouter classifies the PDF as IMAGE, process() must call
        CorporateOCREngine.process_document() and NOT TextExtractor.extract().
        """
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT) as mock_ocr, \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA), \
             patch(_TEXT_PATH) as mock_text:

            pipeline.process(str(dummy_pdf))

        mock_ocr.assert_called_once_with(str(dummy_pdf))
        mock_text.assert_not_called()

    def test_ocr_path_returns_successful_parse_result(self, pipeline, dummy_pdf):
        """process() must return success=True with a store-compatible .data dict."""
        from src.corporate_processor.parser.models import PdfType, ParseResult

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert isinstance(result, ParseResult)
        assert result.success is True
        assert result.parse_method == "ocr"

    def test_ocr_path_data_contains_all_store_keys(self, pipeline, dummy_pdf):
        """
        The .data dict in the ParseResult must contain every key expected
        by MetadataStore.insert_document().
        """
        from src.corporate_processor.parser.models import PdfType

        required_keys = {
            "id", "file_url", "sha256_hash",
            "title", "document_type", "issuing_entity", "document_number",
            "year", "date", "language", "category", "subcategory",
            "file_path", "file_size_bytes", "download_status",
        }

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.data is not None
        missing = required_keys - set(result.data.keys())
        assert not missing, f"Missing store keys: {missing}"

    def test_ocr_path_data_maps_llm_metadata_correctly(self, pipeline, dummy_pdf):
        """LLM-extracted metadata must be faithfully mapped into .data."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        d = result.data
        assert d["title"]           == _FAKE_METADATA["title"]
        assert d["document_type"]   == _FAKE_METADATA["document_type"]
        assert d["issuing_entity"]  == _FAKE_METADATA["issuing_entity"]
        assert d["year"]            == _FAKE_METADATA["year"]
        assert d["language"]        == _FAKE_METADATA["language"]
        assert d["category"]        == _FAKE_METADATA["category"]

    def test_ocr_path_raw_text_is_ocr_output(self, pipeline, dummy_pdf):
        """ParseResult.raw_text must be the string returned by the OCR engine."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.raw_text == _FAKE_OCR_TEXT

    def test_ocr_path_passes_ocr_text_to_llama(self, pipeline, dummy_pdf):
        """LlamaClient.extract_metadata() must receive the OCR engine output."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA) as mock_llama:

            pipeline.process(str(dummy_pdf))

        args, _ = mock_llama.call_args
        assert args[0] == _FAKE_OCR_TEXT

    def test_ocr_path_pdf_type_is_image(self, pipeline, dummy_pdf):
        """ParseResult.pdf_type must be PdfType.IMAGE on the OCR path."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.pdf_type is PdfType.IMAGE

    def test_ocr_path_file_path_in_data(self, pipeline, dummy_pdf):
        """data['file_path'] must be the resolved absolute path of the PDF."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.data["file_path"] == str(dummy_pdf.resolve())

    def test_ocr_path_download_status_is_downloaded(self, pipeline, dummy_pdf):
        """data['download_status'] must be 'downloaded' for locally processed files."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.data["download_status"] == "downloaded"


# ---------------------------------------------------------------------------
# Tests: TEXT path (routing verification)
# ---------------------------------------------------------------------------

class TestPipelineManagerTextPath:
    """Verify the TEXT routing branch delegates to TextExtractor."""

    def test_routes_to_text_extractor_for_text_pdf(self, pipeline, dummy_pdf):
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.TEXT), \
             patch(_TEXT_PATH, return_value=_FAKE_TEXT_TEXT) as mock_text, \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA), \
             patch(_OCR_PATH) as mock_ocr:

            pipeline.process(str(dummy_pdf))

        mock_text.assert_called_once_with(str(dummy_pdf.resolve()))
        mock_ocr.assert_not_called()

    def test_text_path_parse_method_is_text(self, pipeline, dummy_pdf):
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.TEXT), \
             patch(_TEXT_PATH, return_value=_FAKE_TEXT_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            result = pipeline.process(str(dummy_pdf))

        assert result.parse_method == "text"


# ---------------------------------------------------------------------------
# Tests: failure cases
# ---------------------------------------------------------------------------

class TestPipelineManagerFailures:
    """Verify safe failure behaviour for common error conditions."""

    def test_returns_failure_for_nonexistent_file(self, pipeline):
        result = pipeline.process("/absolutely/nonexistent/file.pdf")
        assert result.success is False
        assert result.data is None
        assert "not found" in result.message.lower()

    def test_returns_failure_on_ocr_engine_error(self, pipeline, dummy_pdf):
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, side_effect=RuntimeError("OCR engine crashed")):

            result = pipeline.process(str(dummy_pdf))

        assert result.success is False
        assert result.data is None

    def test_returns_failure_on_llama_api_error(self, pipeline, dummy_pdf):
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, side_effect=ValueError("Invalid JSON from API")):

            result = pipeline.process(str(dummy_pdf))

        assert result.success is False
        assert result.data is None

    def test_returns_failure_on_unknown_pdf_type(self, pipeline, dummy_pdf):
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.UNKNOWN):
            result = pipeline.process(str(dummy_pdf))

        assert result.success is False

    def test_ocr_failure_does_not_raise_exception(self, pipeline, dummy_pdf):
        """A failure in the OCR engine must return ParseResult, not raise."""
        from src.corporate_processor.parser.models import PdfType

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, side_effect=Exception("Unexpected crash")):

            result = pipeline.process(str(dummy_pdf))

        assert isinstance(result, type(result))   # did not raise
        assert result.success is False


# ---------------------------------------------------------------------------
# Tests: process_batch
# ---------------------------------------------------------------------------

class TestPipelineManagerBatch:
    """Verify batch processing handles mixed results correctly."""

    def test_batch_returns_one_result_per_file(self, pipeline, tmp_path):
        from src.corporate_processor.parser.models import PdfType

        pdfs = []
        for i in range(3):
            p = tmp_path / f"doc_{i}.pdf"
            p.write_bytes(b"%PDF-1.4")
            pdfs.append(str(p))

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            results = pipeline.process_batch(pdfs)

        assert len(results) == 3

    def test_batch_failure_on_one_does_not_abort_others(self, pipeline, tmp_path):
        """A crash on one PDF must not prevent the rest of the batch from processing."""
        from src.corporate_processor.parser.models import PdfType

        good_pdf = tmp_path / "good.pdf"
        good_pdf.write_bytes(b"%PDF-1.4")

        paths = ["/nonexistent.pdf", str(good_pdf)]

        with patch(_ROUTER_PATH, return_value=PdfType.IMAGE), \
             patch(_OCR_PATH, return_value=_FAKE_OCR_TEXT), \
             patch(_LLAMA_PATH, return_value=_FAKE_METADATA):

            results = pipeline.process_batch(paths)

        assert len(results) == 2
        assert results[0].success is False   # nonexistent file
        assert results[1].success is True    # good file

    def test_empty_batch_returns_empty_list(self, pipeline):
        results = pipeline.process_batch([])
        assert results == []
