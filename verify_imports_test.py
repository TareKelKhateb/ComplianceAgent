import sys
import os
from pathlib import Path

# Add the project root to sys.path
# Use current working directory to be safe
project_root = Path(os.getcwd())
src_path = project_root / "src"
sys.path.append(str(src_path))

# Files to test (relative to src)
files_to_import = [
    "document_processor.extractors.base_extractor",
    "document_processor.extractors.easyocr_extractor",
    "document_processor.extractors.mistral_extractor",
    "document_processor.chunkers.base_chunker",
    "document_processor.chunkers.overlapping_chunker",
    "document_processor.chunkers.semantic_chunker",
    "document_processor.chunkers.text_formatter",
    "document_processor.semantic_hasher",
    "document_processor.diff_engine",
    "document_processor.pipeline_manager_2"
]

success_count = 0
fail_count = 0

print(f"Project Root: {project_root}")
print(f"Source Path: {src_path}")
print("-" * 30)

for module_name in files_to_import:
    try:
        # Use importlib for more control if needed, but __import__ is fine
        __import__(module_name)
        print(f"[OK]  Imported {module_name}")
        success_count += 1
    except Exception as e:
        print(f"[FAIL] Could not import {module_name}")
        print(f"       Error: {e}")
        fail_count += 1

print("-" * 30)
print(f"Total: {success_count + fail_count} | Success: {success_count} | Failed: {fail_count}")

if fail_count > 0:
    sys.exit(1)
else:
    sys.exit(0)
