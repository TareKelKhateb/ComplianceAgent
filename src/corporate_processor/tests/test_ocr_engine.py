"""
test_ocr_engine.py
------------------
Integration tests for CorporateOCREngine.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

_FAKE_KEY      = "test-mistral-key-ocr"
_FAKE_OCR_TEXT = "## Page 1\n\nExtracted compliance text via OCR."
_MISTRAL_SDK   = "src.document_processor.extractors.mistral_extractor.Mistral"


@pytest.fixture()
def patched_mistral_sdk():
    with patch(_MISTRAL_SDK) as MockMistral:
        fake_page          = MagicMock()
        fake_page.index    = 0
        fake_page.markdown = "Extracted compliance text via OCR."
        fake_response       = MagicMock()
        fake_response.pages = [fake_page]
        client              = MagicMock()
        client.ocr.process  = MagicMock(return_value=fake_response)
        MockMistral.return_value = client
        yield MockMistral


@pytest.fixture()
def ocr_engine(patched_mistral_sdk, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", _FAKE_KEY)
    from src.corporate_processor.ocr_engine import CorporateOCREngine
    return CorporateOCREngine()


class TestCorporateOCREngineInit:

    def test_default_extractor_is_mistral(self, ocr_engine):
        from src.corporate_processor.extractors.mistral_extractor import (
            CorporateMistralExtractor,
        )
        assert isinstance(ocr_engine._extractor, CorporateMistralExtractor)

    def test_custom_extractor_injection(self, patched_mistral_sdk, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", _FAKE_KEY)
        from src.corporate_processor.ocr_engine import CorporateOCREngine
        from src.corporate_processor.extractors.base_extractor import CorporateBaseExtractor

        class FakeExtractor(CorporateBaseExtractor):
            def extract_text(self, pdf_path: str) -> str:
                return "fake ocr output"

        engine = CorporateOCREngine(extractor=FakeExtractor())
        assert isinstance(engine._extractor, FakeExtractor)

    def test_internal_engine_is_legacy_ocr_engine(self, ocr_engine):
        from src.document_processor.ocr_engine import OCREngine as LegacyOCREngine
        assert isinstance(ocr_engine._engine, LegacyOCREngine)

    def test_has_process_document_method(self, ocr_engine):
        assert callable(getattr(ocr_engine, "process_document", None))


class TestCorporateOCREngineProcessDocument:

    def test_returns_string(self, ocr_engine, tmp_path):
        dummy_pdf = tmp_path / "scanned.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        with patch.object(ocr_engine._engine, "process_document", return_value=_FAKE_OCR_TEXT):
            result = ocr_engine.process_document(str(dummy_pdf))
        assert isinstance(result, str) and len(result) > 0

    def test_delegates_to_legacy_engine_exactly_once(self, ocr_engine, tmp_path):
        dummy_pdf = tmp_path / "delegate_test.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        with patch.object(ocr_engine._engine, "process_document", return_value=_FAKE_OCR_TEXT) as mock_eng:
            ocr_engine.process_document(str(dummy_pdf))
        mock_eng.assert_called_once_with(str(dummy_pdf))

    def test_returns_exact_text_from_legacy_engine(self, ocr_engine, tmp_path):
        dummy_pdf = tmp_path / "exact_text.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        expected = "## Page 1\n\nVerbatim OCR output — must not be altered."
        with patch.object(ocr_engine._engine, "process_document", return_value=expected):
            result = ocr_engine.process_document(str(dummy_pdf))
        assert result == expected

    def test_propagates_file_not_found(self, ocr_engine):
        with patch.object(ocr_engine._engine, "process_document",
                          side_effect=FileNotFoundError("PDF not found")):
            with pytest.raises(FileNotFoundError):
                ocr_engine.process_document("/ghost.pdf")

    def test_propagates_runtime_error(self, ocr_engine, tmp_path):
        dummy_pdf = tmp_path / "broken.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        with patch.object(ocr_engine._engine, "process_document",
                          side_effect=RuntimeError("Mistral OCR timed out")):
            with pytest.raises(RuntimeError, match="Mistral OCR timed out"):
                ocr_engine.process_document(str(dummy_pdf))

    def test_markdown_output_surfaced_unchanged(self, ocr_engine, tmp_path):
        dummy_pdf = tmp_path / "markdown_test.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
        markdown = "---\n\n## Page 1\n\n# AML Policy 2024\n\nArticle 1: Purpose\n"
        with patch.object(ocr_engine._engine, "process_document", return_value=markdown):
            result = ocr_engine.process_document(str(dummy_pdf))
        assert "## Page 1" in result and "AML Policy" in result
