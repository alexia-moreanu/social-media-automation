"""The posting queue and the weekly rhythm from docs/content_strategy.md."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")
ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = ROOT / "state" / "queue.json"

# weekday (Mon=0) -> hour, minute. Tuesday 19:00, Thursday 19:00, Saturday 11:00.
SLOTS = {1: (19, 0), 3: (19, 0), 5: (11, 0)}

MIN_LEAD_MINUTES = 20  # Facebook refuses anything less than 10 minutes ahead


def load_queue():
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return []


def save_queue(queue):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2))


def upcoming_slots(count=8, now=None):
    now = now or datetime.now(TZ)
    earliest = now + timedelta(minutes=MIN_LEAD_MINUTES)
    slots, day = [], now.date()
    while len(slots) < count:
        if day.weekday() in SLOTS:
            hour, minute = SLOTS[day.weekday()]
            moment = datetime.combine(day, datetime.min.time(), TZ).replace(
                hour=hour, minute=minute
            )
            if moment >= earliest:
                slots.append(moment)
        day += timedelta(days=1)
    return slots


def next_free_slot(now=None):
    """The next slot in the weekly rhythm that nothing is scheduled into yet."""
    taken = {item["when"] for item in load_queue() if item["status"] != "cancelled"}
    for slot in upcoming_slots(20, now=now):
        if slot.isoformat() not in taken:
            return slot
    raise RuntimeError("No free slot found in the next few weeks.")


def add(*, when, caption, image_path, asset_name, pillar, facebook_post_id, image_url):
    queue = load_queue()
    item = {
        "id": f"{when.strftime('%Y%m%d-%H%M')}-{len(queue) + 1}",
        "when": when.isoformat(),
        "caption": caption,
        "image_path": str(image_path),
        "asset": asset_name,
        "pillar": pillar,
        "facebook_post_id": facebook_post_id,  # already scheduled on Meta's side
        "image_url": image_url,
        "instagram_media_id": None,
        "status": "scheduled",
        "note": None,
    }
    queue.append(item)
    save_queue(queue)
    return item


def due_items(now=None):
    now = now or datetime.now(TZ)
    return [
        item for item in load_queue()
        if item["status"] == "scheduled" and datetime.fromisoformat(item["when"]) <= now
    ]


def update(item_id, **changes):
    queue = load_queue()
    for item in queue:
        if item["id"] == item_id:
            item.update(changes)
    save_queue(queue)


def describe(moment: datetime) -> str:
    days = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
    return f"{days[moment.weekday()]} {moment.day}.{moment.month:02d} la {moment:%H:%M}"
