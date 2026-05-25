from fastapi import FastAPI
from contextlib import asynccontextmanager

# Use absolute paths starting from 'src'
from src.api.database import create_db_and_tables
from src.api.routers import documents

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Booting up ComplianceAgent API...")
    create_db_and_tables()
    yield
    print("🛑 Shutting down API...")

app = FastAPI(
    title="Compliance Data Vault", 
    description="Centralized API for managing legal and regulatory metadata.",
    lifespan=lifespan
)

# --- PLUG IN THE ROUTERS ---
app.include_router(documents.router)

# --- GLOBAL HEALTH CHECK ---
@app.get("/health", tags=["System"])
def health_check():
    return {"status": "Operational"}