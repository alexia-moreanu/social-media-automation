"""Ideas: read the catalogue and propose posts the library can actually deliver.

Content-first. The strategy decides format mix, cadence and seasonal hooks; the footage
decides what the posts are about. An idea that the library cannot support is not an idea.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import catalog, library, llm

ROOT = Path(__file__).resolve().parent.parent

PROMPT = """You are choosing what Happy Place should post, based only on the media it
actually has. Happy Place is a family-run garden party venue near Bucharest.

Below is the catalogue of unused assets — every one has been looked at, so these
descriptions are what the camera really captured.

<library>
{library}
</library>

<brand_guide>
{brand_guide}
</brand_guide>

Propose {count} post ideas that this library can deliver well. Rules:

- Build each idea around assets that genuinely belong together: same event, same place,
  same look, or a clear practical topic they illustrate.
- Only use assets listed above, by their id.
- MATCH THE KIND TO THE FORMAT, without exception:
  · "reel"     -> only assets marked [video], at least 4 of them
  · "carousel" -> only assets marked [photo], 3 to 8 of them
  · "photo"    -> exactly 1 asset marked [photo]
  A reel made of still photos, or a carousel containing a video file, cannot be built.
- Prefer assets with quality 7+. Never build an idea whose average quality is below 6.
- PREFER RECENT FOOTAGE. Each asset shows when it was shot; assets marked RECENT are from
  the last {recent_months} months and should carry most of the ideas. Older material is
  allowed when it is genuinely the best (an event type we have not filmed since), but say
  so in "framing" and treat it as an archive memory.
- Say what season the footage shows. Content shot in summer can still be posted in
  autumn, but it must be framed honestly (a memory, a recap), never as "right now".
- Spread the ideas across the four pillars (promo, educational, mood, story) and across
  formats, but do not force a pillar the footage cannot support.
- Rank by strength: idea 1 should be the one you are most confident in.

Return strict JSON only:
{{"ideas": [{{"title": "short name for this idea, Romanian",
              "format": "reel | carousel | photo",
              "pillar": "promo | educational | mood | story",
              "theme": "what the post says, in Romanian, one sentence",
              "assets": ["drive id", "..."],
              "season_shown": "vară | toamnă | ...",
              "framing": "how to handle the season honestly, one line",
              "strength": 1-10,
              "why": "one line: why this works"}}],
  "gaps": ["what the library cannot currently support, for the shoot list"]}}
"""


RECENT_MONTHS = 6


def _library_text(min_quality=6, limit=140, recent_months=RECENT_MONTHS):
    data = catalog.load()
    used = set(library._used())
    rows = [a for a in data.values()
            if a["id"] not in used and (a.get("quality") or 0) >= min_quality]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=recent_months * 30)).strftime(
        "%Y-%m-%d")

    def is_recent(asset):
        return (asset.get("taken_at") or "") >= cutoff

    # Rank by recency first, then quality: a fresh 8/10 beats a two-year-old 9/10.
    rows.sort(key=lambda a: (is_recent(a), a.get("quality") or 0), reverse=True)
    # Keep both kinds in view: sorting one big list buried every video under photos,
    # and the planner then built "reels" out of still images.
    photos = [a for a in rows if a["kind"] == "photo"][:limit // 2]
    videos = [a for a in rows if a["kind"] == "video"][:limit // 2]
    rows = photos + videos

    lines = []
    for asset in rows:
        lines.append(
            f"- {asset['id']} [{asset['kind']}, {asset.get('quality')}/10, "
            f"{(asset.get('taken_at') or '?')[:10]}"
            f"{', RECENT' if is_recent(asset) else ''}] "
            f"{asset.get('subject')} · eveniment: {asset.get('event')} · "
            f"sezon: {asset.get('season')} · {asset.get('setting')}"
            + (" · cu oameni" if asset.get("people") else "")
            + (" · cu copii" if asset.get("kids") else "")
            + f" · folder: {asset.get('folder')}"
        )
    return "\n".join(lines), len(rows)


def generate(count=12, min_quality=6):
    library_text, available = _library_text(min_quality=min_quality)
    if available < 5:
        raise RuntimeError(
            "Not enough catalogued assets — run scripts/scan_library.py first."
        )
    brand_guide = (ROOT / "brand" / "brand_guide.md").read_text()
    prompt = PROMPT.format(library=library_text, brand_guide=brand_guide, count=count,
                           recent_months=RECENT_MONTHS)
    result = llm.call_json(prompt, max_tokens=16000)
    return result


def as_text(result) -> str:
    lines = []
    for index, idea in enumerate(result.get("ideas", []), start=1):
        lines.append(
            f"{index}. [{idea['strength']}/10] {idea['format']} · {idea['pillar']} — "
            f"{idea['title']}\n   {idea['theme']}\n   filmat {idea['season_shown']} — "
            f"{idea['framing']}\n   assets ({len(idea['assets'])}): "
            + ", ".join(idea["assets"])
        )
    if result.get("gaps"):
        lines.append("\nGaps (for the shoot list):")
        lines += [f"· {gap}" for gap in result["gaps"]]
    return "\n".join(lines)
