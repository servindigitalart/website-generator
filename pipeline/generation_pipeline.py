"""
GenerationPipeline — orchestrates the full website creation flow.

Steps:
1. Fetch or build WebsiteGenerationPackage
2. SiteAgent: select template + inject content/tokens
3. ImageAgent: generate hero + section images
4. DeployAgent: archive source → build Astro → deploy to Vercel
5. GSCAgent: add property + submit sitemap
6. Save clinic_website record to Supabase (status=live)
7. Emit SITE_CREATED event → workers platform (workspace + onboarding)
8. Update Redis job with final status

Each step:
  - Updates Redis job progress (real-time polling)
  - Writes current_step to clinic_websites (durable crash visibility)
  - Writes last_step_completed on success
  - Writes last_error + step_failed_at on failure
"""
import asyncio, uuid, structlog
from datetime import datetime, timezone
from pathlib import Path

import httpx

from agents.site_agent import SiteAgent
from agents.image_agent import ImageAgent
from agents.deploy_agent import DeployAgent
from agents.gsc_agent import GSCAgent
from core.config import settings
from core.database import get_supabase
from core.redis_client import update_job
from core import metrics
from models.generation_package import (
    GenerateRequest,
    WebsiteGenerationPackage,
)

logger = structlog.get_logger()

BUILDS_DIR = Path(__file__).parent.parent / "builds"


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_checkpoint(site_id: str | None, data: dict) -> None:
    """
    Write step-tracking fields to clinic_websites. Fire-and-forget —
    a checkpoint failure must never abort the pipeline itself.
    """
    if not site_id:
        return
    try:
        get_supabase().from_("clinic_websites").update(
            {"updated_at": _now(), **data}
        ).eq("id", site_id).execute()
    except Exception as exc:
        logger.warning("checkpoint_write_failed", site_id=site_id, error=str(exc))


def _step_start(job_id: str, site_id: str | None, step: str,
                pct: int, redis_status: str, msg: str = "") -> str:
    """Mark a step as started in both Redis and Supabase. Returns start timestamp."""
    started_at = _now()
    update_job(job_id, {
        "status": redis_status,
        "progress": pct,
        "current_step": step,
        "message": msg,
    })
    _db_checkpoint(site_id, {
        "current_step": step,
        "step_started_at": started_at,
    })
    return started_at


def _step_done(job_id: str, site_id: str | None, step: str,
               extra_db: dict | None = None,
               started_at: str | None = None) -> None:
    """Mark a step as completed in both Redis and Supabase. Logs duration_ms if started_at given."""
    now_dt = datetime.now(timezone.utc)
    duration_ms: int | None = None
    if started_at:
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            duration_ms = round((now_dt - start).total_seconds() * 1000)
        except ValueError:
            pass

    update_job(job_id, {
        "last_step_completed": step,
        **({"step_duration_ms": duration_ms} if duration_ms is not None else {}),
    })
    data = {"last_step_completed": step, "step_completed_at": now_dt.isoformat()}
    if extra_db:
        data.update(extra_db)
    _db_checkpoint(site_id, data)
    logger.info("pipeline.step_done", job_id=job_id, step=step, duration_ms=duration_ms)


def _step_fail(job_id: str, site_id: str | None, step: str, error: str) -> None:
    """Persist failure details. Called from the top-level except before re-raising."""
    now = _now()
    update_job(job_id, {
        "status": "error",
        "current_step": step,
        "last_error": error[:1000],
        "failed_at": now,
    })
    metrics.incr("wg_step_failed_total")
    _db_checkpoint(site_id, {
        "current_step": step,
        "last_error": error[:1000],
        "step_failed_at": now,
        "failed_at": now,
        "status": "error",
    })


# ── Callback emission ─────────────────────────────────────────────────────────

