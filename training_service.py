"""
Training Service for Bignay Classification
==========================================
Handles user-contributed training data and model retraining.

This service allows:
1. Users to contribute labeled images for training
2. Automatic saving of training images to the dataset
3. Triggering model retraining when enough new data is collected
"""

from __future__ import annotations

import base64
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pymongo import MongoClient

from config import BACKEND_DIR, get_settings

settings = get_settings()

# Paths for training data
DATASET_DIR = BACKEND_DIR.parent / "dataset"
FRUIT_DATASET_DIR = DATASET_DIR / "fruit"
LEAF_DATASET_DIR = DATASET_DIR / "leaf"

# Valid classes for each subject
FRUIT_CLASSES = ["good", "mold", "overripe", "ripe", "unripe"]
LEAF_CLASSES = ["healthy", "mold"]

# Minimum contributions before auto-retrain (configurable)
MIN_CONTRIBUTIONS_FOR_RETRAIN = int(os.getenv("MIN_CONTRIBUTIONS_FOR_RETRAIN", "50"))


class TrainingService:
    """Service to manage training data contributions and model retraining."""

    def __init__(self, mongodb_uri: str | None, db_name: str):
        self._client = None
        self._db = None
        self._training_collection = None
        self._stats_collection = None

        if mongodb_uri:
            try:
                self._client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
                self._db = self._client[db_name]
                self._training_collection = self._db["training_contributions"]
                self._stats_collection = self._db["training_stats"]
                
                # Create indexes
                self._training_collection.create_index("subject")
                self._training_collection.create_index("label")
                self._training_collection.create_index("created_at")
                self._training_collection.create_index("used_for_training")
                
                print("✓ Training service initialized with MongoDB")
            except Exception as e:
                print(f"✗ Training service MongoDB error: {e}")
                self._client = None

    def is_available(self) -> bool:
        """Check if the training service is available."""
        return self._training_collection is not None

    def save_training_contribution(
        self,
        subject: str,
        label: str,
        image_data_url: str,
        original_prediction: str,
        original_confidence: float,
        is_correction: bool,
        user_id: str | None = None,
        save_to_dataset: bool = True,
    ) -> dict[str, Any]:
        """
        Save a user's training contribution.
        
        Args:
            subject: 'fruit' or 'leaf'
            label: The confirmed/corrected label
            image_data_url: Base64 data URL of the image
            original_prediction: What the model predicted
            original_confidence: Model's confidence in original prediction
            is_correction: True if user corrected the prediction
            user_id: Optional user identifier
            save_to_dataset: Whether to save image to dataset folder
            
        Returns:
            Dict with status and contribution details
        """
        # Validate subject and label
        if subject not in {"fruit", "leaf"}:
            return {"success": False, "error": "Invalid subject"}
        
        valid_classes = FRUIT_CLASSES if subject == "fruit" else LEAF_CLASSES
        if label not in valid_classes:
            return {"success": False, "error": f"Invalid label '{label}' for {subject}"}

        # Decode image
        try:
            if "," in image_data_url:
                img_data = base64.b64decode(image_data_url.split(",", 1)[1])
            else:
                img_data = base64.b64decode(image_data_url)
            
            np_img = np.frombuffer(img_data, np.uint8)
            image = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
            
            if image is None:
                return {"success": False, "error": "Could not decode image"}
        except Exception as e:
            return {"success": False, "error": f"Image decode error: {str(e)}"}

        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"contrib_{timestamp}_{unique_id}.jpg"

        # Save to dataset folder if enabled
        dataset_path = None
        if save_to_dataset:
            dataset_base = FRUIT_DATASET_DIR if subject == "fruit" else LEAF_DATASET_DIR
            label_dir = dataset_base / label
            label_dir.mkdir(parents=True, exist_ok=True)
            
            dataset_path = label_dir / filename
            cv2.imwrite(str(dataset_path), image)

        # Create contribution record
        contribution = {
            "subject": subject,
            "label": label,
            "original_prediction": original_prediction,
            "original_confidence": original_confidence,
            "is_correction": is_correction,
            "user_id": user_id,
            "filename": filename,
            "dataset_path": str(dataset_path) if dataset_path else None,
            "used_for_training": False,
            "created_at": datetime.now(timezone.utc),
        }

        # Save to MongoDB if available
        contribution_id = None
        if self._training_collection is not None:
            try:
                result = self._training_collection.insert_one(contribution)
                contribution_id = str(result.inserted_id)
                
                # Update stats
                self._update_stats(subject, label, is_correction)
            except Exception as e:
                print(f"MongoDB save error: {e}")

        return {
            "success": True,
            "contribution_id": contribution_id,
            "filename": filename,
            "saved_to_dataset": dataset_path is not None,
            "message": "Thank you for your contribution! This helps improve the model.",
        }

    def _update_stats(self, subject: str, label: str, is_correction: bool):
        """Update training statistics."""
        if self._stats_collection is None:
            return

        try:
            # Update global stats
            self._stats_collection.update_one(
                {"_id": "global"},
                {
                    "$inc": {
                        "total_contributions": 1,
                        "total_corrections": 1 if is_correction else 0,
                        f"contributions_by_subject.{subject}": 1,
                        f"contributions_by_label.{subject}.{label}": 1,
                    },
                    "$set": {"last_contribution_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )
        except Exception as e:
            print(f"Stats update error: {e}")

    def get_training_stats(self) -> dict[str, Any]:
        """Get training contribution statistics."""
        if self._stats_collection is None:
            return {
                "available": False,
                "message": "Training stats not available (MongoDB not configured)",
            }

        try:
            stats = self._stats_collection.find_one({"_id": "global"})
            if not stats:
                return {
                    "available": True,
                    "total_contributions": 0,
                    "total_corrections": 0,
                    "contributions_by_subject": {},
                    "contributions_by_label": {},
                    "pending_for_training": 0,
                }

            # Count pending contributions
            pending = self._training_collection.count_documents({"used_for_training": False})

            return {
                "available": True,
                "total_contributions": stats.get("total_contributions", 0),
                "total_corrections": stats.get("total_corrections", 0),
                "contributions_by_subject": stats.get("contributions_by_subject", {}),
                "contributions_by_label": stats.get("contributions_by_label", {}),
                "pending_for_training": pending,
                "min_for_retrain": MIN_CONTRIBUTIONS_FOR_RETRAIN,
                "ready_for_retrain": pending >= MIN_CONTRIBUTIONS_FOR_RETRAIN,
                "last_contribution_at": stats.get("last_contribution_at"),
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_contribution_history(self, limit: int = 50, subject: str | None = None) -> list[dict]:
        """Get recent training contributions."""
        if self._training_collection is None:
            return []

        try:
            query = {}
            if subject:
                query["subject"] = subject

            cursor = self._training_collection.find(
                query,
                {"_id": 1, "subject": 1, "label": 1, "original_prediction": 1, 
                 "is_correction": 1, "created_at": 1}
            ).sort("created_at", -1).limit(limit)

            return [
                {
                    "id": str(doc["_id"]),
                    "subject": doc["subject"],
                    "label": doc["label"],
                    "original_prediction": doc.get("original_prediction"),
                    "is_correction": doc.get("is_correction", False),
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                }
                for doc in cursor
            ]
        except Exception as e:
            print(f"Get history error: {e}")
            return []

    def trigger_retrain(self) -> dict[str, Any]:
        """
        Trigger model retraining with new contributions.
        This is a placeholder - actual retraining would be done via a separate process.
        """
        if self._training_collection is None:
            return {"success": False, "error": "MongoDB not configured"}

        try:
            # Count pending contributions
            pending = self._training_collection.count_documents({"used_for_training": False})
            
            if pending < MIN_CONTRIBUTIONS_FOR_RETRAIN:
                return {
                    "success": False,
                    "error": f"Not enough contributions. Need {MIN_CONTRIBUTIONS_FOR_RETRAIN}, have {pending}",
                    "pending": pending,
                    "required": MIN_CONTRIBUTIONS_FOR_RETRAIN,
                }

            # Mark contributions as used (in real implementation, this would happen after successful training)
            # For now, we just return info about what would be trained
            
            return {
                "success": True,
                "message": f"Retraining would use {pending} new contributions",
                "pending": pending,
                "note": "Actual retraining requires running train_model.py manually or via scheduled job",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Create singleton instance
_training_service: TrainingService | None = None


def get_training_service() -> TrainingService:
    """Get or create the training service singleton."""
    global _training_service
    if _training_service is None:
        _training_service = TrainingService(settings.mongodb_uri, settings.mongodb_db)
    return _training_service
