"""Analytics: what actually happened on the last posts.

Engagement only — likes, comments, saves, shares, reach. Bookings happen by phone and
WhatsApp, so there is no sales attribution to be had and we do not pretend otherwise.
"""

import os
from datetime import datetime, timedelta

import requests

from . import schedule

GRAPH = "https://graph.facebook.com/v26.0"


def _token():
    return os.environ["META_PAGE_ACCESS_TOKEN"]


def _get(path, params):
    params = {**params, "access_token": _token()}
    data = requests.get(f"{GRAPH}/{path}", params=params, timeout=60).json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    return data


def instagram_posts(since_days=35, limit=50):
    """Recent Instagram posts with their engagement numbers."""
    ig_id = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    fields = ("id,caption,media_type,media_product_type,permalink,timestamp,"
              "like_count,comments_count")
    media = _get(f"{ig_id}/media", {"fields": fields, "limit": limit}).get("data", [])

    cutoff = datetime.now(schedule.TZ) - timedelta(days=since_days)
    posts = []
    for item in media:
        posted = datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00"))
        if posted < cutoff:
            continue
        metrics = "reach,saved,shares,total_interactions"
        try:
            insights = _get(f"{item['id']}/insights", {"metric": metrics}).get("data", [])
            numbers = {row["name"]: row["values"][0]["value"] for row in insights}
        except RuntimeError:
            numbers = {}  # insights are unavailable for very fresh or very old media
        posts.append({
            "platform": "instagram",
            "id": item["id"],
            "type": item.get("media_product_type") or item.get("media_type"),
            "posted": posted.astimezone(schedule.TZ),
            "caption": (item.get("caption") or "")[:200],
            "permalink": item.get("permalink"),
            "likes": item.get("like_count", 0),
            "comments": item.get("comments_count", 0),
            "reach": numbers.get("reach", 0),
            "saves": numbers.get("saved", 0),
            "shares": numbers.get("shares", 0),
            "interactions": numbers.get("total_interactions", 0),
        })
    return posts


# Meta withdrew post_impressions / post_impressions_unique for Page posts in this API
# version, so Facebook reach is simply not available any more. Reactions, comments,
# shares and clicks still are; Instagram remains the platform with full numbers.
FB_METRICS = "post_reactions_by_type_total,post_clicks,post_video_views"


def facebook_posts(since_days=35, limit=50):
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    # comments/reactions summaries would need pages_read_user_content, which this
    # token does not have; insights give us the reaction totals anyway.
    fields = f"id,message,created_time,permalink_url,insights.metric({FB_METRICS})"
    data = _get(f"{page_id}/posts", {"fields": fields, "limit": limit}).get("data", [])

    cutoff = datetime.now(schedule.TZ) - timedelta(days=since_days)
    posts = []
    for item in data:
        posted = datetime.fromisoformat(item["created_time"].replace("+0000", "+00:00"))
        if posted < cutoff:
            continue
        numbers = {}
        for row in (item.get("insights", {}) or {}).get("data", []):
            numbers[row["name"]] = row["values"][0]["value"]
        reactions = numbers.get("post_reactions_by_type_total", {})
        likes = sum(reactions.values()) if isinstance(reactions, dict) else 0

        posts.append({
            "platform": "facebook",
            "id": item["id"],
            "type": "post",
            "posted": posted.astimezone(schedule.TZ),
            "caption": (item.get("message") or "")[:200],
            "permalink": item.get("permalink_url"),
            "likes": likes,
            "comments": 0,  # needs pages_read_user_content
            "reach": 0,  # not exposed by the API any more
            "saves": 0,
            "shares": 0,
            "interactions": numbers.get("post_clicks", 0),
        })
    return posts


def with_pillars(posts):
    """Attach the pillar and asset we recorded when each post was scheduled."""
    queue = {item.get("instagram_media_id"): item for item in schedule.load_queue()}
    facebook = {item.get("facebook_post_id"): item for item in schedule.load_queue()}
    for post in posts:
        item = queue.get(post["id"]) or facebook.get(post["id"])
        post["pillar"] = item["pillar"] if item else None
        post["asset"] = item["asset"] if item else None
        post["planned_for"] = item["when"] if item else None
    return posts


def summarise(posts):
    """Group the numbers the planner needs: by pillar, by format, by weekday and hour."""
    def bucket(key_fn):
        groups = {}
        for post in posts:
            key = key_fn(post)
            if key is None:
                continue
            row = groups.setdefault(key, {"posts": 0, "reach": 0, "likes": 0,
                                          "comments": 0, "saves": 0, "shares": 0})
            row["posts"] += 1
            for field in ("reach", "likes", "comments", "saves", "shares"):
                row[field] += post.get(field, 0) or 0
        for row in groups.values():
            row["avg_reach"] = round(row["reach"] / row["posts"])
            row["avg_engagement"] = round(
                (row["likes"] + row["comments"] + row["saves"] + row["shares"]) / row["posts"], 1
            )
        return groups

    days = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
    return {
        "total_posts": len(posts),
        "by_pillar": bucket(lambda p: p.get("pillar")),
        "by_format": bucket(lambda p: p["type"]),
        "by_weekday": bucket(lambda p: days[p["posted"].weekday()]),
        "by_hour": bucket(lambda p: f"{p['posted'].hour:02d}:00"),
        "best": sorted(posts, key=lambda p: (p.get("saves", 0) + p.get("shares", 0)
                                             + p.get("comments", 0) + p.get("likes", 0)),
                       reverse=True)[:5],
    }
