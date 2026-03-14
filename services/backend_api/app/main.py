from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import desc, func, select

from libs.common.config import settings
from libs.common.db import Camera, EventRecord, DetectionLog, SystemMetric, db_session, init_db
from libs.common.logging import configure_logging
from libs.common.redis_client import get_redis_client
from libs.common.visualization import artifacts_root, preview_path, render_scene_svg

logger = configure_logging("backend-api")
app = FastAPI(title="Vision AI Backend API", version="0.1.0")


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


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info("backend ready")


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
                "status": camera.status,
                "target_fps": camera.target_fps,
                "reconnect_count": camera.reconnect_count,
                "last_frame_at": camera.last_frame_at,
                "last_inference_at": camera.last_inference_at,
                "metadata": camera.metadata_json,
                "preview_url": f"/cameras/{camera.id}/preview",
            }
            for camera in cameras
        ]


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
            "metadata": camera.metadata_json,
            "preview_url": f"/cameras/{camera.id}/preview",
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


@app.get("/cameras/{camera_id}/preview")
def camera_preview(camera_id: str) -> FileResponse | Response:
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
        total_detections = session.scalar(select(func.count()).select_from(DetectionLog)) or 0
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
