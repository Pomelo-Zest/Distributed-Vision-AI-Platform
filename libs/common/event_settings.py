from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.common.config import settings

ALLOWED_CATEGORIES = {"person", "vehicle", "object"}
ALLOWED_DIRECTIONS = {"both", "positive_to_negative", "negative_to_positive"}

DEFAULT_EVENT_SETTINGS: dict[str, Any] = {
    "zone_entry": {
        "enabled": True,
        "categories": ["person", "vehicle"],
        "min_confidence": 0.5,
        "min_motion": 0.015,
        "min_track_frames": 3,
        "cooldown_seconds": 3.0,
    },
    "line_crossing": {
        "enabled": True,
        "categories": ["vehicle"],
        "min_confidence": 0.7,
        "min_motion": 0.05,
        "min_side_distance": 0.02,
        "stable_side_frames": 2,
        "confirm_frames": 2,
        "rearm_distance": 0.06,
        "min_track_frames": 5,
        "cooldown_seconds": 6.0,
        "direction": "both",
    },
    "loitering": {
        "enabled": True,
        "categories": ["person"],
        "min_confidence": 0.55,
        "min_track_frames": 5,
        "cooldown_seconds": 10.0,
        "duration_seconds": float(settings.loitering_seconds),
    },
}


def normalize_event_settings(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = deepcopy(DEFAULT_EVENT_SETTINGS)
    raw = dict((metadata or {}).get("event_settings", {}))
    for rule_name, defaults in DEFAULT_EVENT_SETTINGS.items():
        incoming = raw.get(rule_name, {})
        if not isinstance(incoming, dict):
            continue
        merged = dict(defaults)
        merged.update(incoming)
        merged["enabled"] = bool(merged.get("enabled", defaults["enabled"]))
        categories = [str(item).strip().lower() for item in merged.get("categories", []) if str(item).strip()]
        categories = [item for item in categories if item in ALLOWED_CATEGORIES]
        merged["categories"] = categories or list(defaults["categories"])
        merged["min_confidence"] = max(0.05, min(0.99, float(merged.get("min_confidence", defaults["min_confidence"]))))
        merged["min_track_frames"] = max(1, int(merged.get("min_track_frames", defaults["min_track_frames"])))
        merged["cooldown_seconds"] = max(0.0, float(merged.get("cooldown_seconds", defaults["cooldown_seconds"])))
        if rule_name == "zone_entry":
            merged["min_motion"] = max(0.0, float(merged.get("min_motion", defaults["min_motion"])))
        elif rule_name == "line_crossing":
            merged["min_motion"] = max(0.0, float(merged.get("min_motion", defaults["min_motion"])))
            merged["min_side_distance"] = max(0.0, float(merged.get("min_side_distance", defaults["min_side_distance"])))
            merged["stable_side_frames"] = max(1, int(merged.get("stable_side_frames", defaults["stable_side_frames"])))
            merged["confirm_frames"] = max(1, int(merged.get("confirm_frames", defaults["confirm_frames"])))
            merged["rearm_distance"] = max(0.0, float(merged.get("rearm_distance", defaults["rearm_distance"])))
            direction = str(merged.get("direction", defaults["direction"])).strip().lower()
            merged["direction"] = direction if direction in ALLOWED_DIRECTIONS else defaults["direction"]
        elif rule_name == "loitering":
            merged["duration_seconds"] = max(1.0, float(merged.get("duration_seconds", defaults["duration_seconds"])))
        normalized[rule_name] = merged
    return normalized

