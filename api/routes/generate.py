from fastapi import APIRouter, BackgroundTasks, HTTPException
from models.generation_package import GenerateRequest, GenerateResponse
from core.redis_client import set_job, get_job, update_job
from pipeline.generation_pipeline import run_pipeline
import uuid
import structlog

router = APIRouter(prefix="/api/generate", tags=["generation"])
logger = structlog.get_logger()


@router.post("", response_model=GenerateResponse)
async def generate_website(
    req: GenerateRequest,
    background_tasks: BackgroundTasks
):
    """
    Start website generation pipeline.
    Returns job_id immediately — poll /status/{job_id}
    """
    job_id = str(uuid.uuid4())
    set_job(job_id, {
        "status": "queued",
        "job_id": job_id,
        "clinic_id": req.clinic_id,
        "specialty": req.specialty,
        "progress": 0,
    })
    background_tasks.add_task(run_pipeline, job_id, req)
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
        raise HTTPException(
            status_code=202,
            detail=f"Not ready: {job.get('status')}"
        )
    return job.get("result")
