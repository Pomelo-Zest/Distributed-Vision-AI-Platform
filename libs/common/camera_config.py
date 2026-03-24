from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from libs.common.config import settings
from libs.common.db import Camera, db_session

CONFIG_KEYS = ("zone", "loitering_zone", "line")
_CONFIG_LOCK = Lock()
_CACHE: dict[str, dict[str, Any]] | None = None
_CACHE_MTIME: float | None = None


def camera_config_path() -> Path:
    path = Path(settings.camera_config_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    return path


def _normalize_geometry(payload: dict[str, Any]) -> dict[str, Any]:
    geometry: dict[str, Any] = {}
    for key in CONFIG_KEYS:
        value = payload.get(key, [])
        if key == "line":
            geometry[key] = [[float(x), float(y)] for x, y in value[:2]]
        else:
            geometry[key] = [[float(x), float(y)] for x, y in value]
    return geometry


def load_camera_configs(force: bool = False) -> dict[str, dict[str, Any]]:
    global _CACHE, _CACHE_MTIME
    path = camera_config_path()
    mtime = path.stat().st_mtime
    if not force and _CACHE is not None and _CACHE_MTIME == mtime:
        return _CACHE
    with _CONFIG_LOCK:
        mtime = path.stat().st_mtime
        if not force and _CACHE is not None and _CACHE_MTIME == mtime:
            return _CACHE
        payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        _CACHE = {camera_id: _normalize_geometry(config) for camera_id, config in payload.items()}
        _CACHE_MTIME = mtime
        return _CACHE


def save_camera_config(camera_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _CACHE, _CACHE_MTIME
    path = camera_config_path()
    geometry = _normalize_geometry(payload)
    with _CONFIG_LOCK:
        configs = json.loads(path.read_text(encoding="utf-8") or "{}")
        configs[camera_id] = geometry
        path.write_text(json.dumps(configs, indent=2) + "\n", encoding="utf-8")
        _CACHE = None
        _CACHE_MTIME = None
    return geometry


def delete_camera_config(camera_id: str) -> None:
    global _CACHE, _CACHE_MTIME
    path = camera_config_path()
    with _CONFIG_LOCK:
        configs = json.loads(path.read_text(encoding="utf-8") or "{}")
        if camera_id in configs:
            configs.pop(camera_id, None)
            path.write_text(json.dumps(configs, indent=2) + "\n", encoding="utf-8")
        _CACHE = None
        _CACHE_MTIME = None


def camera_geometry(camera: Camera, force: bool = False) -> dict[str, Any]:
    configs = load_camera_configs(force=force)
    from_file = configs.get(camera.id, {})
    metadata = dict(camera.metadata_json or {})
    geometry = {key: from_file.get(key, metadata.get(key, [])) for key in CONFIG_KEYS}
    return _normalize_geometry(geometry)


def sync_camera_geometry(camera_id: str, geometry: dict[str, Any]) -> dict[str, Any]:
    normalized = save_camera_config(camera_id, geometry)
    with db_session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            return normalized
        metadata = dict(camera.metadata_json or {})
        for key, value in normalized.items():
            metadata[key] = value
        camera.metadata_json = metadata
    return normalized
