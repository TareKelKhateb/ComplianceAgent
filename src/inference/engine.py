"""
engine.py
---------
The central Orchestrator (The Engine) for the Compliance Agent.
Initializes the retriever, mapper, and prompt template to process user queries.
"""

import logging
import os
from typing import Any, Dict, List, Optional
from jinja2 import Environment, FileSystemLoader, Template

import requests
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Assuming these modules exist based on the user's instructions
try:
    # pyrefly: ignore [missing-import]
    from src.inference.retriever import Retriever
except ImportError:
    class Retriever:
        def get_law_chunks(self, query: str) -> List[Dict[str, Any]]: 
            pass

try:
    # pyrefly: ignore [missing-import]
    from src.inference.mapper import Mapper
except ImportError:
    class Mapper:
        def get_mapping_data(self, hash_val: str) -> Optional[Dict[str, Any]]: 
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ComplianceEngine:
    """
    Orchestrates the retrieval of laws, mapping to corporate policies, 
    and generating compliance responses via an LLM.
    """

    def __init__(self, template_dir: str = "src/inference", template_name: str = "compliance_prompt.jinja2"):
        """
        Initializes the ComplianceEngine with retriever, mapper, and Jinja2 template.
        """
        logger.info("Initializing ComplianceEngine...")
        
        # Load environment variables
        load_dotenv()
        
        # Fetch LLM configuration
        self.llm_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/generate")
        self.llm_model = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
        logger.info(f"LLM Config - URL: {self.llm_url}, Model: {self.llm_model}")
        
        # Initialize dependencies
        try:
            self.retriever = Retriever()
            self.mapper = Mapper()
        except Exception as e:
            logger.error("Failed to initialize Retriever or Mapper: %s", e)
            raise

        # Load Jinja2 Template
        try:
            # We resolve the absolute path to make it robust against varying CWDs
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            full_template_dir = os.path.join(base_dir, "src", "inference")
            template_path = os.path.join(full_template_dir, template_name)
            
            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Template not found at {template_path}")
                
            env = FileSystemLoader(searchpath=full_template_dir)
            jinja_env = Environment(loader=env)
            self.template = jinja_env.get_template(template_name)
            logger.info("Jinja2 template '%s' loaded successfully.", template_name)
        except Exception as e:
            logger.error("Failed to load Jinja2 template: %s", e)
            raise

    def run(self, user_query: str) -> str:
        """
        Main execution flow to process a user query and generate a response.
        
        Steps:
        1. Retrieve law chunks based on the user query.
        2. Iterate through matches to get mapping data (corporate policy + reasoning).
        3. Render the Jinja2 template with the aggregated data.
        4. Call the LLM with the rendered prompt.
        """
        logger.info("Processing user query: '%s'", user_query)
        
        if not user_query or not user_query.strip():
            return "Please provide a valid query."

        # Step 1: Retrieve law matches and hashes
        try:
            # Assuming get_law_chunks returns a list of dicts: [{"hash": "...", "content": "..."}]
            law_matches: List[Dict[str, Any]] = self.retriever.get_law_chunks(user_query)
            logger.info("Retrieved %d law chunk matches.", len(law_matches))
        except Exception as e:
            logger.error("Error retrieving law chunks: %s", e)
            return "An error occurred while retrieving relevant laws."

        if not law_matches:
            return "No relevant laws found for your query. The company policy applies natively."

        combined_law_texts = []
        combined_corp_texts = []
        combined_reasonings = []

        # Step 2: Iterate through matches and get mapping data
        for match in law_matches:
            law_hash = match.get("hash")
            law_text = match.get("content", "")
            
            if not law_hash:
                continue
                
            try:
                # Assuming get_mapping_data returns {"corp_text": "...", "reasoning": "..."} or None
                mapping_data: Optional[Dict[str, Any]] = self.mapper.get_mapping_data(law_hash)
            except Exception as e:
                logger.warning("Error fetching mapping for hash %s: %s", law_hash, e)
                continue

            if mapping_data:
                combined_law_texts.append(law_text)
                combined_corp_texts.append(mapping_data.get("corp_text", "No corporate policy provided."))
                combined_reasonings.append(mapping_data.get("reasoning", "No prior gap analysis available."))
            else:
                # Handle cases where no mapping is found in the database
                combined_law_texts.append(law_text)
                combined_corp_texts.append("No mapped corporate policy found for this law.")
                combined_reasonings.append("No mapping exists. A manual compliance review is required for this specific law.")

        # Step 3: Render the prompt with the retrieved data
        try:
            rendered_prompt = self.template.render(
                law_text="\n\n---\n\n".join(combined_law_texts),
                corp_text="\n\n---\n\n".join(combined_corp_texts),
                reasoning="\n\n---\n\n".join(combined_reasonings)
            )
            logger.debug("Prompt rendered successfully. Length: %d characters", len(rendered_prompt))
        except Exception as e:
            logger.error("Error rendering Jinja2 template: %s", e)
            return "An error occurred while formatting the LLM prompt."

        # Step 4: Placeholder for LLM API call
        return self._call_llm_api(rendered_prompt)

    def _call_llm_api(self, prompt: str) -> str:
        """
        Calls the local LLM API using the configured URL and model parameters.
        Includes error handling for robust execution.
        """
        logger.info(f"Sending prompt to LLM API at {self.llm_url} using model {self.llm_model}...")
        
        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2
            }
        }
        
        try:
            response = requests.post(self.llm_url, json=payload, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            # Ollama /api/generate returns the response in the 'response' key
            llm_response = data.get("response", "")
            
            if not llm_response:
                logger.warning("LLM API returned an empty response.")
                return "Sorry, I couldn't generate a response at this moment. Please try again later."
            
            logger.info("LLM response generated successfully.")
            return llm_response
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to LLM API: {e}")
            return "Sorry, could not connect to the AI engine. Please ensure the server (e.g., Ollama) is running."
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error calling LLM API: {e}")
            return "Sorry, the AI engine took too long to respond. Please try again later."
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error calling LLM API: {e}")
            return "Sorry, an error occurred while communicating with the AI engine."
        except Exception as e:
            logger.error(f"Unexpected error in LLM API call: {e}")
            return "Sorry, an unexpected error occurred while processing the request."

if __name__ == "__main__":
    # Simple test execution if run directly
    engine = ComplianceEngine()
    response = engine.run("What is the company policy regarding working hours and overtime?")
    print("\n--- Final LLM Response ---\n")
    print(response)
