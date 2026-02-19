"""
pipeline.py

The main pipeline. Does three things in sequence:
  1. FETCH  — pull items from SEC RSS feeds and the meetings page
  2. ANALYZE — ask Claude if each new item is crypto-related
  3. STORE  — save relevant items to the database

Run manually:   python pipeline.py
Run on schedule: handled by the scheduler inside app.py (Chunk 6)
"""

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import database

# Load the ANTHROPIC_API_KEY from .env into the environment
load_dotenv()

# -----------------------------------------------------------------
# Constants
# -----------------------------------------------------------------

HEADERS = {
    # The SEC blocks requests that don't send proper browser-like headers.
    # The User-Agent should identify your tool; SEC docs ask for contact info.
    "User-Agent": "sec-monitor/1.0 contact@example.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

RSS_FEEDS = [
    {
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "source": "press_release",
    },
    {
        "url": "https://www.sec.gov/enforcement-litigation/litigation-releases/rss",
        "source": "litigation_release",
    },
]

MEETINGS_URL = "https://www.sec.gov/news/upcoming-events"


# -----------------------------------------------------------------
# Step 1: FETCH
# -----------------------------------------------------------------

def fetch_rss_items(feed_url, source_name):
    """
    Download and parse an RSS feed. Return a list of dicts, one per item.

    feedparser handles the XML parsing. Each item becomes a dict with
    keys like 'title', 'link', 'summary', 'published'.
    """
    print(f"  Fetching {source_name} feed...")
    feed = feedparser.parse(feed_url, agent=HEADERS["User-Agent"],
                            request_headers={"Accept": HEADERS["Accept"]})

    items = []
    for entry in feed.entries:
        items.append({
            "source":    source_name,
            "title":     entry.get("title", "").strip(),
            "url":       entry.get("link", "").strip(),
            "published": entry.get("published", ""),
            "summary":   entry.get("summary", entry.get("title", "")).strip(),
        })

    print(f"    → {len(items)} items found")
    return items


def fetch_meeting_items():
    """
    Scrape the SEC meetings/events page. Return a list of dicts.

    There's no RSS feed for meetings, so we fetch the HTML and use
    BeautifulSoup to extract the structured data from each event card.
    """
    print(f"  Fetching meetings page...")
    response = requests.get(MEETINGS_URL, headers=HEADERS, timeout=15)
    response.raise_for_status()  # raise an error if the request failed

    soup = BeautifulSoup(response.text, "html.parser")
    event_cards = soup.find_all("li", class_="usa-collection__item")

    items = []
    for card in event_cards:
        heading = card.find("h3", class_="usa-collection__heading")
        if not heading or not heading.find("a"):
            continue

        link_tag = heading.find("a")
        title = link_tag.get_text(strip=True)
        relative_url = link_tag.get("href", "")
        full_url = "https://www.sec.gov" + relative_url

        # Grab description text if present (not all events have one)
        desc_tag = card.find("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # The <time> tag has a clean datetime attribute (e.g. "2026-02-18T16:00:00-05:00").
        # Use that directly rather than scraping the display spans, which run together.
        time_tag = card.find("time")
        if time_tag and time_tag.get("datetime"):
            from datetime import datetime as dt
            raw_dt = time_tag["datetime"]          # "2026-02-18T16:00:00-05:00"
            parsed = dt.fromisoformat(raw_dt)
            date_text = parsed.strftime("%Y-%m-%d %I:%M %p ET")
        else:
            date_text = ""

        # Build a summary for Claude to evaluate
        summary = f"{title}. {description}".strip()

        items.append({
            "source":    "open_meeting",
            "title":     title,
            "url":       full_url,
            "published": date_text,
            "summary":   summary,
        })

    print(f"    → {len(items)} meetings found")
    return items


# -----------------------------------------------------------------
# Step 2: STORE
# -----------------------------------------------------------------

def save_item(item, reason):
    """Save a relevant item to the database. Silently skip duplicates."""
    with database.get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO items (source, title, url, published, summary, ai_reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["source"],
                    item["title"],
                    item["url"],
                    item["published"],
                    item["summary"],
                    reason,
                ),
            )
            print(f"    ✓ Saved: {item['title'][:70]}")
        except Exception:
            # The UNIQUE constraint on url triggers here for duplicates — that's fine
            pass


def already_saved(url):
    """Return True if this URL is already in the database."""
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM items WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


# -----------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------

def run_pipeline():
    """Fetch all sources and save every new item."""
    print("\n=== SEC Monitor Pipeline ===")

    # Make sure the database table exists
    database.init_db()

    # Collect items from all sources
    all_items = []
    for feed in RSS_FEEDS:
        all_items.extend(fetch_rss_items(feed["url"], feed["source"]))
    all_items.extend(fetch_meeting_items())

    print(f"\nTotal items fetched: {len(all_items)}")

    new_count = 0

    for item in all_items:
        if already_saved(item["url"]):
            continue

        new_count += 1
        save_item(item, reason="")

    print(f"\n=== Done: {new_count} new items saved ===\n")


if __name__ == "__main__":
    run_pipeline()
