"""
Weekly SEO automation runner — called by GitHub Actions cron.

Usage:
    python automation/weekly_seo_runner.py

Iterates over all live clinic_websites and triggers the SEO
pipeline for each one.
"""
import asyncio, sys, structlog
from pathlib import Path

# Make sure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import setup_logging
from core.database import get_supabase
from agents.gsc_agent import GSCAgent
from agents.seo_content_agent import SEOContentAgent
from agents.image_agent import ImageAgent
from core.config import settings
from datetime import datetime, timezone, timedelta

setup_logging()
logger = structlog.get_logger()


async def should_run_today(site: dict) -> bool:
    """
    Only run for sites that haven't had an SEO pass in the last 6 days,
    to avoid double-running if cron fires twice.
    """
    last_run = site.get("last_seo_run")
    if not last_run:
        return True
    last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last_dt > timedelta(days=6)


async def run_site_seo(site: dict):
    site_id = site["id"]
    clinic_id = site["clinic_id"]
    gsc_property = site.get("gsc_property_url", "")
    if not gsc_property:
        logger.info("skip_no_gsc", site_id=site_id)
        return

    gsc = GSCAgent()
    content_agent = SEOContentAgent()
    img_agent = ImageAgent()

    # 1. Keywords
    try:
        keywords = await asyncio.to_thread(
            gsc.fetch_keyword_data, gsc_property
        )
    except Exception as e:
        logger.error("gsc_fetch_failed", site_id=site_id, error=str(e))
        return

    await gsc.save_keyword_snapshot(site_id, clinic_id, keywords)

    opportunities = gsc.get_keyword_opportunities(keywords)
    targets = opportunities[: settings.weekly_articles_count]
    logger.info("targets_selected",
                site_id=site_id, count=len(targets))
    if not targets:
        logger.info("no_opportunities", site_id=site_id)
        return

    clinic_name = site.get("clinic_name", "Our Clinic")
    specialty = site.get("specialty", "general")
    city = "your city"  # TODO: store city in clinic_websites

    for kw_data in targets:
        keyword = kw_data["keyword"]
        related = [k["keyword"] for k in opportunities
                   if k["keyword"] != keyword][:5]
        try:
            article = await content_agent.generate_article(
                keyword=keyword,
                specialty=specialty,
                clinic_name=clinic_name,
                city=city,
                brand_dna={},
                related_keywords=related,
            )
        except Exception as e:
            logger.error("article_gen_failed",
                         site_id=site_id, keyword=keyword, error=str(e))
            continue

        hero_url = ""
        try:
            prompt = img_agent.get_prompt(specialty, "blog_hero")
            imgs = await img_agent.generate_image(prompt, count=1)
            if imgs:
                hero_url = await img_agent.upload_to_r2(
                    imgs[0], clinic_id, "blog_hero"
                )
        except Exception as e:
            logger.warning("blog_hero_failed",
                           site_id=site_id, error=str(e))

        try:
            await content_agent.save_article(
                site_id=site_id,
                clinic_id=clinic_id,
                article=article,
                keyword_position=kw_data["position"],
                hero_image_url=hero_url,
            )
        except Exception as e:
            # Likely a duplicate slug — skip
            logger.warning("article_save_failed",
                           site_id=site_id, slug=article.get("slug"),
                           error=str(e))
            continue

        logger.info("article_published",
                    site_id=site_id, keyword=keyword, slug=article["slug"])

        await asyncio.sleep(3)  # Be polite to Gemini rate limits

    # Update last_seo_run
    get_supabase().from_("clinic_websites").update({
        "last_seo_run": datetime.now(timezone.utc).isoformat(),
    }).eq("id", site_id).execute()


async def main():
    logger.info("weekly_seo_runner_start")
    result = (
        get_supabase()
        .from_("clinic_websites")
        .select("*")
        .eq("status", "live")
        .eq("gsc_verified", True)
        .execute()
    )
    sites = result.data or []
    logger.info("live_sites_found", count=len(sites))

    # Filter to sites due for a run
    due = [s for s in sites if await should_run_today(s)]
    logger.info("sites_due_for_seo", count=len(due))

    # Run sequentially (avoid API rate limits)
    for site in due:
        logger.info("processing_site",
                    site_id=site["id"],
                    clinic=site.get("clinic_name"))
        await run_site_seo(site)

    logger.info("weekly_seo_runner_complete",
                total_sites=len(due))


if __name__ == "__main__":
    asyncio.run(main())
