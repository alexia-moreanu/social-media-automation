"""Read the collected captions and propose new rules for the brand guide.

Run this every few weeks, once there are 10+ examples:
    python3 scripts/distill_voice.py

It only PRINTS suggestions — you decide what goes into brand/brand_guide.md.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import voice  # noqa: E402

PROMPT = """Below are real social media captions for Happy Place, a family-run event venue.
Some were written by Claude and approved as-is, some were corrected by the owners, and some
the owners wrote themselves. The owners' own words are the target voice.

{examples}

Here are the caption rules currently in the brand guide:

<current_rules>
{rules}
</current_rules>

Look for patterns in what the owners keep changing or writing differently from the drafts:
word choices, sentence length, how direct they are, what they include or leave out,
diacritics, punctuation, structure.

Write at most 5 concrete, specific rule changes that would make future drafts need fewer edits.
Each one: the rule in one line, then one line of evidence from the examples.
Skip anything already covered by the current rules. If the examples do not support a change,
say so instead of inventing one.
"""


def main():
    load_dotenv()
    entries = voice.load_examples(999)
    if len(entries) < 5:
        sys.exit(f"Only {len(entries)} captions saved so far. Come back after ~10 posts.")

    blocks = []
    for entry in entries:
        published = entry["published"].split("\n\n📞")[0].strip()
        block = f"<caption source=\"{entry['source']}\" pillar=\"{entry['pillar']}\">"
        if entry["source"] == "feedback" and entry.get("first_draft"):
            draft = entry["first_draft"].split("\n\n📞")[0].strip()
            block += f"\nClaude drafted: {draft}\nThey asked: {entry['feedback']}"
        block += f"\nPublished: {published}\n</caption>"
        blocks.append(block)

    guide = Path("brand/brand_guide.md").read_text()
    rules = guide.split("## Language", 1)[1].split("## Content pillars", 1)[0]

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-5",
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": PROMPT.format(examples="\n\n".join(blocks), rules=rules),
            }],
        },
        timeout=180,
    )
    response.raise_for_status()
    text = "".join(b["text"] for b in response.json()["content"] if b["type"] == "text")
    print(f"Based on {len(entries)} saved captions:\n")
    print(text)
    print("\nEdit brand/brand_guide.md yourself with whichever of these you agree with.")


if __name__ == "__main__":
    main()
