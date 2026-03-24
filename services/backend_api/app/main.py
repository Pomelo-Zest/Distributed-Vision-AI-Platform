from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, func, select

from libs.common.camera_config import camera_geometry, delete_camera_config, sync_camera_geometry
from libs.common.config import settings
from libs.common.db import Camera, EventRecord, DetectionLog, SystemMetric, db_session, init_db
from libs.common.event_settings import DEFAULT_EVENT_SETTINGS, normalize_event_settings
from libs.common.hls import HLSStreamManager
from libs.common.logging import configure_logging
from libs.common.redis_client import get_redis_client
from libs.common.visualization import artifacts_root, preview_path, render_scene_svg
from libs.common.webrtc import WebRTCStreamManager

logger = configure_logging("backend-api")
app = FastAPI(title="Vision AI Backend API", version="0.1.0")
hls_manager = HLSStreamManager()
webrtc_manager = WebRTCStreamManager()


DEFAULT_DETECTION_SETTINGS = {
    "categories": [item.strip() for item in settings.detection_categories.split(",") if item.strip()],
    "min_confidence": settings.yolo_confidence,
    "min_box_area": settings.detection_min_box_area,
}


class WebRTCOffer(BaseModel):
    sdp: str
    type: str


class CameraCreate(BaseModel):
    id: str
    name: str
    source_uri: str
    target_fps: int = 5
    metadata: dict = Field(default_factory=dict)


class CameraGeometryUpdate(BaseModel):
    zone: list[list[float]] = Field(default_factory=list)
    loitering_zone: list[list[float]] = Field(default_factory=list)
    line: list[list[float]] = Field(default_factory=list)


class CameraDetectionSettingsUpdate(BaseModel):
    categories: list[str] = Field(default_factory=list)
    min_confidence: float = Field(default=DEFAULT_DETECTION_SETTINGS["min_confidence"], ge=0.05, le=0.99)
    min_box_area: float = Field(default=DEFAULT_DETECTION_SETTINGS["min_box_area"], ge=0.0, le=1.0)


class EventRuleUpdate(BaseModel):
    enabled: bool = True
    categories: list[str] = Field(default_factory=list)
    min_confidence: float = Field(default=DEFAULT_EVENT_SETTINGS["zone_entry"]["min_confidence"], ge=0.05, le=0.99)
    min_track_frames: int = Field(default=DEFAULT_EVENT_SETTINGS["zone_entry"]["min_track_frames"], ge=1, le=120)
    cooldown_seconds: float = Field(default=DEFAULT_EVENT_SETTINGS["zone_entry"]["cooldown_seconds"], ge=0.0, le=300.0)
    min_motion: float | None = Field(default=None, ge=0.0, le=1.0)
    min_side_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    stable_side_frames: int | None = Field(default=None, ge=1, le=30)
    confirm_frames: int | None = Field(default=None, ge=1, le=30)
    rearm_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    direction: str | None = None
    duration_seconds: float | None = Field(default=None, ge=1.0, le=3600.0)


class CameraEventSettingsUpdate(BaseModel):
    zone_entry: EventRuleUpdate = Field(default_factory=EventRuleUpdate)
    line_crossing: EventRuleUpdate = Field(default_factory=EventRuleUpdate)
    loitering: EventRuleUpdate = Field(default_factory=EventRuleUpdate)


