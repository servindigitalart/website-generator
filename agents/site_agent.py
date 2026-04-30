"""
SiteAgent — takes a WebsiteGenerationPackage and produces
a ready-to-build Astro site by:
1. Selecting the correct template
2. Injecting design tokens into global.css
3. Injecting content into site.json
4. Injecting Google Fonts into Layout.astro
5. Injecting GSC verification meta tag
6. Injecting IndexNow key
7. Injecting schema markup defaults
"""
import google.generativeai as genai
from core.config import settings
from models.generation_package import WebsiteGenerationPackage
from pathlib import Path
import json, shutil, re, structlog
from datetime import datetime

logger = structlog.get_logger()

TEMPLATE_MAP = {
    "dermatology": "dermatology",
    "orthopedics": "orthopedics",
    "dental": "dental",
    "med_spa": "med-spa",
    "med-spa": "med-spa",
    "medspa": "med-spa",
    "general": "general",
    "family_medicine": "general",
    "internal_medicine": "general",
    "pediatrics": "general",
}

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
BUILDS_DIR = Path(__file__).parent.parent / "builds"


class SiteAgent:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)

    def select_template(self, specialty: str) -> str:
        """Map specialty string to template directory name"""
        key = specialty.lower().replace(" ", "_")
        return TEMPLATE_MAP.get(key, "general")

    def generate_subdomain(self, clinic_name: str, clinic_id: str) -> str:
        """
        Generate URL-safe subdomain from clinic name.
        'Austin Dermatology Associates' → 'austin-dermatology-associates'
        Truncate to 40 chars. Append last 4 chars of clinic_id if collision
        would occur (handled at DB level).
        """
        slug = re.sub(r"[^a-z0-9\s-]", "", clinic_name.lower())
        slug = re.sub(r"\s+", "-", slug.strip())
        slug = re.sub(r"-+", "-", slug)
        slug = slug[:40].rstrip("-")
        return slug or f"clinic-{clinic_id[:8]}"

    async def prepare_site(
        self,
        package: WebsiteGenerationPackage,
        build_dir: Path,
        gsc_verification_token: str = "",
        indexnow_key: str = "",
    ) -> Path:
        """
        Copy template to build_dir and inject all content.
        Returns path to the prepared build directory.
        """
        template_name = self.select_template(package.specialty)
        template_dir = TEMPLATES_DIR / template_name

        if not template_dir.exists():
            logger.error("template_not_found", template=template_name)
            template_dir = TEMPLATES_DIR / "general"

        # 1. Copy template to build dir
        if build_dir.exists():
            shutil.rmtree(build_dir)
        shutil.copytree(template_dir, build_dir)
        logger.info("template_copied", template=template_name, dest=str(build_dir))

        # 2. Inject design tokens
        self._inject_design_tokens(build_dir, package)

        # 3. Inject content
        self._inject_content(build_dir, package)

        # 4. Inject Google Fonts
        self._inject_fonts(build_dir, package)

        # 5. Inject GSC verification
        if gsc_verification_token:
            self._inject_gsc_verification(build_dir, gsc_verification_token)

        # 6. Inject IndexNow key
        if indexnow_key:
            self._inject_indexnow_key(build_dir, indexnow_key)

        # 7. Update astro.config.mjs with site URL
        subdomain = self.generate_subdomain(
            package.brand_dna.brand_name, package.clinic_id
        )
        site_url = f"https://{subdomain}.{settings.base_domain}"
        self._inject_site_url(build_dir, site_url)

        logger.info("site_prepared",
                    clinic_id=package.clinic_id, template=template_name)
        return build_dir

    def _inject_design_tokens(
        self, build_dir: Path, package: WebsiteGenerationPackage
    ):
        """Update :root CSS variables from brand_dna and design_system"""
        css_path = build_dir / "src" / "styles" / "global.css"
        if not css_path.exists():
            return

        dna = package.brand_dna
        ds = package.design_system

        tokens = {
            "--color-brand-primary": dna.primary_color or "#007AE6",
            "--color-brand-secondary": dna.secondary_color or "#0056B3",
            "--color-brand-accent": dna.accent_color or "#00D4AA",
            "--font-display": f"'{dna.font_display}'",
            "--font-body": f"'{dna.font_body}'",
        }

        if ds.css_variables:
            tokens.update(ds.css_variables)

        css_content = css_path.read_text()

        for prop, value in tokens.items():
            pattern = rf"({re.escape(prop)}:\s*)([^;]+)(;)"
            replacement = rf"\g<1>{value}\3"
            css_content = re.sub(pattern, replacement, css_content)

        css_path.write_text(css_content)

    def _inject_content(
        self, build_dir: Path, package: WebsiteGenerationPackage
    ):
        """Write WebsiteGenerationPackage data to src/content/site.json"""
        content_path = build_dir / "src" / "content" / "site.json"
        content_path.parent.mkdir(parents=True, exist_ok=True)

        dna = package.brand_dna
        site_data = {
            "clinic_name": dna.brand_name,
            "tagline": dna.tagline,
            "specialty": package.specialty,
            "phone": package.phone,
            "address": package.address,
            "email": package.email,
            "hours": package.hours,
            "logo_url": package.logo_url,
            "favicon_url": package.favicon_url,
            "hero_headline": dna.hero_headline
            or f"Expert {package.specialty.title()} Care",
            "hero_subtext": dna.hero_subtext or dna.tagline,
            "main_cta": dna.main_cta,
            "secondary_cta": "Our Services",
            "tone": dna.tone,
            "differentiators": dna.differentiators,
            "emotional_promise": dna.emotional_promise,
            "doctors": [d.model_dump() for d in package.doctors],
            "services": [s.model_dump() for s in package.services],
            "pages": {k: v.model_dump() for k, v in package.pages.items()},
            "generated_at": package.generated_at,
            "stats": {
                "patients_treated": "5,000+",
                "years_experience": "15+",
                "board_certified": "Yes",
                "satisfaction_rate": "98%",
            },
        }

        content_path.write_text(json.dumps(site_data, indent=2, default=str))

    def _inject_fonts(
        self, build_dir: Path, package: WebsiteGenerationPackage
    ):
        """Update Google Fonts import URL in Layout.astro."""
        layout_path = build_dir / "src" / "layouts" / "Layout.astro"
        if not layout_path.exists():
            return

        ds = package.design_system
        if ds.google_fonts_import:
            fonts_url = ds.google_fonts_import
        else:
            display = package.brand_dna.font_display.replace(" ", "+")
            body = package.brand_dna.font_body.replace(" ", "+")
            fonts_url = (
                f"https://fonts.googleapis.com/css2?"
                f"family={display}:wght@400;600;700"
                f"&family={body}:wght@400;500;600&display=swap"
            )

        layout = layout_path.read_text()
        font_tag = f'<link href="{fonts_url}" rel="stylesheet">'
        if "fonts.googleapis.com" in layout:
            layout = re.sub(
                r'<link href="https://fonts\.googleapis\.com[^"]*"[^>]*>',
                font_tag,
                layout,
            )
        else:
            layout = layout.replace(
                "<!-- Fonts injected at build time -->",
                f"<!-- Fonts injected at build time -->\n  {font_tag}",
            )
        layout_path.write_text(layout)

    def _inject_gsc_verification(self, build_dir: Path, token: str):
        """Inject Google verification meta tag into Layout.astro"""
        layout_path = build_dir / "src" / "layouts" / "Layout.astro"
        if not layout_path.exists():
            return
        layout = layout_path.read_text()
        meta_tag = f'<meta name="google-site-verification" content="{token}" />'
        layout = layout.replace(
            "<!-- Google Verification injected at build time -->", meta_tag
        )
        layout_path.write_text(layout)

    def _inject_indexnow_key(self, build_dir: Path, key: str):
        """Write IndexNow key to public directory as {key}.txt"""
        public_dir = build_dir / "public"
        public_dir.mkdir(exist_ok=True)
        key_file = public_dir / f"{key}.txt"
        key_file.write_text(key)

        env_file = build_dir / ".env"
        env_content = env_file.read_text() if env_file.exists() else ""
        if "PUBLIC_INDEXNOW_KEY" not in env_content:
            with env_file.open("a") as f:
                f.write(f"\nPUBLIC_INDEXNOW_KEY={key}\n")

    def _inject_site_url(self, build_dir: Path, site_url: str):
        """Update astro.config.mjs with the real site URL for sitemap"""
        config_path = build_dir / "astro.config.mjs"
        if not config_path.exists():
            return
        config = config_path.read_text()
        if "site:" not in config:
            config = config.replace(
                "export default defineConfig({",
                f"export default defineConfig({{\n  site: '{site_url}',",
            )
        else:
            config = re.sub(r"site:\s*'[^']*'", f"site: '{site_url}'", config)
        config_path.write_text(config)
