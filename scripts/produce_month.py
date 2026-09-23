"""Build every planned post for the month and send them all for approval.

    python3 scripts/produce_month.py --show        # what would be built
    python3 scripts/produce_month.py --count 5     # build the next 5 slots
    python3 scripts/produce_month.py               # build everything still planned

Drafts go to Telegram and wait there. Nothing is scheduled until somebody taps a
button and scripts/process_approvals.py picks the decision up.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import planner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILDERS = {
    "photo": [sys.executable, str(ROOT / "run_pipeline.py"), "--from-plan", "--no-wait"],
    "carousel": [sys.executable, str(ROOT / "scripts" / "make_carousel.py"),
                 "--from-plan", "--no-wait"],
    "reel": [sys.executable, str(ROOT / "scripts" / "make_reel.py"), "--from-plan"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, help="how many slots to build")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--pause", type=int, default=5, help="seconds between builds")
    args = parser.parse_args()
    load_dotenv()

    plan = planner.load()
    if not plan:
        sys.exit("No plan — run scripts/plan_month.py first.")
    pending_slots = [s for s in plan["slots"] if s["status"] == "planned"]
    if args.count:
        pending_slots = pending_slots[:args.count]

    print(f"Plan {plan['month']}: {len(pending_slots)} slots to build\n")
    for slot in pending_slots:
        print(f"  {slot['date']} {slot['time']} · {slot['format']:<9} · "
              f"{slot['pillar']:<11} {slot['theme'][:60]}")
    if args.show:
        return

    print()
    built, failed = 0, []
    for index, slot in enumerate(pending_slots, start=1):
        print(f"\n=== [{index}/{len(pending_slots)}] {slot['date']} {slot['format']}: "
              f"{slot['theme'][:60]} ===")
        builder = BUILDERS.get(slot["format"])
        if not builder:
            failed.append((slot, f"unknown format {slot['format']}"))
            continue
        # Name the slot explicitly: builders used to grab "the next planned slot",
        # which meant the carousel builder could pick up a reel slot.
        command = builder + ["--slot", f"{slot['date']}/{slot['time']}"]
        result = subprocess.run(command, cwd=ROOT, text=True, stderr=subprocess.PIPE)
        if result.returncode == 0:
            built += 1
        else:
            # Show why: a silent "failed" taught us nothing the first time.
            tail = [line for line in (result.stderr or "").strip().splitlines() if line]
            reason = tail[-1] if tail else f"exited {result.returncode}"
            failed.append((slot, reason))
            print(f"   !! failed: {reason}")
        time.sleep(args.pause)

    print(f"\nBuilt {built} drafts. {len(failed)} failed.")
    for slot, why in failed:
        print(f"  {slot['date']} {slot['format']}: {why}")
    print("\nReview them in Telegram, then run:")
    print("  python3 scripts/process_approvals.py --watch 600")


if __name__ == "__main__":
    main()
