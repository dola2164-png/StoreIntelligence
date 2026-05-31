# DESIGN

## Architecture Overview

The Store Intelligence system is designed as a clear separation between a detection layer and an analytics API.

- `pipeline/detect.py` processes raw CCTV clips in `data/` and emits structured visitor events into `data/events.jsonl`.
- `app/` contains a FastAPI service that ingests events, stores them in SQLite, and computes metrics in real time.
- `docker-compose.yml` launches the API container so the system can be started with a single command.

## Event Stream Schema

The event schema is designed to support sessions, zone analytics, billing behavior, and anomaly detection.

Each event has:
- `event_id`: UUID v4 for idempotency.
- `store_id`, `camera_id`, `visitor_id` for event context.
- `event_type`: one of the required types such as `ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `EXIT`, and `REENTRY`.
- `timestamp`: ISO-8601 UTC.
- `zone_id`: populated for zone/billing events.
- `dwell_ms`, `is_staff`, `confidence` and structured `metadata`.

## API Design

The API stores events in SQLite with a `store_id` and `visitor_id` index for fast query.

- Ingestion is idempotent by `event_id`.
- Partial success returns accepted, duplicate, and rejected counts.
- Metrics are computed on demand from stored events; the API is intentionally real-time and not static.
- The health endpoint reports both service status and stale feed warnings.

## Pipeline Design

The detection pipeline uses OpenCV background subtraction and a lightweight tracker to produce visitor sessions from individual camera clips.

- Entry cameras use a threshold crossing to emit `ENTRY` and `EXIT` events, with grouping metadata added when guests enter together.
- Floor cameras create `ZONE_ENTER`, `ZONE_EXIT`, and `ZONE_DWELL` events based on centroid zones.
- The billing camera emits `BILLING_QUEUE_JOIN`, on-exit `PURCHASE`, and `BILLING_QUEUE_ABANDON` events using a dwell-based purchase inference heuristic.
- Long-lived detections without an entry/exit crossing are marked as `is_staff` to prevent staff from skewing customer analytics.

This design keeps the pipeline simple, traceable, and compatible with the challenge event schema while improving edge-case consistency and session completeness.

## AI-Assisted Decisions

### 1. Detection Model Choice
I used OpenCV motion detection rather than a heavy learned model.
- Options considered: YOLOv8, MediaPipe, custom heuristics.
- AI suggested using a lightweight approach when real-time inference is not available.
- I chose background subtraction plus simple tracking because it works with raw CCTV footage and avoids model dependency issues.

### 2. Event Schema Design
I kept the schema close to the challenge requirements while ensuring every event carries the metadata needed for analytics.
- Options considered: additional `PURCHASE` event versus inferring conversions from billing events and POS records.
- AI suggested schema-driven design with explicit session tokens.
- I chose the latter so the API can compute funnel and conversion metrics from the same stream.

### 3. API Architecture
I used FastAPI + SQLite for instant containerized deployment.
- Options considered: in-memory store, PostgreSQL, file-based JSON store.
- AI suggested SQLite as a good production-like lightweight database for a take-home project.
- I chose SQLite because it preserves events across restarts and is easy to containerize.
