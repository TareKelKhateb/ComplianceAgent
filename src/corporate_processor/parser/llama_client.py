"""
llama_client.py
---------------
LlamaClient — Llama API interaction and JSON response parsing.

Responsibility (single):
    Given raw text already extracted from a PDF, call the Llama API with a
    structured extraction prompt and return a validated Python dict.

No file I/O, no PDF handling, no routing decisions.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

try:
    from openai import OpenAI  # type: ignore[import]
except ImportError as _e:
    raise ImportError("openai is required: pip install openai") from _e

# pyrefly: ignore [missing-import]
from .models import EXTRACTION_PROMPT
from ..config import CorporateConfig

logger = logging.getLogger(__name__)

# Maximum characters of PDF text embedded in the API prompt.
# 12 000 chars ≈ 3 000 tokens — well within all Llama 3 context windows
# while retaining enough content for reliable header/preamble extraction.
_MAX_TEXT_CHARS = 12_000


class LlamaClient:
    """
    Thin wrapper around the OpenAI-compatible Llama API endpoint.

    Parameters
    ----------
    config : CorporateConfig
        Supplies ``llama_api_key``, ``llama_api_base_url``, and ``llama_model``.

    Example
    -------
    ::

        client = LlamaClient(config)
        metadata: dict = client.extract_metadata(raw_text)
    """

    def __init__(self, config: CorporateConfig) -> None:
        self._cfg = config
        
        # Validation Debug
        key_start = self._cfg.mistral_api_key[:4] if self._cfg.mistral_api_key else "None"
        logger.info(
            "[LlamaClient] Initialization Debug - base_url: %s, api_key_start: %s***",
            self._cfg.mistral_api_base_url,
            key_start
        )
        print(f"[LlamaClient] Initialization Debug - base_url: {self._cfg.mistral_api_base_url}, api_key_start: {key_start}***")
        
        self.client = OpenAI(
            api_key=self._cfg.mistral_api_key,
            base_url=self._cfg.mistral_api_base_url,
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def extract_metadata(self, raw_text: str) -> dict[str, Any]:
        """
        Send *raw_text* to the Llama API and return the parsed metadata dict.

        Steps
        ~~~~~
        1. Validate that the API key is configured.
        2. Truncate *raw_text* to ``_MAX_TEXT_CHARS``.
        3. Build and send the extraction prompt.
        4. Parse + validate the JSON response.

        Parameters
        ----------
        raw_text : str
            Full text extracted from a PDF by :class:`~text_extractor.TextExtractor`
            (or from the OCR engine for image-based PDFs).

        Returns
        -------
        dict[str, Any]
            Parsed metadata with keys: ``title``, ``document_type``,
            ``issuing_entity``, ``document_number``, ``year``, ``date``,
            ``language``, ``category``, ``subcategory``.

        Raises
        ------
        ValueError
            If the API key is missing, the response is empty, or the
            response cannot be decoded as a JSON object.
        openai.APIError
            Propagated if the HTTP request fails or the API returns an error.
        """
        # ── Truncate ─────────────────────────────────────────────────────────
        text_for_prompt = raw_text[:_MAX_TEXT_CHARS]
        if len(raw_text) > _MAX_TEXT_CHARS:
            logger.debug(
                "[LlamaClient] Text truncated %d → %d chars for prompt.",
                len(raw_text), _MAX_TEXT_CHARS,
            )

        # ── API call ─────────────────────────────────────────────────────────
        raw_response = self._call_api(text_for_prompt)

        # ── Parse ─────────────────────────────────────────────────────────────
        return self._parse_json(raw_response)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_api(self, text: str) -> str:
        """
        Build the prompt and call the Llama API.

        Parameters
        ----------
        text : str
            Already-truncated PDF text to embed in the prompt.

        Returns
        -------
        str
            Raw content string returned by the model's first choice.

        Raises
        ------
        ValueError
            If the API returns an empty response body.
        """
        prompt = EXTRACTION_PROMPT.format(text=text)

        logger.debug(
            "[LlamaClient] POST %s  model=%s  prompt_chars=%d",
            self._cfg.mistral_api_base_url, self._cfg.mistral_model, len(prompt),
        )

        response = self.client.chat.completions.create(
            model=self._cfg.mistral_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a corporate document metadata extractor. "
                        "You can process both English and Arabic documents with high precision. "
                        "Normalization: All classification fields, specifically 'document_type', "
                        "'category', and 'subcategory', MUST be returned in English, automatically "
                        "mapping Arabic terms to their appropriate English technical equivalents "
                        "(e.g., 'Financial Statements' instead of 'القوائم المالية'). "
                        "Preservation: The 'title' and 'issuing_entity' MUST be preserved in their "
                        "original language as they appear in the document. "
                        "Always respond with a single, strictly valid JSON object and nothing else."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,   # Deterministic — metadata extraction is not creative
            max_tokens=512,    # Target JSON is small; 512 tokens is ample
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Llama API returned an empty response.")

        logger.debug(
            "[LlamaClient] Response received (%d chars).", len(content)
        )
        return content

    def _parse_json(self, raw_response: str) -> dict[str, Any]:
        """
        Clean and decode the model's raw response string into a Python dict.

        Defensive handling
        ~~~~~~~~~~~~~~~~~~
        Despite the prompt instruction, the model occasionally wraps the JSON
        in markdown code fences (\\`\\`\\`json … \\`\\`\\`).  This method strips
        such fences before parsing.

        Parameters
        ----------
        raw_response : str
            Raw string returned by :meth:`_call_api`.

        Returns
        -------
        dict[str, Any]
            Validated metadata dictionary.

        Raises
        ------
        ValueError
            If the cleaned response cannot be decoded as a JSON *object*.
        """
        cleaned = raw_response.strip()

        # Strip markdown code fences: ```json … ``` or ``` … ```
        fence = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.MULTILINE)
        match = fence.search(cleaned)
        if match:
            cleaned = match.group(1).strip()
            logger.debug("[LlamaClient] Stripped markdown code fence.")

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON decode error: {exc}. "
                f"Raw response (first 300 chars): {cleaned[:300]}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected a JSON object, got {type(parsed).__name__}."
            )

        logger.debug("[LlamaClient] Metadata extracted: %s", list(parsed.keys()))
        return parsed
