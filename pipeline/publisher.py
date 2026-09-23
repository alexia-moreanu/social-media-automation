"""Publisher: posts one photo + caption to the Facebook Page and Instagram.

Instagram's API cannot receive a file upload — it only accepts a public image URL.
So the photo goes to Facebook first, and the resulting Facebook CDN URL is what
Instagram is told to fetch.
"""

import json
import os
import time
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v26.0"


def _token():
    return os.environ["META_PAGE_ACCESS_TOKEN"]


def _check(response):
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def post_to_facebook(image_path: Path, caption: str, publish_at=None) -> dict:
    """Post now, or hand Meta a time and let their servers publish it.

    publish_at: a timezone-aware datetime, at least 10 minutes in the future.
    """
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    data = {"caption": caption, "access_token": _token()}
    if publish_at:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(publish_at.timestamp()))
    else:
        data["published"] = "true"
    with open(image_path, "rb") as handle:
        result = _check(requests.post(
            f"{GRAPH}/{page_id}/photos",
            data=data,
            files={"source": handle},
            timeout=180,
        ))
    photo_id = result["id"]
    post_id = result.get("post_id")

    images = _check(requests.get(
        f"{GRAPH}/{photo_id}",
        params={"fields": "images", "access_token": _token()},
        timeout=60,
    ))["images"]
    # images is ordered largest first
    public_url = images[0]["source"]

    return {
        "photo_id": photo_id,
        "post_id": post_id,
        "public_url": public_url,
        "scheduled": bool(publish_at),
        "link": f"https://www.facebook.com/{post_id}" if post_id else None,
    }


def post_to_instagram(image_url: str, caption: str) -> dict:
    ig_id = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    container = _check(requests.post(
        f"{GRAPH}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": _token()},
        timeout=120,
    ))["id"]

    # Wait for Instagram to finish fetching and processing the image.
    for _ in range(20):
        status = _check(requests.get(
            f"{GRAPH}/{container}",
            params={"fields": "status_code,status", "access_token": _token()},
            timeout=60,
        ))
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram could not process the image: {status.get('status')}")
        time.sleep(3)

    published = _check(requests.post(
        f"{GRAPH}/{ig_id}/media_publish",
        data={"creation_id": container, "access_token": _token()},
        timeout=120,
    ))
    media_id = published["id"]

    permalink = _check(requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": _token()},
        timeout=60,
    )).get("permalink")

    return {"media_id": media_id, "link": permalink}


def upload_unpublished_photo(image_path: Path) -> dict:
    """Put a photo on the Page without publishing it.

    Used twice: as a slide of a Facebook multi-photo post, and to obtain a public URL
    that Instagram can fetch (its API cannot accept file uploads).
    """
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    with open(image_path, "rb") as handle:
        result = _check(requests.post(
            f"{GRAPH}/{page_id}/photos",
            data={"published": "false", "access_token": _token()},
            files={"source": handle},
            timeout=180,
        ))
    photo_id = result["id"]
    images = _check(requests.get(
        f"{GRAPH}/{photo_id}",
        params={"fields": "images", "access_token": _token()},
        timeout=60,
    ))["images"]
    return {"photo_id": photo_id, "public_url": images[0]["source"]}


def post_carousel_to_facebook(photo_ids, caption: str, publish_at=None) -> dict:
    """One Page post carrying several already-uploaded photos."""
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    data = {"message": caption, "access_token": _token()}
    for index, photo_id in enumerate(photo_ids):
        data[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
    if publish_at:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(publish_at.timestamp()))
    result = _check(requests.post(f"{GRAPH}/{page_id}/feed", data=data, timeout=180))
    post_id = result["id"]
    return {"post_id": post_id, "scheduled": bool(publish_at),
            "link": f"https://www.facebook.com/{post_id}"}


def post_carousel_to_instagram(image_urls, caption: str) -> dict:
    """Instagram carousel: one container per slide, then a parent container."""
    ig_id = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    children = []
    for url in image_urls:
        child = _check(requests.post(
            f"{GRAPH}/{ig_id}/media",
            data={"image_url": url, "is_carousel_item": "true", "access_token": _token()},
            timeout=120,
        ))["id"]
        children.append(child)

    for child in children:
        for _ in range(20):
            status = _check(requests.get(
                f"{GRAPH}/{child}",
                params={"fields": "status_code,status", "access_token": _token()},
                timeout=60,
            ))
            if status.get("status_code") == "FINISHED":
                break
            if status.get("status_code") == "ERROR":
                raise RuntimeError(f"Instagram rejected a slide: {status.get('status')}")
            time.sleep(3)

    parent = _check(requests.post(
        f"{GRAPH}/{ig_id}/media",
        data={"media_type": "CAROUSEL", "children": ",".join(children),
              "caption": caption, "access_token": _token()},
        timeout=120,
    ))["id"]

    published = _check(requests.post(
        f"{GRAPH}/{ig_id}/media_publish",
        data={"creation_id": parent, "access_token": _token()},
        timeout=120,
    ))
    media_id = published["id"]
    permalink = _check(requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": _token()},
        timeout=60,
    )).get("permalink")
    return {"media_id": media_id, "link": permalink}
