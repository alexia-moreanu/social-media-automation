"""Reorganise the Drive content folder into categories the pipeline can use.

    python3 scripts/organise_drive.py --plan      # show what would move, change nothing
    python3 scripts/organise_drive.py --apply     # do it
    python3 scripts/organise_drive.py --undo      # put everything back

Before moving anything, every file's current parent is written to
state/drive_move_manifest.json, so --undo can restore the previous layout exactly.

Categories come from the catalogue (what each file actually shows), not from filenames.
A file lands in exactly one folder, because Drive files have one parent.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import catalog, library  # noqa: E402

MANIFEST = Path(__file__).resolve().parent.parent / "state" / "drive_move_manifest.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Event label in the catalogue -> folder name. Order matters: first match wins.
EVENT_FOLDERS = {
    "botez": "Botezuri și moț",
    "petrecere copii": "Petreceri copii",
    "petrecere adulti": "Petreceri adulți",
    "team building": "Team building și cursuri",
    "curs/workshop": "Team building și cursuri",
    "grătar": "Grătar și mâncare",
}

QUALITY_ARCHIVE = 4      # at or below this, the asset goes to the archive
RECENT_MONTHS = 6        # what "recent" means when prioritising content


def move_file(service, file_id, add_parent, remove_parent, attempts=4):
    """Drive returns transient 500s on long move runs; retry before giving up."""
    for attempt in range(attempts):
        try:
            service.files().update(
                fileId=file_id, addParents=add_parent,
                removeParents=remove_parent, fields="id",
            ).execute()
            return True
        except HttpError as error:
            if error.resp.status < 500 and error.resp.status != 429:
                raise
            if attempt == attempts - 1:
                return False
            time.sleep(2 ** attempt)
    return False


def drive():
    credentials = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES)
    return build("drive", "v3", credentials=credentials)


def category_for(asset):
    """Which folder this asset belongs in, based on what it shows."""
    quality = asset.get("quality") or 0
    kind = "Video" if asset.get("kind") == "video" else "Foto"

    # The photographer's high-res originals are duplicates of the "Web size" set at
    # print resolution. They stay apart: posting them would mean huge uploads.
    if (asset.get("folder") or "").strip().casefold() == "print":
        return "Print (originale mari, nu pentru postat)"

    if quality <= QUALITY_ARCHIVE:
        return "Arhivă (calitate slabă)"

    event = (asset.get("event") or "").strip().lower()
    for label, folder in EVENT_FOLDERS.items():
        if label in event:
            return f"{kind}/{folder}"

    # No event in the frame: sort by what the shot is of.
    setting = (asset.get("setting") or "").lower()
    subject = (asset.get("subject") or "").lower()
    detail_words = ("detaliu", "decor", "flori", "baloane", "masă", "aranjament",
                    "lampioane", "ghirland", "tort", "pahar")
    if any(word in subject for word in detail_words):
        return f"{kind}/Detalii și decor"
    if "interior" in setting:
        return f"{kind}/Spații interioare"
    return f"{kind}/Locație și grădină"


def ensure_folder(service, name, parent, cache, dry_run):
    """Find or create one folder, caching by path so we create each only once."""
    key = f"{parent}/{name}"
    if key in cache:
        return cache[key]
    query = (f"name = '{name}' and '{parent}' in parents and trashed = false "
             f"and mimeType = 'application/vnd.google-apps.folder'")
    found = service.files().list(q=query, fields="files(id,name)").execute().get("files", [])
    if found:
        cache[key] = found[0]["id"]
        return cache[key]
    if dry_run:
        cache[key] = f"(new:{name})"
        return cache[key]
    created = service.files().create(
        body={"name": name, "parents": [parent],
              "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    cache[key] = created["id"]
    return created["id"]


def ensure_path(service, path, root, cache, dry_run):
    parent = root
    for part in path.split("/"):
        parent = ensure_folder(service, part, parent, cache, dry_run)
    return parent


def collect():
    """Every asset with its catalogue entry and current parents."""
    data = catalog.load()
    assets = library.list_media("image") + library.list_media("video")
    rows = []
    for asset in assets:
        entry = data.get(asset["id"])
        if not entry:
            continue  # not catalogued yet — leave it where it is
        # parents come from the bulk listing: one call per file would be ~1700 requests
        parents = asset.get("parents") or []
        rows.append({
            "id": asset["id"],
            "name": asset["name"],
            "from": parents[0] if parents else None,
            "to_path": category_for(entry),
            "quality": entry.get("quality"),
            "taken_at": entry.get("taken_at") or library.taken_at(asset),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true", help="show the moves, change nothing")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args()
    load_dotenv()

    if args.undo:
        if not MANIFEST.exists():
            sys.exit("No manifest — nothing to undo.")
        service = drive()
        moves = [m for m in json.loads(MANIFEST.read_text())["moves"] if m.get("done")]
        for index, move in enumerate(moves, start=1):
            move_file(service, move["id"], move["from"], move["to"])
            if index % 50 == 0:
                print(f"   restored {index}/{len(moves)}")
        print(f"Restored {len(moves)} files to their original folders.")
        return

    rows = collect()
    if not rows:
        sys.exit("Nothing catalogued yet — run scripts/scan_library.py first.")

    groups = {}
    for row in rows:
        groups.setdefault(row["to_path"], []).append(row)

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_MONTHS * 30)
    print(f"{len(rows)} catalogued assets\n")
    for path, items in sorted(groups.items()):
        recent = sum(1 for i in items
                     if (i["taken_at"] or "") > cutoff.strftime("%Y-%m-%d"))
        print(f"  {path:<34} {len(items):>4} files  ({recent} from the last "
              f"{RECENT_MONTHS} months)")

    if args.plan or not args.apply:
        print("\n--plan only. Rerun with --apply to move the files.")
        return

    service = drive()
    root = os.environ["DRIVE_CONTENT_FOLDER_ID"]

    if MANIFEST.exists():
        # An interrupted run leaves a manifest: resume it rather than recomputing,
        # so the record of where each file came from stays accurate.
        manifest = json.loads(MANIFEST.read_text())
        moves = manifest["moves"]
        # Reconcile with reality: an interrupted run may have moved files before it
        # could record them. Ask Drive where each file actually is now.
        current = {}
        for asset in library.list_media("image") + library.list_media("video"):
            parents = asset.get("parents") or []
            current[asset["id"]] = parents[0] if parents else None
        reconciled = 0
        for move in moves:
            if not move.get("done") and current.get(move["id"]) == move["to"]:
                move["done"] = True
                reconciled += 1
        if reconciled:
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        remaining = [m for m in moves if not m.get("done")]
        print(f"\nResuming: {reconciled} already moved, {len(remaining)} of "
              f"{len(moves)} left")
    else:
        cache, moves = {}, []
        for path, items in sorted(groups.items()):
            target = ensure_path(service, path, root, cache, dry_run=False)
            for row in items:
                if row["from"] == target or not row["from"]:
                    continue
                moves.append({"id": row["id"], "name": row["name"],
                              "from": row["from"], "to": target})
        manifest = {"created": datetime.now().isoformat(), "moves": moves}
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"\nManifest saved ({len(moves)} moves) — undo with --undo")

    done, failed = 0, []
    for index, move in enumerate(moves, start=1):
        if move.get("done"):
            continue
        if move_file(service, move["id"], move["to"], move["from"]):
            move["done"] = True
            done += 1
        else:
            failed.append(move["name"])
        if done and done % 50 == 0:
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            print(f"   moved {index}/{len(moves)}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    print(f"Moved {done} files. {len(failed)} failed.")
    for name in failed[:10]:
        print(f"   failed: {name}")
    if failed:
        print("Rerun --apply to retry the failures.")


if __name__ == "__main__":
    main()
