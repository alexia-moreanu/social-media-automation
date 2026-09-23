"""Approval: sends a draft to the Telegram group and waits for a human decision."""

import json
import os
import time
from pathlib import Path

import requests


def _api():
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"


def _chat():
    return os.environ["TELEGRAM_APPROVAL_CHAT_ID"]


def send_draft(image_path: Path, caption: str, header: str) -> int:
    keyboard = {"inline_keyboard": [[
        {"text": "✅ Publică", "callback_data": "approve"},
        {"text": "✏️ Modifică", "callback_data": "edit"},
        {"text": "❌ Respinge", "callback_data": "reject"},
    ]]}
    text = f"{header}\n\n{caption}"
    if len(text) > 1024:  # Telegram caption limit
        text = text[:1015] + "\n[...]"
    with open(image_path, "rb") as handle:
        result = requests.post(
            f"{_api()}/sendPhoto",
            data={"chat_id": _chat(), "caption": text, "reply_markup": json.dumps(keyboard)},
            files={"photo": handle},
            timeout=120,
        ).json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram refused the draft: {result.get('description')}")
    return result["result"]["message_id"]


def wait_for_decision(message_id: int, timeout_seconds: int) -> tuple[str, str]:
    """Block until someone taps a button. Returns (decision, person)."""
    deadline = time.time() + timeout_seconds
    offset = None
    while time.time() < deadline:
        params = {"timeout": 25, "allowed_updates": '["callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        updates = requests.get(f"{_api()}/getUpdates", params=params, timeout=45).json()
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            callback = update.get("callback_query")
            if not callback or callback["message"]["message_id"] != message_id:
                continue
            who = callback["from"].get("first_name", "cineva")
            requests.post(
                f"{_api()}/answerCallbackQuery",
                json={"callback_query_id": callback["id"]},
                timeout=30,
            )
            return callback["data"], who
    return "timeout", ""


def ask_for_feedback(message_id: int) -> int:
    """Tell the group to reply with what should change. Returns the prompt message id."""
    result = requests.post(
        f"{_api()}/sendMessage",
        json={
            "chat_id": _chat(),
            "text": "✏️ Scrie aici ce să schimb (ca răspuns la acest mesaj sau direct în grup).",
            "reply_to_message_id": message_id,
            "reply_markup": {"force_reply": True},
        },
        timeout=30,
    ).json()
    return result["result"]["message_id"]


def ask_for_reason(message_id: int) -> int:
    """Ask why a draft was rejected, so the reason can be learned from."""
    result = requests.post(
        f"{_api()}/sendMessage",
        json={
            "chat_id": _chat(),
            "text": "❌ De ce nu e bun? Scrie pe scurt (ex: „ton prea formal”, „poza slabă”, "
                    "„informație greșită”) ca să învăț pentru data viitoare.",
            "reply_to_message_id": message_id,
            "reply_markup": {"force_reply": True},
        },
        timeout=30,
    ).json()
    return result["result"]["message_id"]


def wait_for_text(timeout_seconds: int) -> str | None:
    """Wait for the next normal text message in the group — the human's feedback."""
    deadline = time.time() + timeout_seconds
    offset = None
    while time.time() < deadline:
        params = {"timeout": 25, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        updates = requests.get(f"{_api()}/getUpdates", params=params, timeout=45).json()
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            if text and str(message.get("chat", {}).get("id")) == str(_chat()):
                if text.startswith("/"):
                    continue
                return text
    return None


def update_status(message_id: int, note: str):
    requests.post(
        f"{_api()}/editMessageReplyMarkup",
        json={"chat_id": _chat(), "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        timeout=30,
    )
    requests.post(
        f"{_api()}/sendMessage",
        json={
            "chat_id": _chat(),
            "text": note,
            "reply_to_message_id": message_id,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )


def update_status_plain(note: str):
    """A standalone message in the group (used by the scheduler worker)."""
    requests.post(
        f"{_api()}/sendMessage",
        json={"chat_id": _chat(), "text": note, "disable_web_page_preview": True},
        timeout=30,
    )


def send_video(video_path: Path, caption: str):
    """Send a finished video to the group (no buttons — review only)."""
    with open(video_path, "rb") as handle:
        result = requests.post(
            f"{_api()}/sendVideo",
            data={"chat_id": _chat(), "caption": caption[:1024], "supports_streaming": True},
            files={"video": handle},
            timeout=300,
        ).json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram refused the video: {result.get('description')}")
    return result["result"]["message_id"]


def send_photo_plain(image_path: Path, caption: str):
    """Send an image to the group without approval buttons."""
    with open(image_path, "rb") as handle:
        result = requests.post(
            f"{_api()}/sendPhoto",
            data={"chat_id": _chat(), "caption": caption[:1024]},
            files={"photo": handle},
            timeout=120,
        ).json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram refused the image: {result.get('description')}")
    return result["result"]["message_id"]


def send_album(image_paths, header: str, caption: str):
    """Send the carousel as a Telegram album, then the caption with the buttons."""
    media, files = [], {}
    for index, path in enumerate(image_paths[:10]):
        key = f"photo{index}"
        entry = {"type": "photo", "media": f"attach://{key}"}
        if index == 0:
            entry["caption"] = header  # Telegram rejects a null caption field
        media.append(entry)
        files[key] = open(path, "rb")
    try:
        result = requests.post(
            f"{_api()}/sendMediaGroup",
            data={"chat_id": _chat(), "media": json.dumps(media)},
            files=files,
            timeout=300,
        ).json()
    finally:
        for handle in files.values():
            handle.close()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram refused the album: {result.get('description')}")

    keyboard = {"inline_keyboard": [[
        {"text": "✅ Publică", "callback_data": "approve"},
        {"text": "✏️ Modifică", "callback_data": "edit"},
        {"text": "❌ Respinge", "callback_data": "reject"},
    ]]}
    posted = requests.post(
        f"{_api()}/sendMessage",
        json={"chat_id": _chat(), "text": caption[:4000], "reply_markup": keyboard},
        timeout=60,
    ).json()
    return posted["result"]["message_id"]
