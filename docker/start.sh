#!/bin/sh
# Bind the port the host injects (Render sets PORT; Docker Compose defaults 8080).
set -eu
PORT="${PORT:-8080}"
exec uvicorn main:app --host 0.0.0.0 --port "$PORT" --proxy-headers
