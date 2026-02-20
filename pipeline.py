"""
pipeline.py

Fetches SEC items and saves them to items.json.
Runs as a GitHub Actions scheduled job, or locally via: python pipeline.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------
# Constants
# -----------------------------------------------------------------

HEADERS = {
    "User-Agent": "sec-monitor/1.0 contact@example.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

RSS_FEEDS = [
    {"url": "https://www.sec.gov/news/pressreleases.rss",                       "source": "press_release"},
    {"url": "https://www.sec.gov/enforcement-litigation/litigation-releases/rss", "source": "litigation_release"},
]

MEETINGS_URL = "https://www.sec.gov/news/upcoming-events"
DATA_FILE    = Path("items.json")


# -----------------------------------------------------------------
# JSON storage
# -----------------------------------------------------------------

def load_data():
    """Load existing items from disk. Return empty structure if file doesn't exist."""
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"items": [], "last_updated": None}


def save_data(data):
    """Write items back to disk with an updated timestamp."""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# -----------------------------------------------------------------
# Fetchers
# -----------------------------------------------------------------

def fetch_rss_items(feed_url, source_name):
    print(f"  Fetching {source_name} feed...")
    feed = feedparser.parse(
        feed_url,
        agent=HEADERS["User-Agent"],
        request_headers={"Accept": HEADERS["Accept"]},
    )
    items = []
    for entry in feed.entries:
        items.append({
            "source":     source_name,
            "title":      entry.get("title", "").strip(),
            "url":        entry.get("link", "").strip(),
            "published":  entry.get("published", ""),
            "summary":    entry.get("summary", entry.get("title", "")).strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    print(f"    → {len(items)} items found")
    return items


def fetch_meeting_items():
    print(f"  Fetching meetings page...")
    response = requests.get(MEETINGS_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup  = BeautifulSoup(response.text, "html.parser")
    cards = soup.find_all("li", class_="usa-collection__item")

    items = []
    for card in cards:
        heading = card.find("h3", class_="usa-collection__heading")
        if not heading or not heading.find("a"):
            continue

        link_tag = heading.find("a")
        title    = link_tag.get_text(strip=True)
        full_url = "https://www.sec.gov" + link_tag.get("href", "")

        desc_tag    = card.find("div", class_="usa-collection__description")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        time_tag  = card.find("time")
        date_text = ""
        if time_tag and time_tag.get("datetime"):
            parsed    = datetime.fromisoformat(time_tag["datetime"])
            date_text = parsed.strftime("%Y-%m-%d %I:%M %p ET")

        items.append({
            "source":     "open_meeting",
            "title":      title,
            "url":        full_url,
            "published":  date_text,
            "summary":    description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"    → {len(items)} meetings found")
    return items


# -----------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------

def run_pipeline():
    print("\n=== SEC Monitor Pipeline ===")

    data          = load_data()
    existing_urls = {item["url"] for item in data["items"]}

    all_items = []
    for feed in RSS_FEEDS:
        all_items.extend(fetch_rss_items(feed["url"], feed["source"]))
    all_items.extend(fetch_meeting_items())

    print(f"\nTotal items fetched: {len(all_items)}")

    new_count = 0
    for item in all_items:
        if item["url"] in existing_urls:
            continue
        new_count += 1
        data["items"].insert(0, item)   # newest first
        existing_urls.add(item["url"])
        print(f"    ✓ Saved: {item['title'][:70]}")

    save_data(data)
    print(f"\n=== Done: {new_count} new items saved ===\n")


if __name__ == "__main__":
    run_pipeline()
