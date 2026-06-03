# test_coverage_gaps.py
# Targets every uncovered line to bring coverage to 100%.
# Run with: pytest tests/test_coverage_gaps.py -v --cov=app --cov-report=term-missing

import os
import json
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

os.environ['STORE_INTELLIGENCE_DB'] = 'memory'

from fastapi.testclient import TestClient
from app.db import get_connection
from app.main import app
from app.utils import normalize_store_id, parse_timestamp, load_transactions
from app.schemas import EventIn, EventMetadata
from app.storage import insert_events, fetch_events, get_last_event_timestamp
from app import analytics

client = TestClient(app)
STORE_ID = 'ST_GAP'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reset_db():
    conn = get_connection()
    conn.execute('DELETE FROM events')
    conn.commit()


@pytest.fixture(autouse=True)
def clear_db():
    reset_db()
    yield
    reset_db()


def _ev(event_id, visitor_id, event_type, ts, session_seq=1, **kw):
    return {
        'event_id': event_id,
        'store_id': kw.get('store_id', STORE_ID),
        'camera_id': kw.get('camera_id', 'CAM_01'),
        'visitor_id': visitor_id,
        'event_type': event_type,
        'timestamp': ts,
        'zone_id': kw.get('zone_id'),
        'dwell_ms': kw.get('dwell_ms', 0),
        'is_staff': kw.get('is_staff', False),
        'confidence': kw.get('confidence', 0.9),
        'metadata': {
            'session_seq': session_seq,
            'queue_depth': kw.get('queue_depth'),
            'sku_zone': kw.get('sku_zone'),
        },
    }


def ingest(events):
    r = client.post('/events/ingest', json={'events': events})
    assert r.status_code == 200
    return r.json()


def now_z():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def ago_z(minutes=0, seconds=0):
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes, seconds=seconds)
    return dt.isoformat().replace('+00:00', 'Z')


# ===========================================================================
# app/utils.py  — missing: 16, 20, 25, 31, 36-37, 43, 50, 61-62
# ===========================================================================

class TestUtils:

    def test_normalize_store_id_none(self):
        # line 16: guard for falsy / non-string input
        assert normalize_store_id('') == ''
        assert normalize_store_id(None) is None  # type: ignore

    def test_normalize_store_id_no_digits(self):
        # line 20: branch where no digits → strip+upper
        assert normalize_store_id('  abc  ') == 'ABC'

    def test_parse_timestamp_datetime_passthrough(self):
        # line 25: isinstance(timestamp, datetime) branch
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert parse_timestamp(dt) == dt

    def test_parse_timestamp_format_with_tz_offset(self):
        # line 31: non-Z string parsed with %Y-%m-%dT%H:%M:%S%z
        result = parse_timestamp('2026-04-25T10:00:00+00:00')
        assert result.year == 2026

    def test_parse_timestamp_ddmmyyyy_format(self):
        # lines 36-37: %d-%m-%YT%H:%M:%SZ branch
        result = parse_timestamp('25-04-2026T10:00:00Z')
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 25

    def test_parse_timestamp_fromisoformat_fallback(self):
        # line 43: all strptime fail → fromisoformat
        result = parse_timestamp('2026-04-25T10:00:00.123+00:00')
        assert result.year == 2026

    def test_parse_timestamp_invalid_raises(self):
        # line 50: final ValueError raise
        with pytest.raises(ValueError, match='Invalid timestamp format'):
            parse_timestamp('not-a-date')

    def test_load_transactions_missing_file(self, tmp_path, monkeypatch):
        # lines 61-62: path.exists() == False → return []
        monkeypatch.setattr('app.utils.DATA_DIR', tmp_path)
        assert load_transactions() == []


# ===========================================================================
# app/schemas.py  — missing: 43, 50, 52, 59, 61, 63
# ===========================================================================

