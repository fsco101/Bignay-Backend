"""
Harvest Map Routes
Handles CRUD operations for harvest map pins (locations).
Supports creating, reading, updating, and deleting map markers
with geolocation data, descriptions, and contact information.
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.harvest_pin import HarvestPin, PIN_TYPES
from routes.auth import require_auth, get_current_user

heatmap_bp = Blueprint('heatmap', __name__, url_prefix='/api/heatmap')


def _get_pins_collection():
    """Get MongoDB harvest_pins collection"""
    from flask import current_app
    return current_app.config.get('db_harvest_pins')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


# ==================== PUBLIC ENDPOINTS ====================

@heatmap_bp.route('/pins', methods=['GET'])
def get_pins():
    """
    Get all active harvest pins for map display.
    Optional query params:
      - pin_type: filter by type (farm, blooming_area, market, other)
      - lat: center latitude for bounding box
      - lng: center longitude for bounding box
      - radius: radius in degrees (approximate)
    """
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    try:
        query = {'is_active': True}

        # Filter by pin type
        pin_type = request.args.get('pin_type')
        if pin_type and pin_type in PIN_TYPES:
            query['pin_type'] = pin_type

        # Optional bounding box filter
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        radius = request.args.get('radius', default=1.0, type=float)

        if lat is not None and lng is not None:
            query['latitude'] = {'$gte': lat - radius, '$lte': lat + radius}
            query['longitude'] = {'$gte': lng - radius, '$lte': lng + radius}

        # Pagination
        page = request.args.get('page', default=1, type=int)
        limit = request.args.get('limit', default=100, type=int)
        limit = min(limit, 500)  # Cap at 500 pins per request
        skip = (page - 1) * limit

        pins_cursor = collection.find(query).sort('created_at', -1).skip(skip).limit(limit)
        total = collection.count_documents(query)

        pins = []
        for doc in pins_cursor:
            pin = HarvestPin.from_dict(doc)
            pins.append(pin.to_public_dict())

        # Enrich pins with up-to-date user avatars
        users_col = _get_users_collection()
        if users_col is not None and pins:
            user_ids = list({p['created_by'] for p in pins if p.get('created_by')})
            try:
                user_docs = {str(u['_id']): u for u in users_col.find(
                    {'_id': {'$in': [ObjectId(uid) for uid in user_ids]}},
                    {'profile_image': 1}
                )}
                for p in pins:
                    uid = p.get('created_by', '')
                    if uid in user_docs:
                        p['created_by_avatar'] = user_docs[uid].get('profile_image', '')
            except Exception:
                pass  # gracefully skip if user lookup fails

        return jsonify({
            'ok': True,
            'pins': pins,
            'total': total,
            'page': page,
            'limit': limit,
            'has_more': (page * limit) < total,
        }), 200

    except Exception as e:
        print(f"[HeatMap] Error fetching pins: {e}")
        return jsonify({'error': 'Failed to fetch pins'}), 500


@heatmap_bp.route('/pins/<pin_id>', methods=['GET'])
def get_pin_detail(pin_id):
    """Get a single pin by ID"""
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    try:
        doc = collection.find_one({'_id': ObjectId(pin_id), 'is_active': True})
        if not doc:
            return jsonify({'error': 'Pin not found'}), 404

        pin = HarvestPin.from_dict(doc)
        return jsonify({'ok': True, 'pin': pin.to_public_dict()}), 200

    except Exception as e:
        print(f"[HeatMap] Error fetching pin detail: {e}")
        return jsonify({'error': 'Failed to fetch pin'}), 500


@heatmap_bp.route('/pin-types', methods=['GET'])
def get_pin_types():
    """Get available pin types"""
    return jsonify({
        'ok': True,
        'pin_types': [
            {'id': 'farm', 'name': 'Farm', 'icon': 'leaf', 'color': '#4CAF50'},
            {'id': 'blooming_area', 'name': 'Blooming Area', 'icon': 'flower', 'color': '#E91E63'},
            {'id': 'market', 'name': 'Market', 'icon': 'storefront', 'color': '#FF9800'},
            {'id': 'other', 'name': 'Other', 'icon': 'location', 'color': '#2196F3'},
        ],
    }), 200


# ==================== AUTHENTICATED ENDPOINTS ====================

@heatmap_bp.route('/pins', methods=['POST'])
@require_auth
def create_pin():
    """
    Create a new harvest pin.
    Requires authentication.
    Body: { latitude, longitude, pin_type, description?, place_name?, contact_person?, contact_details? }
    """
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    current_user = get_current_user(request)
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        # Validate required fields
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        pin_type = data.get('pin_type', 'other')

        if latitude is None or longitude is None:
            return jsonify({'error': 'latitude and longitude are required'}), 400

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return jsonify({'error': 'latitude and longitude must be valid numbers'}), 400

        # Get user info
        user_id = current_user.get('user_id', '')
        users_col = _get_users_collection()
        user_name = 'Unknown User'
        user_avatar = ''
        if users_col is not None and user_id:
            user_doc = users_col.find_one({'_id': ObjectId(user_id)})
            if user_doc:
                user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
                if not user_name:
                    user_name = user_doc.get('email', 'Unknown User')
                user_avatar = user_doc.get('profile_image', '')

        # Create pin object
        pin = HarvestPin(
            latitude=latitude,
            longitude=longitude,
            pin_type=pin_type,
            description=data.get('description', ''),
            place_name=data.get('place_name', ''),
            contact_person=data.get('contact_person', ''),
            contact_details=data.get('contact_details', ''),
            created_by=user_id,
            created_by_name=user_name,
            created_by_avatar=user_avatar,
            images=data.get('images', []),
            tags=data.get('tags', []),
        )

        # Validate
        errors = pin.validate()
        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400

        # Insert into MongoDB
        result = collection.insert_one(pin.to_dict())
        pin._id = str(result.inserted_id)

        return jsonify({
            'ok': True,
            'message': 'Pin created successfully',
            'pin': pin.to_public_dict(),
        }), 201

    except Exception as e:
        print(f"[HeatMap] Error creating pin: {e}")
        return jsonify({'error': 'Failed to create pin'}), 500


@heatmap_bp.route('/pins/<pin_id>', methods=['PUT'])
@require_auth
def update_pin(pin_id):
    """
    Update an existing harvest pin.
    Only the creator or an admin can update.
    """
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    current_user = get_current_user(request)
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        # Find existing pin
        doc = collection.find_one({'_id': ObjectId(pin_id)})
        if not doc:
            return jsonify({'error': 'Pin not found'}), 404

        # Check ownership (creator or admin)
        user_id = current_user.get('user_id', '')
        user_role = current_user.get('role', '')
        if doc.get('created_by') != user_id and user_role != 'admin':
            return jsonify({'error': 'Not authorized to update this pin'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        # Build update document
        update_fields = {}
        allowed_fields = [
            'description', 'place_name', 'pin_type',
            'contact_person', 'contact_details', 'images', 'tags',
        ]
        for field_name in allowed_fields:
            if field_name in data:
                update_fields[field_name] = data[field_name]

        # Allow updating coordinates
        if 'latitude' in data:
            update_fields['latitude'] = float(data['latitude'])
        if 'longitude' in data:
            update_fields['longitude'] = float(data['longitude'])

        update_fields['updated_at'] = datetime.now(timezone.utc)

        # Validate pin_type if being updated
        if 'pin_type' in update_fields and update_fields['pin_type'] not in PIN_TYPES:
            return jsonify({'error': f'Invalid pin_type. Must be one of: {", ".join(PIN_TYPES)}'}), 400

        collection.update_one(
            {'_id': ObjectId(pin_id)},
            {'$set': update_fields}
        )

        # Return updated pin
        updated_doc = collection.find_one({'_id': ObjectId(pin_id)})
        pin = HarvestPin.from_dict(updated_doc)

        return jsonify({
            'ok': True,
            'message': 'Pin updated successfully',
            'pin': pin.to_public_dict(),
        }), 200

    except Exception as e:
        print(f"[HeatMap] Error updating pin: {e}")
        return jsonify({'error': 'Failed to update pin'}), 500


@heatmap_bp.route('/pins/<pin_id>', methods=['DELETE'])
@require_auth
def delete_pin(pin_id):
    """
    Soft-delete a harvest pin (set is_active to False).
    Only the creator or an admin can delete.
    """
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    current_user = get_current_user(request)
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        doc = collection.find_one({'_id': ObjectId(pin_id)})
        if not doc:
            return jsonify({'error': 'Pin not found'}), 404

        # Check ownership (creator or admin)
        user_id = current_user.get('user_id', '')
        user_role = current_user.get('role', '')
        if doc.get('created_by') != user_id and user_role != 'admin':
            return jsonify({'error': 'Not authorized to delete this pin'}), 403

        # Soft delete
        collection.update_one(
            {'_id': ObjectId(pin_id)},
            {'$set': {'is_active': False, 'updated_at': datetime.now(timezone.utc)}}
        )

        return jsonify({
            'ok': True,
            'message': 'Pin deleted successfully',
        }), 200

    except Exception as e:
        print(f"[HeatMap] Error deleting pin: {e}")
        return jsonify({'error': 'Failed to delete pin'}), 500


@heatmap_bp.route('/my-pins', methods=['GET'])
@require_auth
def get_my_pins():
    """Get pins created by the current user"""
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    current_user = get_current_user(request)
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        user_id = current_user.get('user_id', '')
        query = {'created_by': user_id, 'is_active': True}

        pins_cursor = collection.find(query).sort('created_at', -1)
        pins = []
        for doc in pins_cursor:
            pin = HarvestPin.from_dict(doc)
            pins.append(pin.to_public_dict())

        return jsonify({
            'ok': True,
            'pins': pins,
            'total': len(pins),
        }), 200

    except Exception as e:
        print(f"[HeatMap] Error fetching user pins: {e}")
        return jsonify({'error': 'Failed to fetch your pins'}), 500


@heatmap_bp.route('/stats', methods=['GET'])
def get_heatmap_stats():
    """Get aggregate stats for the harvest map"""
    collection = _get_pins_collection()
    if collection is None:
        return jsonify({'error': 'Database not available'}), 503

    try:
        total_pins = collection.count_documents({'is_active': True})

        # Count by type
        type_counts = {}
        for pt in PIN_TYPES:
            type_counts[pt] = collection.count_documents({'is_active': True, 'pin_type': pt})

        return jsonify({
            'ok': True,
            'stats': {
                'total_pins': total_pins,
                'by_type': type_counts,
            },
        }), 200

    except Exception as e:
        print(f"[HeatMap] Error fetching stats: {e}")
        return jsonify({'error': 'Failed to fetch stats'}), 500
