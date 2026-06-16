

### Configuration
1.  **Environment Variables**: Copy `.env.example` to `.env` and fill in your API keys:
    ```bash
    cp .env.example .env
    ```
    Required keys:
    - `FIRECRAWL_API_KEY`
    - `GOOGLE_API_KEY`
    - `MISTRAL_API_KEY`

2.  **Pipeline Settings**: Fine-tune the processing logic in `config/document_processor_config.yaml`.

### Running the Test
```bash
uv run python src/document_processor/ocr_test.py
```

### What it does:
1.  **Database Audit**: Checks for the existence of `data/legal_vault.db`.
2.  **Reset (Optional)**: Prompts to wipe the `ocr_chunks` table for a clean test run.
3.  **Queue Processing**: Automatically fetches documents marked as `pending` from the database.
4.  **Extraction**: Converts PDFs to Markdown using the configured strategy (e.g., Mistral OCR).
5.  **Semantic Chunking**: Identifies legal articles (e.g., "مادة") and splits the text into logical, semantically consistent chunks.
6.  **Persistence**: Synchronizes processed chunks back to the SQLite database and optionally saves the full Markdown output.

## 📁 Project Structure
- `src/document_processor/`: Core OCR and chunking logic.
  - `ocr_engine.py`: Multi-strategy extractor implementation.
  - `chunkers/`: Semantic and overlapping chunking logic.
  - `pipeline_manager.py`: The unified orchestrator.
- `data/`: SQLite databases and raw documents.
- `config/`: YAML configuration files.
- `output_markdown/`: (Generated) Extracted full-text Markdown files.
- `tests/`: Pytest suite for regex and pipeline validation.
