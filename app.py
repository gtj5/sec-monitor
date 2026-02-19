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
    /* ---- Layout ---- */
    body    { margin: 0; padding: 0; font-family: system-ui, sans-serif; background: #f8fafc; }
    .wrap   { max-width: 1200px; margin: 0 auto; padding: 0 2rem 3rem; }

    /* ---- Top nav ---- */
    .site-nav {
      background: #0f2540;
      color: #fff;
      padding: 0 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 56px;
      margin-bottom: 2rem;
    }
    .site-nav h1 { margin: 0; font-size: 1.1rem; font-weight: 700; color: #fff; letter-spacing: 0.02em; }
    .site-nav .sub { font-size: 0.75rem; color: #94a3b8; margin-left: 0.75rem; }

    /* ---- Stats strip ---- */
    .stats {
      display: flex;
      gap: 1px;
      background: #e2e8f0;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 1.5rem;
    }
    .stat {
      flex: 1;
      background: #fff;
      padding: 0.9rem 1.25rem;
      text-align: center;
    }
    .stat-number { font-size: 1.6rem; font-weight: 700; color: #0f2540; line-height: 1; }
    .stat-label  { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: #94a3b8; margin-top: 0.25rem; }

    /* ---- Toolbar ---- */
    .toolbar {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
    }
    .toolbar form   { margin: 0; }
    .toolbar button { margin: 0; padding: 0.4rem 1rem; font-size: 0.82rem; background: #0f2540; border-color: #0f2540; color: #fff; border-radius: 6px; cursor: pointer; }
    .toolbar button:hover { background: #1a3a5c; border-color: #1a3a5c; }
    .btn-csv {
      padding: 0.4rem 1rem; font-size: 0.82rem; border: 1px solid #cbd5e1;
      border-radius: 6px; text-decoration: none; color: #334155;
      background: #fff; display: inline-block;
    }
    .btn-csv:hover { background: #f1f5f9; }
    .last-run { margin-left: auto; font-size: 0.78rem; color: #94a3b8; }

    /* ---- Badges ---- */
    .badge {
      display: inline-block;
      padding: 0.2rem 0.65rem;
      border-radius: 20px;
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      white-space: nowrap;
    }
    .badge-press   { background: #dbeafe; color: #1d4ed8; }
    .badge-litig   { background: #fee2e2; color: #b91c1c; }
    .badge-meeting { background: #dcfce7; color: #15803d; }

    /* ---- Table ---- */
    .table-wrap { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
    table  { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    thead th {
      background: #f8fafc;
      padding: 0.65rem 1rem;
      text-align: left;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #64748b;
      border-bottom: 1px solid #e2e8f0;
      position: sticky;
      top: 0;
    }
    tbody tr { border-bottom: 1px solid #f1f5f9; transition: background 0.1s; }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: #f8fafc; }
    td { padding: 0.65rem 1rem; vertical-align: top; }
    td.date { white-space: nowrap; color: #94a3b8; font-size: 0.76rem; padding-top: 0.8rem; width: 11rem; }
    td.type { padding-top: 0.8rem; width: 8rem; }
    td.title a { text-decoration: none; color: #1e293b; font-weight: 500; line-height: 1.4; }
    td.title a:hover { color: #0f2540; text-decoration: underline; }
    .description { color: #64748b; font-size: 0.8rem; margin-top: 0.3rem; line-height: 1.5; }

    /* ---- Footer ---- */
    .site-footer { margin-top: 2.5rem; text-align: center; font-size: 0.75rem; color: #cbd5e1; }
  </style>
</head>
<body>

  <nav class="site-nav">
    <div style="display:flex; align-items:baseline; gap:0.5rem;">
      <h1>SEC Monitor</h1>
      <span class="sub">Press releases &middot; Litigation &middot; Open meetings</span>
    </div>
  </nav>

  <div class="wrap">

    <!-- Stats strip -->
    <div class="stats">
      <div class="stat">
        <div class="stat-number">{{ items|length }}</div>
        <div class="stat-label">Total</div>
      </div>
      <div class="stat">
        <div class="stat-number">{{ items|selectattr('source','equalto','press_release')|list|length }}</div>
        <div class="stat-label">Press Releases</div>
      </div>
      <div class="stat">
        <div class="stat-number">{{ items|selectattr('source','equalto','litigation_release')|list|length }}</div>
        <div class="stat-label">Litigation</div>
      </div>
      <div class="stat">
        <div class="stat-number">{{ items|selectattr('source','equalto','open_meeting')|list|length }}</div>
        <div class="stat-label">Meetings</div>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <form method="POST" action="/run">
        <button type="submit">Refresh now</button>
      </form>
      <a href="/export" class="btn-csv">Download CSV</a>
      <span class="last-run">Last run: {{ last_run }}</span>
    </div>

    <!-- Table -->
    {% if items %}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Type</th>
            <th>Item</th>
            <th>Saved</th>
          </tr>
        </thead>
        <tbody>
          {% for item in items %}
          <tr>
            <td class="date">{{ item.published or '&mdash;' }}</td>
            <td class="type">
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
            <td class="title">
              <a href="{{ item.url }}" target="_blank">{{ item.title }}</a>
              {% if item.summary and item.summary != item.title %}
                <div class="description">{{ item.summary[:200] }}{% if item.summary|length > 200 %}…{% endif %}</div>
              {% endif %}
            </td>
            <td class="date">{{ item.created_at }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
      <p>No items yet. Click "Refresh now" to fetch SEC items.</p>
    {% endif %}

    <p class="site-footer">Data sourced from SEC.gov &mdash; updates every 4 hours</p>
  </div>

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
