"""Planner: writes next month's posting plan and keeps it as the pipeline's brief.

Runs once a month. It reads the standing strategy, last month's engagement, the season,
and what footage is actually left in Drive, then produces a dated slot-by-slot plan.
The plan is the brief every later post is built from.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import catalog, ideas, llm, schedule, trends

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "state" / "plans"

PROMPT = """You are the content planner for Happy Place, a family-run garden party venue
in Domnești, Ilfov. Write the posting plan for {month_name} {year}.

You plan CONTENT-FIRST. The posts come from the footage that actually exists — the ideas
below were built by looking at every usable asset in the library. The strategy decides
how often to post, in what format, and which seasonal moments to hook into. It does NOT
decide what the posts are about; the footage does.

<standing_strategy>
{strategy}
</standing_strategy>

<brand_guide>
{brand_guide}
</brand_guide>

## What happened last period
{performance}

## Post ideas the library can actually deliver (ranked)
{ideas}

## What the library holds
{inventory}

## What is trending right now (fresh web search)
{trends}

## Rules
- Every slot MUST come from the ideas list above. Use the idea's title, theme, format
  and asset ids as they are — do not invent a theme the footage cannot support.
- COPY THE ASSET IDS CHARACTER FOR CHARACTER from the idea you are using. They are Drive
  file ids like "1LJ_FJW7AW4ORnjv8vdZ5qfeg75Zg5QDA". Never shorten them, never invent
  readable ones, never renumber them.
- Schedule the strongest ideas first, and use the weaker ones only if you need the slots.
- If there are fewer good ideas than slots in the rhythm, POST LESS. Quality over volume
  is the standing rule; say so in "changes" and put the shortfall in "shoot_list".
- Where footage was shot in another season, keep the idea's honest framing
  (a memory, a recap) — never present summer footage as today.
- Use the weekly rhythm in the strategy for days and times, but CHANGE it where last
  period's numbers justify a change, and say why in "changes".
- Every slot needs: date (YYYY-MM-DD), time (HH:MM), format (reel | carousel | photo),
  pillar (promo | educational | mood | story), a concrete theme in Romanian, and which
  Drive folder the footage should come from.
- Respect the monthly pillar mix in the strategy unless the numbers argue otherwise.
- Only plan what the available footage can actually support. If something is missing,
  put it in "shoot_list" instead of planning a post that cannot be made.
- Seasonality matters: {season}
- Use the trend data where it genuinely fits this venue. For reels, name a suggested
  track in the slot note (music is added by hand in the Instagram app). Plan around the
  dates found in the search. Never chase a trend that would look silly for a family venue.
- Today is {today}. Plan only dates from tomorrow onwards.
- If there is no performance data yet, say so in "changes" and follow the standing strategy.

Return strict JSON only:
{{"month": "{year}-{month:02d}",
  "summary": "2-3 sentences in Romanian: what this month is about",
  "changes": ["what you changed versus the standing strategy, and why — each one line"],
  "slots": [{{"date": "YYYY-MM-DD", "time": "19:00", "format": "reel",
              "pillar": "promo", "theme": "the idea's theme, in Romanian",
              "idea": "the idea's title",
              "assets": ["drive id", "..."],
              "folder": "Drive subfolder the assets come from, or null",
              "note": "one line of direction, including the season framing",
              "audio": "suggested track for reels, or null"}}],
  "shoot_list": ["what to film or photograph this month to fill the gaps"],
  "watch": ["what to check at the end of the month"]}}
