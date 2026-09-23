"""Build whatever the monthly plan asks for next.

    python3 run_next.py            # build the next planned slot
    python3 run_next.py --dry-run  # draft it without scheduling anything
    python3 run_next.py --show     # just show what's coming, build nothing

One command for the whole thing: it reads the plan, sees whether the next slot is a
photo, a carousel or a reel, and runs the right builder with the plan as its brief.
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline import planner, schedule

ROOT = Path(__file__).resolve().parent

BUILDERS = {
    "photo": [sys.executable, str(ROOT / "run_pipeline.py"), "--from-plan"],
    "carousel": [sys.executable, str(ROOT / "scripts" / "make_carousel.py"), "--from-plan"],
    "reel": [sys.executable, str(ROOT / "scripts" / "make_reel.py"), "--from-plan"],
}


def describe(slot):
    moment = datetime.fromisoformat(f"{slot['date']}T{slot['time']}").replace(
        tzinfo=schedule.TZ)
    line = (f"{schedule.describe(moment)} · {slot['format']} · {slot['pillar']}\n"
            f"   {slot['theme']}")
    if slot.get("note"):
        line += f"\n   {slot['note']}"
    if slot.get("audio"):
        line += f"\n   🎵 {slot['audio']}"
    return line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="list what's coming, build nothing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count", type=int, default=5, help="how many slots --show lists")
    args, passthrough = parser.parse_known_args()

    load_dotenv()
    plan = planner.load()
    if not plan:
        sys.exit("No plan found — run: python3 scripts/plan_month.py")

    pending = [slot for slot in plan["slots"] if slot["status"] == "planned"]
    if not pending:
        sys.exit(f"Every slot in plan {plan['month']} is done. "
                 "Run scripts/plan_month.py for the next month.")

    if args.show:
        print(f"Plan {plan['month']} — {len(pending)} slots left\n")
        for slot in pending[:args.count]:
            print(f"· {describe(slot)}\n")
        done = [s for s in plan["slots"] if s["status"] != "planned"]
        if done:
            print(f"({len(done)} already handled)")
        return

    slot = planner.next_slot(plan)
    if not slot:
        sys.exit("The remaining slots are all in the past — replan the month.")

    print(f"Next up: {describe(slot)}\n")
    builder = BUILDERS.get(slot["format"])
    if not builder:
        sys.exit(f"Unknown format in the plan: {slot['format']}")

    # A reel is never published by the pipeline anyway (music is added by hand in the
    # app), so make_reel.py has no --dry-run to pass on.
    dry = ["--dry-run"] if args.dry_run and slot["format"] != "reel" else []
    if args.dry_run and slot["format"] == "reel":
        print("(reels are always draft-only — they are delivered to Telegram, "
              "never auto-published)\n")
    command = builder + dry + passthrough
    print(f"→ {Path(command[1]).name} {' '.join(command[2:])}\n")
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
