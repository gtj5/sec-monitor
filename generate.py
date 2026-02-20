"""
generate.py

Reads items.json and writes a static index.html for GitHub Pages.
Run after pipeline.py:   python generate.py
"""

import json
from pathlib import Path
from datetime import datetime, timezone

DATA_FILE   = Path("items.json")
OUTPUT_FILE = Path("index.html")


def badge(source):
    if source == "press_release":
        return '<span class="badge badge-press">Press Release</span>'
    if source == "litigation_release":
        return '<span class="badge badge-litig">Litigation</span>'
    if source == "open_meeting":
        return '<span class="badge badge-meeting">Meeting</span>'
    return f'<span class="badge">{source}</span>'


def render_row(item):
    title    = item.get("title", "")
    url      = item.get("url", "#")
    pub      = item.get("published") or "&mdash;"
    summary  = item.get("summary", "")
    saved    = item.get("created_at", "")[:10]   # just the date portion

    desc_html = ""
    if summary and summary != title:
        excerpt   = summary[:200] + ("…" if len(summary) > 200 else "")
        desc_html = f'<div class="description">{excerpt}</div>'

    return f"""
          <tr>
            <td class="date">{pub}</td>
            <td class="type">{badge(item.get('source',''))}</td>
            <td class="title">
              <a href="{url}" target="_blank" rel="noopener">{title}</a>
              {desc_html}
            </td>
            <td class="date">{saved}</td>
          </tr>"""


def generate():
    if not DATA_FILE.exists():
        print("items.json not found — run pipeline.py first.")
        return

    with open(DATA_FILE) as f:
        data = json.load(f)

    items = data.get("items", [])
    last_updated_raw = data.get("last_updated", "")
    if last_updated_raw:
        dt = datetime.fromisoformat(last_updated_raw)
        last_updated = dt.strftime("%Y-%m-%d %H:%M UTC")
    else:
        last_updated = "Unknown"

    n_total    = len(items)
    n_press    = sum(1 for i in items if i.get("source") == "press_release")
    n_litig    = sum(1 for i in items if i.get("source") == "litigation_release")
    n_meetings = sum(1 for i in items if i.get("source") == "open_meeting")

    rows_html = "".join(render_row(item) for item in items)

    if not items:
        table_html = '<p style="color:#484f58;margin-top:2rem;">No items yet.</p>'
    else:
        table_html = f"""
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Date</th><th>Type</th><th>Item</th><th>Saved</th></tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
      </table>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SEC Monitor</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      min-height: 100vh;
      font-size: 14px;
      line-height: 1.5;
    }}
    .nav {{
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
    }}
    .nav-title {{ font-size: 0.95rem; font-weight: 600; color: #e6edf3; letter-spacing: 0.01em; }}
    .nav-sub   {{ font-size: 0.75rem; color: #484f58; }}
    .nav-right {{ margin-left: auto; display: flex; align-items: center; gap: 0.5rem; }}
    .btn {{
      display: inline-block;
      padding: 0.3rem 0.85rem;
      font-size: 0.78rem;
      font-weight: 500;
      border-radius: 6px;
      cursor: pointer;
      text-decoration: none;
      border: 1px solid #30363d;
      background: transparent;
      color: #c9d1d9;
      transition: background 0.15s, border-color 0.15s;
      line-height: 1.6;
    }}
    .btn:hover {{ background: #161b22; border-color: #8b949e; }}
    .nav-updated {{ font-size: 0.75rem; color: #484f58; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 1rem;
      margin-bottom: 1.75rem;
    }}
    .stat {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 1rem 1.25rem; }}
    .stat-number {{ font-size: 1.75rem; font-weight: 700; color: #e6edf3; line-height: 1; }}
    .stat-label  {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: #484f58; margin-top: 0.35rem; }}
    .badge {{
      display: inline-block;
      padding: 0.18rem 0.6rem;
      border-radius: 20px;
      font-size: 0.67rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      white-space: nowrap;
    }}
    .badge-press   {{ background: #0d2044; color: #79c0ff; border: 1px solid #1f6feb; }}
    .badge-litig   {{ background: #2d1215; color: #ff7b72; border: 1px solid #da3633; }}
    .badge-meeting {{ background: #0d2d1a; color: #56d364; border: 1px solid #238636; }}
    .table-wrap {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; }}
    thead th {{
      background: #0d1117;
      padding: 0.6rem 1rem;
      text-align: left;
      font-size: 0.68rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #484f58;
      border-bottom: 1px solid #21262d;
    }}
    tbody tr {{ border-bottom: 1px solid #21262d; transition: background 0.1s; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #1c2128; }}
    td {{ padding: 0.7rem 1rem; vertical-align: top; }}
    td.date  {{ white-space: nowrap; color: #484f58; font-size: 0.74rem; padding-top: 0.85rem; width: 11rem; }}
    td.type  {{ padding-top: 0.85rem; width: 8.5rem; }}
    td.title a {{ text-decoration: none; color: #c9d1d9; font-weight: 500; }}
    td.title a:hover {{ color: #79c0ff; }}
    .description {{ color: #484f58; font-size: 0.78rem; margin-top: 0.3rem; line-height: 1.5; }}
    .site-footer {{ margin-top: 2.5rem; text-align: center; font-size: 0.72rem; color: #30363d; }}
  </style>
</head>
<body>

  <nav class="nav">
    <span class="nav-title">SEC Monitor</span>
    <span class="nav-sub">Press releases &middot; Litigation &middot; Open meetings</span>
    <div class="nav-right">
      <span class="nav-updated">Updated {last_updated}</span>
      <button class="btn" onclick="downloadCSV()">Download CSV</button>
    </div>
  </nav>

  <div class="wrap">
    <div class="stats">
      <div class="stat">
        <div class="stat-number">{n_total}</div>
        <div class="stat-label">Total items</div>
      </div>
      <div class="stat">
        <div class="stat-number">{n_press}</div>
        <div class="stat-label">Press releases</div>
      </div>
      <div class="stat">
        <div class="stat-number">{n_litig}</div>
        <div class="stat-label">Litigation</div>
      </div>
      <div class="stat">
        <div class="stat-number">{n_meetings}</div>
        <div class="stat-label">Meetings</div>
      </div>
    </div>

    {table_html}

    <p class="site-footer">Data sourced from SEC.gov &mdash; updated every 4 hours via GitHub Actions</p>
  </div>

  <script>
    function downloadCSV() {{
      // Walk the table rows and pull out cell text, then trigger a download.
      // This runs entirely in the browser — no server needed.
      const rows  = document.querySelectorAll("tbody tr");
      const lines = [["Type","Title","URL","Published","Saved"]];

      rows.forEach(row => {{
        const cells = row.querySelectorAll("td");
        const type  = cells[1].innerText.trim();
        const link  = cells[2].querySelector("a");
        const title = link ? link.innerText.trim() : "";
        const url   = link ? link.href : "";
        const pub   = cells[0].innerText.trim();
        const saved = cells[3].innerText.trim();
        lines.push([type, title, url, pub, saved]);
      }});

      const csv  = lines.map(r => r.map(v => `"${{v.replace(/"/g,'""')}}"`).join(",")).join("\\n");
      const blob = new Blob([csv], {{ type: "text/csv" }});
      const a    = document.createElement("a");
      a.href     = URL.createObjectURL(blob);
      a.download = "sec_items.csv";
      a.click();
    }}
  </script>
</body>
</html>"""

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Generated {OUTPUT_FILE} ({len(items)} items, last updated {last_updated})")


if __name__ == "__main__":
    generate()
