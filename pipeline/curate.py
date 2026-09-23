"""Curation: let Claude look at candidate clips and choose which belong in the reel.

Motion scoring alone rewards camera pans across empty rooms. Judging the actual frames
picks shots with colour, decor, people and life in them, and puts them in a sensible order.
"""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

import requests

MODEL = "claude-sonnet-5"
API = "https://api.anthropic.com/v1/messages"

PROMPT = """You are choosing shots for a 10-15 second Instagram reel for Happy Place,
a family-run garden party venue near Bucharest (kids' parties, baptisms, BBQs, team buildings).

You are shown one frame from each candidate clip, numbered in order.

Rate each clip 1-10 for how well it works in a reel that should make someone want to
book the venue:
- high: colourful decor, balloon arches, set tables, teepees, food, pools, people enjoying
  themselves, greenery, warm light, a sense of an event happening
- low: empty rooms, bare walls, close-ups of furniture or appliances, dim or grey frames,
  anything that looks like an estate agent photo

Then choose the best {shots} clips and put them in an order that works as a reel:
open on the single most eye-catching shot (people stop scrolling in the first second),
keep energy up in the middle, and end on a shot that leaves a good final impression.

Return strict JSON only:
{{"ratings": [{{"clip": 1, "score": 8, "why": "few words"}}, ...],
  "order": [3, 1, 7, 2, 5, 4],
  "opening_note": "one line: why that first shot earns the scroll-stop"}}
"""


def middle_frame(video_path: Path, out_path: Path, at_fraction=0.4):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video_path)], capture_output=True, text=True,
    )
    total = float(json.loads(result.stdout)["format"]["duration"])
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{total * at_fraction:.2f}",
         "-i", str(video_path), "-frames:v", "1", "-vf", "scale=320:-2", str(out_path)],
        capture_output=True,
    )
    return out_path


def choose_clips(clip_paths, shots=6):
    """Returns (ordered indexes into clip_paths, ratings, opening note)."""
    content = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for index, path in enumerate(clip_paths, start=1):
            frame = middle_frame(path, Path(tmpdir) / f"f{index}.jpg")
            if not frame.exists():
                continue
            content.append({"type": "text", "text": f"Clip {index}: {path.name}"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(frame.read_bytes()).decode(),
            }})
        content.append({"type": "text", "text": PROMPT.format(shots=shots)})

        response = requests.post(
            API,
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": MODEL, "max_tokens": 2000,
                  "messages": [{"role": "user", "content": content}]},
            timeout=180,
        )
    response.raise_for_status()
    text = "".join(b["text"] for b in response.json()["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(text)
    order = [i - 1 for i in result["order"] if 1 <= i <= len(clip_paths)]
    return order, result.get("ratings", []), result.get("opening_note", "")
