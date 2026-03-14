from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from libs.common.config import settings

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720


def artifacts_root() -> Path:
    path = Path(settings.snapshot_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_path(camera_id: str) -> Path:
    path = artifacts_root() / "previews"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{camera_id}.svg"


def snapshot_path(camera_id: str, event_id: str) -> Path:
    path = artifacts_root() / "events"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{camera_id}_{event_id}.svg"


def write_camera_preview(
    camera_id: str,
    frame_id: int,
    source_uri: str,
    detections: list[dict[str, Any]],
    camera_metadata: dict[str, Any] | None = None,
) -> str:
    path = preview_path(camera_id)
    path.write_text(
        render_scene_svg(
            camera_id=camera_id,
            frame_id=frame_id,
            title=f"Live Preview / {camera_id}",
            subtitle=source_uri,
            detections=detections,
            camera_metadata=camera_metadata or {},
        ),
        encoding="utf-8",
    )
    return str(path)


def write_event_snapshot(
    camera_id: str,
    event_id: str,
    frame_id: int,
    source_uri: str,
    detections: list[dict[str, Any]],
    camera_metadata: dict[str, Any] | None,
    event_type: str,
    event_payload: dict[str, Any],
    highlight_track_id: str | None,
    created_at: datetime,
) -> str:
    path = snapshot_path(camera_id, event_id)
    path.write_text(
        render_scene_svg(
            camera_id=camera_id,
            frame_id=frame_id,
            title=f"Event Snapshot / {event_type}",
            subtitle=created_at.isoformat(),
            detections=detections,
            camera_metadata=camera_metadata or {},
            highlight_track_id=highlight_track_id,
            event_payload=event_payload,
            footer=source_uri,
        ),
        encoding="utf-8",
    )
    return str(path)


def render_scene_svg(
    camera_id: str,
    frame_id: int,
    title: str,
    subtitle: str,
    detections: list[dict[str, Any]],
    camera_metadata: dict[str, Any],
    highlight_track_id: str | None = None,
    event_payload: dict[str, Any] | None = None,
    footer: str | None = None,
) -> str:
    zone = _polygon(camera_metadata.get("zone", []), "rgba(57, 224, 155, 0.12)", "#39e09b")
    loitering_zone = _polygon(
        camera_metadata.get("loitering_zone", []),
        "rgba(255, 196, 61, 0.16)",
        "#ffc43d",
        dashed=True,
    )
    line = _line(camera_metadata.get("line", []))
    boxes = [
        _detection_box(detection, highlight=detection.get("track_id") == highlight_track_id)
        for detection in detections
    ]
    event_chip = ""
    if event_payload:
        payload_items = " • ".join(f"{key}={_format_payload_value(value)}" for key, value in event_payload.items())
        event_chip = (
            f'<g transform="translate(42, 124)">'
            f'<rect width="{max(280, len(payload_items) * 8)}" height="36" rx="18" fill="rgba(255,255,255,0.92)" />'
            f'<text x="18" y="23" font-size="16" fill="#162033">{escape(payload_items)}</text>'
            f"</g>"
        )

    footer_text = (
        f'<text x="42" y="{CANVAS_HEIGHT - 28}" font-size="18" fill="rgba(255,255,255,0.72)">{escape(footer)}</text>'
        if footer
        else ""
    )
    detections_count = len(detections)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0%" x2="100%" y1="0%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="50%" stop-color="#10233f" />
      <stop offset="100%" stop-color="#19324d" />
    </linearGradient>
    <pattern id="grid" width="64" height="64" patternUnits="userSpaceOnUse">
      <path d="M 64 0 L 0 0 0 64" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
    </pattern>
  </defs>
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="url(#bg)" />
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="url(#grid)" />
  <circle cx="1080" cy="110" r="240" fill="rgba(64, 196, 255, 0.12)" />
  <circle cx="180" cy="620" r="220" fill="rgba(255, 140, 92, 0.10)" />
  <g transform="translate(42, 42)">
    <text x="0" y="0" dy="0.9em" font-size="34" font-family="IBM Plex Sans, sans-serif" font-weight="700" fill="#ffffff">{escape(title)}</text>
    <text x="0" y="44" font-size="18" font-family="IBM Plex Sans, sans-serif" fill="rgba(255,255,255,0.72)">{escape(subtitle)}</text>
  </g>
  <g transform="translate(1040, 40)">
    <rect width="198" height="94" rx="20" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.12)" />
    <text x="20" y="36" font-size="18" fill="#c7d2fe">camera</text>
    <text x="20" y="62" font-size="24" font-weight="700" fill="#ffffff">{escape(camera_id)}</text>
    <text x="20" y="84" font-size="16" fill="rgba(255,255,255,0.72)">frame {frame_id} • {detections_count} detections</text>
  </g>
  {event_chip}
  {zone}
  {loitering_zone}
  {line}
  {''.join(boxes)}
  {footer_text}
</svg>
"""


def _polygon(points: list[list[float]] | list[tuple[float, float]], fill: str, stroke: str, dashed: bool = False) -> str:
    if len(points) < 3:
        return ""
    point_text = " ".join(f"{x * CANVAS_WIDTH:.1f},{y * CANVAS_HEIGHT:.1f}" for x, y in points)
    dash = ' stroke-dasharray="14 10"' if dashed else ""
    return (
        f'<polygon points="{point_text}" fill="{fill}" stroke="{stroke}" stroke-width="4"{dash} />'
    )


def _line(points: list[list[float]] | list[tuple[float, float]]) -> str:
    if len(points) != 2:
        return ""
    x1, y1 = points[0]
    x2, y2 = points[1]
    return (
        f'<line x1="{x1 * CANVAS_WIDTH:.1f}" y1="{y1 * CANVAS_HEIGHT:.1f}" '
        f'x2="{x2 * CANVAS_WIDTH:.1f}" y2="{y2 * CANVAS_HEIGHT:.1f}" '
        f'stroke="#f472b6" stroke-width="5" stroke-linecap="round" />'
    )


def _detection_box(detection: dict[str, Any], highlight: bool) -> str:
    x1, y1, x2, y2 = detection["bbox"]
    left = x1 * CANVAS_WIDTH
    top = y1 * CANVAS_HEIGHT
    width = max((x2 - x1) * CANVAS_WIDTH, 8)
    height = max((y2 - y1) * CANVAS_HEIGHT, 8)
    centroid_x, centroid_y = detection["centroid"]
    stroke = "#ff8c5c" if highlight else "#6ee7ff"
    badge_width = 190 if highlight else 170
    label = f'{detection["class_name"]} #{detection["track_id"]} • {detection["confidence"]:.2f}'
    return (
        f'<g>'
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{width:.1f}" height="{height:.1f}" '
        f'rx="18" fill="rgba(110,231,255,0.08)" stroke="{stroke}" stroke-width="4" />'
        f'<circle cx="{centroid_x * CANVAS_WIDTH:.1f}" cy="{centroid_y * CANVAS_HEIGHT:.1f}" r="7" fill="{stroke}" />'
        f'<rect x="{left:.1f}" y="{max(18, top - 42):.1f}" width="{badge_width}" height="30" rx="15" fill="rgba(15,23,42,0.88)" />'
        f'<text x="{left + 14:.1f}" y="{max(37, top - 22):.1f}" font-size="16" fill="#ffffff">{escape(label)}</text>'
        f'</g>'
    )


def _format_payload_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return "[" + ",".join(_format_payload_value(item) for item in value[:4]) + "]"
    return str(value)
