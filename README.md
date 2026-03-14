# Vision AI Platform

distributed Vision AI MVP with clear service boundaries:

- `stream-gateway` generates per-camera frames and health telemetry
- `inference-worker` performs mocked detection and tracking on queued frames
- `event-engine` converts tracks into product events
- `backend-api` exposes cameras, events, and metrics summary
- `scheduler` seeds camera configuration and keeps the baseline environment ready
- `dashboard` provides a lightweight demo UI over the API

This repository starts with a working mocked pipeline so the full system can run immediately, then leaves explicit extension points for real video ingest, YOLO, and ByteTrack.

## Quick Start

1. Copy `.env.example` to `.env`.
2. Start the stack:

```bash
docker compose up --build
```

3. Open:

- API docs: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8000/dashboard`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Repository Layout

```text
services/
  backend-api/
  event-engine/
  inference-worker/
  scheduler/
  stream-gateway/
libs/
  common/
  metrics/
  schemas/
  tracking/
deployments/
  docker-compose/
  grafana/
  prometheus/
dashboard/
scripts/
docs/
config/
```

## What Works Now

- multi-camera mocked ingest with per-camera FPS control
- Redis-backed frame and track queues
- deterministic tracking simulation for repeatable demos
- zone entry, line crossing, and loitering event generation
- Postgres-backed camera and event persistence
- FastAPI endpoints for health, cameras, events, and metrics summary
- generated SVG camera previews served through the API and dashboard
- generated SVG event snapshots instead of metadata-only snapshot stubs
- Prometheus scrape targets and a starter Grafana datasource

## Next Upgrades

- replace mocked frame generation with OpenCV, FFmpeg, or GStreamer ingest
- swap `libs/tracking/mock_tracker.py` for YOLO26 + ByteTrack integration
- connect the dashboard to HLS/WebRTC transport instead of generated previews
