"""
router.py
---------
Phase 2 of the RAG Pipeline Upgrade.

Implements the AgenticRouter class — a pre-processing layer that sits
at the very front of the pipeline. It receives the raw user query,
sends it to Llama 3 (via Ollama), and returns a structured, semantically
enriched search query for the Retriever.

Flow:
    Raw User Query
        -> AgenticRouter.process_query()   [Llama 3]
            -> optimized_query (str)
            -> keywords       (list)
            -> intent         (str)
        -> Retriever.get_law_chunks(optimized_query, limit=20)

Design decisions:
  - Llama 3 is instructed (via router_prompt.jinja2) to output ONLY a raw
    JSON object. We parse that JSON with a Pydantic model for type safety.
  - On any failure (timeout, bad JSON, Ollama down), the router falls back
    gracefully to the original raw query so the pipeline never fully breaks.
  - The router is intentionally synchronous to match the rest of the
    current pipeline. It can be made async in a future refactor.
"""

import json
import logging
import os
import re
from typing import List, Optional

import requests
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, ValidationError, field_validator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Output Schema
# ---------------------------------------------------------------------------

class RouterOutput(BaseModel):
    """
    Validated, typed output from the Llama 3 router.
    Enforces that all required fields are present and correctly typed
    before the optimized query is passed downstream.
    """
    optimized_query: str
    keywords: List[str]
    intent: str
    language: str = "ar"

    @field_validator("optimized_query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("optimized_query cannot be empty.")
        return v.strip()

    @field_validator("intent")
    @classmethod
    def intent_must_be_valid(cls, v: str) -> str:
        valid = {
            "law_lookup", "policy_gap_analysis",
            "employee_rights", "aml_compliance", "general_compliance"
        }
        if v not in valid:
            logger.warning("Router returned unknown intent '%s'. Defaulting to 'general_compliance'.", v)
            return "general_compliance"
        return v

    @field_validator("keywords")
    @classmethod
    def keywords_must_be_list(cls, v: List[str]) -> List[str]:
        return [kw.strip() for kw in v if kw.strip()]


# ---------------------------------------------------------------------------
# AgenticRouter
# ---------------------------------------------------------------------------

class AgenticRouter:
    """
    Pre-processing layer using Llama 3 (via Ollama) to optimize user queries
    before they are sent to the Qdrant Hybrid Search Retriever.

    Responsibilities:
      1. Loads the router_prompt.jinja2 template.
      2. Renders the prompt with the raw user query.
      3. Sends it to Llama 3 via the Ollama /api/generate endpoint.
      4. Parses and validates the JSON response into a RouterOutput model.
      5. Returns the optimized_query string (and optionally the full output).

    Fallback Strategy:
      If Llama 3 is unavailable, times out, or returns malformed output,
      the raw user query is returned unchanged so the pipeline continues.
    """

    def __init__(
        self,
        router_model: Optional[str] = None,
        ollama_url: Optional[str] = None,
        timeout: int = 45,
    ):
        """
        Args:
            router_model: Ollama model tag for Llama 3 (e.g. 'llama3:8b').
                          Reads from env var ROUTER_MODEL_NAME if not set.
            ollama_url:   Ollama API base URL. Reads from LLM_BASE_URL env var.
            timeout:      Request timeout in seconds. Llama 3 8B is fast enough
                          for this to be low; increase for 70B.
        """
        load_dotenv()

        self.model = router_model or os.getenv("ROUTER_MODEL_NAME", "llama3:8b")
        self.url = ollama_url or os.getenv("LLM_BASE_URL", "http://localhost:11434/api/generate")
        self.timeout = timeout

        logger.info("AgenticRouter configured — model: %s | url: %s", self.model, self.url)

        # Resolve the prompts directory relative to this file's location
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompts_dir = os.path.join(base_dir, "src", "inference", "prompts")

        if not os.path.isdir(prompts_dir):
            raise FileNotFoundError(f"Prompts directory not found: {prompts_dir}")

        jinja_env = Environment(loader=FileSystemLoader(searchpath=prompts_dir))
        self.template = jinja_env.get_template("router_prompt.jinja2")
        logger.info("Router prompt template loaded from: %s", prompts_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_query(self, raw_query: str) -> RouterOutput:
        """
        Sends raw_query through Llama 3 and returns a validated RouterOutput.

        Falls back to a default RouterOutput wrapping the original query
        on any failure (network error, timeout, malformed JSON, etc.).

        Args:
            raw_query: The unprocessed string from the user.

        Returns:
            RouterOutput with optimized_query, keywords, intent, language.
        """
        if not raw_query or not raw_query.strip():
            logger.warning("AgenticRouter received an empty query. Using default pass-through.")
            return self._fallback_output(raw_query or "")

        logger.info("AgenticRouter processing query: '%s'", raw_query[:80])

        # 1. Render the prompt
        rendered_prompt = self.template.render(raw_query=raw_query)

        # 2. Call Llama 3
        raw_llm_response = self._call_llm(rendered_prompt)
        if not raw_llm_response:
            logger.warning("Router LLM returned empty response. Falling back to raw query.")
            return self._fallback_output(raw_query)

        # 3. Parse & validate
        router_output = self._parse_response(raw_llm_response, raw_query)
        logger.info(
            "Router output — intent: %s | keywords: %s | query: '%s'",
            router_output.intent,
            router_output.keywords,
            router_output.optimized_query[:60],
        )
        return router_output

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Calls Ollama /api/generate with the rendered router prompt."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",       # Ollama native JSON mode — forces valid JSON output
            "options": {
                "temperature": 0.0, # Zero temperature for deterministic, structured output
                "num_predict": 512,
            },
        }
        try:
            response = requests.post(self.url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()

        except requests.exceptions.ConnectionError:
            logger.error(
                "Router: Cannot connect to Ollama at %s. "
                "Is Ollama running? (run: ollama serve)", self.url
            )
        except requests.exceptions.Timeout:
            logger.error(
                "Router: Llama 3 timed out after %ds. "
                "Consider using a smaller model or increasing timeout.", self.timeout
            )
        except requests.exceptions.RequestException as e:
            logger.error("Router: HTTP error calling Llama 3: %s", e)
        except Exception as e:
            logger.error("Router: Unexpected error: %s", e)

        return None

    def _parse_response(self, raw_response: str, original_query: str) -> RouterOutput:
        """
        Attempts to extract and parse a JSON object from the LLM's raw text.
        Uses regex to isolate the first valid JSON block as a safety net
        against any extra commentary the model might prepend/append.
        """
        # Try to extract a JSON block if the model wrapped it in markdown
        json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if not json_match:
            logger.warning("Router: No JSON object found in LLM response. Falling back.")
            return self._fallback_output(original_query)

        json_str = json_match.group(0)

        try:
            parsed_dict = json.loads(json_str)
            return RouterOutput(**parsed_dict)
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning("Router: Failed to parse/validate JSON response: %s", e)
            return self._fallback_output(original_query)

    @staticmethod
    def _fallback_output(raw_query: str) -> RouterOutput:
        """
        Constructs a safe pass-through RouterOutput using the original query.
        This ensures the pipeline always has a valid query to continue with.
        """
        logger.info("Router: Using fallback pass-through for query.")
        return RouterOutput(
            optimized_query=raw_query,
            keywords=[],
            intent="general_compliance",
            language="ar",
        )
