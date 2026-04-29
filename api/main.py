from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.logging import setup_logging
from core.config import settings
import structlog

setup_logging()
logger = structlog.get_logger()

app = FastAPI(
    title="MEDPLATFORM Website Generator",
    description="Generates premium medical clinic websites from brand DNA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes.generate import router as generate_router
from api.routes.sites import router as sites_router
from api.routes.seo import router as seo_router
from api.routes.images import router as images_router

app.include_router(generate_router)
app.include_router(sites_router)
app.include_router(seo_router)
app.include_router(images_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.service_name,
        "port": settings.port,
    }


@app.get("/")
async def root():
    return {
        "service": "MEDPLATFORM Website Generator",
        "version": "1.0.0",
        "templates": [
            "dermatology", "orthopedics", "dental", "med-spa", "general"
        ],
        "endpoints": {
            "generate": "POST /api/generate",
            "status": "GET /api/generate/status/{job_id}",
            "sites": "GET /api/sites",
            "seo": "POST /api/seo/run/{site_id}",
            "images": "POST /api/images/generate",
        }
    }
