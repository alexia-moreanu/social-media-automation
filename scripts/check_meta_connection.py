"""Check that the Meta credentials in .env work. Read-only: it never posts anything.

Run from the repo root:
    python3 scripts/check_meta_connection.py
"""

import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

GRAPH = "https://graph.facebook.com/v26.0"

REQUIRED_SCOPES = {
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
}


def graph_get(path, params):
    response = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "unknown error"))
    return data


def format_timestamp(ts):
    if not ts:
        return "never"
    when = datetime.fromtimestamp(ts, tz=timezone.utc)
    days_left = (when - datetime.now(timezone.utc)).days
    return f"{when:%Y-%m-%d} ({days_left} days from now)"


def main():
    load_dotenv()
    names = [
        "META_APP_ID",
        "META_APP_SECRET",
        "META_PAGE_ACCESS_TOKEN",
        "FACEBOOK_PAGE_ID",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    ]
    env = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in env.items() if not value]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    token = env["META_PAGE_ACCESS_TOKEN"]
    problems = []

    # 1. Inspect the token itself (uses the app ID + secret as an "app token").
    print("1. Access token")
    info = graph_get(
        "debug_token",
        {"input_token": token, "access_token": f"{env['META_APP_ID']}|{env['META_APP_SECRET']}"},
    )["data"]
    print(f"   valid:               {info.get('is_valid')}")
    print(f"   type:                {info.get('type')}")
    print(f"   expires:             {format_timestamp(info.get('expires_at'))}")
    print(f"   data access expires: {format_timestamp(info.get('data_access_expires_at'))}")
    if not info.get("is_valid"):
        problems.append("token is not valid")
    if info.get("type") != "PAGE":
        problems.append("token is not a Page token (use the one from me/accounts)")
    if str(info.get("app_id")) != env["META_APP_ID"]:
        problems.append("token belongs to a different app than META_APP_ID")
    missing_scopes = REQUIRED_SCOPES - set(info.get("scopes", []))
    if missing_scopes:
        problems.append(f"token is missing permissions: {', '.join(sorted(missing_scopes))}")

    # 2. Read the Facebook Page.
    print("2. Facebook Page")
    page = graph_get(
        env["FACEBOOK_PAGE_ID"],
        {"fields": "name,followers_count,instagram_business_account", "access_token": token},
    )
    print(f"   name:      {page.get('name')}")
    print(f"   followers: {page.get('followers_count')}")
    linked_ig = page.get("instagram_business_account", {}).get("id")
    if linked_ig != env["INSTAGRAM_BUSINESS_ACCOUNT_ID"]:
        problems.append("INSTAGRAM_BUSINESS_ACCOUNT_ID is not the account linked to this Page")

    # 3. Read the Instagram account.
    print("3. Instagram account")
    ig = graph_get(
        env["INSTAGRAM_BUSINESS_ACCOUNT_ID"],
        {"fields": "username,followers_count,media_count", "access_token": token},
    )
    print(f"   username:  @{ig.get('username')}")
    print(f"   followers: {ig.get('followers_count')}")
    print(f"   posts:     {ig.get('media_count')}")

    print()
    if problems:
        print("Problems found:")
        for problem in problems:
            print(f"   - {problem}")
        sys.exit(1)
    print("All good: the pipeline can reach the Page and Instagram account.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        sys.exit(f"Meta API error: {error}")
