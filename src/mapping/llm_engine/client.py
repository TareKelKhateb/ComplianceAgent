"""
client.py
---------
LLM integration client for the Compliance Mapping pipeline.
Uses a local Ollama instance to analyze policy relationships via qwen2.5:7b.
"""

import json
import logging
import requests
from pathlib import Path
from typing import Tuple

from src.mapping.data_manager.schema import RelationshipType

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"
PROMPT_FILE_PATH = Path(__file__).parent / "prompts.txt"


def _load_prompt_template() -> str:
    """Loads the system prompt template from the local prompts.txt file."""
    try:
        with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found at {PROMPT_FILE_PATH}")
        # Fallback empty string so formatting won't crash, but analysis will likely fail
        return "{context}"


def _parse_llm_json(response_text: str) -> dict:
    """
    Attempts to parse the raw text response from the LLM into a JSON object.
    Implements a fallback mechanism to extract the JSON block if the LLM
    surrounds it with markdown or conversational text.
    """
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning("Direct JSON parsing failed. Attempting fallback extraction...")
        try:
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx + 1]
                return json.loads(json_str)
            else:
                raise ValueError("No JSON object found in response.")
        except Exception as e:
            logger.error(f"Fallback JSON extraction failed: {e}")
            raise


def analyze_with_llm(context: str) -> Tuple[RelationshipType, str, float]:
    """
    Sends the context to the local Ollama LLM to classify the compliance relationship.
    
    Args:
        context: A formatted string containing the Corporate and Law chunks.
        
    Returns:
        A tuple containing (RelationshipType, reasoning, confidence_score).
    """
    prompt_template = _load_prompt_template()
    final_prompt = prompt_template.replace("{context}", context)
    
    payload = {
        "model": MODEL_NAME,
        "prompt": final_prompt,
        "stream": False
    }
    
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        
        # Ollama returns a JSON response where the generated text is in the 'response' key
        response_data = response.json()
        raw_text = response_data.get("response", "")
        
        if not raw_text:
            raise ValueError("Ollama returned an empty response string.")
            
        # Parse the JSON from the generated text
        parsed_data = _parse_llm_json(raw_text)
        
        # Extract fields
        raw_type = parsed_data.get("relationship_type", "GAP")
        reasoning = parsed_data.get("reasoning", "No reasoning provided.")
        confidence_score = float(parsed_data.get("confidence_score", 0.0))
        
        # Cast to Enum safely
        try:
            relationship_type = RelationshipType(raw_type)
        except ValueError:
            logger.warning(f"Invalid relationship_type '{raw_type}' returned by LLM. Defaulting to GAP.")
            relationship_type = RelationshipType.GAP
            
        return relationship_type, reasoning, confidence_score
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API request to Ollama failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during LLM analysis: {e}")
        
    # Default safe fallback values
    return RelationshipType.GAP, "Analysis failed due to internal error.", 0.0
