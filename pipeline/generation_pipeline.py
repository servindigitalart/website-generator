"""
GenerationPipeline — orchestrates the full website creation flow.

Steps:
1. Fetch or build WebsiteGenerationPackage
2. SiteAgent: select template + inject content/tokens
3. ImageAgent: generate hero + section images
4. DeployAgent: build Astro → deploy to Vercel
5. GSCAgent: add property + submit sitemap
6. Save clinic_website record to Supabase
7. Update Redis job with final status

Each step updates Redis job progress so the polling endpoint
reflects real-time status.
"""
import asyncio, uuid, structlog
from datetime import datetime, timezone
from pathlib import Path

from agents.site_agent import SiteAgent
from agents.image_agent import ImageAgent
from agents.deploy_agent import DeployAgent
from agents.gsc_agent import GSCAgent
from core.config import settings
from core.database import get_supabase
from core.redis_client import update_job
from models.generation_package import (
    GenerateRequest,
    WebsiteGenerationPackage,
)

logger = structlog.get_logger()

BUILDS_DIR = Path(__file__).parent.parent / "builds"


async def _fetch_package_from_ux_analyzer(
    req: GenerateRequest,
) -> WebsiteGenerationPackage:
    """Call ux-analyzer service to get a WebsiteGenerationPackage."""
    import httpx
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{settings.ux_analyzer_url}/api/analyze",
            json={
                "clinic_id": req.clinic_id,
                "url": req.clinic_url,
                "specialty": req.specialty,
            },
        )
        r.raise_for_status()
        return WebsiteGenerationPackage(**r.json())


async def run_pipeline(job_id: str, req: GenerateRequest):
    """
    Full website generation pipeline.
    Catches all exceptions and writes error status to Redis.
    """
    def _progress(pct: int, status: str, msg: str = ""):
        update_job(job_id, {
            "status": status,
            "progress": pct,
            "message": msg,
        })

    try:
        # ----------------------------------------------------------------
        # Step 1 — Get generation package
        # ----------------------------------------------------------------
        _progress(5, "generating", "Fetching clinic data")
        if req.package:
            package = req.package
        elif req.clinic_url:
            package = await _fetch_package_from_ux_analyzer(req)
        else:
            raise ValueError(
                "Either package or clinic_url must be provided"
            )

        # ----------------------------------------------------------------
        # Step 2 — Prepare site from template
        # ----------------------------------------------------------------
        _progress(15, "generating", "Preparing site template")
        site_agent = SiteAgent()
        subdomain = req.custom_subdomain or site_agent.generate_subdomain(
            package.brand_dna.brand_name, req.clinic_id
        )
        build_dir = BUILDS_DIR / f"{req.clinic_id}-{job_id[:8]}"
        BUILDS_DIR.mkdir(exist_ok=True)

        # Create a preliminary DB record so we have a site_id
        gsc_agent = GSCAgent()
        verification_token = gsc_agent.verify_ownership_token(
            f"https://{subdomain}.{settings.base_domain}"
        )
        indexnow_key = settings.indexnow_key or str(uuid.uuid4()).replace("-", "")

        site_record = get_supabase().from_("clinic_websites").insert({
            "clinic_id": req.clinic_id,
            "clinic_name": package.brand_dna.brand_name,
            "specialty": package.specialty,
            "subdomain": subdomain,
            "site_url": f"https://{subdomain}.{settings.base_domain}",
            "template_used": site_agent.select_template(package.specialty),
            "status": "generating",
            "indexnow_key": indexnow_key,
        }).execute()
        site_id = site_record.data[0]["id"]
        update_job(job_id, {"site_id": site_id})

        await site_agent.prepare_site(
            package=package,
            build_dir=build_dir,
            gsc_verification_token=verification_token,
            indexnow_key=indexnow_key,
        )

        # ----------------------------------------------------------------
        # Step 3 — Generate images
        # ----------------------------------------------------------------
        _progress(30, "generating", "Generating site images")
        if req.generate_images:
            img_agent = ImageAgent()
            sections = ["hero", "services", "team", "about", "testimonials"]
            brand_colors = [
                package.brand_dna.primary_color,
                package.brand_dna.secondary_color,
                package.brand_dna.accent_color,
            ]
            images = await img_agent.generate_section_images(
                site_id=site_id,
                clinic_id=req.clinic_id,
                specialty=package.specialty,
                sections=sections,
                brand_colors=brand_colors,
                count_per_section=settings.images_per_section,
            )
            update_job(job_id, {"generated_images": images})

        # ----------------------------------------------------------------
        # Step 4 — Build + deploy
        # ----------------------------------------------------------------
        _progress(55, "building", "Building Astro site")
        deploy_agent = DeployAgent()
        deploy_result = await deploy_agent.deploy(
            build_dir=build_dir,
            clinic_id=req.clinic_id,
            site_id=site_id,
            subdomain=subdomain,
        )

        # ----------------------------------------------------------------
        # Step 5 — GSC setup
        # ----------------------------------------------------------------
        _progress(85, "deploying", "Setting up Google Search Console")
        site_url = deploy_result["site_url"]
        gsc_property = f"{settings.gsc_property_prefix}{subdomain}.{settings.base_domain}"

        gsc_verified = False
        gsc_sitemap_submitted = False
        if req.setup_gsc:
            gsc_verified = await asyncio.to_thread(
                gsc_agent.add_property, gsc_property
            )
            if gsc_verified:
                gsc_sitemap_submitted = await asyncio.to_thread(
                    gsc_agent.submit_sitemap, gsc_property
                )

        # ----------------------------------------------------------------
        # Step 6 — Update DB record to live
        # ----------------------------------------------------------------
        now = datetime.now(timezone.utc).isoformat()
        get_supabase().from_("clinic_websites").update({
            "status": "live",
            "site_url": site_url,
            "preview_url": deploy_result["preview_url"],
            "vercel_project_id": deploy_result["vercel_project_id"],
            "vercel_deployment_id": deploy_result["vercel_deployment_id"],
            "gsc_property_url": gsc_property,
            "gsc_verified": gsc_verified,
            "gsc_sitemap_submitted": gsc_sitemap_submitted,
            "live_at": now,
            "updated_at": now,
        }).eq("id", site_id).execute()

        # ----------------------------------------------------------------
        # Step 7 — Final job status
        # ----------------------------------------------------------------
        _progress(100, "completed", "Site is live!")
        update_job(job_id, {
            "result": {
                "site_id": site_id,
                "site_url": site_url,
                "preview_url": deploy_result["preview_url"],
                "subdomain": subdomain,
                "gsc_property": gsc_property,
                "gsc_verified": gsc_verified,
            }
        })
        logger.info("pipeline_complete",
                    job_id=job_id, site_id=site_id, url=site_url)

    except Exception as e:
        logger.exception("pipeline_failed", job_id=job_id, error=str(e))
        update_job(job_id, {
            "status": "error",
            "progress": 0,
            "error": str(e),
        })
        # Update DB record if we have a site_id
        job = __import__("core.redis_client", fromlist=["get_job"]).get_job(job_id)
        if job and job.get("site_id"):
            get_supabase().from_("clinic_websites").update({
                "status": "error",
                "error_message": str(e)[:500],
            }).eq("id", job["site_id"]).execute()
