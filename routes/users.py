"""
Users Routes
Handles user profile management and admin user management
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.user import User, UserRole, SuspensionType
from routes.auth import require_auth, require_admin, get_current_user
from utils.validators import validate_name, validate_phone, validate_email
from utils.email_service import EmailService

users_bp = Blueprint('users', __name__, url_prefix='/api/users')

# Initialize email service
email_service = EmailService()

# Suspension duration mappings
SUSPENSION_DURATIONS = {
    SuspensionType.HOUR_1.value: timedelta(hours=1),
    SuspensionType.HOURS_8.value: timedelta(hours=8),
    SuspensionType.DAY_1.value: timedelta(days=1),
    SuspensionType.DAYS_15.value: timedelta(days=15),
    SuspensionType.MONTH_1.value: timedelta(days=30),
    SuspensionType.PERMANENT.value: None,  # No end date
}

SUSPENSION_LABELS = {
    SuspensionType.HOUR_1.value: '1 Hour',
    SuspensionType.HOURS_8.value: '8 Hours',
    SuspensionType.DAY_1.value: '1 Day',
    SuspensionType.DAYS_15.value: '15 Days',
    SuspensionType.MONTH_1.value: '1 Month',
    SuspensionType.PERMANENT.value: 'Permanent',
}


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


@users_bp.route('/suspension-types', methods=['GET'])
@require_admin
def get_suspension_types():
    """Get available suspension types (admin only)"""
    types = []
    for type_value, label in SUSPENSION_LABELS.items():
        types.append({
            'value': type_value,
            'label': label,
            'is_permanent': type_value == SuspensionType.PERMANENT.value
        })
    return jsonify({'ok': True, 'suspension_types': types})


@users_bp.route('/<user_id>/suspend', methods=['POST'])
@require_admin
def suspend_user(user_id: str):
    """Suspend a user (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        suspension_type = data.get('suspension_type')
        reason = data.get('reason', '').strip()
        
        if not suspension_type:
            return jsonify({'ok': False, 'error': 'Suspension type is required'}), 400
        
        if suspension_type not in SUSPENSION_DURATIONS:
            return jsonify({'ok': False, 'error': 'Invalid suspension type'}), 400
        
        if not reason:
            return jsonify({'ok': False, 'error': 'Suspension reason is required'}), 400
        
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Can't suspend yourself
        if user_id == request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'Cannot suspend yourself'}), 400
        
        # Get user
        user_doc = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        # Can't suspend an admin
        if user_doc.get('role') == 'admin':
            return jsonify({'ok': False, 'error': 'Cannot suspend an admin user'}), 400
        
        # Calculate suspension dates
        now = datetime.now(timezone.utc)
        duration = SUSPENSION_DURATIONS[suspension_type]
        suspension_end = now + duration if duration else None
        
        # Update user with suspension
        update_data = {
            'is_suspended': True,
            'suspension_type': suspension_type,
            'suspension_reason': reason,
            'suspension_start': now,
            'suspension_end': suspension_end,
            'suspended_by': request.user_info['user_id'],
            'updated_at': now
        }
        
        users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': update_data}
        )
        
        # Send suspension email notification
        user_email = user_doc.get('email')
        user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
        suspension_label = SUSPENSION_LABELS.get(suspension_type, suspension_type)
        
        if suspension_end:
            end_date_str = suspension_end.strftime('%B %d, %Y at %I:%M %p UTC')
            duration_info = f"Your account will be automatically reinstated on {end_date_str}."
        else:
            duration_info = "This suspension is permanent and your account will not be automatically reinstated."
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #D32F2F 0%, #F44336 100%); padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px;">⚠️ Account Suspended</h1>
                </div>
                <div style="padding: 30px;">
                    <p style="font-size: 16px; color: #212121;">Hello <strong>{user_name}</strong>,</p>
                    <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                        Your Bignay Marketplace account has been suspended due to a violation of our community guidelines.
                    </p>
                    <div style="background-color: #FFF3E0; border-left: 4px solid #FF9800; padding: 15px; margin: 20px 0; border-radius: 4px;">
                        <p style="margin: 0 0 10px 0; font-weight: bold; color: #E65100;">Suspension Details:</p>
                        <p style="margin: 5px 0; color: #424242;"><strong>Duration:</strong> {suspension_label}</p>
                        <p style="margin: 5px 0; color: #424242;"><strong>Reason:</strong> {reason}</p>
                    </div>
                    <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                        {duration_info}
                    </p>
                    <p style="font-size: 14px; color: #757575; margin-top: 30px;">
                        If you believe this suspension was made in error, please contact our support team.
                    </p>
                </div>
                <div style="background-color: #f5f5f5; padding: 20px; text-align: center;">
                    <p style="font-size: 12px; color: #757575; margin: 0;">
                        🌿 Bignay Marketplace - Building a trusted community
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
Account Suspended

