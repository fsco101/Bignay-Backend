"""
Firebase Admin SDK Helper
Handles Firebase Admin initialization and token verification
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any

# Try to import firebase_admin
try:
    import firebase_admin
    from firebase_admin import credentials, auth
    FIREBASE_ADMIN_AVAILABLE = True
    print("[FirebaseAdmin] ✓ firebase_admin package available")
except ImportError:
    FIREBASE_ADMIN_AVAILABLE = False
    print("[FirebaseAdmin] ✗ firebase_admin not installed - run: pip install firebase-admin")

# ============================================================================
# Load environment from .env file
# ============================================================================

_UTILS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _UTILS_DIR.parent
_ENV_FILE = _BACKEND_DIR / ".env"

def _load_env_file():
    """Load and parse .env file directly"""
    env_vars = {}
    if _ENV_FILE.exists():
        try:
            with open(_ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip()
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        env_vars[key] = value
        except Exception as e:
            print(f"[FirebaseAdmin] Error reading .env: {e}")
    return env_vars

_ENV_VARS = _load_env_file()

# Firebase Configuration
FIREBASE_PROJECT_ID = _ENV_VARS.get('FIREBASE_PROJECT_ID', '') or os.environ.get('FIREBASE_PROJECT_ID', '')
FIREBASE_PRIVATE_KEY_ID = _ENV_VARS.get('FIREBASE_PRIVATE_KEY_ID', '') or os.environ.get('FIREBASE_PRIVATE_KEY_ID', '')
FIREBASE_PRIVATE_KEY = _ENV_VARS.get('FIREBASE_PRIVATE_KEY', '') or os.environ.get('FIREBASE_PRIVATE_KEY', '')
FIREBASE_CLIENT_EMAIL = _ENV_VARS.get('FIREBASE_CLIENT_EMAIL', '') or os.environ.get('FIREBASE_CLIENT_EMAIL', '')
FIREBASE_CLIENT_ID = _ENV_VARS.get('FIREBASE_CLIENT_ID', '') or os.environ.get('FIREBASE_CLIENT_ID', '')
FIREBASE_CLIENT_CERT_URL = _ENV_VARS.get('FIREBASE_CLIENT_X509_CERT_URL', '') or os.environ.get('FIREBASE_CLIENT_X509_CERT_URL', '')
FIREBASE_SERVICE_ACCOUNT_PATH = _ENV_VARS.get('FIREBASE_SERVICE_ACCOUNT_PATH', '') or os.environ.get('FIREBASE_SERVICE_ACCOUNT_PATH', '')

# Global state
_firebase_app = None
_firebase_initialized = False


def _get_service_account_info() -> Optional[Dict[str, Any]]:
    """Build service account info from environment variables"""
    # First try service account file path
    if FIREBASE_SERVICE_ACCOUNT_PATH:
        service_account_path = _BACKEND_DIR / FIREBASE_SERVICE_ACCOUNT_PATH
        if service_account_path.exists():
            try:
                with open(service_account_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[FirebaseAdmin] Error reading service account file: {e}")
    
    # Build from individual environment variables
    if FIREBASE_PROJECT_ID and FIREBASE_PRIVATE_KEY and FIREBASE_CLIENT_EMAIL:
        # Process private key - replace escaped newlines
        private_key = FIREBASE_PRIVATE_KEY.replace('\\n', '\n')
        
        return {
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "private_key_id": FIREBASE_PRIVATE_KEY_ID,
            "private_key": private_key,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "client_id": FIREBASE_CLIENT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": FIREBASE_CLIENT_CERT_URL,
        }
    
    return None


def initialize_firebase() -> bool:
    """Initialize Firebase Admin SDK"""
    global _firebase_app, _firebase_initialized
    
    if _firebase_initialized:
        return _firebase_app is not None
    
    if not FIREBASE_ADMIN_AVAILABLE:
        print("[FirebaseAdmin] ✗ Cannot initialize - firebase_admin package not installed")
        _firebase_initialized = True
        return False
    
    try:
        # Check if already initialized
        try:
            _firebase_app = firebase_admin.get_app()
            print("[FirebaseAdmin] ✓ Firebase Admin already initialized")
            _firebase_initialized = True
            return True
        except ValueError:
            pass  # Not initialized yet
        
        # Get service account credentials
        service_account_info = _get_service_account_info()
        
        if service_account_info:
            cred = credentials.Certificate(service_account_info)
            _firebase_app = firebase_admin.initialize_app(cred)
            print(f"[FirebaseAdmin] ✓ Initialized with project: {FIREBASE_PROJECT_ID}")
            _firebase_initialized = True
            return True
        else:
            print("[FirebaseAdmin] ⚠ No service account credentials configured")
            print("[FirebaseAdmin]   Token verification will not work without Admin SDK")
            print("[FirebaseAdmin]   To enable: set FIREBASE_SERVICE_ACCOUNT_PATH or individual credentials in .env")
            _firebase_initialized = True
            return False
            
    except Exception as e:
        print(f"[FirebaseAdmin] ✗ Initialization failed: {e}")
        _firebase_initialized = True
        return False


def verify_id_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Firebase ID token
    
    Args:
        id_token: The Firebase ID token to verify
        
    Returns:
        Decoded token data if valid, None otherwise
    """
    if not FIREBASE_ADMIN_AVAILABLE:
        print("[FirebaseAdmin] Cannot verify token - firebase_admin not installed")
        return None
    
    if not initialize_firebase():
        print("[FirebaseAdmin] Cannot verify token - Firebase not initialized")
        return None
    
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except auth.ExpiredIdTokenError:
        print("[FirebaseAdmin] Token expired")
        return None
    except auth.RevokedIdTokenError:
        print("[FirebaseAdmin] Token revoked")
        return None
    except auth.InvalidIdTokenError as e:
        print(f"[FirebaseAdmin] Invalid token: {e}")
        return None
    except Exception as e:
        print(f"[FirebaseAdmin] Token verification error: {e}")
        return None


def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get Firebase user by UID
    
    Args:
        uid: Firebase user UID
        
    Returns:
        User data dict if found, None otherwise
    """
    if not FIREBASE_ADMIN_AVAILABLE or not initialize_firebase():
        return None
    
    try:
        user = auth.get_user(uid)
        return {
            'uid': user.uid,
            'email': user.email,
            'display_name': user.display_name,
            'photo_url': user.photo_url,
            'phone_number': user.phone_number,
            'email_verified': user.email_verified,
            'disabled': user.disabled,
            'provider_data': [
                {
                    'provider_id': p.provider_id,
                    'uid': p.uid,
                    'email': p.email,
                }
                for p in user.provider_data
            ] if user.provider_data else [],
        }
    except auth.UserNotFoundError:
        return None
    except Exception as e:
        print(f"[FirebaseAdmin] Error getting user: {e}")
        return None


def is_firebase_admin_configured() -> bool:
    """Check if Firebase Admin SDK is properly configured"""
    return FIREBASE_ADMIN_AVAILABLE and initialize_firebase()


# Initialize on module import
if FIREBASE_ADMIN_AVAILABLE:
    initialize_firebase()
