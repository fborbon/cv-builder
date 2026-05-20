#!/usr/bin/env bash
cd "$(dirname "$0")"
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8080 --reload
