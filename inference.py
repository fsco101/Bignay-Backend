from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from utils_image import ImageFeatures


@dataclass(frozen=True)
class ClassifierResult:
    class_name: str
    confidence: float


class KerasClassifier:
    def __init__(self, model_path: Path, classes: list[str]):
        self._model_path = model_path
        self._classes = classes
        self._model = None

    @property
    def classes(self) -> list[str]:
        return list(self._classes)

    def available(self) -> bool:
        return self._model_path.exists()

    def _load(self):
        if self._model is not None:
            return
        import tensorflow as tf  # lazy import

        self._model = tf.keras.models.load_model(str(self._model_path))

    def predict(self, input_tensor: np.ndarray) -> ClassifierResult:
        self._load()
        preds = self._model.predict(input_tensor, verbose=0)[0]
        idx = int(np.argmax(preds))
        return ClassifierResult(class_name=self._classes[idx], confidence=float(np.max(preds)))


class HeuristicFruitClassifier:
    """Fallback classifier when no trained model exists.

    This is NOT a real ML model. It provides reasonable demo output for UI/API wiring.
    Replace it with a trained model as soon as possible.
    """

    def __init__(self):
        self._classes = ["unripe", "ripe", "overripe", "mold"]

    def available(self) -> bool:
        return True

    @property
    def classes(self) -> list[str]:
        return list(self._classes)

    def predict_from_features(self, features: ImageFeatures) -> ClassifierResult:
        # Very rough heuristics:
        # - red/purple-ish -> ripe
        # - low brightness -> overripe
        # - many dark+low-sat pixels -> mold (handled in app)

        h, s, v = features.color_hsv_mean

        if v < 60:
            return ClassifierResult("overripe", 0.55)

        # Hue for red wraps around in HSV; OpenCV hue range is [0..179].
        is_reddish = (h <= 10) or (h >= 160)
        if is_reddish and s > 60:
            return ClassifierResult("ripe", 0.60)

        if s < 35:
            return ClassifierResult("unripe", 0.40)

        return ClassifierResult("unripe", 0.55)


class HeuristicLeafClassifier:
    def __init__(self):
        self._classes = ["healthy", "mold"]

    def available(self) -> bool:
        return True

    @property
    def classes(self) -> list[str]:
        return list(self._classes)

    def predict_from_features(self, features: ImageFeatures) -> ClassifierResult:
        _, s, v = features.color_hsv_mean

        # crude guess: very dark or desaturated might indicate disease/mold
        if v < 70 and s < 80:
            return ClassifierResult("mold", 0.55)
        return ClassifierResult("healthy", 0.60)
