"""Drafts waiting for a human decision in Telegram.

A month of content is ~15 drafts. Blocking the builder on each approval would mean
sitting at the terminal all evening, so drafts are sent, recorded here, and picked up
later by scripts/process_approvals.py when somebody actually taps a button.
"""

import json
from datetime import datetime
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent / "state" / "pending.json"


def load():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return []


def save(entries):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(entries, ensure_ascii=False, indent=2))


def add(**entry):
    entries = load()
    entry.setdefault("created", datetime.now().isoformat())
    entry.setdefault("status", "awaiting")
    entries.append(entry)
    save(entries)
    return entry


def awaiting():
    return [e for e in load() if e["status"] == "awaiting"]


def update(message_id, **changes):
    entries = load()
    for entry in entries:
        if entry["message_id"] == message_id:
            entry.update(changes)
    save(entries)
