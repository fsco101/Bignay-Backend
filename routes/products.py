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

products_bp = Blueprint('products', __name__, url_prefix='/api/products')


def _get_products_collection():
    """Get MongoDB products collection"""
    from flask import current_app
    return current_app.config.get('db_products')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


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
