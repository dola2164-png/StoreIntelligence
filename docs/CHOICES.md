# Technical Choices & Rationale

## 1. Detection Model Choice: OpenCV MOG2 vs. Deep Learning

### Decision: Background Subtraction (OpenCV MOG2)

### Options Considered
1. **YOLOv8 Object Detection** — pre-trained CNN for person detection
2. **MediaPipe Pose** — lightweight pose estimation
3. **Custom HOG (Histogram of Oriented Gradients)** — hand-tuned feature extraction
4. **Background Subtraction (MOG2)** — statistical foreground/background decomposition ← **CHOSEN**

### Rationale

| Criterion | MOG2 | YOLOv8 | MediaPipe | HOG |
|-----------|------|--------|-----------|-----|
| CPU Cost | Low | High | Medium | Medium |
| Model Size | 0 | 450MB | 50MB | 0 |
| Frame/Sec (1080p) | 15–20 | 2–3 | 8–12 | 10–15 |
| Requires Training | No | No (pre-trained) | No | Yes |
| Handles Occlusion | Gracefully degrades | Works well | Fails on full-body occlusion | Mediocre |
| **Total 8 videos (144K frames, process every 5th)** | 2–3 min | 30–40 min | 10–15 min | ~5 min |

**Winner: MOG2** because:
- Processing 8 videos totaling 160 minutes CCTV footage at full frame rate is prohibitive with YOLOv8 on CPU
- MOG2 runs at native frame rate, processes entire dataset in ~3 minutes
- Sufficient accuracy for zone transitions and queue detection
- No external dependencies, no GPU required, fully portable

**AI Feedback**: ChatGPT suggested YOLOv8 for "better accuracy," but after analyzing latency trade-offs, MOG2 was endorsed as pragmatic for production ML systems with time budgets.

---

## 2. Event Schema Design

### Core Event Types

| Event Type | Trigger | Zone Populated | Dwell Populated | Metadata |
|------------|---------|----------------|-----------------|----------|
| ENTRY | Centroid crosses store entry threshold | N/A | N/A | group_size (if grouped entry) |
| EXIT | Centroid crosses store exit threshold | N/A | N/A | None |
| ZONE_ENTER | Visitor enters zone (SKINCARE/MAIN_FLOOR/COSMETICS/BILLING) | ✓ | N/A | None |
| ZONE_EXIT | Visitor exits zone | ✓ | N/A | None |
| ZONE_DWELL | Visitor in zone for ≥30 seconds | ✓ | ✓ (seconds) | None |
| BILLING_QUEUE_JOIN | Visitor enters billing zone | BILLING | N/A | queue_depth |
| BILLING_QUEUE_ABANDON | Visitor exits billing zone without purchase | BILLING | N/A | dwell_seconds |
| PURCHASE | Visitor exits billing zone with ≥45s dwell | BILLING | ✓ (dwell_ms) | None |
| REENTRY | Same visitor re-enters store (within 24h) | N/A | N/A | session_seq incremented |

### Why This Schema

1. **Enables Conversion Funnel**: ENTRY → ZONE_ENTER → BILLING_QUEUE_JOIN → PURCHASE traces customer journey
2. **Supports Zone Heatmaps**: ZONE_ENTER/EXIT + ZONE_DWELL provide zone-level engagement metrics
3. **Anomaly Detection**: BILLING_QUEUE_ABANDON and BILLING_QUEUE_JOIN enable queue spike/abandonment alerts
4. **Staff Exclusion**: is_staff flag prevents long-duration staff presence from inflating metrics
5. **Session Continuity**: visitor_id + session_seq enables re-entry tracking without ID collisions

### Trade-offs Made

- **Fixed zone definitions** (position-based) instead of ML-based zone detection
  - Simpler for production, no calibration needed
  - Downside: doesn't adapt to store layout changes
  - Future: add store_layout.json zone calibration

- **Dwell in milliseconds** instead of events per N seconds
  - Better accuracy for correlation with POS transactions
  - Reduces event volume (single ZONE_DWELL vs. multiple periodic events)

---

## 3. API Architecture: FastAPI + SQLite

### Decision: FastAPI REST API + SQLite persistent storage

### Options Considered
1. **FastAPI + SQLite** ← **CHOSEN**
2. **FastAPI + PostgreSQL** (separate container)
3. **GraphQL + Firebase/Firestore**
4. **gRPC + Protocol Buffers + Datastore**

### Comparison

| Aspect | FastAPI + SQLite | FastAPI + PostgreSQL | GraphQL | gRPC |
|--------|------------------|----------------------|---------|------|
| Setup Complexity | Simple (1 container) | Complex (2 containers) | Medium | Complex |
| Query Flexibility | Ad-hoc SQL | Ad-hoc SQL + advanced joins | Fixed schema | Pre-compiled |
| Scaling | Limited (single file) | Horizontal (connection pool) | Horizontal | Excellent |
| Observability | JSON logs | JSON logs + DB logs | Introspection | Protobufs |
| Type Safety | Pydantic | Pydantic + ORM | Weak (runtime) | Strong |
| Time to Production | 1–2 hours | 4–6 hours | 3–4 hours | 6–8 hours |

**Winner: FastAPI + SQLite** because:
- Single-container deployment aligns with Docker Compose requirement
- Pydantic validation provides strong input validation
- SQLite sufficient for ≤10K events/hour (challenge is ≤5K)
- Hot reload during development via volume mount
- Structured logging via middleware
- Idempotent POST /events/ingest by event_id ensures safety

