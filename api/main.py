import sys
import traceback

print(f"Starting api.main, Python {sys.version}", flush=True)

try:
    import logging
    import os
    import time
    import uuid

    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
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

    # CORS — restrict to known origins in production; wildcard only in dev.
    _cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3002", "http://localhost:4321"]
    _admin_url = os.getenv("ADMIN_URL", "")
    if _admin_url.startswith("https://"):
        _cors_origins.append(_admin_url.rstrip("/"))
    _portal_url = os.getenv("PORTAL_URL", "")
    if _portal_url.startswith("https://"):
        _cors_origins.append(_portal_url.rstrip("/"))
    _allow_origins = _cors_origins if settings.environment == "production" else ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request-ID correlation middleware ──────────────────────────────────────
    # Stamps every request with X-Request-ID so logs from the API and pipeline
    # background task can be correlated end-to-end with the workers service.
    _req_log = logging.getLogger("wg.request")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000)
            _req_log.error(
                "request_unhandled_error method=%s path=%s request_id=%s elapsed_ms=%d error=%r",
                request.method, request.url.path, request_id, elapsed, str(exc),
            )
            raise
        elapsed = round((time.perf_counter() - start) * 1000)
        status = response.status_code
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
        _req_log.log(
            level,
            "request method=%s path=%s status=%d request_id=%s elapsed_ms=%d",
            request.method, request.url.path, status, request_id, elapsed,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    from api.routes.generate import router as generate_router
    from api.routes.sites import router as sites_router
    from api.routes.seo import router as seo_router
    from api.routes.images import router as images_router

    app.include_router(generate_router)
    app.include_router(sites_router)
    app.include_router(seo_router)
    app.include_router(images_router)

    @app.on_event("startup")
    async def startup_check():
        """
        Log presence (never values) of critical env vars.
        Warn on localhost service URLs in production — the most common
        misconfiguration that causes silent pipeline failures.
        """
        startup_log = logging.getLogger("wg.startup")
        required = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "REDIS_URL", "VERCEL_TOKEN"]
        optional_services = ["WORKERS_URL", "UX_ANALYZER_URL"]
        auth_vars = ["WORKERS_SHARED_SECRET", "GEMINI_API_KEY"]

        missing_required = [k for k in required if not os.getenv(k)]
        localhost_in_prod = [
            k for k in optional_services
            if "localhost" in os.getenv(k, "") and settings.environment == "production"
        ]
        missing_auth = [k for k in auth_vars if not os.getenv(k)]

        if missing_required:
            startup_log.error("startup_missing_required_vars vars=%s", missing_required)
        if localhost_in_prod:
            startup_log.warning("startup_localhost_urls_in_production vars=%s", localhost_in_prod)
        if missing_auth and settings.environment == "production":
            startup_log.warning(
                "startup_missing_auth_vars vars=%s "
                "(WORKERS_SHARED_SECRET empty = callbacks unauthenticated, "
                "GEMINI_API_KEY empty = image generation will fail)",
                missing_auth,
            )
        startup_log.info(
            "startup_complete service=website-generator environment=%s "
            "missing_required=%d localhost_in_prod=%d missing_auth=%d",
            settings.environment,
            len(missing_required),
            len(localhost_in_prod),
            len(missing_auth),
        )

    @app.get("/metrics")
    async def operational_metrics():
        """
        WG operational counters — Redis INCR values under wg_metrics:* prefix.
        Read-only. Counters accumulate until manually reset via redis-cli.
        Use GET /api/generate/health/operations for alerting thresholds.
        """
        import asyncio
        from core import metrics as wg_metrics
        loop = asyncio.get_running_loop()
        counters = await loop.run_in_executor(None, wg_metrics.get_all)
        return JSONResponse(content={"counters": counters, "service": "website-generator"})

    @app.get("/health")
    async def health():
        """
        Deep health check — probes every critical dependency.
        Returns 200 if all healthy, 503 if any dependency is degraded.
        Used by Railway restart policy and external uptime monitors.
        """
        checks: dict[str, str] = {}
        healthy = True

        # Redis
        try:
            from core.redis_client import get_redis
            r = get_redis()
            r.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            healthy = False

        # Supabase (lightweight query)
        try:
            from core.database import get_supabase
            get_supabase().from_("clinic_websites").select("id").limit(1).execute()
            checks["supabase"] = "ok"
        except Exception as exc:
            checks["supabase"] = f"error: {exc}"
            healthy = False

        # R2 (bucket reachable)
        try:
            import boto3
            if settings.r2_endpoint:
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.r2_endpoint,
                    aws_access_key_id=settings.r2_access_key,
                    aws_secret_access_key=settings.r2_secret_key,
                    region_name="auto",
                )
                s3.head_bucket(Bucket=settings.r2_bucket)
                checks["r2"] = "ok"
            else:
                checks["r2"] = "not_configured"
        except Exception as exc:
            checks["r2"] = f"error: {exc}"
            # R2 degraded is non-fatal for the API

        status_code = 200 if healthy else 503
        return JSONResponse(
            content={
                "status": "ok" if healthy else "degraded",
                "service": "website-generator",
                "checks": checks,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            status_code=status_code,
        )

    @app.get("/")
    async def root():
        return {
            "service": "MEDPLATFORM Website Generator",
            "version": "1.0.0",
            "templates": ["dermatology", "orthopedics", "dental", "med-spa", "general"],
            "endpoints": {
                "generate": "POST /api/generate",
                "status": "GET /api/generate/status/{job_id}",
                "sites": "GET /api/sites",
                "seo": "POST /api/seo/run/{site_id}",
                "images": "POST /api/images/generate",
                "metrics": "GET /metrics",
                "ops_health": "GET /api/generate/health/operations",
            },
        }

except Exception as e:
    print(f"FATAL: Failed to initialize api.main: {e}", flush=True)
    traceback.print_exc()
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok", "degraded": True}
