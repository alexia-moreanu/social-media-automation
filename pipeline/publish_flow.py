"""Scheduling a draft once a human has approved it.

Shared by the interactive builders and by the approvals worker, so an approval means
exactly the same thing whether it arrives in 10 seconds or the next morning.
"""

import datetime as dt
from pathlib import Path

from . import library, planner, publisher, schedule, voice


def _when_for(slot):
    """The planned time if it is still ahead of us, otherwise the next free slot."""
    if slot:
        planned = dt.datetime.fromisoformat(f"{slot['date']}T{slot['time']}").replace(
            tzinfo=schedule.TZ)
        if planned > dt.datetime.now(schedule.TZ):
            return planned
    return schedule.next_free_slot()


def schedule_photo(entry, slot=None):
    when = _when_for(slot)
    path = Path(entry["image_path"])
    facebook = publisher.post_to_facebook(path, entry["caption"], publish_at=when)
    item = schedule.add(
        when=when, caption=entry["caption"], image_path=path,
        asset_name=entry["asset_name"], pillar=entry["pillar"],
        facebook_post_id=facebook["photo_id"], image_url=facebook["public_url"],
    )
    _finalise(entry, slot, item, when)
    return item, when


def schedule_carousel(entry, slot=None):
    when = _when_for(slot)
    slides = [Path(p) for p in entry["slide_paths"]]
    uploaded = [publisher.upload_unpublished_photo(slide) for slide in slides]
    facebook = publisher.post_carousel_to_facebook(
        [u["photo_id"] for u in uploaded], entry["caption"], publish_at=when)
    item = schedule.add(
        when=when, caption=entry["caption"], image_path=slides[0],
        asset_name=entry["asset_name"], pillar=entry["pillar"],
        facebook_post_id=facebook["post_id"],
        image_url=[u["public_url"] for u in uploaded],
    )
    _finalise(entry, slot, item, when)
    return item, when


def _finalise(entry, slot, item, when):
    for asset_id in entry.get("asset_ids", []):
        library.mark_used(asset_id)
    voice.remember(
        published_text=entry["caption"],
        first_draft=entry.get("first_draft") or entry["caption"],
        pillar=entry["pillar"], asset_name=entry["asset_name"],
        feedback=entry.get("feedback"),
        source=entry.get("voice_source", "as_is"),
    )
    if slot:
        plan = planner.load()
        if plan:
            planner.mark(plan, slot, "scheduled",
                         note=f"{item['id']} · {schedule.describe(when)}")
