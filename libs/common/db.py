from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from libs.common.config import settings


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(32), default="offline")
    target_fps: Mapped[int] = mapped_column(Integer, default=5)
    reconnect_count: Mapped[int] = mapped_column(Integer, default=0)
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inference_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DetectionLog(Base):
    __tablename__ = "detection_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    frame_id: Mapped[int] = mapped_column(Integer)
    track_id: Mapped[str] = mapped_column(String(64), index=True)
    class_name: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    bbox_json: Mapped[dict] = mapped_column(JSON)
    centroid_x: Mapped[float] = mapped_column(Float)
    centroid_y: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    track_id: Mapped[str] = mapped_column(String(64), index=True)
    frame_id: Mapped[int] = mapped_column(Integer, index=True)
    severity: Mapped[str] = mapped_column(String(32), default="info")
    snapshot_path: Mapped[str | None] = mapped_column(Text())
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class SystemMetric(Base):
    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    metric_value: Mapped[float] = mapped_column(Float)
    labels_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def update_camera_runtime(camera: Camera, **runtime_fields: object) -> None:
    metadata = dict(camera.metadata_json or {})
    runtime = dict(metadata.get("runtime", {}))
    runtime.update(runtime_fields)
    metadata["runtime"] = runtime
    camera.metadata_json = metadata


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
