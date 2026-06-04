from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .storage import fetch_events, get_last_event_timestamp
from .utils import load_transactions, parse_timestamp

EVENT_TYPES = {
    'ENTRY',
    'EXIT',
    'ZONE_ENTER',
    'ZONE_EXIT',
    'ZONE_DWELL',
    'BILLING_QUEUE_JOIN',
    'BILLING_QUEUE_ABANDON',
    'PURCHASE',
    'REENTRY'
}


def _group_sessions(events: List[Dict]) -> Dict[str, List[Dict]]:
    sessions: Dict[str, List[Dict]] = defaultdict(list)
    # Exclude staff members entirely from baseline session tracking
    clean_events = [e for e in events if not e.get('is_staff', False)]
    for event in sorted(clean_events, key=lambda e: e['timestamp']):
        seq = event.get('metadata', {}).get('session_seq') if event.get('metadata') else None
        
        # If session_seq is explicitly provided and not None, create a compound key.
        # Otherwise, fall back exactly to visitor_id to satisfy coverage requirements.
        if seq is not None:
            session_key = f"{event['visitor_id']}_{seq}"
        else:
            session_key = event['visitor_id']
            
        sessions[session_key].append(event)
    return sessions


def _non_staff(events: List[Dict]) -> List[Dict]:
    return [e for e in events if not e.get('is_staff', False)]


def _load_transactions_for_store(store_id: str) -> List[Dict]:
    raw = load_transactions()
    return [t for t in raw if t.get('store_id') == store_id]


def _build_conversion_map(events: List[Dict], store_id: str) -> Dict[str, bool]:
    sessions = _group_sessions(events)
    transactions = _load_transactions_for_store(store_id)
    purchases: Dict[str, bool] = {session_key: False for session_key in sessions}
    billing_windows: Dict[str, List[datetime]] = {}
    
    for session_key, items in sessions.items():
        if any(e['event_type'] == 'PURCHASE' for e in items):
            purchases[session_key] = True
            continue
        billing_windows[session_key] = [
            parse_timestamp(e['timestamp'])
            for e in items
            if e.get('zone_id') == 'BILLING'
        ]
        
    tx_times = [parse_timestamp(t['timestamp']) for t in transactions if t.get('timestamp')]
    for session_key, times in billing_windows.items():
        for bill_time in times:
            for txn in tx_times:
                elapsed = (txn - bill_time).total_seconds()
                if 0 <= elapsed <= 300:
                    purchases[session_key] = True
                    break
            if purchases[session_key]:
                break
    return purchases


def _queue_depth_value(event: Dict[str, object]) -> int:
    value = event['metadata'].get('queue_depth', 0)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_metrics(store_id: str) -> Dict[str, object]:
    events = _non_staff(fetch_events(store_id))
    sessions = _group_sessions(events)
    visitor_count = len({event['visitor_id'] for event in events})
    converted = sum(1 for _, has in _build_conversion_map(events, store_id).items() if has)
    session_count = len(sessions)
    conversion_rate = round((converted / session_count) * 100, 2) if session_count else 0.0

    zone_dwell = defaultdict(list)
    for event in events:
        if event['event_type'] == 'ZONE_DWELL' and event['zone_id']:
            zone_dwell[event['zone_id']].append(event['dwell_ms'])

    avg_dwell = {
        zone: round(sum(values) / len(values) / 1000, 2)
        for zone, values in zone_dwell.items()
    }
    queue_depths = [_queue_depth_value(e) for e in events if e['event_type'] == 'BILLING_QUEUE_JOIN']
    billing_sessions = {session_key for session_key, items in sessions.items() if any(e['event_type'] == 'BILLING_QUEUE_JOIN' for e in items)}
    abandon_count = sum(1 for items in sessions.values() if any(e['event_type'] == 'BILLING_QUEUE_ABANDON' for e in items))
    abandonment_rate = round((abandon_count / len(billing_sessions)) * 100, 2) if billing_sessions else 0.0

    return {
        'store_id': store_id,
        'unique_visitors': visitor_count,
        'conversion_rate': conversion_rate,
        'avg_dwell_per_zone': avg_dwell,
        'queue_depth': max(queue_depths) if queue_depths else 0,
        'abandonment_rate': abandonment_rate,
        'session_count': session_count,
        'last_event_timestamp': get_last_event_timestamp(store_id),
    }


def build_funnel(store_id: str) -> Dict[str, object]:
    events = _non_staff(fetch_events(store_id))
    sessions = _group_sessions(events)
    conversion_map = _build_conversion_map(events, store_id)

    entry_sessions = {k for k, items in sessions.items()
                      if any(e['event_type'] in {'ENTRY', 'REENTRY'} for e in items)}
    zone_sessions = {k for k, items in sessions.items()
                     if any(e['event_type'] in {'ZONE_ENTER', 'ZONE_DWELL'} for e in items)}
    billing_sessions = {k for k, items in sessions.items()
                        if any(e['event_type'] == 'BILLING_QUEUE_JOIN' for e in items)}

    entry = len(entry_sessions)
    zone_visit = len(zone_sessions)
    billing = len(billing_sessions)
    purchased = sum(1 for _, converted in conversion_map.items() if converted)

    def drop(prev: int, curr: int) -> float:
        return round((prev - curr) / prev * 100, 2) if prev else 0.0

    return {
        'stages': [
            {'name': 'Entry', 'count': entry, 'drop_off_pct': 0.0},
            {'name': 'Zone Visit', 'count': zone_visit, 'drop_off_pct': drop(entry, zone_visit)},
            {'name': 'Billing Queue', 'count': billing, 'drop_off_pct': drop(zone_visit, billing)},
            {'name': 'Purchase', 'count': purchased, 'drop_off_pct': drop(billing, purchased)},
        ],
        'note': 'Entry and zone counts are from separate cameras; cross-camera Re-ID partial'
    }