**Scaling Path**: If dataset exceeds 1M events, migrate to PostgreSQL with same Pydantic/SQLAlchemy code.

### Why Not X?

- **Not GraphQL**: Fixed query patterns (metrics, funnel, heatmap) don't require ad-hoc query flexibility
- **Not gRPC**: Browser dashboard needs REST + JSON, gRPC adds transport bridging complexity
- **Not Firebase**: Cold-start latency + vendor lock-in; SQLite gives full control

---

## 4. Multi-Store Support Design

### Decision: Store ID in event payload + store_layout.json config

### How It Works

1. **Data Organization**: Videos organized in `data/Store 1/`, `data/Store 2/`, etc.
2. **Camera Mapping**: `store_layout.json` maps video filenames to store_id and camera roles
3. **Event Ingestion**: Each event includes store_id; POST /events/ingest handles multiple stores
4. **Querying**: `/stores/{id}/metrics` returns metrics for that store_id only

### Trade-offs

- **One store_id per store folder** (current): Simple config, deterministic
- **Dynamic store discovery**: Would require auto-registration API endpoint (future)

---

## 5. Session Deduplication & Re-Entry

### Decision: Centroid tracking + session_seq counter

### Algorithm

```
For each frame:
  1. Detect foreground blobs via MOG2 background subtraction
  2. For each blob:
     - Compute centroid (x, y)
     - Match to existing track within 80-pixel distance
     - If match found: update track, continue visitor_id
     - If no match: new track, new visitor_id
  3. For each lost track (no match for 25+ frames):
     - Emit EXIT event
     - Increment session_seq (tracks re-entry)
```

### Why Centroid Tracking

- **Simple**: O(n²) for n people per frame; acceptable for retail (<20 simultaneous)
- **Deterministic**: No learned model, no randomness, reproducible
- **Handles re-entry**: New ENTRY after EXIT implicitly increments session_seq

### Limitations

- **Cross-camera Re-ID**: If visitor walks from floor camera to entry camera, gets new visitor_id
- **Occlusion**: Temporary occlusion breaks track if >25 frames (~1.7 seconds)
- **Dense crowds**: >20 simultaneous people causes ID fragmentation

**Future Improvement**: Add lightweight Re-ID model (OSNet) for cross-camera tracking.

---

## 6. Conversion Correlation

### Decision: Dual-mode correlation (PURCHASE event OR transaction match)

### Logic

A visitor is marked **converted** if:

1. **Primary**: PURCHASE event in their session (billing_queue_join + ≥45s dwell → PURCHASE)
   ```
   is_converted = any(e.event_type == 'PURCHASE' for e in session.events)
   ```

2. **Fallback**: POS transaction within 5 minutes of billing zone entry
   ```
   billing_entry_time = first(e.timestamp for e in session if e.event_type == 'BILLING_QUEUE_JOIN')
   is_converted = any(billing_entry_time <= tx.timestamp <= billing_entry_time + 5min 
                      for tx in pos_transactions)
   ```

### Rationale

- **Handles missed frames**: CCTV may miss exact purchase moment (customer at far corner of billing zone)
- **Matches transaction time**: POS system has independent timestamp; matching adds confidence
- **Deduplication**: If both signals exist, transaction overrides (authoritative source)

---

## 7. Anomaly Detection Thresholds

### Queue Spike
- **Trigger**: current_queue_depth > 1.75 × avg_queue_depth AND current_queue_depth ≥ 3
- **Rationale**: 75% increase + minimum absolute depth prevents false positives during slow hours

### Conversion Drop
- **Trigger**: conversion_rate < 15% AND session_count ≥ 5 (in last 1 hour)
- **Rationale**: 15% is industry baseline for retail; require ≥5 visitors before flagging

### Dead Zone
- **Trigger**: zone_visit_count == 0 for 30+ minutes
- **Rationale**: Zone with zero visits suggests fixture down/blocked/merchandising

---

## 8. Logging & Observability

### Structured Logging Format

```json
{
  "trace_id": "req-uuid-here",
  "timestamp": "2025-04-15T10:30:45Z",
  "level": "info",
  "path": "/events/ingest",
  "method": "POST",
  "status_code": 200,
  "latency_ms": 42,
  "message": "Events ingested",
  "accepted": 2591,
  "duplicates": 0,
  "rejected": 0
}
```

### Why Structured

- Enables automated alerting on latency_ms > 100 or status_code >= 500
- Distributed tracing compatible (trace_id shared across services)
- Log aggregation tools (ELK, Datadog) can parse JSON natively

---

## Decisions NOT Made (Deferred)

| Feature | Why Deferred |
|---------|-------------|
| **Cross-camera Re-ID** | Complex; centroid tracking sufficient for challenge scope |
| **Real-time alerts via WebSocket** | REST polling adequate; WebSocket adds complexity |
| **Distributed tracing (Jaeger)** | Single service; no inter-service communication yet |
| **Caching layer (Redis)** | Metrics computed on-demand; DB lookup fast enough |
| **Multi-region deployment** | Single store deployment is MVP |

- that an event schema should prioritize session semantics,
- and that SQLite was a suitable production-aware persistence layer.

I intentionally overrode any AI recommendation that would add unnecessary model complexity in favor of a working, containerized system.
