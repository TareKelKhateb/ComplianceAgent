import os
import numpy as np
import easyocr
from pdf2image import convert_from_path
from typing import List
from .base_extractor import BaseExtractor

class EasyOcrExtractor(BaseExtractor):
    """
    Handles OCR using the EasyOCR library locally.
    Focuses only on raw text extraction per page.
    """

    def __init__(
        self,
        languages: List[str] = None,
        gpu: bool = True,
        poppler_path: str = None,
        dpi: int = 300,
    ) -> None:
        self.languages = languages or ["ar", "en"]
        self.gpu = gpu
        self.poppler_path = poppler_path
        self.dpi = dpi
        self._reader = None

    def _get_reader(self) -> easyocr.Reader:
        """Lazy initialization of the EasyOCR Reader."""
        if self._reader is None:
            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader

    def extract_text(self, pdf_path: str) -> str:
        """
        Converts PDF to images and extracts raw text.
        Returns a formatted string with page markers.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

        reader = self._get_reader()
        
        # Convert PDF pages to PIL images
        pages = convert_from_path(
            pdf_path, 
            dpi=self.dpi, 
            poppler_path=self.poppler_path
        )
        
        document_parts = []

        for i, page_image in enumerate(pages):
            # Convert PIL image to numpy array for EasyOCR
            img_array = np.array(page_image)
            
            # Extract text (returns list of tuples: [bbox, text, confidence])
            results = reader.readtext(img_array)
            
            # Join all detected text pieces in the page
            page_content = "\n".join([res[1] for res in results])
            
            # Format the page with a standardized header
            page_markdown = f"## Page {i + 1}\n\n{page_content}"
            document_parts.append(page_markdown)
            
            # Clear memory
            page_image.close()

        # Join pages with a horizontal rule separator
        return "\n\n---\n\n".join(document_parts)