async def _emit_site_created(event: dict, site_id: str | None = None) -> bool:
    """
    Notify the main workers platform that a site went live.
    POST to /api/onboarding/site-activated.

    Retries up to 3 times with exponential backoff (2s, 4s).
    Retries on network errors and 5xx only.
    Does NOT retry on 4xx — those indicate a configuration error.

    Returns True if callback was acknowledged (2xx), False otherwise.
    Non-fatal regardless — rescue_unactivated_clinics recovers within 15 min.
    """
    workers_url = settings.workers_url.rstrip("/")
    clinic_id = event.get("clinic_id")
    url = f"{workers_url}/api/onboarding/site-activated"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.workers_shared_secret:
        headers["Authorization"] = f"Bearer {settings.workers_shared_secret}"

    log = logger.bind(
        clinic_id=clinic_id,
        site_id=site_id or event.get("site_id"),
        workers_url=workers_url,
    )

    max_attempts = 3
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json=event, headers=headers)

            if r.status_code < 300:
                metrics.incr("wg_callback_success_total")
                log.info(
                    "site_created_callback_ok",
                    status=r.status_code,
                    attempt=attempt,
                )
                # Mark clinic_websites as 'deployed' so rescue_unactivated_clinics
                # distinguishes "callback received" from "Vercel live but not notified".
                if site_id:
                    _db_checkpoint(site_id, {
                        "status": "deployed",
                        "callback_ok": True,
                        "callback_attempts": attempt,
                    })
                return True

            if 400 <= r.status_code < 500:
                metrics.incr("wg_callback_4xx_total")
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                log.error(
                    "site_created_callback_4xx",
                    status=r.status_code,
                    body=r.text[:500],
                    attempt=attempt,
                    action="not_retrying_config_error",
                )
                _db_checkpoint(site_id, {
                    "callback_ok": False,
                    "callback_attempts": attempt,
                    "callback_last_error": last_error,
                })
                return False

            # 5xx — transient, will retry
            last_error = f"HTTP {r.status_code}"
            metrics.incr("wg_callback_retry_total")
            log.warning(
                "site_created_callback_5xx",
                status=r.status_code,
                body=r.text[:200],
                attempt=attempt,
                remaining_attempts=max_attempts - attempt,
            )

        except Exception as exc:
            last_error = str(exc)
            metrics.incr("wg_callback_retry_total")
            log.warning(
                "site_created_callback_network_error",
                error=str(exc),
                attempt=attempt,
                remaining_attempts=max_attempts - attempt,
            )

        if attempt < max_attempts:
            await asyncio.sleep(2 ** attempt)  # 2s, 4s

    metrics.incr("wg_callback_exhausted_total")
    log.error(
        "site_created_callback_exhausted",
        max_attempts=max_attempts,
        last_error=last_error,
        action="rescue_unactivated_clinics_beat_task_will_recover_within_15min",
    )
    _db_checkpoint(site_id, {
        "callback_ok": False,
        "callback_attempts": max_attempts,
        "callback_last_error": last_error,
    })
    return False


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _fetch_package_from_ux_analyzer(
    req: GenerateRequest,
) -> WebsiteGenerationPackage:
    """Call ux-analyzer service to get a WebsiteGenerationPackage."""
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


