import json
import logging
from pathlib import Path

# Import the new Centralized Config and the Manager
from src.corporate_processor.config import CorporateConfig
from src.corporate_processor.pipeline_manager import PipelineManager

# Setup basic logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # 1. Initialize Centralized Configuration (Fail-fast validation happens here)
    # This automatically loads .env and the YAML config
    try:
        config = CorporateConfig.load()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return

    # 2. Define inputs and outputs
    file_path = "data/corporate/raw/2016.pdf"
    output_dir = Path("data/corporate/processed")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Inject the config into the PipelineManager
    print(f"--- Starting pipeline for: {file_path} ---")
    manager = PipelineManager(config=config)
    
    # 4. Process the document
    result = manager.process(file_path)
    
    # 5. Handle the output
    if result.success:
        print("Pipeline success!")
        output_path = output_dir / f"{Path(file_path).stem}.json"
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.data, f, indent=4, ensure_ascii=False)
            
        print(f"JSON saved to: {output_path}")
    else:
        print(f"Pipeline failed: {result.message}")

if __name__ == "__main__":
    main()