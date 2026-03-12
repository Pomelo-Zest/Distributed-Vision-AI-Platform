from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


FRAME_EMITTED = Counter(
    "vision_frames_emitted_total",
    "Frames emitted by stream gateway",
    ["camera_id"],
)
FRAME_DROPPED = Counter(
    "vision_frames_dropped_total",
    "Frames dropped before inference",
    ["camera_id", "reason"],
)
QUEUE_DEPTH = Gauge(
    "vision_queue_depth",
    "Queue depth for internal services",
    ["queue_name"],
)
INFERENCE_LATENCY = Histogram(
    "vision_inference_latency_seconds",
    "Inference latency from frame capture to result generation",
    buckets=(0.01, 0.03, 0.05, 0.1, 0.3, 0.5, 1, 2, 5),
)
EVENTS_EMITTED = Counter(
    "vision_events_emitted_total",
    "Product-level events emitted by the event engine",
    ["rule_type", "camera_id"],
)
CAMERA_STATUS = Gauge(
    "vision_camera_status",
    "Camera online status: 1 online, 0 offline",
    ["camera_id"],
)
RECONNECT_TOTAL = Counter(
    "vision_camera_reconnect_total",
    "Reconnect attempts per camera",
    ["camera_id"],
)

