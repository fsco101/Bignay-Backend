"""
Forum/Blog Routes
Handles CRUD operations for forum/blog posts
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.forum import ForumPost, FORUM_CATEGORIES
from routes.auth import require_auth, require_admin, get_current_user
from utils.validators import validate_required_fields
from utils.cloudinary_helper import upload_image, upload_multiple_images

forum_bp = Blueprint('forum', __name__, url_prefix='/api/forum')


def _get_forum_collection():
    """Get MongoDB forum collection"""
    from flask import current_app
    return current_app.config.get('db_forum')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


# ==================== PUBLIC ROUTES ====================

@forum_bp.route('/posts', methods=['GET'])
def list_posts():
    """List all published posts with filtering and pagination"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        # Filters
        category = request.args.get('category')
        search = request.args.get('search', '').strip()
        featured = request.args.get('featured')
        
        # Build query - only published posts for public
        query = {'is_published': True}
        
        if category and category != 'all':
            query['category'] = category
        
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'content': {'$regex': search, '$options': 'i'}},
                {'tags': {'$regex': search, '$options': 'i'}},
            ]
        
        if featured == 'true':
            query['is_featured'] = True
        
        # Sort: pinned first, then by published_at desc
        cursor = forum_collection.find(query).sort([
            ('is_pinned', -1),
            ('published_at', -1)
        ]).skip(skip).limit(limit)
        
        total = forum_collection.count_documents(query)
        
        posts = []
        for doc in cursor:
            post = ForumPost.from_dict(doc)
            posts.append(post.to_list_dict())
        
        return jsonify({
            'ok': True,
            'posts': posts,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@forum_bp.route('/posts/<post_id>', methods=['GET'])
def get_post(post_id: str):
    """Get a single post by ID"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        # Check if published (unless admin)
        user = get_current_user()
        is_admin = user and user.get('role') == 'admin'
        
        if not post_doc.get('is_published') and not is_admin:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        # Increment view count
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$inc': {'views': 1}}
        )
        
        post = ForumPost.from_dict(post_doc)
        
        return jsonify({
            'ok': True,
            'post': post.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@forum_bp.route('/posts/<post_id>/like', methods=['POST'])
def like_post(post_id: str):
    """Like/unlike a post"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        if not post_doc.get('is_published'):
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        # Increment like count
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$inc': {'likes': 1}}
        )
        
        return jsonify({
            'ok': True,
            'message': 'Post liked successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@forum_bp.route('/featured', methods=['GET'])
def get_featured_posts():
    """Get featured posts for home page"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        limit = int(request.args.get('limit', 5))
        
        # Get featured posts
        featured = list(forum_collection.find({
            'is_published': True,
            'is_featured': True
        }).sort('published_at', -1).limit(limit))
        
        # Get pinned posts
        pinned = list(forum_collection.find({
            'is_published': True,
            'is_pinned': True
        }).sort('published_at', -1).limit(limit))
        
        # Get latest by category
        categories_data = {}
        for cat in FORUM_CATEGORIES:
            cat_posts = list(forum_collection.find({
                'is_published': True,
                'category': cat['id']
            }).sort('published_at', -1).limit(3))
            categories_data[cat['id']] = [
                ForumPost.from_dict(p).to_list_dict() for p in cat_posts
            ]
        
        return jsonify({
            'ok': True,
            'featured': [ForumPost.from_dict(p).to_list_dict() for p in featured],
            'pinned': [ForumPost.from_dict(p).to_list_dict() for p in pinned],
            'by_category': categories_data,
            'categories': FORUM_CATEGORIES
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@forum_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all forum categories"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({
                'ok': True,
                'categories': FORUM_CATEGORIES
            })
        
        # Get post count per category
        categories_with_count = []
        for cat in FORUM_CATEGORIES:
            count = forum_collection.count_documents({
                'category': cat['id'],
                'is_published': True
            })
            categories_with_count.append({
                **cat,
                'post_count': count
            })
        
        return jsonify({
            'ok': True,
            'categories': categories_with_count
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ==================== ADMIN ROUTES ====================

@forum_bp.route('/admin/posts', methods=['GET'])
@require_admin
def admin_list_posts():
    """List all posts for admin (including unpublished)"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        category = request.args.get('category')
        is_published = request.args.get('is_published')
        search = request.args.get('search', '').strip()
        
        query = {}
        
        if category and category != 'all':
            query['category'] = category
        
        if is_published is not None:
            query['is_published'] = is_published.lower() == 'true'
        
        if search:
            query['$or'] = [
                {'title': {'$regex': search, '$options': 'i'}},
                {'content': {'$regex': search, '$options': 'i'}},
            ]
        
        cursor = forum_collection.find(query).sort('created_at', -1).skip(skip).limit(limit)
        total = forum_collection.count_documents(query)
        
        posts = []
        for doc in cursor:
            post = ForumPost.from_dict(doc)
            posts.append(post.to_public_dict())
        
        return jsonify({
            'ok': True,
            'posts': posts,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@forum_bp.route('/admin/posts', methods=['POST'])
@require_admin
def create_post():
    """Create a new forum post"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['title', 'content', 'category']
        is_valid, missing = validate_required_fields(data, required)
        if not is_valid:
            return jsonify({'ok': False, 'errors': missing}), 400
        
        # Validate category
        valid_categories = [cat['id'] for cat in FORUM_CATEGORIES]
        if data['category'] not in valid_categories:
            return jsonify({'ok': False, 'error': f'Invalid category. Must be one of: {valid_categories}'}), 400
        
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Handle cover image upload
        cover_image = ''
        if data.get('cover_image') and data['cover_image'].startswith('data:'):
            success, url_or_error, _ = upload_image(data['cover_image'], folder='forum')
            if success:
                cover_image = url_or_error
        elif data.get('cover_image'):
            cover_image = data['cover_image']
        
        # Handle additional images
        images = []
        if data.get('images'):
            for img in data['images']:
                if img.startswith('data:'):
                    success, url_or_error, _ = upload_image(img, folder='forum')
                    if success:
                        images.append(url_or_error)
                else:
                    images.append(img)
        
        # Get author info
        user_id = request.user_info['user_id']
        users_collection = _get_users_collection()
        author_name = 'Admin'
        if users_collection is not None:
            user_doc = users_collection.find_one({'_id': ObjectId(user_id)})
            if user_doc:
                author_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip() or 'Admin'
        
        # Create excerpt if not provided
        excerpt = data.get('excerpt', '')
        if not excerpt and data.get('content'):
            # Strip HTML and take first 200 chars
            import re
            clean_content = re.sub(r'<[^>]+>', '', data['content'])
            excerpt = clean_content[:200] + '...' if len(clean_content) > 200 else clean_content
        
        # Determine published_at
        is_published = data.get('is_published', False)
        published_at = datetime.now(timezone.utc) if is_published else None
        
        post = ForumPost(
            title=data['title'],
            content=data['content'],
            category=data['category'],
            author_id=user_id,
            author_name=author_name,
            excerpt=excerpt,
            cover_image=cover_image,
            images=images,
            tags=data.get('tags', []),
            is_published=is_published,
            is_featured=data.get('is_featured', False),
            is_pinned=data.get('is_pinned', False),
            published_at=published_at,
        )
        
        result = forum_collection.insert_one(post.to_dict())
        post._id = str(result.inserted_id)
        
        return jsonify({
            'ok': True,
            'message': 'Post created successfully',
            'post': post.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to create post: {str(e)}'}), 500


@forum_bp.route('/admin/posts/<post_id>', methods=['PUT'])
@require_admin
def update_post(post_id: str):
    """Update an existing forum post"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        # Build update dict
        update_data = {'updated_at': datetime.now(timezone.utc)}
        
        allowed_fields = ['title', 'content', 'category', 'excerpt', 'tags', 
                          'is_published', 'is_featured', 'is_pinned']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        # Validate category if provided
        if 'category' in data:
            valid_categories = [cat['id'] for cat in FORUM_CATEGORIES]
            if data['category'] not in valid_categories:
                return jsonify({'ok': False, 'error': f'Invalid category'}), 400
        
        # Handle cover image update
        if 'cover_image' in data:
            if data['cover_image'] and data['cover_image'].startswith('data:'):
                success, url_or_error, _ = upload_image(data['cover_image'], folder='forum')
                if success:
                    update_data['cover_image'] = url_or_error
            else:
                update_data['cover_image'] = data['cover_image'] or ''
        
        # Handle images update
        if 'images' in data:
            images = []
            for img in data['images']:
                if img.startswith('data:'):
                    success, url_or_error, _ = upload_image(img, folder='forum')
                    if success:
                        images.append(url_or_error)
                else:
                    images.append(img)
            update_data['images'] = images
        
        # Update published_at if publishing for the first time
        if data.get('is_published') and not post_doc.get('published_at'):
            update_data['published_at'] = datetime.now(timezone.utc)
        
        # Update excerpt if content changed and no custom excerpt
        if 'content' in data and 'excerpt' not in data:
            import re
            clean_content = re.sub(r'<[^>]+>', '', data['content'])
            update_data['excerpt'] = clean_content[:200] + '...' if len(clean_content) > 200 else clean_content
        
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$set': update_data}
        )
        
        # Get updated post
        updated_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        post = ForumPost.from_dict(updated_doc)
        
        return jsonify({
            'ok': True,
            'message': 'Post updated successfully',
            'post': post.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update post: {str(e)}'}), 500


@forum_bp.route('/admin/posts/<post_id>', methods=['DELETE'])
@require_admin
def delete_post(post_id: str):
    """Delete a forum post"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        # Hard delete
        forum_collection.delete_one({'_id': ObjectId(post_id)})
        
        return jsonify({
            'ok': True,
            'message': 'Post deleted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to delete post: {str(e)}'}), 500


@forum_bp.route('/admin/posts/<post_id>/publish', methods=['PUT'])
@require_admin
def toggle_publish(post_id: str):
    """Toggle publish status of a post"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        is_published = not post_doc.get('is_published', False)
        update_data = {
            'is_published': is_published,
            'updated_at': datetime.now(timezone.utc)
        }
        
        # Set published_at if publishing
        if is_published and not post_doc.get('published_at'):
            update_data['published_at'] = datetime.now(timezone.utc)
        
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$set': update_data}
        )
        
        return jsonify({
            'ok': True,
            'message': f'Post {"published" if is_published else "unpublished"} successfully',
            'is_published': is_published
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update post: {str(e)}'}), 500


@forum_bp.route('/admin/posts/<post_id>/feature', methods=['PUT'])
@require_admin
def toggle_feature(post_id: str):
    """Toggle featured status of a post"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        is_featured = not post_doc.get('is_featured', False)
        
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$set': {
                'is_featured': is_featured,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': f'Post {"featured" if is_featured else "unfeatured"} successfully',
            'is_featured': is_featured
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update post: {str(e)}'}), 500


@forum_bp.route('/admin/posts/<post_id>/pin', methods=['PUT'])
@require_admin
def toggle_pin(post_id: str):
    """Toggle pinned status of a post"""
    try:
        forum_collection = _get_forum_collection()
        if forum_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        post_doc = forum_collection.find_one({'_id': ObjectId(post_id)})
        if not post_doc:
            return jsonify({'ok': False, 'error': 'Post not found'}), 404
        
        is_pinned = not post_doc.get('is_pinned', False)
        
        forum_collection.update_one(
            {'_id': ObjectId(post_id)},
            {'$set': {
                'is_pinned': is_pinned,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': f'Post {"pinned" if is_pinned else "unpinned"} successfully',
            'is_pinned': is_pinned
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Failed to update post: {str(e)}'}), 500
