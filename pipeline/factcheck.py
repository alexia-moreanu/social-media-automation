"""Facts guard: catch claims a caption makes that the brand documents don't support.

This exists because a draft once said the pool would be open "a few more days" —
plausible, invented, and nearly published. Everything concrete in a caption must be
traceable to brand/brand_guide.md or brand/about_ro.md.
"""

import json
import os
from pathlib import Path

import requests

MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"
ROOT = Path(__file__).resolve().parent.parent

PROMPT = """You are checking a social media caption for a venue before it is published.

These two documents are the ONLY source of truth about Happy Place:

<brand_guide>
{brand_guide}
</brand_guide>

<family_texts>
{about}
</family_texts>

Here is the caption:
<caption>
{caption}
</caption>

List every factual claim in the caption that is NOT supported by the documents: numbers,
prices, capacities, dates, seasons, what is included, what the family did, what visitors
can do. Opinions, atmosphere and descriptions of the attached photo are not claims —
ignore those. A claim that contradicts the documents is the most serious kind.

Return strict JSON only:
{{"issues": [{{"claim": "the exact words from the caption",
               "problem": "unsupported" or "contradicts",
               "note": "one short line in Romanian explaining the problem"}}],
  "verdict": "clean" or "check"}}

Return an empty list if everything checks out. Do not invent problems — a caption that
only uses documented facts must come back clean.
"""


def check(caption: str) -> dict:
    brand_guide = (ROOT / "brand" / "brand_guide.md").read_text()
    about = (ROOT / "brand" / "about_ro.md").read_text()

    response = requests.post(
        API,
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 1500, "messages": [{
            "role": "user",
            "content": PROMPT.format(brand_guide=brand_guide, about=about, caption=caption),
        }]},
        timeout=120,
    )
    response.raise_for_status()
    text = "".join(b["text"] for b in response.json()["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def summary(result: dict) -> str:
    """A short line for the Telegram draft, or empty when nothing is wrong."""
    issues = result.get("issues", [])
    if not issues:
        return ""
    lines = ["⚠️ De verificat:"]
    for issue in issues[:4]:
        mark = "❌" if issue.get("problem") == "contradicts" else "❓"
        lines.append(f"{mark} „{issue['claim']}” — {issue['note']}")
    return "\n".join(lines)