"""


def _inventory():
    """What the catalogue says the library holds — reality, not folder names."""
    scanned = catalog.summary()
    if scanned["total_catalogued"]:
        lines = [
            f"{scanned['usable']} usable unused assets "
            f"(of {scanned['total_catalogued']} catalogued), "
            f"{scanned['with_people']} with people, {scanned['with_kids']} with kids.",
            "By event: " + ", ".join(f"{k} {v}" for k, v in scanned["by_event"].items()),
            "By season: " + ", ".join(f"{k} {v}" for k, v in scanned["by_season"].items()),
            "By kind: " + ", ".join(f"{k} {v}" for k, v in scanned["by_kind"].items()),
        ]
        return "\n".join(lines)
    return _folder_inventory()


def _folder_inventory():
    """Fallback when nothing has been catalogued yet."""
    from . import library

    photos = library.list_media("image")
    videos = library.list_media("video")
    unused_photos = library.unused(photos)
    unused_videos = library.unused(videos)

    folders = {}
    for asset in unused_photos + unused_videos:
        name = asset["folder"].strip() or "(root)"
        row = folders.setdefault(name, {"photos": 0, "videos": 0})
        row["photos" if asset["mimeType"].startswith("image/") else "videos"] += 1

    lines = [f"Total unused: {len(unused_photos)} photos, {len(unused_videos)} videos."]
    for name, row in sorted(folders.items(), key=lambda kv: -(kv[1]["photos"] + kv[1]["videos"])):
        lines.append(f"- {name}: {row['photos']} photos, {row['videos']} videos")
    return "\n".join(lines)


def _performance_text(summary):
    if not summary or not summary.get("total_posts"):
        return "No posts with data yet — this is the first planned month."

    lines = [f"{summary['total_posts']} posts measured."]
    for label, key in (("By pillar", "by_pillar"), ("By format", "by_format"),
                       ("By weekday", "by_weekday"), ("By hour", "by_hour")):
        rows = summary.get(key) or {}
        if not rows:
            continue
        lines.append(f"\n{label}:")
        for name, row in sorted(rows.items(), key=lambda kv: -kv[1]["avg_engagement"]):
            lines.append(
                f"- {name}: {row['posts']} posts, avg reach {row['avg_reach']}, "
                f"avg engagement {row['avg_engagement']} "
                f"(likes {row['likes']}, comments {row['comments']}, "
                f"saves {row['saves']}, shares {row['shares']})"
            )
    best = summary.get("best") or []
    if best:
        lines.append("\nBest performing posts:")
        for post in best:
            lines.append(f"- [{post.get('pillar') or '?'}/{post['type']}] "
                         f"{post['caption'][:90]}... "
                         f"(reach {post['reach']}, saves {post['saves']}, "
                         f"comments {post['comments']})")
    return "\n".join(lines)


SEASONS = {
    (9, 10): "Autumn garden parties, team buildings, courses & workshops; start promoting December",
    (11, 12): "Christmas / end-of-year company parties, indoor kids' parties, cozy mood content",
    (1, 3): "Courses, workshops, therapy groups, indoor birthdays; weekday offers; book summer early",
    (4, 5): "Baptisms, moț, small weddings; spring garden reopening",
    (6, 8): "Pools, kids' parties, BBQs — peak garden season",
}


def season_for(month):
    for (start, end), text in SEASONS.items():
        if start <= month <= end:
            return text
    return "Open all year"


MONTHS_RO = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie",
             "august", "septembrie", "octombrie", "noiembrie", "decembrie"]


def build_plan(performance_summary, target: date = None, use_trends=True,
               idea_count=14):
    target = target or (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    strategy = (ROOT / "docs" / "content_strategy.md").read_text()
    brand_guide = (ROOT / "brand" / "brand_guide.md").read_text()
    trend_data = trends.fetch(target) if use_trends else {}
    idea_set = ideas.generate(count=idea_count)

    prompt = PROMPT.format(
        month_name=MONTHS_RO[target.month - 1], year=target.year, month=target.month,
        strategy=strategy, brand_guide=brand_guide,
        performance=_performance_text(performance_summary),
        ideas=ideas.as_text(idea_set), inventory=_inventory(),
        trends=trends.as_text(trend_data),
        season=season_for(target.month),
        today=date.today().isoformat(),
    )

    plan = llm.call_json(prompt, max_tokens=16000)
    plan["trends_used"] = trend_data
    plan["ideas_used"] = idea_set
    repair_assets(plan)
    return plan


def repair_assets(plan):
    """Make sure every slot points at real Drive files.

    The model has to copy long opaque ids; when it paraphrases them instead, the whole
    slot is unbuildable. The ideas it worked from are stored alongside the plan, so the
    correct ids can be restored by matching the idea title.
    """
    data = catalog.load()
    known = set(data.keys())

    def right_kind(asset_id, fmt):
        entry = data.get(asset_id)
        if not entry:
            return False
        return entry["kind"] == ("video" if fmt == "reel" else "photo")
    by_title = {i["title"].strip().casefold(): i
                for i in (plan.get("ideas_used") or {}).get("ideas", [])}
    repaired, dropped, blocked = 0, 0, []
    for slot in plan.get("slots", []):
        fmt = slot.get("format", "photo")
        assets = [a for a in (slot.get("assets") or [])
                  if a in known and right_kind(a, fmt)]
        if not assets:
            idea = by_title.get((slot.get("idea") or slot.get("theme", "")).strip().casefold())
            if not idea:  # fall back to the closest title match
                for title, candidate in by_title.items():
                    if title in (slot.get("theme") or "").casefold() or \
                       (slot.get("idea") or "").casefold() in title:
                        idea = candidate
                        break
            if idea:
                assets = [a for a in idea["assets"] if a in known and right_kind(a, fmt)]
                repaired += 1
            else:
                dropped += 1
        slot["assets"] = assets
        # A reel needs real clips; without them the slot is not buildable as planned.
        minimum = 4 if fmt == "reel" else (3 if fmt == "carousel" else 1)
        if len(assets) < minimum:
            slot["status"] = "blocked"
            slot["result"] = (f"{len(assets)} {'clipuri' if fmt == 'reel' else 'poze'} "
                              f"potrivite — are nevoie de {minimum}")
            blocked.append(slot)
    if repaired or dropped or blocked:
        print(f"   plan check: {repaired} slots had their asset ids restored, "
              f"{dropped} unmatched, {len(blocked)} blocked for lack of usable media")
    return plan


def save(plan):
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    for slot in plan["slots"]:
        slot.setdefault("status", "planned")
    path = PLAN_DIR / f"{plan['month']}.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    return path


def load(month: str = None):
    """Load a plan by month ("2026-10"), or the one covering today."""
    if month:
        path = PLAN_DIR / f"{month}.json"
        return json.loads(path.read_text()) if path.exists() else None
    for path in sorted(PLAN_DIR.glob("*.json"), reverse=True):
        plan = json.loads(path.read_text())
        if any(slot["status"] == "planned" for slot in plan["slots"]):
            return plan
    return None


def next_slot(plan, when: datetime = None):
    """The next unfulfilled slot — what the pipeline should build now."""
    when = when or datetime.now(schedule.TZ)
    upcoming = [
        slot for slot in plan["slots"]
        if slot["status"] == "planned"
        and datetime.fromisoformat(f"{slot['date']}T{slot['time']}").replace(
            tzinfo=schedule.TZ) >= when - timedelta(hours=6)
    ]
    upcoming.sort(key=lambda slot: (slot["date"], slot["time"]))
    return upcoming[0] if upcoming else None


def slot_by_key(plan, key):
    """Find one slot by "YYYY-MM-DD/HH:MM" — builders must work on the slot they were
    given, not on whatever happens to be next in the plan."""
    date_part, _, time_part = key.partition("/")
    for slot in plan.get("slots", []):
        if slot["date"] == date_part and slot["time"] == time_part:
            return slot
    return None


def mark(plan, slot, status, note=None):
    for item in plan["slots"]:
        if item["date"] == slot["date"] and item["time"] == slot["time"]:
            item["status"] = status
            if note:
                item["result"] = note
    save(plan)


def as_text(plan) -> str:
    """A readable plan for Telegram."""
    days = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
    lines = [f"📅 Plan {plan['month']}", "", plan["summary"], ""]
    if plan.get("changes"):
        lines.append("Ce am schimbat față de strategie:")
        lines += [f"· {change}" for change in plan["changes"]]
        lines.append("")
    for slot in plan["slots"]:
        moment = datetime.fromisoformat(slot["date"])
        line = (f"{days[moment.weekday()][:2]} {moment.day:02d}.{moment.month:02d} "
                f"{slot['time']} · {slot['format']} · {slot['pillar']} — {slot['theme']}")
        if slot.get("audio"):
            line += f"\n     🎵 {slot['audio']}"
        lines.append(line)
    if plan.get("shoot_list"):
        lines += ["", "🎥 De filmat/fotografiat:"]
        lines += [f"· {item}" for item in plan["shoot_list"]]
    return "\n".join(lines)
