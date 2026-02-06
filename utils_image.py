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


@dataclass(frozen=True)
class ImageQuality:
    """Assessment of image quality for better detection feedback."""
    blur_score: float  # 0-1, higher = sharper
    brightness_score: float  # 0-1, optimal around 0.5
    contrast_score: float  # 0-1, higher = better contrast
    subject_size_score: float  # 0-1, based on mask coverage
    overall_quality: str  # "good", "acceptable", "poor"
    issues: list  # List of detected issues
    recommendations: list  # Suggestions for better capture


def assess_image_quality(image_bgr: np.ndarray, mask_coverage: float) -> ImageQuality:
    """
    Assess image quality to provide actionable feedback for blurry or distant images.
    This helps users understand why detection might fail and how to improve it.
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    
    # Blur detection using Laplacian variance
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Normalize blur score (typical range 0-2000+, we normalize to 0-1)
    blur_score = min(1.0, laplacian_var / 500.0)
    
    # Brightness assessment
    brightness = np.mean(gray) / 255.0
    # Optimal brightness around 0.4-0.6, penalize too dark/bright
    if 0.3 <= brightness <= 0.7:
        brightness_score = 1.0
    elif brightness < 0.3:
        brightness_score = brightness / 0.3
    else:
        brightness_score = (1.0 - brightness) / 0.3
    brightness_score = max(0.0, min(1.0, brightness_score))
    
    # Contrast assessment using standard deviation
    contrast = np.std(gray) / 128.0  # Normalize by half range
    contrast_score = min(1.0, contrast)
    
    # Subject size score based on mask coverage
    # Good coverage: 5-50%, too small < 5%, too large > 50%
    if 0.05 <= mask_coverage <= 0.50:
        subject_size_score = 1.0
    elif mask_coverage < 0.05:
        subject_size_score = mask_coverage / 0.05
    else:
        subject_size_score = max(0.3, 1.0 - (mask_coverage - 0.50) / 0.50)
    subject_size_score = max(0.0, min(1.0, subject_size_score))
    
    # Collect issues and recommendations
    issues = []
    recommendations = []
    
    if blur_score < 0.3:
        issues.append("Image appears blurry")
        recommendations.append("Hold the camera steady or tap to focus")
    elif blur_score < 0.5:
        issues.append("Image is slightly out of focus")
        recommendations.append("Try focusing on the fruit/leaf")
    
    if brightness < 0.25:
        issues.append("Image is too dark")
        recommendations.append("Move to better lighting or use flash")
    elif brightness > 0.75:
        issues.append("Image is overexposed")
        recommendations.append("Reduce direct light or move to shade")
    
    if contrast_score < 0.3:
        issues.append("Low contrast detected")
        recommendations.append("Ensure the fruit/leaf stands out from background")
    
    if mask_coverage < 0.03:
        issues.append("Subject appears too far or small")
        recommendations.append("Move closer to the Bignay fruit or leaf")
    elif mask_coverage > 0.60:
        issues.append("Subject is too close")
        recommendations.append("Move back slightly to capture the whole fruit/leaf")
    
    # Calculate overall quality
    avg_score = (blur_score + brightness_score + contrast_score + subject_size_score) / 4.0
    
    if avg_score >= 0.6 and len(issues) <= 1:
        overall_quality = "good"
    elif avg_score >= 0.35 or len(issues) <= 2:
        overall_quality = "acceptable"
    else:
        overall_quality = "poor"
    
    return ImageQuality(
        blur_score=round(blur_score, 3),
        brightness_score=round(brightness_score, 3),
        contrast_score=round(contrast_score, 3),
        subject_size_score=round(subject_size_score, 3),
        overall_quality=overall_quality,
        issues=issues,
        recommendations=recommendations
    )


def enhance_image_for_detection(image_bgr: np.ndarray) -> np.ndarray:
    """
    Apply image enhancement to improve detection for blurry/distant/poor quality images.
    This preprocessing helps the model recognize Bignay even in suboptimal conditions.
    """
    enhanced = image_bgr.copy()
    
    # 1. Denoise while preserving edges (helps with blurry images)
    enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)
    
    # 2. Adaptive histogram equalization for better contrast
    # Convert to LAB color space for better color preservation
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to L channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    
    # Merge channels back
    lab = cv2.merge([l_channel, a_channel, b_channel])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    
    # 3. Slight sharpening to improve edge detection
    kernel = np.array([[-1, -1, -1],
                       [-1, 9.5, -1],
                       [-1, -1, -1]]) / 1.5
    enhanced = cv2.filter2D(enhanced, -1, kernel)
    
    # Ensure values are in valid range
    enhanced = np.clip(enhanced, 0, 255).astype(np.uint8)
    
    return enhanced


def safe_json(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(v) for v in obj]
    return str(obj)
