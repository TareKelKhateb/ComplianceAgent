"""
config.py
---------
Centralised configuration management for the corporate processor.

Combines sensitive keys from the environment with non-sensitive settings
from the project-level YAML configuration file.

Ensures fail-fast behaviour during application startup via validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class CorporateConfig:
    """
    Strict configuration model for the corporate pipeline.
    """
    llama_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    mistral_api_base_url: str = "https://api.mistral.ai/v1"
    mistral_model: str = "mistral-large-latest"
    llama_api_base_url: str = "https://api.llama-api.com"
    llama_model: str = "llama3.3-70b"
    ocr_threshold: int = 80

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """
        Check for missing API keys at the moment of instantiation.
        """
        missing = []
        if not self.mistral_api_key:
            missing.append("MISTRAL_API_KEY")

        if missing:
            raise ValueError(
                f"Application Startup Failed: Missing required environment "
                f"variables: {', '.join(missing)}. Please set these in your .env file."
            )

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "CorporateConfig":
        """
        Load non-sensitive variables from YAML config and sensitive keys from the environment.
        """
        load_dotenv()

        # 1. Load static configurations from YAML
        if not config_path:
            root_dir = Path(__file__).resolve().parent.parent.parent
            config_path_obj = root_dir / "config" / "document_processor_config.yaml"
        else:
            config_path_obj = Path(config_path)

        yaml_config = {}
        if config_path_obj.is_file():
            with open(config_path_obj, "r", encoding="utf-8") as f:
                full_config = yaml.safe_load(f) or {}
            yaml_config = full_config.get("corporate_processor", {})

        # 2. Load sensitive configurations from environment
        llama_key = os.getenv("LLAMA_API_KEY")
        mistral_key = os.getenv("MISTRAL_API_KEY")

        return cls(
            llama_api_key=llama_key,
            mistral_api_key=mistral_key,
            mistral_api_base_url=yaml_config.get("mistral_api_base_url", "https://api.mistral.ai/v1"),
            mistral_model=yaml_config.get("mistral_model", "mistral-large-latest"),
            llama_api_base_url=yaml_config.get("llama_api_base_url", "https://api.llama-api.com"),
            llama_model=yaml_config.get("llama_model", "llama3.3-70b"),
            ocr_threshold=int(yaml_config.get("ocr_threshold", 80))
        )
