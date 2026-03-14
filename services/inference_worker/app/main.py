from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from libs.common.config import settings
from libs.common.db import Camera, DetectionLog, SystemMetric, db_session, init_db
from libs.common.logging import configure_logging
from libs.common.metrics import INFERENCE_LATENCY, QUEUE_DEPTH
from libs.common.redis_client import get_redis_client
from libs.common.visualization import write_camera_preview
from libs.schemas.messages import FrameEnvelope, InferenceEnvelope
from libs.tracking.mock_tracker import MockTracker

logger = configure_logging("inference-worker")
app = FastAPI(title="Vision AI Inference Worker", version="0.1.0")
worker_task: asyncio.Task | None = None
tracker = MockTracker()


async def consume_frames() -> None:
    redis = get_redis_client()
    while True:
        item = await redis.blpop(settings.frame_queue_name, timeout=1)
        if item is None:
            await asyncio.sleep(0.1)
            continue
        _, payload = item
        depth = await redis.llen(settings.frame_queue_name)
        QUEUE_DEPTH.labels(queue_name=settings.frame_queue_name).set(depth)
        frame = FrameEnvelope.model_validate_json(payload)
        inference_at = datetime.now(timezone.utc)
        detections = tracker.infer(frame.camera_id, frame.frame_id)
        result = InferenceEnvelope(
            camera_id=frame.camera_id,
            frame_id=frame.frame_id,
            captured_at=frame.captured_at,
            inference_at=inference_at,
            detections=detections,
            metadata={"frame_token": frame.frame_token, "source_uri": frame.source_uri},
        )
        with db_session() as session:
            camera = session.get(Camera, frame.camera_id)
            if camera is not None:
                camera.last_inference_at = inference_at
                write_camera_preview(
                    camera_id=frame.camera_id,
                    frame_id=frame.frame_id,
                    source_uri=frame.source_uri,
                    detections=[detection.model_dump() for detection in detections],
                    camera_metadata=camera.metadata_json,
                )
            for detection in detections:
                session.add(
                    DetectionLog(
                        camera_id=frame.camera_id,
                        frame_id=frame.frame_id,
                        track_id=detection.track_id,
                        class_name=detection.class_name,
                        confidence=detection.confidence,
                        bbox_json=detection.bbox,
                        centroid_x=detection.centroid[0],
                        centroid_y=detection.centroid[1],
                        captured_at=frame.captured_at,
                    )
                )
            session.add(
                SystemMetric(
                    service="inference-worker",
                    metric_name="detections_per_frame",
                    metric_value=float(len(detections)),
                    labels_json={"camera_id": frame.camera_id},
                )
            )
        INFERENCE_LATENCY.observe((inference_at - frame.captured_at).total_seconds())
        await redis.rpush(settings.track_queue_name, result.model_dump_json())
        QUEUE_DEPTH.labels(queue_name=settings.track_queue_name).set(await redis.llen(settings.track_queue_name))


@app.on_event("startup")
async def startup() -> None:
    global worker_task
    init_db()
    worker_task = asyncio.create_task(consume_frames())
    logger.info("inference worker started")


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
