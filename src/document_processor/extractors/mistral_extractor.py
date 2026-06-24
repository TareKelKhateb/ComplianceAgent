import base64
import os
from typing import List

from mistralai.client import Mistral
from mistralai.client.utils import BackoffStrategy, RetryConfig

from .base_extractor import BaseExtractor
from dotenv import load_dotenv

load_dotenv()

class MistralExtractor(BaseExtractor):
    """
    Extractor implementation backed by the Mistral OCR API.

    Sends the entire PDF as a base64-encoded payload to Mistral's
    ``mistral-ocr-latest`` model.  Each page already comes back as
    high-quality Markdown, so no manual bounding-box or regex header
    mapping is needed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "mistral-ocr-latest",
        table_format: str = "markdown",
    ) -> None:
        """
        Args:
            api_key (str | None): Mistral API key.  Falls back to the
                                  ``MISTRAL_API_KEY`` environment variable.
            model (str):          Mistral OCR model name.
            table_format (str):   Format to use for detected tables
                                  (``"markdown"`` or ``"html"``).
        """
        resolved_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not resolved_key:
            raise EnvironmentError(
                "MistralExtractor requires a Mistral API key. "
                "Set MISTRAL_API_KEY in your environment or pass api_key= explicitly."
            )

        retry_config = RetryConfig(
            strategy="backoff",
            backoff=BackoffStrategy(
                initial_interval=1000,
                max_interval=60000,
                exponent=2.0,
                max_elapsed_time=300000
            ),
            retry_connection_errors=True
        )
        self._client = Mistral(api_key=resolved_key, retry_config=retry_config)
        self._model = model
        self._table_format = table_format

    # ------------------------------------------------------------------
    # BaseExtractor contract
    # ------------------------------------------------------------------

    def extract_text(self, pdf_path: str) -> str:
        """
        Send the PDF to the Mistral OCR API and return a single Markdown string.

        Pages are separated by a ``---`` horizontal rule and a ``## Page N``
        heading to keep the output consistent with ``EasyOcrExtractor``.

        Args:
            pdf_path (str): Path to the input PDF file.

        Returns:
            str: Full document as a Markdown string.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            RuntimeError:      If the Mistral API call fails.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"[Mistral] PDF not found: {pdf_path}")

        print(f"[*] Mistral OCR: Encoding '{pdf_path}' as base64…")

        with open(pdf_path, "rb") as f:
            base64_pdf = base64.standard_b64encode(f.read()).decode("utf-8")

        print(f"[*] Mistral OCR: Sending to model '{self._model}'…")

        try:
            ocr_response = self._client.ocr.process(
                model=self._model,
                document={
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{base64_pdf}",
                },
                table_format=self._table_format,
            )
        except Exception as exc:
            raise RuntimeError(f"[Mistral] API call failed: {exc}") from exc

        # Stitch pages into one Markdown string -------------------------
        parts: List[str] = []
        for page in ocr_response.pages:
            parts.append(
                f"---\n\n## Page {page.index + 1}\n\n{page.markdown}\n"
            )

        full_markdown = "\n".join(parts)
        print(
            f"[+] Mistral OCR: Extraction complete "
            f"({len(ocr_response.pages)} pages, {len(full_markdown):,} chars)."
        )
        return full_markdown
