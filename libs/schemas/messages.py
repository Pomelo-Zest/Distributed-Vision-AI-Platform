from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FrameEnvelope(BaseModel):
    camera_id: str
    frame_id: int
    captured_at: datetime
    source_uri: str
    frame_token: str
    frame_path: str | None = None
    frame_width: int | None = None
    frame_height: int | None = None


class Detection(BaseModel):
    class_name: str = "person"
    confidence: float
    bbox: list[float] = Field(description="[x1, y1, x2, y2] in normalized coordinates")
    centroid: list[float]
    track_id: str


class InferenceEnvelope(BaseModel):
    camera_id: str
    frame_id: int
    captured_at: datetime
    inference_at: datetime
    detections: list[Detection]
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(BaseModel):
    id: str
    camera_id: str
    rule_type: str
    track_id: str
    frame_id: int
    severity: str = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    snapshot_path: str | None = None
    created_at: datetime
