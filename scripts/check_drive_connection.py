"""Check that the pipeline can read the Google Drive content folder. Read-only.

    python3 scripts/check_drive_connection.py
"""

import os
import sys
from collections import Counter

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main():
    load_dotenv()
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    folder_id = os.getenv("DRIVE_CONTENT_FOLDER_ID", "").strip()
    if not key_file or not folder_id:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_FILE or DRIVE_CONTENT_FOLDER_ID is missing from .env")
    if not os.path.exists(key_file):
        sys.exit(f"Key file not found: {key_file}")

    credentials = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    print(f"Service account: {credentials.service_account_email}\n")
    drive = build("drive", "v3", credentials=credentials)

    try:
        folder = drive.files().get(
            fileId=folder_id, fields="id,name,mimeType", supportsAllDrives=True
        ).execute()
    except HttpError as error:
        if error.resp.status == 404:
            sys.exit(
                "The folder was not found.\n"
                "  - Share the Drive folder with the service account email above (Viewer).\n"
                "  - Check DRIVE_CONTENT_FOLDER_ID is the id from the folder's URL\n"
                "    (drive.google.com/drive/folders/THIS_PART)."
            )
        sys.exit(f"Google API error: {error}")

    print(f"Folder: {folder['name']}")

    files, page_token = [], None
    while True:
        response = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id,name,mimeType,size,videoMediaMetadata/durationMillis)",
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    if not files:
        print("\nThe folder is empty, or its files live in subfolders.")
        return

    kinds = Counter()
    total_bytes = 0
    for item in files:
        mime = item["mimeType"]
        if mime == "application/vnd.google-apps.folder":
            kinds["subfolders"] += 1
        elif mime.startswith("image/"):
            kinds["photos"] += 1
        elif mime.startswith("video/"):
            kinds["videos"] += 1
        else:
            kinds["other"] += 1
        total_bytes += int(item.get("size", 0) or 0)

    print(f"Items visible: {len(files)}  ({human_size(total_bytes)})")
    for kind, count in kinds.most_common():
        print(f"   {kind:<12} {count}")

    print("\nFirst few items:")
    for item in files[:5]:
        print(f"   {item['name']}")

    print("\nDrive connection works — the pipeline can read this folder.")


if __name__ == "__main__":
    main()
