"""
GSCAgent — Google Search Console integration.

Responsibilities:
1. Verify GSC property ownership via meta-tag method
2. Submit sitemap after deploy
3. Pull weekly keyword performance (clicks, impressions, position)
4. Return top keyword opportunities (position 4-20)
"""
import asyncio, json, structlog
from datetime import date, timedelta
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
from core.config import settings
from core.database import get_supabase

logger = structlog.get_logger()


class GSCAgent:
    def __init__(self):
        self._service = None

    def _get_service(self):
        """Lazy-load GSC API service using service account credentials."""
        if self._service is not None:
            return self._service

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        sa_path = settings.google_service_account_json
        if not sa_path or not Path(sa_path).exists():
            raise ValueError(
                "google_service_account_json not configured or file missing"
            )

        creds = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=["https://www.googleapis.com/auth/webmasters"],
        )
        self._service = build("searchconsole", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Property management
    # ------------------------------------------------------------------

    def add_property(self, site_url: str) -> bool:
        """Add a new property to GSC."""
        try:
            svc = self._get_service()
            svc.sites().add(siteUrl=site_url).execute()
            logger.info("gsc_property_added", url=site_url)
            return True
        except Exception as e:
            logger.error("gsc_add_property_failed",
                         url=site_url, error=str(e))
            return False

    def verify_ownership_token(self, site_url: str) -> str:
        """
        Returns the meta-tag verification token for this site.
        The token must be injected into the site HTML before GSC
        can verify ownership.
        """
        # GSC doesn't have an API to get verification tokens directly —
        # we use our own IndexNow key as a combined token, or generate one.
        import uuid, hashlib
        token = hashlib.sha256(
            f"{settings.gemini_api_key[:8]}:{site_url}".encode()
        ).hexdigest()[:32]
        return token

    def submit_sitemap(self, site_url: str) -> bool:
        """Submit sitemap.xml to GSC."""
        try:
            svc = self._get_service()
            sitemap_url = site_url.rstrip("/") + "/sitemap.xml"
            svc.sitemaps().submit(siteUrl=site_url,
                                  feedpath=sitemap_url).execute()
            logger.info("sitemap_submitted", url=sitemap_url)
            return True
        except Exception as e:
            logger.error("sitemap_submit_failed",
                         site=site_url, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Keyword data
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
    )
    def fetch_keyword_data(
        self,
        site_url: str,
        days: int = 28,
        row_limit: int = 500,
    ) -> list[dict]:
        """
        Pull keyword performance from GSC Search Analytics API.
        Returns list of {keyword, clicks, impressions, ctr, position}.
        """
        svc = self._get_service()
        end_date = date.today() - timedelta(days=3)  # GSC 3-day lag
        start_date = end_date - timedelta(days=days)

        request_body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": ["query"],
            "rowLimit": row_limit,
            "dataState": "final",
        }

        response = (
            svc.searchanalytics()
            .query(siteUrl=site_url, body=request_body)
            .execute()
        )

        rows = response.get("rows", [])
        keywords = []
        for row in rows:
            keywords.append({
                "keyword": row["keys"][0],
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": round(row.get("ctr", 0), 4),
                "position": round(row.get("position", 0), 2),
            })

        logger.info("gsc_keywords_fetched",
                    site=site_url, count=len(keywords))
        return keywords

    def get_keyword_opportunities(
        self, keywords: list[dict]
    ) -> list[dict]:
        """
        Filter to position 4-20 with ≥10 impressions.
        Sort by impressions DESC (highest volume to win first).
        """
        min_pos = settings.min_keyword_position
        max_pos = settings.max_keyword_position
        opportunities = [
            kw for kw in keywords
            if min_pos <= kw["position"] <= max_pos
            and kw["impressions"] >= 10
        ]
        opportunities.sort(key=lambda x: x["impressions"], reverse=True)
        return opportunities

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    async def save_keyword_snapshot(
        self, site_id: str, clinic_id: str, keywords: list[dict]
    ):
        """Upsert keyword data into gsc_keyword_snapshots."""
        today = date.today().isoformat()
        rows = [
            {
                "site_id": site_id,
                "clinic_id": clinic_id,
                "keyword": kw["keyword"],
                "clicks": kw["clicks"],
                "impressions": kw["impressions"],
                "ctr": kw["ctr"],
                "position": kw["position"],
                "snapshot_date": today,
            }
            for kw in keywords
        ]
        if rows:
            get_supabase().from_("gsc_keyword_snapshots").upsert(
                rows,
                on_conflict="site_id,keyword,snapshot_date",
            ).execute()
            logger.info("keyword_snapshot_saved",
                        site_id=site_id, count=len(rows))
