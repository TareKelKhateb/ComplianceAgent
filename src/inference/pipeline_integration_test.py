"""
pipeline_integration_test.py
-----------------------------
Full end-to-end integration test for the upgraded RAG pipeline.

Tests each layer independently, then runs the full chain.
Run from the project root:
    uv run python -m src.inference.pipeline_integration_test

Layers tested:
    [1] AgenticRouter  (Llama 3  — requires Ollama running)
    [2] Retriever      (Qdrant   — requires data/qdrant_db)
    [3] BGEReranker    (bge-v2-m3 — downloaded from HuggingFace on first run)
    [4] Mapper         (SQLite   — requires data/mapping.db)
    [5] ComplianceEngine full pipeline
"""

import sys
import logging
import time
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Colour helpers (Windows-safe ASCII fallback) ───────────────────────────
def ok(msg):  print(f"  [PASS] {msg}")
def fail(msg): print(f"  [FAIL] {msg}"); global _FAILURES; _FAILURES += 1
def sep(title=""): print(f"\n{'='*60}\n  {title}\n{'='*60}" if title else "="*60)

_FAILURES = 0

# Test query — realistic AML compliance question in Arabic
TEST_QUERY = (
    "وفقاً للضوابط الواردة في تعليمات البنك المركزي المصري بشأن مكافحة غسل الأموال، "
    "ما هي الإجراءات الواجب اتباعها عند التعامل مع عميل من عالي المخاطر؟"
)


# ===========================================================================
# LAYER 1 — AgenticRouter
# ===========================================================================
def test_router() -> dict:
    sep("LAYER 1: AgenticRouter (Llama 3)")
    result = {"optimized_query": TEST_QUERY, "intent": "general_compliance", "available": False}

    try:
        from src.inference.router import AgenticRouter
        router = AgenticRouter()
        result["available"] = True

        t0 = time.time()
        output = router.process_query(TEST_QUERY)
        elapsed = time.time() - t0

        ok(f"Router responded in {elapsed:.1f}s")
        ok(f"Intent detected: {output.intent}")
        ok(f"Keywords: {output.keywords}")
        print(f"\n  Optimized query:\n  {output.optimized_query[:200]}\n")

        result["optimized_query"] = output.optimized_query
        result["intent"] = output.intent

    except Exception as e:
        fail(f"Router error: {e}")
        print(f"  -> Using raw query as fallback.")

    return result


# ===========================================================================
# LAYER 2 — Retriever
# ===========================================================================
def test_retriever(query: str) -> list:
    sep("LAYER 2: Retriever (Qdrant Hybrid Search)")
    chunks = []

    try:
        from src.inference.retriever import Retriever
        retriever = Retriever()

        t0 = time.time()
        chunks = retriever.get_law_chunks(query, limit=20)
        elapsed = time.time() - t0

        ok(f"Retrieved {len(chunks)} chunks in {elapsed:.2f}s")

        if chunks:
            ok(f"First chunk hash: {chunks[0].get('hash', 'N/A')[:20]}...")
            ok(f"First chunk preview: {chunks[0].get('content', '')[:100]}...")
        else:
            fail("No chunks retrieved — Qdrant DB may be empty or path is wrong.")

    except Exception as e:
        fail(f"Retriever error: {e}")

    return chunks


# ===========================================================================
# LAYER 3 — BGEReranker
# ===========================================================================
def test_reranker(query: str, chunks: list) -> list:
    sep("LAYER 3: BGEReranker (BAAI/bge-reranker-v2-m3)")
    reranked = []

    if not chunks:
        fail("No chunks to rerank — skipping.")
        return reranked

    try:
        from src.inference.reranker import BGEReranker
        reranker = BGEReranker(device="cpu")

        t0 = time.time()
        reranked = reranker.rerank(query, chunks, top_n=5)
        elapsed = time.time() - t0

        ok(f"Reranked {len(chunks)} -> {len(reranked)} chunks in {elapsed:.2f}s")

        print("\n  Top-5 reranked results:")
        for i, r in enumerate(reranked, 1):
            print(f"    [{i}] score={r['score']:.4f} | {r['content'][:90]}...")

    except Exception as e:
        fail(f"Reranker error: {e}")
        reranked = chunks[:5]  # fallback
        print(f"  -> Falling back to top-5 unreranked chunks.")

    return reranked


# ===========================================================================
# LAYER 4 — Mapper
# ===========================================================================
def test_mapper(chunks: list) -> list:
    sep("LAYER 4: Mapper (SQLite cross-DB JOIN)")
    enriched = []

    if not chunks:
        fail("No chunks to map — skipping.")
        return enriched

    try:
        from src.inference.mapper import Mapper
        mapper = Mapper()

        hits = 0
        for chunk in chunks:
            law_hash = chunk.get("hash", "")
            mapping = mapper.get_mapping_data(law_hash) if law_hash else None
            enriched.append({
                "law_text": chunk.get("content", ""),
                "corp_text": mapping.get("corp_text", "N/A") if mapping else "No mapping found.",
                "reasoning": mapping.get("reasoning", "N/A") if mapping else "No reasoning.",
                "score": chunk.get("score", 0.0),
                "hash": law_hash,
            })
            if mapping:
                hits += 1

        ok(f"Mapped {hits}/{len(chunks)} chunks to corporate policies.")
        if enriched:
            ok(f"Sample corp_text: {enriched[0]['corp_text'][:100]}...")

    except Exception as e:
        fail(f"Mapper error: {e}")

    return enriched


# ===========================================================================
# LAYER 5 — Full ComplianceEngine pipeline
# ===========================================================================
def test_full_engine():
    sep("LAYER 5: Full ComplianceEngine (End-to-End)")

    try:
        from src.inference.engine import ComplianceEngine

        engine = ComplianceEngine(
            enable_router=True,
            enable_reranker=True,
            reranker_device="cpu",
        )

        t0 = time.time()
        response = engine.run(TEST_QUERY)
        elapsed = time.time() - t0

        ok(f"Full pipeline completed in {elapsed:.1f}s")
        ok(f"Response length: {len(response)} characters")

        print(f"\n{'─'*60}")
        print("  FINAL LLM RESPONSE:")
        print(f"{'─'*60}")
        print(response)
        print(f"{'─'*60}\n")

    except Exception as e:
        fail(f"ComplianceEngine error: {e}")
        import traceback
        traceback.print_exc()


# ===========================================================================
# Main runner
# ===========================================================================
def main():
    global _FAILURES
    _FAILURES = 0

    sep("COMPLIANCE AGENT — FULL PIPELINE INTEGRATION TEST")
    print(f"  Query: {TEST_QUERY[:80]}...")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  CWD: {os.getcwd()}")

    # Run layers independently first (useful for debugging individual failures)
    router_result = test_router()
    optimized_query = router_result["optimized_query"]

    chunks = test_retriever(optimized_query)
    reranked = test_reranker(optimized_query, chunks)
    test_mapper(reranked)

    # Run the full engine end-to-end
    test_full_engine()

    # Summary
    sep("TEST SUMMARY")
    if _FAILURES == 0:
        print("  All layers passed successfully.")
    else:
        print(f"  {_FAILURES} layer(s) had failures. Review logs above.")
    sep()

    sys.exit(_FAILURES)


if __name__ == "__main__":
    main()
