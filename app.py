"""
app.py

Flask web dashboard for the SEC monitor.
Also starts the background scheduler that runs the pipeline every few hours.

To run:   python app.py
Then open: http://localhost:8080
"""

import csv
import io
import os
from datetime import datetime
from flask import Flask, redirect, url_for, make_response
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

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEC Monitor</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <style>
    body { max-width: 1100px; margin: 0 auto; padding: 1rem 2rem; }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      white-space: nowrap;
    }
    .badge-press   { background: #dbeafe; color: #1e40af; }
    .badge-litig   { background: #fee2e2; color: #991b1b; }
    .badge-meeting { background: #d1fae5; color: #065f46; }
    .toolbar { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
    .toolbar form { margin: 0; }
    .toolbar small { color: #888; }
    table { font-size: 0.9rem; }
    td, th { vertical-align: middle; }
    td.date { white-space: nowrap; color: #888; font-size: 0.8rem; }
    td.title a { text-decoration: none; color: inherit; }
    td.title a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <header>
    <hgroup>
      <h1>SEC Monitor</h1>
      <p>Items from SEC press releases, litigation releases, and open meetings — updated every 4 hours.</p>
    </hgroup>
  </header>

  <main>
    <div class="toolbar">
      <form method="POST" action="/run">
        <button type="submit">Run pipeline now</button>
      </form>
      <a href="/export" role="button" class="secondary outline">Download CSV</a>
      <small>Last run: {{ last_run }} &nbsp;|&nbsp; {{ items|length }} items</small>
    </div>

    {% if items %}
    <figure>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Type</th>
            <th>Title</th>
            <th>Saved</th>
          </tr>
        </thead>
        <tbody>
          {% for item in items %}
          <tr>
            <td class="date">{{ item.published or '—' }}</td>
            <td>
              {% if item.source == 'press_release' %}
                <span class="badge badge-press">Press Release</span>
              {% elif item.source == 'litigation_release' %}
                <span class="badge badge-litig">Litigation</span>
              {% elif item.source == 'open_meeting' %}
                <span class="badge badge-meeting">Meeting</span>
              {% else %}
                <span class="badge">{{ item.source }}</span>
              {% endif %}
            </td>
            <td class="title"><a href="{{ item.url }}" target="_blank">{{ item.title }}</a></td>
            <td class="date">{{ item.created_at }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </figure>
    {% else %}
      <p>No items yet. Click "Run pipeline now" to fetch SEC items.</p>
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

    columns = ["source", "title", "url", "published", "summary", "ai_reason", "created_at"]
    items = [dict(zip(columns, row)) for row in rows]

    try:
        with open(".last_run", "r") as f:
            last_run = f.read().strip()
    except FileNotFoundError:
        last_run = "Never"

    return render_template_string(TEMPLATE, items=items, last_run=last_run)


@app.route("/run", methods=["POST"])
def run_now():
    """Manually trigger the pipeline from the dashboard."""
    pipeline.run_pipeline()
    _record_run_time()
    return redirect(url_for("index"))


@app.route("/export")
def export_csv():
    """
    Download all items as a CSV file.

    make_response lets us set headers on the response.
    The Content-Disposition header tells the browser to treat it as
    a file download rather than displaying it in the browser window.
    """
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT source, title, url, published, created_at "
            "FROM items ORDER BY id DESC"
        ).fetchall()

    # io.StringIO is an in-memory text buffer — like a file, but in RAM.
    # We write CSV into it, then send the contents as a response.
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Title", "URL", "Published", "Saved"])
    writer.writerows(rows)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=sec_items.csv"
    return response


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
    """Start the background scheduler."""
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
    database.init_db()
    scheduler = start_scheduler()

    with database.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    if count == 0:
        print("[Startup] Database empty — running initial pipeline fetch...")
        pipeline.run_pipeline()
        _record_run_time()
    else:
        print(f"[Startup] Database has {count} items — skipping initial fetch.")

    app.run(debug=False, use_reloader=False, port=8080)
