"""
Weekly SEO automation runner — called by GitHub Actions cron every Monday.

Usage:
    python automation/weekly_seo_runner.py

For every live, GSC-verified clinic site:
  1. Fetch GSC keyword data
  2. Generate SEO articles via Gemini (stored to clinic_seo_articles)
  3. Publish pending articles to the live Vercel site via PublishAgent
     (pulls R2 source, injects MDX, rebuilds, redeploys, pings IndexNow)
  4. Stamp last_seo_run

All log events carry run_id for end-to-end traceability in Railway logs.
"""
import asyncio, sys, uuid, structlog
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import setup_logging
from core.database import get_supabase
from agents.gsc_agent import GSCAgent
from agents.seo_content_agent import SEOContentAgent
from agents.image_agent import ImageAgent
from agents.publish_agent import PublishAgent
from core.config import settings
from datetime import datetime, timezone, timedelta

setup_logging()
logger = structlog.get_logger()


async def should_run_today(site: dict) -> bool:
    last_run = site.get("last_seo_run")
    if not last_run:
        return True
    last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - last_dt > timedelta(days=6)


async def run_site_seo(site: dict, run_id: str) -> dict:
    """
    Run the full SEO pipeline for a single site.
    Returns a summary dict for the run report.
    """
    site_id = site["id"]
    clinic_id = site["clinic_id"]
    gsc_property = site.get("gsc_property_url", "")

    log = logger.bind(run_id=run_id, site_id=site_id,
                      clinic=site.get("clinic_name"))

    summary = {
        "site_id": site_id,
        "clinic": site.get("clinic_name"),
        "articles_generated": 0,
        "articles_published": 0,
        "errors": [],
    }

    if not gsc_property:
        log.info("skip_no_gsc")
        summary["errors"].append("no_gsc_property")
        return summary

    gsc = GSCAgent()
    content_agent = SEOContentAgent()
    img_agent = ImageAgent()

    # ── Step 1: Pull GSC keyword data ─────────────────────────────────────────
    try:
        keywords = await asyncio.to_thread(gsc.fetch_keyword_data, gsc_property)
    except Exception as exc:
        log.error("gsc_fetch_failed", error=str(exc))
        summary["errors"].append(f"gsc_fetch: {exc}")
        return summary

    await gsc.save_keyword_snapshot(site_id, clinic_id, keywords)

    opportunities = gsc.get_keyword_opportunities(keywords)
    targets = opportunities[: settings.weekly_articles_count]
    log.info("targets_selected", count=len(targets))

    if not targets:
        log.info("no_keyword_opportunities")

    clinic_name = site.get("clinic_name", "Our Clinic")
    specialty = site.get("specialty", "general")
    city = site.get("city") or "your city"

    # ── Step 2: Generate articles ──────────────────────────────────────────────
    for kw_data in targets:
        keyword = kw_data["keyword"]
        related = [k["keyword"] for k in opportunities if k["keyword"] != keyword][:5]
        try:
            article = await content_agent.generate_article(
                keyword=keyword,
                specialty=specialty,
                clinic_name=clinic_name,
                city=city,
                brand_dna={},
                related_keywords=related,
            )
        except Exception as exc:
            log.error("article_gen_failed", keyword=keyword, error=str(exc))
            summary["errors"].append(f"gen:{keyword}: {exc}")
            continue

        hero_url = ""
        try:
            prompt = img_agent.get_prompt(specialty, "blog_hero")
            imgs = await img_agent.generate_image(prompt, count=1)
            if imgs:
                hero_url = await img_agent.upload_to_r2(imgs[0], clinic_id, "blog_hero")
        except Exception as exc:
            log.warning("blog_hero_failed", error=str(exc))

        try:
            await content_agent.save_article(
                site_id=site_id,
                clinic_id=clinic_id,
                article=article,
                keyword_position=kw_data["position"],
                hero_image_url=hero_url,
            )
            summary["articles_generated"] += 1
            log.info("article_saved", keyword=keyword, slug=article["slug"])
        except Exception as exc:
            # Likely a duplicate slug — skip
            log.warning("article_save_failed",
                        slug=article.get("slug"), error=str(exc))
            summary["errors"].append(f"save:{keyword}: {exc}")
            continue

        await asyncio.sleep(3)  # Respect Gemini rate limits

    # ── Step 3: Publish all pending articles to live site ─────────────────────
    publish_agent = PublishAgent()
    try:
        pub_result = await publish_agent.publish_pending_articles(site)
        summary["articles_published"] = pub_result["published"]
        if pub_result.get("error"):
            summary["errors"].append(f"publish: {pub_result['error']}")
        log.info("publish_result",
                 published=pub_result["published"],
                 skipped=pub_result["skipped"])
    except Exception as exc:
        log.error("publish_exception", error=str(exc))
        summary["errors"].append(f"publish_exception: {exc}")

    # ── Step 4: Stamp last_seo_run ────────────────────────────────────────────
    get_supabase().from_("clinic_websites").update({
        "last_seo_run": datetime.now(timezone.utc).isoformat(),
    }).eq("id", site_id).execute()

    log.info("site_seo_complete",
             generated=summary["articles_generated"],
             published=summary["articles_published"],
             errors=len(summary["errors"]))
    return summary


async def main():
    run_id = uuid.uuid4().hex[:12]
    log = logger.bind(run_id=run_id)
    log.info("weekly_seo_runner_start")

    result = (
        get_supabase()
        .from_("clinic_websites")
        .select("*")
        .eq("status", "live")
        .eq("gsc_verified", True)
        .execute()
    )
    sites = result.data or []
    log.info("live_sites_found", count=len(sites))

    due = [s for s in sites if await should_run_today(s)]
    log.info("sites_due_for_seo", count=len(due))

    all_summaries = []
    for site in due:
        log.info("processing_site", site_id=site["id"],
                 clinic=site.get("clinic_name"))
        summary = await run_site_seo(site, run_id)
        all_summaries.append(summary)

    total_generated = sum(s["articles_generated"] for s in all_summaries)
    total_published = sum(s["articles_published"] for s in all_summaries)
    total_errors = sum(len(s["errors"]) for s in all_summaries)

    log.info("weekly_seo_runner_complete",
             sites_processed=len(due),
             articles_generated=total_generated,
             articles_published=total_published,
             total_errors=total_errors)

    # Non-zero exit code causes GitHub Actions to mark run as failed
    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
