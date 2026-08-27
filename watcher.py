#!/usr/bin/env python3
"""
Vinted Watcher
--------------
Checks one or more saved Vinted searches for new listings and sends a
Telegram message for each new item found. Designed to be run on a schedule
(e.g. via GitHub Actions) with a small JSON file used to remember which
items have already been seen, so you don't get re-notified.

Config lives in searches.json. Secrets (Telegram bot token + chat id) are
read from environment variables so they never need to be committed to the
repo.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

VINTED_DOMAIN = os.environ.get("VINTED_DOMAIN", "www.vinted.co.uk")
SEARCHES_FILE = Path(__file__).parent / "searches.json"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: {path} was not valid JSON, starting fresh.")
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def get_session():
    """
    Vinted's API sits behind anti-bot protection that expects normal
    browser cookies. Hitting the homepage first picks up the cookies
    a real browser would have before calling the API.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(f"https://{VINTED_DOMAIN}/", timeout=15)
    return session


def search_vinted(session, search):
    """
    Calls Vinted's internal catalog search API.
    Docs are unofficial/reverse-engineered; Vinted can change this without
    notice, in which case this function is the place to fix things.
    """
    params = {
        "search_text": search.get("keyword", ""),
        "order": "newest_first",
        "per_page": 20,
    }
    if search.get("max_price"):
        params["price_to"] = search["max_price"]
    if search.get("min_price"):
        params["price_from"] = search["min_price"]
    if search.get("size_ids"):
        params["size_ids[]"] = search["size_ids"]
    if search.get("brand_ids"):
        params["brand_ids[]"] = search["brand_ids"]
    if search.get("status_ids"):
        params["status_ids[]"] = search["status_ids"]

    url = f"https://{VINTED_DOMAIN}/api/v2/catalog/items"
    resp = session.get(url, params=params, timeout=15)

    if resp.status_code != 200:
        print(
            f"  ! Vinted returned status {resp.status_code} for "
            f"'{search.get('keyword')}' — skipping this run for this search."
        )
        return []

    try:
        data = resp.json()
    except ValueError:
        print("  ! Response was not JSON — Vinted may have changed its API.")
        return []

    return data.get("items", [])


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set — printing instead:")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        print(f"  ! Failed to send Telegram message: {resp.status_code} {resp.text}")


def format_item_message(item, search_name):
    title = item.get("title", "Untitled item")
    price_obj = item.get("price") or {}
    price = price_obj.get("amount", "?")
    currency = price_obj.get("currency_code", "")
    item_id = item.get("id")
    url = item.get("url") or f"https://{VINTED_DOMAIN}/items/{item_id}"
    brand = item.get("brand_title", "")
    size = item.get("size_title", "")

    lines = [
        f"🆕 <b>New match: {search_name}</b>",
        f"{title}",
    ]
    if brand:
        lines.append(f"Brand: {brand}")
    if size:
        lines.append(f"Size: {size}")
    lines.append(f"Price: {price} {currency}")
    lines.append(url)
    return "\n".join(lines)


def main():
    searches = load_json(SEARCHES_FILE, [])
    if not searches:
        print("No searches configured in searches.json — nothing to do.")
        return

    seen = load_json(SEEN_FILE, {})
    session = get_session()
    any_new = False

    for search in searches:
        name = search.get("name", search.get("keyword", "unnamed search"))
        print(f"Checking search: {name}")
        seen_ids = set(seen.get(name, []))

        items = search_vinted(session, search)
        new_ids = []

        for item in items:
            item_id = str(item.get("id"))
            if item_id in seen_ids:
                continue
            new_ids.append(item_id)
            message = format_item_message(item, name)
            send_telegram_message(message)
            any_new = True
            time.sleep(1)  # be gentle on Telegram's rate limits

        seen_ids.update(new_ids)
        # keep the seen set from growing forever
        seen[name] = list(seen_ids)[-500:]

        print(f"  {len(new_ids)} new item(s) found.")
        time.sleep(2)  # be gentle between Vinted requests

    save_json(SEEN_FILE, seen)

    if not any_new:
        print("No new items across any search this run.")


if __name__ == "__main__":
    sys.exit(main())