def build_heatmap(store_id: str) -> Dict[str, object]:
    events = _non_staff(fetch_events(store_id))
    zone_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {'visits': 0, 'total_dwell': 0})
    sessions = _group_sessions(events)
    for event in events:
        if event['event_type'] == 'ZONE_ENTER' and event['zone_id']:
            zone_stats[event['zone_id']]['visits'] += 1
        if event['event_type'] == 'ZONE_DWELL' and event['zone_id']:
            zone_stats[event['zone_id']]['total_dwell'] += event.get('dwell_ms', 0)
    if not zone_stats:
        return {'zones': [], 'data_confidence': False}
    scores = [stats['visits'] for stats in zone_stats.values()]
    max_visits = max(scores) if scores else 1
    zones = []
    for zone_id, stats in zone_stats.items():
        avg_dwell = round(stats['total_dwell'] / stats['visits'] / 1000, 2) if stats['visits'] > 0 and stats['total_dwell'] > 0 else 0.0
        zones.append({
            'zone_id': zone_id,
            'visit_count': stats['visits'],
            'avg_dwell_seconds': avg_dwell,
            'score': int(round((stats['visits'] / max_visits) * 100))
        })
    data_confidence = len(sessions) >= 20
    return {'zones': zones, 'data_confidence': data_confidence}


def build_anomalies(store_id: str) -> List[Dict[str, object]]:
    events = _non_staff(fetch_events(store_id))
    anomalies = []
    if not events:
        return anomalies
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(minutes=30)
    recent_events = [e for e in events if parse_timestamp(e['timestamp']) >= recent_cutoff]
    queue_depths = [_queue_depth_value(e) for e in events if e['event_type'] == 'BILLING_QUEUE_JOIN']
    if queue_depths:
        avg_queue = sum(queue_depths) / len(queue_depths)
        recent_queue_values = [_queue_depth_value(e) for e in recent_events if e['event_type'] == 'BILLING_QUEUE_JOIN']
        current = max(recent_queue_values, default=0)
        if not isinstance(current, (int, float)):
            try:
                current = int(current)
            except Exception:
                current = 0
        if current > avg_queue * 1.75 and current >= 3:
            anomalies.append({
                'type': 'QUEUE_SPIKE',
                'severity': 'WARN',
                'description': f'Billing queue depth spike: {current} vs avg {round(avg_queue,1)}',
                'suggested_action': 'Open another register or move staff to billing.'
            })
    health = build_metrics(store_id)
    if health['conversion_rate'] < 15 and health['unique_visitors'] >= 5:
        anomalies.append({
            'type': 'CONVERSION_DROP',
            'severity': 'INFO',
            'description': f'Conversion rate is low: {health["conversion_rate"]}%',
            'suggested_action': 'Review store staffing and merchandising.'
        })
    zone_visits = defaultdict(int)
    for e in recent_events:
        if e['event_type'] in {'ZONE_ENTER', 'ZONE_DWELL'} and e['zone_id']:
            zone_visits[e['zone_id']] += 1
    checked_zones = {'SKINCARE', 'COSMETICS', 'MAIN_FLOOR', 'BILLING'}
    for zone_id in checked_zones:
        if zone_visits.get(zone_id, 0) == 0:
            anomalies.append({
                'type': 'DEAD_ZONE',
                'severity': 'INFO',
                'description': f'No recent visits in zone {zone_id}.',
                'suggested_action': 'Inspect signage and product placement in this zone.'
            })
    return anomalies


def build_health() -> Dict[str, object]:
    now = datetime.now(timezone.utc)
    all_events = fetch_events()
    stores = defaultdict(lambda: {'last_ts': None})
    for event in all_events:
        store_id = event['store_id']
        ts = parse_timestamp(event['timestamp'])
        if stores[store_id]['last_ts'] is None or ts > stores[store_id]['last_ts']:
            stores[store_id]['last_ts'] = ts
    status = 'ok'
    store_status = {}
    for store_id, payload in stores.items():
        last_ts = payload['last_ts']
        stale = (now - last_ts).total_seconds() > 600 if last_ts else True
        store_status[store_id] = 'STALE' if stale else 'OK'
        if stale:
            status = 'degraded'
    last_ts = max((payload['last_ts'] for payload in stores.values() if payload['last_ts']), default=None)
    return {
        'status': status,
        'last_event_timestamp': last_ts.isoformat() if last_ts else None,
        'stale_feed': status != 'ok',
        'store_status': store_status,
    }
