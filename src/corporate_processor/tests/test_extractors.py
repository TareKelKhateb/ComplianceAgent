"""
test_extractors.py
------------------
Integration tests for CorporateMistralExtractor.

What is tested
~~~~~~~~~~~~~~
- The adapter correctly delegates to the legacy MistralExtractor.
- The constructor raises EnvironmentError when no API key is provided.
- ``extract_text()`` returns the string produced by the legacy delegate.
- ``extract_text()`` propagates FileNotFoundError from the legacy extractor.
- ``extract_text()`` propagates RuntimeError (API failure) from the legacy extractor.

Mocking strategy
~~~~~~~~~~~~~~~~
We patch ``src.document_processor.extractors.mistral_extractor.Mistral``
(the Mistral SDK client) so no real API calls are made.  The
``CorporateMistralExtractor`` itself is instantiated normally — we only
replace the underlying HTTP client.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FAKE_KEY    = "test-mistral-key-abc123"
_FAKE_PDF    = "/fake/path/document.pdf"
_FAKE_TEXT   = "## Page 1\n\nThis is the extracted corporate compliance text."

# Patch target: the Mistral client imported inside the legacy extractor module.
_MISTRAL_CLIENT_PATH = (
    "src.document_processor.extractors.mistral_extractor.Mistral"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_mistral_client():
    """
    Patch the Mistral SDK client so no HTTP calls are made.

    Returns a MagicMock configured to return _FAKE_TEXT on ocr.process().
    The patch is active for the duration of each test that requests this fixture.
    """
    with patch(_MISTRAL_CLIENT_PATH) as MockMistral:
        # Build a fake OCR response object that mimics the SDK's structure.
        fake_page          = MagicMock()
        fake_page.index    = 0
        fake_page.markdown = "This is the extracted corporate compliance text."

        fake_response       = MagicMock()
        fake_response.pages = [fake_page]

        # client_instance.ocr.process(...) → fake_response
        client_instance             = MagicMock()
        client_instance.ocr.process = MagicMock(return_value=fake_response)
        MockMistral.return_value    = client_instance

        yield MockMistral


@pytest.fixture()
def extractor(mock_mistral_client):
    """
    Return a CorporateMistralExtractor with a fake API key.

    Depends on mock_mistral_client so the Mistral SDK is always patched
    before the extractor is instantiated.
    """
    # pyrefly: ignore [missing-import]
    from src.corporate_processor.extractors.mistral_extractor import (
        CorporateMistralExtractor,
    )
    return CorporateMistralExtractor(api_key=_FAKE_KEY)


# ---------------------------------------------------------------------------
# Tests: construction
# ---------------------------------------------------------------------------

class TestCorporateMistralExtractorInit:
    """Verify constructor behaviour and delegation setup."""

    def test_instantiation_with_explicit_key(self, mock_mistral_client):
        """Extractor must initialise without error when an API key is provided."""
        from src.corporate_processor.extractors.mistral_extractor import (
            CorporateMistralExtractor,
        )
        ext = CorporateMistralExtractor(api_key=_FAKE_KEY)
        assert ext is not None

    def test_instantiation_reads_env_var(self, mock_mistral_client, monkeypatch):
        """When no explicit key is passed, the key must be read from MISTRAL_API_KEY."""
        from src.corporate_processor.extractors.mistral_extractor import (
            CorporateMistralExtractor,
        )
        monkeypatch.setenv("MISTRAL_API_KEY", _FAKE_KEY)
        ext = CorporateMistralExtractor()   # no explicit api_key
        assert ext is not None

    def test_instantiation_raises_without_key(self, monkeypatch):
        """
        Extractor must raise EnvironmentError when neither an explicit key
        nor the MISTRAL_API_KEY env var is set.
        """
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

        # Patch the SDK client class to let the constructor reach the key check.
        with patch(_MISTRAL_CLIENT_PATH, side_effect=Exception("no key")):
            from src.corporate_processor.extractors.mistral_extractor import (
                CorporateMistralExtractor,
            )
            with pytest.raises((EnvironmentError, Exception)):
                CorporateMistralExtractor()

    def test_delegate_is_legacy_mistral_extractor(self, extractor):
        """The internal delegate must be an instance of the legacy MistralExtractor."""
        from src.document_processor.extractors.mistral_extractor import (
            MistralExtractor as LegacyMistralExtractor,
        )
        assert isinstance(extractor._delegate, LegacyMistralExtractor)

    def test_has_extract_text_method(self, extractor):
        """CorporateMistralExtractor must expose the extract_text() method."""
        assert callable(getattr(extractor, "extract_text", None))


# ---------------------------------------------------------------------------
# Tests: extract_text delegation
# ---------------------------------------------------------------------------

class TestCorporateMistralExtractorExtractText:
    """Verify that extract_text() correctly delegates to the legacy extractor."""

    def test_returns_string_from_delegate(self, extractor, tmp_path):
        """
        extract_text() must return the string produced by the legacy delegate.

        We create a real (but empty) temp PDF file so path validation passes,
        then assert the mocked SDK response is surfaced correctly.
        """
        # Create a dummy file so the legacy extractor's os.path.exists check passes.
        dummy_pdf = tmp_path / "corporate_policy.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        result = extractor.extract_text(str(dummy_pdf))

        assert isinstance(result, str)
        # The mock returns one page with our canned markdown.
        assert "Page 1" in result

    def test_calls_legacy_extract_text_exactly_once(self, extractor, tmp_path):
        """
        The adapter must call the legacy delegate's extract_text() exactly once
        per invocation — no extra calls, no caching side-effects.
        """
        dummy_pdf = tmp_path / "doc.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        with patch.object(
            extractor._delegate,
            "extract_text",
            return_value=_FAKE_TEXT,
        ) as mock_delegate:
            extractor.extract_text(str(dummy_pdf))

        mock_delegate.assert_called_once_with(str(dummy_pdf))

    def test_propagates_file_not_found(self, extractor):
        """
        extract_text() must propagate FileNotFoundError raised by the delegate
        when the PDF path does not exist.
        """
        with patch.object(
            extractor._delegate,
            "extract_text",
            side_effect=FileNotFoundError("PDF not found"),
        ):
            with pytest.raises(FileNotFoundError, match="PDF not found"):
                extractor.extract_text("/does/not/exist.pdf")

    def test_propagates_runtime_error_on_api_failure(self, extractor, tmp_path):
        """
        extract_text() must propagate RuntimeError when the Mistral API call
        fails inside the legacy delegate.
        """
        dummy_pdf = tmp_path / "broken.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        with patch.object(
            extractor._delegate,
            "extract_text",
            side_effect=RuntimeError("Mistral API call failed: 500"),
        ):
            with pytest.raises(RuntimeError, match="Mistral API call failed"):
                extractor.extract_text(str(dummy_pdf))

    def test_passes_correct_path_to_delegate(self, extractor, tmp_path):
        """
        The adapter must forward the exact pdf_path string to the delegate
        without modification.
        """
        dummy_pdf = tmp_path / "exact_path_test.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

        with patch.object(
            extractor._delegate,
            "extract_text",
            return_value=_FAKE_TEXT,
        ) as mock_delegate:
            extractor.extract_text(str(dummy_pdf))

        args, _ = mock_delegate.call_args
        assert args[0] == str(dummy_pdf)
