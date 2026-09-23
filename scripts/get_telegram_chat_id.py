"""Find the Telegram chat ID for the approval group.

Send a message starting with "/" in the group (for example /start), then run:
    python3 scripts/get_telegram_chat_id.py

Copy the printed ID into TELEGRAM_APPROVAL_CHAT_ID in .env.
"""

import os
import sys

import requests
from dotenv import load_dotenv


def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is empty in .env — paste the token from @BotFather first.")

    api = f"https://api.telegram.org/bot{token}"

    me = requests.get(f"{api}/getMe", timeout=30).json()
    if not me.get("ok"):
        sys.exit(f"Telegram rejected the token: {me.get('description')}")
    print(f"Bot: @{me['result']['username']} ({me['result']['first_name']})\n")

    updates = requests.get(f"{api}/getUpdates", timeout=30).json()
    if not updates.get("ok"):
        sys.exit(f"Telegram error: {updates.get('description')}")

    chats = {}
    for update in updates["result"]:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat")
        if chat:
            chats[chat["id"]] = chat

    if not chats:
        sys.exit(
            "No messages seen yet.\n"
            "  - In the approval group, send a message starting with / (for example /start).\n"
            "  - Make sure the bot is a member of the group.\n"
            "  - Then run this script again."
        )

    print("Chats the bot has seen:")
    for chat_id, chat in chats.items():
        title = chat.get("title") or " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        )
        print(f"   {chat_id}   {chat['type']:<10} {title}")

    groups = [cid for cid, chat in chats.items() if chat["type"] in ("group", "supergroup")]
    print()
    if len(groups) == 1:
        print(f"Put this in .env:  TELEGRAM_APPROVAL_CHAT_ID={groups[0]}")
        print("(Group IDs start with a minus sign — keep it.)")
    else:
        print("Pick the approval group above and copy its ID into TELEGRAM_APPROVAL_CHAT_ID.")


if __name__ == "__main__":
    main()
