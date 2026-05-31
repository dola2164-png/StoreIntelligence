import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"
_CONN = None


def get_connection():
    global _CONN
    if _CONN is not None:
        return _CONN
    if os.environ.get('STORE_INTELLIGENCE_DB') == 'memory':
        conn = sqlite3.connect(':memory:', check_same_thread=False)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _CONN = conn
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            visitor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            zone_id TEXT,
            dwell_ms INTEGER NOT NULL,
            is_staff INTEGER NOT NULL,
            confidence REAL NOT NULL,
            metadata TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_store_ts ON events(store_id, timestamp)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_store_visitor ON events(store_id, visitor_id)"
    )
    conn.commit()
    return conn
