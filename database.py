"""
database.py

Sets up a SQLite database to store SEC items flagged as crypto-related.
Run this file directly once to create the database before using the pipeline.
"""

import sqlite3

DB_PATH = "sec_monitor.db"


def get_connection():
    """Return a connection to the SQLite database."""
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create the items table if it doesn't already exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,       -- e.g. "press_release" or "open_meeting"
                title       TEXT NOT NULL,
                url         TEXT UNIQUE NOT NULL, -- UNIQUE prevents saving the same item twice
                published   TEXT,                 -- date string from the feed
                summary     TEXT,                 -- original text we sent to Claude
                ai_reason   TEXT,                 -- Claude's explanation of why it's relevant
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        print("Database ready.")


if __name__ == "__main__":
    init_db()
