from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

from libs.common.config import settings
from libs.common.db import Camera, SystemMetric, db_session, init_db
from libs.common.logging import configure_logging
from libs.common.metrics import CAMERA_STATUS, FRAME_EMITTED, QUEUE_DEPTH
from libs.common.redis_client import get_redis_client
from libs.schemas.messages import FrameEnvelope

logger = configure_logging("stream-gateway")
app = FastAPI(title="Vision AI Stream Gateway", version="0.1.0")
camera_tasks: dict[str, asyncio.Task] = {}
refresh_task: asyncio.Task | None = None


async def publish_frames(camera_id: str) -> None:
    redis = get_redis_client()
    frame_id = 0
    try:
        while True:
            with db_session() as session:
                camera = session.get(Camera, camera_id)
                if camera is None:
                    return
                camera.status = "online"
                camera.last_frame_at = datetime.now(timezone.utc)
                session.add(
                    SystemMetric(
                        service="stream-gateway",
                        metric_name="camera_fps_target",
                        metric_value=float(camera.target_fps),
                        labels_json={"camera_id": camera.id},
                    )
                )
                fps = max(camera.target_fps, 1)

            frame_id += 1
            envelope = FrameEnvelope(
                camera_id=camera_id,
                frame_id=frame_id,
                captured_at=datetime.now(timezone.utc),
                source_uri=camera.source_uri,
                frame_token=f"{camera_id}:{frame_id}",
            )
            await redis.rpush(settings.frame_queue_name, envelope.model_dump_json())
            depth = await redis.llen(settings.frame_queue_name)
            QUEUE_DEPTH.labels(queue_name=settings.frame_queue_name).set(depth)
            FRAME_EMITTED.labels(camera_id=camera_id).inc()
            CAMERA_STATUS.labels(camera_id=camera_id).set(1)
            await asyncio.sleep(1 / fps)
    except asyncio.CancelledError:
        raise
    finally:
        with db_session() as session:
            camera = session.get(Camera, camera_id)
            if camera is not None:
                camera.status = "offline"
            session.add(
                SystemMetric(
                    service="stream-gateway",
                    metric_name="camera_shutdown",
                    metric_value=1,
                    labels_json={"camera_id": camera_id},
                )
            )
        CAMERA_STATUS.labels(camera_id=camera_id).set(0)
        await redis.close()


async def reconcile_cameras() -> None:
    while True:
        with db_session() as session:
            cameras = session.scalars(select(Camera)).all()
        camera_ids = {camera.id for camera in cameras}
        for camera in cameras:
            if camera.id not in camera_tasks or camera_tasks[camera.id].done():
                camera_tasks[camera.id] = asyncio.create_task(publish_frames(camera.id))
        for camera_id, task in list(camera_tasks.items()):
            if camera_id not in camera_ids:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                camera_tasks.pop(camera_id, None)
        await asyncio.sleep(5)


@app.on_event("startup")
async def startup() -> None:
    global refresh_task
    init_db()
    refresh_task = asyncio.create_task(reconcile_cameras())
    logger.info("stream gateway started")


@app.on_event("shutdown")
async def shutdown() -> None:
    global refresh_task
    if refresh_task is not None:
        refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await refresh_task
    for task in camera_tasks.values():
        task.cancel()
    for task in camera_tasks.values():
        with suppress(asyncio.CancelledError):
            await task


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

