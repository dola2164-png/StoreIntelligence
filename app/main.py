from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import logging
import time
import uuid

from . import analytics
from .db import init_db
from .schemas import EventIn, EventIngestResult, ErrorResponse
from .storage import insert_events, fetch_events, get_last_event_timestamp

app = FastAPI(title='Store Intelligence API')
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

logger = logging.getLogger('store_intelligence')
logging.basicConfig(level=logging.INFO, format='%(message)s')


@app.middleware('http')
async def add_trace_id(request: Request, call_next):
    trace_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    request.state.trace_id = trace_id
    start = time.time()
    response = await call_next(request)
    latency_ms = int((time.time() - start) * 1000)
    logger.info(
        {
            'trace_id': trace_id,
            'path': request.url.path,
            'method': request.method,
            'status_code': response.status_code,
            'latency_ms': latency_ms,
        }
    )
    response.headers['X-Request-ID'] = trace_id
    return response


@app.post('/events/ingest', response_model=EventIngestResult)
async def ingest_events(request: Request):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail='Request body is empty')
    try:
        payload = await request.json()
    except Exception:
        try:
            payload = {
                'events': [json.loads(line) for line in body.decode('utf-8').splitlines() if line.strip()]
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f'Invalid JSON or JSONL payload: {exc}')
    items = []
    if isinstance(payload, dict) and isinstance(payload.get('events'), list):
        items = payload['events']
    elif isinstance(payload, list):
        items = payload
    else:
        raise HTTPException(status_code=400, detail='events must be a list or JSONL lines')

    accepted = 0
    duplicates = 0
    rejected = 0
    errors = {}
    valid_events = []
    for idx, raw_event in enumerate(items):
        if not isinstance(raw_event, dict):
            rejected += 1
            errors[idx] = 'Each event must be a JSON object'
            continue
        try:
            event = EventIn(**raw_event)
            valid_events.append(event.model_dump())
        except Exception as exc:
            rejected += 1
            errors[idx] = str(exc)
    if valid_events:
        result = insert_events(valid_events)
        accepted = result['accepted']
        duplicates = result['duplicates']
    return {
        'accepted': accepted,
        'duplicates': duplicates,
        'rejected': rejected,
        'errors': errors,
    }


@app.get('/stores/{store_id}/metrics')
def get_store_metrics(store_id: str):
    return analytics.build_metrics(store_id)


@app.get('/stores/{store_id}/funnel')
def get_store_funnel(store_id: str):
    return analytics.build_funnel(store_id)


@app.get('/stores/{store_id}/heatmap')
def get_store_heatmap(store_id: str):
    return analytics.build_heatmap(store_id)


@app.get('/stores/{store_id}/anomalies')
def get_store_anomalies(store_id: str):
    return analytics.build_anomalies(store_id)


@app.get('/dashboard', response_class=HTMLResponse)
def get_dashboard():
    return """
    <html>
      <head>
        <title>Store Intelligence Dashboard</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 24px; }
          .card { border: 1px solid #ccc; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
          pre { background: #f5f5f5; padding: 12px; overflow-x: auto; }
          h1, h2 { margin-bottom: 8px; }
        </style>
      </head>
      <body>
        <h1>Store Intelligence Dashboard</h1>
        <p>Use the controls below to fetch live metrics and anomaly data for STORE_BLR_002.</p>
        <div class="card">
          <button onclick="loadMetrics()">Load Metrics</button>
          <pre id="metrics">Ready</pre>
        </div>
        <div class="card">
          <button onclick="loadFunnel()">Load Funnel</button>
          <pre id="funnel">Ready</pre>
        </div>
        <div class="card">
          <button onclick="loadAnomalies()">Load Anomalies</button>
          <pre id="anomalies">Ready</pre>
        </div>
        <div class="card">
          <button onclick="loadHealth()">Load Health</button>
          <pre id="health">Ready</pre>
        </div>
        <script>
          async function fetchJson(path) {
            const res = await fetch(path);
            return res.json();
          }
          async function loadMetrics() {
            document.getElementById('metrics').textContent = 'Loading...';
            const data = await fetchJson('/stores/STORE_BLR_002/metrics');
            document.getElementById('metrics').textContent = JSON.stringify(data, null, 2);
          }
          async function loadFunnel() {
            document.getElementById('funnel').textContent = 'Loading...';
            const data = await fetchJson('/stores/STORE_BLR_002/funnel');
            document.getElementById('funnel').textContent = JSON.stringify(data, null, 2);
          }
          async function loadAnomalies() {
            document.getElementById('anomalies').textContent = 'Loading...';
            const data = await fetchJson('/stores/STORE_BLR_002/anomalies');
            document.getElementById('anomalies').textContent = JSON.stringify(data, null, 2);
          }
          async function loadHealth() {
            document.getElementById('health').textContent = 'Loading...';
            const data = await fetchJson('/health');
            document.getElementById('health').textContent = JSON.stringify(data, null, 2);
          }
        </script>
      </body>
    </html>
    """


@app.get('/health')
def get_health():
    return analytics.build_health()


@app.exception_handler(HTTPException)
def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={'detail': exc.detail},
    )
