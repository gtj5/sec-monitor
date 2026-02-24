"""
pipeline.py

Fetches SEC items and saves them to items.json.
Runs as a GitHub Actions scheduled job, or locally via: python pipeline.py
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
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
# AI scoring
# -----------------------------------------------------------------

SCORE_PROMPT = """You are a research assistant for a journalist covering the SEC and financial regulation.

Rate the newsworthiness of this SEC item on a scale of 1–5 using this rubric:
  1 = Routine administrative (personnel announcements, budget approvals, procedural notices)
  2 = Standard activity (routine enforcement against individuals, minor settlements)
  3 = Notable (significant enforcement action, meaningful rule proposal, advisory findings)
  4 = Important (major policy change, large enforcement with broad market impact, systemic issue)
  5 = Break immediately or investigate (major fraud, systemic risk, market-moving news, scandal)

Title: {title}
Summary: {summary}

Respond with JSON only — no other text:
{{"score": <integer 1-5>, "reason": "<one sentence>"}}"""


def score_item(title, summary):
    """
    Ask Claude Haiku to rate an item's newsworthiness 1–5.
    Returns (score: int, reason: str) or (None, "") if the API key is absent.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None, ""

    client = anthropic.Anthropic(api_key=api_key)
    msg    = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": SCORE_PROMPT.format(
            title=title, summary=summary or title
        )}],
    )
    raw = msg.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()

    try:
        result = json.loads(raw)
        return int(result.get("score", 0)), result.get("reason", "")
    except (json.JSONDecodeError, ValueError):
        return None, ""


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

        # Score the item before saving
        ai_score, ai_reason = score_item(item["title"], item.get("summary", ""))
        item["ai_score"]        = ai_score
        item["ai_score_reason"] = ai_reason
        if ai_score:
            print(f"    ✓ Saved [{ai_score}/5]: {item['title'][:60]}")
        else:
            print(f"    ✓ Saved [no score]: {item['title'][:60]}")

        data["items"].insert(0, item)   # newest first
        existing_urls.add(item["url"])

    save_data(data)
    print(f"\n=== Done: {new_count} new items saved ===\n")


if __name__ == "__main__":
    run_pipeline()

