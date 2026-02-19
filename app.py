"""
app.py

Flask web dashboard for the SEC crypto monitor.
Also starts the background scheduler that runs the pipeline every few hours.

To run:   python app.py
Then open: http://localhost:5000
"""

import os
from datetime import datetime
from flask import Flask, redirect, url_for
from flask import render_template_string
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

import database
import pipeline

load_dotenv()

app = Flask(__name__)

# -----------------------------------------------------------------
# HTML Template
# -----------------------------------------------------------------
# render_template_string lets us keep the template in this file
# instead of a separate templates/ folder — fine for a single page.

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEC Crypto Monitor</title>
  <!-- Pico.css: classless CSS framework — plain HTML looks clean automatically -->
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>
    body { max-width: 900px; margin: 0 auto; padding: 1rem 2rem; }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-press   { background: #dbeafe; color: #1e40af; }
    .badge-litig   { background: #fee2e2; color: #991b1b; }
    .badge-meeting { background: #d1fae5; color: #065f46; }
    .reason { color: #555; font-size: 0.9rem; margin-top: 0.25rem; }
    .meta   { color: #888; font-size: 0.8rem; margin-bottom: 0.25rem; }
    .run-form { display: inline; }
  </style>
</head>
<body>
  <header>
    <hgroup>
      <h1>SEC Crypto Monitor</h1>
      <p>AI-flagged items from SEC press releases, litigation releases, and open meetings.</p>
    </hgroup>
    <form method="POST" action="/run" class="run-form">
      <button type="submit">Run pipeline now</button>
    </form>
    <small>Last pipeline run: {{ last_run }}</small>
  </header>

  <main>
    {% if items %}
      {% for item in items %}
        <article>
          <header>
            <span class="meta">{{ item.published or 'No date' }}</span>
            {% if item.source == 'press_release' %}
              <span class="badge badge-press">Press Release</span>
            {% elif item.source == 'litigation_release' %}
              <span class="badge badge-litig">Litigation</span>
            {% elif item.source == 'open_meeting' %}
              <span class="badge badge-meeting">Meeting</span>
            {% else %}
              <span class="badge">{{ item.source }}</span>
            {% endif %}
          </header>
          <h3><a href="{{ item.url }}" target="_blank">{{ item.title }}</a></h3>
          <footer><small>Saved {{ item.created_at }}</small></footer>
        </article>
      {% endfor %}
    {% else %}
      <p>No crypto-related items found yet. Run the pipeline to fetch and analyze SEC items.</p>
    {% endif %}
  </main>
</body>
</html>
"""


# -----------------------------------------------------------------
# Routes
# -----------------------------------------------------------------

@app.route("/")
def index():
    """Main dashboard: show all saved items, newest first."""
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT source, title, url, published, summary, ai_reason, created_at "
            "FROM items ORDER BY id DESC"
        ).fetchall()

    # Convert raw tuples to dicts for easy use in the template
    columns = ["source", "title", "url", "published", "summary", "ai_reason", "created_at"]
    items = [dict(zip(columns, row)) for row in rows]

    # Read the timestamp of the last pipeline run (stored in a small file)
    try:
        with open(".last_run", "r") as f:
            last_run = f.read().strip()
    except FileNotFoundError:
        last_run = "Never"

    return render_template_string(TEMPLATE, items=items, last_run=last_run)


@app.route("/run", methods=["POST"])
def run_now():
    """
    Manually trigger the pipeline from the dashboard.
    Redirects back to the homepage when done.
    """
    pipeline.run_pipeline()
    _record_run_time()
    return redirect(url_for("index"))


# -----------------------------------------------------------------
# Scheduler
# -----------------------------------------------------------------

def scheduled_run():
    """Called by APScheduler every few hours."""
    print(f"\n[Scheduler] Running pipeline at {datetime.now():%Y-%m-%d %H:%M}")
    pipeline.run_pipeline()
    _record_run_time()


def _record_run_time():
    """Write the current time to a small file so the dashboard can show it."""
    with open(".last_run", "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M"))


def start_scheduler():
    """
    Start the background scheduler.

    BackgroundScheduler runs jobs in a separate thread while Flask
    handles web requests normally. The 'interval' trigger fires every
    PIPELINE_INTERVAL_HOURS hours.
    """
    interval_hours = int(os.getenv("PIPELINE_INTERVAL_HOURS", "4"))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scheduled_run,
        trigger="interval",
        hours=interval_hours,
        id="pipeline",
    )
    scheduler.start()
    print(f"[Scheduler] Pipeline will run every {interval_hours} hours.")
    return scheduler


# -----------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------

if __name__ == "__main__":
    # Initialize DB in case it doesn't exist yet
    database.init_db()

    # Start the background scheduler
    # use_reloader=False is required: Flask's reloader starts the process
    # twice in debug mode, which would launch two schedulers.
    scheduler = start_scheduler()

    # Run the pipeline on startup only if the database is empty,
    # so we don't re-analyze everything on every restart.
    with database.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    if count == 0:
        print("[Startup] Database empty — running initial pipeline fetch...")
        pipeline.run_pipeline()
        _record_run_time()
    else:
        print(f"[Startup] Database has {count} items — skipping initial fetch.")

    app.run(debug=False, use_reloader=False, port=8080)
