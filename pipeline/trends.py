"""Trends: what is actually working on social right now, fetched at planning time.

Uses Claude's server-side web search, so the planner is not limited to what the model
remembers. Results are cached for a week — trends do not move fast enough to justify
searching on every run, and each search costs money.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from . import llm

CACHE = Path(__file__).resolve().parent.parent / "state" / "trends_cache.json"
CACHE_DAYS = 7

PROMPT = """Search the web and report what is worth knowing for planning
{month_name} {year} social media content for a family-run garden party and event venue
near Bucharest, Romania (kids' parties, baptisms, "tăierea moțului", small weddings,
BBQs, team buildings, courses and workshops).

Find:
1. Trending Instagram Reels audio right now — 3 to 5 tracks, and for each, what kind of
   footage it suits. Prefer ones that fit warm, family, outdoor or celebration content.
2. Reels and carousel formats or hooks that are performing well this season
   (for example specific editing patterns, "POV", before/after, checklists).
3. Romanian holidays, school holidays, seasonal moments and booking-decision periods in
   {month_name} that a venue should post around — be specific about dates.
4. Anything currently trending in Romanian event decor or party themes.

Be concrete and skip generic advice like "post consistently". If something is uncertain,
say so rather than guessing.

Return strict JSON only:
{{"audio": [{{"track": "Artist - Title", "fits": "what footage it suits"}}],
  "formats": [{{"format": "name", "why": "one line"}}],
  "dates": [{{"date": "YYYY-MM-DD or range", "what": "what it is", "angle": "how to use it"}}],
  "themes": ["decor or party themes trending now"],
  "as_of": "{today}"}}
"""

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def _cached():
    if not CACHE.exists():
        return None
    data = json.loads(CACHE.read_text())
    fetched = datetime.fromisoformat(data["fetched_at"])
    if datetime.now() - fetched > timedelta(days=CACHE_DAYS):
        return None
    return data["trends"]


def fetch(target: date, force=False):
    """Current trends for the month being planned. Returns {} if the search fails."""
    if not force:
        cached = _cached()
        if cached:
            return cached

    prompt = PROMPT.format(
        month_name=MONTHS_EN[target.month - 1], year=target.year,
        today=date.today().isoformat(),
    )
    try:
        trends = llm.call_json(
            prompt,
            max_tokens=12000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        )
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as error:
        print(f"   (trend search failed: {error} — planning without it)")
        return {}

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now().isoformat(), "trends": trends},
        ensure_ascii=False, indent=2,
    ))
    return trends


def as_text(trends) -> str:
    if not trends:
        return "No trend data available this run."
    lines = [f"(searched {trends.get('as_of', 'recently')})"]
    if trends.get("audio"):
        lines.append("\nTrending audio:")
        lines += [f"- {a['track']} — {a['fits']}" for a in trends["audio"]]
    if trends.get("formats"):
        lines.append("\nFormats working now:")
        lines += [f"- {f['format']}: {f['why']}" for f in trends["formats"]]
    if trends.get("dates"):
        lines.append("\nDates to post around:")
        lines += [f"- {d['date']}: {d['what']} → {d['angle']}" for d in trends["dates"]]
    if trends.get("themes"):
        lines.append("\nTrending themes: " + ", ".join(trends["themes"]))
    return "\n".join(lines)
