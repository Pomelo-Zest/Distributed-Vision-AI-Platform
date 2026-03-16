from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - depends on installed runtime extras
    cv2 = None
    np = None

from libs.common.config import settings
from libs.common.db import Camera, SystemMetric, db_session, init_db
from libs.common.logging import configure_logging
from libs.common.metrics import CAMERA_STATUS, FRAME_EMITTED, QUEUE_DEPTH
from libs.common.redis_client import get_redis_client
from libs.schemas.messages import FrameEnvelope

logger = configure_logging("stream-gateway")
app = FastAPI(title="Vision AI Stream Gateway", version="0.2.0")
camera_tasks: dict[str, asyncio.Task] = {}
refresh_task: asyncio.Task | None = None

BACKEND_MAP = {
    "opencv": 0,
    "ffmpeg": 1900,
    "gstreamer": 1800,
}


def ensure_video_runtime() -> None:
    if cv2 is None or np is None:
        raise RuntimeError(
            "OpenCV video ingest is not available. Install dependencies from pyproject.toml and rebuild the service."
        )


def resolve_backend(camera: Camera) -> tuple[str, int]:
    ensure_video_runtime()
    backend_name = (camera.metadata_json or {}).get("ingest_backend", settings.stream_backend).lower()
    return backend_name, BACKEND_MAP.get(backend_name, BACKEND_MAP["opencv"])


def resolve_source_uri(source_uri: str) -> str:
    if source_uri.startswith("file://"):
        return urlparse(source_uri).path
    return source_uri


def open_capture(camera: Camera) -> cv2.VideoCapture:
    ensure_video_runtime()
    backend_name, backend = resolve_backend(camera)
    source_uri = resolve_source_uri(camera.source_uri)
    capture = cv2.VideoCapture(source_uri, backend)
    logger.info("opened capture", extra={"camera_id": camera.id, "backend": backend_name, "source_uri": camera.source_uri})
    return capture


def frame_store_path(camera_id: str, frame_id: int) -> Path:
    root = Path(settings.frame_store_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    directory = root / camera_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{frame_id:08d}.jpg"


def write_frame_file(camera_id: str, frame_id: int, frame: np.ndarray) -> str:
    ensure_video_runtime()
    path = frame_store_path(camera_id, frame_id)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"failed to persist frame to {path}")
    return str(path)


def build_mock_frame(camera: Camera, frame_id: int) -> np.ndarray:
    ensure_video_runtime()
    # Compatibility path while seeded cameras still use mock:// URIs.
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    gradient = np.linspace(40, 160, frame.shape[1], dtype=np.uint8)
    frame[:, :, 0] = gradient
    frame[:, :, 1] = gradient[::-1]
    frame[:, :, 2] = 90
    cv2.putText(frame, camera.name, (54, 96), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(
        frame,
        f"{camera.source_uri}  frame={frame_id}",
        (54, 146),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (210, 230, 255),
        2,
        cv2.LINE_AA,
    )
    metadata = camera.metadata_json or {}
    for polygon_key, color in (("zone", (80, 235, 155)), ("loitering_zone", (255, 196, 61))):
        points = metadata.get(polygon_key, [])
        if len(points) >= 3:
            pts = np.array(
                [[int(x * frame.shape[1]), int(y * frame.shape[0])] for x, y in points],
                dtype=np.int32,
            )
            cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=3)
    line = metadata.get("line", [])
    if len(line) == 2:
        start = (int(line[0][0] * frame.shape[1]), int(line[0][1] * frame.shape[0]))
        end = (int(line[1][0] * frame.shape[1]), int(line[1][1] * frame.shape[0]))
        cv2.line(frame, start, end, (244, 114, 182), 4, cv2.LINE_AA)
    return frame


async def next_frame(camera: Camera, capture: cv2.VideoCapture | None, frame_id: int) -> tuple[bool, np.ndarray | None]:
    if camera.source_uri.startswith("mock://"):
        await asyncio.sleep(0)
        return True, build_mock_frame(camera, frame_id)
    if capture is None:
        return False, None
    success, frame = await asyncio.to_thread(capture.read)
    return success, frame


def mark_camera_state(camera_id: str, status: str, reconnect_increment: bool = False) -> None:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            return
        camera.status = status
        if reconnect_increment:
            camera.reconnect_count += 1


async def publish_frames(camera_id: str) -> None:
    redis = get_redis_client()
    capture: cv2.VideoCapture | None = None
    frame_id = 0
    last_emit_monotonic = 0.0
    try:
        while True:
            with db_session() as session:
                camera = session.get(Camera, camera_id)
                if camera is None:
                    return
                fps = max(camera.target_fps, 1)
                session.add(
                    SystemMetric(
                        service="stream-gateway",
                        metric_name="camera_fps_target",
                        metric_value=float(fps),
                        labels_json={"camera_id": camera.id},
                    )
                )

            if not camera.source_uri.startswith("mock://"):
                if capture is None or not capture.isOpened():
                    capture = await asyncio.to_thread(open_capture, camera)
                    if not capture.isOpened():
                        logger.warning("capture open failed", extra={"camera_id": camera.id, "source_uri": camera.source_uri})
                        mark_camera_state(camera.id, "offline", reconnect_increment=True)
                        CAMERA_STATUS.labels(camera_id=camera.id).set(0)
                        await asyncio.sleep(settings.stream_reconnect_seconds)
                        continue

            now_monotonic = asyncio.get_running_loop().time()
            next_emit_at = last_emit_monotonic + (1 / fps) if last_emit_monotonic else now_monotonic
            if now_monotonic < next_emit_at:
                await asyncio.sleep(next_emit_at - now_monotonic)

            frame_id += 1
            success, frame_image = await next_frame(camera, capture, frame_id)
            if not success or frame_image is None:
                logger.warning("frame read failed", extra={"camera_id": camera.id, "source_uri": camera.source_uri})
                mark_camera_state(camera.id, "offline", reconnect_increment=True)
                CAMERA_STATUS.labels(camera_id=camera.id).set(0)
                if capture is not None:
                    await asyncio.to_thread(capture.release)
                    capture = None
                await asyncio.sleep(settings.stream_reconnect_seconds)
                continue

            captured_at = datetime.now(timezone.utc)
            frame_path = await asyncio.to_thread(write_frame_file, camera_id, frame_id, frame_image)
            with db_session() as session:
                camera_row = session.get(Camera, camera_id)
                if camera_row is None:
                    return
                camera_row.status = "online"
                camera_row.last_frame_at = captured_at

            envelope = FrameEnvelope(
                camera_id=camera_id,
                frame_id=frame_id,
                captured_at=captured_at,
                source_uri=camera.source_uri,
                frame_token=f"{camera_id}:{frame_id}",
                frame_path=frame_path,
                frame_width=int(frame_image.shape[1]),
                frame_height=int(frame_image.shape[0]),
            )
            await redis.rpush(settings.frame_queue_name, envelope.model_dump_json())
            depth = await redis.llen(settings.frame_queue_name)
            QUEUE_DEPTH.labels(queue_name=settings.frame_queue_name).set(depth)
            FRAME_EMITTED.labels(camera_id=camera_id).inc()
            CAMERA_STATUS.labels(camera_id=camera_id).set(1)
            last_emit_monotonic = asyncio.get_running_loop().time()
    except asyncio.CancelledError:
        raise
    finally:
        if capture is not None:
            await asyncio.to_thread(capture.release)
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
