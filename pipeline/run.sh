#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python detect.py

if [ -f ../data/events.jsonl ]; then
  echo "Detection complete. events.jsonl is ready in ../data"
  echo "Ingest the events with:"
  echo "  curl -X POST http://localhost:8000/events/ingest -H 'Content-Type: application/json' --data-binary @../data/events.jsonl"
fi
