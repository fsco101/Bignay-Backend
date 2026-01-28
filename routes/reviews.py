"""
Reviews Routes
Handles product reviews and ratings
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.review import Review
from routes.auth import require_auth, require_admin, get_current_user
from routes.orders import user_purchased_product
from utils.validators import validate_rating
from utils.bad_words_filter import filter_bad_words, validate_content

reviews_bp = Blueprint('reviews', __name__, url_prefix='/api/reviews')


def _get_reviews_collection():
    """Get MongoDB reviews collection"""
    from flask import current_app
    return current_app.config.get('db_reviews')


def _get_products_collection():
    """Get MongoDB products collection"""
    from flask import current_app
    return current_app.config.get('db_products')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


def _get_orders_collection():
    """Get MongoDB orders collection"""
    from flask import current_app
    return current_app.config.get('db_orders')


def _update_product_rating(product_id: str):
    """Recalculate and update product average rating"""
    reviews_collection = _get_reviews_collection()
    products_collection = _get_products_collection()
    
    if any(c is None for c in [reviews_collection, products_collection]):
        return
    
    # Calculate average rating
    pipeline = [
        {'$match': {'product_id': product_id, 'is_visible': True}},
        {'$group': {
            '_id': '$product_id',
            'average_rating': {'$avg': '$rating'},
            'review_count': {'$sum': 1}
        }}
    ]
    
    result = list(reviews_collection.aggregate(pipeline))
    
    if result:
        avg_rating = round(result[0]['average_rating'], 1)
        review_count = result[0]['review_count']
    else:
        avg_rating = 0
        review_count = 0
    
    products_collection.update_one(
        {'_id': ObjectId(product_id)},
        {'$set': {
            'average_rating': avg_rating,
            'review_count': review_count,
            'updated_at': datetime.now(timezone.utc)
        }}
    )


@reviews_bp.route('/product/<product_id>', methods=['GET'])
def get_product_reviews(product_id: str):
    """Get reviews for a product"""
    try:
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Sort
        sort_by = request.args.get('sort', 'created_at')
        sort_order = -1 if request.args.get('order', 'desc') == 'desc' else 1
        
        sort_field = 'created_at'
        if sort_by == 'rating':
            sort_field = 'rating'
        elif sort_by == 'helpful':
            sort_field = 'helpful_count'
        
        query = {'product_id': product_id, 'is_visible': True}
        
        cursor = reviews_collection.find(query).skip(skip).limit(limit).sort(sort_field, sort_order)
        total = reviews_collection.count_documents(query)
        
        reviews = []
        for doc in cursor:
            review = Review.from_dict(doc)
            review._id = str(doc['_id'])
            reviews.append(review.to_public_dict())
        
        # Get rating distribution
        rating_pipeline = [
            {'$match': {'product_id': product_id, 'is_visible': True}},
            {'$group': {'_id': '$rating', 'count': {'$sum': 1}}}
        ]
        rating_dist = list(reviews_collection.aggregate(rating_pipeline))
        rating_distribution = {str(i): 0 for i in range(1, 6)}
        for r in rating_dist:
            rating_distribution[str(r['_id'])] = r['count']
        
        return jsonify({
            'ok': True,
            'reviews': reviews,
            'rating_distribution': rating_distribution,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/product/<product_id>', methods=['POST'])
@require_auth
def create_review(product_id: str):
    """Create a review for a product (must have purchased)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate rating
        rating = data.get('rating')
        is_valid, error = validate_rating(rating)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Validate comment
        comment = data.get('comment', '').strip()
        if not comment:
            return jsonify({'ok': False, 'error': 'Review comment is required'}), 400
        
        is_valid, filtered_comment, error = validate_content(comment, max_length=1000)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        reviews_collection = _get_reviews_collection()
        products_collection = _get_products_collection()
        users_collection = _get_users_collection()
        orders_collection = _get_orders_collection()
        
        if any(c is None for c in [reviews_collection, products_collection, users_collection, orders_collection]):
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Check if product exists
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Check if user has purchased this product
        purchase_order = orders_collection.find_one({
            'user_id': request.user_info['user_id'],
            'status': 'delivered',
            'items.product_id': product_id
        })
        
        if not purchase_order:
            return jsonify({
                'ok': False, 
                'error': 'You can only review products you have purchased and received'
            }), 403
        
        # Check if user already reviewed this product
        existing_review = reviews_collection.find_one({
            'product_id': product_id,
            'user_id': request.user_info['user_id']
        })
        
        if existing_review:
            return jsonify({'ok': False, 'error': 'You have already reviewed this product'}), 409
        
        # Get user info
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
        user_profile_image = user_doc.get('profile_image')
        
        # Create review
        review = Review(
            product_id=product_id,
            user_id=request.user_info['user_id'],
            user_name=user_name or 'Anonymous',
            order_id=str(purchase_order['_id']),
            rating=int(rating),
            comment=filtered_comment,
            original_comment=comment,
            user_profile_image=user_profile_image,
            is_verified_purchase=True,
        )
        
        result = reviews_collection.insert_one(review.to_dict())
        review._id = str(result.inserted_id)
        
        # Update product rating
        _update_product_rating(product_id)
        
        return jsonify({
            'ok': True,
            'message': 'Review submitted successfully',
            'review': review.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to submit review: {str(e)}'}), 500


@reviews_bp.route('/<review_id>', methods=['PUT'])
@require_auth
def update_review(review_id: str):
    """Update own review"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        review_doc = reviews_collection.find_one({'_id': ObjectId(review_id)})
        if not review_doc:
            return jsonify({'ok': False, 'error': 'Review not found'}), 404
        
        # Check ownership
        if review_doc.get('user_id') != request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        
        update_fields = {}
        
        # Update rating
        if 'rating' in data:
            is_valid, error = validate_rating(data['rating'])
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['rating'] = int(data['rating'])
        
        # Update comment
        if 'comment' in data:
            comment = data['comment'].strip()
            is_valid, filtered_comment, error = validate_content(comment, max_length=1000)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['comment'] = filtered_comment
            update_fields['original_comment'] = comment
        
        if not update_fields:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400
        
        update_fields['updated_at'] = datetime.now(timezone.utc)
        
        reviews_collection.update_one(
            {'_id': ObjectId(review_id)},
            {'$set': update_fields}
        )
        
        # Update product rating if rating changed
        if 'rating' in update_fields:
            _update_product_rating(review_doc['product_id'])
        
        return jsonify({
            'ok': True,
            'message': 'Review updated successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/<review_id>', methods=['DELETE'])
@require_auth
def delete_review(review_id: str):
    """Delete own review"""
    try:
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        review_doc = reviews_collection.find_one({'_id': ObjectId(review_id)})
        if not review_doc:
            return jsonify({'ok': False, 'error': 'Review not found'}), 404
        
        # Check ownership (or admin)
        if (review_doc.get('user_id') != request.user_info['user_id'] and 
            request.user_info.get('role') != 'admin'):
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        
        product_id = review_doc['product_id']
        
        reviews_collection.delete_one({'_id': ObjectId(review_id)})
        
        # Update product rating
        _update_product_rating(product_id)
        
        return jsonify({
            'ok': True,
            'message': 'Review deleted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/<review_id>/helpful', methods=['POST'])
@require_auth
def mark_helpful(review_id: str):
    """Mark a review as helpful"""
    try:
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        result = reviews_collection.update_one(
            {'_id': ObjectId(review_id)},
            {'$inc': {'helpful_count': 1}}
        )
        
        if result.matched_count == 0:
            return jsonify({'ok': False, 'error': 'Review not found'}), 404
        
        return jsonify({
            'ok': True,
            'message': 'Marked as helpful'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Admin routes

@reviews_bp.route('/admin/all', methods=['GET'])
@require_admin
def admin_list_reviews():
    """List all reviews (admin only)"""
    try:
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        product_id = request.args.get('product_id')
        is_visible = request.args.get('is_visible')
        
        query = {}
        if product_id:
            query['product_id'] = product_id
        if is_visible is not None:
            query['is_visible'] = is_visible.lower() == 'true'
        
        cursor = reviews_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = reviews_collection.count_documents(query)
        
        reviews = []
        for doc in cursor:
            review = Review.from_dict(doc)
            review._id = str(doc['_id'])
            review_data = review.to_public_dict()
            review_data['original_comment'] = doc.get('original_comment', '')
            review_data['is_visible'] = doc.get('is_visible', True)
            reviews.append(review_data)
        
        return jsonify({
            'ok': True,
            'reviews': reviews,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/admin/<review_id>/visibility', methods=['PUT'])
@require_admin
def update_review_visibility(review_id: str):
    """Show/hide a review (admin only)"""
    try:
        data = request.get_json()
        if data is None or 'is_visible' not in data:
            return jsonify({'ok': False, 'error': 'is_visible field required'}), 400
        
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        review_doc = reviews_collection.find_one({'_id': ObjectId(review_id)})
        if not review_doc:
            return jsonify({'ok': False, 'error': 'Review not found'}), 404
        
        reviews_collection.update_one(
            {'_id': ObjectId(review_id)},
            {'$set': {
                'is_visible': bool(data['is_visible']),
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        # Update product rating
        _update_product_rating(review_doc['product_id'])
        
        return jsonify({
            'ok': True,
            'message': f"Review {'shown' if data['is_visible'] else 'hidden'} successfully"
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/my-reviews', methods=['GET'])
@require_auth
def get_my_reviews():
    """Get current user's reviews"""
    try:
        reviews_collection = _get_reviews_collection()
        if reviews_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        cursor = reviews_collection.find(
            {'user_id': request.user_info['user_id']}
        ).sort('created_at', -1)
        
        reviews = []
        for doc in cursor:
            review = Review.from_dict(doc)
            review._id = str(doc['_id'])
            reviews.append(review.to_public_dict())
        
        return jsonify({
            'ok': True,
            'reviews': reviews
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@reviews_bp.route('/can-review/<product_id>', methods=['GET'])
@require_auth
def can_review_product(product_id: str):
    """Check if user can review a product"""
    try:
        reviews_collection = _get_reviews_collection()
        orders_collection = _get_orders_collection()
        
        if any(c is None for c in [reviews_collection, orders_collection]):
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Check if already reviewed
        existing_review = reviews_collection.find_one({
            'product_id': product_id,
            'user_id': request.user_info['user_id']
        })
        
        if existing_review:
            return jsonify({
                'ok': True,
                'can_review': False,
                'reason': 'already_reviewed',
                'existing_review_id': str(existing_review['_id'])
            })
        
        # Check if purchased
        purchase_order = orders_collection.find_one({
            'user_id': request.user_info['user_id'],
            'status': 'delivered',
            'items.product_id': product_id
        })
        
        if not purchase_order:
            return jsonify({
                'ok': True,
                'can_review': False,
                'reason': 'not_purchased'
            })
        
        return jsonify({
            'ok': True,
            'can_review': True
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