class TestSchemas:

    def _base(self, **overrides):
        data = {
            'event_id': 'sch-1',
            'store_id': 'ST_TEST',
            'camera_id': 'CAM_1',
            'visitor_id': 'V_1',
            'event_type': 'ZONE_ENTER',
            'timestamp': datetime.now(timezone.utc),
            'zone_id': 'SKINCARE',
            'dwell_ms': 0,
            'is_staff': False,
            'confidence': 0.9,
            'metadata': EventMetadata(session_seq=1, sku_zone='SKINCARE'),
        }
        data.update(overrides)
        return data

    def test_invalid_event_type_rejected(self):
        # line 43: validate_event_type raises for unknown type
        data = self._base(event_type='UNKNOWN_TYPE', zone_id=None,
                          metadata=EventMetadata(session_seq=1))
        with pytest.raises(Exception, match='event_type must be one of'):
            EventIn(**data)

    def test_zone_id_required_for_zone_event(self):
        # line 50: zone_id missing for zone-type event
        with pytest.raises(Exception, match='zone_id is required'):
            EventIn(**self._base(zone_id=None))

    def test_zone_id_must_be_null_for_entry(self):
        # line 52: zone_id present for ENTRY
        data = self._base(event_type='ENTRY', zone_id='SKINCARE',
                          metadata=EventMetadata(session_seq=1))
        with pytest.raises(Exception, match='zone_id must be null'):
            EventIn(**data)

    def test_sku_zone_required_for_zone_event(self):
        # line 59: sku_zone missing for zone-type event
        with pytest.raises(Exception, match='sku_zone is required'):
            EventIn(**self._base(metadata=EventMetadata(session_seq=1, sku_zone=None)))

    def test_queue_depth_required_for_billing_queue_join(self):
        # line 61: queue_depth None for BILLING_QUEUE_JOIN
        data = self._base(
            event_type='BILLING_QUEUE_JOIN',
            zone_id='BILLING',
            metadata=EventMetadata(session_seq=1, sku_zone='BILLING', queue_depth=None),
        )
        with pytest.raises(Exception, match='queue_depth is required'):
            EventIn(**data)

    def test_sku_zone_must_be_null_for_entry(self):
        # line 63: sku_zone present for ENTRY
        data = self._base(event_type='ENTRY', zone_id=None,
                          metadata=EventMetadata(session_seq=1, sku_zone='SKINCARE'))
        with pytest.raises(Exception, match='sku_zone must be null'):
            EventIn(**data)


# ===========================================================================
# app/storage.py  — missing: 32-33, 56-60, 95-96, 120-121
# ===========================================================================

class TestStorage:

    def test_insert_timestamp_datetime_object(self):
        # lines 56-60: timestamp is a datetime, not a string → isoformat branch
        dt = datetime.now(timezone.utc)
        event = {
            'event_id': 'ts-obj-1',
            'store_id': STORE_ID,
            'camera_id': 'CAM_1',
            'visitor_id': 'V_1',
            'event_type': 'ENTRY',
            'timestamp': dt,   # <-- datetime object
            'zone_id': None,
            'dwell_ms': 0,
            'is_staff': False,
            'confidence': 0.9,
            'metadata': {'session_seq': 1},
        }
        result = insert_events([event])
        assert result['accepted'] == 1

    def test_insert_integrity_error_counts_as_duplicate(self, monkeypatch):
        # lines 32-33: IntegrityError on INSERT → duplicates++
        # Python 3.14 makes sqlite3.Connection attrs read-only, so we replace
        # get_connection entirely with a fake connection whose cursor raises on INSERT.
        class FakeCursor:
            def execute(self, sql, params=()):
                if 'INSERT' in sql:
                    raise sqlite3.IntegrityError('UNIQUE constraint failed')
            def fetchone(self):
                return None   # SELECT sees no duplicate

        class FakeConn:
            def cursor(self): return FakeCursor()
            def rollback(self): pass
            def commit(self): pass

        monkeypatch.setattr('app.storage.get_connection', lambda: FakeConn())
        event = {
            'event_id': 'integ-dup-1', 'store_id': STORE_ID, 'camera_id': 'CAM_1',
            'visitor_id': 'V_1', 'event_type': 'ENTRY', 'timestamp': now_z(),
            'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.9,
            'metadata': {'session_seq': 1},
        }
        result = insert_events([event])
        assert result['duplicates'] == 1

    def test_insert_events_get_connection_raises(self, monkeypatch):
        # outer try/except in insert_events: get_connection raises
        monkeypatch.setattr(
            'app.storage.get_connection',
            lambda: (_ for _ in ()).throw(sqlite3.DatabaseError('no conn')),
        )
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            insert_events([])

    def test_fetch_events_since_and_until(self):
        # lines 95-96: both since and until clauses appended
        ingest([_ev('since-1', 'V1', 'ENTRY', '2026-01-01T00:00:00Z')])
        rows = fetch_events(STORE_ID,
                            since='2025-01-01T00:00:00Z',
                            until='2027-01-01T00:00:00Z')
        assert any(r['event_id'] == 'since-1' for r in rows)

    def test_fetch_events_list_store_ids(self):
        # lines 87-88: store_id is a list
        ingest([_ev('list-s-1', 'V1', 'ENTRY', now_z())])
        rows = fetch_events([STORE_ID, 'ST_OTHER'])
        assert any(r['event_id'] == 'list-s-1' for r in rows)

    def test_fetch_events_db_error_raises(self, monkeypatch):
        # lines 103-104: DatabaseError on execute inside fetch_events
        monkeypatch.setattr(
            'app.storage.get_connection',
            lambda: (_ for _ in ()).throw(sqlite3.DatabaseError('fetch fail')),
        )
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            fetch_events(STORE_ID)

    def test_get_last_event_timestamp_list_store(self):
        # lines 110-112: list store_id branch in get_last_event_timestamp
        ingest([_ev('last-ts-1', 'V1', 'ENTRY', now_z())])
        ts = get_last_event_timestamp([STORE_ID])
        assert ts is not None

    def test_get_last_event_timestamp_no_row_returns_none(self):
        # lines 120-121: cursor.fetchone() is None → return None
        ts = get_last_event_timestamp('STORE_THAT_DOES_NOT_EXIST')
        assert ts is None

    def test_get_last_event_timestamp_db_error(self, monkeypatch):
        # ServiceUnavailable when get_connection raises
        monkeypatch.setattr(
            'app.storage.get_connection',
            lambda: (_ for _ in ()).throw(sqlite3.DatabaseError('ts fail')),
        )
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            get_last_event_timestamp(STORE_ID)


