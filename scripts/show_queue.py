"""Show what is scheduled and what has gone out.

    python3 scripts/show_queue.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import schedule  # noqa: E402

ICONS = {"scheduled": "🗓", "published": "✅", "failed": "⚠️", "cancelled": "🚫"}

queue = schedule.load_queue()
if not queue:
    print("Nothing in the queue yet.")
    raise SystemExit

now = datetime.now(schedule.TZ)
for item in sorted(queue, key=lambda i: i["when"]):
    when = datetime.fromisoformat(item["when"])
    marker = "  (trecut)" if when < now and item["status"] == "scheduled" else ""
    print(f"{ICONS.get(item['status'], '?')} {schedule.describe(when)}{marker}"
          f"  [{item['pillar']}]  {item['asset']}")
    print(f"    {item['caption'].splitlines()[0][:90]}...")
    if item.get("note"):
        print(f"    note: {item['note']}")
