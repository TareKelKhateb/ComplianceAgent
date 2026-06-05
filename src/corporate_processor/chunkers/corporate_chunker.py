import re
import logging
import tempfile
import os
from typing import List
import requests

# Import the configuration
from src.corporate_processor.chunkers.config import Config

# Configure logging instead of print
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CorporateChunker:
    """
    A professional corporate chunker tool to split and refine text.
    """
    def __init__(self):
        self.config = Config()

    def split_text_by_headers(self, text: str) -> List[str]:
        """
        Splits text by markdown headers (##, ###, ####) using re.split.
        """
        if not isinstance(text, str):
            logger.error("Validation Error: Provided text is not a string.")
            return []
            
        # Use re.split to split before headers, keeping the headers intact
        # using a positive lookahead for newlines followed by ##, ###, or ####
        chunks = re.split(r'\n(?=#{2,4}\s)', text)
        
        # Clean up empty chunks
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def refine_chunk(self, content: str) -> str:
        """
        Refines the content chunk using the LLM, maintaining strict constraints.
        """
        if not isinstance(content, str):
            logger.error("Validation Error: Content provided for refinement is not a string.")
            return content

        logger.info(f"Sending chunk to Ollama for refinement (length: {len(content)} chars)")
        
        try:
            prompt = (
                "You are a professional corporate compliance assistant. "
                "If the text is already perfectly formatted and clear, return it as is without changes. "
                "Otherwise, refine it for clarity and tone while maintaining Markdown structure, and ALWAYS respond in Arabic.\n"
                "Output ONLY the refined text.\n"
                f"Text to refine: {content}"
            )
            
            payload = {
                "model": self.config.LLM_MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.config.LLM_TEMPERATURE
                }
            }
            
            response = requests.post(self.config.LLM_BASE_URL, json=payload, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            refined_content = response_data.get("response")
            
            if not refined_content:
                logger.warning("Ollama returned an empty response. Returning original content.")
                return content
                
            return refined_content.strip()
            
        except requests.exceptions.RequestException as e:
            # Robust try-except to prevent data loss in case of API error/unreachable host
            logger.warning(f"Ollama instance unreachable or API Error: {e}. Returning original content.")
            return content
        except Exception as e:
            logger.error(f"Unexpected error during refinement: {e}. Returning original content.")
            return content

if __name__ == "__main__":
    # Demo block demonstrating file reading, splitting, processing, and logging
    
    demo_text = """## Financial Performance 2023
The company achieved a total revenue of $14.5M, representing an 8% year-over-year growth.
Net margins remained stable at 12.4%.

### Legal Disclaimer
Under Section 4.A (Liability), the corporation assumes no responsibility for third-party damages.
Please refer to the compliance mandate 2023-A."""

    logger.info("Starting Corporate Chunker Demo...")
    
    # Create a temporary file to simulate reading from a file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
        tmp.write(demo_text)
        tmp_path = tmp.name

    try:
        logger.info(f"Reading content from file: {tmp_path}")
        with open(tmp_path, "r", encoding="utf-8") as f:
            file_content = f.read()
            
        chunker = CorporateChunker()
        
        logger.info("Splitting text by headers...")
        chunks = chunker.split_text_by_headers(file_content)
        logger.info(f"Generated {len(chunks)} chunks.")
        
        for i, chunk in enumerate(chunks, start=1):
            logger.info(f"--- Processing Chunk {i} ---")
            refined_result = chunker.refine_chunk(chunk)
            
            logger.info(f"Refined Output for Chunk {i}:\n{refined_result}\n")
            
    finally:
        # Cleanup temporary file
        os.remove(tmp_path)
        logger.info("Demo complete. Temporary files cleaned up.")
