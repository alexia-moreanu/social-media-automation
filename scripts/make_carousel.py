"""Build one carousel: choose a coherent set of photos, write the caption, ask approval.

    python3 scripts/make_carousel.py --from-plan
    python3 scripts/make_carousel.py --pillar educational --slides 5 --dry-run

With --from-plan the slides are the assets the monthly plan chose from the catalogue.
Without it, Claude picks a coherent set from unused photos in Drive.
"""

import argparse
import datetime as dt
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import (approval, carousel, caption as caption_writer, design,  # noqa: E402
                      library, pending, planner, publisher, schedule, voice)

OUTPUT = Path(__file__).resolve().parent.parent / "output"

SEASONS = {
    (9, 10): "Autumn garden parties, team buildings, courses & workshops; December events",
    (11, 12): "Christmas / end-of-year company parties, indoor kids' parties, cozy content",
    (1, 3): "Courses, workshops, therapy groups, indoor birthdays; weekday offers",
    (4, 5): "Baptisms, moț, small weddings; spring garden reopening",
    (6, 8): "Pools, kids' parties, BBQs — peak garden season",
}


def season_for(month):
    for (start, end), text in SEASONS.items():
        if start <= month <= end:
            return text
    return "Open all year"


def gather(args, slot):
    """Return (assets, paths, picked) — either the plan's choice or Claude's."""
    if slot and slot.get("assets"):
        print(f"1. Using the {len(slot['assets'])} photos the plan chose...")
        assets = library.assets_by_ids(slot["assets"])
        paths = [library.download(asset) for asset in assets]
        theme = args.theme or slot["theme"]
        cover = carousel.cover_text(paths[0], theme, args.pillar)
        picked = {"theme": theme, "order": list(range(len(paths))), "slides": [],
                  "rejected": "", **cover}
        return assets, paths, picked

    print("1. Gathering candidate photos from Drive...")
    photos = library.list_media("image")
    if args.folder:
        wanted = args.folder.strip().casefold()
        photos = [p for p in photos if p["folder"].strip().casefold() == wanted]
    available = library.unused(photos)
    if len(available) < 3:
        sys.exit("Not enough unused photos to build a carousel.")
    assets = random.sample(available, min(args.candidates, len(available)))
    paths = [library.download(asset) for asset in assets]
    print(f"   {len(available)} unused photos, showing {len(paths)} to Claude")

    print("2. Choosing a set that belongs together...")
    picked = carousel.choose_set(paths, count=args.slides, pillar=args.pillar,
                                 theme=args.theme)
    print(f"   theme: {picked['theme']}")
    for slide in picked.get("slides", []):
        index = slide["clip"] - 1
        if 0 <= index < len(assets):
            print(f"   · {assets[index]['name'][:34]:<34} {slide.get('why', '')}")
    if picked.get("rejected"):
        print(f"   left out: {picked['rejected']}")
    return assets, paths, picked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pillar", default="promo", choices=list(caption_writer.PILLARS))
    parser.add_argument("--folder", help="only use photos from this Drive subfolder")
    parser.add_argument("--slides", type=int, default=5, help="slides in the carousel (2-10)")
    parser.add_argument("--candidates", type=int, default=14)
    parser.add_argument("--no-cover-text", action="store_true")
    parser.add_argument("--from-plan", action="store_true")
    parser.add_argument("--slot", help="build this exact slot: YYYY-MM-DD/HH:MM")
    parser.add_argument("--theme", help="override the carousel theme")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true",
                        help="send the draft and exit; approvals handled later")
    parser.add_argument("--wait", type=int, default=900)
    args = parser.parse_args()

    load_dotenv()
    today = dt.date.today()

    plan, slot = None, None
    if args.from_plan or args.slot:
        plan = planner.load()
        slot = (planner.slot_by_key(plan, args.slot) if args.slot
                else (planner.next_slot(plan) if plan else None))
        if not slot:
            sys.exit("No such planned slot — run scripts/plan_month.py first.")
        args.pillar = slot["pillar"]
        if not slot.get("assets"):
            args.folder = slot.get("folder") or args.folder
        print(f"0. Plan slot: {slot['date']} {slot['time']} · {slot['pillar']}\n"
              f"   temă: {slot['theme']}\n   {slot.get('note', '')}")

    assets, paths, picked = gather(args, slot)

    ordered_indexes = picked["order"][:args.slides]
    ordered = [paths[i] for i in ordered_indexes]
    ordered_assets = [assets[i] for i in ordered_indexes]
    if len(ordered) < 2:
        sys.exit("Fewer than two usable slides — try another folder or replan.")

    print("3. Rendering slides at 4:5...")
    # Unique per draft: several carousels can sit in the approval queue at once, and
    # fixed filenames would have them overwrite each other's slides.
    stamp = dt.datetime.now().strftime("%m%d-%H%M%S")
    OUTPUT.mkdir(exist_ok=True)
    slides = []
    for position, path in enumerate(ordered):
        if position == 0 and not args.no_cover_text:
            slide = design.compose(path, picked["cover_headline"], picked["cover_subline"],
                                   size="post", output=OUTPUT / f"carousel_{stamp}_{position + 1}.jpg")
        else:
            slide = design.compose(path, "", "", size="post", watermark=False,
                                   output=OUTPUT / f"carousel_{stamp}_{position + 1}.jpg")
        slides.append(slide)
    print(f"   {len(slides)} slides")

    print("4. Writing the caption...")
    brief = (f"This is a carousel of {len(slides)} slides about: {picked['theme']}. "
             f"Write the caption for the whole set, not just the first photo.")
    if slot and slot.get("note"):
        brief += f" Direction from the plan: {slot['note']}"
    draft = caption_writer.build_caption(
        ordered[0], args.pillar, season_for(today.month), today.isoformat(),
        feedback=brief, previous="(no previous draft)",
    )
    text = caption_writer.render(draft)
    print("   ---")
    print("   " + text.replace("\n", "\n   "))
    print("   ---")

    header = (f"🎠 Carusel {len(slides)} slide-uri — {picked['theme']}\n"
              f"🏷 pilon: {args.pillar}" + ("\n⚠️ TEST" if args.dry_run else ""))

    print("5. Sending to Telegram...")
    message_id = approval.send_album(slides, header, text)
    if args.dry_run:
        print("   Dry run: nothing will be published.")
        return

    if args.no_wait:
        pending.add(
            message_id=message_id, kind="carousel", caption=text,
            slide_paths=[str(s) for s in slides],
            asset_name=f"carusel: {picked['theme']}",
            asset_ids=[a["id"] for a in ordered_assets], pillar=args.pillar,
            slot=({"date": slot["date"], "time": slot["time"],
                   "month": plan["month"]} if slot else None),
        )
        if plan and slot:
            planner.mark(plan, slot, "drafted", note="așteaptă decizia în Telegram")
        print("   Draft sent. Decision will be handled by process_approvals.py")
        return

    print(f"6. Waiting up to {args.wait}s for a decision...")
    decision, who = approval.wait_for_decision(message_id, args.wait)

    if decision == "reject":
        approval.ask_for_reason(message_id)
        reason = approval.wait_for_text(180) or "(fără motiv)"
        voice.remember_rejection(rejected_text=text, reason=reason, pillar=args.pillar,
                                 asset_name=f"carusel: {picked['theme']}")
        approval.update_status(message_id,
                               f"❌ Respins de {who}. Motivul e salvat:\n„{reason}”")
        print(f"   rejected — reason saved: {reason}")
        return
    if decision != "approve":
        approval.update_status(message_id, "⌛️ Nimeni nu a apăsat — nu s-a programat nimic.")
        print("   timeout — nothing scheduled.")
        return

    if slot:
        planned = dt.datetime.fromisoformat(f"{slot['date']}T{slot['time']}").replace(
            tzinfo=schedule.TZ)
        when = planned if planned > dt.datetime.now(schedule.TZ) else schedule.next_free_slot()
    else:
        when = schedule.next_free_slot()
    when_text = schedule.describe(when)
    print(f"   Approved by {who}. Scheduling for {when_text}...")

    uploaded = [publisher.upload_unpublished_photo(slide) for slide in slides]
    facebook = publisher.post_carousel_to_facebook(
        [item["photo_id"] for item in uploaded], text, publish_at=when
    )
    item = schedule.add(
        when=when, caption=text, image_path=slides[0],
        asset_name=f"carusel: {picked['theme']}", pillar=args.pillar,
        facebook_post_id=facebook["post_id"],
        image_url=[item["public_url"] for item in uploaded],
    )
    for asset in ordered_assets:
        library.mark_used(asset["id"])
    voice.remember(published_text=text, first_draft=text, pillar=args.pillar,
                   asset_name=f"carusel: {picked['theme']}", source="as_is")
    if plan and slot:
        planner.mark(plan, slot, "scheduled", note=f"{item['id']} · {when_text}")

    approval.update_status(
        message_id,
        f"🗓 Carusel programat de {who} pentru {when_text}\n"
        f"👍 Facebook: programat la Meta\n📸 Instagram: în coadă (id {item['id']})",
    )
    print("Done.")


if __name__ == "__main__":
    main()
