"""
reranker_test.py
----------------
Self-contained test for the BGEReranker (Phase 1).

Run from the project root:
    python -m src.inference.reranker_test

No live Qdrant or LLM connection required — uses dummy document chunks
that simulate what the Retriever would return after a Hybrid Search.

The test verifies:
    1. The reranker loads BAAI/bge-reranker-v2-m3 correctly.
    2. It accepts a List[Dict] with "hash" and "content" keys.
    3. The returned list is sorted by descending score.
    4. The top_n parameter correctly limits results.
    5. Edge cases: empty query, empty documents, empty content fields.
"""

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

try:
    from src.inference.reranker import BGEReranker
except ImportError:
    # Allow running directly from the src/inference/ folder during dev
    from reranker import BGEReranker


# ---------------------------------------------------------------------------
# Dummy Data — simulates Retriever output from a compliance domain query
# ---------------------------------------------------------------------------
DUMMY_QUERY = "ما هي إجراءات مكافحة غسل الأموال المطلوبة للعملاء عالي المخاطر؟"

# 10 dummy chunks: mix of highly relevant, partially relevant, and off-topic
DUMMY_DOCUMENTS = [
    {
        "hash": "hash_001",
        "content": (
            "يجب على البنوك تطبيق إجراءات العناية الواجبة المعززة (EDD) على العملاء "
            "المصنفين كعالي المخاطر، بما في ذلك التحقق من مصدر الأموال والثروة، "
            "والحصول على موافقة الإدارة العليا قبل إنشاء أي علاقة عمل."
        ),
    },
    {
        "hash": "hash_002",
        "content": (
            "تلتزم المؤسسات المالية بالإبلاغ عن أي معاملات مشبوهة إلى وحدة "
            "الاستخبارات المالية (FIU) خلال 24 ساعة من اكتشاف الشبوهة."
        ),
    },
    {
        "hash": "hash_003",
        "content": (
            "يحق للموظفين الحصول على 21 يوم إجازة سنوية مدفوعة الأجر بعد إتمام "
            "سنة كاملة في الخدمة، وفقاً لسياسة الموارد البشرية للشركة."
        ),
    },  # Off-topic (HR policy, not AML)
    {
        "hash": "hash_004",
        "content": (
            "يشمل نظام مكافحة غسل الأموال برامج التدريب الإلزامي لجميع الموظفين "
            "المتعاملين مع العملاء، مع تحديث سنوي للمعرفة بالمتطلبات التنظيمية."
        ),
    },
    {
        "hash": "hash_005",
        "content": (
            "يتعين على البنوك إجراء مراجعة دورية لملفات العملاء عالي المخاطر "
            "كل ستة أشهر على الأقل، مع توثيق جميع التحديثات في سجلات KYC."
        ),
    },
    {
        "hash": "hash_006",
        "content": (
            "تنظم اللجنة الفنية اجتماعاتها مرة كل ثلاثة أشهر لمراجعة السياسات "
            "الداخلية وتحديث إجراءات العمل التشغيلي."
        ),
    },  # Vague, low relevance
    {
        "hash": "hash_007",
        "content": (
            "تُعدّ الكيانات ذات الصلة بالأشخاص المدرجين على قوائم العقوبات الدولية "
            "(OFAC, UN) من أعلى فئات المخاطر، ويُحظر التعامل معها إلا بعد الحصول "
            "على استثناء قانوني صريح."
        ),
    },
    {
        "hash": "hash_008",
        "content": (
            "تنقسم المركبات إلى فئتين: المركبات ذات المحرك والمركبات غير الآلية، "
            "وتخضع كل منها لأنظمة مرورية مختلفة."
        ),
    },  # Completely off-topic
    {
        "hash": "hash_009",
        "content": (
            "في حالة العميل الشخص السياسي البارز (PEP)، يُشترط الحصول على موافقة "
            "لجنة الامتثال وتوثيق تقييم المخاطر قبل قبول طلب فتح الحساب."
        ),
    },
    {
        "hash": "hash_010",
        "content": "",  # Empty content — edge case
    },
]


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def print_separator(title: str = "") -> None:
    line = "─" * 60
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


def assert_condition(condition: bool, message: str) -> None:
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}  —  {message}")
    if not condition:
        # Don't hard-exit; finish all tests first
        global _TEST_FAILURES
        _TEST_FAILURES += 1


_TEST_FAILURES = 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_model_loads() -> BGEReranker:
    """Test 1: Model initializes without errors."""
    print_separator("TEST 1: Model Initialization")
    reranker = BGEReranker(device="cpu")  # CPU for portability in test
    assert_condition(reranker.model is not None, "CrossEncoder model loaded.")
    assert_condition(
        reranker.model_name == "BAAI/bge-reranker-v2-m3",
        f"Correct model name: {reranker.model_name}"
    )
    return reranker


def test_basic_reranking(reranker: BGEReranker) -> None:
    """Test 2: Returns correct number of results, sorted by score."""
    print_separator("TEST 2: Basic Reranking (top_n=5)")
    results = reranker.rerank(DUMMY_QUERY, DUMMY_DOCUMENTS, top_n=5)

    assert_condition(len(results) == 5, f"Returned exactly 5 results (got {len(results)}).")

    # Verify sorted descending
    scores = [r["score"] for r in results]
    is_sorted = all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
    assert_condition(is_sorted, "Results are sorted by descending score.")

    # Verify shape: each result must have hash, content, score
    for i, r in enumerate(results):
        assert_condition(
            "hash" in r and "content" in r and "score" in r,
            f"Result #{i+1} has required keys (hash, content, score)."
        )

    print("\n  🔎 Top-5 Results:")
    for rank, result in enumerate(results, 1):
        print(f"    [{rank}] score={result['score']:.4f} | hash={result['hash']}")
        print(f"         {result['content'][:90]}{'...' if len(result['content']) > 90 else ''}")


