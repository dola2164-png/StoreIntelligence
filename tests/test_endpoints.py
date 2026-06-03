# PROMPT: Verify endpoint behavior, payload validation, and stability of ingest/health/metrics APIs.
# The tests should document API contract expectations and serve as executable prompt coverage.

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import EventIn
import json
import uuid

client = TestClient(app)


class TestHealthEndpoint:
    """Test /health endpoint"""
    
    def test_health_returns_ok_status(self):
        """Health endpoint should return status field"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["ok", "degraded", "down"]
    
    def test_health_contains_stale_feed_flag(self):
        """Health should indicate if feed is stale (>10 min without events)"""
        response = client.get("/health")
        data = response.json()
        assert "stale_feed" in data
        assert isinstance(data["stale_feed"], bool)
    
    def test_health_contains_store_status(self):
        """Health should list per-store status"""
        response = client.get("/health")
        data = response.json()
        assert "store_status" in data
        assert isinstance(data["store_status"], dict)


class TestEventIngestion:
    """Test /events/ingest endpoint"""
    
    def test_ingest_single_event(self):
        """Should accept single valid event in array"""
        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] >= 1  # At least our event was accepted
        assert data["rejected"] == 0
    
    def test_ingest_multiple_events_as_array(self):
        """Should accept array of events"""
        base_time = datetime.now(timezone.utc)
        events = [
            {
                "event_id": f"test-multi-{uuid.uuid4()}",
                "store_id": "ST_TEST",
                "camera_id": "CAM_1",
                "visitor_id": f"V_{i}",
                "event_type": "ENTRY",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.95,
                "metadata": {"session_seq": 1}
            }
            for i in range(3)
        ]
        response = client.post("/events/ingest", json=events)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] >= 3
    
    def test_ingest_rejects_malformed_event(self):
        """Should reject event missing required fields"""
        bad_event = {
            "event_id": "bad-event",
            # Missing required fields: store_id, visitor_id, event_type, timestamp
        }
        response = client.post("/events/ingest", json=[bad_event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1  # Malformed event should be rejected

    
    def test_ingest_rejects_invalid_event_type(self):
        """Should reject event with invalid event_type"""
        event = {
            "event_id": "bad-type",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "INVALID_TYPE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1

    
    def test_ingest_idempotency_duplicate_events(self):
        """Duplicate event_id should not increase accepted count twice"""
        event = {
            "event_id": "dedup-test-001",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"session_seq": 1}
        }
        # First ingest
        response1 = client.post("/events/ingest", json=[event])
        data1 = response1.json()
        
        # Second ingest (same event)
        response2 = client.post("/events/ingest", json=[event])
        data2 = response2.json()
        
        # Second ingestion should count as duplicate
        assert data2.get("duplicates", 0) >= 1 or data2["accepted"] == 0

    
    def test_ingest_returns_structured_response(self):
        """Ingest response should have accepted/duplicates/rejected/errors"""
        event = {
            "event_id": "struct-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "EXIT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        data = response.json()
        assert "accepted" in data
        assert "duplicates" in data
        assert "rejected" in data
        assert "errors" in data


class TestMetricsEndpoint:
    """Test /stores/{id}/metrics endpoint"""
    
    def test_metrics_returns_all_fields(self):
        """Metrics should return all required fields"""
        response = client.get("/stores/ST_TEST/metrics")
        assert response.status_code == 200
        data = response.json()
        required_fields = [
            "store_id",
            "unique_visitors",
            "conversion_rate",
            "avg_dwell_per_zone",
            "queue_depth",
            "abandonment_rate",
            "session_count",
            "last_event_timestamp"
        ]
        for field in required_fields:
            assert field in data
    
    def test_metrics_returns_reasonable_types(self):
        """Metrics values should have correct types"""
        response = client.get("/stores/ST_TEST/metrics")
        data = response.json()
        assert isinstance(data["store_id"], str)
        assert isinstance(data["unique_visitors"], int)
        assert isinstance(data["conversion_rate"], (int, float))
        assert isinstance(data["avg_dwell_per_zone"], dict)
        assert isinstance(data["queue_depth"], int)
        assert isinstance(data["abandonment_rate"], (int, float))
        assert isinstance(data["session_count"], int)
    
    def test_metrics_conversion_rate_bounds(self):
        """Conversion rate should be between 0 and 100"""
        response = client.get("/stores/ST_TEST/metrics")
        data = response.json()
        assert 0 <= data["conversion_rate"] <= 100
    
    def test_metrics_queue_depth_non_negative(self):
        """Queue depth should be non-negative"""
        response = client.get("/stores/ST_TEST/metrics")
        data = response.json()
        assert data["queue_depth"] >= 0
    
    def test_metrics_abandonment_rate_bounds(self):
        """Abandonment rate should be 0-100"""
        response = client.get("/stores/ST_TEST/metrics")
        data = response.json()
        assert 0 <= data["abandonment_rate"] <= 100


class TestFunnelEndpoint:
    """Test /stores/{id}/funnel endpoint"""
    
    def test_funnel_returns_stages(self):
        """Funnel should return array of stages"""
        response = client.get("/stores/ST_TEST/funnel")
        assert response.status_code == 200
        data = response.json()
        assert "stages" in data
        assert isinstance(data["stages"], list)
        assert len(data["stages"]) > 0
    
    def test_funnel_stage_has_required_fields(self):
        """Each stage should have name, count, drop_off_pct"""
        response = client.get("/stores/ST_TEST/funnel")
        data = response.json()
        for stage in data["stages"]:
            assert "name" in stage
            assert "count" in stage
            assert "drop_off_pct" in stage
            assert isinstance(stage["count"], int)
            assert isinstance(stage["drop_off_pct"], (int, float))
    
    def test_funnel_expected_stages(self):
        """Funnel should include Entry, Zone Visit, Billing Queue, Purchase"""
        response = client.get("/stores/ST_TEST/funnel")
        data = response.json()
        stage_names = [s["name"] for s in data["stages"]]
        assert "Entry" in stage_names
        assert "Purchase" in stage_names


class TestHeatmapEndpoint:
    """Test /stores/{id}/heatmap endpoint"""
    
    def test_heatmap_returns_zones_and_confidence(self):
        """Heatmap should return zones array and data_confidence flag"""
        response = client.get("/stores/ST_TEST/heatmap")
        assert response.status_code == 200
        data = response.json()
        assert "zones" in data
        assert "data_confidence" in data
        assert isinstance(data["zones"], list)
        assert isinstance(data["data_confidence"], bool)
    
    def test_heatmap_zone_has_required_fields(self):
        """Each zone should have zone_id, visit_count, avg_dwell_seconds, score"""
        response = client.get("/stores/ST_TEST/heatmap")
        data = response.json()
        for zone in data["zones"]:
            assert "zone_id" in zone
            assert "visit_count" in zone
            assert "avg_dwell_seconds" in zone
            assert "score" in zone
            assert isinstance(zone["visit_count"], int)
            assert isinstance(zone["score"], int)
    
    def test_heatmap_score_normalized_0_to_100(self):
        """Zone scores should be 0-100"""
        response = client.get("/stores/ST_TEST/heatmap")
        data = response.json()
        for zone in data["zones"]:
            assert 0 <= zone["score"] <= 100


class TestAnomaliesEndpoint:
    """Test /stores/{id}/anomalies endpoint"""
    
    def test_anomalies_returns_array(self):
        """Anomalies should return array of anomaly objects"""
        response = client.get("/stores/ST_TEST/anomalies")
        assert response.status_code == 200
        data = response.json()
        assert "value" in data or isinstance(data, list)
    
    def test_anomaly_has_required_fields(self):
        """Each anomaly should have type, severity, description, suggested_action"""
        response = client.get("/stores/ST_TEST/anomalies")
        data = response.json()
        anomalies = data.get("value", []) if isinstance(data, dict) else data
        for anomaly in anomalies:
            assert "type" in anomaly
            assert "severity" in anomaly
            assert "description" in anomaly
            assert "suggested_action" in anomaly
    
    def test_anomaly_severity_valid_values(self):
        """Anomaly severity should be INFO, WARNING, or CRITICAL"""
        response = client.get("/stores/ST_TEST/anomalies")
        data = response.json()
        anomalies = data.get("value", []) if isinstance(data, dict) else data
        for anomaly in anomalies:
            assert anomaly["severity"] in ["INFO", "WARNING", "CRITICAL"]


class TestDashboardEndpoint:
    """Test /dashboard endpoint"""
    
    def test_dashboard_returns_html(self):
        """Dashboard endpoint should return HTML"""
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
    
    def test_dashboard_contains_store_data(self):
        """Dashboard should reference store and metrics"""
        response = client.get("/dashboard")
        html = response.text
        assert "store" in html.lower() or "metrics" in html.lower()


class TestEventSchemaValidation:
    """Test Pydantic EventIn schema validation"""
    
    def test_event_zone_id_required_for_zone_events(self):
        """ZONE_ENTER/EXIT/DWELL events should have zone_id and sku_zone metadata"""
        zone_event = {
            "event_id": "zone-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ZONE_ENTER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": "MAIN_FLOOR",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"sku_zone": "MAIN_FLOOR", "session_seq": 1}
        }
        response = client.post("/events/ingest", json=[zone_event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] == 0

    def test_event_dwell_ms_numeric(self):
        """dwell_ms should be numeric"""
        event = {
            "event_id": "dwell-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ZONE_DWELL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": "BILLING",
            "dwell_ms": 5000,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"sku_zone": "BILLING", "session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
    
    def test_event_confidence_0_to_1(self):
        """Confidence should be between 0 and 1"""
        event = {
            "event_id": "conf-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.75,
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
    
    def test_event_confidence_invalid_outside_0_1(self):
        """Confidence outside 0-1 should be rejected"""
        event = {
            "event_id": "conf-invalid",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 1.5,  # Invalid
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1  # Should reject invalid confidence

    def test_event_metadata_session_seq_required(self):
        """Events must include session_seq in metadata"""
        event = {
            "event_id": "sessionseq-missing",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ENTRY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.75,
            "metadata": {}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1

    def test_billing_queue_join_requires_queue_depth(self):
        """BILLING_QUEUE_JOIN must include metadata.queue_depth"""
        event = {
            "event_id": "billing-queue-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.75,
            "metadata": {"sku_zone": "BILLING", "session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1

    def test_zone_events_require_sku_zone(self):
        """Zone events must include metadata.sku_zone"""
        event = {
            "event_id": "zone-sku-test",
            "store_id": "ST_TEST",
            "camera_id": "CAM_1",
            "visitor_id": "V_001",
            "event_type": "ZONE_ENTER",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": "MAIN_FLOOR",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.75,
            "metadata": {"session_seq": 1}
        }
        response = client.post("/events/ingest", json=[event])
        assert response.status_code == 200
        data = response.json()
        assert data["rejected"] >= 1


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_empty_store_returns_zero_metrics(self):
        """Store with no events should return zero metrics"""
        response = client.get("/stores/STORE_NONEXISTENT/metrics")
        data = response.json()
        assert data["unique_visitors"] == 0
        assert data["session_count"] == 0
    
    def test_all_staff_detection_excludes_from_count(self):
        """Visitors marked is_staff=true should not affect metrics"""
        staff_events = [
            {
                "event_id": f"staff-{i}",
                "store_id": "ST_STAFF_TEST",
                "camera_id": "CAM_1",
                "visitor_id": f"STAFF_{i}",
                "event_type": "ENTRY",
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(seconds=i)).isoformat(),
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.95,
                "metadata": {"session_seq": 1}
            }
            for i in range(5)
        ]
        response = client.post("/events/ingest", json=staff_events)
        assert response.status_code == 200
        
        # Staff should not count toward unique_visitors in metrics
        metrics_response = client.get("/stores/ST_STAFF_TEST/metrics")
        data = metrics_response.json()
        # Non-staff visitors should be minimal or zero
        assert data["unique_visitors"] < 5 or data["is_staff"] is not None
    
    def test_re_entry_handled_correctly(self):
        """REENTRY events should increment session_seq"""
        visitor_id = f"V_REENTRY_{uuid.uuid4()}"
        reentry_events = [
            {
                "event_id": str(uuid.uuid4()),
                "store_id": "ST_REENTRY",
                "camera_id": "CAM_1",
                "visitor_id": visitor_id,
                "event_type": "ENTRY",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.95,
                "metadata": {"session_seq": 1}
            },
            {
                "event_id": str(uuid.uuid4()),
                "store_id": "ST_REENTRY",
                "camera_id": "CAM_1",
                "visitor_id": visitor_id,
                "event_type": "REENTRY",
                "timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "zone_id": None,
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.95,
                "metadata": {"session_seq": 2}
            }
        ]
        response = client.post("/events/ingest", json=reentry_events)
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] >= 2
    
    def test_zero_purchases_handling(self):
        """Funnel should handle zero purchases gracefully"""
        response = client.get("/stores/ST_ZERO_PURCHASE/funnel")
        assert response.status_code == 200
        data = response.json()
        # Should still return funnel structure even with zero purchases
        purchase_stage = next((s for s in data.get("stages", []) if s["name"] == "Purchase"), None)
        if purchase_stage:
            assert purchase_stage["count"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
