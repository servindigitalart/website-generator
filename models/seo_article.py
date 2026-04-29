from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SEOArticle(BaseModel):
    id: str = ""
    clinic_id: str
    site_id: str
    title: str
    slug: str
    keyword_target: str
    keyword_position_before: Optional[float] = None
    keyword_position_after: Optional[float] = None
    content_mdx: str = ""
    meta_description: str = ""
    published_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None
    indexnow_sent: bool = False
    gsc_sitemap_updated: bool = False
    clicks_7d: int = 0
    impressions_7d: int = 0
    created_at: Optional[datetime] = None
