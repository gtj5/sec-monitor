"""
app.py

Flask web dashboard for the SEC monitor.
Also starts the background scheduler that runs the pipeline every few hours.

To run:   python app.py
Then open: http://localhost:8080
"""

import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, redirect, url_for, make_response
from flask import render_template_string
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

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
  <style>
    /* ---- Base ---- */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      min-height: 100vh;
      font-size: 14px;
      line-height: 1.5;
    }

    /* ---- Nav ---- */
    .nav {
      border-bottom: 1px solid #21262d;
      padding: 0 2rem;
      height: 52px;
      display: flex;
      align-items: center;
      gap: 1rem;
      position: sticky;
      top: 0;
      background: #0d1117;
      z-index: 10;
    }
    .nav-title { font-size: 0.95rem; font-weight: 600; color: #e6edf3; letter-spacing: 0.01em; }
    .nav-sub   { font-size: 0.75rem; color: #484f58; }
    .nav-right { margin-left: auto; display: flex; align-items: center; gap: 0.5rem; }

    /* ---- Buttons ---- */
    .btn {
      display: inline-block;
      padding: 0.3rem 0.85rem;
      font-size: 0.78rem;
      font-weight: 500;
      border-radius: 6px;
      cursor: pointer;
      text-decoration: none;
      border: 1px solid transparent;
      transition: background 0.15s, border-color 0.15s;
      line-height: 1.6;
    }
    .btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
    .btn-primary:hover { background: #2ea043; }
    .btn-ghost   { background: transparent; border-color: #30363d; color: #c9d1d9; }
    .btn-ghost:hover { background: #161b22; border-color: #8b949e; }

    /* ---- Wrap ---- */
    .wrap { max-width: 1200px; margin: 0 auto; padding: 2rem; }

    /* ---- Stats strip ---- */
    .stats {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1rem;
      margin-bottom: 1.75rem;
    }
    .stat {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 8px;
      padding: 1rem 1.25rem;
    }
    .stat-number { font-size: 1.75rem; font-weight: 700; color: #e6edf3; line-height: 1; }
    .stat-label  { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: #484f58; margin-top: 0.35rem; }

    /* ---- Toolbar ---- */
    .toolbar {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 1rem;
    }
    .toolbar form { margin: 0; }
    .last-run { margin-left: auto; font-size: 0.75rem; color: #484f58; }

    /* ---- Badges ---- */
    .badge {
      display: inline-block;
      padding: 0.18rem 0.6rem;
      border-radius: 20px;
      font-size: 0.67rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      white-space: nowrap;
    }
    .badge-press   { background: #0d2044; color: #79c0ff; border: 1px solid #1f6feb; }
    .badge-litig   { background: #2d1215; color: #ff7b72; border: 1px solid #da3633; }
    .badge-meeting { background: #0d2d1a; color: #56d364; border: 1px solid #238636; }

    /* ---- Table ---- */
    .table-wrap {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 8px;
      overflow: hidden;
    }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      background: #0d1117;
      padding: 0.6rem 1rem;
      text-align: left;
      font-size: 0.68rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #484f58;
      border-bottom: 1px solid #21262d;
    }
    tbody tr { border-bottom: 1px solid #21262d; transition: background 0.1s; }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background: #1c2128; }
    td { padding: 0.7rem 1rem; vertical-align: top; }
    td.date { white-space: nowrap; color: #484f58; font-size: 0.74rem; padding-top: 0.85rem; width: 11rem; }
    td.type { padding-top: 0.85rem; width: 8.5rem; }
    td.title a { text-decoration: none; color: #c9d1d9; font-weight: 500; }
    td.title a:hover { color: #79c0ff; }
    .description { color: #484f58; font-size: 0.78rem; margin-top: 0.3rem; line-height: 1.5; }

    /* ---- Footer ---- */
    .site-footer { margin-top: 2.5rem; text-align: center; font-size: 0.72rem; color: #30363d; }
  </style>
</head>
<body>

  <nav class="nav">
    <span class="nav-title">SEC Monitor</span>
    <span class="nav-sub">Press releases &middot; Litigation &middot; Open meetings</span>
    <div class="nav-right">
      <form method="POST" action="/run" style="margin:0;">
        <button type="submit" class="btn btn-primary">Refresh now</button>
      </form>
      <a href="/export" class="btn btn-ghost">Download CSV</a>
    </div>
  </nav>

  <div class="wrap">

    <div class="stats">
      <div class="stat">
        <div class="stat-number">{{ items|length }}</div>
        <div class="stat-label">Total items</div>
      </div>
      <div class="stat">
        <div class="stat-number">{{ items|selectattr('source','equalto','press_release')|list|length }}</div>
        <div class="stat-label">Press releases</div>
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

    <div class="toolbar">
      <span style="font-size:0.78rem; color:#484f58;">{{ items|length }} items</span>
      <span class="last-run">Last run: {{ last_run }}</span>
    </div>

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
      <p style="color:#484f58; margin-top:2rem;">No items yet. Click "Refresh now" to fetch SEC items.</p>
    {% endif %}

    <p class="site-footer">Data sourced from SEC.gov &mdash; updates every 4 hours</p>
  </div>

</body>
</html>
"""


# -----------------------------------------------------------------
# Routes
# -----------------------------------------------------------------

def load_items():
    """Read items from items.json."""
    p = Path("items.json")
    if p.exists():
        return json.loads(p.read_text())
    return {"items": [], "last_updated": None}


@app.route("/")
def index():
    """Main dashboard: show all saved items, newest first."""
    data     = load_items()
    items    = data.get("items", [])
    last_raw = data.get("last_updated", "")
    last_run = last_raw[:16].replace("T", " ") + " UTC" if last_raw else "Never"
    return render_template_string(TEMPLATE, items=items, last_run=last_run)


@app.route("/run", methods=["POST"])
def run_now():
    """Manually trigger the pipeline from the dashboard."""
    pipeline.run_pipeline()
    _record_run_time()
    return redirect(url_for("index"))


@app.route("/export")
def export_csv():
    """Download all items as a CSV file."""
    data  = load_items()
    items = data.get("items", [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Type", "Title", "URL", "Published", "Saved"])
    for item in items:
        writer.writerow([
            item.get("source"), item.get("title"), item.get("url"),
            item.get("published"), item.get("created_at", "")[:10],
        ])

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
    scheduler = start_scheduler()

    data  = load_items()
    count = len(data.get("items", []))

    if count == 0:
        print("[Startup] No items found — running initial pipeline fetch...")
        pipeline.run_pipeline()
        _record_run_time()
    else:
        print(f"[Startup] Loaded {count} items from items.json.")

    app.run(debug=False, use_reloader=False, port=8080)
