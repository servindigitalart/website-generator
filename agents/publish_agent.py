"""
PublishAgent — deploys pending SEO articles to live Vercel sites.

Called weekly by weekly_seo_runner.py after article generation.

Flow per site:
1. Query clinic_seo_articles WHERE indexnow_sent=false AND site_id=<id>
2. Pull source archive from R2 into a temp build dir
3. Write each article's MDX into src/content/blog/{slug}.mdx
4. npm install + npm run build
5. Deploy dist/ to existing Vercel project (no domain re-add needed)
6. Update source archive in R2 with new content
7. Mark each article: published_at=now, indexed_at=now, indexnow_sent=true
8. Ping IndexNow for each new article URL
9. Clean up temp build dir
10. Update clinic_websites.total_articles_generated counter

Idempotent: articles with indexnow_sent=true are never re-processed.
"""
import asyncio, shutil, structlog
from datetime import datetime, timezone
from pathlib import Path

import httpx

from agents.deploy_agent import DeployAgent
from core.config import settings
from core.database import get_supabase

logger = structlog.get_logger()

BUILDS_DIR = Path(__file__).parent.parent / "builds"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


class PublishAgent:

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def publish_pending_articles(self, site: dict) -> dict:
        """
        Publish all pending (indexnow_sent=false) articles for a site.
        Returns {"published": int, "skipped": int, "error": str|None}.
        """
        site_id = site["id"]
        clinic_id = site["clinic_id"]
        subdomain = site.get("subdomain", "")
        site_url = site.get("site_url", "")
        indexnow_key = site.get("indexnow_key", "")

        log = logger.bind(site_id=site_id, clinic=site.get("clinic_name"))

        # 1. Find articles awaiting deployment
        articles = self._fetch_pending_articles(site_id)
        if not articles:
            log.info("no_pending_articles")
            return {"published": 0, "skipped": 0, "error": None}

        log.info("pending_articles_found", count=len(articles))

        # 2. Pull source from R2
        build_dir = BUILDS_DIR / f"publish-{site_id[:8]}"
        try:
            deploy_agent = DeployAgent()
            await deploy_agent.download_source_from_r2(
                clinic_id, site_id, build_dir
            )
        except Exception as exc:
            log.error("source_pull_failed", error=str(exc))
            return {"published": 0, "skipped": len(articles), "error": str(exc)}

        published_count = 0
        try:
            # 3. Inject MDX files
            blog_dir = build_dir / "src" / "content" / "blog"
            blog_dir.mkdir(parents=True, exist_ok=True)
            for article in articles:
                mdx_path = blog_dir / f"{article['slug']}.mdx"
                mdx_path.write_text(article["content_mdx"])
                log.info("mdx_injected", slug=article["slug"])

            # 4. Build
            dist_dir = await deploy_agent.build_site(build_dir)

            # 5. Deploy to existing Vercel project (project already exists)
            project_name = f"{settings.vercel_project_prefix}{subdomain}"
            await deploy_agent.deploy_to_vercel(dist_dir, project_name)
            log.info("vercel_redeployed", project=project_name)

            # 6. Update source archive in R2
            await deploy_agent.upload_source_to_r2(build_dir, clinic_id, site_id)

            # 7. Mark articles as published + 8. IndexNow
            now = datetime.now(timezone.utc).isoformat()
            article_urls = []
            for article in articles:
                self._mark_published(article["id"], now)
                article_urls.append(f"{site_url}/blog/{article['slug']}")
                published_count += 1

            if article_urls and indexnow_key and site_url:
                await self._ping_indexnow(site_url, indexnow_key, article_urls)

            # 9. Update total_articles_generated counter
            self._increment_article_count(site_id, published_count)

            log.info("publish_complete", published=published_count)
            return {"published": published_count, "skipped": 0, "error": None}

        except Exception as exc:
            log.error("publish_failed", error=str(exc), published_so_far=published_count)
            return {
                "published": published_count,
                "skipped": len(articles) - published_count,
                "error": str(exc),
            }
        finally:
            # 9. Always clean up temp build dir
            await deploy_agent.cleanup_build_dir(build_dir)

    # ------------------------------------------------------------------
    # Supabase helpers
    # ------------------------------------------------------------------

    def _fetch_pending_articles(self, site_id: str) -> list[dict]:
        result = (
            get_supabase()
            .from_("clinic_seo_articles")
            .select("id, slug, content_mdx")
            .eq("site_id", site_id)
            .eq("indexnow_sent", False)
            .execute()
        )
        return result.data or []

    def _mark_published(self, article_id: str, now: str) -> None:
        get_supabase().from_("clinic_seo_articles").update({
            "published_at": now,
            "indexed_at": now,
            "indexnow_sent": True,
            "gsc_sitemap_updated": True,
        }).eq("id", article_id).execute()

    def _increment_article_count(self, site_id: str, count: int) -> None:
        # Use a raw RPC to increment atomically; fall back to read-modify-write
        try:
            get_supabase().rpc(
                "increment_article_count",
                {"p_site_id": site_id, "p_amount": count},
            ).execute()
        except Exception:
            # Graceful fallback: read then write
            row = (
                get_supabase()
                .from_("clinic_websites")
                .select("total_articles_generated")
                .eq("id", site_id)
                .single()
                .execute()
            )
            current = (row.data or {}).get("total_articles_generated", 0) or 0
            get_supabase().from_("clinic_websites").update({
                "total_articles_generated": current + count,
            }).eq("id", site_id).execute()

    # ------------------------------------------------------------------
    # IndexNow
    # ------------------------------------------------------------------

    async def _ping_indexnow(
        self, site_url: str, key: str, urls: list[str]
    ) -> None:
        """
        Notify IndexNow (Bing/Yandex) about newly published article URLs.
        Non-fatal — failure is logged but does not abort the publish flow.
        """
        host = site_url.replace("https://", "").replace("http://", "").rstrip("/")
        payload = {
            "host": host,
            "key": key,
            "keyLocation": f"{site_url}/{key}.txt",
            "urlList": urls,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    INDEXNOW_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code in (200, 202):
                    logger.info("indexnow_ping_sent", urls=len(urls), host=host)
                else:
                    logger.warning(
                        "indexnow_ping_non_200",
                        status=r.status_code, body=r.text[:200],
                    )
        except Exception as exc:
            logger.warning("indexnow_ping_failed", error=str(exc))
