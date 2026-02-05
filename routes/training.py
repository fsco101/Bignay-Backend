"""
Training Routes
===============
API endpoints for training data contributions and model improvement.
"""

from flask import Blueprint, jsonify, request

from training_service import get_training_service, FRUIT_CLASSES, LEAF_CLASSES

training_bp = Blueprint("training", __name__, url_prefix="/api/training")


@training_bp.get("/info")
def training_info():
    """Get information about training contributions."""
    service = get_training_service()
    
    return jsonify({
        "available": service.is_available(),
        "fruit_classes": FRUIT_CLASSES,
        "leaf_classes": LEAF_CLASSES,
        "description": "Contribute to model training by confirming or correcting classifications",
    })


@training_bp.get("/stats")
def training_stats():
    """Get training contribution statistics."""
    service = get_training_service()
    stats = service.get_training_stats()
    return jsonify(stats)


@training_bp.post("/contribute")
def contribute_training_data():
    """
    Submit a training contribution.
    
    Expected JSON body:
    {
        "subject": "fruit" or "leaf",
        "label": "ripe", "unripe", etc.,
        "image": "data:image/jpeg;base64,...",
        "original_prediction": "what model predicted",
        "original_confidence": 0.85,
        "is_correction": true/false,
        "user_id": "optional user id"
    }
    """
    service = get_training_service()
    
    if not service.is_available():
        return jsonify({
            "success": False,
            "error": "Training service not available. MongoDB may not be configured.",
        }), 503

    try:
        body = request.get_json(force=True, silent=False)
    except Exception as e:
        return jsonify({"success": False, "error": f"Invalid JSON: {str(e)}"}), 400

    # Validate required fields
    required = ["subject", "label", "image", "original_prediction", "original_confidence"]
    for field in required:
        if field not in body:
            return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

    result = service.save_training_contribution(
        subject=body["subject"],
        label=body["label"],
        image_data_url=body["image"],
        original_prediction=body["original_prediction"],
        original_confidence=body["original_confidence"],
        is_correction=body.get("is_correction", False),
        user_id=body.get("user_id"),
        save_to_dataset=body.get("save_to_dataset", True),
    )

    if result["success"]:
        return jsonify(result), 201
    else:
        return jsonify(result), 400


@training_bp.get("/history")
def contribution_history():
    """Get recent training contributions."""
    service = get_training_service()
    
    limit = request.args.get("limit", 50, type=int)
    subject = request.args.get("subject")
    
    history = service.get_contribution_history(limit=limit, subject=subject)
    return jsonify({
        "contributions": history,
        "count": len(history),
    })


@training_bp.post("/retrain")
def trigger_retrain():
    """
    Trigger model retraining (admin endpoint).
    Note: Actual retraining is done via train_model.py script.
    """
    service = get_training_service()
    result = service.trigger_retrain()
    
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code
