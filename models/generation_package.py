"""
WebsiteGenerationPackage — received from ux-analyzer.
This is the input to the website generator.
"""
from pydantic import BaseModel
from typing import Optional


class DoctorProfile(BaseModel):
    name: str
    title: str = ""
    specialty: str = ""
    bio: str = ""
    photo_url: str = ""
    credentials: list[str] = []


class ServiceDetail(BaseModel):
    name: str
    description: str = ""
    page_slug: str = ""
    is_featured: bool = False


class PageContent(BaseModel):
    title: str
    meta_description: str = ""
    h1: str
    sections: list[dict] = []
    schema_markup: dict = {}


class BrandDNA(BaseModel):
    brand_name: str
    tagline: str = ""
    tone: str = "professional"
    personality: str = ""
    primary_color: str = "#007AE6"
    secondary_color: str = "#0056B3"
    accent_color: str = "#00D4AA"
    font_display: str = "DM Sans"
    font_body: str = "Inter"
    hero_headline: str = ""
    hero_subtext: str = ""
    main_cta: str = "Book a Consultation"
    differentiators: list[str] = []
    emotional_promise: str = ""
    patient_type: str = ""


class DesignSystem(BaseModel):
    tailwind_config: dict = {}
    css_variables: dict = {}
    color_tokens: dict = {}
    typography_tokens: dict = {}
    google_fonts_import: str = ""
    animation_config: dict = {}
    component_styles: dict = {}


class WebsiteGenerationPackage(BaseModel):
    clinic_id: str
    clinic_url: str
    specialty: str = "general"
    generated_at: str = ""
    brand_dna: BrandDNA
    design_system: DesignSystem
    doctors: list[DoctorProfile] = []
    services: list[ServiceDetail] = []
    phone: str = ""
    address: str = ""
    hours: str = ""
    email: str = ""
    logo_url: str = ""
    favicon_url: str = ""
    pages: dict[str, PageContent] = {}
    component_library: dict = {}
    premium_features_detected: list[str] = []
    original_ux_score: int = 0
    original_issues: list[str] = []
    recommended_template: str = "general"
    raw_crawl_summary: dict = {}


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
