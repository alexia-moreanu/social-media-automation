"""Caption writer: asks Claude for a caption for one image."""

import base64
import io
import json
import os
from pathlib import Path

import requests
from PIL import Image

from . import voice

MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"
ROOT = Path(__file__).resolve().parent.parent

PILLARS = {
    "promo": "Promo — spaces, event types, seasonal offers, weekday vs weekend, how to book",
    "educational": "Educational — practical tips people save (planning a party, checklists, ideas)",
    "mood": "Aesthetic / mood — garden, pools, willows, lights, details, Lola the dog and the cats",
    "story": "Our story — built by the family since 2013, behind the scenes (facts from about_ro.md only)",
}

PROMPT = """You write Instagram/Facebook captions for Happy Place, a family-run event venue
in Domnești, Ilfov. Your captions must sound like a real Romanian person from the Bucharest
area wrote them — not like marketing copy, and not like a translation.

Below are the brand guide and the source texts written by the family. Never invent facts
that are not in them.

<brand_guide>
{brand_guide}
</brand_guide>

<family_texts>
{about}
</family_texts>

Today is {today}. Seasonal focus: {season}.
Content pillar for this post: {pillar}
The attached photo is what will be posted. Only mention things actually visible in it.

## Language
- ONE caption, in Romanian. Never write a separate English version or translate yourself.
- Sprinkle in the English words Romanians actually use in speech when they fit naturally:
  venue, outdoor, indoor, vibe, team building, save the date, setup, brunch, open air,
  sunset, weekend, full, review, tips. Use them because that is how people talk, not as decoration.
  Two or three per caption is plenty; zero is fine if none fit.
- Natural spoken register: short sentences, contractions, the way a friend texts you.
  Diacritics always.

## Length
- ONE paragraph. Roughly 25–60 words. No line breaks inside the caption.
- The hook line is the opening of that same paragraph, not a separate line.

## What makes a caption good here
- Give the reader something concrete they did not know: a real detail, number, date,
  practical tip, or an honest behind-the-scenes fact. Every caption must earn its place.
  Useful facts available to you: 11:00–22:00, what is included
  (veselă, pahare, grătar, scaune, espressor, frigider), capacities (60 / 40–50 / 30),
  the three cottages and what each is best for, weekday vs weekend differences,
  team buildings / cursuri / grupuri get a personalised offer.
- Say the thing plainly. If the photo shows a baptism setup, talk about what actually
  goes into one, not about how magical the light is.

## Never
- NO PRICES. Not per person, not packages, not "de la ... €". Prices are given by phone,
  WhatsApp or DM so the offer can be personalised. This rule has no exceptions.

## Banned (this is what "cringe" means here)
- Generic filler questions that could sit under any photo. A question is welcome when it is
  specific to this photo or genuinely worth answering.
- Clichés: "colț de rai", "magie", "povestea ta", "momente de neuitat", "locul perfect",
  "atmosferă de vis", "zâmbete", "amintiri prețioase".
- Describing the obvious contents of the photo back to the viewer — they can see it.
- Emoji clutter. At most 1–2, and only where a person would actually use one.
- Exclamation marks everywhere. Usually zero or one.
- Announcing the feeling the reader should have ("veți fi încântați").

Return strict JSON, nothing else:
{{"hook": "the opening words, max 60 chars — what shows before 'more'",
  "caption": "the full caption in Romanian: ONE paragraph, 25-60 words, no line breaks",
  "hashtags": ["#tag", "..."],
  "value": "one short line: what concrete thing the reader gets from this caption",
  "image_notes": "one sentence: what is in the photo, so a human can sanity-check the match"}}

The posted text will be: caption + blank line + CTA + hashtags.
Do not put the CTA or hashtags inside the caption. 3 to 5 hashtags.
"""

CTA = "📞 / WhatsApp 0728 888 881 sau un DM"


FEEDBACK_BLOCK = '''

## Revision requested
You already wrote this caption:
<previous_caption>
{previous}
</previous_caption>

A human reviewed it and asked for these changes:
<feedback>
{feedback}
</feedback>

Rewrite the caption applying that feedback. Keep everything else about the rules the same.'''


MAX_EDGE = 1400


def _encode_for_api(image_path: Path) -> str:
    image = Image.open(image_path).convert("RGB")
    if max(image.size) > MAX_EDGE:
        ratio = MAX_EDGE / max(image.size)
        image = image.resize((round(image.width * ratio), round(image.height * ratio)),
                             Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode()


def build_caption(image_path: Path, pillar: str, season: str, today: str,
                  feedback: str = None, previous: str = None) -> dict:
    brand_guide = (ROOT / "brand" / "brand_guide.md").read_text()
    about = (ROOT / "brand" / "about_ro.md").read_text()

    # Anthropic sees no more detail beyond ~1568px on the long edge, and a full-size
    # iPhone photo (4284x5712) exceeds the request size limit.
    media_type, image_b64 = "image/jpeg", _encode_for_api(image_path)

    prompt = PROMPT.format(
        brand_guide=brand_guide,
        about=about,
        today=today,
        season=season,
        pillar=PILLARS.get(pillar, pillar),
    )
    prompt += voice.examples_block()
    if feedback:
        prompt += FEEDBACK_BLOCK.format(previous=previous, feedback=feedback)

    response = requests.post(
        API,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        },
        timeout=180,
    )
    response.raise_for_status()
    blocks = response.json()["content"]
    text = "".join(b["text"] for b in blocks if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def render(caption: dict) -> str:
    """Turn the JSON caption into the exact text that gets posted."""
    tags = " ".join(caption["hashtags"])
    return f"{caption['caption']}\n\n{CTA}\n\n{tags}"
