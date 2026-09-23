"""Library: finds and downloads media from the Google Drive content folder."""

import json
import os
import random
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT / "media"
STATE_FILE = ROOT / "state" / "used_assets.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Folders whose photos are already sized for the web; "Print" holds the huge originals.
PREFERRED_FOLDERS = ["Web size", "working", "casuta verde video promovare", "gradinarit"]


def _drive():
    credentials = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials)


def list_media(kind="image"):
    """Walk the content folder recursively and return every photo (or video)."""
    drive = _drive()
    found, queue = [], [(os.environ["DRIVE_CONTENT_FOLDER_ID"], "")]
    while queue:
        folder_id, folder_name = queue.pop()
        page_token = None
        while True:
            response = drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=("nextPageToken, files(id,name,mimeType,size,createdTime,"
                        "modifiedTime,parents,imageMediaMetadata/time,"
                        "videoMediaMetadata)"),
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            for item in response.get("files", []):
                if item["mimeType"] == "application/vnd.google-apps.folder":
                    queue.append((item["id"], item["name"]))
                elif item["mimeType"].startswith(f"{kind}/"):
                    item["folder"] = folder_name
                    found.append(item)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    return found


def _used():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def mark_used(file_id):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    used = _used() | {file_id}
    STATE_FILE.write_text(json.dumps(sorted(used), indent=2))


def asset_by_id(file_id):
    """One asset, looked up directly — the plan names the exact files to use."""
    item = _drive().files().get(
        fileId=file_id,
        fields=("id,name,mimeType,size,createdTime,modifiedTime,"
                "imageMediaMetadata/time,videoMediaMetadata"),
    ).execute()
    item["folder"] = ""
    return item


def assets_by_ids(file_ids):
    return [asset_by_id(file_id) for file_id in file_ids]


def taken_at(asset):
    """Best guess at when this was shot: EXIF first, then Drive timestamps."""
    exif = (asset.get("imageMediaMetadata") or {}).get("time")
    if exif:  # EXIF format: 2026:08:14 18:32:01
        return exif.replace(":", "-", 2).replace(" ", "T")
    video_time = (asset.get("videoMediaMetadata") or {}).get("creationTime")
    return video_time or asset.get("createdTime") or asset.get("modifiedTime") or ""


def unused(assets):
    """Filter out anything already posted."""
    used = _used()
    return [a for a in assets if a["id"] not in used]


def pick_asset(kind="image", folder=None):
    """Choose one asset that has not been posted before."""
    assets = [a for a in list_media(kind) if a["id"] not in _used()]
    if folder:
        wanted = folder.strip().casefold()
        assets = [a for a in assets if a["folder"].strip().casefold() == wanted]
    if not assets:
        raise RuntimeError("No unused assets left — clear state/used_assets.json or add media.")

    preferred_names = {f.strip().casefold() for f in PREFERRED_FOLDERS}
    preferred = [a for a in assets if a["folder"].strip().casefold() in preferred_names]
    return random.choice(preferred or assets)


def _to_jpeg(path: Path) -> Path:
    """HEIC is fine in Drive but useless downstream: Claude, Instagram and Facebook
    all want JPEG. Convert once, next to the original."""
    from PIL import Image

    jpeg = path.with_suffix(".jpg")
    if not jpeg.exists():
        Image.open(path).convert("RGB").save(jpeg, quality=92)
    return jpeg


def download(asset):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target = MEDIA_DIR / f"{asset['id']}_{asset['name']}".replace("/", "_")
    if target.exists():
        return _to_jpeg(target) if target.suffix.lower() in {".heic", ".heif"} else target
    request = _drive().files().get_media(fileId=asset["id"])
    with open(target, "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    if target.suffix.lower() in {".heic", ".heif"}:
        return _to_jpeg(target)
    return target
