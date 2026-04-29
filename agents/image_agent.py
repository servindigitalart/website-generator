"""
ImageAgent — generates premium medical clinic images using
Google Gemini Imagen 3.0 API and stores them in Cloudflare R2.

Uses specialty-specific prompt templates from skills/medical_image_prompts.md
to generate images that look like professional photography, not AI stock.
"""
from google import genai
from google.genai import types
from core.config import settings
from core.database import get_supabase
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
import boto3, uuid, structlog, asyncio
from datetime import datetime, timezone

logger = structlog.get_logger()

# Load image prompt skills
SKILLS_DIR = Path(__file__).parent.parent / "skills"
IMAGE_PROMPTS_SKILL = (SKILLS_DIR / "medical_image_prompts.md").read_text()

# Prompt templates by specialty and section
IMAGE_PROMPTS = {
    "dermatology": {
        "hero": (
            "Confident woman with clear glowing skin, modern luxury clinic "
            "reception with marble surfaces and soft plants, diffused natural "
            "window light from left, calm confident serene mood, editorial "
            "beauty photography, Canon 5D, 85mm f/1.8, ultra sharp, 8K"
        ),
        "services": (
            "Close-up of healthy radiant skin texture, minimalist white "
            "background, soft diffused studio lighting, clinical yet beautiful, "
            "medical editorial photography, macro lens, 8K"
        ),
        "team": (
            "Professional female dermatologist in white coat with stethoscope, "
            "modern clinical background softly blurred, warm genuine smile, "
            "natural window light from left, LinkedIn professional portrait, "
            "Sony A7R, 50mm, sharp focus on face"
        ),
        "about": (
            "Modern dermatology clinic interior, reception area with white "
            "marble, soft warm lighting, elegant minimal decor with single "
            "orchid, architectural interior photography, wide angle"
        ),
        "testimonials": (
            "Soft abstract bokeh in warm cream and purple tones, "
            "suitable for text overlay, professional studio photography, "
            "minimal medical aesthetic background"
        ),
        "blog_hero": (
            "Dermatologist consulting patient at desk, genuine warm interaction, "
            "modern bright clinic with natural light, documentary style, "
            "trust and expertise visible, candid authentic"
        ),
    },
    "orthopedics": {
        "hero": (
            "Active fit man in his 40s hiking mountain trail with confidence, "
            "dramatic mountain vista background, golden hour warm light, "
            "motion blur on background sharp on subject, inspirational "
            "lifestyle sports photography, 8K, wide angle"
        ),
        "services": (
            "Physical therapy session, male therapist helping patient with "
            "knee exercise, bright modern clinic with equipment, natural light, "
            "hopeful determined expressions, documentary medical photography"
        ),
        "team": (
            "Male orthopedic surgeon in blue scrubs, hospital corridor "
            "background with soft depth of field, confident professional "
            "posture, arms crossed, clean clinical lighting, medical portrait"
        ),
        "about": (
            "State-of-the-art orthopedic surgery suite, clean and modern, "
            "professional medical equipment, bright clinical lighting, "
            "architectural medical photography"
        ),
        "testimonials": (
            "Abstract soft bokeh in navy blue and orange tones, "
            "professional background suitable for testimonial text overlay"
        ),
        "blog_hero": (
            "Doctor reviewing x-ray with patient, collaborative moment, "
            "modern medical office, bright natural light, documentary style"
        ),
    },
    "dental": {
        "hero": (
            "Beautiful genuine wide smile of diverse woman in her 30s, "
            "perfect natural white teeth, warm bright dental office background "
            "softly blurred, warm natural lighting, friendly approachable mood, "
            "lifestyle photography, Canon R5, 85mm, 8K"
        ),
        "services": (
            "Modern dental chair in bright clean treatment room, "
            "teal and white color scheme, natural light through window, "
            "professional dental office interior photography"
        ),
        "team": (
            "Friendly female dentist with warm genuine smile wearing "
            "white coat and gloves, dental equipment in background, "
            "approachable patient-centered portrait, warm clinic lighting"
        ),
        "about": (
            "Modern dental reception area, bright white and teal decor, "
            "comfortable seating, warm welcoming atmosphere, "
            "interior architectural photography"
        ),
        "testimonials": (
            "Soft abstract bokeh in teal and white tones, "
            "clean fresh aesthetic, background for dental testimonial"
        ),
        "blog_hero": (
            "Dentist educating patient about oral health, tablet showing "
            "dental xray, warm professional interaction, bright clinic"
        ),
    },
    "med_spa": {
        "hero": (
            "Elegant woman receiving luxury facial treatment at medical spa, "
            "dark moody dramatic background, single soft light source from "
            "above highlighting her face, aspirational beauty editorial, "
            "Vogue magazine aesthetic, Hasselblad quality, 8K"
        ),
        "services": (
            "Luxury aesthetics treatment room, marble surfaces, gold accents, "
            "soft warm amber lighting, premium medical spa interior, "
            "editorial luxury lifestyle photography, moody dark tones"
        ),
        "team": (
            "Medical aesthetician in elegant black uniform, luxury spa "
            "background with dark tones and gold accents, sophisticated "
            "professional portrait, dramatic editorial lighting, "
            "Harper Bazaar style"
        ),
        "about": (
            "Luxury medical spa lobby, dark walls with gold accents, "
            "marble floors, dramatic lighting, ultra-premium interior design, "
            "architectural photography"
        ),
        "testimonials": (
            "Abstract dark bokeh with gold light points, luxury editorial "
            "background, suitable for testimonial overlay"
        ),
        "blog_hero": (
            "Medical director consulting patient about aesthetic treatment, "
            "luxury consultation room, professional intimate setting, "
            "editorial documentary style"
        ),
    },
    "general": {
        "hero": (
            "Diverse family with doctor in modern clinic, warm professional "
            "interaction, bright natural light, welcoming community healthcare, "
            "documentary medical photography"
        ),
        "services": (
            "Modern medical examination room, clean professional equipment, "
            "bright natural lighting, medical interior photography"
        ),
        "team": (
            "Friendly doctor in white coat with stethoscope, warm smile, "
            "modern clinic background, professional medical portrait"
        ),
        "about": (
            "Modern medical clinic reception, clean professional design, "
            "warm welcoming atmosphere, interior photography"
        ),
        "testimonials": (
            "Soft abstract bokeh in blue and teal tones, "
            "professional medical background for testimonial"
        ),
        "blog_hero": (
            "Doctor and patient consultation, warm professional interaction, "
            "modern clinic, documentary style photography"
        ),
    },
}


