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
    """Get current user from request authorization header"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    return verify_token(auth_header)


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
