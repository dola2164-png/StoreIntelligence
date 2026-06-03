from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
import csv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def normalize_store_id(store_id: str) -> str:
    """
    Standardizes store identifiers by extracting digits and building a uniform token.
    Maps patterns like 'store_1076' and 'ST1076' to 'ST1076'.
    """
    if not store_id or not isinstance(store_id, str):
        return store_id
    digits = "".join(c for c in store_id if c.isdigit())
    if digits:
        return f"ST{digits}"
    return store_id.strip().upper()


def parse_timestamp(timestamp: str) -> datetime:
    if isinstance(timestamp, datetime):
        return timestamp.astimezone(timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%d-%m-%YT%H:%M:%SZ", "%d-%m-%YT%H:%M:%S%z"):
        try:
            if timestamp.endswith('Z'):
                parsed = datetime.strptime(timestamp, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            return datetime.strptime(timestamp, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        raise ValueError(f'Invalid timestamp format: {timestamp}')


def load_transactions() -> list[Dict[str, str]]:
    path = DATA_DIR / "transactions.csv"
    if not path.exists():
        return []
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        transactions = []
        for row in reader:
            raw_store = row.get('store_id', '')
            if not raw_store:
                continue
            # Ensure POS store ids are normalized perfectly
            row['store_id'] = normalize_store_id(raw_store)
            
            order_date = row.get('order_date', '').strip()
            order_time = row.get('order_time', '').strip()
            timestamp = None
            if order_date and order_time:
                try:
                    parsed = datetime.strptime(f"{order_date}T{order_time}Z", "%d-%m-%YT%H:%M:%SZ")
                    timestamp = parsed.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
                except ValueError:
                    timestamp = f"{order_date}T{order_time}Z"
            row['timestamp'] = timestamp
            transactions.append(row)
    return transactions
