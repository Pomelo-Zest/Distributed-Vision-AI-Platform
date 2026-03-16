# Vision AI Platform

distributed Vision AI MVP with clear service boundaries:

- `stream-gateway` captures per-camera frames and health telemetry
- `inference-worker` performs YOLO26n detection with ByteTrack tracking on queued frames
- `event-engine` converts tracks into product events
- `backend-api` exposes cameras, events, and metrics summary
- `scheduler` seeds camera configuration and keeps the baseline environment ready
- `dashboard` provides a lightweight demo UI over the API

This repository starts with a working end-to-end pipeline using real video ingest and model-backed tracking, then leaves explicit extension points for production transports and higher-accuracy models.

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

- multi-camera ingest with per-camera FPS control
- OpenCV-based ingest for RTSP, file, HTTP, and GStreamer/FFmpeg-backed sources
- YOLO26n detection with ByteTrack tracking for people and vehicles
- Redis-backed frame and track queues
- zone entry, line crossing, and loitering event generation
- Postgres-backed camera and event persistence
- FastAPI endpoints for health, cameras, events, and metrics summary
- generated SVG camera previews served through the API and dashboard
- generated SVG event snapshots instead of metadata-only snapshot stubs
- Prometheus scrape targets and a starter Grafana datasource

## Next Upgrades

- connect the dashboard to HLS/WebRTC transport instead of generated previews

## Stream Sources

- `source_uri` now supports direct OpenCV ingest from `rtsp://`, `http://`, `https://`, local file paths, and `file://...` URIs.
- Set `STREAM_BACKEND=ffmpeg`, `STREAM_BACKEND=gstreamer`, or `STREAM_BACKEND=opencv` to choose the OpenCV capture backend globally.
- Override a single camera backend with `metadata.ingest_backend` in `config/cameras.seed.json`.
- The seeded cameras now use the person and vehicle test clips under `assets/human_streams/` and `assets/traffic_streams/`.
- The default YOLO weight path is `models/yolo26n.pt`.
- Existing `mock://...` URIs still work as a compatibility path while you migrate seeded cameras to real streams.
