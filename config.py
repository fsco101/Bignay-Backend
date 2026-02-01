from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

# Load .env file (try backend folder first, then repo root)
_env_loaded = False
try:
    from dotenv import load_dotenv  # type: ignore

    # Try backend folder first
    backend_env = BACKEND_DIR / ".env"
    if backend_env.exists():
        load_dotenv(backend_env, override=True)
        _env_loaded = True
        print(f"[Config] Loaded .env from {backend_env}")
    else:
        # Fallback to repo root
        root_env = REPO_ROOT / ".env"
        if root_env.exists():
            load_dotenv(root_env, override=True)
            _env_loaded = True
            print(f"[Config] Loaded .env from {root_env}")
        else:
            print(f"[Config] Warning: No .env file found")
except ImportError:
    print("[Config] python-dotenv not installed, using system env vars")
except Exception as e:
    print(f"[Config] Error loading .env: {e}")


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None
    mongodb_db: str
    mongodb_collection: str

    host: str
    port: int
    debug: bool

    fruit_model_path: Path
    leaf_model_path: Path

    # If true, API will store base64 images in MongoDB (not recommended)
    store_images_in_db: bool
    
    # Cloudinary settings for product images
    cloudinary_cloud_name: str | None
    cloudinary_api_key: str | None
    cloudinary_api_secret: str | None
    
    # JWT Secret for auth tokens
    jwt_secret: str
    
    # PayMongo settings for online payments
    paymongo_secret_key: str | None
    paymongo_public_key: str | None


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_settings() -> Settings:
    mongodb_uri = os.getenv("MONGODB_URI")

    return Settings(
        mongodb_uri=mongodb_uri,
        mongodb_db=os.getenv("MONGODB_DB", "bignay"),
        mongodb_collection=os.getenv("MONGODB_COLLECTION", "predictions"),
        host=os.getenv("HOST", "127.0.0.1"),
        port=_get_int("PORT", 5000),
        debug=_get_bool("FLASK_DEBUG", True),
        fruit_model_path=Path(os.getenv("FRUIT_MODEL_PATH", str(BACKEND_DIR / "model" / "fruit_model.h5"))),
        leaf_model_path=Path(os.getenv("LEAF_MODEL_PATH", str(BACKEND_DIR / "model" / "leaf_model.h5"))),
        store_images_in_db=_get_bool("STORE_IMAGES_IN_DB", False),
        cloudinary_cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        cloudinary_api_key=os.getenv("CLOUDINARY_API_KEY"),
        cloudinary_api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        jwt_secret=os.getenv("JWT_SECRET", "bignay-secret-key-change-in-production"),
        paymongo_secret_key=os.getenv("PAYMONGO_SECRET_KEY"),
        paymongo_public_key=os.getenv("PAYMONGO_PUBLIC_KEY"),
    )