def resolve_artifact(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def public_snapshot_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = resolve_artifact(path_value)
    try:
        relative_path = path.relative_to(artifacts_root())
    except ValueError:
        return None
    return f"/artifacts/{relative_path.as_posix()}"


def camera_runtime(camera: Camera) -> dict:
    metadata = camera.metadata_json or {}
    return dict(metadata.get("runtime", {}))


def camera_metadata(camera: Camera) -> dict:
    metadata = dict(camera.metadata_json or {})
    metadata.update(camera_geometry(camera))
    metadata["detection_settings"] = camera_detection_settings(camera)
    metadata["event_settings"] = camera_event_settings(camera)
    return metadata


def camera_detection_settings(camera: Camera) -> dict:
    metadata = dict(camera.metadata_json or {})
    raw = dict(metadata.get("detection_settings", {}))
    categories = [str(item).strip().lower() for item in raw.get("categories", []) if str(item).strip()]
    if not categories:
        categories = list(DEFAULT_DETECTION_SETTINGS["categories"])
    categories = [item for item in categories if item in {"person", "vehicle", "object"}]
    if not categories:
        categories = list(DEFAULT_DETECTION_SETTINGS["categories"])
    return {
        "categories": categories,
        "min_confidence": float(raw.get("min_confidence", DEFAULT_DETECTION_SETTINGS["min_confidence"])),
        "min_box_area": float(raw.get("min_box_area", DEFAULT_DETECTION_SETTINGS["min_box_area"])),
    }


def camera_event_settings(camera: Camera) -> dict:
    return normalize_event_settings(dict(camera.metadata_json or {}))


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info("backend ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    hls_manager.stop_all()
    await webrtc_manager.close_all()


@app.get("/health")
async def health() -> dict[str, str]:
    with db_session() as session:
        session.execute(select(1))
    redis = get_redis_client()
    await redis.ping()
    await redis.close()
    return {"status": "ok"}


@app.get("/cameras")
def list_cameras() -> list[dict]:
    with db_session() as session:
        cameras = session.scalars(select(Camera).order_by(Camera.id)).all()
        return [
            {
                "id": camera.id,
                "name": camera.name,
                "source_uri": camera.source_uri,
                "status": camera.status,
                "target_fps": camera.target_fps,
                "reconnect_count": camera.reconnect_count,
                "last_frame_at": camera.last_frame_at,
                "last_inference_at": camera.last_inference_at,
                "metadata": camera_metadata(camera),
                "runtime": camera_runtime(camera),
                "preview_url": f"/cameras/{camera.id}/preview",
                "stream_url": f"/cameras/{camera.id}/hls/index.m3u8",
                "stream_protocol": "hls",
                "webrtc_url": f"/cameras/{camera.id}/webrtc/offer",
            }
            for camera in cameras
        ]


@app.post("/cameras", status_code=201)
def create_camera(payload: CameraCreate) -> dict:
    if not payload.source_uri.startswith(("rtsp://", "rtsps://", "http://", "https://", "file://")) and "/" not in payload.source_uri:
        raise HTTPException(status_code=400, detail="source_uri must be an RTSP, HTTP, file URI, or local path")
    with db_session() as session:
        existing = session.get(Camera, payload.id)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Camera id already exists")
        camera = Camera(
            id=payload.id,
            name=payload.name,
            source_uri=payload.source_uri,
            status="idle",
            target_fps=max(payload.target_fps, 1),
            metadata_json=payload.metadata or {},
        )
        session.add(camera)
        session.flush()
        return {
            "id": camera.id,
            "name": camera.name,
            "source_uri": camera.source_uri,
            "status": camera.status,
            "target_fps": camera.target_fps,
            "metadata": camera_metadata(camera),
        }


@app.get("/cameras/{camera_id}")
def get_camera(camera_id: str) -> dict:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        recent_tracks = session.execute(
            select(DetectionLog)
            .where(DetectionLog.camera_id == camera_id)
            .order_by(desc(DetectionLog.created_at))
            .limit(10)
        ).scalars()
        return {
            "id": camera.id,
            "name": camera.name,
            "status": camera.status,
            "target_fps": camera.target_fps,
            "source_uri": camera.source_uri,
            "reconnect_count": camera.reconnect_count,
            "last_frame_at": camera.last_frame_at,
            "last_inference_at": camera.last_inference_at,
            "metadata": camera_metadata(camera),
            "runtime": camera_runtime(camera),
            "preview_url": f"/cameras/{camera.id}/preview",
            "stream_url": f"/cameras/{camera.id}/hls/index.m3u8",
            "stream_protocol": "hls",
            "webrtc_url": f"/cameras/{camera.id}/webrtc/offer",
            "recent_tracks": [
                {
                    "frame_id": row.frame_id,
                    "track_id": row.track_id,
                    "confidence": row.confidence,
                    "bbox": row.bbox_json,
                    "centroid": [row.centroid_x, row.centroid_y],
                    "captured_at": row.captured_at,
                }
                for row in recent_tracks
            ],
        }


@app.delete("/cameras/{camera_id}", status_code=204, response_model=None)
async def delete_camera(camera_id: str) -> Response:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        session.delete(camera)
    delete_camera_config(camera_id)
    hls_manager.stop_stream(camera_id)
    await webrtc_manager.close_camera(camera_id)
    return Response(status_code=204)


@app.put("/cameras/{camera_id}/geometry")
def update_camera_geometry(camera_id: str, payload: CameraGeometryUpdate) -> dict:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
    geometry = sync_camera_geometry(camera_id, payload.model_dump())
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        return {
            "id": camera.id,
            "metadata": camera_metadata(camera),
            "geometry": geometry,
        }


@app.put("/cameras/{camera_id}/detection_settings")
def update_camera_detection_settings(camera_id: str, payload: CameraDetectionSettingsUpdate) -> dict:
    categories = [item.strip().lower() for item in payload.categories if item.strip()]
    categories = [item for item in categories if item in {"person", "vehicle", "object"}]
    if not categories:
        raise HTTPException(status_code=400, detail="Select at least one detection category")
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        metadata = dict(camera.metadata_json or {})
        metadata["detection_settings"] = {
            "categories": categories,
            "min_confidence": payload.min_confidence,
            "min_box_area": payload.min_box_area,
        }
        camera.metadata_json = metadata
        return {
            "id": camera.id,
            "metadata": camera_metadata(camera),
            "detection_settings": camera_detection_settings(camera),
        }


@app.put("/cameras/{camera_id}/event_settings")
def update_camera_event_settings(camera_id: str, payload: CameraEventSettingsUpdate) -> dict:
    normalized = normalize_event_settings({"event_settings": payload.model_dump()})
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        metadata = dict(camera.metadata_json or {})
        metadata["event_settings"] = normalized
        camera.metadata_json = metadata
        return {
            "id": camera.id,
            "metadata": camera_metadata(camera),
            "event_settings": camera_event_settings(camera),
        }


@app.get("/events")
def list_events(limit: int = 50, camera_id: str | None = None, rule_type: str | None = None) -> list[dict]:
    with db_session() as session:
        query = select(EventRecord).order_by(desc(EventRecord.created_at)).limit(min(limit, 200))
        if camera_id:
            query = query.where(EventRecord.camera_id == camera_id)
        if rule_type:
            query = query.where(EventRecord.rule_type == rule_type)
        events = session.scalars(query).all()
        return [
            {
                "id": event.id,
                "camera_id": event.camera_id,
                "rule_type": event.rule_type,
                "track_id": event.track_id,
                "frame_id": event.frame_id,
                "severity": event.severity,
                "payload": event.payload_json,
                "snapshot_path": event.snapshot_path,
                "snapshot_url": public_snapshot_url(event.snapshot_path),
                "created_at": event.created_at,
            }
            for event in events
        ]


@app.get("/events/{event_id}")
def get_event(event_id: str) -> dict:
    with db_session() as session:
        event = session.get(EventRecord, event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return {
            "id": event.id,
            "camera_id": event.camera_id,
            "rule_type": event.rule_type,
            "track_id": event.track_id,
            "frame_id": event.frame_id,
            "severity": event.severity,
            "payload": event.payload_json,
            "snapshot_path": event.snapshot_path,
            "snapshot_url": public_snapshot_url(event.snapshot_path),
            "created_at": event.created_at,
        }


@app.get("/cameras/{camera_id}/preview", response_model=None)
def camera_preview(camera_id: str) -> Response:
    path = preview_path(camera_id)
    if not path.exists():
        return Response(
            render_scene_svg(
                camera_id=camera_id,
                frame_id=0,
                title=f"Live Preview / {camera_id}",
                subtitle="Awaiting first inference result",
                detections=[],
                camera_metadata={},
            ),
            media_type="image/svg+xml",
        )
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/cameras/{camera_id}/hls/{asset_name:path}")
def camera_hls_asset(camera_id: str, asset_name: str) -> Response:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
    try:
        if asset_name == "index.m3u8":
            path = hls_manager.wait_until_ready(camera)
        else:
            path = hls_manager.asset_path(camera_id, asset_name)
            if not path.exists():
                hls_manager.ensure_stream(camera)
                deadline = time.time() + 2
                while time.time() < deadline and not path.exists():
                    time.sleep(0.1)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HLS asset not found")
    if path.suffix == ".m3u8":
        return Response(
            path.read_text(encoding="utf-8"),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )
    media_type = "video/mp2t" if path.suffix == ".ts" else None
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.post("/cameras/{camera_id}/webrtc/offer")
async def camera_webrtc_offer(camera_id: str, offer: WebRTCOffer) -> dict[str, str]:
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
    try:
        return await webrtc_manager.create_answer(camera, offer.sdp, offer.type)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/artifacts/{artifact_path:path}")
def artifact(artifact_path: str) -> FileResponse:
    path = artifacts_root() / artifact_path
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = "image/svg+xml" if path.suffix == ".svg" else None
    return FileResponse(path, media_type=media_type)


@app.get("/metrics/summary")
async def metrics_summary() -> dict:
    redis = get_redis_client()
    frame_depth = await redis.llen(settings.frame_queue_name)
    track_depth = await redis.llen(settings.track_queue_name)
    await redis.close()
    with db_session() as session:
        active_cameras = session.scalar(select(func.count()).select_from(Camera).where(Camera.status == "online")) or 0
        total_events = session.scalar(select(func.count()).select_from(EventRecord)) or 0
        latest_frame_per_camera = (
            select(
                DetectionLog.camera_id.label("camera_id"),
                func.max(DetectionLog.frame_id).label("frame_id"),
            )
            .group_by(DetectionLog.camera_id)
            .subquery()
        )
        latest_tracks_query = (
            select(DetectionLog.camera_id, DetectionLog.track_id)
            .join(
                latest_frame_per_camera,
                (DetectionLog.camera_id == latest_frame_per_camera.c.camera_id)
                & (DetectionLog.frame_id == latest_frame_per_camera.c.frame_id),
            )
            .distinct()
            .subquery()
        )
        total_detections = session.scalar(select(func.count()).select_from(latest_tracks_query)) or 0
        latest_metrics = session.scalars(
            select(SystemMetric).order_by(desc(SystemMetric.created_at)).limit(10)
        ).all()
    return {
        "active_cameras": active_cameras,
        "total_events": total_events,
        "total_detections": total_detections,
        "queue_depth": {"frames": frame_depth, "tracks": track_depth},
        "latest_service_metrics": [
            {
                "service": metric.service,
                "name": metric.metric_name,
                "value": metric.metric_value,
                "labels": metric.labels_json,
                "created_at": metric.created_at,
            }
            for metric in latest_metrics
        ],
    }


@app.post("/metrics/reset_summary")
async def reset_metrics_summary() -> dict:
    with db_session() as session:
        session.execute(delete(EventRecord))
        session.execute(delete(DetectionLog))
        session.execute(delete(SystemMetric))
        cameras = session.scalars(select(Camera)).all()
        for camera in cameras:
            metadata = dict(camera.metadata_json or {})
            runtime = dict(metadata.get("runtime", {}))
            runtime["last_event"] = None
            metadata["runtime"] = runtime
            camera.metadata_json = metadata
    return await metrics_summary()


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> FileResponse:
    path = Path("/app/dashboard/index.html")
    if not path.exists():
        path = Path.cwd() / "dashboard" / "index.html"
    return FileResponse(path)


@app.get("/dashboard/{asset_path:path}")
def dashboard_assets(asset_path: str) -> FileResponse:
    path = Path("/app/dashboard") / asset_path
    if not path.exists():
        path = Path.cwd() / "dashboard" / asset_path
    return FileResponse(path)
