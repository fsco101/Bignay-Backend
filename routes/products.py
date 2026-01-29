"""
Products Routes
Handles CRUD operations for marketplace products
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.product import Product
from routes.auth import require_auth, require_admin, get_current_user
from utils.validators import validate_required_fields, validate_positive_number
from utils.cloudinary_helper import upload_image, upload_multiple_images, delete_image
from utils.email_service import EmailService

products_bp = Blueprint('products', __name__, url_prefix='/api/products')

# Initialize email service
email_service = EmailService()


def _get_products_collection():
    """Get MongoDB products collection"""
    from flask import current_app
    return current_app.config.get('db_products')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


def _get_reviews_collection():
    """Get MongoDB reviews collection"""
    from flask import current_app
    return current_app.config.get('db_reviews')


def _send_product_notification_email(user_doc: dict, product_name: str, action: str, reason: str = None, changes: list = None):
    """Send email notification to product owner about product changes"""
    user_email = user_doc.get('email')
    user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip() or 'Seller'
    
    if action == 'updated':
        subject = f"Your Product Has Been Updated - {product_name}"
        title = "📝 Product Updated"
        main_color = "#2196F3"
        message = "Your product listing has been modified by an administrator."
        changes_html = ""
        if changes:
            changes_list = "".join([f"<li style='margin: 5px 0; color: #424242;'>{change}</li>" for change in changes])
            changes_html = f"""
            <div style="background-color: #E3F2FD; border-left: 4px solid #2196F3; padding: 15px; margin: 20px 0; border-radius: 4px;">
                <p style="margin: 0 0 10px 0; font-weight: bold; color: #1565C0;">Changes Made:</p>
                <ul style="margin: 0; padding-left: 20px;">{changes_list}</ul>
            </div>
            """
    elif action == 'deleted':
        subject = f"Your Product Has Been Removed - {product_name}"
        title = "🗑️ Product Removed"
        main_color = "#D32F2F"
        message = "Your product listing has been removed from the marketplace by an administrator."
        changes_html = ""
        if reason:
            changes_html = f"""
            <div style="background-color: #FFEBEE; border-left: 4px solid #D32F2F; padding: 15px; margin: 20px 0; border-radius: 4px;">
                <p style="margin: 0; color: #C62828;"><strong>Reason:</strong> {reason}</p>
            </div>
            """
    else:
        return False
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #2E7D32 0%, #4CAF50 100%); padding: 30px; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px;">🌿 Bignay Marketplace</h1>
            </div>
            <div style="background-color: {main_color}; padding: 15px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 18px;">{title}</h2>
            </div>
            <div style="padding: 30px;">
                <p style="font-size: 16px; color: #212121;">Hello <strong>{user_name}</strong>,</p>
                <p style="font-size: 15px; color: #424242; line-height: 1.6;">{message}</p>
                <div style="background-color: #F5F5F5; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <p style="margin: 0; color: #212121;"><strong>Product:</strong> {product_name}</p>
                </div>
                {changes_html}
                <p style="font-size: 14px; color: #757575; margin-top: 30px;">
                    If you have any questions about this action, please contact our support team.
                </p>
            </div>
            <div style="background-color: #f5f5f5; padding: 20px; text-align: center;">
                <p style="font-size: 12px; color: #757575; margin: 0;">
                    🌿 Bignay Marketplace - Thank you for being a seller!
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_body = f"""
{title}

Hello {user_name},

{message}

Product: {product_name}

If you have any questions, please contact our support team.

