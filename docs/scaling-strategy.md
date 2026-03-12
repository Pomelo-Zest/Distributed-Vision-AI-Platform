# Scaling Strategy

## Immediate Scaling Levers

- run more `inference-worker` replicas because inference is queue-backed
- split frame queues per camera group if one global queue becomes noisy
- lower `target_fps` on non-critical cameras under load
- switch from simple Redis lists to Redis Streams or Kafka when consumer groups matter

## 20-100 Camera Story

- synthetic cameras already exist through `scripts/load-test/scale_cameras.py`
- use 8, 16, 32, and 64 camera seed files to observe queue depth and processing lag
- record the saturation point where frame backlog grows faster than inference drains it
- document degraded mode behavior such as stale-frame dropping or reduced FPS

## Real-World Changes Needed

- GPU-bound model execution with batch scheduling
- explicit backpressure policy for image payloads
- camera affinity or shard allocation across multiple gateway instances
- object storage for snapshots and archival data

