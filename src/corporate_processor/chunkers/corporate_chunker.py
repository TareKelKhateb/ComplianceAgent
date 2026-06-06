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
        Splits text by markdown headers (##, ###, ####) using re.split,
        but applies semantic merging to prevent over-chunking and data fragmentation.
        """
        if not isinstance(text, str):
            logger.error("Validation Error: Provided text is not a string.")
            return []
            
        # 1. Initial split based on Markdown headers
        raw_chunks = re.split(r'\n(?=#{2,4}\s)', text)
        raw_chunks = [chunk.strip() for chunk in raw_chunks if chunk.strip()]
        
        merged_chunks = []
        
        for chunk in raw_chunks:
            # Remove Markdown formatting for pure content analysis
            plain_text = re.sub(r'#+\s*', '', chunk).strip()
            
            # 2. Discard Metadata-only Chunks (e.g., '## صفحة 3' or isolated numbers/very short strings)
            # If it's just "صفحة X" or extremely short (< 10 chars), discard it completely
            if re.match(r'^(صفحة|page)\s*\d+$', plain_text, re.IGNORECASE) or len(plain_text) < 10:
                logger.debug(f"Discarding metadata-only chunk: {chunk}")
                continue
                
            # 3. Minimum Content Threshold
            # If chunk is less than 100 characters, it lacks full semantic context.
            # We merge it with the PREVIOUS chunk if one exists.
            if len(chunk) < 100 and merged_chunks:
                logger.debug(f"Merging short chunk (<100 chars) with previous: {chunk}")
                merged_chunks[-1] += "\n\n" + chunk
            else:
                merged_chunks.append(chunk)
                
        # 4. Context Preservation (Forward Merging for isolated headings)
        # If a chunk ends up being just a heading (e.g. it was >100 chars but is just a list of names/headers), 
        # or it's an isolated heading that didn't get merged backwards, we merge it FORWARD.
        final_chunks = []
        i = 0
        while i < len(merged_chunks):
            current = merged_chunks[i]
            
            # If this chunk looks like an isolated heading (starts with # and is relatively short)
            # merge it with the NEXT chunk so the heading has body text.
            if current.startswith('#') and len(current) < 150 and i < len(merged_chunks) - 1:
                logger.debug(f"Forward merging isolated heading: {current}")
                final_chunks.append(current + "\n\n" + merged_chunks[i+1])
                i += 2
            else:
                final_chunks.append(current)
                i += 1
                
        return final_chunks

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
            
            response = requests.post(self.config.LLM_BASE_URL, json=payload, timeout=120)
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
