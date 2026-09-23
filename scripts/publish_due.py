"""Publish any queued Instagram posts whose time has come.

Facebook posts are scheduled on Meta's servers and need nothing from us.
Instagram has no scheduling API, so this worker does it — run it every 15 minutes.

    python3 scripts/publish_due.py

If the Mac was asleep at the scheduled time, the post goes out at the next run and
Telegram is told it was late.
"""

import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import approval, publisher, schedule  # noqa: E402

LATE_MINUTES = 45  # beyond this, say in Telegram that it went out late


def main():
    load_dotenv()
    due = schedule.due_items()
    if not due:
        print("Nothing due.")
        return

    for item in due:
        when = datetime.fromisoformat(item["when"])
        late = (datetime.now(schedule.TZ) - when).total_seconds() / 60
        print(f"Publishing {item['id']} ({item['asset']}), due {schedule.describe(when)}")

        urls = item["image_url"]
        is_carousel = isinstance(urls, list)
        try:
            if is_carousel:
                instagram = publisher.post_carousel_to_instagram(urls, item["caption"])
            else:
                instagram = publisher.post_to_instagram(urls, item["caption"])
        except RuntimeError as error:
            # The Facebook CDN link can expire; re-upload the local file to refresh it.
            if is_carousel:
                schedule.update(item["id"], status="failed", note=str(error))
                approval.update_status_plain(
                    f"⚠️ Caruselul Instagram a eșuat ({item['asset']}): {error}"
                )
                print(f"  failed: {error}")
                continue
            try:
                refreshed = publisher.post_to_facebook(
                    Path(item["image_path"]), item["caption"],
                    publish_at=datetime.now(schedule.TZ).replace(microsecond=0),
                )
                instagram = publisher.post_to_instagram(refreshed["public_url"], item["caption"])
            except RuntimeError as second_error:
                schedule.update(item["id"], status="failed", note=str(second_error))
                approval.update_status_plain(
                    f"⚠️ Instagram a eșuat pentru {item['asset']}: {second_error}\n"
                    f"(prima eroare: {error})"
                )
                print(f"  failed: {second_error}")
                continue

        schedule.update(
            item["id"], status="published", instagram_media_id=instagram["media_id"]
        )
        note = f"📸 Instagram publicat: {instagram['link']}"
        if late > LATE_MINUTES:
            note += f"\n⏰ Cu {int(late)} minute întârziere (Mac-ul a fost închis?)"
        approval.update_status_plain(note)
        print(f"  published: {instagram['link']}")


if __name__ == "__main__":
    main()
