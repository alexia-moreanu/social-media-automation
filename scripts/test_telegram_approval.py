"""Send one fake draft post to the Telegram approval group and wait for a button press.

Nothing is published to Facebook or Instagram — this only shows how approvals will look.

    python3 scripts/test_telegram_approval.py
"""

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

DRAFT = (
    "*Exemplu de postare* (test — nu se publică nicăieri)\n\n"
    "🌞 Vara la Happy Place înseamnă piscină, iarbă verde și copii fericiți.\n"
    "Rezervă-ți ziua perfectă: 0728 888 881\n\n"
    "#happyplace #petreceri #domnesti\n\n"
    "_Canal: Instagram + Facebook · Programat: mâine 18:00_"
)

POLL_SECONDS = 120


def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_APPROVAL_CHAT_ID", "").strip()
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN or TELEGRAM_APPROVAL_CHAT_ID is missing from .env")

    api = f"https://api.telegram.org/bot{token}"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Aprobă", "callback_data": "approve"},
            {"text": "❌ Respinge", "callback_data": "reject"},
        ]]
    }

    # Optional: pass an image path to see a draft with the picture attached,
    # e.g. python3 scripts/test_telegram_approval.py brand/assets/logo.png
    photo = sys.argv[1] if len(sys.argv) > 1 else None
    if photo:
        with open(photo, "rb") as handle:
            sent = requests.post(
                f"{api}/sendPhoto",
                data={
                    "chat_id": chat_id,
                    "caption": DRAFT,
                    "parse_mode": "Markdown",
                    "reply_markup": json.dumps(keyboard),
                },
                files={"photo": handle},
                timeout=60,
            ).json()
    else:
        sent = requests.post(
            f"{api}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": DRAFT,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            },
            timeout=30,
        ).json()
    if not sent.get("ok"):
        sys.exit(f"Telegram refused to send: {sent.get('description')}")

    message_id = sent["result"]["message_id"]
    print(f"Draft sent to the group. Waiting up to {POLL_SECONDS}s for someone to tap a button...")

    deadline = time.time() + POLL_SECONDS
    offset = None
    while time.time() < deadline:
        params = {"timeout": 20, "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        updates = requests.get(f"{api}/getUpdates", params=params, timeout=40).json()
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            callback = update.get("callback_query")
            if not callback or callback["message"]["message_id"] != message_id:
                continue

            decision = callback["data"]
            who = callback["from"].get("first_name", "cineva")
            requests.post(
                f"{api}/answerCallbackQuery",
                json={"callback_query_id": callback["id"], "text": "Mulțumim!"},
                timeout=30,
            )
            verdict = "✅ Aprobat" if decision == "approve" else "❌ Respins"
            endpoint = "editMessageCaption" if photo else "editMessageText"
            field = "caption" if photo else "text"
            requests.post(
                f"{api}/{endpoint}",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    field: f"{DRAFT}\n\n*{verdict} de {who}*",
                    "parse_mode": "Markdown",
                },
                timeout=30,
            )
            print(f"{who} tapped: {decision}")
            print("Approvals work. In the real pipeline, 'approve' is what triggers publishing.")
            return

    print("Nobody tapped a button in time. Rerun the script and tap one to finish the test.")


if __name__ == "__main__":
    main()
