import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Allowed strategy values — used for validation
_ALLOWED_STRATEGIES = {"llm", "semantic", "none"}


class Config:
    """
    LLM and chunking configuration for the Corporate Chunker.

    CHUNK_REFINEMENT_STRATEGY controls which refinement backend is used:
        - 'llm'      : Use the local Ollama LLM to refine each chunk.
        - 'semantic' : Use embedding-based semantic chunking (placeholder).
        - 'none'     : Pass chunks through with no refinement.
    """

    # ── LLM settings ──────────────────────────────────────────────────────────
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/api/generate")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
    LLM_TEMPERATURE: float = 0.0

    # ── Chunking strategy ─────────────────────────────────────────────────────
    CHUNK_REFINEMENT_STRATEGY: str = os.getenv("CHUNK_REFINEMENT_STRATEGY", "llm")

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)

    @classmethod
    def validate(cls) -> None:
        """Raise ValueError if any configuration value is invalid."""
        strategy = cls.CHUNK_REFINEMENT_STRATEGY
        if strategy not in _ALLOWED_STRATEGIES:
            raise ValueError(
                f"Invalid CHUNK_REFINEMENT_STRATEGY: '{strategy}'. "
                f"Allowed values are: {sorted(_ALLOWED_STRATEGIES)}"
            )
