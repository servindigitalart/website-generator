"""
SEOContentAgent — generates SEO-optimized blog articles
from GSC keyword opportunities. Runs weekly via GitHub Action.
"""
import google.generativeai as genai
from core.config import settings
from core.database import get_supabase
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
import json, structlog, asyncio, re, uuid
from datetime import datetime, timezone

logger = structlog.get_logger()

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SEO_PATTERNS = (SKILLS_DIR / "seo_content_patterns.md").read_text()


class SEOContentAgent:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self._model = genai.GenerativeModel(
            "gemini-2.0-flash",
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=4096,
                temperature=0.4,
            ),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
    )
    async def generate_article(
        self,
        keyword: str,
        specialty: str,
        clinic_name: str,
        city: str,
        brand_dna: dict,
        related_keywords: list[str] = None,
    ) -> dict:
        """
        Generate a complete SEO-optimized MDX article.

        Returns:
        {
            title, slug, meta_description, content_mdx,
            schema_faq, internal_links, word_count
        }
        """
        tone = brand_dna.get("tone", "professional")
        differentiators = brand_dna.get("differentiators", [])

        prompt = f"""
You are an expert medical content writer for {clinic_name}, a {specialty}
clinic in {city}. Write a complete SEO-optimized blog article.

TARGET KEYWORD: "{keyword}"
RELATED KEYWORDS TO INCLUDE: {json.dumps(related_keywords or [])}
CLINIC NAME: {clinic_name}
CITY: {city}
SPECIALTY: {specialty}
TONE: {tone}
CLINIC DIFFERENTIATORS: {json.dumps(differentiators)}

CONTENT GUIDELINES:
{SEO_PATTERNS}

OUTPUT FORMAT — Return ONLY valid JSON, no markdown:
{{
  "title": "Article title with keyword (60 chars max)",
  "slug": "url-friendly-slug",
  "meta_description": "155 char meta description with keyword",
  "intro": "150-word introduction paragraph",
  "sections": [
    {{
      "heading": "H2 heading",
      "content": "Section content (200-300 words)",
      "is_faq": false
    }}
  ],
  "faq": [
    {{"question": "FAQ question?", "answer": "Answer (50-80 words)"}},
    {{"question": "FAQ question?", "answer": "Answer (50-80 words)"}},
    {{"question": "FAQ question?", "answer": "Answer (50-80 words)"}},
    {{"question": "FAQ question?", "answer": "Answer (50-80 words)"}}
  ],
  "cta_headline": "CTA headline",
  "cta_body": "Short CTA paragraph",
  "word_count": 1400,
  "internal_link_suggestions": ["/services", "/team", "/contact"]
}}

REQUIREMENTS:
- Include keyword "{keyword}" in H1, first paragraph, and 1-2 H2s
- Include clinic name and city naturally throughout
- 1400-1800 words total
- Medical accuracy — do not make specific medical claims
- HIPAA safe — no patient data examples
- Include local SEO signals (city name, local context)
"""
        response = await asyncio.to_thread(self._model.generate_content, [prompt])

        text = response.text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        article_data = json.loads(text)

        mdx = self._build_mdx(article_data, keyword, clinic_name, city)
        article_data["content_mdx"] = mdx

        return article_data

    def _build_mdx(
        self, data: dict, keyword: str, clinic_name: str, city: str
    ) -> str:
        """Assemble MDX article from structured data"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        faq_schema = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["answer"],
                        },
                    }
                    for faq in data.get("faq", [])
                ],
            },
            indent=2,
        )

        sections_md = ""
        for section in data.get("sections", []):
            sections_md += f"\n## {section['heading']}\n\n{section['content']}\n"

        faq_md = "\n## Frequently Asked Questions\n\n"
        for faq in data.get("faq", []):
            faq_md += f"### {faq['question']}\n\n{faq['answer']}\n\n"

        mdx = f"""---
title: "{data['title']}"
slug: "{data['slug']}"
date: "{today}"
metaDescription: "{data['meta_description']}"
keyword: "{keyword}"
clinic: "{clinic_name}"
city: "{city}"
schema: |
{chr(10).join('  ' + line for line in faq_schema.split(chr(10)))}
---

# {data['title']}

{data.get('intro', '')}
{sections_md}
{faq_md}
## Ready to Learn More?

{data.get('cta_body', f'Contact {clinic_name} today to schedule your consultation.')}

[Book a Consultation](/contact) | [Meet Our Team](/team)
"""
        return mdx

    async def save_article(
        self,
        site_id: str,
        clinic_id: str,
        article: dict,
        keyword_position: float,
        hero_image_url: str = "",
    ) -> str:
        """Save article to clinic_seo_articles table"""
        result = (
            get_supabase()
            .from_("clinic_seo_articles")
            .insert(
                {
                    "clinic_id": clinic_id,
                    "site_id": site_id,
                    "title": article["title"],
                    "slug": article["slug"],
                    "keyword_target": article.get("slug", ""),
                    "keyword_position_before": keyword_position,
                    "content_mdx": article["content_mdx"],
                    "meta_description": article["meta_description"],
                    "hero_image_url": hero_image_url,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .execute()
        )
        return result.data[0]["id"] if result.data else ""
