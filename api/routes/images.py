from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from core.database import get_supabase
from agents.image_agent import ImageAgent
import structlog

router = APIRouter(prefix="/api/images", tags=["images"])
logger = structlog.get_logger()


class ImageRequest(BaseModel):
    site_id: str
    clinic_id: str
    specialty: str
    section: str       # hero|services|team|about|blog_hero
    page: str          # home|services|about|etc
    brand_colors: list[str] = []
    style_hints: str = ""
    count: int = 2


async def _run_image_generation(req: ImageRequest):
    agent = ImageAgent()
    prompt = agent.get_prompt(
        req.specialty, req.section, req.brand_colors, req.style_hints
    )
    image_bytes_list = await agent.generate_image(
        prompt=prompt, count=req.count
    )
    urls = []
    for i, img_bytes in enumerate(image_bytes_list):
        url = await agent.upload_to_r2(img_bytes, req.clinic_id, req.section, i)
        if url:
            await agent.save_to_db(
                site_id=req.site_id,
                clinic_id=req.clinic_id,
                section=req.section,
                page=req.page,
                prompt=prompt,
                public_url=url,
                alt_text=f"{req.specialty} {req.section} image",
            )
            urls.append(url)
    logger.info("images_generated",
                site_id=req.site_id, section=req.section, count=len(urls))


@router.post("/generate")
async def generate_images(req: ImageRequest, background_tasks: BackgroundTasks):
    """Generate images for a specific site section."""
    background_tasks.add_task(_run_image_generation, req)
    return {
        "queued": True,
        "site_id": req.site_id,
        "section": req.section,
        "message": "Image generation started"
    }


@router.get("/{site_id}")
async def get_site_images(site_id: str, section: str = None):
    query = get_supabase().from_("clinic_site_images") \
        .select("*").eq("site_id", site_id)
    if section:
        query = query.eq("section", section)
    result = query.order("created_at", desc=True).execute()
    return {"images": result.data or []}


@router.patch("/{image_id}/approve")
async def approve_image(image_id: str):
    """Account manager approves an image for the site"""
    get_supabase().from_("clinic_site_images") \
        .update({"approved": True}).eq("id", image_id).execute()
    return {"approved": True, "image_id": image_id}
