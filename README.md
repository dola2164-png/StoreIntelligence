# Store Intelligence

This repository implements a working Store Intelligence pipeline from raw CCTV clips to a live metrics API.

## Store ID mapping is set as ST1008 → STORE_BLR_002(keep in mind)

## What is included

- `app/`: FastAPI service with structured event ingestion and metrics endpoints.
- `pipeline/`: CCTV detection pipeline that emits structured visitor events to `data/events.jsonl`.
- `data/`: Sample videos, transaction data, store layout configuration, and generated events.
- `docker-compose.yml`: Starts the API service with no manual intervention.
- `tests/`: Pytest coverage for ingestion idempotency and basic API responses.
- `docs/DESIGN.md`: Architecture overview and AI-assisted decisions.
- `docs/CHOICES.md`: Decision log for model selection and system trade-offs.

## Setup

```bash
cd store-intelligence
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the API

```bash
docker compose up --build
```

Then visit `http://localhost:8000/health`.

## Run the detection pipeline

```bash
cd pipeline
./run.sh
```

The pipeline writes events to `data/events.jsonl`.

## Ingest events into the API

```bash
curl -X POST http://localhost:8000/events/ingest \
  -H 'Content-Type: application/json' \
  --data-binary @data/events.jsonl
```

On PowerShell, use the real curl executable or `Invoke-RestMethod`:

```powershell
curl.exe -X POST "http://localhost:8000/events/ingest" `
  -H "Content-Type: application/json" `
  --data-binary "@data/events.jsonl"
```

or

```powershell
$body = Get-Content .\data\events.jsonl -Raw
Invoke-RestMethod -Uri "http://localhost:8000/events/ingest" -Method Post -ContentType "application/json" -Body $body
```

The API now also accepts line-delimited JSONL event payloads directly from `events.jsonl`.

## Endpoints

- `POST /events/ingest` — accepts up to 500 structured events, deduplicates by `event_id`, returns partial success.
- `GET /stores/{id}/metrics` — unique visitors, conversion rate, dwell, queue, abandonment.
- `GET /stores/{id}/funnel` — session-based entry-to-purchase funnel.
- `GET /stores/{id}/heatmap` — zone frequency and dwell heatmap scores.
- `GET /stores/{id}/anomalies` — active store anomalies.
- `GET /dashboard` — live dashboard for metrics and anomaly inspection.
- `GET /health` — service and feed health.

## Validation fixtures

A validation fixture dataset is available at `tests/fixtures/validation_events.jsonl` for schema and session-quality checks.

## Testing

```bash
pytest -q
```
## Requirements:
- fastapi
- uvicorn
- opencv-python
- pandas
- numpy
- openpyxl
- pytest

## Reviewer Flow
- Clone repo → setup venv → pip install -r requirements.txt
- Run docker compose up → API starts
- Visit /health → JSON response
- Run detection pipeline → events generated
- Ingest events → /metrics, /funnel, /anomalies, /heatmap, /dashboard all work
- Run pytest → coverage passes

## Dashboard
The live dashboard is available at:
http://localhost:8000/dashboard