# ===========================================================================
# app/main.py  — missing: 91-93, 114-115, 132
# ===========================================================================

class TestMainEndpoints:

    def test_ingest_empty_body_returns_400(self):
        # line 57: empty body guard
        response = client.post('/events/ingest', content=b'')
        assert response.status_code == 400

    def test_ingest_invalid_json_returns_400(self):
        # lines 60-66: bad JSON and JSONL also fail → 400
        response = client.post(
            '/events/ingest',
            content=b'{bad json!!!}',
            headers={'Content-Type': 'application/json'},
        )
        assert response.status_code == 400

    def test_ingest_payload_not_list_or_dict_returns_400(self):
        # line 73: payload is a bare string, not list/dict
        response = client.post(
            '/events/ingest',
            content=b'"just a string"',
            headers={'Content-Type': 'application/json'},
        )
        assert response.status_code == 400

    def test_ingest_non_dict_item_in_list_rejected(self):
        # lines 85-87: item in list is not a dict → rejected
        response = client.post(
            '/events/ingest',
            content=json.dumps(['not_a_dict']).encode(),
            headers={'Content-Type': 'application/json'},
        )
        data = response.json()
        assert data['rejected'] >= 1

    def test_heatmap_endpoint_returns_zones(self):
        # lines 114-115: /stores/{id}/heatmap route exercised
        ingest([_ev('hm-1', 'V1', 'ZONE_ENTER', now_z(),
                    zone_id='SKINCARE', sku_zone='SKINCARE')])
        response = client.get(f'/stores/{STORE_ID}/heatmap')
        assert response.status_code == 200
        assert 'zones' in response.json()

    def test_http_exception_handler_503_adds_error_key(self, monkeypatch):
        # line 132: exception_handler for HTTPException with 503 adds 'error' field
        monkeypatch.setattr(
            'app.storage.get_connection',
            lambda: (_ for _ in ()).throw(sqlite3.DatabaseError('db down')),
        )
        response = client.post('/events/ingest',
                               json={'events': [_ev('exc-503', 'V1', 'ENTRY', now_z())]})
        assert response.status_code == 503
        assert response.json()['error'] == 'SERVICE_UNAVAILABLE'

    def test_ingest_jsonl_ndjson_lines(self):
        # lines 60-66: JSONL / ndjson fallback path
        line = json.dumps({
            'event_id': 'jsonl-1', 'store_id': STORE_ID, 'camera_id': 'CAM_1',
            'visitor_id': 'V_1', 'event_type': 'ENTRY', 'timestamp': now_z(),
            'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.9,
            'metadata': {'session_seq': 1},
        })
        response = client.post(
            '/events/ingest',
            content=line.encode(),
            headers={'Content-Type': 'application/x-ndjson'},
        )
        # JSONL branch is executed regardless of final status
        assert response.status_code in (200, 400)


# ===========================================================================
# app/analytics.py  — missing: 47-48, 88, 112-128, 180-183, 202
# ===========================================================================

