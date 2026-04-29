from fastapi import APIRouter, HTTPException
from core.database import get_supabase
import structlog

router = APIRouter(prefix="/api/sites", tags=["sites"])
logger = structlog.get_logger()


@router.get("")
async def list_sites(clinic_id: str = None, status: str = None):
    """List all generated sites, optionally filtered"""
    query = get_supabase().from_("clinic_websites").select("*")
    if clinic_id:
        query = query.eq("clinic_id", clinic_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).execute()
    return {"sites": result.data or []}


@router.get("/{site_id}")
async def get_site(site_id: str):
    result = get_supabase().from_("clinic_websites") \
        .select("*").eq("id", site_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Site not found")
    return result.data


@router.patch("/{site_id}/status")
async def update_site_status(site_id: str, status: str):
    """Update site status (admin use)"""
    result = get_supabase().from_("clinic_websites") \
        .update({"status": status}) \
        .eq("id", site_id).execute()
    return {"updated": True, "status": status}
