# Local Demo Guide

This guide walks through the local command-line workflow for demoing and testing the Vision AI Platform from the repository root at `/Users/iuhyeong/Documents/vision-ai-platform`.

## Recommended Path

Use Docker Compose for the full demo. This is the least fragile path because Postgres, Redis, API, workers, Prometheus, and Grafana all come up together.

## 1. Prerequisites

You should have:

- `docker`
- `docker compose`
- `python3` 3.11+
- `pip3`

Optional but useful:

- `curl`
- `jq`

The default seed file in [config/cameras.seed.json](/Users/iuhyeong/Documents/vision-ai-platform/config/cameras.seed.json) is intentionally empty now. Add RTSP cameras from the dashboard or with `POST /cameras` before demoing live streams.

## 2. First-Time Setup

From the repo root:

```bash
cd /Users/iuhyeong/Documents/vision-ai-platform
cp .env.example .env
```

For Docker demoing, the default `.env.example` values are fine.

If you also want local Python commands outside Docker, install the package:

```bash
pip3 install -e .
```

## 3. Start the Full Stack

```bash
docker compose up --build
```

If you want it detached:

```bash
docker compose up --build -d
```

Useful follow-ups:

```bash
docker compose ps
docker compose logs -f backend-api
docker compose logs -f stream-gateway
docker compose logs -f inference-worker
docker compose logs -f event-engine
docker compose logs -f scheduler
```

Stop everything:

```bash
docker compose down
```

Stop and remove the Postgres volume too:

```bash
docker compose down -v
```

## 4. Main URLs

Once the stack is up:

- API docs: `http://localhost:8000/docs`
- Dashboard: `http://localhost:8000/dashboard`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

Grafana default login:

- user: `admin`
- pass: `admin`

## 5. Fast CLI Smoke Test

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8010/health
curl http://localhost:8020/health
curl http://localhost:8030/health
curl http://localhost:8040/health
```

List current cameras:

```bash
curl http://localhost:8000/cameras | jq
```

If you have not added cameras yet, this list may be empty.

Check metrics summary:

```bash
curl http://localhost:8000/metrics/summary | jq
```

Watch events arrive:

```bash
watch -n 2 "curl -s http://localhost:8000/events?limit=10 | jq"
```

If `watch` is unavailable:

```bash
while true; do
  clear
  curl -s http://localhost:8000/events?limit=10 | jq
  sleep 2
done
```

## 6. Demo the HLS Transport

Fetch a playlist directly:

```bash
curl http://localhost:8000/cameras/cam-lobby/hls/index.m3u8
```

You should see HLS playlist lines like:

```text
#EXTM3U
#EXT-X-VERSION
#EXTINF
```

Inspect the camera payload for stream URLs:

```bash
curl http://localhost:8000/cameras | jq '.[0]'
```

You should see fields like:

- `stream_url`
- `stream_protocol`
- `webrtc_url`

## 7. Demo the WebRTC Signaling Path

This is the server-side signaling endpoint the dashboard uses:

```bash
curl -X POST http://localhost:8000/cameras/cam-lobby/webrtc/offer \
  -H 'Content-Type: application/json' \
  -d '{"sdp":"dummy","type":"offer"}'
```

That exact dummy request should fail, but it proves the route exists.

A real CLI-level signaling smoke test from Python:

```bash
python3 -c "exec('''import asyncio
from aiortc import RTCPeerConnection
from libs.common.db import Camera
from libs.common.webrtc import WebRTCStreamManager