Bignay Marketplace
    """
    
    return email_service.send_email(
        to_email=user_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body
    )


# Public routes

@products_bp.route('/', methods=['GET'])
def list_products():
    """List all active products with filtering and pagination"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        category = request.args.get('category')
        search = request.args.get('search', '').strip()
        min_price = request.args.get('min_price', type=float)
        max_price = request.args.get('max_price', type=float)
        in_stock = request.args.get('in_stock')
        sort_by = request.args.get('sort', 'created_at')
        sort_order = request.args.get('order', 'desc')
        
        # Build query
        query = {'is_active': True}
        
        if category:
            query['category'] = category
        
        if search:
            query['$or'] = [
                {'name': {'$regex': search, '$options': 'i'}},
                {'description': {'$regex': search, '$options': 'i'}},
                {'tags': {'$regex': search, '$options': 'i'}},
            ]
        
        if min_price is not None:
            query['price'] = {'$gte': min_price}
        
        if max_price is not None:
            if 'price' in query:
                query['price']['$lte'] = max_price
            else:
                query['price'] = {'$lte': max_price}
        
        if in_stock == 'true':
            query['stock'] = {'$gt': 0}
        
        # Sort options
        sort_field = 'created_at'
        if sort_by == 'price':
            sort_field = 'price'
        elif sort_by == 'rating':
            sort_field = 'average_rating'
        elif sort_by == 'sales':
            sort_field = 'sales_count'
        elif sort_by == 'views':
            sort_field = 'views'
        
        sort_direction = -1 if sort_order == 'desc' else 1
        
        # Get products
        cursor = products_collection.find(query).skip(skip).limit(limit).sort(sort_field, sort_direction)
        total = products_collection.count_documents(query)
        
        # Get reviews collection to fetch latest review for each product
        reviews_collection = _get_reviews_collection()
        
        products = []
        for doc in cursor:
            product = Product.from_dict(doc)
            product._id = str(doc['_id'])
            product_dict = product.to_public_dict()
            
            # Fetch the latest review for this product
            if reviews_collection is not None:
                latest_review = reviews_collection.find_one(
                    {'product_id': str(doc['_id']), 'is_active': True},
                    sort=[('created_at', -1)]
                )
                if latest_review:
                    product_dict['latest_review'] = {
                        'rating': latest_review.get('rating', 0),
                        'comment': latest_review.get('comment', ''),
                        'comment_filtered': latest_review.get('comment_filtered', latest_review.get('comment', '')),
                        'user_name': latest_review.get('user_name', 'Anonymous'),
                        'created_at': latest_review.get('created_at').isoformat() if latest_review.get('created_at') else None
                    }
            
            products.append(product_dict)
        
        return jsonify({
            'ok': True,
            'products': products,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@products_bp.route('/featured', methods=['GET'])
def get_featured_products():
    """Get featured products for carousel sections"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        limit = int(request.args.get('limit', 10))
        
        # Recently added
        recent = list(products_collection.find(
            {'is_active': True, 'stock': {'$gt': 0}}
        ).sort('created_at', -1).limit(limit))
        
        # Most popular (by sales)
        popular = list(products_collection.find(
            {'is_active': True, 'stock': {'$gt': 0}}
        ).sort('sales_count', -1).limit(limit))
        
        # Highest rated
        top_rated = list(products_collection.find(
            {'is_active': True, 'stock': {'$gt': 0}, 'review_count': {'$gt': 0}}
        ).sort('average_rating', -1).limit(limit))
        
        # Most viewed
        trending = list(products_collection.find(
            {'is_active': True, 'stock': {'$gt': 0}}
        ).sort('views', -1).limit(limit))
        
        def convert_products(docs):
            products = []
            for doc in docs:
                product = Product.from_dict(doc)
                product._id = str(doc['_id'])
                products.append(product.to_public_dict())
            return products
        
        return jsonify({
            'ok': True,
            'featured': {
                'recently_added': convert_products(recent),
                'most_popular': convert_products(popular),
                'top_rated': convert_products(top_rated),
                'trending': convert_products(trending),
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@products_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all product categories"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get distinct categories
        categories = products_collection.distinct('category', {'is_active': True})
        
        # Get count for each category
        category_counts = []
        for cat in categories:
            count = products_collection.count_documents({'category': cat, 'is_active': True})
            category_counts.append({'name': cat, 'count': count})
        
        return jsonify({
            'ok': True,
            'categories': category_counts
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@products_bp.route('/<product_id>', methods=['GET'])
def get_product(product_id: str):
    """Get single product by ID"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Increment view count
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {'$inc': {'views': 1}}
        )
        
        product = Product.from_dict(product_doc)
        product._id = str(product_doc['_id'])
        
        return jsonify({
            'ok': True,
            'product': product.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Admin routes

@products_bp.route('/', methods=['POST'])
@require_admin
def create_product():
    """Create a new product (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['name', 'description', 'price', 'stock', 'category']
        is_valid, missing = validate_required_fields(data, required)
        if not is_valid:
            return jsonify({'ok': False, 'errors': missing}), 400
        
        # Validate price
        is_valid, error = validate_positive_number(data['price'], 'Price', min_val=0.01)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Validate stock
        is_valid, error = validate_positive_number(data['stock'], 'Stock', min_val=0)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Get seller info (current admin)
        users_collection = _get_users_collection()
        admin_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        seller_name = f"{admin_doc.get('first_name', '')} {admin_doc.get('last_name', '')}".strip()
        
        # Handle image uploads
        images = []
        if 'images' in data and data['images']:
            print(f"[Products] Received {len(data['images'])} images to upload")
            results = upload_multiple_images(data['images'], folder='products')
            for result in results:
                if result['success']:
                    images.append(result['url'])
                    print(f"[Products] Image uploaded successfully: {result['url']}")
                else:
                    print(f"[Products] Image upload failed: {result.get('error', 'Unknown error')}")
            print(f"[Products] Total images uploaded successfully: {len(images)}")
        else:
            print("[Products] No images provided in request")
        
        # Create product
        product = Product(
            name=data['name'].strip(),
            description=data['description'].strip(),
            price=float(data['price']),
            stock=int(data['stock']),
            category=data['category'].strip(),
            seller_id=request.user_info['user_id'],
            seller_name=seller_name or 'Admin',
            images=images,
            unit=data.get('unit', 'per item').strip(),
            location=data.get('location', '').strip(),
            quality=data.get('quality', 'Standard').strip(),
            tags=data.get('tags', []),
        )
        
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        result = products_collection.insert_one(product.to_dict())
        product._id = str(result.inserted_id)
        
        return jsonify({
            'ok': True,
            'message': 'Product created successfully',
            'product': product.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to create product: {str(e)}'}), 500


@products_bp.route('/<product_id>', methods=['PUT'])
@require_admin
def update_product(product_id: str):
    """Update a product (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Build update document
        update_fields = {}
        
        if 'name' in data:
            update_fields['name'] = data['name'].strip()
        
        if 'description' in data:
            update_fields['description'] = data['description'].strip()
        
        if 'price' in data:
            is_valid, error = validate_positive_number(data['price'], 'Price', min_val=0.01)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['price'] = float(data['price'])
        
        if 'stock' in data:
            is_valid, error = validate_positive_number(data['stock'], 'Stock', min_val=0)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['stock'] = int(data['stock'])
        
        if 'category' in data:
            update_fields['category'] = data['category'].strip()
        
        if 'unit' in data:
            update_fields['unit'] = data['unit'].strip()
        
        if 'location' in data:
            update_fields['location'] = data['location'].strip()
        
        if 'quality' in data:
            update_fields['quality'] = data['quality'].strip()
        
        if 'tags' in data:
            update_fields['tags'] = data['tags']
        
        if 'is_active' in data:
            update_fields['is_active'] = bool(data['is_active'])
        
        # Handle new images
        if 'new_images' in data and data['new_images']:
            results = upload_multiple_images(data['new_images'], folder='products')
            new_urls = [r['url'] for r in results if r['success']]
            current_images = product_doc.get('images', [])
            update_fields['images'] = current_images + new_urls
        
        # Replace all images
        if 'images' in data:
            update_fields['images'] = data['images']
        
        if not update_fields:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400
        
        update_fields['updated_at'] = datetime.now(timezone.utc)
        
        # Track changes for email notification
        changes = []
        for field, new_value in update_fields.items():
            if field == 'updated_at':
                continue
            old_value = product_doc.get(field)
            if old_value != new_value:
                if field == 'price':
                    changes.append(f"Price: ₱{old_value} → ₱{new_value}")
                elif field == 'stock':
                    changes.append(f"Stock: {old_value} → {new_value}")
                elif field == 'name':
                    changes.append(f"Name: {old_value} → {new_value}")
                elif field == 'category':
                    changes.append(f"Category: {old_value} → {new_value}")
                elif field == 'is_active':
                    changes.append(f"Status: {'Active' if new_value else 'Inactive'}")
                elif field == 'images':
                    changes.append("Product images updated")
                else:
                    changes.append(f"{field.replace('_', ' ').title()} updated")
        
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {'$set': update_fields}
        )
        
        # Send email notification to product owner if product has a seller
        seller_id = product_doc.get('seller_id')
        if seller_id and changes:
            users_collection = _get_users_collection()
            if users_collection:
                seller_doc = users_collection.find_one({'_id': ObjectId(seller_id)})
                if seller_doc:
                    _send_product_notification_email(
                        user_doc=seller_doc,
                        product_name=product_doc.get('name', 'Your product'),
                        action='updated',
                        changes=changes
                    )
        
        # Get updated product
        updated_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        product = Product.from_dict(updated_doc)
        product._id = str(updated_doc['_id'])
        
        return jsonify({
            'ok': True,
            'message': 'Product updated successfully',
            'product': product.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update product: {str(e)}'}), 500


@products_bp.route('/<product_id>', methods=['DELETE'])
@require_admin
def delete_product(product_id: str):
    """Delete a product (admin only)"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Get reason for deletion from request body
        data = request.get_json() or {}
        deletion_reason = data.get('reason', 'Product removed by administrator')
        
        # Send email notification to product owner before deleting
        seller_id = product_doc.get('seller_id')
        if seller_id:
            users_collection = _get_users_collection()
            if users_collection:
                seller_doc = users_collection.find_one({'_id': ObjectId(seller_id)})
                if seller_doc:
                    _send_product_notification_email(
                        user_doc=seller_doc,
                        product_name=product_doc.get('name', 'Your product'),
                        action='deleted',
                        reason=deletion_reason
                    )
        
        # Soft delete (deactivate) instead of hard delete
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {'$set': {
                'is_active': False,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': 'Product deleted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to delete product: {str(e)}'}), 500


@products_bp.route('/<product_id>/images', methods=['POST'])
@require_admin
def add_product_images(product_id: str):
    """Add images to a product (admin only)"""
    try:
        data = request.get_json()
        if not data or 'images' not in data:
            return jsonify({'ok': False, 'error': 'Images data required'}), 400
        
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Upload images
        results = upload_multiple_images(data['images'], folder='products')
        new_urls = [r['url'] for r in results if r['success']]
        
        if not new_urls:
            return jsonify({'ok': False, 'error': 'No images were uploaded successfully'}), 400
        
        # Add to existing images
        current_images = product_doc.get('images', [])
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {
                '$set': {
                    'images': current_images + new_urls,
                    'updated_at': datetime.now(timezone.utc)
                }
            }
        )
        
        return jsonify({
            'ok': True,
            'message': f'{len(new_urls)} image(s) added successfully',
            'images': current_images + new_urls
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@products_bp.route('/<product_id>/images/<int:image_index>', methods=['DELETE'])
@require_admin
def remove_product_image(product_id: str, image_index: int):
    """Remove an image from a product (admin only)"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        images = product_doc.get('images', [])
        if image_index < 0 or image_index >= len(images):
            return jsonify({'ok': False, 'error': 'Invalid image index'}), 400
        
        # Remove image from list
        images.pop(image_index)
        
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {
                '$set': {
                    'images': images,
                    'updated_at': datetime.now(timezone.utc)
                }
            }
        )
        
        return jsonify({
            'ok': True,
            'message': 'Image removed successfully',
            'images': images
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================
# User Product Routes (for selling their own products)
# ============================================

@products_bp.route('/user/my-products', methods=['GET'])
@require_auth
def get_my_products():
    """Get current user's products"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_id = request.user_info['user_id']
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        search = request.args.get('search', '').strip()
        category = request.args.get('category')
        
        query = {'seller_id': user_id}
        
        if search:
            query['$or'] = [
                {'name': {'$regex': search, '$options': 'i'}},
                {'description': {'$regex': search, '$options': 'i'}},
            ]
        
        if category and category != 'all':
            query['category'] = category
        
        cursor = products_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = products_collection.count_documents(query)
        
        products = []
        for doc in cursor:
            product = Product.from_dict(doc)
            product._id = str(doc['_id'])
            products.append(product.to_public_dict())
        
        return jsonify({
            'ok': True,
            'products': products,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@products_bp.route('/user/create', methods=['POST'])
@require_auth
def user_create_product():
    """Create a new product (for regular users to sell)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['name', 'description', 'price', 'stock', 'category']
        is_valid, missing = validate_required_fields(data, required)
        if not is_valid:
            return jsonify({'ok': False, 'errors': missing}), 400
        
        # Validate price
        is_valid, error = validate_positive_number(data['price'], 'Price', min_val=0.01)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Validate stock
        is_valid, error = validate_positive_number(data['stock'], 'Stock', min_val=0)
        if not is_valid:
            return jsonify({'ok': False, 'error': error}), 400
        
        # Get seller info (current user)
        users_collection = _get_users_collection()
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        seller_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
        
        # Handle image uploads
        images = []
        if 'images' in data and data['images']:
            print(f"[Products] User uploading {len(data['images'])} images")
            results = upload_multiple_images(data['images'], folder='products')
            for result in results:
                if result['success']:
                    images.append(result['url'])
        
        # Create product
        product = Product(
            name=data['name'].strip(),
            description=data['description'].strip(),
            price=float(data['price']),
            stock=int(data['stock']),
            category=data['category'].strip(),
            seller_id=request.user_info['user_id'],
            seller_name=seller_name or 'User',
            images=images,
            unit=data.get('unit', 'per item').strip(),
            location=data.get('location', '').strip(),
            quality=data.get('quality', 'Standard').strip(),
            tags=data.get('tags', []),
        )
        
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        result = products_collection.insert_one(product.to_dict())
        product._id = str(result.inserted_id)
        
        return jsonify({
            'ok': True,
            'message': 'Product created successfully',
            'product': product.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to create product: {str(e)}'}), 500


@products_bp.route('/user/<product_id>', methods=['PUT'])
@require_auth
def user_update_product(product_id: str):
    """Update user's own product"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Verify ownership
        if product_doc.get('seller_id') != request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'You can only edit your own products'}), 403
        
        # Build update document
        update_fields = {}
        
        if 'name' in data:
            update_fields['name'] = data['name'].strip()
        
        if 'description' in data:
            update_fields['description'] = data['description'].strip()
        
        if 'price' in data:
            is_valid, error = validate_positive_number(data['price'], 'Price', min_val=0.01)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['price'] = float(data['price'])
        
        if 'stock' in data:
            is_valid, error = validate_positive_number(data['stock'], 'Stock', min_val=0)
            if not is_valid:
                return jsonify({'ok': False, 'error': error}), 400
            update_fields['stock'] = int(data['stock'])
        
        if 'category' in data:
            update_fields['category'] = data['category'].strip()
        
        if 'unit' in data:
            update_fields['unit'] = data['unit'].strip()
        
        if 'location' in data:
            update_fields['location'] = data['location'].strip()
        
        if 'quality' in data:
            update_fields['quality'] = data['quality'].strip()
        
        if 'tags' in data:
            update_fields['tags'] = data['tags']
        
        if 'is_active' in data:
            update_fields['is_active'] = bool(data['is_active'])
        
        # Handle new images
        if 'new_images' in data and data['new_images']:
            results = upload_multiple_images(data['new_images'], folder='products')
            new_urls = [r['url'] for r in results if r['success']]
            current_images = product_doc.get('images', [])
            update_fields['images'] = current_images + new_urls
        
        # Replace all images
        if 'images' in data:
            update_fields['images'] = data['images']
        
        if not update_fields:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400
        
        update_fields['updated_at'] = datetime.now(timezone.utc)
        
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {'$set': update_fields}
        )
        
        # Get updated product
        updated_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        product = Product.from_dict(updated_doc)
        product._id = str(updated_doc['_id'])
        
        return jsonify({
            'ok': True,
            'message': 'Product updated successfully',
            'product': product.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update product: {str(e)}'}), 500


@products_bp.route('/user/<product_id>', methods=['DELETE'])
@require_auth
def user_delete_product(product_id: str):
    """Delete user's own product (soft delete)"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        product_doc = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_doc:
            return jsonify({'ok': False, 'error': 'Product not found'}), 404
        
        # Verify ownership
        if product_doc.get('seller_id') != request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'You can only delete your own products'}), 403
        
        # Soft delete (deactivate)
        products_collection.update_one(
            {'_id': ObjectId(product_id)},
            {'$set': {
                'is_active': False,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': 'Product deleted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to delete product: {str(e)}'}), 500


# Admin product listing with all products (including inactive)
@products_bp.route('/admin/all', methods=['GET'])
@require_admin
def admin_list_products():
    """List all products including inactive (admin only)"""
    try:
        products_collection = _get_products_collection()
        if products_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        is_active = request.args.get('is_active')
        search = request.args.get('search', '').strip()
        
        query = {}
        if is_active is not None:
            query['is_active'] = is_active.lower() == 'true'
        
        if search:
            query['$or'] = [
                {'name': {'$regex': search, '$options': 'i'}},
                {'description': {'$regex': search, '$options': 'i'}},
            ]
        
        cursor = products_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = products_collection.count_documents(query)
        
        products = []
        for doc in cursor:
            product = Product.from_dict(doc)
            product._id = str(doc['_id'])
            products.append(product.to_public_dict())
        
        return jsonify({
            'ok': True,
            'products': products,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
