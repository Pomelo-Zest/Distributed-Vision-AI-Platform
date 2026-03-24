from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libs.common.geometry import crossed_line, line_distance, point_distance, point_in_polygon, side_of_line
from libs.schemas.messages import Detection, InferenceEnvelope


@dataclass(slots=True)
class TrackContext:
    last_centroid: tuple[float, float] | None = None
    last_anchor: tuple[float, float] | None = None
    zone_inside: bool = False
    loitering_started_at: datetime | None = None
    emitted_loitering: bool = False
    last_frame_id: int = 0
    last_event_at: dict[str, datetime] = field(default_factory=dict)
    observed_frames: int = 0
    line_side_sign: int = 0
    line_side_streak: int = 0
    pending_line_sign: int = 0
    pending_line_count: int = 0
    pending_line_from_sign: int = 0
    line_cross_armed: bool = True


def reset_track_context(ctx: TrackContext) -> None:
    ctx.last_centroid = None
    ctx.last_anchor = None
    ctx.zone_inside = False
    ctx.loitering_started_at = None
    ctx.emitted_loitering = False
    ctx.last_frame_id = 0
    ctx.last_event_at.clear()
    ctx.observed_frames = 0
    ctx.line_side_sign = 0
    ctx.line_side_streak = 0
    ctx.pending_line_sign = 0
    ctx.pending_line_count = 0
    ctx.pending_line_from_sign = 0
    ctx.line_cross_armed = True


def signed_side(point: tuple[float, float], line: list[tuple[float, float]], min_side_distance: float) -> int:
    distance = line_distance(point, line)
    if distance < min_side_distance:
        return 0
    side = side_of_line(point, line)
    return 1 if side > 0 else -1


def can_emit_rule(
    ctx: TrackContext,
    frame: InferenceEnvelope,
    detection: Detection,
    rule_name: str,
    rule_settings: dict[str, Any],
) -> bool:
    if not rule_settings.get("enabled", True):
        return False
    if not detection.tracked:
        return False
    if detection.category not in set(rule_settings.get("categories", [])):
        return False
    if ctx.observed_frames < int(rule_settings.get("min_track_frames", 1)):
        return False
    if detection.confidence < float(rule_settings.get("min_confidence", 0.0)):
        return False
    last_emitted = ctx.last_event_at.get(rule_name)
    if last_emitted is None:
        return True
    return (frame.inference_at - last_emitted).total_seconds() >= float(rule_settings.get("cooldown_seconds", 0.0))


def mark_rule_emitted(ctx: TrackContext, frame: InferenceEnvelope, rule_name: str) -> None:
    ctx.last_event_at[rule_name] = frame.inference_at


def evaluate_track_rules(
    ctx: TrackContext,
    frame: InferenceEnvelope,
    detection: Detection,
    geometry: dict[str, list[tuple[float, float]]],
    event_settings: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    results: list[tuple[str, dict[str, Any]]] = []
    centroid = tuple(detection.centroid)
    anchor = tuple(detection.anchor)
    frame_gap = frame.frame_id - ctx.last_frame_id if ctx.last_frame_id else 1
    if frame_gap > 8:
        reset_track_context(ctx)
    ctx.observed_frames += 1

    zone = geometry["zone"]
    line = geometry["line"]
    loitering_zone = geometry["loitering_zone"]

    zone_settings = event_settings["zone_entry"]
    if zone:
        inside_zone = point_in_polygon(anchor, zone)
        moved_enough = ctx.last_anchor is None or point_distance(ctx.last_anchor, anchor) >= float(zone_settings["min_motion"])
        if inside_zone and not ctx.zone_inside and moved_enough and can_emit_rule(ctx, frame, detection, "zone_entry", zone_settings):
            payload = {
                "anchor": detection.anchor,
                "centroid": detection.centroid,
                "zone": zone,
                "class_name": detection.class_name,
                "category": detection.category,
                "confidence": detection.confidence,
            }
            results.append(("zone_entry", payload))
            mark_rule_emitted(ctx, frame, "zone_entry")
        ctx.zone_inside = inside_zone

    line_settings = event_settings["line_crossing"]
    if line:
        current_side_sign = signed_side(anchor, line, float(line_settings["min_side_distance"]))
        if line_distance(anchor, line) >= float(line_settings["rearm_distance"]):
            ctx.line_cross_armed = True
        if current_side_sign == 0:
            ctx.pending_line_sign = 0
            ctx.pending_line_count = 0
        elif ctx.line_side_sign == 0:
            ctx.line_side_sign = current_side_sign
            ctx.line_side_streak = 1
        elif current_side_sign == ctx.line_side_sign:
            ctx.line_side_streak += 1
            ctx.pending_line_sign = 0
            ctx.pending_line_count = 0
        else:
            if ctx.pending_line_sign != current_side_sign:
                ctx.pending_line_sign = current_side_sign
                ctx.pending_line_count = 1
                ctx.pending_line_from_sign = ctx.line_side_sign
            else:
                ctx.pending_line_count += 1
            stable_ready = ctx.line_side_streak >= int(line_settings["stable_side_frames"])
            confirm_ready = ctx.pending_line_count >= int(line_settings["confirm_frames"])
            direction = "positive_to_negative" if ctx.pending_line_from_sign > 0 else "negative_to_positive"
            direction_allowed = line_settings["direction"] in {"both", direction}
            if (
                ctx.last_anchor
                and ctx.line_cross_armed
                and stable_ready
                and confirm_ready
                and direction_allowed
                and can_emit_rule(ctx, frame, detection, "line_crossing", line_settings)
                and crossed_line(
                    ctx.last_anchor,
                    anchor,
                    line,
                    min_motion_distance=float(line_settings["min_motion"]),
                    min_side_distance=float(line_settings["min_side_distance"]),
                )
            ):
                payload = {
                    "from": list(ctx.last_anchor),
                    "to": detection.anchor,
                    "line": line,
                    "anchor": detection.anchor,
                    "direction": direction,
                    "class_name": detection.class_name,
                    "category": detection.category,
                    "confidence": detection.confidence,
                }
                results.append(("line_crossing", payload))
                mark_rule_emitted(ctx, frame, "line_crossing")
                ctx.line_cross_armed = False
            ctx.line_side_sign = current_side_sign
            ctx.line_side_streak = 1
            ctx.pending_line_sign = 0
            ctx.pending_line_count = 0
            ctx.pending_line_from_sign = 0

    loiter_settings = event_settings["loitering"]
    if loitering_zone:
        inside_loitering = point_in_polygon(anchor, loitering_zone)
        if inside_loitering and ctx.loitering_started_at is None:
            ctx.loitering_started_at = frame.inference_at
        if not inside_loitering:
            ctx.loitering_started_at = None
            ctx.emitted_loitering = False
        if (
            inside_loitering
            and ctx.loitering_started_at is not None
            and not ctx.emitted_loitering
            and can_emit_rule(ctx, frame, detection, "loitering", loiter_settings)
            and (frame.inference_at - ctx.loitering_started_at).total_seconds() >= float(loiter_settings["duration_seconds"])
        ):
            payload = {
                "duration_seconds": float(loiter_settings["duration_seconds"]),
                "zone": loitering_zone,
                "anchor": detection.anchor,
                "class_name": detection.class_name,
                "category": detection.category,
                "confidence": detection.confidence,
            }
            results.append(("loitering", payload))
            ctx.emitted_loitering = True
            mark_rule_emitted(ctx, frame, "loitering")

    ctx.last_centroid = centroid
    ctx.last_anchor = anchor
    ctx.last_frame_id = frame.frame_id
    return results

