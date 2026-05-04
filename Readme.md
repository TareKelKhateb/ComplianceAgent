# ComplianceAgent

A compliance-focused AI agent that leverages a containerized **Scraper Extractor Microservice** to retrieve and process web content.

---

## 🐳 Running the Scraper Extractor Service (Docker)

The scraper is packaged as a Docker image and exposed as a REST API on port **8000**.  
The `docker-compose.yml` at the root of this project pulls the published image — **no local build required**.

### Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Docker Desktop (or Docker Engine) | 24+ |
| Docker Compose (bundled with Desktop) | v2+ |

---

### 1 · Set up Environment Variables

Create a `.env` file in the root of this project (next to `docker-compose.yml`).  
Use the table below as a reference:

| Variable | Required | Description |
|----------|----------|-------------|
| `FIRECRAWL_API_KEY` | ✅ | API key for the Firecrawl scraping service |
| `GEMINI_API_KEY` | ✅ | API key for the Google Gemini LLM |

```dotenv
# .env
FIRECRAWL_API_KEY=your_firecrawl_key
GEMINI_API_KEY=your_gemini_key
```

---

### 2 · Start the Service

```bash
docker compose up -d
```

This will:
- Pull `tarekelkhateb/scraper-extractor-api:latest` from Docker Hub (first run only)
- Start the container as `scraper_api`
- Expose the API on **http://localhost:8000**

---

### 3 · Verify It's Running

```bash
# Check container status
docker compose ps

# View live logs
docker compose logs -f scraper-api

# Quick health check via curl
curl http://localhost:8000/docs
```

The interactive Swagger UI is available at **http://localhost:8000/docs**.

---

### 4 · Make a Scrape / Extract Request

**Single page scrape:**
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example.com", "is_crawl": false, "limit": 1}'
```

**Site crawl (up to 10 pages):**
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.example.com", "is_crawl": true, "limit": 10}'
```

**Response shape:**
```json
{
  "status": "success",
  "data": [ { "...": "extracted fields" } ]
}
```

---

### 5 · Stop the Service

```bash
docker compose down
```

---

## 🐍 Using the ScrapperClient (Python)

Instead of calling the API manually, use the built-in `ScrapperClient` located at `src/Scrapper/ScrapperClient.py`.

```python
from src.Scrapper.ScrapperClient import ScrapperClient

client = ScrapperClient()

# Single page extraction
result = client.extract(url="https://www.example.com")

# Crawl multiple pages
result = client.extract(url="https://www.example.com", is_crawl=True, limit=5)

print(result)
```

The base URL is managed in `src/Scrapper/config.py` — update `SCRAPPER_BASE_URL` there if the service runs on a different host or port.

---

## 📁 Project Structure

```
ComplianceAgent/
├── docker-compose.yml       # Pulls & runs the scraper image
├── .env                     # Your secret keys (never commit this)
├── Readme.md
└── src/
    ├── main.py
    └── Scrapper/
        ├── __init__.py
        ├── config.py        # Service URL configuration
        └── ScrapperClient.py  # HTTP client wrapper
```
