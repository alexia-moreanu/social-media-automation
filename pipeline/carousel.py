"""Carousel: choose a set of photos that belong together and order them.

A carousel only works if the slides feel like one story. Claude looks at every candidate
and picks a coherent set, rather than us stitching together whatever is newest.
"""

import base64
import json
import os
import tempfile
from pathlib import Path

import requests
from PIL import Image

MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"

PROMPT = """You are building an Instagram carousel for Happy Place, a family-run garden
party venue near Bucharest (kids' parties, baptisms, BBQs, team buildings, courses).

You are shown candidate photos, numbered. Choose {count} of them that work as ONE post:
the slides must share a theme a viewer can name — one event, one cottage, one type of
celebration, one practical topic (for example "cum arată un botez la noi" or
"ce e inclus în preț").

Rules:
- Slide 1 has to stop the scroll on its own: the most striking, colourful, complete shot.
- Slides after it should add something new, not repeat the same angle.
- Do not mix obviously different events or seasons in one carousel.
- Skip empty rooms, bare walls, blurry shots and near-duplicates.
- The pools are packed away for this season: no swimming shots unless the theme is
  explicitly a summer memory.

Pillar: {pillar}.{theme_line}

Return strict JSON only:
{{"theme": "the one thing this carousel is about, in Romanian, max 8 words",
  "order": [4, 1, 6, 2, 5],
  "slides": [{{"clip": 4, "why": "few words"}}, ...],
  "cover_headline": "max 4 words for slide 1, Romanian, Amatic SC display font",
  "cover_subline": "max 9 words, one or two concrete facts separated by ·",
  "rejected": "one line: what you left out and why"}}
"""


def _thumbnail(path: Path, out_dir: Path, index: int, width=340) -> Path:
    image = Image.open(path).convert("RGB")
    ratio = width / image.width
    image = image.resize((width, round(image.height * ratio)), Image.LANCZOS)
    out = out_dir / f"thumb_{index}.jpg"
    image.save(out, quality=75)
    return out


def choose_set(image_paths, count=5, pillar="promo", theme=None):
    content = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for index, path in enumerate(image_paths, start=1):
            thumb = _thumbnail(path, Path(tmpdir), index)
            content.append({"type": "text", "text": f"Photo {index}: {path.name}"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(thumb.read_bytes()).decode(),
            }})
        theme_line = (f"\nThe monthly plan asks this carousel to be about: {theme}. "
                      f"Choose photos that serve that theme." if theme else "")
        content.append({"type": "text", "text": PROMPT.format(
            count=count, pillar=pillar, theme_line=theme_line)})

        response = requests.post(
            API,
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": content}]},
            timeout=180,
        )
    response.raise_for_status()
    text = "".join(b["text"] for b in response.json()["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(text)
    result["order"] = [i - 1 for i in result["order"] if 1 <= i <= len(image_paths)]
    return result


COVER_PROMPT = """Write the text for slide 1 of an Instagram carousel for Happy Place,
a family-run garden party venue near Bucharest.

The carousel is about: {theme}
Pillar: {pillar}
Never put a price on the slide — prices are given by phone or DM.
The attached image is slide 1.

{phrasings}

Return strict JSON only:
{{"cover_headline": "max 4 words, Romanian, Amatic SC display font",
  "cover_subline": "max 9 words, one or two concrete facts separated by ·"}}
"""


def cover_text(image_path, theme, pillar):
    """Headline and subline for the first slide, when the plan already chose the photos."""
    from . import llm

    guide = (Path(__file__).resolve().parent.parent / "brand" / "brand_guide.md").read_text()
    phrasings = "## On-image text" + guide.split("## On-image text", 1)[1].split("\n## ", 1)[0]
    return llm.call_json([
        llm.encode_image(image_path),
        {"type": "text", "text": COVER_PROMPT.format(
            theme=theme, pillar=pillar, phrasings=phrasings)},
    ], max_tokens=1000)
