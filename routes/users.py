"""
Users Routes
Handles user profile management and admin user management
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.user import User, UserRole
from routes.auth import require_auth, require_admin, get_current_user
from utils.validators import validate_name, validate_phone, validate_email

users_bp = Blueprint('users', __name__, url_prefix='/api/users')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


@users_bp.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    """Get current user's profile"""
    try:
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
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


@users_bp.route('/profile', methods=['PUT'])
@require_auth
def update_profile():
    """Update current user's profile"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        # Build update document
        update_fields = {}
        
        # Validate and update first name
        if 'first_name' in data:
            first_name = data['first_name'].strip()
            is_valid, error = validate_name(first_name, 'First Name')
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['first_name'] = first_name
        
        # Validate and update last name
        if 'last_name' in data:
            last_name = data['last_name'].strip()
            is_valid, error = validate_name(last_name, 'Last Name')
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['last_name'] = last_name
        
        # Validate and update phone
        if 'phone' in data:
            phone = data['phone'].strip() if data['phone'] else ''
            if phone:
                is_valid, error = validate_phone(phone)
                if not is_valid:
                    return jsonify({'ok': False, 'error': error}), 400
            update_fields['phone'] = phone or None
        
        # Update address fields
        if 'address' in data:
            update_fields['address'] = data['address'].strip() if data['address'] else None
        if 'city' in data:
            update_fields['city'] = data['city'].strip() if data['city'] else None
        if 'province' in data:
            update_fields['province'] = data['province'].strip() if data['province'] else None
        if 'postal_code' in data:
            update_fields['postal_code'] = data['postal_code'].strip() if data['postal_code'] else None
        
        # Update profile image
        if 'profile_image' in data:
            update_fields['profile_image'] = data['profile_image']
        
        if not update_fields:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400
        
        update_fields['updated_at'] = datetime.now(timezone.utc)
        
        # Update user
        users_collection.update_one(
            {'_id': ObjectId(request.user_info['user_id'])},
            {'$set': update_fields}
        )
        
        # Get updated user
        updated_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        user = User.from_dict(updated_doc)
        user._id = str(updated_doc['_id'])
        
        return jsonify({
            'ok': True,
            'message': 'Profile updated successfully',
            'user': user.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update profile: {str(e)}'}), 500


@users_bp.route('/profile/image', methods=['POST'])
@require_auth
def update_profile_image():
    """Update profile image"""
    try:
        data = request.get_json()
        if not data or 'image' not in data:
            return jsonify({'ok': False, 'error': 'Image data required'}), 400
        
        from utils.cloudinary_helper import upload_image
        
        success, url_or_error, public_id = upload_image(
            data['image'],
            folder='profile_images',
            public_id=f"user_{request.user_info['user_id']}"
        )
        
        if not success:
            return jsonify({'ok': False, 'error': url_or_error}), 400
        
        # Update user profile image
        users_collection = _get_users_collection()
        users_collection.update_one(
            {'_id': ObjectId(request.user_info['user_id'])},
            {'$set': {
                'profile_image': url_or_error,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': 'Profile image updated',
            'image_url': url_or_error
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Admin routes

@users_bp.route('/', methods=['GET'])
@require_admin
def list_users():
    """List all users (admin only)"""
    try:
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        role_filter = request.args.get('role')
        search = request.args.get('search', '').strip()
        
        query = {}
        if role_filter:
            query['role'] = role_filter
        if search:
            query['$or'] = [
                {'email': {'$regex': search, '$options': 'i'}},
                {'first_name': {'$regex': search, '$options': 'i'}},
                {'last_name': {'$regex': search, '$options': 'i'}},
            ]
        
        # Get users
        cursor = users_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = users_collection.count_documents(query)
        
        users = []
        for doc in cursor:
            user = User.from_dict(doc)
            user._id = str(doc['_id'])
            users.append(user.to_public_dict())
        
        return jsonify({
            'ok': True,
            'users': users,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@users_bp.route('/<user_id>', methods=['GET'])
@require_admin
def get_user(user_id: str):
    """Get user by ID (admin only)"""
    try:
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_doc = users_collection.find_one({'_id': ObjectId(user_id)})
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


@users_bp.route('/<user_id>/status', methods=['PUT'])
@require_admin
def update_user_status(user_id: str):
    """Activate/deactivate user (admin only)"""
    try:
        data = request.get_json()
        if data is None or 'is_active' not in data:
            return jsonify({'ok': False, 'error': 'is_active field required'}), 400
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Can't deactivate yourself
        if user_id == request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'Cannot change your own status'}), 400
        
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'is_active': bool(data['is_active']),
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        if result.matched_count == 0:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        return jsonify({
            'ok': True,
            'message': f"User {'activated' if data['is_active'] else 'deactivated'} successfully"
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@users_bp.route('/<user_id>/role', methods=['PUT'])
@require_admin
def update_user_role(user_id: str):
    """Change user role (admin only)"""
    try:
        data = request.get_json()
        if not data or 'role' not in data:
            return jsonify({'ok': False, 'error': 'role field required'}), 400
        
        role = data['role']
        if role not in ['user', 'admin']:
            return jsonify({'ok': False, 'error': 'Invalid role. Must be "user" or "admin"'}), 400
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Can't change your own role
        if user_id == request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'Cannot change your own role'}), 400
        
        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'role': role,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        if result.matched_count == 0:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        return jsonify({
            'ok': True,
            'message': f'User role updated to {role}'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
