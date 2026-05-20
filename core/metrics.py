"""
Lightweight operational counters backed by Redis INCR — WG service.

Same pattern as workers/core/metrics.py. Keys live under "wg_metrics:" prefix
in Redis DB 1 (WG's Redis database, isolated from workers' DB 0).

incr() is fire-and-forget — any Redis error is swallowed and logged so a
metrics failure never affects the main pipeline flow.

Counter names:
  wg_generation_started_total      — pipeline entered
  wg_generation_completed_total    — pipeline completed successfully
  wg_generation_failed_total       — pipeline caught an unhandled exception
  wg_step_failed_total             — a single named step raised an exception
  wg_build_failed_total            — npm build subprocess failed
  wg_vercel_timeout_total          — Vercel deployment did not reach READY in time
  wg_callback_success_total        — site-activated callback returned 2xx
  wg_callback_4xx_total            — site-activated callback returned 4xx (config error)
  wg_callback_exhausted_total      — all 3 retry attempts failed
  wg_readiness_dispatched_total    — verify_and_enrich task dispatched to workers
"""
import logging
from typing import Any

_log = logging.getLogger(__name__)
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        from core.config import settings
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def incr(name: str, amount: int = 1) -> None:
    """Atomically increment counter. Never raises."""
    try:
        _get_redis().incr(f"wg_metrics:{name}", amount)
    except Exception as exc:
        _log.debug("wg_metrics.incr_failed key=%s error=%r", name, exc)


def get_all() -> dict[str, int]:
    """Return all WG metric counters as {name: count}."""
    try:
        r = _get_redis()
        keys = r.keys("wg_metrics:*")
        if not keys:
            return {}
        values = r.mget(keys)
        return {
            k.removeprefix("wg_metrics:"): int(v or 0)
            for k, v in zip(keys, values)
        }
    except Exception as exc:
        _log.warning("wg_metrics.get_all_failed error=%r", exc)
        return {}
