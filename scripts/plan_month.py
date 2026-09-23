"""Write next month's plan: read the numbers, check trends, propose the schedule.

    python3 scripts/plan_month.py                 # plan next month
    python3 scripts/plan_month.py --month 2026-10
    python3 scripts/plan_month.py --no-trends     # skip the web search

The plan is saved to state/plans/ and sent to Telegram. The posting pipeline then
follows it slot by slot.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import analytics, approval, planner  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM (default: next month)")
    parser.add_argument("--no-trends", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    target = (datetime.strptime(args.month, "%Y-%m").date() if args.month else None)

    print("1. Reading last month's performance...")
    try:
        posts = analytics.with_pillars(
            analytics.instagram_posts() + analytics.facebook_posts()
        )
        summary = analytics.summarise(posts)
        print(f"   {summary['total_posts']} posts measured")
        for pillar, row in (summary.get("by_pillar") or {}).items():
            print(f"   {pillar}: avg engagement {row['avg_engagement']}, "
                  f"avg reach {row['avg_reach']}")
    except RuntimeError as error:
        print(f"   (could not read insights: {error})")
        summary = {}

    print("2. Writing the plan" + ("" if args.no_trends else " (searching trends first)") + "...")
    plan = planner.build_plan(summary, target=target, use_trends=not args.no_trends)
    path = planner.save(plan)
    print(f"   {len(plan['slots'])} slots -> {path}")

    print()
    print(planner.as_text(plan))

    if not args.no_telegram:
        text = planner.as_text(plan)
        approval.update_status_plain(text[:4000])
        if plan.get("watch"):
            approval.update_status_plain(
                "🔍 De urmărit luna asta:\n" + "\n".join(f"· {w}" for w in plan["watch"])
            )
        print("\nSent to Telegram.")


if __name__ == "__main__":
    main()
