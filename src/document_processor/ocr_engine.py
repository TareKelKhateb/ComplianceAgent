import os
import easyocr
import numpy as np
from PIL import Image
import re
from typing import List, Generator, Any, Dict
from pdf2image import convert_from_path

class DocumentProcessor:
    """
    Advanced Document Processor using EasyOCR for regulatory compliance.
    Replaced PaddleOCR to resolve Windows stability issues.
    """

    def __init__(self, lang: str = 'ar') -> None:
        """
        Initializes the processor with EasyOCR Reader.
        
        Args:
            lang (str): Primary language (unused here as we load both 'ar' and 'en').
        """
        # Initialize EasyOCR with Arabic and English support
        self.reader = easyocr.Reader(['ar', 'en'], gpu=True)
        print("[!] EasyOCR: Initialized in GPU mode for faster processing.")
        

        
        self.article_pattern = re.compile(
            r'^(مادة|المادة)'
            r'\s*[\(\（]?\s*'
            r'(\d+|[٠-٩]+|[أ-ي]+)'
            r'\s*[\)\）]?\s*:?\s*$'
        )

    def process_layer_one(self, pdf_path: str, doc_id: int) -> List[Dict[str, Any]]:
        """
        Layer 1: Raw Extraction using EasyOCR.
        Processes the PDF page-by-page and returns structured chunks.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found at: {pdf_path}")

        final_chunks: List[Dict[str, Any]] = []
        current_idx: int = 0
        
        print(f"[*] Layer 1 (EasyOCR): Extracting text from Doc ID {doc_id}...")
        
        for i, page_image in enumerate(self._get_pdf_pages_generator(pdf_path)):
            # Convert PIL image to numpy array for EasyOCR
            img_array = np.array(page_image)
            
            # Perform OCR
            results = self.reader.readtext(img_array)
            
            # Format elements
            page_chunks = self._format_page_elements(
                results, 
                doc_id, 
                i + 1, 
                current_idx
            )
            
            current_idx += len(page_chunks)
            final_chunks.extend(page_chunks)
            page_image.close() 

        print(f"[+] Layer 1 Complete: {len(final_chunks)} raw chunks generated.")
        return final_chunks

    def _get_pdf_pages_generator(self, pdf_path: str) -> Generator[Image.Image, None, None]:
        """Yields PDF pages as PIL Images."""
        return convert_from_path(pdf_path, dpi=300, thread_count=2, poppler_path=r"C:\Program Files\Release-26.02.0-0\poppler-26.02.0\Library\bin")

    def _format_page_elements(self, results: List[Any], doc_id: int, 
                                page_num: int, start_idx: int) -> List[Dict[str, Any]]:
        """
        Formats EasyOCR results into structured chunks.
        Each result is (bbox, text, confidence).
        """
        page_chunks: List[Dict[str, Any]] = []
        
        for idx, (bbox, text, prob) in enumerate(results):
            content = text.strip()
            if not content:
                continue

            # Apply Markdown heading to articles for better LLM retrieval
            if self.article_pattern.match(content):
                content = f"### {content}" 

            page_chunks.append({
                "doc_id": doc_id,
                "chunk_index": start_idx + idx, 
                "page_number": page_num,
                "content": content,
                "type": "text", # EasyOCR provides raw text detection
                "bbox": str(bbox)
            })
            
        return page_chunks