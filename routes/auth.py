"""
Authentication Routes
Handles login, registration, and token management
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
import secrets
import hashlib

from models.user import User, UserRole
from utils.validators import (
    validate_email, 
    validate_password, 
    validate_required_fields,
    validate_name,
    validate_phone
)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Simple token storage (in production, use Redis or database)
_active_tokens = {}


def _generate_token(user_id: str, role: str) -> str:
    """Generate a simple auth token"""
    token = secrets.token_urlsafe(32)
    _active_tokens[token] = {
        'user_id': user_id,
        'role': role,
        'created_at': datetime.now(timezone.utc),
        'expires_at': datetime.now(timezone.utc) + timedelta(days=7)
    }
    return token


def verify_token(token: str) -> dict | None:
    """Verify token and return user info"""
    if not token:
        return None
    
    # Remove 'Bearer ' prefix if present
    if token.startswith('Bearer '):
        token = token[7:]
    
    token_data = _active_tokens.get(token)
    if not token_data:
        return None
    
    if datetime.now(timezone.utc) > token_data['expires_at']:
        del _active_tokens[token]
        return None
    
    return token_data


def get_current_user(request) -> dict | None:
    """Get current user from request authorization header or query param"""
    # First try Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header:
        return verify_token(auth_header)
    
    # Fallback to query parameter (for PDF downloads in web browser)
    token = request.args.get('token')
    if token:
        return verify_token(token)
    
    return None


def require_auth(f):
    """Decorator to require authentication"""
    from functools import wraps
    
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = get_current_user(request)
        if not user_info:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        request.user_info = user_info
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator to require admin role"""
    from functools import wraps
    
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = get_current_user(request)
        if not user_info:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        if user_info.get('role') != 'admin':
            return jsonify({'ok': False, 'error': 'Admin access required'}), 403
        request.user_info = user_info
        return f(*args, **kwargs)
    return decorated


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new user
    Required fields: email, password, first_name, last_name
    Optional fields: phone, address, city, province, postal_code
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['email', 'password', 'first_name', 'last_name']
        is_valid, missing = validate_required_fields(data, required)
        if not is_valid:
            return jsonify({'ok': False, 'errors': missing}), 400
        
        # Validate email
        email = data.get('email', '').strip().lower()
        is_valid, error = validate_email(email)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Validate password
        password = data.get('password', '')
        is_valid, errors = validate_password(password)
        if not is_valid:
            return jsonify({'ok': False, 'errors': errors}), 400
        
        # Validate names
        first_name = data.get('first_name', '').strip()
        is_valid, error = validate_name(first_name, 'First Name')
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        last_name = data.get('last_name', '').strip()
        is_valid, error = validate_name(last_name, 'Last Name')
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Validate phone if provided
        phone = data.get('phone', '').strip()
        if phone:
            is_valid, error = validate_phone(phone)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
        
        # Check if user already exists
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        existing_user = users_collection.find_one({'email': email})
        if existing_user:
            return jsonify({'ok': False, 'error': 'An account with this email already exists'}), 409
        
        # Create new user
        user = User(
            email=email,
            password_hash=User.hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=UserRole.USER,
            phone=phone or None,
            address=data.get('address', '').strip() or None,
            city=data.get('city', '').strip() or None,
            province=data.get('province', '').strip() or None,
            postal_code=data.get('postal_code', '').strip() or None,
        )
        
        # Save to database
        result = users_collection.insert_one(user.to_dict(include_password=True))
        user._id = str(result.inserted_id)
        
        # Generate token
        token = _generate_token(user._id, user.role.value)
        
        return jsonify({
            'ok': True,
            'message': 'Registration successful',
            'token': token,
            'user': user.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Registration failed: {str(e)}'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login with email and password
    Returns auth token and user info
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'ok': False, 'error': 'Email and password are required'}), 400
        
        # Find user
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_doc = users_collection.find_one({'email': email})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'Invalid email or password'}), 401
        
        # Verify password
        if not User.verify_password(password, user_doc.get('password_hash', '')):
            return jsonify({'ok': False, 'error': 'Invalid email or password'}), 401
        
        # Check if user is active
        if not user_doc.get('is_active', True):
            return jsonify({'ok': False, 'error': 'Your account has been deactivated'}), 403
        
        # Check if user is suspended
        if user_doc.get('is_suspended'):
            suspension_end = user_doc.get('suspension_end')
            suspension_reason = user_doc.get('suspension_reason', 'Violation of community guidelines')
            
            # Check if suspension has expired
            if suspension_end:
                if isinstance(suspension_end, str):
                    suspension_end = datetime.fromisoformat(suspension_end.replace('Z', '+00:00'))
                
                if datetime.now(timezone.utc) > suspension_end:
                    # Suspension has expired, automatically lift it
                    users_collection.update_one(
                        {'_id': user_doc['_id']},
                        {'$set': {
                            'is_suspended': False,
                            'suspension_type': None,
                            'suspension_reason': None,
                            'suspension_start': None,
                            'suspension_end': None,
                            'suspended_by': None,
                            'updated_at': datetime.now(timezone.utc)
                        }}
                    )
                else:
                    # Still suspended
                    end_date_str = suspension_end.strftime('%B %d, %Y at %I:%M %p UTC')
                    return jsonify({
                        'ok': False, 
                        'error': f'Your account is suspended until {end_date_str}',
                        'suspension': {
                            'reason': suspension_reason,
                            'end': suspension_end.isoformat(),
                            'is_permanent': False
                        }
                    }), 403
            else:
                # Permanent suspension
                return jsonify({
                    'ok': False, 
                    'error': 'Your account has been permanently suspended',
                    'suspension': {
                        'reason': suspension_reason,
                        'end': None,
                        'is_permanent': True
                    }
                }), 403
        
        # Create user object
        user = User.from_dict(user_doc)
        user._id = str(user_doc['_id'])
        
        # Update last login
        users_collection.update_one(
            {'_id': user_doc['_id']},
            {'$set': {'last_login': datetime.now(timezone.utc)}}
        )
        
        # Generate token
        token = _generate_token(user._id, user.role.value if isinstance(user.role, UserRole) else user.role)
        
        return jsonify({
            'ok': True,
            'message': 'Login successful',
            'token': token,
            'user': user.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Login failed: {str(e)}'}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout and invalidate token"""
    auth_header = request.headers.get('Authorization')
    if auth_header:
        token = auth_header.replace('Bearer ', '')
        if token in _active_tokens:
            del _active_tokens[token]
    
    return jsonify({'ok': True, 'message': 'Logged out successfully'})


@auth_bp.route('/google', methods=['POST'])
def google_login():
    """
    Login or register with Google OAuth
    Expects: google_id, email, first_name, last_name, profile_image, access_token
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        google_id = data.get('google_id', '').strip()
        email = data.get('email', '').strip().lower()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        profile_image = data.get('profile_image', '').strip()
        
        if not google_id or not email:
            return jsonify({'ok': False, 'error': 'Google ID and email are required'}), 400
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Try to find existing user by google_id or email
        user_doc = users_collection.find_one({
            '$or': [
                {'google_id': google_id},
                {'email': email}
            ]
        })
        
        if user_doc:
            # Existing user - update google_id if needed and login
            update_fields = {
                'last_login': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc)
            }
            
            # Update google_id if user registered with email but now using Google
            if not user_doc.get('google_id'):
                update_fields['google_id'] = google_id
                update_fields['auth_provider'] = 'google'
            
            # Update profile image if provided and not already set
            if profile_image and not user_doc.get('profile_image'):
                update_fields['profile_image'] = profile_image
            
            users_collection.update_one(
                {'_id': user_doc['_id']},
                {'$set': update_fields}
            )
            
            # Check if user is active
            if not user_doc.get('is_active', True):
                return jsonify({'ok': False, 'error': 'Your account has been deactivated'}), 403
            
            # Check if user is suspended
            if user_doc.get('is_suspended'):
                suspension_end = user_doc.get('suspension_end')
                suspension_reason = user_doc.get('suspension_reason', 'Violation of community guidelines')
                
                # Check if suspension has expired
                if suspension_end:
                    if isinstance(suspension_end, str):
                        suspension_end = datetime.fromisoformat(suspension_end.replace('Z', '+00:00'))
                    
                    if datetime.now(timezone.utc) > suspension_end:
                        # Suspension has expired, automatically lift it
                        users_collection.update_one(
                            {'_id': user_doc['_id']},
                            {'$set': {
                                'is_suspended': False,
                                'suspension_type': None,
                                'suspension_reason': None,
                                'suspension_start': None,
                                'suspension_end': None,
                                'suspended_by': None,
                                'updated_at': datetime.now(timezone.utc)
                            }}
                        )
                    else:
                        # Still suspended
                        end_date_str = suspension_end.strftime('%B %d, %Y at %I:%M %p UTC')
                        return jsonify({
                            'ok': False, 
                            'error': f'Your account is suspended until {end_date_str}',
                            'suspension': {
                                'reason': suspension_reason,
                                'end': suspension_end.isoformat(),
                                'is_permanent': False
                            }
                        }), 403
                else:
                    # Permanent suspension
                    return jsonify({
                        'ok': False, 
                        'error': 'Your account has been permanently suspended',
                        'suspension': {
                            'reason': suspension_reason,
                            'end': None,
                            'is_permanent': True
                        }
                    }), 403
            
            user = User.from_dict(user_doc)
            user._id = str(user_doc['_id'])
            
        else:
            # New user - create account
            user = User(
                email=email,
                password_hash='',  # No password for Google users
                first_name=first_name or email.split('@')[0],
                last_name=last_name or '',
                role=UserRole.USER,
                google_id=google_id,
                auth_provider='google',
                profile_image=profile_image or None,
                is_verified=True,  # Google accounts are already verified
            )
            
            result = users_collection.insert_one(user.to_dict(include_password=True))
            user._id = str(result.inserted_id)
        
        # Generate token
        token = _generate_token(
            user._id, 
            user.role.value if isinstance(user.role, UserRole) else user.role
        )
        
        return jsonify({
            'ok': True,
            'message': 'Google login successful',
            'token': token,
            'user': user.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Google login failed: {str(e)}'}), 500


@auth_bp.route('/verify', methods=['GET'])
def verify():
    """Verify current token and return user info"""
    user_info = get_current_user(request)
    if not user_info:
        return jsonify({'ok': False, 'error': 'Invalid or expired token'}), 401
    
    # Get full user info from database
    users_collection = _get_users_collection()
    if users_collection is None:
        return jsonify({'ok': False, 'error': 'Database not available'}), 503
    
    from bson import ObjectId
    try:
        user_doc = users_collection.find_one({'_id': ObjectId(user_info['user_id'])})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        user = User.from_dict(user_doc)
        user._id = str(user_doc['_id'])
        
        return jsonify({
            'ok': True,
            'user': user.to_public_dict()
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@auth_bp.route('/change-password', methods=['POST'])
@require_auth
def change_password():
    """Change user password"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        
        if not current_password or not new_password:
            return jsonify({'ok': False, 'error': 'Current and new passwords are required'}), 400
        
        # Validate new password
        is_valid, errors = validate_password(new_password)
        if not is_valid:
            return jsonify({'ok': False, 'errors': errors}), 400
        
        # Get user
        users_collection = _get_users_collection()
        from bson import ObjectId
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        # Verify current password
        if not User.verify_password(current_password, user_doc.get('password_hash', '')):
            return jsonify({'ok': False, 'error': 'Current password is incorrect'}), 401
        
        # Update password
        new_hash = User.hash_password(new_password)
        users_collection.update_one(
            {'_id': user_doc['_id']},
            {'$set': {
                'password_hash': new_hash,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({'ok': True, 'message': 'Password changed successfully'})
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to change password: {str(e)}'}), 500


# Helper function to create admin user (call once during setup)
def create_admin_user(email: str, password: str, first_name: str, last_name: str):
    """Create an admin user - for setup purposes"""
    from flask import current_app
    users_collection = current_app.config.get('db_users')
    
    if users_collection is None:
        return None, "Database not available"
    
    # Check if admin already exists
    existing = users_collection.find_one({'email': email})
    if existing:
        return None, "User already exists"
    
    user = User(
        email=email,
        password_hash=User.hash_password(password),
        first_name=first_name,
        last_name=last_name,
        role=UserRole.ADMIN,
        is_verified=True,
    )
    
    result = users_collection.insert_one(user.to_dict(include_password=True))
    user._id = str(result.inserted_id)
    
    return user, None


@auth_bp.route('/firebase', methods=['POST'])
def firebase_login():
    """
    Login or register with Firebase Authentication
    Supports Google, Email/Password, and other Firebase providers
    Expects: firebaseUid, email, idToken, provider, and optionally firstName, lastName, profileImage
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        firebase_uid = data.get('firebaseUid', '').strip()
        email = data.get('email', '').strip().lower()
        id_token = data.get('idToken', '').strip()
        provider = data.get('provider', 'unknown').strip()
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        profile_image = data.get('profileImage', '').strip()
        
        if not firebase_uid or not email:
            return jsonify({'ok': False, 'error': 'Firebase UID and email are required'}), 400
        
        # Optional: Verify Firebase ID token with Firebase Admin SDK
        # For now, we trust the token since it came from Firebase client SDK
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Try to find existing user by firebase_uid or email
        user_doc = users_collection.find_one({
            '$or': [
                {'firebase_uid': firebase_uid},
                {'email': email}
            ]
        })
        
        if user_doc:
            # Existing user - update firebase_uid if needed and login
            update_fields = {
                'last_login': datetime.now(timezone.utc),
                'updated_at': datetime.now(timezone.utc)
            }
            
            # Update firebase_uid if user registered differently
            if not user_doc.get('firebase_uid'):
                update_fields['firebase_uid'] = firebase_uid
                update_fields['auth_provider'] = f'firebase:{provider}'
            
            # Update profile image if provided and not already set
            if profile_image and not user_doc.get('profile_image'):
                update_fields['profile_image'] = profile_image
            
            users_collection.update_one(
                {'_id': user_doc['_id']},
                {'$set': update_fields}
            )
            
            # Check if user is active
            if not user_doc.get('is_active', True):
                return jsonify({'ok': False, 'error': 'Your account has been deactivated'}), 403
            
            # Check if user is suspended
            if user_doc.get('is_suspended'):
                suspension_end = user_doc.get('suspension_end')
                suspension_reason = user_doc.get('suspension_reason', 'Violation of community guidelines')
                
                # Check if suspension has expired
                if suspension_end:
                    if isinstance(suspension_end, str):
                        suspension_end = datetime.fromisoformat(suspension_end.replace('Z', '+00:00'))
                    
                    if datetime.now(timezone.utc) > suspension_end:
                        # Suspension has expired, automatically lift it
                        users_collection.update_one(
                            {'_id': user_doc['_id']},
                            {'$set': {
                                'is_suspended': False,
                                'suspension_type': None,
                                'suspension_reason': None,
                                'suspension_start': None,
                                'suspension_end': None,
                                'suspended_by': None,
                                'updated_at': datetime.now(timezone.utc)
                            }}
                        )
                    else:
                        # Still suspended
                        end_date_str = suspension_end.strftime('%B %d, %Y at %I:%M %p UTC')
                        return jsonify({
                            'ok': False, 
                            'error': f'Your account is suspended until {end_date_str}',
                            'suspension': {
                                'reason': suspension_reason,
                                'end': suspension_end.isoformat(),
                                'is_permanent': False
                            }
                        }), 403
                else:
                    # Permanent suspension
                    return jsonify({
                        'ok': False, 
                        'error': 'Your account has been permanently suspended',
                        'suspension': {
                            'reason': suspension_reason,
                            'end': None,
                            'is_permanent': True
                        }
                    }), 403
            
            user = User.from_dict(user_doc)
            user._id = str(user_doc['_id'])
        else:
            # New user - create account
            user = User(
                email=email,
                password_hash='',  # No password for Firebase auth users
                first_name=first_name or email.split('@')[0],
                last_name=last_name or '',
                firebase_uid=firebase_uid,
                auth_provider=f'firebase:{provider}',
                profile_image=profile_image or None,
                is_verified=True,  # Firebase users are verified
            )
            
            result = users_collection.insert_one(user.to_dict(include_password=True))
            user._id = str(result.inserted_id)
        
        # Generate token
        token = _generate_token(
            user._id, 
            user.role.value if isinstance(user.role, UserRole) else user.role
        )
        
        return jsonify({
            'ok': True,
            'message': 'Firebase login successful',
            'token': token,
            'user': user.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Firebase login failed: {str(e)}'}), 500