async def wait_ice(pc):
    if pc.iceGatheringState == \"complete\":
        return
    fut = asyncio.get_running_loop().create_future()
    @pc.on(\"icegatheringstatechange\")
    def on_state():
        if pc.iceGatheringState == \"complete\" and not fut.done():
            fut.set_result(None)
    await asyncio.wait_for(fut, timeout=5)

async def main():
    manager = WebRTCStreamManager()
    camera = Camera(id=\"cam-offer-test\", name=\"Offer Test\", source_uri=\"rtsp://your-host/stream\", target_fps=5, metadata_json={})
    client = RTCPeerConnection()
    client.addTransceiver(\"video\", direction=\"recvonly\")
    offer = await client.createOffer()
    await client.setLocalDescription(offer)
    await wait_ice(client)
    answer = await manager.create_answer(camera, client.localDescription.sdp, client.localDescription.type)
    print(answer[\"type\"])
    print(\"m=video\" in answer[\"sdp\"])
    await client.close()
    await manager.close_all()

asyncio.run(main())
''' )"
```

Expected output:

```text
answer
True
```

Important note:

- In this environment, WebRTC signaling is implemented and the dashboard can try it.
- Full peer media delivery may still depend on local ICE and network behavior.
- HLS is the reliable fallback for demos.

## 8. Inspect Detections and Events

Recent events:

```bash
curl "http://localhost:8000/events?limit=20" | jq
```

Single camera detail:

```bash
curl http://localhost:8000/cameras/<camera-id> | jq
```

That returns:

- recent tracks
- last frame time
- last inference time
- source URI
- preview and stream endpoints

## 9. Metrics and Monitoring CLI

Prometheus raw metrics:

```bash
curl http://localhost:8000/metrics | head
curl http://localhost:8010/metrics | head
curl http://localhost:8020/metrics | head
curl http://localhost:8030/metrics | head
curl http://localhost:8040/metrics | head
```

Quick queue depth view:

```bash
curl -s http://localhost:8000/metrics/summary | jq '.queue_depth'
```

## 10. Reset the Demo State

If you want a clean rerun:

```bash
docker compose down -v
rm -rf vision_snapshots vision_frames vision_hls
docker compose up --build
```

If you want to apply the current seed file without restarting everything:

```bash
curl http://localhost:8040/seed | jq
```

## 11. Local Python-Only Testing

If you want to test code without full Compose, keep in mind:

- the default `.env.example` points `DATABASE_URL` to `postgres`
- the default `.env.example` points `REDIS_URL` to `redis`

Those hostnames only work inside Docker.

For local host-based runs, export overrides first:

```bash
export DATABASE_URL='postgresql+psycopg://vision:vision@localhost:5432/vision_ai'
export REDIS_URL='redis://localhost:6379/0'
```

Then you can run services individually, for example:

```bash
uvicorn services.backend_api.app.main:app --host 0.0.0.0 --port 8000
uvicorn services.scheduler.app.main:app --host 0.0.0.0 --port 8040
uvicorn services.stream_gateway.app.main:app --host 0.0.0.0 --port 8010
uvicorn services.inference_worker.app.main:app --host 0.0.0.0 --port 8020
uvicorn services.event_engine.app.main:app --host 0.0.0.0 --port 8030
```

For a demo, Docker is still the better path.

## 12. Best Demo Flow

If you are presenting live, this sequence is steady and easy:

1. Start the stack:

```bash
docker compose up --build
```

2. In another terminal, confirm cameras:

```bash
curl -s http://localhost:8000/cameras | jq '.[].id'
```

3. Confirm events are flowing:

```bash
watch -n 2 "curl -s http://localhost:8000/events?limit=5 | jq"
```

4. Open:

- `http://localhost:8000/dashboard`
- `http://localhost:8000/docs`

5. In the dashboard:

- use `WebRTC` first
- if the browser or session does not establish WebRTC cleanly, switch to `HLS`

## 13. Common Issues

If `docker compose up` fails:

- make sure Docker Desktop is running
- make sure ports `3000`, `5432`, `6379`, `8000`, `8010`, `8020`, `8030`, `8040`, `9090` are free

If no events appear:

- check worker logs:

```bash
docker compose logs -f stream-gateway
docker compose logs -f inference-worker
docker compose logs -f event-engine
```

If dashboard video is blank:

- try the `HLS` button
- verify playlist directly:

```bash
curl http://localhost:8000/cameras/cam-lobby/hls/index.m3u8
```

If local Python commands fail on imports:

```bash
pip3 install -e .
```
