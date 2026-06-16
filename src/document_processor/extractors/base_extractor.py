from abc import ABC, abstractmethod


class BaseExtractor(ABC):
    """
    Abstract base class (interface) for all document extractors.

    Every extractor — regardless of underlying engine (EasyOCR, Mistral, etc.) —
    must implement `extract_text`. The pipeline orchestrator depends only on this
    interface, never on concrete implementations.
    """

    @abstractmethod
    def extract_text(self, pdf_path: str) -> str:
        """
        Extract the full content of a PDF and return it as a single Markdown string.

        The returned string is the "ground truth" representation of the document.
        It is saved as-is before any chunking takes place.

        Args:
            pdf_path (str): Absolute or relative path to the input PDF file.

        Returns:
            str: A Markdown-formatted string containing the entire document text.

        Raises:
            FileNotFoundError: If the PDF does not exist at the given path.
            RuntimeError: For any engine-specific failure during extraction.
        """
        ...
