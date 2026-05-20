"""
Website generation routes — operator diagnostics layer.

Public routes:
  POST /api/generate                         — start generation pipeline
  GET  /api/generate/status/{job_id}         — poll Redis job state
  GET  /api/generate/result/{job_id}         — fetch completed result

Operator diagnostics (not customer-facing):
  GET  /api/generate/diagnostics/search      — bulk broken-state scan
  GET  /api/generate/diagnostics/dead-letter — unrecoverable jobs
  GET  /api/generate/diagnostics/{clinic_id} — full lifecycle snapshot
  GET  /api/generate/timeline/{clinic_id}    — chronological event list
  GET  /api/generate/health/operations       — aggregated ops health

Admin recovery (operator-only):
  POST /api/generate/admin/replay-callback/{clinic_id}     — re-fire site-activated
  POST /api/generate/admin/reset-stale-pipeline/{clinic_id}— mark stale active jobs as error
  POST /api/generate/admin/clear-redis-job/{job_id}        — delete stale Redis key
"""
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from core.config import settings
from core.database import get_supabase
from core.redis_client import get_job, get_redis, set_job
from models.generation_package import GenerateRequest, GenerateResponse
from pipeline.generation_pipeline import run_pipeline

router = APIRouter(prefix="/api/generate", tags=["generation"])
logger = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────
_STALE_GENERATION_MINUTES = 30   # active status but no DB update → "stuck"
_DEAD_LETTER_GENERATION_HOURS = 1  # stuck longer than this → "dead letter"
_STALE_QUEUE_MINUTES = 20        # enrichment_status='queued' without touch → exhausted
_DEAD_LETTER_ENRICH_HOURS = 1    # site live this long but enrichment never progressed
_CALLBACK_EXHAUSTED_ATTEMPTS = 3  # callback_attempts >= this → permanently failed


# ── Existing generation routes ────────────────────────────────────────────────

