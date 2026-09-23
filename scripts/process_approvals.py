"""Act on Telegram decisions for drafts that are waiting.

    python3 scripts/process_approvals.py            # one pass
    python3 scripts/process_approvals.py --watch 600  # keep listening for 10 minutes

Approve -> the post is scheduled (Facebook at Meta, Instagram in the local queue).
Reject  -> the bot asks why, and the reason is saved for the voice memory.
Edit    -> the bot asks what to change; the request is noted for the next build.
"""

import argparse
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import approval, pending, planner, publish_flow, voice  # noqa: E402


def slot_for(entry):
    if not entry.get("slot"):
        return None
    plan = planner.load(entry["slot"].get("month"))
    if not plan:
        return None
    for slot in plan["slots"]:
        if (slot["date"] == entry["slot"]["date"]
                and slot["time"] == entry["slot"]["time"]):
            return slot
    return None


def handle(callback):
    message_id = callback["message"]["message_id"]
    entry = next((e for e in pending.awaiting() if e["message_id"] == message_id), None)
    if not entry:
        return False

    who = callback["from"].get("first_name", "cineva")
    decision = callback["data"]
    requests.post(f"https://api.telegram.org/bot{approval.os.environ['TELEGRAM_BOT_TOKEN']}"
                  f"/answerCallbackQuery",
                  json={"callback_query_id": callback["id"]}, timeout=30)

    if decision == "approve":
        slot = slot_for(entry)
        scheduler = (publish_flow.schedule_carousel if entry["kind"] == "carousel"
                     else publish_flow.schedule_photo)
        try:
            item, when = scheduler(entry, slot)
        except RuntimeError as error:
            approval.update_status(message_id, f"⚠️ Nu s-a putut programa: {error}")
            pending.update(message_id, status="failed", note=str(error))
            print(f"  {message_id}: failed — {error}")
            return True
        from pipeline import schedule as sched
        pending.update(message_id, status="scheduled", queue_id=item["id"])
        approval.update_status(
            message_id,
            f"🗓 Programat de {who} pentru {sched.describe(when)}\n"
            f"👍 Facebook: programat la Meta\n📸 Instagram: în coadă (id {item['id']})")
        print(f"  {message_id}: scheduled for {sched.describe(when)}")
        return True

    if decision == "reject":
        approval.ask_for_reason(message_id)
        reason = approval.wait_for_text(120) or "(fără motiv)"
        voice.remember_rejection(rejected_text=entry["caption"], reason=reason,
                                 pillar=entry["pillar"], asset_name=entry["asset_name"])
        pending.update(message_id, status="rejected", note=reason)
        approval.update_status(message_id,
                               f"❌ Respins de {who}. Motivul e salvat:\n„{reason}”")
        print(f"  {message_id}: rejected — {reason}")
        return True

    if decision == "edit":
        approval.ask_for_feedback(message_id)
        feedback = approval.wait_for_text(180) or ""
        pending.update(message_id, status="needs_edit", note=feedback)
        approval.update_status(
            message_id,
            "✏️ Notat. Refac postarea cu observațiile astea la următoarea rulare:\n"
            f"„{feedback}”")
        print(f"  {message_id}: edit requested — {feedback}")
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", type=int, default=0,
                        help="keep listening this many seconds")
    args = parser.parse_args()
    load_dotenv()

    waiting = pending.awaiting()
    if not waiting:
        print("No drafts awaiting a decision.")
        return
    print(f"{len(waiting)} drafts awaiting a decision")

    api = f"https://api.telegram.org/bot{approval.os.environ['TELEGRAM_BOT_TOKEN']}"
    deadline = time.time() + max(args.watch, 1)
    offset, handled = None, 0
    while True:
        params = {"timeout": 20 if args.watch else 0,
                  "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        updates = requests.get(f"{api}/getUpdates", params=params, timeout=45).json()
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            callback = update.get("callback_query")
            if callback and handle(callback):
                handled += 1
        if time.time() >= deadline or not pending.awaiting():
            break
    print(f"Handled {handled} decisions. {len(pending.awaiting())} still waiting.")


if __name__ == "__main__":
    main()
