"""
ClinicWebsite — tracks a generated and deployed site.
Stored in Supabase clinic_websites table.
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from models.generation_package import WebsiteGenerationPackage


class ClinicWebsite(BaseModel):
    id: str = ""
    clinic_id: str
    clinic_name: str = ""
    specialty: str = "general"
    template_used: str = ""

    # URLs
    subdomain: str = ""            # austin-derm
    site_url: str = ""             # https://austin-derm.medplatform.io
    custom_domain: str = ""        # https://austinderm.com (upgrade)
    preview_url: str = ""          # Vercel preview URL

    # Vercel
    vercel_project_id: str = ""
    vercel_deployment_id: str = ""

    # GSC
    gsc_property_url: str = ""
    gsc_verified: bool = False
    gsc_sitemap_submitted: bool = False
    indexnow_key: str = ""

    # Status
    status: str = "pending"
    # pending → generating → building → deploying → live → error

    # SEO
    last_seo_run: Optional[datetime] = None
    total_articles_generated: int = 0
    last_ranking_check: Optional[datetime] = None

    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    live_at: Optional[datetime] = None


class GenerateRequest(BaseModel):
    """Request to generate a new website"""
    clinic_id: str
    specialty: str = "general"
    # Option A: provide URL to analyze
    clinic_url: str = ""
    # Option B: provide pre-built package (from ux-analyzer)
    package: Optional[WebsiteGenerationPackage] = None
    # Customization
    custom_subdomain: str = ""     # override auto-generated subdomain
    target_pages: list[str] = [
        "home", "services", "team",
        "about", "contact", "insurance", "patient-info"
    ]
    generate_images: bool = True
    auto_deploy: bool = True
    setup_gsc: bool = True


class GenerateResponse(BaseModel):
    job_id: str
    status: str
    clinic_id: str
    poll_url: str
    estimated_minutes: int = 5