@router.post("", response_model=GenerateResponse)
async def generate_website(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Start website generation pipeline.

    Returns 409 if an active generation already exists for this clinic
    (status=generating/building/deploying) to prevent concurrent pipelines.
    Returns job_id immediately — poll /status/{job_id} for progress.
    """
    db = get_supabase()

    # Idempotency guard: reject duplicate pipeline for same clinic.
    # Callers must use POST /admin/reset-stale-pipeline first if they want
    # to force a new run while one is nominally in progress.
    try:
        active = (
            db.from_("clinic_websites")
            .select("id, status, wg_job_id, updated_at")
            .eq("clinic_id", req.clinic_id)
            .in_("status", ["generating", "building", "deploying"])
            .limit(1)
            .execute()
        )
        if active.data:
            row = active.data[0]
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "active_generation_exists",
                    "message": (
                        f"Generation already in progress (status={row['status']}). "
                        "Use POST /api/generate/admin/reset-stale-pipeline/{clinic_id} "
                        "if the job is stuck, then retry."
                    ),
                    "site_id": row["id"],
                    "status": row["status"],
                    "wg_job_id": row.get("wg_job_id"),
                    "updated_at": row.get("updated_at"),
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Guard failure must not block generation — log and proceed.
        logger.warning(
            "generate.idempotency_check_failed",
            clinic_id=req.clinic_id,
            error=str(exc),
        )

    # Global concurrent pipeline cap — prevents Railway OOM and Vercel rate limit hits.
    # Checked after per-clinic guard so the 409 path doesn't count against the cap.
    if settings.max_concurrent_pipelines > 0:
        try:
            active_count_result = (
                db.from_("clinic_websites")
                .select("id")
                .in_("status", ["generating", "building", "deploying"])
                .execute()
            )
            active_count = len(active_count_result.data) if active_count_result.data else 0
            if active_count >= settings.max_concurrent_pipelines:
                logger.warning(
                    "generate.concurrent_cap_hit",
                    clinic_id=req.clinic_id,
                    active=active_count,
                    cap=settings.max_concurrent_pipelines,
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "concurrent_pipeline_limit",
                        "message": (
                            f"Maximum concurrent pipelines reached "
                            f"({active_count}/{settings.max_concurrent_pipelines}). "
                            "Retry in 2–5 minutes or increase MAX_CONCURRENT_PIPELINES."
                        ),
                        "active_pipelines": active_count,
                        "limit": settings.max_concurrent_pipelines,
                        "retry_after_seconds": 120,
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("generate.cap_check_failed", clinic_id=req.clinic_id, error=str(exc))

    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    job_id = str(uuid.uuid4())
    set_job(job_id, {
        "status": "queued",
        "job_id": job_id,
        "clinic_id": req.clinic_id,
        "specialty": req.specialty,
        "progress": 0,
        "request_id": request_id,
    })
    background_tasks.add_task(run_pipeline, job_id, req, request_id)
    logger.info(
        "generate.job_queued",
        job_id=job_id,
        clinic_id=req.clinic_id,
        specialty=req.specialty,
        request_id=request_id,
    )
    return GenerateResponse(
        job_id=job_id,
        status="queued",
        clinic_id=req.clinic_id,
        poll_url=f"/api/generate/status/{job_id}",
        estimated_minutes=5,
    )


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=202, detail=f"Not ready: {job.get('status')}")
    return job.get("result")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_ago(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 60, 1)


def _recommended_action(
    *,
    cw_status: str | None,
    current_step: str | None,
    last_error: str | None,
    enrichment_status: str | None,
    callback_ok: bool | None,
    score_exists: bool,
    generation_stale: bool,
    cw_updated_minutes_ago: float | None,
) -> str:
    if not cw_status:
        if enrichment_status == "enriched" and score_exists:
            return "Pipeline complete — no action needed"
        if enrichment_status == "enriched":
            return "Enrichment complete but scoring missing — trigger score_clinic or check scoring worker"
        return "No website generation found — trigger via POST /api/wg/generate"

    if cw_status in ("generating", "building", "deploying") and generation_stale:
        age = f"{cw_updated_minutes_ago:.0f}min" if cw_updated_minutes_ago else "unknown"
        return (
            f"Likely crashed WG pipeline (stalled at step={current_step or 'unknown'}, "
            f"no progress for {age}) — POST /api/generate/admin/reset-stale-pipeline/{{clinic_id}}, "
            "then retry generation"
        )

    if cw_status in ("generating", "building", "deploying"):
        return f"Generation in progress at step={current_step or 'unknown'} — no action needed"

    if cw_status in ("error", "failed"):
        err = (last_error or "no error recorded")[:100]
        return (
            f"Generation failed at step={current_step}: {err} — "
            "retry via POST /api/wg/retry-generation/{clinic_id}"
        )

    if cw_status in ("live", "deployed") and callback_ok is False:
        return (
            "Site is live but callback to workers failed — enrichment was never dispatched. "
            "POST /api/generate/admin/replay-callback/{clinic_id} to recover"
        )

    if cw_status in ("live", "deployed") and enrichment_status == "queued":
        return (
            "Enrichment queued — verify_and_enrich probing DNS/readiness "
            "(retries every 60s, max 10 min). No action unless stale >20 min"
        )

    if cw_status in ("live", "deployed") and enrichment_status == "enriching":
        return "Enrichment in progress — no action needed"

    if cw_status in ("live", "deployed") and enrichment_status == "failed":
        return (
            "Enrichment failed — POST /api/wg/admin/retry-enrichment/{clinic_id} to re-queue"
        )

    if cw_status in ("live", "deployed") and enrichment_status == "enriched" and not score_exists:
        return (
            "Enrichment complete but scoring missing — "
            "POST /api/wg/admin/retry-scoring/{clinic_id} to re-queue"
        )

    if cw_status in ("live", "deployed") and enrichment_status == "enriched" and score_exists:
        return "Pipeline complete — no action needed"

    if cw_status in ("live", "deployed") and enrichment_status == "pending":
        return (
            "Site live but enrichment still pending — "
            "rescue_unactivated_clinics will pick up within 15 min. "
            "If stuck >1h use POST /api/generate/admin/replay-callback/{clinic_id}"
        )

    return f"Unknown state — cw_status={cw_status}, enrichment_status={enrichment_status}"


# ── Diagnostics: search ───────────────────────────────────────────────────────

@router.get("/diagnostics/search")
async def diagnostics_search(
    state: str = Query(
        "all",
        description=(
            "Filter: all | failed | stuck | callback_failed | "
            "queued_stale | missing_scores | no_vercel_id"
        ),
    ),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Operator search for clinics in broken generation states.
    Returns lightweight summaries keyed by clinic_id.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    stale_gen_cutoff = (now - timedelta(minutes=_STALE_GENERATION_MINUTES)).isoformat()
    stale_queue_cutoff = (now - timedelta(minutes=_STALE_QUEUE_MINUTES)).isoformat()
    results: list[dict] = []

    if state in ("all", "failed"):
        rows = (
            db.from_("clinic_websites")
            .select("clinic_id, status, current_step, last_error, failed_at, updated_at")
            .in_("status", ["error", "failed"])
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        for r in rows.data or []:
            results.append({
                "clinic_id": r["clinic_id"],
                "state": "generation_failed",
                "current_step": r.get("current_step"),
                "last_error": (r.get("last_error") or "")[:120],
                "failed_at": r.get("failed_at"),
                "recommended_action": (
                    f"Retry generation (failed at step={r.get('current_step')}) — "
                    "POST /api/wg/retry-generation/{clinic_id}"
                ),
            })

    if state in ("all", "stuck"):
        rows = (
            db.from_("clinic_websites")
            .select("clinic_id, status, current_step, updated_at")
            .in_("status", ["generating", "building", "deploying"])
            .lt("updated_at", stale_gen_cutoff)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        for r in rows.data or []:
            updated = _parse_dt(r.get("updated_at"))
            age = _minutes_ago(updated, now)
            results.append({
                "clinic_id": r["clinic_id"],
                "state": "stuck_pipeline",
                "current_step": r.get("current_step"),
                "stalled_minutes": age,
                "recommended_action": (
                    f"Possible crashed pipeline (stalled {age:.0f}min at step={r.get('current_step')}) — "
                    "POST /api/generate/admin/reset-stale-pipeline/{clinic_id}, then retry"
                ),
            })

    if state in ("all", "callback_failed"):
        rows = (
            db.from_("clinic_websites")
            .select("clinic_id, status, callback_ok, callback_attempts, callback_last_error, updated_at")
            .in_("status", ["live", "deployed"])
            .eq("callback_ok", False)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        for r in rows.data or []:
            results.append({
                "clinic_id": r["clinic_id"],
                "state": "callback_failed",
                "callback_attempts": r.get("callback_attempts"),
                "callback_last_error": (r.get("callback_last_error") or "")[:120],
                "recommended_action": (
                    "POST /api/generate/admin/replay-callback/{clinic_id} to re-fire enrichment"
                ),
            })

    if state in ("all", "queued_stale"):
        rows = (
            db.from_("clinics")
            .select("id, enrichment_status, updated_at")
            .eq("enrichment_status", "queued")
            .lt("updated_at", stale_queue_cutoff)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        for r in rows.data or []:
            updated = _parse_dt(r.get("updated_at"))
            age = _minutes_ago(updated, now)
            results.append({
                "clinic_id": r["id"],
                "state": "queued_stale",
                "queued_minutes": age,
                "recommended_action": (
                    "verify_and_enrich may have exhausted — "
                    "rescue_unactivated_clinics will retry <15 min. "
                    "If stuck >30 min: POST /api/generate/admin/replay-callback/{clinic_id}"
                ),
            })

    if state in ("all", "missing_scores"):
        enriched = (
            db.from_("clinics")
            .select("id")
            .eq("enrichment_status", "enriched")
            .limit(limit)
            .execute()
        )
        if enriched.data:
            ids = [r["id"] for r in enriched.data]
            scored = (
                db.from_("clinic_scores")
                .select("clinic_id")
                .in_("clinic_id", ids)
                .execute()
            )
            scored_ids = {r["clinic_id"] for r in (scored.data or [])}
            for cid in ids:
                if cid not in scored_ids:
                    results.append({
                        "clinic_id": cid,
                        "state": "missing_scores",
                        "recommended_action": (
                            "POST /api/wg/admin/retry-scoring/{clinic_id}"
                        ),
                    })

    if state in ("all", "no_vercel_id"):
        rows = (
            db.from_("clinic_websites")
            .select("clinic_id, status, updated_at")
            .in_("status", ["live", "deployed"])
            .is_("vercel_deployment_id", "null")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        for r in rows.data or []:
            results.append({
                "clinic_id": r["clinic_id"],
                "state": "no_vercel_id",
                "site_status": r.get("status"),
                "recommended_action": (
                    "Vercel deployment ID not persisted — deploy_vercel step likely crashed. "
                    "Check Vercel dashboard for the project"
                ),
            })

    logger.info("diagnostics.search_complete", filter=state, result_count=len(results))
    return {"filter": state, "count": len(results), "results": results[:limit], "as_of": now.isoformat()}


# ── Diagnostics: dead letter ──────────────────────────────────────────────────

@router.get("/diagnostics/dead-letter")
async def dead_letter(limit: int = Query(50, ge=1, le=200)):
    """
    Surface all clinics in provably unrecoverable states that require
    explicit operator intervention — auto-recovery systems cannot help these.

    Dead-letter criteria:
      • Generation failed (status=error/failed)
      • Callback permanently exhausted (callback_ok=False AND attempts >=3)
      • Pipeline frozen >1h with active status (Railway likely crashed and won't restart)
      • Enrichment failed after retries
      • Site live >1h but enrichment still pending/queued (rescue exhausted)
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    dead_gen_cutoff = (now - timedelta(hours=_DEAD_LETTER_GENERATION_HOURS)).isoformat()
    dead_enrich_cutoff = (now - timedelta(hours=_DEAD_LETTER_ENRICH_HOURS)).isoformat()
    results: list[dict] = []

    # 1. Terminal generation failures
    rows = (
        db.from_("clinic_websites")
        .select(
            "clinic_id, status, current_step, last_error, failed_at, retry_count, "
            "callback_attempts, updated_at, wg_job_id"
        )
        .in_("status", ["error", "failed"])
        .order("failed_at", desc=True)
        .limit(limit)
        .execute()
    )
    for r in rows.data or []:
        failed = _parse_dt(r.get("failed_at") or r.get("updated_at"))
        results.append({
            "clinic_id": r["clinic_id"],
            "category": "generation_failed",
            "status": r.get("status"),
            "failed_step": r.get("current_step"),
            "last_error": (r.get("last_error") or "")[:200],
            "failed_at": r.get("failed_at"),
            "stuck_hours": _minutes_ago(failed, now) / 60 if failed else None,
            "retry_count": r.get("retry_count"),
            "recommended_action": (
                "POST /api/wg/retry-generation/{clinic_id} — "
                "or POST /api/wg/mark-failed/{clinic_id} to close without retrying"
            ),
        })

    # 2. Callback exhausted (site live, enrichment permanently blocked)
    rows = (
        db.from_("clinic_websites")
        .select(
            "clinic_id, status, callback_ok, callback_attempts, callback_last_error, "
            "live_at, updated_at"
        )
        .in_("status", ["live", "deployed"])
        .eq("callback_ok", False)
        .gte("callback_attempts", _CALLBACK_EXHAUSTED_ATTEMPTS)
        .order("live_at", desc=True)
        .limit(limit)
        .execute()
    )
    for r in rows.data or []:
        live = _parse_dt(r.get("live_at"))
        results.append({
            "clinic_id": r["clinic_id"],
            "category": "callback_exhausted",
            "status": r.get("status"),
            "callback_attempts": r.get("callback_attempts"),
            "callback_last_error": (r.get("callback_last_error") or "")[:200],
            "live_at": r.get("live_at"),
            "stuck_hours": _minutes_ago(live, now) / 60 if live else None,
            "recommended_action": (
                "POST /api/generate/admin/replay-callback/{clinic_id} to re-fire workers notification"
            ),
        })

    # 3. Pipeline frozen (active status, no update for >1h — Railway won't auto-recover)
    rows = (
        db.from_("clinic_websites")
        .select("clinic_id, status, current_step, updated_at, wg_job_id")
        .in_("status", ["generating", "building", "deploying"])
        .lt("updated_at", dead_gen_cutoff)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    for r in rows.data or []:
        updated = _parse_dt(r.get("updated_at"))
        results.append({
            "clinic_id": r["clinic_id"],
            "category": "pipeline_frozen",
            "status": r.get("status"),
            "frozen_at_step": r.get("current_step"),
            "last_update_at": r.get("updated_at"),
            "stuck_hours": _minutes_ago(updated, now) / 60 if updated else None,
            "wg_job_id": r.get("wg_job_id"),
            "recommended_action": (
                "POST /api/generate/admin/reset-stale-pipeline/{clinic_id}, "
                "then POST /api/wg/retry-generation/{clinic_id}"
            ),
        })

    # 4. Enrichment permanently failed
    rows = (
        db.from_("clinics")
        .select("id, enrichment_status, enrichment_error, enrichment_attempted_at, updated_at")
        .eq("enrichment_status", "failed")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    for r in rows.data or []:
        attempted = _parse_dt(r.get("enrichment_attempted_at"))
        results.append({
            "clinic_id": r["id"],
            "category": "enrichment_failed",
            "enrichment_error": (r.get("enrichment_error") or "")[:200],
            "failed_at": r.get("enrichment_attempted_at"),
            "stuck_hours": _minutes_ago(attempted, now) / 60 if attempted else None,
            "recommended_action": (
                "POST /api/wg/admin/retry-enrichment/{clinic_id} after investigating error"
            ),
        })

    # 5. Site live >1h but enrichment never progressed (rescue exhausted)
    rows = (
        db.from_("clinic_websites")
        .select("clinic_id, status, live_at, callback_ok")
        .in_("status", ["live", "deployed"])
        .lt("live_at", dead_enrich_cutoff)
        .execute()
    )
    if rows.data:
        deployed_ids = [r["clinic_id"] for r in rows.data]
        live_at_map = {r["clinic_id"]: r.get("live_at") for r in rows.data}
        stuck_clinics = (
            db.from_("clinics")
            .select("id, enrichment_status, updated_at")
            .in_("id", deployed_ids)
            .in_("enrichment_status", ["pending", "queued"])
            .execute()
        )
        for r in stuck_clinics.data or []:
            live_at = _parse_dt(live_at_map.get(r["id"]))
            results.append({
                "clinic_id": r["id"],
                "category": "enrichment_abandoned",
                "enrichment_status": r.get("enrichment_status"),
                "site_live_at": live_at_map.get(r["id"]),
                "stuck_hours": _minutes_ago(live_at, now) / 60 if live_at else None,
                "recommended_action": (
                    "POST /api/generate/admin/replay-callback/{clinic_id} to restart enrichment dispatch"
                ),
            })

    # Deduplicate clinic_ids that appear in multiple categories
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        if r["clinic_id"] not in seen:
            seen.add(r["clinic_id"])
            deduped.append(r)

    logger.info(
        "diagnostics.dead_letter_scanned",
        total_found=len(results),
        unique_clinics=len(deduped),
    )
    return {
        "count": len(deduped),
        "results": deduped[:limit],
        "as_of": now.isoformat(),
        "thresholds": {
            "pipeline_frozen_hours": _DEAD_LETTER_GENERATION_HOURS,
            "callback_exhausted_attempts": _CALLBACK_EXHAUSTED_ATTEMPTS,
            "enrichment_abandoned_hours": _DEAD_LETTER_ENRICH_HOURS,
        },
    }


# ── Timeline reconstruction ───────────────────────────────────────────────────

@router.get("/timeline/{clinic_id}")
async def get_timeline(clinic_id: str):
    """
    Reconstruct a chronological incident timeline for a clinic from durable
    database fields. Not full event sourcing — derived from point-in-time
    snapshots stored across clinic_websites, clinics, generation_jobs, and
    clinic_scores.

    Useful for post-incident review and support escalations.
    """
    db = get_supabase()
    events: list[dict] = []

    def _event(ts: str | None, event: str, **extra) -> None:
        if ts:
            events.append({"timestamp": ts, "event": event, **extra})

    # ── clinic_websites row ───────────────────────────────────────────────────
    cw = (
        db.from_("clinic_websites")
        .select(
            "id, status, site_url, subdomain, "
            "current_step, last_step_completed, "
            "step_started_at, step_completed_at, step_failed_at, "
            "failed_at, last_error, live_at, created_at, "
            "vercel_deployment_id, wg_job_id, "
            "callback_ok, callback_attempts, callback_last_error"
        )
        .eq("clinic_id", clinic_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    cw = cw.data[0] if cw.data else None

    if cw:
        _event(cw.get("created_at"), "generation.started",
               wg_job_id=cw.get("wg_job_id"))

        if cw.get("step_started_at") and cw.get("current_step"):
            _event(cw["step_started_at"], "generation.step_started",
                   step=cw["current_step"])

        if cw.get("step_completed_at") and cw.get("last_step_completed"):
            _event(cw["step_completed_at"], "generation.step_completed",
                   step=cw["last_step_completed"])

        if cw.get("vercel_deployment_id") and cw.get("step_completed_at"):
            _event(cw.get("step_completed_at"), "deploy_vercel.completed",
                   vercel_deployment_id=cw["vercel_deployment_id"])

        if cw.get("live_at"):
            _event(cw["live_at"], "generation.pipeline_completed",
                   site_url=cw.get("site_url"),
                   status=cw.get("status"))

        if cw.get("step_failed_at"):
            _event(cw["step_failed_at"], "generation.step_failed",
                   step=cw.get("current_step"),
                   error=(cw.get("last_error") or "")[:200])

        if cw.get("failed_at") and cw.get("status") in ("error", "failed"):
            _event(cw["failed_at"], "generation.failed",
                   step=cw.get("current_step"),
                   error=(cw.get("last_error") or "")[:200])

        # Callback outcome
        if cw.get("live_at"):
            if cw.get("callback_ok") is True:
                _event(cw.get("live_at"), "callback.succeeded",
                       attempts=cw.get("callback_attempts"))
            elif cw.get("callback_ok") is False:
                _event(cw.get("live_at"), "callback.failed",
                       attempts=cw.get("callback_attempts"),
                       error=(cw.get("callback_last_error") or "")[:200])

    # ── generation_jobs rows (up to 5 most recent) ────────────────────────────
    gj_rows = (
        db.from_("generation_jobs")
        .select(
            "id, status, retry_count, failure_reason, "
            "generation_started_at, deployed_at, timeout_at, failed_at"
        )
        .eq("clinic_id", clinic_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )
    for gj in gj_rows.data or []:
        _event(gj.get("generation_started_at"), "generation_job.created",
               job_id=gj.get("id"), retry_count=gj.get("retry_count"))
        if gj.get("deployed_at"):
            _event(gj["deployed_at"], "generation_job.marked_deployed",
                   job_id=gj.get("id"))
        if gj.get("timeout_at"):
            _event(gj["timeout_at"], "generation_job.timed_out",
                   job_id=gj.get("id"))
        if gj.get("failed_at") and gj.get("status") in ("failed", "cancelled"):
            _event(gj["failed_at"], "generation_job.failed",
                   job_id=gj.get("id"),
                   status=gj.get("status"),
                   reason=(gj.get("failure_reason") or "")[:200])

    # ── clinics enrichment state ──────────────────────────────────────────────
    clinic = (
        db.from_("clinics")
        .select("enrichment_status, enrichment_attempted_at, enrichment_error, updated_at")
        .eq("id", clinic_id)
        .limit(1)
        .execute()
    )
    clinic = clinic.data[0] if clinic.data else None

    if clinic:
        if clinic.get("enrichment_attempted_at"):
            enrich_event = (
                "enrichment.completed"
                if clinic.get("enrichment_status") == "enriched"
                else "enrichment.failed"
                if clinic.get("enrichment_status") == "failed"
                else "enrichment.started"
            )
            _event(clinic["enrichment_attempted_at"], enrich_event,
                   status=clinic.get("enrichment_status"),
                   error=(clinic.get("enrichment_error") or None))

    # ── clinic_scores — scoring completion ────────────────────────────────────
    score = (
        db.from_("clinic_scores")
        .select("computed_at, total_score, tier, snapshot_date")
        .eq("clinic_id", clinic_id)
        .order("computed_at", desc=True)
        .limit(1)
        .execute()
    )
    if score.data:
        s = score.data[0]
        _event(s.get("computed_at") or s.get("snapshot_date"), "scoring.completed",
               total_score=s.get("total_score"),
               tier=s.get("tier"))

    # Sort chronologically, put None timestamps last
    events.sort(key=lambda e: e["timestamp"] or "")

    return {
        "clinic_id": clinic_id,
        "event_count": len(events),
        "events": events,
        "note": (
            "Timeline reconstructed from durable DB snapshots. "
            "Intermediate step transitions not recorded unless a crash occurred."
        ),
    }


# ── Ops health ────────────────────────────────────────────────────────────────

@router.get("/health/operations")
async def ops_health():
    """
    Aggregated operational health for the website generation + enrichment pipeline.

    Returns counts, alert list, and WG Redis metrics.
    Use for morning ops checks, dashboards, and alerting thresholds.

    Status:
      healthy  — no known stuck/failed states
      degraded — some broken clinics but recovery systems active
      critical — multiple unrecoverable states or active generation spike
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    stale_gen_cutoff = (now - timedelta(minutes=_STALE_GENERATION_MINUTES)).isoformat()
    dead_gen_cutoff = (now - timedelta(hours=_DEAD_LETTER_GENERATION_HOURS)).isoformat()
    stale_queue_cutoff = (now - timedelta(minutes=_STALE_QUEUE_MINUTES)).isoformat()
    dead_enrich_cutoff = (now - timedelta(hours=_DEAD_LETTER_ENRICH_HOURS)).isoformat()

    # ── Count queries ─────────────────────────────────────────────────────────
    def _count(result) -> int:
        return len(result.data) if result.data else 0

    active = _count(
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["generating", "building", "deploying"])
        .execute()
    )
    stuck = _count(
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["generating", "building", "deploying"])
        .lt("updated_at", stale_gen_cutoff)
        .execute()
    )
    frozen = _count(
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["generating", "building", "deploying"])
        .lt("updated_at", dead_gen_cutoff)
        .execute()
    )
    gen_failed = _count(
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["error", "failed"])
        .execute()
    )
    callback_failed = _count(
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["live", "deployed"])
        .eq("callback_ok", False)
        .gte("callback_attempts", _CALLBACK_EXHAUSTED_ATTEMPTS)
        .execute()
    )
    queued_stale = _count(
        db.from_("clinics")
        .select("id")
        .eq("enrichment_status", "queued")
        .lt("updated_at", stale_queue_cutoff)
        .execute()
    )
    enrich_failed = _count(
        db.from_("clinics")
        .select("id")
        .eq("enrichment_status", "failed")
        .execute()
    )

    # Missing scores: enriched clinics with no clinic_scores row
    enriched_rows = (
        db.from_("clinics")
        .select("id")
        .eq("enrichment_status", "enriched")
        .limit(500)
        .execute()
    )
    missing_scores = 0
    if enriched_rows.data:
        eids = [r["id"] for r in enriched_rows.data]
        scored_rows = (
            db.from_("clinic_scores")
            .select("clinic_id")
            .in_("clinic_id", eids)
            .execute()
        )
        scored_ids = {r["clinic_id"] for r in (scored_rows.data or [])}
        missing_scores = len(eids) - len(scored_ids)

    # Enrichment abandoned (site live >1h, enrichment still pending/queued)
    enrichment_abandoned = 0
    abandoned_rows = (
        db.from_("clinic_websites")
        .select("clinic_id")
        .in_("status", ["live", "deployed"])
        .lt("live_at", dead_enrich_cutoff)
        .execute()
    )
    if abandoned_rows.data:
        aids = [r["clinic_id"] for r in abandoned_rows.data]
        stuck_enrich = (
            db.from_("clinics")
            .select("id")
            .in_("id", aids)
            .in_("enrichment_status", ["pending", "queued"])
            .execute()
        )
        enrichment_abandoned = _count(stuck_enrich)

    # ── WG Redis metrics ──────────────────────────────────────────────────────
    wg_counters: dict = {}
    try:
        from core import metrics as wg_metrics
        wg_counters = wg_metrics.get_all()
    except Exception as exc:
        logger.warning("ops_health.metrics_fetch_failed", error=str(exc))

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts: list[dict] = []

    if frozen > 0:
        alerts.append({
            "severity": "critical",
            "alert": "pipeline_frozen",
            "count": frozen,
            "message": f"{frozen} pipeline(s) frozen >1h — Railway may not restart them. Manual intervention required.",
            "action": "GET /api/generate/diagnostics/dead-letter",
        })
    if callback_failed > 0:
        alerts.append({
            "severity": "critical",
            "alert": "callback_exhausted",
            "count": callback_failed,
            "message": f"{callback_failed} clinic(s) with exhausted callbacks — enrichment permanently blocked.",
            "action": "GET /api/generate/diagnostics/dead-letter",
        })
    if enrichment_abandoned > 0:
        alerts.append({
            "severity": "critical",
            "alert": "enrichment_abandoned",
            "count": enrichment_abandoned,
            "message": f"{enrichment_abandoned} clinic(s) with site live >1h and enrichment stuck — all recovery systems exhausted.",
            "action": "GET /api/generate/diagnostics/dead-letter",
        })
    if stuck > 0:
        alerts.append({
            "severity": "warning",
            "alert": "pipeline_stuck",
            "count": stuck,
            "message": f"{stuck} pipeline(s) stalled >30min — may self-recover or need retry.",
            "action": "GET /api/generate/diagnostics/search?state=stuck",
        })
    if enrich_failed > 0:
        alerts.append({
            "severity": "warning",
            "alert": "enrichment_failed",
            "count": enrich_failed,
            "message": f"{enrich_failed} clinic(s) with failed enrichment.",
            "action": "GET /api/generate/diagnostics/dead-letter",
        })
    if missing_scores > 5:
        alerts.append({
            "severity": "warning",
            "alert": "scoring_backlog",
            "count": missing_scores,
            "message": f"{missing_scores} enriched clinics missing scores — scoring worker may be down.",
            "action": "GET /api/generate/diagnostics/search?state=missing_scores",
        })
    if queued_stale > 0:
        alerts.append({
            "severity": "info",
            "alert": "enrichment_queue_stale",
            "count": queued_stale,
            "message": f"{queued_stale} clinic(s) queued >20min — verify_and_enrich likely exhausted, rescue will retry.",
            "action": "GET /api/generate/diagnostics/search?state=queued_stale",
        })

    # ── Overall status ────────────────────────────────────────────────────────
    critical_alerts = [a for a in alerts if a["severity"] == "critical"]
    warning_alerts = [a for a in alerts if a["severity"] == "warning"]

    if critical_alerts:
        status = "critical"
    elif warning_alerts:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "counts": {
            "active_generations": active,
            "stuck_generations_30min": stuck,
            "frozen_generations_1h": frozen,
            "generation_failures": gen_failed,
            "callback_exhausted": callback_failed,
            "enrichment_failed": enrich_failed,
            "enrichment_abandoned": enrichment_abandoned,
            "queued_stale": queued_stale,
            "missing_scores": missing_scores,
        },
        "alerts": alerts,
        "wg_metrics": wg_counters,
        "as_of": now.isoformat(),
    }


# ── Throughput analytics ──────────────────────────────────────────────────────

@router.get("/health/throughput")
async def pipeline_throughput():
    """
    Pipeline throughput metrics for the last 24h and last 1h.

    Computes:
      - Generation completions and failures (hourly + daily)
      - Average generation duration for completed pipelines (seconds)
      - Deploy success rate (completions / (completions + failures))
      - Callback success rate
      - Active / stuck counts
      - Enrichment and scoring throughput
      - Concurrent pipeline utilisation vs cap

    Use this for daily ops review and SLO tracking. Not suitable as a
    high-frequency polling target — results involve 6–8 Supabase queries.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_1h = (now - timedelta(hours=1)).isoformat()
    stale_gen_cutoff = (now - timedelta(minutes=_STALE_GENERATION_MINUTES)).isoformat()

    # ── Generation completions ────────────────────────────────────────────────
    completed_24h_rows = (
        db.from_("clinic_websites")
        .select("live_at, created_at, callback_ok")
        .in_("status", ["live", "deployed"])
        .gte("live_at", cutoff_24h)
        .execute()
    )
    completed_24h = completed_24h_rows.data or []
    completed_1h = [r for r in completed_24h if (r.get("live_at") or "") >= cutoff_1h]

    # Average generation duration (live_at - created_at) for completed pipelines
    durations: list[float] = []
    for r in completed_24h:
        start = _parse_dt(r.get("created_at"))
        end = _parse_dt(r.get("live_at"))
        if start and end and end > start:
            durations.append((end - start).total_seconds())
    avg_duration_s = round(sum(durations) / len(durations), 1) if durations else None
    p95_duration_s = round(sorted(durations)[int(len(durations) * 0.95)], 1) if len(durations) >= 5 else None

    # Callback success rate
    callbacks_tracked = [r for r in completed_24h if r.get("callback_ok") is not None]
    callback_successes = sum(1 for r in callbacks_tracked if r.get("callback_ok") is True)
    callback_success_rate = (
        round(callback_successes / len(callbacks_tracked) * 100, 1)
        if callbacks_tracked else None
    )

    # ── Generation failures ───────────────────────────────────────────────────
    failed_24h = len((
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["error", "failed"])
        .gte("failed_at", cutoff_24h)
        .execute()
    ).data or [])
    failed_1h = len((
        db.from_("clinic_websites")
        .select("id")
        .in_("status", ["error", "failed"])
        .gte("failed_at", cutoff_1h)
        .execute()
    ).data or [])

    total_attempted_24h = len(completed_24h) + failed_24h
    deploy_success_rate = (
        round(len(completed_24h) / total_attempted_24h * 100, 1)
        if total_attempted_24h > 0 else None
    )

    # ── Active / stuck ────────────────────────────────────────────────────────
    active_rows = (
        db.from_("clinic_websites")
        .select("id, status, updated_at")
        .in_("status", ["generating", "building", "deploying"])
        .execute()
    ).data or []
    active_count = len(active_rows)
    stuck_count = sum(
        1 for r in active_rows
        if (r.get("updated_at") or "") < stale_gen_cutoff
    )

    # ── Enrichment throughput ─────────────────────────────────────────────────
    enriched_24h = len((
        db.from_("clinics")
        .select("id")
        .eq("enrichment_status", "enriched")
        .gte("updated_at", cutoff_24h)
        .execute()
    ).data or [])
    enrich_failed_24h = len((
        db.from_("clinics")
        .select("id")
        .eq("enrichment_status", "failed")
        .gte("updated_at", cutoff_24h)
        .execute()
    ).data or [])
    pending_enrichment = len((
        db.from_("clinics")
        .select("id")
        .in_("enrichment_status", ["pending", "queued"])
        .execute()
    ).data or [])

    # ── Scoring throughput ────────────────────────────────────────────────────
    scored_24h = len((
        db.from_("clinic_scores")
        .select("clinic_id")
        .gte("computed_at", cutoff_24h)
        .execute()
    ).data or [])

    # ── Concurrency utilisation ───────────────────────────────────────────────
    cap = settings.max_concurrent_pipelines
    utilisation_pct = round(active_count / cap * 100) if cap > 0 else None

    logger.info(
        "throughput.queried",
        completed_24h=len(completed_24h),
        failed_24h=failed_24h,
        active=active_count,
        stuck=stuck_count,
    )

    return {
        "as_of": now.isoformat(),
        "generation": {
            "completed_last_24h": len(completed_24h),
            "completed_last_1h": len(completed_1h),
            "failed_last_24h": failed_24h,
            "failed_last_1h": failed_1h,
            "active_now": active_count,
            "stuck_now": stuck_count,
            "avg_duration_seconds": avg_duration_s,
            "p95_duration_seconds": p95_duration_s,
            "deploy_success_rate_pct": deploy_success_rate,
            "callback_success_rate_pct": callback_success_rate,
        },
        "concurrency": {
            "active": active_count,
            "cap": cap,
            "utilisation_pct": utilisation_pct,
            "headroom": max(0, cap - active_count) if cap > 0 else None,
        },
        "enrichment": {
            "completed_last_24h": enriched_24h,
            "failed_last_24h": enrich_failed_24h,
            "pending_queue_depth": pending_enrichment,
        },
        "scoring": {
            "completed_last_24h": scored_24h,
        },
    }


# ── Diagnostics: single clinic ────────────────────────────────────────────────

@router.get("/diagnostics/{clinic_id}")
async def get_diagnostics(clinic_id: str, request: Request):
    """
    Aggregated generation lifecycle diagnostic for a single clinic.
    Operator/admin only — not customer-facing.
    """
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    log = logger.bind(clinic_id=clinic_id, request_id=request_id)
    log.info("diagnostics.requested", clinic_id=clinic_id, request_id=request_id)

    db = get_supabase()
    now = datetime.now(timezone.utc)

    cw_result = (
        db.from_("clinic_websites")
        .select(
            "id, status, site_url, subdomain, "
            "current_step, last_step_completed, "
            "step_started_at, step_completed_at, step_failed_at, "
            "failed_at, last_error, retry_count, wg_job_id, "
            "callback_ok, callback_attempts, callback_last_error, "
            "vercel_deployment_id, vercel_deployment_url, preview_url, "
            "readiness_verified_at, readiness_attempts, "
            "live_at, created_at, updated_at"
        )
        .eq("clinic_id", clinic_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    cw = cw_result.data[0] if cw_result.data else None
    site_id = cw["id"] if cw else None
    wg_job_id = cw.get("wg_job_id") if cw else None

    redis_job: dict | None = None
    if wg_job_id:
        try:
            redis_job = get_job(wg_job_id)
        except Exception as exc:
            log.warning("diagnostics.redis_lookup_failed", wg_job_id=wg_job_id, error=str(exc))

    gj_result = (
        db.from_("generation_jobs")
        .select(
            "id, status, retry_count, wg_response_status, site_url, "
            "failure_reason, generation_started_at, deployed_at, timeout_at, "
            "failed_at, updated_at"
        )
        .eq("clinic_id", clinic_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    gen_job = gj_result.data[0] if gj_result.data else None

    clinic_result = (
        db.from_("clinics")
        .select(
            "id, name, specialty, has_website, website_url, website_domain, "
            "enrichment_status, enrichment_attempted_at, enrichment_error, updated_at"
        )
        .eq("id", clinic_id)
        .limit(1)
        .execute()
    )
    clinic = clinic_result.data[0] if clinic_result.data else None

    score_result = (
        db.from_("clinic_scores")
        .select("total_score, site_score, seo_score, snapshot_date, computed_at")
        .eq("clinic_id", clinic_id)
        .order("computed_at", desc=True)
        .limit(1)
        .execute()
    )
    score = score_result.data[0] if score_result.data else None

    cw_status = cw.get("status") if cw else None
    enrichment_status = clinic.get("enrichment_status") if clinic else None
    callback_ok = cw.get("callback_ok") if cw else None
    current_step = cw.get("current_step") if cw else None
    last_error = cw.get("last_error") if cw else None

    cw_updated = _parse_dt(cw.get("updated_at")) if cw else None
    cw_updated_minutes = _minutes_ago(cw_updated, now)
    generation_stale = (
        cw_status in ("generating", "building", "deploying")
        and cw_updated_minutes is not None
        and cw_updated_minutes > _STALE_GENERATION_MINUTES
    )

    rescued_by_fallback = bool(
        cw_status in ("live", "deployed")
        and callback_ok is False
        and enrichment_status == "queued"
    )

    clinic_updated = _parse_dt(clinic.get("updated_at")) if clinic else None
    clinic_updated_minutes = _minutes_ago(clinic_updated, now)
    stale_queue_detected = bool(
        enrichment_status == "queued"
        and clinic_updated_minutes is not None
        and clinic_updated_minutes > _STALE_QUEUE_MINUTES
    )

    action = _recommended_action(
        cw_status=cw_status,
        current_step=current_step,
        last_error=last_error,
        enrichment_status=enrichment_status,
        callback_ok=callback_ok,
        score_exists=score is not None,
        generation_stale=generation_stale,
        cw_updated_minutes_ago=cw_updated_minutes,
    )

    if cw and enrichment_status:
        if cw_status in ("live", "deployed") and enrichment_status == "pending" and not callback_ok:
            log.warning(
                "diagnostics.inconsistent_state",
                issue="site_live_but_enrichment_pending_and_callback_failed",
                cw_status=cw_status,
                enrichment_status=enrichment_status,
                callback_ok=callback_ok,
            )
        if cw_status in ("live", "deployed") and enrichment_status == "enriched" and not score:
            log.warning(
                "diagnostics.inconsistent_state",
                issue="enriched_but_no_scores",
                cw_status=cw_status,
                enrichment_status=enrichment_status,
            )

    if rescued_by_fallback:
        log.info(
            "diagnostics.recovery_detected",
            rescue_type="callback_failed_but_enrichment_queued",
            clinic_id=clinic_id,
        )

    result = {
        "clinic_id": clinic_id,
        "as_of": now.isoformat(),
        "generation": {
            "site_id": site_id,
            "status": cw_status,
            "current_step": current_step,
            "last_completed_step": cw.get("last_step_completed") if cw else None,
            "retry_count": cw.get("retry_count") if cw else None,
            "started_at": cw.get("created_at") if cw else None,
            "live_at": cw.get("live_at") if cw else None,
            "failed_at": cw.get("failed_at") if cw else None,
            "last_error": last_error,
            "vercel_deployment_id": cw.get("vercel_deployment_id") if cw else None,
            "vercel_deployment_url": cw.get("vercel_deployment_url") if cw else None,
            "callback_ok": callback_ok,
            "callback_attempts": cw.get("callback_attempts") if cw else None,
            "callback_last_error": cw.get("callback_last_error") if cw else None,
            "stale": generation_stale,
            "updated_minutes_ago": cw_updated_minutes,
            "wg_job_id": wg_job_id,
        },
        "redis_job": (
            {
                "found": redis_job is not None,
                "status": redis_job.get("status") if redis_job else None,
                "progress": redis_job.get("progress") if redis_job else None,
                "current_step": redis_job.get("current_step") if redis_job else None,
                "message": redis_job.get("message") if redis_job else None,
                "last_error": redis_job.get("last_error") if redis_job else None,
            }
            if wg_job_id
            else {"found": False, "reason": "no_wg_job_id_in_clinic_websites"}
        ),
        "generation_job": (
            {
                "id": gen_job.get("id"),
                "status": gen_job.get("status"),
                "retry_count": gen_job.get("retry_count"),
                "wg_response_status": gen_job.get("wg_response_status"),
                "failure_reason": gen_job.get("failure_reason"),
                "started_at": gen_job.get("generation_started_at"),
                "deployed_at": gen_job.get("deployed_at"),
                "failed_at": gen_job.get("failed_at"),
                "timeout_at": gen_job.get("timeout_at"),
            }
            if gen_job
            else None
        ),
        "clinic_website": (
            {
                "site_url": cw.get("site_url"),
                "subdomain": cw.get("subdomain"),
                "status": cw_status,
                "live_at": cw.get("live_at"),
            }
            if cw
            else None
        ),
        "enrichment": (
            {
                "status": enrichment_status,
                "has_website": clinic.get("has_website"),
                "website_url": clinic.get("website_url"),
                "last_attempted_at": clinic.get("enrichment_attempted_at"),
                "last_error": clinic.get("enrichment_error"),
                "score_exists": score is not None,
                "score_total": score.get("total_score") if score else None,
                "score_site": score.get("site_score") if score else None,
                "score_seo": score.get("seo_score") if score else None,
                "score_date": score.get("computed_at") if score else None,
                "clinic_updated_minutes_ago": clinic_updated_minutes,
            }
            if clinic
            else None
        ),
        "recovery": {
            "rescued_by_fallback": rescued_by_fallback,
            "stale_queue_detected": stale_queue_detected,
        },
        "recommended_action": action,
    }

    log.info(
        "diagnostics.generated",
        clinic_id=clinic_id,
        site_id=site_id,
        request_id=request_id,
        wg_job_id=wg_job_id,
        cw_status=cw_status,
        enrichment_status=enrichment_status,
        callback_ok=callback_ok,
        recommended_action=action,
    )
    return result


# ── Admin recovery endpoints ──────────────────────────────────────────────────

@router.post("/admin/replay-callback/{clinic_id}")
async def admin_replay_callback(clinic_id: str, request: Request):
    """
    Re-fire the site-activated callback to the workers platform.

    Reads the most recent live/deployed clinic_websites row and re-emits
    the SITE_CREATED event. Useful when the original callback failed due to
    auth errors, network partitions, or wrong workers URL at deploy time.

    Idempotent — safe to call multiple times.
    """
    from pipeline.generation_pipeline import _emit_site_created

    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    log = logger.bind(clinic_id=clinic_id, request_id=request_id)

    db = get_supabase()
    cw = (
        db.from_("clinic_websites")
        .select(
            "id, site_url, subdomain, specialty, clinic_name, "
            "gsc_property_url, status, callback_ok, callback_attempts"
        )
        .eq("clinic_id", clinic_id)
        .in_("status", ["live", "deployed", "error"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not cw.data:
        raise HTTPException(
            status_code=404,
            detail="No live/deployed clinic_websites row found for this clinic",
        )

    row = cw.data[0]
    site_id = row["id"]

    log.info(
        "admin.replay_callback_start",
        site_id=site_id,
        site_url=row.get("site_url"),
        prev_callback_ok=row.get("callback_ok"),
        prev_callback_attempts=row.get("callback_attempts"),
    )

    event = {
        "site_id": site_id,
        "clinic_id": clinic_id,
        "site_url": row.get("site_url", ""),
        "subdomain": row.get("subdomain", ""),
        "specialty": row.get("specialty", "general"),
        "clinic_name": row.get("clinic_name", ""),
        "gsc_property": row.get("gsc_property_url", ""),
    }

    ok = await _emit_site_created(event, site_id=site_id)

    log.info("admin.replay_callback_complete", site_id=site_id, callback_ok=ok)
    return {
        "status": "ok" if ok else "failed",
        "clinic_id": clinic_id,
        "site_id": site_id,
        "callback_ok": ok,
        "message": (
            "Callback sent successfully — enrichment dispatched via workers"
            if ok
            else "Callback failed — check workers URL and WG_SHARED_SECRET env vars"
        ),
    }


@router.post("/admin/reset-stale-pipeline/{clinic_id}")
async def admin_reset_stale_pipeline(clinic_id: str, request: Request):
    """
    Mark a frozen active-status pipeline as 'error' so the idempotency guard
    in POST /api/generate no longer blocks a fresh generation attempt.

    Only acts on rows with status=generating/building/deploying that haven't
    been updated in >30 min. Refuses to reset pipelines that are actively
    progressing to avoid interrupting live runs.
    """
    db = get_supabase()
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    log = logger.bind(clinic_id=clinic_id, request_id=request_id)

    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(minutes=_STALE_GENERATION_MINUTES)).isoformat()
    now_str = now.isoformat()

    result = (
        db.from_("clinic_websites")
        .update({
            "status": "error",
            "last_error": "Reset by operator — pipeline stale with no progress",
            "failed_at": now_str,
            "updated_at": now_str,
        })
        .eq("clinic_id", clinic_id)
        .in_("status", ["generating", "building", "deploying"])
        .lt("updated_at", stale_cutoff)
        .execute()
    )

    reset_count = len(result.data) if result.data else 0
    if reset_count == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "No stale active pipeline found for this clinic. "
                "Either there is no active generation, or the pipeline updated "
                f"within the last {_STALE_GENERATION_MINUTES} minutes (still progressing). "
                "Check GET /api/generate/diagnostics/{clinic_id} for current state."
            ),
        )

    log.warning(
        "admin.stale_pipeline_reset",
        clinic_id=clinic_id,
        rows_reset=reset_count,
        request_id=request_id,
    )
    return {
        "status": "reset",
        "clinic_id": clinic_id,
        "rows_reset": reset_count,
        "message": (
            f"Marked {reset_count} stale pipeline(s) as error. "
            "You may now retry via POST /api/wg/retry-generation/{clinic_id}"
        ),
    }


@router.post("/admin/clear-redis-job/{job_id}")
async def admin_clear_redis_job(job_id: str, request: Request):
    """
    Delete a stale Redis job key (wg_job:{job_id}).

    Use when a crashed pipeline left a Redis key in a terminal state but the
    48-hour TTL hasn't expired yet and the job is cluttering diagnostics.

    This does NOT affect Supabase state — use reset-stale-pipeline for that.
    """
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    log = logger.bind(job_id=job_id, request_id=request_id)

    key = f"wg_job:{job_id}"
    try:
        r = get_redis()
        existed = r.exists(key)
        if not existed:
            raise HTTPException(
                status_code=404,
                detail=f"Redis key {key!r} not found — may have already expired or been cleared",
            )
        r.delete(key)
        log.info("admin.redis_job_cleared", job_id=job_id, key=key)
        return {"status": "deleted", "job_id": job_id, "key": key}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("admin.redis_job_clear_failed", job_id=job_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
