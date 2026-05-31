# PROMPT: Extend API tests for session correctness, conversion, anomalies, and live dashboard coverage.

import os
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

os.environ['STORE_INTELLIGENCE_DB'] = 'memory'

from app.db import get_connection
from app.main import app

client = TestClient(app)


def reset_db():
    conn = get_connection()
    conn.execute('DELETE FROM events')
    conn.commit()


@pytest.fixture(autouse=True)
def clear_db():
    reset_db()
    yield
    reset_db()


def ingest(events):
    response = client.post('/events/ingest', json={'events': events})
    assert response.status_code == 200
    return response.json()


def make_event(event_id, visitor_id, event_type, timestamp, session_seq, **kwargs):
    return {
        'event_id': event_id,
        'store_id': 'STORE_BLR_002',
        'camera_id': kwargs.get('camera_id', 'CAM_ENTRY_01'),
        'visitor_id': visitor_id,
        'event_type': event_type,
        'timestamp': timestamp,
        'zone_id': kwargs.get('zone_id'),
        'dwell_ms': kwargs.get('dwell_ms', 0),
        'is_staff': kwargs.get('is_staff', False),
        'confidence': kwargs.get('confidence', 0.85),
        'metadata': {
            'queue_depth': kwargs.get('queue_depth'),
            'sku_zone': kwargs.get('sku_zone'),
            'session_seq': session_seq,
        },
    }


def test_event_ingest_accepts_batch():
    event = make_event('test-event-001', 'VIS_1', 'ENTRY', '2026-04-25T10:00:00Z', 1)
    result = ingest([event])
    assert result['accepted'] == 1
    assert result['duplicates'] == 0
    assert result['rejected'] == 0


def test_event_ingest_idempotent():
    event = make_event('test-event-001', 'VIS_1', 'ENTRY', '2026-04-25T10:00:00Z', 1)
    ingest([event])
    result = ingest([event])
    assert result['accepted'] == 0
    assert result['duplicates'] == 1
    assert result['rejected'] == 0