async def run_pipeline(job_id: str, req: GenerateRequest, request_id: str | None = None):
    """
    Full website generation pipeline.

    Catches all exceptions, persists failure details to both Redis and
    clinic_websites (when site_id is available), then re-raises for logging.

    request_id threads the X-Request-ID from the originating HTTP call through
    every pipeline step so logs from generate.py → run_pipeline → agents can
    be correlated end-to-end in Logtail / Datadog.
    """
    # site_id is None until the DB insert in step 2b succeeds.
    site_id: str | None = None
    current_step = "init"

    log = logger.bind(job_id=job_id, clinic_id=req.clinic_id, request_id=request_id)
    metrics.incr("wg_generation_started_total")
    log.info("pipeline.started", clinic_id=req.clinic_id, job_id=job_id)

    try:
        # ----------------------------------------------------------------
        # Step 1 — Get generation package
        # ----------------------------------------------------------------
        current_step = "fetch_package"
        step_started = _step_start(job_id, site_id, current_step, 5, "generating", "Fetching clinic data")

        if req.package:
            package = req.package
        elif req.clinic_url:
            package = await _fetch_package_from_ux_analyzer(req)
        else:
            raise ValueError("Either package or clinic_url must be provided")

        _step_done(job_id, site_id, current_step, started_at=step_started)

        # ----------------------------------------------------------------
        # Step 2 — Prepare site from template
        # ----------------------------------------------------------------
        current_step = "prepare_site"
        step_started = _step_start(job_id, site_id, current_step, 15, "generating", "Preparing site template")

        site_agent = SiteAgent()
        subdomain = req.custom_subdomain or site_agent.generate_subdomain(
            package.brand_dna.brand_name, req.clinic_id
        )
        build_dir = BUILDS_DIR / f"{req.clinic_id}-{job_id[:8]}"
        BUILDS_DIR.mkdir(exist_ok=True)

        gsc_agent = GSCAgent()
        verification_token = gsc_agent.verify_ownership_token(
            f"https://{subdomain}.{settings.base_domain}"
        )
        indexnow_key = settings.indexnow_key or str(uuid.uuid4()).replace("-", "")

        # Insert clinic_websites row — from here on site_id is available
        # for all subsequent checkpoints.
        site_record = get_supabase().from_("clinic_websites").insert({
            "clinic_id": req.clinic_id,
            "clinic_name": package.brand_dna.brand_name,
            "specialty": package.specialty,
            "subdomain": subdomain,
            "site_url": f"https://{subdomain}.{settings.base_domain}",
            "template_used": site_agent.select_template(package.specialty),
            "status": "generating",
            "indexnow_key": indexnow_key,
            "current_step": current_step,
            "step_started_at": _now(),
            "wg_job_id": job_id,
            "retry_count": 0,
        }).execute()
        site_id = site_record.data[0]["id"]
        update_job(job_id, {"site_id": site_id})

        await site_agent.prepare_site(
            package=package,
            build_dir=build_dir,
            gsc_verification_token=verification_token,
            indexnow_key=indexnow_key,
        )

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step, site_id=site_id)

        # ----------------------------------------------------------------
        # Step 3 — Generate images
        # ----------------------------------------------------------------
        current_step = "generate_images"
        step_started = _step_start(job_id, site_id, current_step, 30, "generating", "Generating site images")

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

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step)

        # ----------------------------------------------------------------
        # Step 4a — Archive source to R2
        # ----------------------------------------------------------------
        current_step = "archive_source"
        step_started = _step_start(job_id, site_id, current_step, 45, "building", "Archiving source to R2")

        deploy_agent = DeployAgent()
        r2_source_key = await deploy_agent.upload_source_to_r2(
            build_dir, req.clinic_id, site_id
        )
        _step_done(job_id, site_id, current_step,
                   extra_db={"r2_source_key": r2_source_key} if r2_source_key else None,
                   started_at=step_started)
        log.info("pipeline.step_complete", step=current_step, r2_key=r2_source_key)

        # ----------------------------------------------------------------
        # Step 4b — npm build
        # ----------------------------------------------------------------
        current_step = "build_site"
        step_started = _step_start(job_id, site_id, current_step, 55, "building", "Building Astro site")

        try:
            dist_dir = await deploy_agent.build_site(build_dir)
        except RuntimeError as exc:
            metrics.incr("wg_build_failed_total")
            raise  # let top-level except handle persistence

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step)

        # ----------------------------------------------------------------
        # Step 4c — Deploy to Vercel + wait for READY
        # ----------------------------------------------------------------
        current_step = "deploy_vercel"
        step_started = _step_start(job_id, site_id, current_step, 65, "deploying", "Deploying to Vercel")

        project_name = f"{settings.vercel_project_prefix}{subdomain}"
        try:
            vercel = await deploy_agent.deploy_to_vercel(dist_dir, project_name)
        except TimeoutError as exc:
            metrics.incr("wg_vercel_timeout_total")
            raise

        # Persist vercel_deployment_id IMMEDIATELY — before any further steps.
        # This makes the deployment recoverable even if a subsequent step crashes.
        _step_done(job_id, site_id, current_step, extra_db={
            "vercel_deployment_id": vercel["deployment_id"],
            "vercel_deployment_url": vercel["preview_url"],
            "preview_url": vercel["preview_url"],
            "vercel_project_id": vercel["project_id"],
        }, started_at=step_started)
        update_job(job_id, {
            "vercel_deployment_id": vercel["deployment_id"],
            "preview_url": vercel["preview_url"],
        })
        log.info("pipeline.step_complete", step=current_step,
                 deployment_id=vercel["deployment_id"])

        # ----------------------------------------------------------------
        # Step 4d — Add Vercel domain alias
        # ----------------------------------------------------------------
        current_step = "add_domain"
        step_started = _step_start(job_id, site_id, current_step, 72, "deploying", "Configuring domain")

        site_url = await deploy_agent.add_vercel_domain(project_name, subdomain)
        site_url = f"https://{site_url}"

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step, site_url=site_url)

        # Upload dist to R2 (non-fatal if it fails — source archive is enough for re-publish)
        try:
            await deploy_agent.upload_dist_to_r2(dist_dir, req.clinic_id, site_id)
        except Exception as exc:
            log.warning("dist_upload_r2_failed", error=str(exc))

        # Clean up local build dir (best-effort; Railway ephemeral disk anyway)
        await deploy_agent.cleanup_build_dir(build_dir)

        # ----------------------------------------------------------------
        # Step 5 — GSC setup (non-fatal)
        # ----------------------------------------------------------------
        current_step = "setup_gsc"
        step_started = _step_start(job_id, site_id, current_step, 82, "deploying", "Setting up Google Search Console")

        gsc_property = f"{settings.gsc_property_prefix}{subdomain}.{settings.base_domain}"
        gsc_verified = False
        gsc_sitemap_submitted = False

        if req.setup_gsc:
            try:
                gsc_verified = await asyncio.to_thread(
                    gsc_agent.add_property, gsc_property
                )
                if gsc_verified:
                    gsc_sitemap_submitted = await asyncio.to_thread(
                        gsc_agent.submit_sitemap, gsc_property
                    )
            except Exception as exc:
                log.warning("gsc_setup_failed", error=str(exc))

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step,
                 gsc_verified=gsc_verified)

        # ----------------------------------------------------------------
        # Step 6 — Finalize clinic_websites (status=live)
        # ----------------------------------------------------------------
        current_step = "finalize_record"
        step_started = _step_start(job_id, site_id, current_step, 90, "finalizing", "Activating site record")

        now = _now()
        get_supabase().from_("clinic_websites").update({
            "status": "live",
            "current_step": current_step,
            "site_url": site_url,
            "gsc_property_url": gsc_property,
            "gsc_verified": gsc_verified,
            "gsc_sitemap_submitted": gsc_sitemap_submitted,
            "live_at": now,
            "updated_at": now,
        }).eq("id", site_id).execute()

        _step_done(job_id, site_id, current_step, started_at=step_started)
        log.info("pipeline.step_complete", step=current_step, site_url=site_url)

        # ----------------------------------------------------------------
        # Step 7 — Emit SITE_CREATED callback (retries internally)
        # ----------------------------------------------------------------
        current_step = "emit_callback"
        step_started = _step_start(job_id, site_id, current_step, 95, "finalizing", "Activating platform services")

        callback_ok = await _emit_site_created(
            event={
                "site_id": site_id,
                "clinic_id": req.clinic_id,
                "site_url": site_url,
                "subdomain": subdomain,
                "specialty": package.specialty,
                "clinic_name": package.brand_dna.brand_name,
                "gsc_property": gsc_property,
            },
            site_id=site_id,
        )
        update_job(job_id, {"callback_ok": callback_ok})

        if callback_ok:
            _step_done(job_id, site_id, current_step, started_at=step_started)
            metrics.incr("wg_readiness_dispatched_total")
        else:
            # clinic_websites status/callback fields already set by _emit_site_created
            log.warning("pipeline.callback_failed_rescue_will_recover",
                        site_id=site_id, site_url=site_url)

        log.info("pipeline.step_complete", step=current_step, callback_ok=callback_ok)

        # ----------------------------------------------------------------
        # Step 8 — Final job status
        # ----------------------------------------------------------------
        current_step = "completed"
        update_job(job_id, {
            "status": "completed",
            "progress": 100,
            "current_step": "completed",
            "message": "Site is live!",
            "result": {
                "site_id": site_id,
                "site_url": site_url,
                "preview_url": vercel["preview_url"],
                "subdomain": subdomain,
                "gsc_property": gsc_property,
                "gsc_verified": gsc_verified,
                "callback_ok": callback_ok,
            },
        })
        _db_checkpoint(site_id, {
            "current_step": "completed",
            "last_step_completed": "completed",
        })

        metrics.incr("wg_generation_completed_total")
        log.info("pipeline.complete",
                 job_id=job_id, site_id=site_id, site_url=site_url,
                 callback_ok=callback_ok)

    except Exception as exc:
        metrics.incr("wg_generation_failed_total")
        log.exception("pipeline.failed",
                      job_id=job_id, current_step=current_step,
                      site_id=site_id, error=str(exc))

        # Persist failure to both Redis and Supabase (if site_id available).
        _step_fail(job_id, site_id, current_step, str(exc))

        # Ensure clinic_websites reflects the terminal failure state.
        if site_id:
            try:
                get_supabase().from_("clinic_websites").update({
                    "status": "error",
                    "current_step": current_step,
                    "last_error": str(exc)[:1000],
                    "failed_at": _now(),
                    "updated_at": _now(),
                }).eq("id", site_id).execute()
            except Exception as db_exc:
                log.warning("pipeline_failure_db_write_failed", error=str(db_exc))
