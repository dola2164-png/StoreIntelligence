import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from .db import get_connection
from .exceptions import ServiceUnavailable


def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    event = dict(row)
    event["is_staff"] = bool(event["is_staff"])
    event["dwell_ms"] = int(event["dwell_ms"])
    event["confidence"] = float(event["confidence"])
    event["metadata"] = json.loads(event["metadata"])
    return event


def insert_events(events: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    try:
        conn = get_connection()
    except sqlite3.DatabaseError as exc:
        raise ServiceUnavailable('Database unavailable') from exc
    cursor = conn.cursor()
    accepted = 0
    duplicates = 0

    try:
        for event in events:
            event_id = event["event_id"]
            cursor.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,))
            if cursor.fetchone():
                duplicates += 1
                continue
            metadata_json = json.dumps(event["metadata"])
            timestamp_value = event["timestamp"]
            if not isinstance(timestamp_value, str):
                timestamp_value = timestamp_value.isoformat().replace('+00:00', 'Z')
            try:
                cursor.execute(
                    "INSERT INTO events (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        event["store_id"],
                        event["camera_id"],
                        event["visitor_id"],
                        event["event_type"],
                        timestamp_value,
                        event.get("zone_id"),
                        event["dwell_ms"],
                        1 if event["is_staff"] else 0,
                        event["confidence"],
                        metadata_json,
                    ),
                )
                accepted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
    except sqlite3.DatabaseError as exc:
        conn.rollback()
        raise ServiceUnavailable('Database unavailable') from exc
    finally:
        conn.commit()
    return {"accepted": accepted, "duplicates": duplicates}


def fetch_events(store_id: Optional[list[str] | str] = None, since: Optional[str] = None, until: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
    except sqlite3.DatabaseError as exc:
        raise ServiceUnavailable('Database unavailable') from exc
    cursor = conn.cursor()
    query = "SELECT * FROM events"
    params: List[Any] = []
    clauses: List[str] = []
    if store_id:
        if isinstance(store_id, list):
            placeholders = ",".join("?" for _ in store_id)
            clauses.append(f"store_id IN ({placeholders})")
            params.extend(store_id)
        else:
            clauses.append("store_id = ?")
            params.append(store_id)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("timestamp <= ?")
        params.append(until)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY timestamp ASC"
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.DatabaseError as exc:
        raise ServiceUnavailable('Database unavailable') from exc
    return [_row_to_event(row) for row in rows]


def get_last_event_timestamp(store_id: Optional[list[str] | str] = None) -> Optional[str]:
    try:
        conn = get_connection()
    except sqlite3.DatabaseError as exc:
        raise ServiceUnavailable('Database unavailable') from exc
    cursor = conn.cursor()
    query = "SELECT timestamp FROM events"
    params: List[Any] = []
    if store_id:
        if isinstance(store_id, list):
            placeholders = ",".join("?" for _ in store_id)
            query += f" WHERE store_id IN ({placeholders})"
            params.extend(store_id)
        else:
            query += " WHERE store_id = ?"
            params.append(store_id)
    query += " ORDER BY timestamp DESC LIMIT 1"
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()
    except sqlite3.DatabaseError as exc:
        raise ServiceUnavailable('Database unavailable') from exc
    return row["timestamp"] if row else None
