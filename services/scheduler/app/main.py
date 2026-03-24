from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from libs.common.config import settings
from libs.common.db import Camera, SystemMetric, db_session, init_db
from libs.common.logging import configure_logging

logger = configure_logging("scheduler")
app = FastAPI(title="Vision AI Scheduler", version="0.1.0")


def is_local_video_source(source_uri: str) -> bool:
    return source_uri.startswith("file://") or "://" not in source_uri


def seed_cameras() -> int:
    path = Path(settings.camera_seed_path)
    if not path.exists():
        path = Path.cwd() / settings.camera_seed_path
    payload = json.loads(path.read_text())
    upserts = 0
    seeded_ids = {entry["id"] for entry in payload}
    with db_session() as session:
        for entry in payload:
            camera = session.get(Camera, entry["id"])
            if camera is None:
                camera = Camera(
                    id=entry["id"],
                    name=entry["name"],
                    source_uri=entry["source_uri"],
                    status="idle",
                    target_fps=entry["target_fps"],
                    metadata_json=entry["metadata"],
                )
                session.add(camera)
            else:
                camera.name = entry["name"]
                camera.source_uri = entry["source_uri"]
                camera.target_fps = entry["target_fps"]
                camera.metadata_json = entry["metadata"]
            upserts += 1
        for camera in session.query(Camera).all():
            if camera.id not in seeded_ids and is_local_video_source(camera.source_uri):
                session.delete(camera)
        session.add(
            SystemMetric(
                service="scheduler",
                metric_name="camera_seed_count",
                metric_value=upserts,
                labels_json={},
            )
        )
    return upserts


@app.on_event("startup")
def startup() -> None:
    init_db()
    seeded = seed_cameras()
    logger.info("seeded %s cameras", seeded)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/seed")
def seed() -> dict[str, int]:
    return {"seeded": seed_cameras()}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
