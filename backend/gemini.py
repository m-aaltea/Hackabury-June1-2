import asyncio
import json
import os
from functools import lru_cache

from google import genai
from google.genai import types

_PASS_TYPES = ("Membership Card", "Event Pass", "Loyalty Card", "Supporter Card", "Member ID")

_FALLBACK_COLOURS = {"primary": "#1a1a1a", "secondary": "#ffffff", "text": "#ffffff"}

_PROMPT = """\
You are a digital pass design expert. Produce a JSON object for a digital wallet pass preview.

## Website Data
Title: {title}
Description: {description}
Logo URL: {logo_url}
Theme colour: {theme_color}
Dominant image colours: {image_colors}
Body text snippet: {body_text}

## Instructions
1. Infer brand_name from the title and body text. If the body text says "use your knowledge", rely on what you know about that brand.
2. Set logo_url to the provided Logo URL if it looks like a valid image (png, jpg, webp, svg, ico), otherwise null.
3. Choose primary, secondary, and text hex colours that match this brand. Use the theme/image colours if available; otherwise use your knowledge of the brand's real colours.
4. Classify pass_type as exactly one of: "Membership Card", "Event Pass", "Loyalty Card", "Supporter Card", "Member ID".
5. Produce exactly 4 field objects with realistic label and value pairs for this brand (e.g. Member ID, Tier, Points, Expiry, Store, Club). Use your knowledge of the brand if scraped data is sparse.
6. Write a tagline of at most 8 words capturing what this pass represents.
7. Set confidence_score between 0.0 and 1.0 reflecting extraction quality.

Return ONLY a JSON object with exactly these keys:
{{
  "brand_name": "string",
  "logo_url": "string or null",
  "colours": {{"primary": "#hex", "secondary": "#hex", "text": "#hex"}},
  "pass_type": "one of the five types",
  "fields": [{{"label": "string", "value": "string"}}],
  "tagline": "string",
  "confidence_score": 0.0
}}
"""


def _build_prompt(scraped: dict) -> str:
    return _PROMPT.format(
        title=scraped.get("title") or "(none)",
        description=scraped.get("description") or "(none)",
        logo_url=scraped.get("logo_url") or "(none)",
        theme_color=scraped.get("theme_color") or "(none)",
        image_colors=", ".join(scraped.get("image_colors") or []) or "(none)",
        body_text=scraped.get("body_text") or "(none)",
    )


def _validate(data: dict) -> dict:
    required = {"brand_name", "logo_url", "colours", "pass_type", "fields", "tagline", "confidence_score"}
    if not required.issubset(data.keys()):
        raise ValueError(f"missing keys: {required - data.keys()}")
    colours = data["colours"]
    if not {"primary", "secondary", "text"}.issubset(colours.keys()):
        raise ValueError("missing colour keys")
    if data["pass_type"] not in _PASS_TYPES:
        raise ValueError(f"invalid pass_type: {data['pass_type']}")
    return data


def _fallback(scraped: dict) -> dict:
    brand_name = scraped.get("title") or ""
    return {
        "brand_name": brand_name,
        "logo_url": scraped.get("logo_url"),
        "colours": _FALLBACK_COLOURS,
        "pass_type": "Membership Card",
        "fields": [
            {"label": "Member", "value": brand_name or "Member"},
            {"label": "ID", "value": "000-123-456"},
            {"label": "Tier", "value": "Standard"},
            {"label": "Expires", "value": "Dec 2026"},
        ],
        "tagline": "Member pass",
        "confidence_score": 0.0,
    }


@lru_cache(maxsize=1)
def _parameter_api_key() -> str | None:
    """Load the production key once per warm Lambda environment."""
    parameter_name = os.getenv("GEMINI_PARAMETER_NAME")
    if not parameter_name:
        return None

    import boto3

    response = boto3.client("ssm").get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )
    return response["Parameter"]["Value"]


async def analyse(scraped: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key and os.getenv("GEMINI_PARAMETER_NAME"):
        try:
            api_key = await asyncio.to_thread(_parameter_api_key)
        except Exception as exc:
            print(f"[gemini] unable to load API key from SSM: {exc.__class__.__name__}")

    if not api_key:
        print("[gemini] GEMINI_API_KEY missing, using fallback")
        return _fallback(scraped)

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(scraped)

    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            ),
            timeout=15,
        )
        data = json.loads(response.text)
        return _validate(data)
    except Exception as exc:
        print(f"[gemini] error={exc.__class__.__name__} message={exc} using fallback")
        return _fallback(scraped)
