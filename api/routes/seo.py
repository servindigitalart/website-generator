from fastapi import APIRouter, BackgroundTasks, HTTPException
from core.database import get_supabase
from agents.gsc_agent import GSCAgent
from agents.seo_content_agent import SEOContentAgent
from agents.image_agent import ImageAgent
from core.config import settings
import structlog

router = APIRouter(prefix="/api/seo", tags=["seo"])
logger = structlog.get_logger()


async def _run_seo_pipeline(site: dict):
    """
    Weekly SEO pipeline for a single site:
    1. Fetch GSC keyword data + save snapshot
    2. Pick top N keyword opportunities (pos 4-20)
    3. Generate SEO article per keyword
    4. Generate hero image for each article
    """
    site_id = site["id"]
    clinic_id = site["clinic_id"]
    gsc_property = site.get("gsc_property_url", "")
    if not gsc_property:
        logger.warning("seo_pipeline_skipped_no_gsc", site_id=site_id)
        return

    gsc = GSCAgent()
    content_agent = SEOContentAgent()
    img_agent = ImageAgent()

    # 1. Fetch + save keyword snapshot
    keywords = await __import__("asyncio").to_thread(
        gsc.fetch_keyword_data, gsc_property
    )
    await gsc.save_keyword_snapshot(site_id, clinic_id, keywords)

    # 2. Keyword opportunities
    opportunities = gsc.get_keyword_opportunities(keywords)
    target_kws = opportunities[: settings.weekly_articles_count]
    logger.info("seo_pipeline_keywords",
                site_id=site_id, count=len(target_kws))

    # 3. Get clinic context
    clinic_name = site.get("clinic_name", "Our Clinic")
    specialty = site.get("specialty", "general")
    # Extract city from site_url heuristic (e.g. "Austin")
    city = "your city"

    for kw_data in target_kws:
        keyword = kw_data["keyword"]
        related = [k["keyword"] for k in opportunities
                   if k["keyword"] != keyword][:5]
        article = await content_agent.generate_article(
            keyword=keyword,
            specialty=specialty,
            clinic_name=clinic_name,
            city=city,
            brand_dna={},
            related_keywords=related,
        )

        # 4. Hero image for this article
        hero_url = ""
        try:
            prompt = img_agent.get_prompt(specialty, "blog_hero")
            imgs = await img_agent.generate_image(prompt, count=1)
            if imgs:
                hero_url = await img_agent.upload_to_r2(
                    imgs[0], clinic_id, "blog_hero"
                )
        except Exception as e:
            logger.warning("blog_hero_image_failed", error=str(e))

        await content_agent.save_article(
            site_id=site_id,
            clinic_id=clinic_id,
            article=article,
            keyword_position=kw_data["position"],
            hero_image_url=hero_url,
        )
        logger.info("seo_article_saved",
                    site_id=site_id, keyword=keyword, slug=article["slug"])

    # Update last_seo_run
    from datetime import datetime, timezone
    get_supabase().from_("clinic_websites").update({
        "last_seo_run": datetime.now(timezone.utc).isoformat(),
    }).eq("id", site_id).execute()


@router.post("/run/{site_id}")
async def run_seo_pipeline(site_id: str, background_tasks: BackgroundTasks):
    """Manually trigger weekly SEO pipeline for a site."""
    result = get_supabase().from_("clinic_websites") \
        .select("*").eq("id", site_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Site not found")
    background_tasks.add_task(_run_seo_pipeline, result.data)
    return {
        "triggered": True,
        "site_id": site_id,
        "message": "SEO pipeline started",
    }


@router.get("/keywords/{site_id}")
async def get_keywords(site_id: str, days: int = 30):
    """Get GSC keyword data for a site"""
    result = get_supabase().from_("gsc_keyword_snapshots") \
        .select("*") \
        .eq("site_id", site_id) \
        .order("snapshot_date", desc=True) \
        .limit(200) \
        .execute()
    return {"keywords": result.data or []}


@router.get("/articles/{site_id}")
async def get_articles(site_id: str):
    """Get all generated SEO articles for a site"""
    result = get_supabase().from_("clinic_seo_articles") \
        .select("*") \
        .eq("site_id", site_id) \
        .order("published_at", desc=True) \
        .execute()
    return {"articles": result.data or []}
