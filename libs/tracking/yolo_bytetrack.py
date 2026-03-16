from __future__ import annotations

from pathlib import Path

import cv2

from libs.common.config import settings
from libs.schemas.messages import Detection

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - depends on installed runtime extras
    YOLO = None


def _parse_classes() -> list[int] | None:
    raw = settings.yolo_classes.strip()
    if not raw:
        return None
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


class YOLOByteTracker:
    def __init__(self) -> None:
        self._models: dict[str, YOLO] = {}
        self._classes = _parse_classes()

    def infer(self, camera_id: str, frame_path: str) -> list[Detection]:
        model = self._model_for(camera_id)
        frame = cv2.imread(frame_path)
        if frame is None:
            raise RuntimeError(f"failed to load frame from {frame_path}")
        height, width = frame.shape[:2]
        results = model.track(
            source=frame,
            persist=True,
            tracker=settings.yolo_tracker_config,
            conf=settings.yolo_confidence,
            iou=settings.yolo_iou,
            imgsz=settings.yolo_image_size,
            classes=self._classes,
            device=settings.yolo_device or None,
            verbose=False,
        )
        if not results:
            return []
        result = results[0]
        boxes = result.boxes
        if boxes is None or boxes.xyxy is None:
            return []

        names = result.names or model.names
        ids = boxes.id.tolist() if boxes.id is not None else [None] * len(boxes)
        classes = boxes.cls.tolist() if boxes.cls is not None else [0] * len(boxes)
        confidences = boxes.conf.tolist() if boxes.conf is not None else [0.0] * len(boxes)
        xyxy_boxes = boxes.xyxy.tolist()

        detections: list[Detection] = []
        for index, xyxy in enumerate(xyxy_boxes):
            x1, y1, x2, y2 = xyxy
            track_id_value = ids[index]
            class_index = int(classes[index])
            class_name = self._class_name(names, class_index)
            detections.append(
                Detection(
                    class_name=class_name,
                    confidence=round(float(confidences[index]), 4),
                    bbox=[
                        round(max(0.0, min(1.0, x1 / width)), 4),
                        round(max(0.0, min(1.0, y1 / height)), 4),
                        round(max(0.0, min(1.0, x2 / width)), 4),
                        round(max(0.0, min(1.0, y2 / height)), 4),
                    ],
                    centroid=[
                        round(max(0.0, min(1.0, ((x1 + x2) / 2) / width)), 4),
                        round(max(0.0, min(1.0, ((y1 + y2) / 2) / height)), 4),
                    ],
                    track_id=str(int(track_id_value)) if track_id_value is not None else f"{camera_id}-det-{index}",
                )
            )
        return detections

    def _model_for(self, camera_id: str) -> YOLO:
        if YOLO is None:
            raise RuntimeError(
                "Ultralytics is not installed. Install project dependencies and ensure ultralytics is available."
            )
        model = self._models.get(camera_id)
        if model is not None:
            return model
        model_path = Path(settings.yolo_model_path)
        source = str(model_path if model_path.exists() else settings.yolo_model_path)
        model = YOLO(source)
        self._models[camera_id] = model
        return model

    @staticmethod
    def _class_name(names: dict[int, str] | list[str], class_index: int) -> str:
        if isinstance(names, dict):
            return str(names.get(class_index, class_index))
        if 0 <= class_index < len(names):
            return str(names[class_index])
        return str(class_index)
