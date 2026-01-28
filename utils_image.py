from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageFeatures:
    image_sha256: str
    color_hsv_mean: list[float]
    color_lab_mean: list[float]
    size_px_diameter: float | None
    mask_coverage: float


def decode_data_url(data_url: str) -> bytes:
    if "," not in data_url:
        raise ValueError("Invalid data URL")
    return base64.b64decode(data_url.split(",", 1)[1])


def decode_image_bytes(img_bytes: bytes) -> np.ndarray:
    np_img = np.frombuffer(img_bytes, np.uint8)
    image = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image")
    return image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _largest_contour_mask(image_bgr: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image_bgr.shape[:2]

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    # Combine saturation and value to get a decent foreground mask in many webcam setups.
    gray = cv2.addWeighted(s, 0.6, v, 0.4, 0)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)

    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = np.ones((7, 7), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros((h, w), dtype=np.uint8), 0.0

    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=-1)

    coverage = area / float(h * w)
    return mask, coverage


def extract_features(image_bgr: np.ndarray) -> ImageFeatures:
    h, w = image_bgr.shape[:2]
    mask, coverage = _largest_contour_mask(image_bgr)

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)

    if coverage > 0.01:
        mask_bool = mask.astype(bool)
        hsv_pixels = hsv[mask_bool]
        lab_pixels = lab[mask_bool]
    else:
        hsv_pixels = hsv.reshape(-1, 3)
        lab_pixels = lab.reshape(-1, 3)

    hsv_mean = hsv_pixels.mean(axis=0).astype(float).tolist()
    lab_mean = lab_pixels.mean(axis=0).astype(float).tolist()

    size_px_diameter: float | None = None
    if coverage > 0.01:
        area = float(mask.sum() / 255.0)
        # Equivalent circular diameter from area
        size_px_diameter = float(np.sqrt(4.0 * area / np.pi))

    # Hash for dedupe/logging (not the image bytes themselves)
    # Caller should pass original bytes for accurate hash; here we hash a JPEG-encoded version.
    ok, encoded = cv2.imencode(".jpg", image_bgr)
    if not ok:
        encoded_bytes = image_bgr.tobytes()
    else:
        encoded_bytes = encoded.tobytes()

    return ImageFeatures(
        image_sha256=sha256_bytes(encoded_bytes),
        color_hsv_mean=hsv_mean,
        color_lab_mean=lab_mean,
        size_px_diameter=size_px_diameter,
        mask_coverage=float(coverage),
    )


def resize_for_model(image_bgr: np.ndarray, size: int = 224) -> np.ndarray:
    image = cv2.resize(image_bgr, (size, size), interpolation=cv2.INTER_AREA)
    image = image.astype(np.float32) / 255.0
    return np.expand_dims(image, axis=0)


def safe_json(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(v) for v in obj]
    return str(obj)
