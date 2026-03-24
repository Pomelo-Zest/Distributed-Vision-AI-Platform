from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from libs.common.camera_config import camera_geometry
from libs.common.db import Camera, EventRecord, SystemMetric, db_session, init_db, update_camera_runtime
from libs.common.event_rules import TrackContext, evaluate_track_rules
from libs.common.event_settings import normalize_event_settings
from libs.common.logging import configure_logging
from libs.common.metrics import EVENTS_EMITTED, QUEUE_DEPTH
from libs.common.redis_client import get_redis_client
from libs.common.visualization import write_event_snapshot
from libs.schemas.messages import Detection, InferenceEnvelope

logger = configure_logging("event-engine")
app = FastAPI(title="Vision AI Event Engine", version="0.1.0")
worker_task: asyncio.Task | None = None


track_state: dict[str, TrackContext] = {}


def state_key(camera_id: str, track_id: str) -> str:
    return f"{camera_id}:{track_id}"


def emit_event(
    camera: Camera,
    frame: InferenceEnvelope,
    rule_type: str,
    detection: Detection,
    payload: dict,
) -> None:
    event_id = str(uuid4())
    camera_metadata = dict(camera.metadata_json or {})
    camera_metadata.update(camera_geometry(camera))
    snapshot_path = write_event_snapshot(
        camera_id=frame.camera_id,
        event_id=event_id,
        frame_id=frame.frame_id,
        source_uri=frame.metadata.get("source_uri", camera.source_uri),
        frame_path=frame.metadata.get("frame_path"),
        detections=[detection.model_dump()],
        camera_metadata=camera_metadata,
        event_type=rule_type,
        event_payload=payload,
        highlight_track_id=detection.track_id,
        created_at=frame.inference_at,
    )
    with db_session() as session:
        camera_row = session.get(Camera, frame.camera_id)
        if camera_row is not None:
            update_camera_runtime(
                camera_row,
                last_event={
                "id": event_id,
                "rule_type": rule_type,
                "track_id": detection.track_id,
                "class_name": detection.class_name,
                "category": detection.category,
                "confidence": detection.confidence,
                "frame_id": frame.frame_id,
                "created_at": frame.inference_at.isoformat(),
            },
            )
        session.add(
            EventRecord(
                id=event_id,
                camera_id=frame.camera_id,
                rule_type=rule_type,
                track_id=detection.track_id,
                frame_id=frame.frame_id,
                severity="info",
                snapshot_path=snapshot_path,
                payload_json=payload,
            )
        )
        session.add(
            SystemMetric(
                service="event-engine",
                metric_name="events_total",
                metric_value=1,
                labels_json={"camera_id": frame.camera_id, "rule_type": rule_type},
            )
        )
    EVENTS_EMITTED.labels(rule_type=rule_type, camera_id=frame.camera_id).inc()


def evaluate_detection(camera: Camera, frame: InferenceEnvelope, detection: Detection) -> None:
    metadata = dict(camera.metadata_json or {})
    metadata.update(camera_geometry(camera))
    geometry = {
        "zone": [tuple(point) for point in metadata.get("zone", [])],
        "line": [tuple(point) for point in metadata.get("line", [])],
        "loitering_zone": [tuple(point) for point in metadata.get("loitering_zone", [])],
    }
    event_settings = normalize_event_settings(metadata)
    key = state_key(frame.camera_id, detection.track_id)
    ctx = track_state.setdefault(key, TrackContext())
    for rule_type, payload in evaluate_track_rules(ctx, frame, detection, geometry, event_settings):
        emit_event(camera, frame, rule_type, detection, payload)


async def consume_tracks() -> None:
    redis = get_redis_client()
    while True:
        item = await redis.blpop(settings.track_queue_name, timeout=1)
        if item is None:
            await asyncio.sleep(0.1)
            continue
        _, payload = item
        QUEUE_DEPTH.labels(queue_name=settings.track_queue_name).set(await redis.llen(settings.track_queue_name))
        frame = InferenceEnvelope.model_validate_json(payload)
        try:
            with db_session() as session:
                camera = session.get(Camera, frame.camera_id)
            if camera is None:
                continue
            for detection in frame.detections:
                evaluate_detection(camera, frame, detection)
        finally:
            frame_path = frame.metadata.get("frame_path")
            if frame_path:
                Path(frame_path).unlink(missing_ok=True)


@app.on_event("startup")
async def startup() -> None:
    global worker_task
    init_db()
    worker_task = asyncio.create_task(consume_tracks())
    logger.info("event engine started")


@app.on_event("shutdown")
async def shutdown() -> None:
    if worker_task is not None:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
