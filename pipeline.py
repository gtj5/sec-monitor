"""
pipeline.py

The main pipeline. Does three things in sequence:
  1. FETCH  — pull items from SEC RSS feeds and the meetings page
  2. ANALYZE — ask Claude if each new item is crypto-related
  3. STORE  — save relevant items to the database

Run manually:   python pipeline.py
Run on schedule: handled by the scheduler inside app.py (Chunk 6)
"""

import os
import json
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import anthropic

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

        # Grab the date/time line (the first few text nodes before the heading)
        date_tag = card.find("time") or card.find(class_=lambda c: c and "date" in str(c))
        date_text = date_tag.get_text(strip=True) if date_tag else ""

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
# Step 2: ANALYZE (with Claude)
# -----------------------------------------------------------------

def is_crypto_related(title, summary):
    """
    Ask Claude whether an SEC item is related to crypto/digital assets.

    Returns a tuple: (is_relevant: bool, reason: str)

    We ask Claude to respond in JSON so we can reliably parse the answer
    without trying to interpret free-form text.
    """
    client = anthropic.Anthropic()  # automatically reads ANTHROPIC_API_KEY

    prompt = f"""You are a research assistant for a journalist covering the SEC.

Evaluate whether the following SEC item is related to cryptocurrency,
digital assets, blockchain technology, crypto tokens, NFTs, DeFi,
stablecoins, or similar topics.

Title: {title}
Summary: {summary}

Respond with JSON only — no other text. Use this exact format:
{{
  "is_relevant": true or false,
  "reason": "one sentence explaining why or why not"
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # fast and cheap — good for classification
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Claude sometimes wraps JSON in markdown fences (```json ... ```)
    # Strip them so json.loads gets clean input
    if raw.startswith("```"):
        raw = raw.split("```")[1]          # drop the opening ```json line
        if raw.startswith("json"):
            raw = raw[4:]                  # drop the word "json"
        raw = raw.strip()

    try:
        result = json.loads(raw)
        return result.get("is_relevant", False), result.get("reason", "")
    except json.JSONDecodeError:
        # If Claude's response wasn't valid JSON, log it and skip
        print(f"    ⚠ Could not parse Claude response: {raw[:100]}")
        return False, ""


# -----------------------------------------------------------------
# Step 3: STORE
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
    """Fetch all sources, analyze new items, save relevant ones."""
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
    relevant_count = 0

    for item in all_items:
        # Skip items we've already analyzed (saves API calls)
        if already_saved(item["url"]):
            continue

        new_count += 1
        print(f"\n  Analyzing: {item['title'][:70]}")

        is_relevant, reason = is_crypto_related(item["title"], item["summary"])

        if is_relevant:
            relevant_count += 1
            save_item(item, reason)
        else:
            print(f"    – Not crypto-related")

    print(f"\n=== Done: {new_count} new items analyzed, {relevant_count} saved ===\n")


if __name__ == "__main__":
    run_pipeline()
