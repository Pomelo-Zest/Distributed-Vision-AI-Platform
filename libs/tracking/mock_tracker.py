from __future__ import annotations

from dataclasses import dataclass
from math import sin

from libs.schemas.messages import Detection


@dataclass(slots=True)
class TrackState:
    track_id: str
    x: float
    y: float
    vx: float
    vy: float


class MockTracker:
    def __init__(self) -> None:
        self._tracks: dict[str, list[TrackState]] = {}

    def infer(self, camera_id: str, frame_id: int) -> list[Detection]:
        states = self._tracks.setdefault(camera_id, self._seed_tracks(camera_id))
        detections: list[Detection] = []
        for index, state in enumerate(states):
            state.x = (state.x + state.vx + 0.01 * sin(frame_id / (4 + index))) % 1.0
            state.y = (state.y + state.vy + 0.01 * sin(frame_id / (5 + index))) % 1.0
            width = 0.08 + 0.01 * index
            height = 0.18
            x1 = max(0.0, state.x - width / 2)
            y1 = max(0.0, state.y - height / 2)
            x2 = min(1.0, state.x + width / 2)
            y2 = min(1.0, state.y + height / 2)
            detections.append(
                Detection(
                    confidence=0.78 + 0.03 * ((frame_id + index) % 4),
                    bbox=[round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    centroid=[round(state.x, 4), round(state.y, 4)],
                    track_id=state.track_id,
                )
            )
        return detections

    def _seed_tracks(self, camera_id: str) -> list[TrackState]:
        base = sum(ord(char) for char in camera_id) % 5
        return [
            TrackState(track_id=f"{camera_id}-t1", x=0.15 + 0.02 * base, y=0.15, vx=0.015, vy=0.01),
            TrackState(track_id=f"{camera_id}-t2", x=0.75, y=0.20 + 0.03 * base, vx=-0.012, vy=0.008),
        ]

