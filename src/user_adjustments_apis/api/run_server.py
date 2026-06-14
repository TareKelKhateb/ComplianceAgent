"""
run_server.py
-------------
Uvicorn entry point for the User Adjustments API.

Usage:
    python -m src.user_adjustments_apis.api.run_server
    # or
    python src/user_adjustments_apis/api/run_server.py
"""

import os
import sys
import logging

# Ensure project root is on sys.path
_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import uvicorn


def main() -> None:
    """Start the User Adjustments API server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    uvicorn.run(
        "src.user_adjustments_apis.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[os.path.join(_ROOT, "src")],
    )


if __name__ == "__main__":
    main()