Hello {user_name},

Your Bignay Marketplace account has been suspended.

Suspension Details:
- Duration: {suspension_label}
- Reason: {reason}

{duration_info}

If you believe this suspension was made in error, please contact our support team.

Bignay Marketplace - Building a trusted community
        """
        
        # Send email
        email_service.send_email(
            to_email=user_email,
            subject="Account Suspended - Bignay Marketplace",
            html_body=html_body,
            text_body=text_body
        )
        
        return jsonify({
            'ok': True,
            'message': f'User suspended successfully ({suspension_label})',
            'suspension': {
                'type': suspension_type,
                'reason': reason,
                'start': now.isoformat(),
                'end': suspension_end.isoformat() if suspension_end else None
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@users_bp.route('/<user_id>/unsuspend', methods=['POST'])
@require_admin
def unsuspend_user(user_id: str):
    """Lift suspension from a user (admin only)"""
    try:
        users_collection = _get_users_collection()
        if users_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get user
        user_doc = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        if not user_doc.get('is_suspended'):
            return jsonify({'ok': False, 'error': 'User is not currently suspended'}), 400
        
        # Remove suspension
        users_collection.update_one(
            {'_id': ObjectId(user_id)},
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
        
        # Send unsuspension email notification
        user_email = user_doc.get('email')
        user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%); padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px;">✅ Account Reinstated</h1>
                </div>
                <div style="padding: 30px;">
                    <p style="font-size: 16px; color: #212121;">Hello <strong>{user_name}</strong>,</p>
                    <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                        Great news! Your Bignay Marketplace account has been reinstated. You can now log in and use all features of the platform.
                    </p>
                    <div style="background-color: #E8F5E9; border-left: 4px solid #4CAF50; padding: 15px; margin: 20px 0; border-radius: 4px;">
                        <p style="margin: 0; color: #2E7D32; font-weight: bold;">Your account is now active!</p>
                    </div>
                    <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                        Please ensure you follow our community guidelines to avoid future suspensions.
                    </p>
                </div>
                <div style="background-color: #f5f5f5; padding: 20px; text-align: center;">
                    <p style="font-size: 12px; color: #757575; margin: 0;">
                        🌿 Bignay Marketplace - Welcome back!
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
Account Reinstated

Hello {user_name},

Great news! Your Bignay Marketplace account has been reinstated. You can now log in and use all features of the platform.

Please ensure you follow our community guidelines to avoid future suspensions.

Bignay Marketplace - Welcome back!
        """
        
        # Send email
        email_service.send_email(
            to_email=user_email,
            subject="Account Reinstated - Bignay Marketplace",
            html_body=html_body,
            text_body=text_body
        )
        
        return jsonify({
            'ok': True,
            'message': 'User suspension lifted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


def check_and_lift_expired_suspensions():
    """Check and automatically lift expired suspensions"""
    try:
        from flask import current_app
        users_collection = current_app.config.get('db_users')
        if users_collection is None:
            return
        
        now = datetime.now(timezone.utc)
        
        # Find users with expired suspensions (non-permanent)
        expired_users = users_collection.find({
            'is_suspended': True,
            'suspension_end': {'$ne': None, '$lte': now}
        })
        
        for user_doc in expired_users:
            users_collection.update_one(
                {'_id': user_doc['_id']},
                {'$set': {
                    'is_suspended': False,
                    'suspension_type': None,
                    'suspension_reason': None,
                    'suspension_start': None,
                    'suspension_end': None,
                    'suspended_by': None,
                    'updated_at': now
                }}
            )
            
            # Send email notification about automatic reinstatement
            user_email = user_doc.get('email')
            user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
            
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
            </head>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden;">
                    <div style="background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%); padding: 30px; text-align: center;">
                        <h1 style="color: #ffffff; margin: 0; font-size: 24px;">✅ Suspension Period Ended</h1>
                    </div>
                    <div style="padding: 30px;">
                        <p style="font-size: 16px; color: #212121;">Hello <strong>{user_name}</strong>,</p>
                        <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                            Your suspension period has ended and your account has been automatically reinstated. 
                            You can now log in and use all features of the Bignay Marketplace.
                        </p>
                        <p style="font-size: 15px; color: #424242; line-height: 1.6;">
                            Please ensure you follow our community guidelines to avoid future suspensions.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            email_service.send_email(
                to_email=user_email,
                subject="Suspension Period Ended - Bignay Marketplace",
                html_body=html_body,
                text_body=f"Hello {user_name}, your suspension period has ended and your account has been reinstated."
            )
    
    except Exception as e:
        print(f"[Users] Error checking expired suspensions: {e}")
