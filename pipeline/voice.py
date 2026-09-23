"""Voice memory: remembers how Alexia and Mihaela actually write.

Every approved caption is saved here, together with what Claude originally drafted and
any feedback given in Telegram. Future runs get the most recent real captions as examples,
so the writing drifts towards the family's voice instead of resetting every time.
"""

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "state" / "voice_examples.jsonl"
MAX_EXAMPLES = 12


def remember(*, published_text, first_draft, pillar, asset_name, feedback=None, source):
    """Record one finished caption.

    source: "as_is"     — approved exactly as Claude wrote it
            "feedback"  — Claude rewrote it after a human asked for changes
            "verbatim"  — a human wrote or pasted the caption themselves
    """
    STORE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": date.today().isoformat(),
        "pillar": pillar,
        "asset": asset_name,
        "source": source,
        "feedback": feedback,
        "first_draft": first_draft,
        "published": published_text,
    }
    with STORE.open("a") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def remember_rejection(*, rejected_text, reason, pillar, asset_name):
    """Record a caption that was turned down, and why. Negative examples teach too."""
    STORE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": date.today().isoformat(),
        "pillar": pillar,
        "asset": asset_name,
        "source": "rejected",
        "feedback": reason,
        "first_draft": rejected_text,
        "published": None,
    }
    with STORE.open("a") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_rejections(limit=6):
    if not STORE.exists():
        return []
    entries = [json.loads(line) for line in STORE.read_text().splitlines() if line.strip()]
    return [e for e in entries if e["source"] == "rejected"][-limit:]


def load_examples(limit=MAX_EXAMPLES):
    if not STORE.exists():
        return []
    entries = [json.loads(line) for line in STORE.read_text().splitlines() if line.strip()]
    entries = [e for e in entries if e["source"] != "rejected"]
    # Human-written and human-corrected captions teach more than untouched drafts.
    entries.sort(key=lambda e: (e["source"] == "as_is", e["date"]))
    return entries[-limit:]


def examples_block(limit=MAX_EXAMPLES) -> str:
    """The few-shot section injected into the caption prompt."""
    entries = load_examples(limit)
    if not entries and not load_rejections():
        return ""

    parts = [
        "\n## How we actually write (real published captions — match this voice)",
        "These were approved by the family. Copy the rhythm, sentence length, vocabulary and",
        "level of directness. Do not copy their content.",
    ]
    if not entries:
        parts = []
    for entry in entries:
        caption = entry["published"].split("\n\n📞")[0].strip()
        note = ""
        if entry["source"] == "verbatim":
            note = " (written by the family themselves — closest to the target voice)"
        elif entry["feedback"]:
            note = f" (after they asked: \"{entry['feedback'][:120]}\")"
        parts.append(f"\n<example pillar=\"{entry['pillar']}\"{note}>\n{caption}\n</example>")

    rejections = load_rejections()
    if rejections:
        parts.append("\n## Captions they REJECTED (never write like this again)")
        for entry in rejections:
            text = (entry["first_draft"] or "").split("\n\n📞")[0].strip()
            parts.append(f"\n<rejected reason=\"{entry['feedback']}\">\n{text}\n</rejected>")

    corrections = [e for e in entries if e["source"] == "feedback" and e.get("first_draft")]
    if corrections:
        parts.append("\n## Corrections they made (avoid repeating the mistake)")
        for entry in corrections[-4:]:
            before = entry["first_draft"].split("\n\n📞")[0].strip()
            after = entry["published"].split("\n\n📞")[0].strip()
            parts.append(
                f"\n<correction>\nDraft: {before}\nThey asked: {entry['feedback']}\n"
                f"Final: {after}\n</correction>"
            )
    return "\n".join(parts)
