"""Create one post: pick a photo, write a caption, ask for approval, publish.

    python3 run_pipeline.py --pillar mood            # full run, waits for the Telegram buttons
    python3 run_pipeline.py --pillar mood --dry-run  # draft only, never publishes

Nothing is ever published unless somebody taps "Publică" in the Telegram group.
"""

import argparse
import datetime as dt
import sys

from dotenv import load_dotenv

from pipeline import (approval, caption as caption_writer, factcheck, library,
                      pending, planner, publisher, schedule, voice)


def looks_like_full_caption(message: str) -> bool:
    """Decide whether the human wrote the caption itself, or just gave advice.

    Starting the message with "=" always means "use my text exactly as it is".
    """
    if message.startswith("="):
        return True
    if "#" in message or "0728 888 881" in message:
        return True
    # Several sentences across multiple paragraphs reads as a caption, not an instruction.
    return message.count("\n\n") >= 1 and len(message) > 180


def use_verbatim(message: str) -> dict:
    """Take the human's own text as the caption, keeping their words exactly."""
    message = message.lstrip("=").strip()
    lines = [line.strip() for line in message.strip().splitlines()]
    hashtags = []
    body = []
    for line in lines:
        if line.startswith("#"):
            hashtags += line.split()
        elif "0728 888 881" in line:
            continue  # the CTA is added back by render()
        else:
            body.append(line)
    text = "\n".join(body).strip()
    return {
        "hook": text[:60],
        "caption": text,
        "hashtags": hashtags or ["#happyplace", "#locatieevenimente", "#ilfov"],
        "value": "scris manual",
        "image_notes": "(text scris de om, nu de Claude)",
    }

SEASONS = {
    (9, 10): "Autumn garden parties, team buildings, courses & workshops; start promoting December events",
    (11, 12): "Christmas / end-of-year company parties, indoor kids' parties, cozy mood content",
    (1, 3): "Courses, workshops, therapy groups, indoor birthdays; weekday offers; book summer dates early",
    (4, 5): "Baptisms, moț, small weddings; spring garden reopening",
    (6, 8): "Pools, kids' parties, BBQs — peak garden season",
}


