#!/usr/bin/env python3
"""
Vinted Watcher
--------------
Checks one or more saved Vinted searches for new listings and sends a
Telegram message for each new item found. Designed to be run on a schedule
(e.g. via GitHub Actions) with a small JSON file used to remember which
items have already been seen, so you don't get re-notified.

Vinted retired its JSON search endpoint (/api/v2/catalog/items) in late
September 2026, so this version reads the normal website search page
(/catalog) and pulls the listings out of the page itself.

Config lives in searches.json. Secrets (Telegram bot token + chat id) are
read from environment variables so they never need to be committed to the
repo.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

VINTED_DOMAIN = os.environ.get("VINTED_DOMAIN", "www.vinted.co.uk")
SEARCHES_FILE = Path(__file__).parent / "searches.json"
SEEN_FILE = Path(__file__).parent / "seen_items.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Only look at the newest N listings per search, per run.
MAX_ITEMS = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

ITEM_LINK_RE = re.compile(r"/items/(\d+)-([a-z0-9][a-z0-9\-]*)")


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: {path.name} is not valid JSON ({e}).")
            if path == SEARCHES_FILE:
                # Fail loudly so a broken searches file shows as a red cross
                # in GitHub Actions instead of silently doing nothing.
                sys.exit(1)
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def get_session():
    """
    Hitting the homepage first picks up the cookies a real browser would
    have before it requests a search page.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    home = session.get(f"https://{VINTED_DOMAIN}/", timeout=20)
    print(
        f"Homepage status: {home.status_code}; "
        f"cookies: {list(session.cookies.keys())}"
    )
    return session


def _decode(text):
    """Turn a JSON-escaped string fragment (\\u00a3, \\" etc.) into plain text."""
    try:
        return json.loads(f'"{text}"')
    except ValueError:
        return text


def parse_catalog_html(page):
    """
    Pull listings out of the search results page.

    Item links look like /items/1234567890-some-title-slug. They appear in
    the order shown on the page (newest first, because we ask for that).
    Where the page's embedded data also includes a proper title and price
    next to the item id, we use those; otherwise we fall back to a title
    built from the link.
    """
    # Embedded page data is JSON inside a string, so slashes/quotes can be
    # escaped. Normalise both so one set of patterns works.
    text = page.replace("\\/", "/").replace('\\"', '"')

    items = {}
    for match in ITEM_LINK_RE.finditer(text):
        item_id, slug = match.group(1), match.group(2)
        if item_id in items:
            continue
        items[item_id] = {
            "id": item_id,
            "title": slug.replace("-", " ").title(),
            "url": f"https://{VINTED_DOMAIN}/items/{item_id}-{slug}",
            "price": None,
            "currency": "",
        }

    for item_id, item in items.items():
        pos = text.find(f'"id":{item_id},')
        if pos == -1:
            continue
        near = text[pos : pos + 400]
        title = re.search(r'"title":"([^"]{2,200})"', near)
        if title:
            item["title"] = _decode(title.group(1))
        window = text[pos : pos + 1800]
        amount = re.search(r'"amount":"?([\d.]+)"?', window)
        if amount:
            item["price"] = amount.group(1)
        currency = re.search(r'"currency_code":"([A-Z]{3})"', window)
        if currency:
            item["currency"] = currency.group(1)

    return list(items.values())


def search_vinted(session, search):
    params = {
        "search_text": search.get("keyword", ""),
        "order": "newest_first",
        "currency": "GBP",
    }
    if search.get("max_price"):
        params["price_to"] = search["max_price"]
    if search.get("min_price"):
        params["price_from"] = search["min_price"]
    if search.get("catalog_ids"):
        params["catalog[]"] = search["catalog_ids"]
    if search.get("size_ids"):
        params["size_ids[]"] = search["size_ids"]
    if search.get("brand_ids"):
        params["brand_ids[]"] = search["brand_ids"]
    if search.get("status_ids"):
        params["status_ids[]"] = search["status_ids"]

    url = f"https://{VINTED_DOMAIN}/catalog"
    resp = session.get(
        url,
        params=params,
        timeout=20,
        headers={"Referer": f"https://{VINTED_DOMAIN}/"},
    )

    if resp.status_code != 200:
        print(
            f"  ! Vinted returned status {resp.status_code} for "
            f"'{search.get('keyword')}' — skipping this run for this search."
        )
        print("  Response start:", resp.text[:200].replace("\n", " "))
        return []

    items = parse_catalog_html(resp.text)
    if not items:
        print(
            f"  ! Page loaded (status 200, {len(resp.text)} characters) but no "
            f"listings were found in it for '{search.get('keyword')}'."
        )
        print("  Page start:", resp.text[:300].replace("\n", " "))
        print("  Contains '/items/':", "/items/" in resp.text)

    return items[:MAX_ITEMS]


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set — printing instead:")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        print(f"  ! Failed to send Telegram message: {resp.status_code} {resp.text}")


def format_item_message(item, search_name):
    lines = [f"🆕 New match: {search_name}", item["title"]]
    if item.get("price"):
        lines.append(f"Price: {item['price']} {item.get('currency', '')}".strip())
    lines.append(item["url"])
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
            item_id = str(item["id"])
            if item_id in seen_ids:
                continue
            new_ids.append(item_id)
            send_telegram_message(format_item_message(item, name))
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


if __name__ == "__main__":
    sys.exit(main())
