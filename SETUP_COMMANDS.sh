# RAG Pipeline Upgrade — Setup & Run Commands
# Copy and paste each block into your terminal from the project root.
# All commands use `uv` and `ollama`.

# ===========================================================================
# STEP 1 — Python Dependencies (uv)
# ===========================================================================

# Install all required packages into the project venv
uv add sentence-transformers pydantic jinja2 python-dotenv requests

# Verify sentence-transformers is importable
uv run python -c "from sentence_transformers import CrossEncoder; print('sentence-transformers OK')"

# Verify pydantic v2 is available
uv run python -c "import pydantic; print('pydantic', pydantic.__version__)"


# ===========================================================================
# STEP 2 — Ollama Models (run these in any terminal, not inside uv)
# ===========================================================================

# Pull Llama 3 8B (Router layer) — ~4.7 GB download
ollama pull llama3:8b

# Pull Qwen 2.5 7B (Inference layer) — ~4.4 GB download
ollama pull qwen2.5:7b

# Verify both models are available
ollama list

# Start Ollama server (keep this terminal open or run as background service)
ollama serve


# ===========================================================================
# STEP 3 — Environment Variables (.env file)
# ===========================================================================
# Create or update your .env file in the project root with these values:

# LLM_BASE_URL=http://localhost:11434/api/generate
# LLM_MODEL_NAME=qwen2.5:7b
# ROUTER_MODEL_NAME=llama3:8b
# HF_HUB_DISABLE_SYMLINKS_WARNING=1      # suppress the Windows symlink warning


# ===========================================================================
# STEP 4 — Pre-download the BGE Reranker Model
# ===========================================================================
# This downloads BAAI/bge-reranker-v2-m3 (~1.1 GB) to your HuggingFace cache.
# Run once; subsequent runs use the local cache.

uv run python -c "
from sentence_transformers import CrossEncoder
print('Downloading BAAI/bge-reranker-v2-m3 ...')
model = CrossEncoder(model_name_or_path='BAAI/bge-reranker-v2-m3', device='cpu')
print('Download complete. Model cached at ~/.cache/huggingface/hub/')
"


# ===========================================================================
# STEP 5 — Run Individual Tests
# ===========================================================================

# Test the Reranker only (no Ollama or Qdrant needed)
uv run python -m src.inference.reranker_test

# Test the full pipeline (requires Ollama running + Qdrant DB populated)
uv run python -m src.inference.pipeline_integration_test


# ===========================================================================
# STEP 6 — Run the Engine Directly
# ===========================================================================

uv run python -m src.inference.engine


# ===========================================================================
# VRAM NOTES (local machine)
# ===========================================================================
# If you have limited VRAM (< 12 GB), disable the router to reduce load:
#
#   engine = ComplianceEngine(enable_router=False, enable_reranker=True)
#
# If VRAM is very tight (< 8 GB), also disable reranker:
#
#   engine = ComplianceEngine(enable_router=False, enable_reranker=False)
#
# The BGE Reranker can be forced to CPU by setting reranker_device="cpu"
# in ComplianceEngine() — this keeps GPU free for both LLMs.
#
#   engine = ComplianceEngine(enable_router=True, enable_reranker=True, reranker_device="cpu")
