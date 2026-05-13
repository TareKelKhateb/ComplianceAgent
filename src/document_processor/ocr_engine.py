# src/document_processor/ocr_engine.py

from .extractors.base_extractor import BaseExtractor
from .extractors.mistral_extractor import MistralExtractor
from .chunkers.text_formatter import TextFormatter

class OCREngine:
    """
    Orchestrates the OCR process by selecting the appropriate 
    extraction strategy and applying targeted formatting.
    """

    def __init__(self, extractor: BaseExtractor) -> None:
        """
        Args:
            extractor (BaseExtractor): The OCR strategy to use (EasyOCR or Mistral).
        """
        self.extractor = extractor
        self.formatter = TextFormatter()

    def process_document(self, pdf_path: str) -> str:
        """
        Executes the extraction and applies formatting based on the extractor type.
        
        Args:
            pdf_path (str): Path to the target PDF file.
            
        Returns:
            str: The processed and formatted text.
        """
        # Step 1: Extract raw text
        raw_text = self.extractor.extract_text(pdf_path)
        
        # Step 2: Conditional Formatting

        # If Mistral is used, we trust its structure and apply light formatting
        if isinstance(self.extractor, MistralExtractor):

            print(f"[*] OCREngine: Applying light formatting for {self.extractor.__class__.__name__}")

            return self.formatter.light_format(raw_text)
        
        # For other extractors (like EasyOCR), apply full cleaning
        print(f"[*] OCREngine: Applying full clean-up for {self.extractor.__class__.__name__}")

        return self.formatter.full_clean_format(raw_text)