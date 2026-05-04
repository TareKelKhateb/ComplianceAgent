# ---------------------------------------------------------------------------
# src/Scrapper/ScrapperClient.py
#
# A lightweight HTTP client that wraps the Scraper Extractor microservice.
# The service must be running (via Docker) before calling any method.
# See Readme.md → "Running the Scraper Extractor Service" for setup steps.
#
# Configuration is loaded from src/Scrapper/config.yaml — edit that file
# to change the service URL, endpoint, or timeout without touching Python code.
#
# Usage:
#   from src.Scrapper.ScrapperClient import ScrapperClient
#
#   client = ScrapperClient()
#
#   # Single-page extraction
#   data = client.extract("https://www.example.com")
#
#   # Site crawl (up to N pages)
#   data = client.extract("https://www.example.com", is_crawl=True, limit=10)
# ---------------------------------------------------------------------------

import logging
import pathlib
import yaml
import requests
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "Scrapper_config.yaml"


def _load_config() -> dict:
    """Load and parse config.yaml located next to this module."""
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Scrapper config file not found at '{_CONFIG_PATH}'. "
            "Make sure config.yaml exists in config/config.yaml at the project root."
        )
    with _CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ScrapperClientError(Exception):
    """Raised when the Scrapper microservice returns an error response."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ScrapperClient:
    """
    HTTP client for the Scraper Extractor microservice.

    Configuration is read from ``src/Scrapper/config.yaml``.
    You can override the base URL at instantiation time if needed
    (e.g. pointing at a remote host).

    Parameters
    ----------
    base_url : str, optional
        Override the ``scrapper.base_url`` value from config.yaml.

    Example
    -------
    >>> client = ScrapperClient()
    >>> result = client.extract("https://www.cbe.org.eg")
    >>> print(result["status"])  # "success"
    >>> print(result["data"])    # list of extracted records
    """

    def __init__(self, base_url: str | None = None) -> None:
        cfg = _load_config()["scrapper"]

        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self._extract_url = f"{self.base_url}{cfg['extract_endpoint']}"
        self._timeout = cfg["timeout_seconds"]

        logger.debug(
            "ScrapperClient initialised — endpoint: %s  timeout: %ds",
            self._extract_url,
            self._timeout,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        url: str,
        is_crawl: bool = False,
        limit: int = 1,
    ) -> dict[str, Any]:
        """
        Send an extraction request to the Scraper Extractor microservice.

        Parameters
        ----------
        url : str
            The web page (or site root) to scrape / crawl.
        is_crawl : bool
            ``False`` (default) — scrape a single page.
            ``True``           — crawl the site up to *limit* pages.
        limit : int
            Maximum number of pages to crawl when ``is_crawl=True``.
            Ignored for single-page scrapes.

        Returns
        -------
        dict
            The JSON response from the service::

                {
                    "status": "success",
                    "data": [ { ...extracted fields... } ]
                }

        Raises
        ------
        ScrapperClientError
            If the service returns a non-2xx status code or the
            container is unreachable.
        """
        payload = {"url": url, "is_crawl": is_crawl, "limit": limit}

        logger.info(
            "ScrapperClient.extract — url=%s  is_crawl=%s  limit=%d",
            url,
            is_crawl,
            limit,
        )

        try:
            response = requests.post(
                self._extract_url,
                json=payload,
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise ScrapperClientError(
                f"Cannot reach the Scrapper service at '{self._extract_url}'. "
                "Make sure the Docker container is running (`docker compose up -d`)."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise ScrapperClientError(
                f"Request timed out after {self._timeout}s. "
                "Consider increasing timeout_seconds in src/Scrapper/config.yaml "
                "or reducing the crawl limit."
            ) from exc

        if not response.ok:
            raise ScrapperClientError(
                f"Scrapper service returned HTTP {response.status_code}: {response.text}"
            )

        result: dict[str, Any] = response.json()
        logger.info(
            "ScrapperClient.extract — received %d record(s)",
            len(result.get("data", [])),
        )
        return result

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def extract_data(
        self,
        url: str,
        is_crawl: bool = False,
        limit: int = 1,
    ) -> list[Any] | None:
        """
        Like :meth:`extract` but returns only the ``data`` list directly,
        or ``None`` when extraction yielded no results.

        Example
        -------
        >>> records = client.extract_data("https://www.example.com")
        >>> for record in records:
        ...     print(record)
        """
        result = self.extract(url=url, is_crawl=is_crawl, limit=limit)
        return result.get("data") or None