def test_entry_exit_session_and_purchase_conversion():
    now = datetime.now(timezone.utc)
    events = [
        make_event('session-1-entry', 'VIS_1', 'ENTRY', now.isoformat().replace('+00:00', 'Z'), 1),
        make_event('session-1-zone-enter', 'VIS_1', 'ZONE_ENTER', (now + timedelta(seconds=10)).isoformat().replace('+00:00', 'Z'), 1, zone_id='SKINCARE', sku_zone='MOISTURISER'),
        make_event('session-1-dwell', 'VIS_1', 'ZONE_DWELL', (now + timedelta(seconds=40)).isoformat().replace('+00:00', 'Z'), 1, zone_id='SKINCARE', dwell_ms=30000, sku_zone='MOISTURISER'),
        make_event('session-1-billing', 'VIS_1', 'BILLING_QUEUE_JOIN', (now + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z'), 1, zone_id='BILLING', queue_depth=1),
        make_event('session-1-purchase', 'VIS_1', 'PURCHASE', (now + timedelta(minutes=6)).isoformat().replace('+00:00', 'Z'), 1),
    ]
    ingest(events)

    metrics = client.get('/stores/STORE_BLR_002/metrics').json()
    funnel = client.get('/stores/STORE_BLR_002/funnel').json()

    assert metrics['unique_visitors'] == 1
    assert metrics['session_count'] == 1
    assert metrics['conversion_rate'] == 100.0
    assert funnel['stages'][0]['count'] == 1
    assert funnel['stages'][3]['count'] == 1


def test_reentry_and_staff_exclusion():
    now = datetime.now(timezone.utc)
    events = [
        make_event('staff-1', 'VIS_STAFF', 'ENTRY', now.isoformat().replace('+00:00', 'Z'), 1, is_staff=True),
        make_event('customer-1-entry', 'VIS_2', 'ENTRY', (now + timedelta(seconds=5)).isoformat().replace('+00:00', 'Z'), 1),
        make_event('customer-1-exit', 'VIS_2', 'EXIT', (now + timedelta(seconds=20)).isoformat().replace('+00:00', 'Z'), 1),
        make_event('customer-1-reentry', 'VIS_2', 'REENTRY', (now + timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'), 2),
    ]
    ingest(events)

    metrics = client.get('/stores/STORE_BLR_002/metrics').json()
    assert metrics['unique_visitors'] == 1
    assert metrics['session_count'] == 2
    assert metrics['conversion_rate'] == 0.0


def test_funnel_accuracy_with_held_out_events():
    now = datetime.now(timezone.utc)
    events = [
        make_event('hold-1-entry', 'VIS_A', 'ENTRY', now.isoformat().replace('+00:00', 'Z'), 1),
        make_event('hold-1-zone', 'VIS_A', 'ZONE_ENTER', (now + timedelta(seconds=10)).isoformat().replace('+00:00', 'Z'), 1, zone_id='SKINCARE'),
        make_event('hold-1-purchase', 'VIS_A', 'PURCHASE', (now + timedelta(minutes=4)).isoformat().replace('+00:00', 'Z'), 1),

        make_event('hold-2-entry', 'VIS_B', 'ENTRY', (now + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z'), 1),
        make_event('hold-2-zone', 'VIS_B', 'ZONE_ENTER', (now + timedelta(minutes=5, seconds=10)).isoformat().replace('+00:00', 'Z'), 1, zone_id='COSMETICS'),
        make_event('hold-2-billing', 'VIS_B', 'BILLING_QUEUE_JOIN', (now + timedelta(minutes=6)).isoformat().replace('+00:00', 'Z'), 1, zone_id='BILLING', queue_depth=2),

        make_event('hold-3-entry', 'VIS_C', 'ENTRY', (now + timedelta(minutes=10)).isoformat().replace('+00:00', 'Z'), 1),
    ]
    ingest(events)

    funnel = client.get('/stores/STORE_BLR_002/funnel').json()
    assert funnel['stages'][0]['count'] == 3
    assert funnel['stages'][1]['count'] == 2
    assert funnel['stages'][2]['count'] == 1
    assert funnel['stages'][3]['count'] == 1
    assert funnel['stages'][1]['drop_off_pct'] == 33.33
    assert funnel['stages'][2]['drop_off_pct'] == 50.0
    assert funnel['stages'][3]['drop_off_pct'] == 0.0


def test_purchase_event_and_group_metadata():
    now = datetime.now(timezone.utc)
    event = make_event('purchase-event', 'VIS_1', 'PURCHASE', now.isoformat().replace('+00:00', 'Z'), 1)
    event['metadata']['group_size'] = 2

    result = ingest([event])
    assert result['accepted'] == 1

    metrics = client.get('/stores/STORE_BLR_002/metrics').json()
    funnel = client.get('/stores/STORE_BLR_002/funnel').json()

    assert metrics['session_count'] == 1
    assert metrics['conversion_rate'] == 100.0
    assert funnel['stages'][3]['count'] == 1


def test_anomaly_cases_for_queue_spike_and_conversion_drop():
    now = datetime.now(timezone.utc)
    older = now - timedelta(minutes=45)
    events = [
        make_event('an-1-entry', 'VIS_10', 'ENTRY', older.isoformat().replace('+00:00', 'Z'), 1),
        make_event('an-1-billing', 'VIS_10', 'BILLING_QUEUE_JOIN', older.isoformat().replace('+00:00', 'Z'), 1, zone_id='BILLING', queue_depth=1),
    ]
    for i in range(4):
        ts = (now - timedelta(minutes=10) + timedelta(seconds=i * 30)).isoformat().replace('+00:00', 'Z')
        events.append(make_event(f'an-recent-{i}', f'VIS_R{i}', 'BILLING_QUEUE_JOIN', ts, 1, zone_id='BILLING', queue_depth=1))
    events.append(make_event('an-recent-spike', 'VIS_R5', 'BILLING_QUEUE_JOIN', now.isoformat().replace('+00:00', 'Z'), 1, zone_id='BILLING', queue_depth=5))
    ingest(events)

    anomalies = client.get('/stores/STORE_BLR_002/anomalies').json()
    types = {item['type'] for item in anomalies}
    assert 'CONVERSION_DROP' in types
    assert 'QUEUE_SPIKE' in types
    assert 'DEAD_ZONE' in types


def test_dashboard_endpoint_returns_html():
    response = client.get('/dashboard')
    assert response.status_code == 200
    assert 'Store Intelligence Dashboard' in response.text


def test_health_endpoint_returns_status():
    response = client.get('/health')
    assert response.status_code == 200
    payload = response.json()
    assert 'status' in payload
    assert 'stale_feed' in payload
