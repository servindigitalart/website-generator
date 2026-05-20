import json

import redis as _redis_lib

from core.config import settings

JOB_TTL = 60 * 60 * 48  # 48 hours

# Module-level pool — one connection pool for the entire process lifetime.
# redis-py's ConnectionPool is thread-safe and asyncio-safe when used with
# blocking=True (the default). Creating a new from_url() on every call
# was spawning an unbounded number of short-lived connections under load.
_pool = _redis_lib.ConnectionPool.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=10,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_redis() -> _redis_lib.Redis:
    """Return a Redis client backed by the shared module-level pool."""
    return _redis_lib.Redis(connection_pool=_pool)


def set_job(job_id: str, data: dict) -> None:
    get_redis().setex(f"wg_job:{job_id}", JOB_TTL, json.dumps(data, default=str))


def get_job(job_id: str) -> dict | None:
    raw = get_redis().get(f"wg_job:{job_id}")
    return json.loads(raw) if raw else None


def update_job(job_id: str, updates: dict) -> None:
    """Merge `updates` into the existing job dict (single round-trip via pipeline)."""
    r = get_redis()
    key = f"wg_job:{job_id}"
    raw = r.get(key)
    existing = json.loads(raw) if raw else {}
    existing.update(updates)
    r.setex(key, JOB_TTL, json.dumps(existing, default=str))
