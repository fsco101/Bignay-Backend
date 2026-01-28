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
)

# Import route blueprints
from routes import auth_bp, users_bp, products_bp, orders_bp, reviews_bp

settings = get_settings()

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"

app = Flask(__name__)

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
            
            print("✓ MongoDB collections initialized successfully")
        except Exception as e:
            print(f"✗ Failed to initialize MongoDB: {e}")
            app.config['db_users'] = None
            app.config['db_products'] = None
            app.config['db_orders'] = None
            app.config['db_reviews'] = None
    else:
        app.config['db_users'] = None
        app.config['db_products'] = None
        app.config['db_orders'] = None
        app.config['db_reviews'] = None
        print("✗ MongoDB URI not configured - marketplace features will be disabled")

# Initialize database
init_database()

# Register route blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(reviews_bp)

store = PredictionStore(settings.mongodb_uri, settings.mongodb_db, settings.mongodb_collection)

# If you have trained models, drop them in backend/model/ and set FRUIT_MODEL_PATH / LEAF_MODEL_PATH
fruit_model = KerasClassifier(settings.fruit_model_path, classes=["good", "mold", "overripe", "ripe", "unripe"])
leaf_model = KerasClassifier(settings.leaf_model_path, classes=["healthy", "mold"])

fruit_fallback = HeuristicFruitClassifier()
leaf_fallback = HeuristicLeafClassifier()


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

    features = extract_features(image_bgr)
    mold_heuristic = _mold_flag_from_image(image_bgr)

    # Model inference (if models exist) else fallback heuristics
    input_tensor = resize_for_model(image_bgr, 224)

    fruit_pred = None
    leaf_pred = None

    if subject == "fruit":
        if fruit_model.available():
            fruit_pred = fruit_model.predict(input_tensor)
        else:
            fruit_pred = fruit_fallback.predict_from_features(features)
    else:
        if leaf_model.available():
            leaf_pred = leaf_model.predict(input_tensor)
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

    rec = recommend(ripeness_stage=ripeness_stage, mold_present=mold_present, quality=quality)

    response = {
        # Backwards-compatible fields used by existing frontend
        "result": (fruit_obj or leaf_obj or {}).get("class", "unknown"),
        "confidence": float((fruit_obj or leaf_obj or {}).get("confidence", 0.0)),

        # Extended fields
        "subject": subject,
        "image_sha256": image_sha256,
        "fruit": fruit_obj,
        "leaf": leaf_obj,
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
        },
        "debug": {
            "mold_heuristic": mold_heuristic,
            "fruit_model_available": fruit_model.available(),
            "leaf_model_available": leaf_model.available(),
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
