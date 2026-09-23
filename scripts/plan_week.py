"""Curate the coming week from the footage we actually have.

    python3 scripts/plan_week.py --show      # propose, change nothing
    python3 scripts/plan_week.py --apply     # add the slots to the current plan

Picks the strongest ideas the library can support, matches them to the weekly rhythm
(Tue 19:00, Thu 19:00, Sat 11:00) and adds them to the active monthly plan.
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import catalog, ideas, planner, schedule  # noqa: E402

SLOTS = {1: "19:00", 3: "19:00", 5: "11:00"}   # Tue, Thu, Sat
MIN_ASSETS = {"reel": 4, "carousel": 3, "photo": 1}


def upcoming(days=8):
    now = datetime.now(schedule.TZ)
    out, day = [], now.date()
    for _ in range(days):
        if day.weekday() in SLOTS:
            when = datetime.combine(day, datetime.min.time(), schedule.TZ).replace(
                hour=int(SLOTS[day.weekday()][:2]), minute=0)
            if when > now + timedelta(minutes=30):
                out.append(when)
        day += timedelta(days=1)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--quality", type=int, default=7,
                        help="minimum asset quality to consider")
    parser.add_argument("--count", type=int, default=10, help="ideas to generate")
    args = parser.parse_args()
    load_dotenv()

    plan = planner.load()
    if not plan:
        sys.exit("No active plan — run scripts/plan_month.py first.")
    taken = {f"{s['date']} {s['time']}" for s in plan["slots"]}
    slots = [s for s in upcoming() if f"{s:%Y-%m-%d} {s:%H:%M}" not in taken]
    if not slots:
        print("Every slot this week is already planned.")
        for slot in plan["slots"]:
            print(f"  {slot['date']} {slot['time']} {slot['status']:<12} {slot['theme'][:50]}")
        return

    print(f"Open slots this week: {', '.join(schedule.describe(s) for s in slots)}\n")
    print(f"Generating ideas from assets rated {args.quality}+...")
    result = ideas.generate(count=args.count, min_quality=args.quality)
    data = catalog.load()

    usable = []
    for idea in sorted(result["ideas"], key=lambda i: -i["strength"]):
        kind = "video" if idea["format"] == "reel" else "photo"
        assets = [a for a in idea["assets"]
                  if a in data and data[a]["kind"] == kind
                  and (data[a].get("quality") or 0) >= args.quality]
        if len(assets) >= MIN_ASSETS.get(idea["format"], 1):
            idea["assets"] = assets
            usable.append(idea)

    print(f"{len(usable)} of {len(result['ideas'])} ideas are buildable\n")
    chosen = usable[:len(slots)]
    for slot, idea in zip(slots, chosen):
        print(f"{schedule.describe(slot)} · {idea['format']} · {idea['pillar']} "
              f"[{idea['strength']}/10]\n   {idea['title']}\n   {idea['theme']}\n"
              f"   {len(idea['assets'])} assets · {idea['framing']}\n")

    if not args.apply or args.show:
        print("--show only. Rerun with --apply to add these to the plan.")
        return

    for slot, idea in zip(slots, chosen):
        plan["slots"].append({
            "date": f"{slot:%Y-%m-%d}", "time": f"{slot:%H:%M}",
            "format": idea["format"], "pillar": idea["pillar"],
            "theme": idea["theme"], "idea": idea["title"],
            "assets": idea["assets"], "folder": None,
            "note": idea["framing"], "audio": None, "status": "planned",
        })
    plan["slots"].sort(key=lambda s: (s["date"], s["time"]))
    plan.setdefault("ideas_used", {}).setdefault("ideas", []).extend(chosen)
    planner.save(plan)
    print(f"Added {len(chosen)} slots to plan {plan['month']}.")


if __name__ == "__main__":
    main()
