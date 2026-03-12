from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(slots=True)
class Settings:
    database_url: str = _env(
        "DATABASE_URL",
        "postgresql+psycopg://vision:vision@localhost:5432/vision_ai",
    )
    redis_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    api_host: str = _env("API_HOST", "0.0.0.0")
    api_port: int = int(_env("API_PORT", "8000"))
    stream_gateway_port: int = int(_env("STREAM_GATEWAY_PORT", "8010"))
    inference_worker_port: int = int(_env("INFERENCE_WORKER_PORT", "8020"))
    event_engine_port: int = int(_env("EVENT_ENGINE_PORT", "8030"))
    scheduler_port: int = int(_env("SCHEDULER_PORT", "8040"))
    frame_queue_name: str = _env("FRAME_QUEUE_NAME", "vision:frames")
    track_queue_name: str = _env("TRACK_QUEUE_NAME", "vision:tracks")
    camera_seed_path: str = _env("CAMERA_SEED_PATH", "config/cameras.seed.json")
    snapshot_dir: str = _env("SNAPSHOT_DIR", "vision_snapshots")
    loitering_seconds: int = int(_env("LOITERING_SECONDS", "10"))


settings = Settings()

