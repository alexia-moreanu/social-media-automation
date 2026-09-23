"""Put branded text on a photo and send it to Telegram for review.

    python3 scripts/make_graphic.py --pillar promo
    python3 scripts/make_graphic.py --file media/whatever.jpg --headline "..." --subline "..."

Nothing is published; the files land in output/.
"""

import argparse
import base64
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import approval, design, library  # noqa: E402

GUIDE = Path(__file__).resolve().parent.parent / "brand" / "brand_guide.md"


def approved_phrasings() -> str:
    """The single source of truth lives in the brand guide, not in this prompt."""
    text = GUIDE.read_text()
    return "## On-image text" + text.split("## On-image text", 1)[1].split("\n## ", 1)[0]


PROMPT = """You write the text that goes ON a photo for Happy Place, a family-run garden
party venue near Bucharest. This is on-image text, not a caption: it has to work in a
glance, in Romanian.

Never write a price on an image — send people to the phone for a personalised offer.
Brand facts you may use: 11:00-22:00, everything included
(veselă, pahare, grătar, scaune, espressor), three cottages seating 60 / 40-50 / 30,
open all year with indoor space, team buildings and courses get a personalised offer.
The pools are already packed away for this season — do not mention swimming.

Pillar: {pillar}. Today: {today}.

{phrasings}

Look at the photo and return strict JSON only:
{{"headline": "max 4 words, Amatic SC display font, Romanian",
  "subline": "max 9 words, one or two facts separated by ·",
  "why": "one line: why this works for the photo"}}

The headline is big and hand-drawn: short and punchy, no full sentences, no punctuation
at the end. The subline carries the concrete detail (a number, a time, a capacity).
"""


def write_text(image_path, pillar):
    from pipeline.caption import _encode_for_api

    data = _encode_for_api(image_path)
    media_type = "image/jpeg"
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-5", "max_tokens": 800, "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": data}},
                {"type": "text", "text": PROMPT.format(
                    pillar=pillar, today=dt.date.today().isoformat(),
                    phrasings=approved_phrasings())},
            ]}]},
        timeout=120,
    )
    response.raise_for_status()
    text = "".join(b["text"] for b in response.json()["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pillar", default="promo")
    parser.add_argument("--file", help="use this local image instead of picking from Drive")
    parser.add_argument("--folder", help="pick from this Drive subfolder")
    parser.add_argument("--headline")
    parser.add_argument("--subline")
    parser.add_argument("--white", action="store_true", help="white headline instead of yellow")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    load_dotenv()

    if args.file:
        path, name = Path(args.file), Path(args.file).name
    else:
        print("1. Picking a photo from Drive...")
        asset = library.pick_asset("image", folder=args.folder)
        path = library.download(asset)
        name = f"{asset['folder']}/{asset['name']}"
        print(f"   {name}")

    if args.headline:
        text = {"headline": args.headline, "subline": args.subline or "", "why": "scris manual"}
    else:
        print("2. Writing the on-image text...")
        text = write_text(path, args.pillar)
    print(f"   {text['headline']} / {text['subline']}")
    print(f"   why: {text['why']}")

    print("3. Rendering...")
    colour = design.WHITE if args.white else design.YELLOW
    post = design.compose(path, text["headline"], text["subline"],
                          size="post", headline_colour=colour)
    story = design.compose(path, text["headline"], text["subline"],
                           size="story", headline_colour=colour)
    print(f"   {post}\n   {story}")

    if not args.no_telegram:
        print("4. Sending to Telegram...")
        approval.send_photo_plain(post, f"🖼 Post 4:5 — {name}\n{text['headline']}")
        approval.send_photo_plain(story, "📱 Story 9:16 — aceeași imagine")
        print("   Sent.")


if __name__ == "__main__":
    main()
