import redis
import json
from core.config import settings


def get_redis():
    return redis.from_url(settings.redis_url, decode_responses=True)


JOB_TTL = 60 * 60 * 48  # 48 hours


def set_job(job_id: str, data: dict):
    r = get_redis()
    r.setex(f"wg_job:{job_id}", JOB_TTL, json.dumps(data, default=str))


def get_job(job_id: str) -> dict | None:
    r = get_redis()
    raw = r.get(f"wg_job:{job_id}")
    return json.loads(raw) if raw else None


def update_job(job_id: str, updates: dict):
    existing = get_job(job_id) or {}
    existing.update(updates)
    set_job(job_id, existing)
