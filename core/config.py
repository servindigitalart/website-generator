from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Service
    service_name: str = "website-generator"
    port: int = 8006
    environment: str = "development"
    debug: bool = True

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/1"

    # Google / Gemini
    gemini_api_key: str = ""
    google_service_account_json: str = ""
    gsc_property_prefix: str = "sc-domain:"

    # Cloudflare R2
    r2_endpoint: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = "medplatform-sites"

    # Vercel
    vercel_token: str = ""
    vercel_team_id: str = ""
    vercel_project_prefix: str = "clinic-"

    # Domain
    base_domain: str = "medplatform.io"

    # IndexNow
    indexnow_key: str = ""

    # UX Analyzer
    ux_analyzer_url: str = "http://localhost:8002"

    # B2B Prospector Workers
    workers_url: str = "http://localhost:8000"

    # Image generation
    imagen_model: str = "imagen-3.0-generate-001"
    images_per_section: int = 2

    # SEO automation
    weekly_articles_count: int = 2
    min_keyword_position: int = 4
    max_keyword_position: int = 20

    # Cost tracking
    gemini_cost_per_1k_tokens: float = 0.000075

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
