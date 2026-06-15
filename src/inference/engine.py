"""
engine.py
---------
Phase 3 of the RAG Pipeline Upgrade.

The ComplianceEngine is the central orchestrator for the full pipeline.
It chains all layers in strict sequence:

    Raw Query
        -> [1] AgenticRouter     (Llama 3)    — query optimization
        -> [2] Retriever         (Qdrant)     — hybrid search, top-20 broad results
        -> [3] BGEReranker       (bge-v2-m3)  — re-score & filter to top-5
        -> [4] Mapper            (SQLite)     — fetch corporate policy + reasoning
        -> [5] Qwen 2.5          (Ollama)     — final response generation

Design Principles:
  - Each layer is independently replaceable (Pydantic data contracts).
  - Graceful degradation: if the Router fails, raw query is used. 
    If Reranker produces zero results, broad Retriever results are used.
  - The new Jinja2 template (qwen_inference_prompt.jinja2) renders
    reranked chunks with their scores for better LLM grounding.
  - The original compliance_prompt.jinja2 is preserved for backward compat.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# --- Inference layer imports with graceful fallbacks ---
try:
    from src.inference.retriever import Retriever
except ImportError:
    class Retriever:  # type: ignore[no-redef]
        def get_law_chunks(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
            return []

try:
    from src.inference.mapper import Mapper
except ImportError:
    class Mapper:  # type: ignore[no-redef]
        def get_mapping_data(self, hash_val: str) -> Optional[Dict[str, Any]]:
            return None

try:
    from src.inference.reranker import BGEReranker
except ImportError:
    BGEReranker = None  # type: ignore[assignment,misc]

try:
    from src.inference.router import AgenticRouter
except ImportError:
    AgenticRouter = None  # type: ignore[assignment,misc]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal data model: a fully enriched chunk passed to the LLM
# ---------------------------------------------------------------------------

@dataclass
class EnrichedChunk:
    """
    A reranked chunk enriched with corporate mapping data, ready for the LLM.
    """
    law_text: str
    corp_text: str
    reasoning: str
    score: float = 0.0
    hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ComplianceEngine (upgraded orchestrator)
# ---------------------------------------------------------------------------

class ComplianceEngine:
    """
    Upgraded orchestrator that chains the full 5-layer RAG pipeline:
    Router -> Retriever -> Reranker -> Mapper -> LLM (Qwen 2.5).
    """

    # Retriever broad recall limit before reranking
    RETRIEVER_TOP_K: int = 20
    # Reranker output limit passed to Mapper + LLM
    RERANKER_TOP_N: int = 5

    def __init__(
        self,
        enable_router: bool = True,
        enable_reranker: bool = True,
        reranker_device: Optional[str] = None,
    ):
        """
        Initializes all pipeline layers.

        Args:
            enable_router:    Set False to bypass Llama 3 and use raw query directly.
            enable_reranker:  Set False to bypass BGE-Reranker (for low-VRAM machines).
            reranker_device:  'cuda' or 'cpu'. None = auto-detect.
        """
        logger.info("=" * 60)
        logger.info("Initializing ComplianceEngine (Upgraded Pipeline)")
        logger.info("  Router   : %s", "ENABLED" if enable_router else "DISABLED")
        logger.info("  Reranker : %s", "ENABLED" if enable_reranker else "DISABLED")
        logger.info("=" * 60)

        load_dotenv()

        self.llm_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/generate")
        self.llm_model = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
        logger.info("Inference LLM: %s @ %s", self.llm_model, self.llm_url)

        # --- Layer 1: Router (Llama 3) ---
        self.router: Optional[AgenticRouter] = None
        if enable_router and AgenticRouter is not None:
            try:
                self.router = AgenticRouter()
                logger.info("[Layer 1] AgenticRouter ready.")
            except Exception as e:
                logger.warning("[Layer 1] AgenticRouter failed to init: %s. Continuing without router.", e)

        # --- Layer 2: Retriever (Qdrant Hybrid Search) ---
        try:
            self.retriever = Retriever()
            logger.info("[Layer 2] Retriever ready.")
        except Exception as e:
            logger.error("[Layer 2] Retriever init failed: %s", e)
            raise

        # --- Layer 3: BGE-Reranker ---
        self.reranker: Optional[BGEReranker] = None
        if enable_reranker and BGEReranker is not None:
            try:
                self.reranker = BGEReranker(device=reranker_device)
                logger.info("[Layer 3] BGEReranker ready.")
            except Exception as e:
                logger.warning("[Layer 3] BGEReranker failed to init: %s. Continuing without reranker.", e)

        # --- Layer 4: Mapper (SQLite) ---
        try:
            self.mapper = Mapper()
            logger.info("[Layer 4] Mapper ready.")
        except Exception as e:
            logger.error("[Layer 4] Mapper init failed: %s", e)
            raise

        # --- Layer 5: Jinja2 prompt template ---
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompts_dir = os.path.join(base_dir, "src", "inference", "prompts")
        qwen_template_path = os.path.join(prompts_dir, "qwen_inference_prompt.jinja2")

        if os.path.exists(qwen_template_path):
            qwen_env = Environment(loader=FileSystemLoader(searchpath=prompts_dir))
            self.qwen_template = qwen_env.get_template("qwen_inference_prompt.jinja2")
            logger.info("[Layer 5] Qwen inference template loaded from: %s", prompts_dir)
        else:
            self.qwen_template = None
            logger.warning(
                "[Layer 5] qwen_inference_prompt.jinja2 not found at %s. "
                "Will use inline fallback prompt.", prompts_dir
            )
        logger.info("ComplianceEngine initialization complete.\n")

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(self, user_query: str) -> str:
        """
        Main entry point. Executes the full 5-layer pipeline.

        Args:
            user_query: The raw, unprocessed query from the user.

        Returns:
            The final Arabic compliance analysis response string.
        """
        if not user_query or not user_query.strip():
            return "يرجى تقديم سؤال صحيح."

        logger.info("\n%s\nProcessing: '%s'\n%s", "="*60, user_query[:80], "="*60)

        # ── LAYER 1: Route & Optimize Query ───────────────────────────────
        optimized_query = user_query
        router_intent = "general_compliance"

        if self.router:
            try:
                router_output = self.router.process_query(user_query)
                optimized_query = router_output.optimized_query
                router_intent = router_output.intent
                logger.info(
                    "[Router] Intent: %s | Optimized: '%s'",
                    router_intent, optimized_query[:80]
                )
            except Exception as e:
                logger.warning("[Router] Exception during routing: %s. Using raw query.", e)
        else:
            logger.info("[Router] Skipped. Using raw query.")

        # ── LAYER 2: Broad Hybrid Retrieval ───────────────────────────────
        try:
            broad_chunks: List[Dict[str, Any]] = self.retriever.get_law_chunks(
                optimized_query, limit=self.RETRIEVER_TOP_K
            )
            logger.info("[Retriever] Retrieved %d broad chunks.", len(broad_chunks))
        except Exception as e:
            logger.error("[Retriever] Failed: %s", e)
            return "حدث خطأ أثناء استرجاع النصوص القانونية ذات الصلة."

        if not broad_chunks:
            return "لم يتم العثور على نصوص قانونية ذات صلة بسؤالك. تنطبق سياسة الشركة بشكل مباشر."

        # ── LAYER 3: Rerank → top N ────────────────────────────────────────
        if self.reranker:
            try:
                reranked_chunks = self.reranker.rerank(
                    optimized_query, broad_chunks, top_n=self.RERANKER_TOP_N
                )
                logger.info(
                    "[Reranker] Filtered %d -> %d chunks.",
                    len(broad_chunks), len(reranked_chunks)
                )
                # Graceful fallback: if reranker returns nothing, use broad results
                chunks_for_mapping = reranked_chunks if reranked_chunks else broad_chunks[:self.RERANKER_TOP_N]
            except Exception as e:
                logger.warning("[Reranker] Failed: %s. Using broad retrieval results.", e)
                chunks_for_mapping = broad_chunks[:self.RERANKER_TOP_N]
        else:
            logger.info("[Reranker] Skipped. Using top-%d broad results.", self.RERANKER_TOP_N)
            chunks_for_mapping = broad_chunks[:self.RERANKER_TOP_N]

        # ── LAYER 4: Enrich with Mapper (corporate policy + reasoning) ────
        enriched_chunks: List[EnrichedChunk] = self._enrich_with_mapping(chunks_for_mapping)
        logger.info("[Mapper] Enriched %d chunks with corporate mapping data.", len(enriched_chunks))

        # ── LAYER 5: Render Prompt & Call LLM (Qwen 2.5) ─────────────────
        prompt = self._render_prompt(optimized_query, enriched_chunks)
        return self._call_llm_api(prompt)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _enrich_with_mapping(self, chunks: List[Dict[str, Any]]) -> List[EnrichedChunk]:
        """Iterates through reranked chunks and fetches corporate policy from SQLite."""
        enriched: List[EnrichedChunk] = []

        for chunk in chunks:
            law_hash = chunk.get("hash", "")
            law_text = chunk.get("content", "")
            score = chunk.get("score", 0.0)

            corp_text = "لا توجد سياسة مؤسسية معيّنة لهذا النص القانوني."
            reasoning = "لا يوجد تحليل سابق. يُوصى بإجراء مراجعة يدوية."

            if law_hash:
                try:
                    mapping = self.mapper.get_mapping_data(law_hash)
                    if mapping:
                        corp_text = mapping.get("corp_text", corp_text)
                        reasoning = mapping.get("reasoning", reasoning)
                except Exception as e:
                    logger.warning("[Mapper] Error for hash %s: %s", law_hash, e)

            enriched.append(EnrichedChunk(
                law_text=law_text,
                corp_text=corp_text,
                reasoning=reasoning,
                score=score,
                hash=law_hash,
            ))

        return enriched

    def _render_prompt(self, optimized_query: str, chunks: List[EnrichedChunk]) -> str:
        """Renders the Jinja2 prompt. Falls back to a safe inline string if template missing."""
        chunk_dicts = [
            {
                "law_text": c.law_text,
                "corp_text": c.corp_text,
                "reasoning": c.reasoning,
                "score": c.score,
                "hash": c.hash,
            }
            for c in chunks
        ]

        if self.qwen_template:
            try:
                return self.qwen_template.render(
                    optimized_query=optimized_query,
                    chunks=chunk_dicts,
                )
            except Exception as e:
                logger.warning("[Prompt] Template rendering failed: %s. Using inline fallback.", e)

        # Inline fallback — no file dependency
        context_blocks = []
        for i, c in enumerate(chunks, 1):
            block = f"[{i}] Law Text (score: {c.score:.3f}):\n{c.law_text}\n"
            if c.corp_text:
                block += f"[{i}] Corporate Policy:\n{c.corp_text}\n"
            if c.reasoning:
                block += f"[{i}] Gap Analysis:\n{c.reasoning}\n"
            context_blocks.append(block)

        return (
            f"You are a legal compliance expert for Egyptian law.\n"
            f"Answer the following question based ONLY on the context below.\n"
            f"Your response MUST be in formal Arabic (العربية الفصحى).\n\n"
            f"Question: {optimized_query}\n\n"
            f"Context:\n{'---'.join(context_blocks)}\n\n"
            f"Response (in Arabic):"
        )

    def _call_llm_api(self, prompt: str) -> str:
        """Sends the rendered prompt to Qwen 2.5 via Ollama."""
        logger.info("[LLM] Sending prompt to %s @ %s...", self.llm_model, self.llm_url)

        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }

        try:
            response = requests.post(self.llm_url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            llm_response = data.get("response", "").strip()

            if not llm_response:
                logger.warning("[LLM] Empty response received.")
                return "عذراً، لم أتمكن من توليد رد في الوقت الحالي. يرجى المحاولة مرة أخرى."

            logger.info("[LLM] Response generated successfully (%d chars).", len(llm_response))
            return llm_response

        except requests.exceptions.ConnectionError:
            logger.error("[LLM] Cannot connect to Ollama. Is it running? (ollama serve)")
            return "عذراً، لا يمكن الاتصال بمحرك الذكاء الاصطناعي. يرجى التأكد من تشغيل خادم Ollama."
        except requests.exceptions.Timeout:
            logger.error("[LLM] Qwen 2.5 timed out after 120s.")
            return "عذراً، استغرق الذكاء الاصطناعي وقتاً طويلاً للرد. يرجى المحاولة مرة أخرى."
        except requests.exceptions.RequestException as e:
            logger.error("[LLM] HTTP error: %s", e)
            return "عذراً، حدث خطأ في التواصل مع محرك الذكاء الاصطناعي."
        except Exception as e:
            logger.error("[LLM] Unexpected error: %s", e)
            return "عذراً، حدث خطأ غير متوقع أثناء معالجة الطلب."


if __name__ == "__main__":
    engine = ComplianceEngine()
    response = engine.run(
        "وفقاً للضوابط الواردة في تعليمات البنك المركزي المصري بشأن مكافحة غسل الأموال، "
        "ما هي الإجراءات الواجب اتباعها عند التعامل مع عميل من عالي المخاطر؟"
    )
    print("\n--- Final LLM Response ---\n")
    print(response)