def test_top_n_limit(reranker: BGEReranker) -> None:
    """Test 3: top_n=1 returns exactly 1 result."""
    print_separator("TEST 3: top_n Limit")
    results = reranker.rerank(DUMMY_QUERY, DUMMY_DOCUMENTS, top_n=1)
    assert_condition(len(results) == 1, f"top_n=1 returns 1 result (got {len(results)}).")
    print(f"    Best match score: {results[0]['score']:.4f}")
    print(f"    Content: {results[0]['content'][:100]}...")


def test_score_threshold(reranker: BGEReranker) -> None:
    """Test 4: score_threshold filters out low-scoring docs."""
    print_separator("TEST 4: Score Threshold")

    # First, get the max score to set a very high threshold
    all_results = reranker.rerank(DUMMY_QUERY, DUMMY_DOCUMENTS, top_n=10)
    max_score = all_results[0]["score"]

    # Set threshold above max score — should return 0 results
    results_empty = reranker.rerank(
        DUMMY_QUERY, DUMMY_DOCUMENTS, top_n=5,
        score_threshold=max_score + 10.0
    )
    assert_condition(
        len(results_empty) == 0,
        f"score_threshold above max ({max_score:.4f}) returns 0 results."
    )

    # Set threshold at a value that should let some through
    mid_score = all_results[len(all_results) // 2]["score"]
    results_filtered = reranker.rerank(
        DUMMY_QUERY, DUMMY_DOCUMENTS, top_n=10,
        score_threshold=mid_score
    )
    assert_condition(
        len(results_filtered) < len(all_results),
        f"score_threshold={mid_score:.4f} reduces results "
        f"({len(results_filtered)} < {len(all_results)})."
    )


def test_empty_content_skipped(reranker: BGEReranker) -> None:
    """Test 5: Documents with empty content are gracefully skipped."""
    print_separator("TEST 5: Empty Content Handling")
    docs_with_empty = [
        {"hash": "empty_1", "content": ""},
        {"hash": "empty_2", "content": "   "},
        {"hash": "valid_1", "content": "إجراءات العناية الواجبة المعززة للعملاء عالي المخاطر."},
    ]
    results = reranker.rerank(DUMMY_QUERY, docs_with_empty, top_n=5)
    assert_condition(len(results) == 1, "Empty content docs skipped; 1 valid result returned.")
    assert_condition(results[0]["hash"] == "valid_1", "The valid document was returned.")


def test_empty_documents(reranker: BGEReranker) -> None:
    """Test 6: Empty document list returns [] without error."""
    print_separator("TEST 6: Empty Document List")
    results = reranker.rerank(DUMMY_QUERY, [], top_n=5)
    assert_condition(results == [], "Empty document list returns [].")


def test_extra_metadata_preserved(reranker: BGEReranker) -> None:
    """Test 7: Extra keys in the retriever payload are preserved."""
    print_separator("TEST 7: Extra Metadata Preserved")
    docs_with_meta = [
        {
            "hash": "hash_meta_1",
            "content": "يجب الإبلاغ عن المعاملات المشبوهة.",
            "source": "CBE_Circular_2023",
            "article_id": "Art-12",
        },
        {
            "hash": "hash_meta_2",
            "content": "سياسة الموارد البشرية للإجازات السنوية.",
            "source": "HR_Policy_2022",
            "article_id": "Art-5",
        },
    ]
    results = reranker.rerank(DUMMY_QUERY, docs_with_meta, top_n=2)
    assert_condition(len(results) == 2, "Both documents returned.")
    for r in results:
        assert_condition("source" in r, f"'source' key preserved in result (hash={r['hash']}).")
        assert_condition("article_id" in r, f"'article_id' key preserved (hash={r['hash']}).")
    print(f"    Metadata in top result: source={results[0].get('source')}, article_id={results[0].get('article_id')}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    global _TEST_FAILURES
    _TEST_FAILURES = 0

    print_separator("BGEReranker Test Suite — BAAI/bge-reranker-v2-m3")
    print(f"  Query: {DUMMY_QUERY[:80]}...")
    print(f"  Input documents: {len(DUMMY_DOCUMENTS)}")

    try:
        reranker = test_model_loads()
    except Exception as e:
        print(f"\n❌ CRITICAL: Model failed to load. Aborting tests.\n   Error: {e}")
        sys.exit(1)

    test_basic_reranking(reranker)
    test_top_n_limit(reranker)
    test_score_threshold(reranker)
    test_empty_content_skipped(reranker)
    test_empty_documents(reranker)
    test_extra_metadata_preserved(reranker)

    print_separator()
    if _TEST_FAILURES == 0:
        print(f"  ✅ All tests passed.")
    else:
        print(f"  ❌ {_TEST_FAILURES} test(s) failed.")
    print_separator()

    sys.exit(_TEST_FAILURES)


if __name__ == "__main__":
    main()
