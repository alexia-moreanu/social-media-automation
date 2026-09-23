"""Catalogue: look at every asset in Drive once and record what it actually shows.

This is the foundation for content-first planning. Instead of inventing a theme and
hoping the footage exists, the planner reads this catalogue and proposes posts that the
library can genuinely support.

Results are cached per Drive file id, so a rerun only costs money for new files.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import library, llm

ROOT = Path(__file__).resolve().parent.parent
CATALOG_FILE = ROOT / "state" / "catalog.json"
BATCH = 10
THUMB_WIDTH = 300

PROMPT = """You are cataloguing the media library of Happy Place, a family-run garden
party venue near Bucharest (kids' parties, baptisms, "tăierea moțului", small weddings,
BBQs, team buildings, courses, workshops). Three cottages: Verde (elegant, baptisms),
Albastră (cozy, birthdays), Galbenă (small, intimate, cats).

For each numbered image, record what is actually visible. Be literal and specific —
this catalogue decides what gets posted, so a wrong label means a wrong post.

Return strict JSON only:
{"assets": [{"n": 1,
             "subject": "what is in the frame, in Romanian, max 10 words",
             "event": "botez | petrecere copii | petrecere adulti | team building | "
                      "grătar | curs/workshop | fără eveniment | necunoscut",
             "season": "primăvară | vară | toamnă | iarnă | neclar",
             "setting": "exterior | interior | ambele",
             "people": true/false,
             "kids": true/false,
             "quality": 1-10,
             "good_for": ["reel","carousel","photo","story"],
             "note": "one short line: why it is or is not usable"}]}

Quality scale: 9-10 striking, publishable as-is; 7-8 solid, colour and subject;
5-6 usable filler; 3-4 weak (empty rooms, clutter, bad light); 1-2 unusable
(blurry, dark, duplicate-looking, personal snapshots that say nothing about the venue).
Season: judge from the foliage, light and clothing, not the file name.
"""


def _thumbnail(path: Path, out: Path) -> Path:
    if path.suffix.lower() in {".mov", ".mp4", ".m4v"}:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", str(out)],
            capture_output=True,
        )
        return out if out.exists() else None
    image = Image.open(path).convert("RGB")
    ratio = THUMB_WIDTH / image.width
    image.resize((THUMB_WIDTH, round(image.height * ratio)), Image.LANCZOS).save(
        out, quality=75)
    return out


def load():
    if CATALOG_FILE.exists():
        return json.loads(CATALOG_FILE.read_text())
    return {}


def save(catalog):
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))


def scan(limit=None, only_new=True, kinds=("image", "video"), progress=print):
    """Describe assets that are not catalogued yet. Returns the whole catalogue."""
    catalog = load()
    assets = []
    for kind in kinds:
        assets += library.list_media(kind)
    todo = [a for a in assets if not (only_new and a["id"] in catalog)]
    if limit:
        todo = todo[:limit]
    progress(f"{len(catalog)} already catalogued, {len(todo)} to look at")

    with tempfile.TemporaryDirectory() as tmpdir:
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            content, kept = [], []
            for index, asset in enumerate(batch, start=1):
                try:
                    path = library.download(asset)
                    thumb = _thumbnail(path, Path(tmpdir) / f"t{index}.jpg")
                except Exception as error:  # a broken or unsupported file
                    progress(f"   skipped {asset['name']}: {error}")
                    continue
                if not thumb:
                    continue
                kept.append(asset)
                content.append({"type": "text",
                                "text": f"Image {len(kept)}: {asset['name']}"})
                content.append(llm.encode_image(thumb))
            if not kept:
                continue
            content.append({"type": "text", "text": PROMPT})

            try:
                result = llm.call_json(content, max_tokens=8000)
            except llm.BillingError:
                progress("   STOPPED: the Anthropic account is out of credit. "
                         "Top up at console.anthropic.com, then rerun — "
                         f"{len(catalog)} assets are already saved.")
                return catalog
            except Exception as error:
                # One bad file (odd colour profile, huge dimensions, corrupt frame) used
                # to kill the whole scan. Fall back to one-at-a-time so the rest survives.
                progress(f"   batch of {len(kept)} failed ({error}) — retrying singly")
                result = {"assets": []}
                for position, asset in enumerate(kept, start=1):
                    single = [content[(position - 1) * 2], content[(position - 1) * 2 + 1],
                              {"type": "text", "text": PROMPT}]
                    try:
                        one = llm.call_json(single, max_tokens=2000)
                    except llm.BillingError:
                        progress("   STOPPED: out of API credit. "
                                 f"{len(catalog)} assets saved so far.")
                        save(catalog)
                        return catalog
                    except Exception as inner:
                        progress(f"      skipped {asset['name']}: {inner}")
                        continue
                    for row in one.get("assets", []):
                        row["n"] = position
                        result["assets"].append(row)

            for row in result.get("assets", []):
                position = row.get("n", 0) - 1
                if not 0 <= position < len(kept):
                    continue
                asset = kept[position]
                catalog[asset["id"]] = {
                    "id": asset["id"],
                    "name": asset["name"],
                    "folder": asset["folder"].strip(),
                    "kind": "video" if asset["mimeType"].startswith("video/") else "photo",
                    "taken_at": library.taken_at(asset),
                    **{k: v for k, v in row.items() if k != "n"},
                }
            save(catalog)
            progress(f"   catalogued {min(start + BATCH, len(todo))}/{len(todo)}")
    return catalog


def summary(catalog=None, min_quality=6):
    """What the library actually contains — the planner's view of reality."""
    catalog = catalog or load()
    used = set(library._used())
    rows = [a for a in catalog.values() if a["id"] not in used]
    good = [a for a in rows if (a.get("quality") or 0) >= min_quality]

    def tally(field):
        counts = {}
        for asset in good:
            value = asset.get(field)
            for item in (value if isinstance(value, list) else [value]):
                if item:
                    counts[item] = counts.get(item, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    return {
        "total_catalogued": len(rows),
        "usable": len(good),
        "by_event": tally("event"),
        "by_season": tally("season"),
        "by_kind": tally("kind"),
        "with_people": sum(1 for a in good if a.get("people")),
        "with_kids": sum(1 for a in good if a.get("kids")),
        "top": sorted(good, key=lambda a: -(a.get("quality") or 0))[:40],
    }
