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
- HLS and WebRTC camera streams served through the API and attached in the dashboard
- desktop-first dashboard layout with interactive canvas overlays for zones and line rules
- generated SVG event snapshots instead of metadata-only snapshot stubs
- Prometheus scrape targets and a starter Grafana datasource
- bounded frame queueing and stale-frame dropping to keep live detection responsive under RTSP load

## Next Upgrades

- add TURN/STUN configuration and auth hardening for production WebRTC deployments

## Stream Sources

- `source_uri` now supports direct OpenCV ingest from `rtsp://`, `http://`, `https://`, local file paths, and `file://...` URIs.
- Set `STREAM_BACKEND=ffmpeg`, `STREAM_BACKEND=gstreamer`, or `STREAM_BACKEND=opencv` to choose the OpenCV capture backend globally.
- Override a single camera backend with `metadata.ingest_backend` in `config/cameras.seed.json`.
- The default seed file no longer adds local demo videos. Add RTSP cameras from the dashboard or `POST /cameras`.
- Persist editable rule geometry in `config/camera_configs.json`.
- The default YOLO weight path is `models/yolo26n.pt`.
- Existing `mock://...` URIs still work as a compatibility path while you migrate seeded cameras to real streams.

## Runtime Stability

- `FRAME_QUEUE_MAX_DEPTH` bounds queued frames so the system drops old work instead of accumulating unbounded latency.
- `INFERENCE_MAX_FRAME_AGE_SECONDS` drops stale frames before inference so detections stay near-real-time.
- The scheduler prunes previously seeded local-file cameras that are no longer present in `config/cameras.seed.json`, while preserving RTSP cameras you add through the web UI.

## Docker Notes

- A repo-level [`.dockerignore`](/Users/iuhyeong/Documents/vision-ai-platform/.dockerignore) now excludes runtime artifacts such as `vision_frames/`, `vision_hls/`, and `.git` from the build context.
- The image build no longer copies the whole repository after install, which keeps rebuilds smaller and reduces local Docker storage pressure.

## Dashboard Transport

- The dashboard now supports WebRTC for lower-latency previews and HLS as the fallback transport.
- The dashboard is optimized for desktop operation, with a fixed control sidebar and a multi-player workspace grid.
- Draw `zone`, `loitering_zone`, and `line` geometry directly on the HLS player overlay, then save it through `PUT /cameras/{camera_id}/geometry`.
- WebRTC offers are posted to `/cameras/{camera_id}/webrtc/offer`.
- HLS playlists remain available at `/cameras/{camera_id}/hls/index.m3u8`.
- Server-side HLS packaging is produced with the bundled `imageio-ffmpeg` binary, so no system `ffmpeg` install is required.
