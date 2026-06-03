from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import logging
import time
import uuid

from . import analytics
from .db import init_db
from .exceptions import ServiceUnavailable
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
    request.state.store_id = None
    request.state.event_count = 0
    start = time.time()
    response = await call_next(request)
    latency_ms = int((time.time() - start) * 1000)
    logger.info(
        {
            'trace_id': trace_id,
            'path': request.url.path,
            'method': request.method,
            'store_id': getattr(request.state, 'store_id', None),
            'event_count': getattr(request.state, 'event_count', 0),
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
    request.state.event_count = len(items)
    if items and isinstance(items, list) and isinstance(items[0], dict):
        request.state.store_id = items[0].get('store_id')

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
def get_store_metrics(store_id: str, request: Request):
    request.state.store_id = store_id
    return analytics.build_metrics(store_id)


@app.get('/stores/{store_id}/funnel')
def get_store_funnel(store_id: str, request: Request):
    request.state.store_id = store_id
    return analytics.build_funnel(store_id)


@app.get('/stores/{store_id}/heatmap')
def get_store_heatmap(store_id: str, request: Request):
    request.state.store_id = store_id
    return analytics.build_heatmap(store_id)


@app.get('/stores/{store_id}/anomalies')
def get_store_anomalies(store_id: str, request: Request):
    request.state.store_id = store_id
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
        <p>Live dashboard for store <strong>ST1008</strong>. Use the buttons below to fetch metrics and anomalies from the local API.</p>
        <div class="card">
          <h2>Live API endpoints</h2>
          <p>
            <a href="/dashboard" target="_blank">http://localhost:8000/dashboard</a><br>
            <a href="/health" target="_blank">http://localhost:8000/health</a><br>
            <a href="/stores/ST1008/metrics" target="_blank">http://localhost:8000/stores/ST1008/metrics</a><br>
            <a href="/stores/ST1008/funnel" target="_blank">http://localhost:8000/stores/ST1008/funnel</a><br>
            <a href="/stores/ST1008/heatmap" target="_blank">http://localhost:8000/stores/ST1008/heatmap</a><br>
            <a href="/stores/ST1008/anomalies" target="_blank">http://localhost:8000/stores/ST1008/anomalies</a>
          </p>
        </div>
        <div class="card">
          <button onclick="loadMetrics()">Load Metrics</button>
          <pre id="metrics">Ready</pre>
        </div>
        <div class="card">
          <button onclick="loadFunnel()">Load Funnel</button>
          <pre id="funnel">Ready</pre>
        </div>
        <div class="card">
          <button onclick="loadHeatmap()">Load Heatmap</button>
          <pre id="heatmap">Ready</pre>
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
          const baseUrl = window.location.origin;
          const storeId = 'ST1008';

          async function fetchJson(path) {
            const res = await fetch(path);
            return res.json();
          }
          async function loadMetrics() {
            document.getElementById('metrics').textContent = 'Loading...';
            const data = await fetchJson(`${baseUrl}/stores/${storeId}/metrics`);
            document.getElementById('metrics').textContent = JSON.stringify(data, null, 2);
          }
          async function loadFunnel() {
            document.getElementById('funnel').textContent = 'Loading...';
            const data = await fetchJson(`${baseUrl}/stores/${storeId}/funnel`);
            document.getElementById('funnel').textContent = JSON.stringify(data, null, 2);
          }
          async function loadHeatmap() {
            document.getElementById('heatmap').textContent = 'Loading...';
            const data = await fetchJson(`${baseUrl}/stores/${storeId}/heatmap`);
            document.getElementById('heatmap').textContent = JSON.stringify(data, null, 2);
          }
          async function loadAnomalies() {
            document.getElementById('anomalies').textContent = 'Loading...';
            const data = await fetchJson(`${baseUrl}/stores/${storeId}/anomalies`);
            document.getElementById('anomalies').textContent = JSON.stringify(data, null, 2);
          }
          async function loadHealth() {
            document.getElementById('health').textContent = 'Loading...';
            const data = await fetchJson(`${baseUrl}/health`);
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
    content = {'detail': exc.detail}
    if exc.status_code == 503:
        content['error'] = 'SERVICE_UNAVAILABLE'
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )
