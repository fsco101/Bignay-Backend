from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient

from config import BACKEND_DIR, get_settings
from db import PredictionStore
from inference import (
    HeuristicFruitClassifier,
    HeuristicLeafClassifier,
    KerasClassifier,
)
from recommendation import recommend
from utils_image import (
    decode_data_url,
    decode_image_bytes,
    extract_features,
    resize_for_model,
    safe_json,
    sha256_bytes,
    assess_image_quality,
    enhance_image_for_detection,
)

# Import route blueprints
from routes import auth_bp, users_bp, products_bp, orders_bp, reviews_bp, chatbot_bp
from routes.payments import payments_bp
from routes.analytics import analytics_bp
from routes.training import training_bp
from routes.forum import forum_bp

settings = get_settings()

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

app = Flask(__name__)

# Disable strict slashes to prevent redirects that lose auth headers
app.url_map.strict_slashes = False

# Set max content length to 50MB to handle large image uploads
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# Configure CORS to allow connections from any origin in development
# This is essential for mobile apps to connect to the backend
# Note: supports_credentials=False when origins="*" (CORS spec requirement)
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        "allow_headers": ["Content-Type", "Authorization", "Accept", "X-Requested-With"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": False,
        "max_age": 3600
    }
})

# Initialize MongoDB collections for new features
def init_database():
    """Initialize MongoDB collections and store in app config"""
    if settings.mongodb_uri:
        try:
            client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
            db = client[settings.mongodb_db]
            
            # Store collections in app config for routes to access
            app.config['db_users'] = db['users']
            app.config['db_products'] = db['products']
            app.config['db_orders'] = db['orders']
            app.config['db_reviews'] = db['reviews']
            
            # Create indexes for better performance
            app.config['db_users'].create_index('email', unique=True)
            app.config['db_products'].create_index([('name', 'text'), ('description', 'text')])
            app.config['db_products'].create_index('category')
            app.config['db_products'].create_index('is_active')
            app.config['db_orders'].create_index('user_id')
            app.config['db_orders'].create_index('status')
            app.config['db_reviews'].create_index('product_id')
            app.config['db_reviews'].create_index('user_id')
            
            # Forum collection
            app.config['db_forum'] = db['forum']
            app.config['db_forum'].create_index('category')
            app.config['db_forum'].create_index('is_published')
            app.config['db_forum'].create_index([('title', 'text'), ('content', 'text')])
            
            print("✓ MongoDB collections initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize MongoDB: {e}")
            app.config['db_users'] = None
            app.config['db_products'] = None
            app.config['db_orders'] = None
            app.config['db_reviews'] = None
            app.config['db_forum'] = None
    else:
        app.config['db_users'] = None
        app.config['db_products'] = None
        app.config['db_orders'] = None
        app.config['db_reviews'] = None
        app.config['db_forum'] = None
        print("✗ MongoDB URI not configured - marketplace features will be disabled")

# Initialize database
init_database()

# Initialize Cloudinary and verify configuration
def init_cloudinary():
    """Initialize and verify Cloudinary configuration"""
    from utils.cloudinary_helper import is_cloudinary_configured
    if is_cloudinary_configured():
        print("✓ Cloudinary configured successfully")
    else:
        print("✗ Cloudinary not configured - image upload will fail")
        print("  Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in .env")

init_cloudinary()

# Register route blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(reviews_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(training_bp)
app.register_blueprint(forum_bp)
app.register_blueprint(chatbot_bp)

store = PredictionStore(settings.mongodb_uri, settings.mongodb_db, settings.mongodb_collection)

# If you have trained models, drop them in backend/model/ and set FRUIT_MODEL_PATH / LEAF_MODEL_PATH
fruit_model = KerasClassifier(settings.fruit_model_path, classes=["good", "mold", "overripe", "ripe", "unripe"])
leaf_model = KerasClassifier(settings.leaf_model_path, classes=["healthy", "mold"])

fruit_fallback = HeuristicFruitClassifier()
leaf_fallback = HeuristicLeafClassifier()

# Confidence threshold for Bignay detection
# Balance between accepting blurry/distant bignay and rejecting non-bignay items
BIGNAY_CONFIDENCE_THRESHOLD = 0.45  # Main threshold for confident detection
MIN_CONFIDENCE_THRESHOLD = 0.30  # Minimum to consider - below this is definitely not bignay
# Very low threshold - image enhancement should help real bignay exceed this
ABSOLUTE_MIN_THRESHOLD = 0.25


def _is_bignay_image(confidence: float, features: Any, image_quality: Any = None) -> dict:
    """
    Determines if the image is likely a Bignay fruit or leaf based on:
    1. Model confidence score
    2. Image features (color analysis)
    3. Image quality assessment
    
    Balances accepting blurry/distant bignay while rejecting non-bignay items.
    Returns a dict with detection status, confidence level, and reason.
    """
    # Build quality context for better feedback
    quality_issues = image_quality.issues if image_quality else []
    quality_recommendations = image_quality.recommendations if image_quality else []
    overall_quality = image_quality.overall_quality if image_quality else "unknown"
    
    # Color-based validation for Bignay (check early to help with non-bignay rejection)
    # Bignay fruits: dark purple/red when ripe, green when unripe
    # Bignay leaves: green
    hsv_mean = features.color_hsv_mean
    h, s, v = hsv_mean
    
    # Define typical Bignay color ranges
    # HSV hue: Red ~0-15 or 165-180; Green ~35-85; Purple/Magenta ~130-165
    is_red_purple = (h <= 20) or (h >= 130)  # Red, purple, magenta range
    is_green = (35 <= h <= 90)  # Green range for unripe or leaves
    is_typical_bignay_color = is_red_purple or is_green
    
    # Detect clearly non-bignay colors (orange, yellow, bright blue, etc.)
    is_orange_yellow = (20 < h < 35) and s > 50  # Orange/yellow fruits
    is_blue_cyan = (90 < h < 130) and s > 40  # Blue/cyan - not bignay
    is_clearly_not_bignay_color = is_orange_yellow or is_blue_cyan
    
    # STEP 1: Absolute minimum threshold - below this is definitely not bignay
    if confidence < ABSOLUTE_MIN_THRESHOLD:
        reason = "The image does not appear to be a Bignay fruit or leaf."
        if quality_issues:
            reason += f" Issues: {', '.join(quality_issues[:2])}."
        else:
            reason += " Model confidence is very low."
        
        return {
            "is_bignay": False,
            "confidence_level": "very_low",
            "reason": reason,
            "quality_issues": quality_issues,
            "quality_recommendations": quality_recommendations
        }
    
    # STEP 2: Color-based rejection for clearly non-bignay colors
    if is_clearly_not_bignay_color and confidence < 0.60:
        # Strong color mismatch + low confidence = not bignay
        return {
            "is_bignay": False,
            "confidence_level": "color_mismatch",
            "reason": "The image color does not match Bignay. Bignay fruits are typically dark purple/red (ripe) or green (unripe).",
            "quality_issues": quality_issues,
            "quality_recommendations": ["Make sure you're scanning a Bignay fruit or leaf"]
        }
    
    # STEP 3: Check if below minimum threshold
    if confidence < MIN_CONFIDENCE_THRESHOLD:
        # Below minimum AND not a typical bignay color = reject
        if not is_typical_bignay_color:
            return {
                "is_bignay": False,
                "confidence_level": "low",
                "reason": "The image does not appear to be a Bignay. Color and confidence do not match expected values.",
                "quality_issues": quality_issues,
                "quality_recommendations": quality_recommendations
            }
        
        # Below minimum but has bignay-like color AND poor image quality = might be bignay
        if overall_quality in ["poor", "acceptable"] and is_typical_bignay_color:
            return {
                "is_bignay": True,
                "confidence_level": "very_low",
                "reason": "Detection confidence is very low, but color profile matches Bignay.",
                "quality_issues": quality_issues,
                "quality_recommendations": quality_recommendations,
                "warning": "Results may be inaccurate. Try capturing a clearer image."
            }
        
        # Below minimum, okay color, good quality = probably not bignay
        return {
            "is_bignay": False,
            "confidence_level": "low",
            "reason": "The image might not be a Bignay fruit or leaf. Please verify.",
            "quality_issues": quality_issues,
            "quality_recommendations": quality_recommendations
        }
    
    # STEP 4: Between MIN and BIGNAY threshold - accept with warnings
    if confidence < BIGNAY_CONFIDENCE_THRESHOLD:
        warning_msg = "Results may be less accurate due to low confidence."
        if quality_issues:
            warning_msg = f"Results may be affected by: {', '.join(quality_issues[:2])}."
        
        return {
            "is_bignay": True,
            "confidence_level": "low",
            "reason": None,
            "quality_issues": quality_issues,
            "quality_recommendations": quality_recommendations,
            "warning": warning_msg
        }
    
    # STEP 5: Above threshold - confident detection
    # Even with good confidence, warn if color is unusual
    if not is_typical_bignay_color and s > 60 and confidence < 0.65:
        return {
            "is_bignay": True,
            "confidence_level": "medium",
            "reason": None,
            "quality_issues": quality_issues,
            "quality_recommendations": ["Color appears unusual - verify if needed"],
            "warning": "Color profile is atypical for Bignay"
        }
    
    # Determine confidence level for good detections
    if confidence >= 0.70:
        confidence_level = "high"
    elif confidence >= 0.55:
        confidence_level = "medium"
    else:
        confidence_level = "low"
    
    return {
        "is_bignay": True,
        "confidence_level": confidence_level,
        "reason": None,
        "quality_issues": quality_issues,
        "quality_recommendations": quality_recommendations if confidence < 0.60 else []
    }


def _ripeness_stage_from_fruit_class(fruit_class: str) -> str | None:
    if fruit_class in {"unripe", "ripe", "overripe"}:
        return fruit_class
    if fruit_class == "good":
        return "ripe"
    return None


def _quality_from_fruit_class(fruit_class: str) -> str | None:
    if fruit_class in {"mold"}:
        return "reject"
    if fruit_class in {"good", "ripe"}:
        return "good"
    if fruit_class in {"unripe", "overripe"}:
        return "ok"
    return None


def _mold_flag_from_image(image_bgr) -> bool:
    # Conservative classical heuristic: if too many pixels are very dark and low saturation.
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    moldish = (v < 55) & (s < 85)
    ratio = float(np.mean(moldish))
    return ratio > 0.22


@app.get("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/design/style.css")
def serve_style():
    return send_from_directory(FRONTEND_DIR / "design", "style.css")


@app.get("/script.js")
def serve_script():
    return send_from_directory(FRONTEND_DIR, "script.js")


@app.get("/api-info")
def api_info():
    return jsonify(
        {
            "ok": True,
            "message": "Bignay backend is running.",
            "routes": {
                "ui": "/",
                "health": "/health",
                "predict": "/predict",
                "predictions": "/predictions",
            },
        }
    )


@app.get("/health")
def health():
    db_status = store.status()
    return jsonify(
        {
            "ok": True,
            "time": datetime.now(timezone.utc).isoformat(),
            "models": {
                "fruit": {"path": str(settings.fruit_model_path), "available": fruit_model.available()},
                "leaf": {"path": str(settings.leaf_model_path), "available": leaf_model.available()},
            },
            "db": {"enabled": db_status.enabled, "ok": db_status.ok, "message": db_status.message},
        }
    )

@app.post("/predict")
def predict():
    body: dict[str, Any] = request.get_json(force=True, silent=False)
    if "image" not in body:
        return jsonify({"error": "Missing 'image' field"}), 400

    subject = str(body.get("subject", "fruit")).strip().lower()
    if subject not in {"fruit", "leaf"}:
        return jsonify({"error": "Invalid 'subject'. Use 'fruit' or 'leaf'."}), 400

    data_url = body["image"]
    img_bytes = decode_data_url(data_url)
    image_sha256 = sha256_bytes(img_bytes)
    image_bgr = decode_image_bytes(img_bytes)

    # Extract features for quality assessment
    features = extract_features(image_bgr)
    
    # Assess image quality first
    image_quality = assess_image_quality(image_bgr, features.mask_coverage)
    
    # Apply image enhancement for better detection of blurry/distant images
    enhanced_image = enhance_image_for_detection(image_bgr)
    
    mold_heuristic = _mold_flag_from_image(image_bgr)

    # Model inference with enhanced image for better detection
    # Try both original and enhanced image, use the one with higher confidence
    input_tensor_original = resize_for_model(image_bgr, 224)
    input_tensor_enhanced = resize_for_model(enhanced_image, 224)

    fruit_pred = None
    leaf_pred = None
    used_enhanced = False

    if subject == "fruit":
        if fruit_model.available():
            # Try both original and enhanced, use best result
            pred_original = fruit_model.predict(input_tensor_original)
            pred_enhanced = fruit_model.predict(input_tensor_enhanced)
            
            # Use the prediction with higher confidence
            if pred_enhanced.confidence > pred_original.confidence:
                fruit_pred = pred_enhanced
                used_enhanced = True
            else:
                fruit_pred = pred_original
        else:
            fruit_pred = fruit_fallback.predict_from_features(features)
    else:
        if leaf_model.available():
            # Try both original and enhanced, use best result
            pred_original = leaf_model.predict(input_tensor_original)
            pred_enhanced = leaf_model.predict(input_tensor_enhanced)
            
            if pred_enhanced.confidence > pred_original.confidence:
                leaf_pred = pred_enhanced
                used_enhanced = True
            else:
                leaf_pred = pred_original
        else:
            leaf_pred = leaf_fallback.predict_from_features(features)

    # Build extended response
    fruit_obj: dict[str, Any] | None = None
    leaf_obj: dict[str, Any] | None = None

    if fruit_pred is not None:
        fruit_class = fruit_pred.class_name
        ripeness = _ripeness_stage_from_fruit_class(fruit_class)
        quality = _quality_from_fruit_class(fruit_class)
        fruit_obj = {
            "class": fruit_class,
            "confidence": fruit_pred.confidence,
            "ripeness_stage": ripeness,
            "mold_present": (fruit_class == "mold") or mold_heuristic,
            "quality": quality,
        }

    if leaf_pred is not None:
        leaf_class = leaf_pred.class_name
        leaf_obj = {
            "class": leaf_class,
            "confidence": leaf_pred.confidence,
            "mold_present": (leaf_class == "mold") or mold_heuristic,
        }

    mold_present = bool((fruit_obj and fruit_obj.get("mold_present")) or (leaf_obj and leaf_obj.get("mold_present")))
    ripeness_stage = fruit_obj.get("ripeness_stage") if fruit_obj else None
    quality = fruit_obj.get("quality") if fruit_obj else None

    # Check if the image is actually a Bignay (with image quality context)
    current_confidence = float((fruit_obj or leaf_obj or {}).get("confidence", 0.0))
    bignay_detection = _is_bignay_image(current_confidence, features, image_quality)

    rec = recommend(ripeness_stage=ripeness_stage, mold_present=mold_present, quality=quality)

    # If not detected as Bignay, modify the response accordingly
    if not bignay_detection["is_bignay"]:
        response = {
            "result": "not_bignay",
            "confidence": current_confidence,
            "subject": subject,
            "image_sha256": image_sha256,
            "fruit": None,
            "leaf": None,
            "is_bignay": False,
            "detection": bignay_detection,
            "image_quality": {
                "overall": image_quality.overall_quality,
                "blur_score": image_quality.blur_score,
                "brightness_score": image_quality.brightness_score,
                "contrast_score": image_quality.contrast_score,
                "subject_size_score": image_quality.subject_size_score,
                "issues": image_quality.issues,
                "recommendations": image_quality.recommendations,
            },
            "color": {
                "hsv_mean": features.color_hsv_mean,
                "lab_mean": features.color_lab_mean,
            },
            "size": {
                "px_diameter": features.size_px_diameter,
                "mask_coverage": features.mask_coverage,
            },
            "recommendation": {
                "primary": "Please scan a Bignay fruit or leaf",
                "alternatives": [],
                "reason": bignay_detection["reason"],
                "tips": image_quality.recommendations,
            },
            "debug": {
                "mold_heuristic": mold_heuristic,
                "fruit_model_available": fruit_model.available(),
                "leaf_model_available": leaf_model.available(),
                "detection_reason": bignay_detection["reason"],
                "used_enhanced_image": used_enhanced,
            },
            "time": datetime.now(timezone.utc).isoformat(),
        }
    else:
        # Build recommendation with quality-aware tips
        quality_tips = []
        if bignay_detection.get("warning"):
            quality_tips.append(bignay_detection["warning"])
        if image_quality.overall_quality != "good" and image_quality.recommendations:
            quality_tips.extend(image_quality.recommendations[:2])
        
        response = {
            # Backwards-compatible fields used by existing frontend
            "result": (fruit_obj or leaf_obj or {}).get("class", "unknown"),
            "confidence": current_confidence,
            "is_bignay": True,
            "detection": bignay_detection,

            # Extended fields
            "subject": subject,
            "image_sha256": image_sha256,
            "fruit": fruit_obj,
            "leaf": leaf_obj,
            "image_quality": {
                "overall": image_quality.overall_quality,
                "blur_score": image_quality.blur_score,
                "brightness_score": image_quality.brightness_score,
                "contrast_score": image_quality.contrast_score,
                "subject_size_score": image_quality.subject_size_score,
                "issues": image_quality.issues,
                "recommendations": image_quality.recommendations,
            },
            "color": {
                "hsv_mean": features.color_hsv_mean,
                "lab_mean": features.color_lab_mean,
            },
            "size": {
                "px_diameter": features.size_px_diameter,
                "mask_coverage": features.mask_coverage,
            },
            "recommendation": {
                "primary": rec.primary,
                "alternatives": rec.alternatives,
                "reason": rec.reason,
                "tips": quality_tips,
            },
            "debug": {
                "mold_heuristic": mold_heuristic,
                "fruit_model_available": fruit_model.available(),
                "leaf_model_available": leaf_model.available(),
                "used_enhanced_image": used_enhanced,
            },
            "time": datetime.now(timezone.utc).isoformat(),
        }

    # Store to MongoDB (metadata by default)
    record = {
        "subject": subject,
        "image_sha256": image_sha256,
        "result": response["result"],
        "confidence": response["confidence"],
        "fruit": fruit_obj,
        "leaf": leaf_obj,
        "color": response["color"],
        "size": response["size"],
        "recommendation": response["recommendation"],
        "debug": response["debug"],
        "client": {
            "ip": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
        },
    }
    if settings.store_images_in_db or bool(body.get("store_image")):
        record["image_data_url"] = data_url

    try:
        inserted_id = store.insert_prediction(safe_json(record))
        response["db"] = {"saved": bool(inserted_id), "id": inserted_id}
    except Exception as e:  # pylint: disable=broad-except
        response["db"] = {"saved": False, "error": str(e)}

    return jsonify(safe_json(response))


@app.get("/predictions")
def predictions():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    items = store.list_predictions(limit=limit)
    return jsonify({"items": items, "count": len(items)})

if __name__ == "__main__":
    import socket
    
    # Get local IP address
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    local_ip = get_local_ip()
    
    print("\n" + "="*60)
    print("🍇 BIGNAY BACKEND SERVER")
    print("="*60)
    print(f"\n✓ Server is starting...")
    print(f"  Host: {settings.host}")
    print(f"  Port: {settings.port}")
    print(f"  Debug: {settings.debug}")
    print(f"\n📱 Connect from your devices using:")
    print(f"  • Local:      http://localhost:{settings.port}")
    print(f"  • Network:    http://{local_ip}:{settings.port}")
    print(f"  • Emulator:   http://10.0.2.2:{settings.port} (Android)")
    print(f"\n📋 Available endpoints:")
    print(f"  • Health:     /health")
    print(f"  • Predict:    /predict")
    print(f"  • Auth:       /api/auth/*")
    print(f"  • Products:   /api/products/*")
    print(f"  • Orders:     /api/orders/*")
    print(f"  • Reviews:    /api/reviews/*")
    print("\n" + "="*60 + "\n")
    
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
