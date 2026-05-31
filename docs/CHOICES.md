# CHOICES

## Model and Detection Approach
I selected a lightweight OpenCV-based detection pipeline instead of a full deep-learning model.

- **Why**: the challenge prioritizes end-to-end system correctness and production readiness over perfect detection accuracy.
- **Options**: YOLOv8/YOLOv9, MediaPipe, OpenCV HOG, background subtraction.
- **Decision**: use background subtraction and simple centroid tracking for structured event emission.
- **Rationale**: this keeps the pipeline portable, avoids heavy dependencies, and still produces session and zone events.

## Event Schema and Session Design
The event schema was intentionally kept close to the challenge catalog.

- `ENTRY` and `EXIT` are used to build sessions.
- `ZONE_ENTER`, `ZONE_EXIT`, and `ZONE_DWELL` capture zone behavior.
- `BILLING_QUEUE_JOIN` and `BILLING_QUEUE_ABANDON` support purchase and abandonment analysis.
- `REENTRY` preserves visitor continuity when the same person crosses the threshold again.

This design makes funnel and anomaly metrics computable from the same event stream.

## API Architecture
I chose FastAPI with SQLite.

- **Why**: FastAPI is lightweight, container-friendly, and supports schema validation out of the box.
- **Data storage**: SQLite provides a simple persistent backend for event ingestion without a separate database container.
- **Observability**: request middleware captures trace IDs, latency, status codes, and event counts.

## AI Assistance
I used an AI-assisted design review to confirm:
- that lightweight CV detection was a reasonable choice for a take-home case,
- that an event schema should prioritize session semantics,
- and that SQLite was a suitable production-aware persistence layer.

I intentionally overrode any AI recommendation that would add unnecessary model complexity in favor of a working, containerized system.
