from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from libs.common.config import settings
from libs.common.db import Camera, EventRecord, SystemMetric, db_session, init_db
from libs.common.geometry import crossed_line, point_in_polygon
from libs.common.logging import configure_logging
from libs.common.metrics import EVENTS_EMITTED, QUEUE_DEPTH
from libs.common.redis_client import get_redis_client
from libs.schemas.messages import Detection, InferenceEnvelope

logger = configure_logging("event-engine")
app = FastAPI(title="Vision AI Event Engine", version="0.1.0")
worker_task: asyncio.Task | None = None


@dataclass(slots=True)
class TrackContext:
    last_centroid: tuple[float, float] | None = None
    zone_inside: bool = False
    loitering_started_at: datetime | None = None
    emitted_loitering: bool = False
    last_frame_id: int = 0


track_state: dict[str, TrackContext] = {}


def state_key(camera_id: str, track_id: str) -> str:
    return f"{camera_id}:{track_id}"


def write_snapshot(camera_id: str, event_id: str, detection: Detection, payload: dict) -> str:
    directory = Path(settings.snapshot_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{camera_id}_{event_id}.json"
    path.write_text(
        json.dumps(
            {
                "camera_id": camera_id,
                "detection": detection.model_dump(),
                "payload": payload,
            },
            indent=2,
        )
    )
    return str(path)


def emit_event(camera_id: str, rule_type: str, frame_id: int, detection: Detection, payload: dict) -> None:
    event_id = str(uuid4())
    snapshot_path = write_snapshot(camera_id, event_id, detection, payload)
    with db_session() as session:
        session.add(
            EventRecord(
                id=event_id,
                camera_id=camera_id,
                rule_type=rule_type,
                track_id=detection.track_id,
                frame_id=frame_id,
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
                labels_json={"camera_id": camera_id, "rule_type": rule_type},
            )
        )
    EVENTS_EMITTED.labels(rule_type=rule_type, camera_id=camera_id).inc()


def evaluate_detection(camera: Camera, frame: InferenceEnvelope, detection: Detection) -> None:
    metadata = camera.metadata_json or {}
    zone = [tuple(point) for point in metadata.get("zone", [])]
    line = [tuple(point) for point in metadata.get("line", [])]
    loitering_zone = [tuple(point) for point in metadata.get("loitering_zone", [])]
    key = state_key(frame.camera_id, detection.track_id)
    ctx = track_state.setdefault(key, TrackContext())
    centroid = tuple(detection.centroid)

    if zone:
        inside_zone = point_in_polygon(centroid, zone)
        if inside_zone and not ctx.zone_inside:
            emit_event(
                frame.camera_id,
                "zone_entry",
                frame.frame_id,
                detection,
                {"centroid": detection.centroid, "zone": zone},
            )
        ctx.zone_inside = inside_zone

    if line and ctx.last_centroid and crossed_line(ctx.last_centroid, centroid, line):
        emit_event(
            frame.camera_id,
            "line_crossing",
            frame.frame_id,
            detection,
            {"from": list(ctx.last_centroid), "to": detection.centroid, "line": line},
        )

    if loitering_zone:
        inside_loitering = point_in_polygon(centroid, loitering_zone)
        if inside_loitering and ctx.loitering_started_at is None:
            ctx.loitering_started_at = frame.inference_at
        if not inside_loitering:
            ctx.loitering_started_at = None
            ctx.emitted_loitering = False
        if (
            inside_loitering
            and ctx.loitering_started_at is not None
            and not ctx.emitted_loitering
            and (frame.inference_at - ctx.loitering_started_at).total_seconds() >= settings.loitering_seconds
        ):
            emit_event(
                frame.camera_id,
                "loitering",
                frame.frame_id,
                detection,
                {"duration_seconds": settings.loitering_seconds, "zone": loitering_zone},
            )
            ctx.emitted_loitering = True

    ctx.last_centroid = centroid
    ctx.last_frame_id = frame.frame_id


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
        with db_session() as session:
            camera = session.get(Camera, frame.camera_id)
        if camera is None:
            continue
        for detection in frame.detections:
            evaluate_detection(camera, frame, detection)


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

