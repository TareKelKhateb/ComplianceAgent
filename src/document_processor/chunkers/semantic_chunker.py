import re
from typing import List, Dict, Any

from .base_chunker import BaseChunker


class SemanticChunker(BaseChunker):
    """
    Article-aware semantic chunker for legal/regulatory Markdown documents.

    Splits the full Markdown text exactly at article headers, so every
    chunk maps 1-to-1 with one legal article.  This is the ideal input
    for the Diff Engine because it can detect precise article-level
    additions, modifications, and deletions.

    Recognised header patterns (configurable via ``header_pattern``):
        - Arabic:  ``### المادة 5``  or  ``### مادة الأولى``
        - English: ``### Article 5``

    Any text that appears before the first article header is kept as a
    preamble chunk (chunk_index=0, type='preamble').
    """

    # Default regex: matches a Markdown header that starts an article
    _DEFAULT_PATTERN = re.compile(
        r"(?m)^((?:#{1,6}\s*|\*\*)?[\(\（]?\s*(?!Page\s+\d)(?:ب?(?:المادة|مادة)|Article)\s*[\(\（]?\s*(?:\d+|[٠-٩]+|[أ-ي]+)?\s*[\)\）]?\s*(?:\((?:المادة|مادة)\s+[أ-ي]+\))?\s*:?(?:\*\*)?\s*.*)",
        re.IGNORECASE,
    )

    def __init__(self, header_pattern: re.Pattern | None = None) -> None:
        """
        Args:
            header_pattern (re.Pattern | None): Override the default article-header
                regex.  Must use at least one capture group so that split() keeps
                the delimiter.
        """
        self._pattern = header_pattern or self._DEFAULT_PATTERN

    # ------------------------------------------------------------------
    # BaseChunker contract
    # ------------------------------------------------------------------

    def create_chunks(self, full_text: str, doc_id: int) -> List[Dict[str, Any]]:
        """
        Split *full_text* on article headers.

        Args:
            full_text (str): The complete Markdown string from the extractor.
            doc_id (int):    Parent document identifier.

        Returns:
            List[Dict[str, Any]]: Chunk dicts with keys
                ``doc_id``, ``chunk_index``, ``content``, ``metadata``.
                The ``metadata`` dict always includes ``type``
                (``'preamble'`` or ``'article'``) and ``header``
                (the raw header line for articles).
        """
        print(f"[*] SemanticChunker: Splitting on article headers…")

        full_text = re.sub(r'(?m)^---\s*\n+##\s+Page\s+\d+\s*\n+\d*\s*\n*', '', full_text)

        # re.split with a capturing group keeps the delimiters in the list
        parts = self._pattern.split(full_text)
        # parts alternates: [text_before_first_header, header, body, header, body, …]

        chunks: List[Dict[str, Any]] = []
        idx = 0

        # --- Preamble (everything before the first header) -------------
        preamble = parts[0].strip()
        if preamble:
            chunks.append(
                {
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    "content": preamble,
                    "metadata": {"type": "preamble", "header": None},
                }
            )
            idx += 1

        # --- Article chunks (header + body pairs) ----------------------
        # parts[1:] is a flat list: [header, body, header, body, …]
        it = iter(parts[1:])
        for header in it:
            body = next(it, "").strip()
            content = f"{header.strip()}\n\n{body}" if body else header.strip()

            chunks.append(
                {
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    "content": content,
                    "metadata": {"type": "article", "header": header.strip()},
                }
            )
            idx += 1

        print(f"[+] SemanticChunker: {len(chunks)} chunks created "
              f"({sum(1 for c in chunks if c['metadata']['type'] == 'article')} articles, "
              f"{sum(1 for c in chunks if c['metadata']['type'] == 'preamble')} preamble).")
        return chunks