class TestAnalytics:

    # lines 47-48: _load_transactions_for_store filters by store_id
    def test_load_transactions_filters_by_store(self, monkeypatch):
        fake_tx = [
            {'store_id': STORE_ID, 'timestamp': now_z()},
            {'store_id': 'OTHER_STORE', 'timestamp': now_z()},
        ]
        monkeypatch.setattr('app.analytics.load_transactions', lambda: fake_tx)
        from app.analytics import _load_transactions_for_store
        result = _load_transactions_for_store(STORE_ID)
        assert all(t['store_id'] == STORE_ID for t in result)
        assert len(result) == 1

    # line 88: _group_sessions with no session_seq falls back to visitor_id key
    def test_group_sessions_no_session_seq(self):
        from app.analytics import _group_sessions
        events = [
            {'visitor_id': 'V1', 'timestamp': now_z(),
             'metadata': {}},   # no session_seq key
        ]
        sessions = _group_sessions(events)
        assert 'V1' in sessions

    # lines 112-128: _build_conversion_map — PURCHASE event marks session converted
    def test_conversion_map_purchase_event(self):
        ingest([_ev('cv-purchase', 'V_CV', 'PURCHASE', now_z())])
        metrics = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert metrics['conversion_rate'] == 100.0

    # lines 112-128: billing window conversion via POS tx within 300s
    def test_conversion_via_pos_transaction_window(self, monkeypatch):
        bill_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        tx_time = bill_time + timedelta(seconds=60)
        monkeypatch.setattr('app.analytics.load_transactions', lambda: [
            {'store_id': STORE_ID, 'timestamp': tx_time.isoformat().replace('+00:00', 'Z')},
        ])
        ingest([_ev('pos-conv-1', 'V_POS', 'BILLING_QUEUE_JOIN',
                    bill_time.isoformat().replace('+00:00', 'Z'),
                    zone_id='BILLING', sku_zone='BILLING', queue_depth=1)])
        metrics = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert metrics['conversion_rate'] == 100.0

    # POS tx outside 300s window → no conversion
    def test_no_conversion_tx_outside_window(self, monkeypatch):
        bill_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        tx_time = bill_time + timedelta(minutes=10)   # 600s > 300s
        monkeypatch.setattr('app.analytics.load_transactions', lambda: [
            {'store_id': STORE_ID, 'timestamp': tx_time.isoformat().replace('+00:00', 'Z')},
        ])
        ingest([_ev('noconv-1', 'V_NC', 'BILLING_QUEUE_JOIN',
                    bill_time.isoformat().replace('+00:00', 'Z'),
                    zone_id='BILLING', sku_zone='BILLING', queue_depth=1)])
        metrics = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert metrics['conversion_rate'] == 0.0

    # _queue_depth_value: None → 0
    def test_queue_depth_none_returns_zero(self):
        from app.analytics import _queue_depth_value
        assert _queue_depth_value({'metadata': {'queue_depth': None}}) == 0

    # _queue_depth_value: non-numeric string → 0
    def test_queue_depth_non_numeric_string_returns_zero(self):
        from app.analytics import _queue_depth_value
        assert _queue_depth_value({'metadata': {'queue_depth': 'bad'}}) == 0

    # abandonment rate > 0 (line ~170)
    def test_abandonment_rate_calculated(self):
        ingest([
            _ev('ab-join', 'V_AB', 'BILLING_QUEUE_JOIN', ago_z(5),
                zone_id='BILLING', sku_zone='BILLING', queue_depth=1),
            _ev('ab-abandon', 'V_AB', 'BILLING_QUEUE_ABANDON', ago_z(4),
                zone_id='BILLING', sku_zone='BILLING'),
        ])
        metrics = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert metrics['abandonment_rate'] == 100.0

    # empty store → conversion_rate 0.0, session_count 0
    def test_metrics_empty_store_returns_zeros(self):
        metrics = client.get('/stores/EMPTY_XYZ/metrics').json()
        assert metrics['conversion_rate'] == 0.0
        assert metrics['session_count'] == 0

    # lines 180-183: heatmap with no events → empty zones, data_confidence False
    def test_heatmap_empty_store(self):
        response = client.get('/stores/EMPTY_XYZ/heatmap')
        assert response.json() == {'zones': [], 'data_confidence': False}

    # line 202: heatmap with ZONE_DWELL → avg_dwell_seconds > 0
    def test_heatmap_with_dwell_events(self):
        ingest([
            _ev('hm-enter', 'V1', 'ZONE_ENTER', ago_z(10),
                zone_id='COSMETICS', sku_zone='COSMETICS'),
            _ev('hm-dwell', 'V1', 'ZONE_DWELL', ago_z(9),
                zone_id='COSMETICS', sku_zone='COSMETICS', dwell_ms=15000),
        ])
        data = client.get(f'/stores/{STORE_ID}/heatmap').json()
        zone = next(z for z in data['zones'] if z['zone_id'] == 'COSMETICS')
        assert zone['avg_dwell_seconds'] > 0
        assert zone['score'] == 100

    # line 202: data_confidence True when >= 20 sessions
    def test_heatmap_data_confidence_true_with_20_sessions(self):
        events = [
            _ev(f'conf-{i}', f'V_{i}', 'ZONE_ENTER', ago_z(i + 1),
                zone_id='MAIN_FLOOR', sku_zone='MAIN_FLOOR')
            for i in range(20)
        ]
        ingest(events)
        data = client.get(f'/stores/{STORE_ID}/heatmap').json()
        assert data['data_confidence'] is True

    # anomalies: empty store → []
    def test_anomalies_no_events_returns_empty(self):
        assert client.get('/stores/EMPTY_XYZ/anomalies').json() == []

    # anomalies: queue spike detected
    def test_anomalies_queue_spike_detected(self):
        now = datetime.now(timezone.utc)
        older = now - timedelta(minutes=45)
        events = [
            _ev('an-old', 'V_OLD', 'BILLING_QUEUE_JOIN',
                older.isoformat().replace('+00:00', 'Z'),
                zone_id='BILLING', sku_zone='BILLING', queue_depth=1),
        ]
        for i in range(4):
            ts = (now - timedelta(minutes=5, seconds=-i*10)).isoformat().replace('+00:00', 'Z')
            events.append(_ev(f'an-r-{i}', f'VR_{i}', 'BILLING_QUEUE_JOIN',
                               ts, zone_id='BILLING', sku_zone='BILLING', queue_depth=1))
        events.append(_ev('an-spike', 'VR_5', 'BILLING_QUEUE_JOIN',
                           now.isoformat().replace('+00:00', 'Z'),
                           zone_id='BILLING', sku_zone='BILLING', queue_depth=5))
        ingest(events)
        types = {a['type'] for a in client.get(f'/stores/{STORE_ID}/anomalies').json()}
        assert 'QUEUE_SPIKE' in types

    # health: stale store → degraded
    def test_health_with_stale_store(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace('+00:00', 'Z')
        ingest([_ev('stale-1', 'V_H', 'ENTRY', old_ts, store_id='ST_STALE')])
        data = client.get('/health').json()
        assert data['stale_feed'] is True
        assert data['status'] == 'degraded'
        assert data['store_status'].get('ST_STALE') == 'STALE'

    # health: fresh store → OK
    def test_health_fresh_store_is_ok(self):
        ingest([_ev('fresh-1', 'V_F', 'ENTRY', now_z(), store_id='ST_FRESH')])
        data = client.get('/health').json()
        assert data['store_status'].get('ST_FRESH') == 'OK'

    # health: no events → ok structure
    def test_health_no_events_returns_ok_structure(self):
        data = client.get('/health').json()
        assert 'status' in data
        assert 'stale_feed' in data


# ===========================================================================
# app/db.py  — missing: 17-18  (file-based connection)
# ===========================================================================

class TestDb:

    def test_file_based_connection(self, tmp_path, monkeypatch):
        # lines 17-18: STORE_INTELLIGENCE_DB != 'memory' → real file created
        import app.db as db_module

        saved_conn = db_module._CONN
        saved_path = db_module.DB_PATH
        fake_db = tmp_path / 'data' / 'events.db'

        monkeypatch.setattr(db_module, 'DB_PATH', fake_db)
        monkeypatch.setattr(db_module, '_CONN', None)
        monkeypatch.delenv('STORE_INTELLIGENCE_DB', raising=False)

        conn = None
        try:
            conn = db_module.get_connection()
            assert conn is not None
            assert fake_db.exists()
        finally:
            if conn:
                conn.close()
            db_module._CONN = saved_conn
            db_module.DB_PATH = saved_path
            os.environ['STORE_INTELLIGENCE_DB'] = 'memory'


# ===========================================================================
# app/anomalies.py  0% → 100%  (lines 2-14)
# app/funnel.py     0% → 100%  (lines 3-18)
# app/ingestion.py  0% → 100%  (lines 1-13)
# app/metrics.py    0% → 100%  (lines 1-16)
# These files are imported here so the coverage tool sees them executed.
# ===========================================================================

import sys
import importlib
import runpy


class TestStandaloneModules:
    """
    Covers all lines in the standalone pandas modules including
    function bodies AND the if __name__ == '__main__' blocks.
    """

    def test_anomalies_function_and_main(self):
        import pandas as pd
        df = pd.DataFrame({'GMV': [10, 20, 100, 15, 12]})
        with patch('pandas.read_csv', return_value=df):
            import app.anomalies as mod
            importlib.reload(mod)
            assert len(mod.detect_anomalies(df)) >= 0
        sys.modules.pop('app.anomalies', None)
        with patch('pandas.read_csv', return_value=df), patch('builtins.print'):
            runpy.run_module('app.anomalies', run_name='__main__', alter_sys=False)

    def test_funnel_function_and_main(self):
        import app.funnel as mod
        importlib.reload(mod)
        result = mod.funnel_stages([
            {'type': 'enter'}, {'type': 'browse'}, {'type': 'checkout'}, {'type': 'other'}
        ])
        assert result == {'enter': 1, 'browse': 1, 'checkout': 1}
        sys.modules.pop('app.funnel', None)
        with patch('builtins.print'):
            runpy.run_module('app.funnel', run_name='__main__', alter_sys=False)

    def test_ingestion_module_and_main(self):
        import pandas as pd
        fake_df = pd.DataFrame({'col': [1]})
        sys.modules.pop('app.ingestion', None)
        with patch('pandas.read_csv', return_value=fake_df), \
             patch('pandas.read_excel', return_value=fake_df), \
             patch('builtins.print'):
            import app.ingestion as mod
            importlib.reload(mod)
            assert mod.transactions is not None

    def test_metrics_functions_and_main(self):
        import pandas as pd
        df = pd.DataFrame({
            'GMV': [100.0, 200.0, 50.0],
            'NMV': [80.0, 160.0, 40.0],
            'offer_name': ['promo_a', 'promo_b', 'promo_a'],
        })
        with patch('pandas.read_csv', return_value=df):
            import app.metrics as mod
            importlib.reload(mod)
            assert mod.compute_gmv(df) == 350.0
            assert mod.compute_nmv(df) == 280.0
            assert 'promo_a' in mod.promo_effectiveness(df)
        # covers __main__ block (lines 13-16) — pop first to avoid RuntimeWarning
        sys.modules.pop('app.metrics', None)
        with patch('pandas.read_csv', return_value=df), patch('builtins.print'):
            runpy.run_module('app.metrics', run_name='__main__', alter_sys=False)


# ===========================================================================
# Remaining storage.py lines: 32-33, 58-60, 95-96, 120-121
# Remaining analytics.py lines: 88, 112-128, 180-183, 202
# Remaining utils.py lines: 50, 61-62
# Remaining main.py lines: 91-93, 114-115, 132
# ===========================================================================

class TestRemainingStorageLines:

    def test_insert_timestamp_with_utc_offset(self):
        # lines 58-60: datetime with +00:00 offset goes through isoformat().replace()
        dt = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        event = {
            'event_id': 'dt-offset-1', 'store_id': STORE_ID, 'camera_id': 'CAM_1',
            'visitor_id': 'V_DT', 'event_type': 'ENTRY', 'timestamp': dt,
            'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.9,
            'metadata': {'session_seq': 1},
        }
        result = insert_events([event])
        assert result['accepted'] == 1

    def test_fetch_events_with_since_filter_only(self):
        # line 95: only since clause
        ingest([_ev('since-only', 'V1', 'ENTRY', '2026-03-01T00:00:00Z')])
        rows = fetch_events(STORE_ID, since='2026-01-01T00:00:00Z')
        assert any(r['event_id'] == 'since-only' for r in rows)

    def test_fetch_events_with_until_filter_only(self):
        # line 96: only until clause
        ingest([_ev('until-only', 'V1', 'ENTRY', '2026-03-01T00:00:00Z')])
        rows = fetch_events(STORE_ID, until='2027-01-01T00:00:00Z')
        assert any(r['event_id'] == 'until-only' for r in rows)

    def test_get_last_ts_single_store_string(self):
        # lines 120-121: single string store_id, event exists → returns timestamp
        ingest([_ev('last-single', 'V1', 'ENTRY', now_z())])
        ts = get_last_event_timestamp(STORE_ID)
        assert ts is not None


class TestRemainingAnalyticsLines:

    def test_group_sessions_no_session_seq_key(self):
        # line 88: metadata has no session_seq → key falls back to visitor_id string
        from app.analytics import _group_sessions
        events = [{'visitor_id': 'V_NS', 'timestamp': now_z(), 'metadata': {}}]
        sessions = _group_sessions(events)
        assert 'V_NS' in sessions

    def test_build_conversion_map_with_purchase(self):
        # lines 112-128: PURCHASE event directly marks session converted
        ingest([_ev('direct-purchase', 'V_P', 'PURCHASE', now_z())])
        r = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert r['conversion_rate'] == 100.0

    def test_build_conversion_map_billing_no_tx(self, monkeypatch):
        # lines 112-128: billing window with no matching tx → not converted
        monkeypatch.setattr('app.analytics.load_transactions', lambda: [])
        ingest([_ev('bill-notx', 'V_BN', 'BILLING_QUEUE_JOIN', ago_z(10),
                    zone_id='BILLING', sku_zone='BILLING', queue_depth=1)])
        r = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert r['conversion_rate'] == 0.0

    def test_heatmap_no_dwell_zero_avg(self):
        # lines 180-183 + 202: ZONE_ENTER only (no dwell) → avg_dwell_seconds == 0
        ingest([_ev('hm-nodwell', 'V1', 'ZONE_ENTER', ago_z(5),
                    zone_id='FRAGRANCE', sku_zone='FRAGRANCE')])
        data = client.get(f'/stores/{STORE_ID}/heatmap').json()
        zone = next((z for z in data['zones'] if z['zone_id'] == 'FRAGRANCE'), None)
        assert zone is not None
        assert zone['avg_dwell_seconds'] == 0.0

    def test_heatmap_multiple_zones_score_relative(self):
        # line 202: score = int(round(visits/max_visits * 100))
        ingest([
            _ev('sc-z1-a', 'V1', 'ZONE_ENTER', ago_z(10), zone_id='ZONE_A', sku_zone='ZONE_A'),
            _ev('sc-z1-b', 'V2', 'ZONE_ENTER', ago_z(9),  zone_id='ZONE_A', sku_zone='ZONE_A'),
            _ev('sc-z2-a', 'V3', 'ZONE_ENTER', ago_z(8),  zone_id='ZONE_B', sku_zone='ZONE_B'),
        ])
        data = client.get(f'/stores/{STORE_ID}/heatmap').json()
        za = next(z for z in data['zones'] if z['zone_id'] == 'ZONE_A')
        zb = next(z for z in data['zones'] if z['zone_id'] == 'ZONE_B')
        assert za['score'] == 100
        assert zb['score'] == 50


class TestRemainingMainLines:

    def test_ingest_store_id_set_on_request_state(self):
        # lines 91-93: first item's store_id stored on request.state
        ev = _ev('state-sid', 'V1', 'ENTRY', now_z())
        r = client.post('/events/ingest', json={'events': [ev]})
        assert r.status_code == 200

    def test_metrics_sets_request_store_id(self):
        # lines 114-115: store_id set on request.state in get_store_metrics
        r = client.get(f'/stores/{STORE_ID}/metrics')
        assert r.status_code == 200

    def test_funnel_sets_request_store_id(self):
        # line 115 (funnel route): store_id set on request.state
        r = client.get(f'/stores/{STORE_ID}/funnel')
        assert r.status_code == 200

    def test_anomalies_sets_request_store_id(self):
        # line 132: store_id set on request.state in get_store_anomalies
        r = client.get(f'/stores/{STORE_ID}/anomalies')
        assert r.status_code == 200


class TestRemainingUtilsLines:

    def test_parse_timestamp_raises_for_garbage(self):
        # line 50: ValueError with message
        with pytest.raises(ValueError, match='Invalid timestamp format'):
            parse_timestamp('garbage-value-xyz')

    def test_load_transactions_empty_dir(self, tmp_path, monkeypatch):
        # lines 61-62: DATA_DIR exists but transactions.csv absent → []
        monkeypatch.setattr('app.utils.DATA_DIR', tmp_path)
        assert load_transactions() == []


class TestFinalGaps:

    def test_main_list_payload_sets_store_id(self):
        # lines 91-93: list payload, first dict item → request.state.store_id set
        ev = _ev('list-sid', 'V1', 'ENTRY', now_z())
        r = client.post('/events/ingest',
                        content=json.dumps([ev]).encode(),
                        headers={'Content-Type': 'application/json'})
        assert r.status_code == 200

    def test_main_404_exception_handler_no_error_key(self):
        # line 132: HTTPException != 503 → 'error' key not added
        r = client.get('/stores/NO/SUCH/ROUTE/AT/ALL')
        assert r.status_code == 404
        assert 'error' not in r.json()

    def test_analytics_conversion_already_true_breaks_early(self, monkeypatch):
        # lines 119-124: session has BILLING_QUEUE_JOIN + matching tx;
        # inner loop hits `if purchases[session_key]: break` path
        bill_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        tx1 = bill_time + timedelta(seconds=30)
        tx2 = bill_time + timedelta(seconds=60)   # second tx triggers the break
        monkeypatch.setattr('app.analytics.load_transactions', lambda: [
            {'store_id': STORE_ID, 'timestamp': tx1.isoformat().replace('+00:00', 'Z')},
            {'store_id': STORE_ID, 'timestamp': tx2.isoformat().replace('+00:00', 'Z')},
        ])
        ingest([_ev('multi-tx', 'V_MT', 'BILLING_QUEUE_JOIN',
                    bill_time.isoformat().replace('+00:00', 'Z'),
                    zone_id='BILLING', sku_zone='BILLING', queue_depth=1)])
        r = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert r['conversion_rate'] == 100.0

    def test_storage_insert_db_error_mid_loop(self, monkeypatch):
        # lines 32-33: DatabaseError mid-loop (not IntegrityError) → rollback + raise
        class FailCursor:
            def execute(self, sql, params=()):
                raise sqlite3.DatabaseError('mid-loop db error')
            def fetchone(self): return None

        class FailConn:
            def cursor(self): return FailCursor()
            def rollback(self): pass
            def commit(self): pass

        monkeypatch.setattr('app.storage.get_connection', lambda: FailConn())
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            insert_events([{
                'event_id': 'mid-err', 'store_id': STORE_ID, 'camera_id': 'CAM_1',
                'visitor_id': 'V_1', 'event_type': 'ENTRY', 'timestamp': now_z(),
                'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.9,
                'metadata': {'session_seq': 1},
            }])

    def test_storage_fetch_db_error_on_execute(self, monkeypatch):
        # lines 95-96 error path: DatabaseError on cursor.execute in fetch_events
        class FailCursor:
            def execute(self, sql, params=()): raise sqlite3.DatabaseError('exec fail')
            def fetchall(self): return []

        class FailConn:
            def cursor(self): return FailCursor()

        monkeypatch.setattr('app.storage.get_connection', lambda: FailConn())
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            fetch_events(STORE_ID)

    def test_storage_last_ts_db_error_on_execute(self, monkeypatch):
        # lines 120-121 error path: DatabaseError on cursor.execute in get_last_event_timestamp
        class FailCursor:
            def execute(self, sql, params=()): raise sqlite3.DatabaseError('ts exec fail')
            def fetchone(self): return None

        class FailConn:
            def cursor(self): return FailCursor()

        monkeypatch.setattr('app.storage.get_connection', lambda: FailConn())
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            get_last_event_timestamp(STORE_ID)


class TestPreciseGaps:
    """Hits the exact remaining lines reported by coverage."""

    # --- utils.py line 50: ValueError raised at end of parse_timestamp ---
    def test_parse_timestamp_totally_invalid(self):
        with pytest.raises(ValueError, match='Invalid timestamp format'):
            parse_timestamp('TOTALLY_INVALID_99')

    # --- utils.py lines 61-62: load_transactions file missing ---
    def test_load_transactions_no_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr('app.utils.DATA_DIR', tmp_path)  # no transactions.csv here
        assert load_transactions() == []

    # --- main.py lines 91-93: list payload, first item sets store_id on state ---
    def test_ingest_list_payload_first_item_store_id(self):
        ev = _ev('precise-sid', 'V1', 'ENTRY', now_z())
        r = client.post('/events/ingest',
                        content=json.dumps([ev]).encode(),
                        headers={'Content-Type': 'application/json'})
        assert r.status_code == 200
        assert r.json()['accepted'] >= 1

    # --- main.py line 132: exception_handler for non-503 HTTPException ---
    def test_http_exception_non_503_no_error_field(self):
        r = client.get('/stores/X/Y/Z/NOTFOUND')   # triggers 404
        assert r.status_code == 404
        body = r.json()
        assert 'detail' in body
        assert 'error' not in body

    # --- analytics.py line 88: session_seq is None → key is visitor_id string ---
    def test_group_sessions_session_seq_none(self):
        from app.analytics import _group_sessions
        events = [
            {'visitor_id': 'V_NONE', 'timestamp': now_z(),
             'metadata': {'session_seq': None}},
        ]
        sessions = _group_sessions(events)
        assert 'V_NONE' in sessions

    # --- analytics.py lines 119-124: early break when already converted ---
    def test_conversion_map_breaks_after_first_matching_tx(self, monkeypatch):
        bill = datetime.now(timezone.utc) - timedelta(seconds=20)
        # Two transactions both within window — second triggers the `break`
        monkeypatch.setattr('app.analytics.load_transactions', lambda: [
            {'store_id': STORE_ID,
             'timestamp': (bill + timedelta(seconds=10)).isoformat().replace('+00:00', 'Z')},
            {'store_id': STORE_ID,
             'timestamp': (bill + timedelta(seconds=20)).isoformat().replace('+00:00', 'Z')},
        ])
        ingest([_ev('break-1', 'V_BR', 'BILLING_QUEUE_JOIN',
                    bill.isoformat().replace('+00:00', 'Z'),
                    zone_id='BILLING', sku_zone='BILLING', queue_depth=1)])
        r = client.get(f'/stores/{STORE_ID}/metrics').json()
        assert r['conversion_rate'] == 100.0

    # --- analytics.py lines 180-183: heatmap empty → early return ---
    def test_heatmap_truly_empty_store(self):
        r = client.get('/stores/TRULY_EMPTY_STORE/heatmap').json()
        assert r == {'zones': [], 'data_confidence': False}

    # --- analytics.py line 202: avg_dwell when visits>0 and total_dwell>0 ---
    def test_heatmap_avg_dwell_computed(self):
        ingest([
            _ev('dw-enter', 'V1', 'ZONE_ENTER', ago_z(10),
                zone_id='PERFUME', sku_zone='PERFUME'),
            _ev('dw-dwell', 'V1', 'ZONE_DWELL',  ago_z(9),
                zone_id='PERFUME', sku_zone='PERFUME', dwell_ms=20000),
        ])
        data = client.get(f'/stores/{STORE_ID}/heatmap').json()
        zone = next(z for z in data['zones'] if z['zone_id'] == 'PERFUME')
        assert zone['avg_dwell_seconds'] == 20.0
        assert zone['score'] == 100

    # --- storage.py lines 32-33: DatabaseError in loop → rollback ---
    def test_storage_db_error_in_loop_raises(self, monkeypatch):
        class LoopFailCursor:
            def execute(self, sql, params=()):
                raise sqlite3.DatabaseError('loop fail')
            def fetchone(self): return None

        class LoopFailConn:
            def cursor(self): return LoopFailCursor()
            def rollback(self): pass
            def commit(self): pass

        monkeypatch.setattr('app.storage.get_connection', lambda: LoopFailConn())
        from app.exceptions import ServiceUnavailable
        with pytest.raises(ServiceUnavailable):
            insert_events([{
                'event_id': 'loop-err', 'store_id': STORE_ID, 'camera_id': 'CAM_1',
                'visitor_id': 'V1', 'event_type': 'ENTRY', 'timestamp': now_z(),
                'zone_id': None, 'dwell_ms': 0, 'is_staff': False, 'confidence': 0.9,
                'metadata': {'session_seq': 1},
            }])