def season_for(month):
    for (start, end), text in SEASONS.items():
        if start <= month <= end:
            return text
    return "Open all year"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pillar", default="mood", choices=list(caption_writer.PILLARS))
    parser.add_argument("--folder", help="only use assets from this Drive subfolder")
    parser.add_argument("--dry-run", action="store_true", help="draft only, no publishing")
    parser.add_argument("--wait", type=int, default=900, help="seconds to wait for approval")
    parser.add_argument("--no-wait", action="store_true",
                        help="send the draft and exit; approvals are handled later by "
                             "scripts/process_approvals.py")
    parser.add_argument("--from-plan", action="store_true",
                        help="build the next slot from the monthly plan instead of --pillar")
    parser.add_argument("--slot", help="build this exact slot: YYYY-MM-DD/HH:MM")
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
        args.folder = slot.get("folder") or args.folder
        print(f"0. Plan slot: {slot['date']} {slot['time']} · {slot['format']} · "
              f"{slot['pillar']}\n   temă: {slot['theme']}\n   {slot.get('note', '')}")
        if slot["format"] != "photo":
            print(f"   NOTE: the plan asks for a {slot['format']}. "
                  f"Use scripts/make_{'carousel' if slot['format'] == 'carousel' else 'reel'}.py "
                  f"for that — continuing here as a single photo.")

    if slot and slot.get("assets"):
        asset = library.asset_by_id(slot["assets"][0])
        path = library.download(asset)
        print(f"1. Using the photo the plan chose: {asset['name']}")
    else:
        print("1. Picking a photo from Drive...")
        asset = library.pick_asset("image", folder=args.folder)
        path = library.download(asset)
        print(f"   {asset['folder']}/{asset['name']}")

    feedback, previous, round_number, verbatim = None, None, 1, None
    first_draft, last_feedback, wrote_it_themselves = None, None, False
    while True:
        if verbatim:
            print(f"2. Using your own caption (round {round_number})...")
            draft, verbatim = verbatim, None
        else:
            print(f"2. Writing the caption with Claude (round {round_number})...")
            theme_brief = None
            if slot and not feedback:
                theme_brief = (f"This post is planned as: {slot['theme']}. "
                               f"Direction: {slot.get('note', '')}")
            draft = caption_writer.build_caption(
                path, args.pillar, season_for(today.month), today.isoformat(),
                feedback=feedback or theme_brief,
                previous=previous or "(no previous draft)",
            )
        text = caption_writer.render(draft)
        if first_draft is None:
            first_draft = text
        print(f"   photo seen as: {draft['image_notes']}")
        print(f"   value for reader: {draft['value']}")
        print("   ---")
        print("   " + text.replace("\n", "\n   "))
        print("   ---")

        print("   Checking the facts...")
        facts = factcheck.check(text)
        facts_note = factcheck.summary(facts)
        if facts_note:
            print("   " + facts_note.replace("\n", "\n   "))
        else:
            print("   facts: clean")

        header = (
            f"🗂 {asset['folder']}/{asset['name']}"
            f"\n🏷 pilon: {args.pillar}"
            f"\n📍 Facebook + Instagram"
            + (f"\n🔁 versiunea {round_number}" if round_number > 1 else "")
            + ("\n⚠️ TEST — nu se publică" if args.dry_run else "")
            + (f"\n\n{facts_note}" if facts_note else "")
        )

        print("3. Sending the draft to Telegram...")
        message_id = approval.send_draft(path, text, header)

        if args.dry_run:
            print("   Dry run: stopping here. Nothing will be published.")
            return

        if args.no_wait:
            pending.add(
                message_id=message_id, kind="photo", caption=text,
                first_draft=first_draft, image_path=str(path),
                asset_name=f"{asset['folder']}/{asset['name']}",
                asset_ids=[asset["id"]], pillar=args.pillar,
                slot=({"date": slot["date"], "time": slot["time"],
                       "month": plan["month"]} if slot else None),
            )
            if plan and slot:
                # Mark it drafted so a rerun does not send the same post twice.
                planner.mark(plan, slot, "drafted", note="așteaptă decizia în Telegram")
            print("   Draft sent. Decision will be handled by process_approvals.py")
            return

        print(f"4. Waiting up to {args.wait}s for someone to tap a button...")
        decision, who = approval.wait_for_decision(message_id, args.wait)

        if decision == "edit":
            approval.ask_for_feedback(message_id)
            print("   Edit requested — waiting for the written feedback in the group...")
            feedback = approval.wait_for_text(args.wait)
            if not feedback:
                approval.update_status(message_id, "⌛️ N-a venit niciun mesaj. M-am oprit.")
                print("   No feedback arrived — stopping.")
                return
            print(f"   Feedback: {feedback}")
            previous, round_number = text, round_number + 1
            last_feedback = feedback
            if looks_like_full_caption(feedback):
                print("   Looks like a finished caption — using your words exactly.")
                verbatim = use_verbatim(feedback)
                wrote_it_themselves = True
            continue

        if decision == "reject":
            approval.ask_for_reason(message_id)
            reason = approval.wait_for_text(180) or "(fără motiv)"
            voice.remember_rejection(
                rejected_text=text, reason=reason, pillar=args.pillar,
                asset_name=f"{asset['folder']}/{asset['name']}",
            )
            approval.update_status(
                message_id,
                f"❌ Respins de {who}. Motivul e salvat, ca să nu se repete:\n„{reason}”",
            )
            print(f"   rejected — reason saved: {reason}")
            return

        if decision != "approve":
            approval.update_status(
                message_id, "⌛️ Nimeni nu a apăsat un buton. Nu s-a publicat nimic."
            )
            print("   timeout — nothing was published.")
            return
        break

    if slot:
        planned = dt.datetime.fromisoformat(f"{slot['date']}T{slot['time']}").replace(
            tzinfo=schedule.TZ)
        when = planned if planned > dt.datetime.now(schedule.TZ) else schedule.next_free_slot()
    else:
        when = schedule.next_free_slot()
    when_text = schedule.describe(when)
    print(f"   Approved by {who}. Scheduling for {when_text}...")

    facebook = publisher.post_to_facebook(path, text, publish_at=when)
    item = schedule.add(
        when=when,
        caption=text,
        image_path=path,
        asset_name=f"{asset['folder']}/{asset['name']}",
        pillar=args.pillar,
        facebook_post_id=facebook["photo_id"],
        image_url=facebook["public_url"],
    )

    library.mark_used(asset["id"])
    voice.remember(
        published_text=text,
        first_draft=first_draft,
        pillar=args.pillar,
        asset_name=f"{asset['folder']}/{asset['name']}",
        feedback=last_feedback,
        source="verbatim" if wrote_it_themselves else ("feedback" if last_feedback else "as_is"),
    )
    print(f"   Voice memory: {len(voice.load_examples(999))} captions learned so far.")

    if plan and slot:
        planner.mark(plan, slot, "scheduled", note=f"{item['id']} · {when_text}")
    approval.update_status(
        message_id,
        f"🗓 Programat de {who} pentru {when_text}\n"
        f"👍 Facebook: programat direct la Meta\n"
        f"📸 Instagram: se publică automat la aceeași oră (id {item['id']})",
    )
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError) as error:
        sys.exit(f"Pipeline stopped: {error}")