class ImageAgent:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.r2 = (
            boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint,
                aws_access_key_id=settings.r2_access_key,
                aws_secret_access_key=settings.r2_secret_key,
                region_name="auto",
            )
            if settings.r2_endpoint
            else None
        )

    def get_prompt(
        self,
        specialty: str,
        section: str,
        brand_colors: list[str] = None,
        style_hints: str = "",
    ) -> str:
        """Get optimized image prompt for specialty + section."""
        key = specialty.lower().replace(" ", "_").replace("-", "_")
        prompts = IMAGE_PROMPTS.get(key, IMAGE_PROMPTS["general"])
        base_prompt = prompts.get(section, prompts.get("hero", ""))

        if brand_colors:
            color_hint = f"Color palette hints: {', '.join(brand_colors[:3])}"
            base_prompt = f"{base_prompt}, {color_hint}"

        if style_hints:
            base_prompt = f"{base_prompt}, {style_hints}"

        return base_prompt

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
    )
    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        count: int = 2,
    ) -> list[bytes]:
        """
        Generate images using Gemini Imagen 3.0.
        Returns list of image bytes.
        """
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_images,
                model=settings.imagen_model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=min(count, 4),
                    aspect_ratio=aspect_ratio,
                    safety_filter_level="block_only_high",
                    person_generation="allow_adult",
                ),
            )
            images = []
            for img in response.generated_images:
                if hasattr(img.image, "image_bytes"):
                    images.append(img.image.image_bytes)
                elif hasattr(img.image, "data"):
                    images.append(img.image.data)
            return images
        except Exception as e:
            logger.error("imagen_generation_failed",
                         error=str(e), prompt=prompt[:100])
            raise

    async def upload_to_r2(
        self,
        image_bytes: bytes,
        clinic_id: str,
        section: str,
        index: int = 0,
    ) -> str:
        """Upload image to Cloudflare R2. Returns public URL."""
        if not self.r2:
            logger.warning("r2_not_configured")
            return ""

        key = f"sites/{clinic_id}/{section}/{uuid.uuid4()}.jpg"
        try:
            await asyncio.to_thread(
                self.r2.put_object,
                Bucket=settings.r2_bucket,
                Key=key,
                Body=image_bytes,
                ContentType="image/jpeg",
                CacheControl="public, max-age=31536000",
            )
            endpoint = settings.r2_endpoint.rstrip("/")
            public_url = f"{endpoint}/{settings.r2_bucket}/{key}"
            return public_url
        except Exception as e:
            logger.error("r2_upload_failed", error=str(e), key=key)
            return ""

    async def save_to_db(
        self,
        site_id: str,
        clinic_id: str,
        section: str,
        page: str,
        prompt: str,
        public_url: str,
        r2_key: str = "",
        alt_text: str = "",
    ) -> str:
        """Save generated image record to clinic_site_images table"""
        result = (
            get_supabase()
            .from_("clinic_site_images")
            .insert(
                {
                    "clinic_id": clinic_id,
                    "site_id": site_id,
                    "section": section,
                    "page": page,
                    "prompt_used": prompt,
                    "r2_key": r2_key,
                    "public_url": public_url,
                    "alt_text": alt_text or f"{section} image",
                    "approved": False,
                }
            )
            .execute()
        )
        return result.data[0]["id"] if result.data else ""

    async def generate_section_images(
        self,
        site_id: str,
        clinic_id: str,
        specialty: str,
        sections: list[str],
        brand_colors: list[str] = None,
        count_per_section: int = 2,
    ) -> dict[str, list[str]]:
        """
        Generate images for multiple sections of a site.
        Returns {section: [public_url, ...]}
        """
        results = {}
        aspect_map = {
            "hero": "16:9",
            "services": "4:3",
            "team": "3:4",
            "about": "16:9",
            "testimonials": "16:9",
            "blog_hero": "16:9",
        }

        for section in sections:
            try:
                prompt = self.get_prompt(specialty, section, brand_colors)
                aspect = aspect_map.get(section, "16:9")

                image_bytes_list = await self.generate_image(
                    prompt=prompt,
                    aspect_ratio=aspect,
                    count=count_per_section,
                )

                section_urls = []
                for i, img_bytes in enumerate(image_bytes_list):
                    public_url = await self.upload_to_r2(
                        img_bytes, clinic_id, section, i
                    )
                    if public_url:
                        await self.save_to_db(
                            site_id=site_id,
                            clinic_id=clinic_id,
                            section=section,
                            page="generated",
                            prompt=prompt,
                            public_url=public_url,
                            alt_text=f"{specialty} {section} image",
                        )
                        section_urls.append(public_url)

                results[section] = section_urls
                logger.info("section_images_generated",
                            section=section, count=len(section_urls))

                # Rate limit pause between sections
                await asyncio.sleep(2)

            except Exception as e:
                logger.error("section_image_failed",
                             section=section, error=str(e))
                results[section] = []

        return results
