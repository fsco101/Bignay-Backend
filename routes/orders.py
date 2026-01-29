"""
Orders Routes
Handles checkout and order management
"""

from __future__ import annotations
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from bson import ObjectId

from models.order import Order, OrderItem, OrderStatus
from models.product import Product
from routes.auth import require_auth, require_admin, get_current_user
from utils.validators import validate_required_fields
from utils.email_service import get_email_service

orders_bp = Blueprint('orders', __name__, url_prefix='/api/orders')


def _get_orders_collection():
    """Get MongoDB orders collection"""
    from flask import current_app
    return current_app.config.get('db_orders')


def _get_products_collection():
    """Get MongoDB products collection"""
    from flask import current_app
    return current_app.config.get('db_products')


def _get_users_collection():
    """Get MongoDB users collection"""
    from flask import current_app
    return current_app.config.get('db_users')


@orders_bp.route('/checkout', methods=['POST'])
@require_auth
def checkout():
    """
    Create a new order (checkout)
    Expects: items (array of {product_id, quantity}), shipping info
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400
        
        # Validate required fields
        required = ['items', 'shipping_address', 'shipping_city', 'shipping_phone']
        is_valid, missing = validate_required_fields(data, required)
        if not is_valid:
            return jsonify({'ok': False, 'errors': missing}), 400
        
        items_data = data.get('items', [])
        if not items_data:
            return jsonify({'ok': False, 'error': 'Cart is empty'}), 400
        
        products_collection = _get_products_collection()
        users_collection = _get_users_collection()
        orders_collection = _get_orders_collection()
        
        if any(c is None for c in [products_collection, users_collection, orders_collection]):
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get user info
        user_doc = users_collection.find_one({'_id': ObjectId(request.user_info['user_id'])})
        if not user_doc:
            return jsonify({'ok': False, 'error': 'User not found'}), 404
        
        user_name = f"{user_doc.get('first_name', '')} {user_doc.get('last_name', '')}".strip()
        
        # Validate items and check stock
        order_items = []
        total_amount = 0
        stock_updates = []
        
        for item in items_data:
            product_id = item.get('product_id')
            quantity = int(item.get('quantity', 1))
            
            if quantity < 1:
                return jsonify({'ok': False, 'error': 'Quantity must be at least 1'}), 400
            
            # Get product
            product_doc = products_collection.find_one({'_id': ObjectId(product_id), 'is_active': True})
            if not product_doc:
                return jsonify({'ok': False, 'error': f'Product not found: {product_id}'}), 404
            
            # Check stock
            if product_doc.get('stock', 0) < quantity:
                return jsonify({
                    'ok': False, 
                    'error': f"Not enough stock for {product_doc['name']}. Available: {product_doc.get('stock', 0)}"
                }), 400
            
            # Calculate subtotal
            unit_price = float(product_doc.get('price', 0))
            subtotal = unit_price * quantity
            total_amount += subtotal
            
            # Create order item
            order_item = OrderItem(
                product_id=str(product_doc['_id']),
                product_name=product_doc.get('name', ''),
                product_image=product_doc.get('images', [''])[0] if product_doc.get('images') else '',
                quantity=quantity,
                unit_price=unit_price,
                subtotal=subtotal,
                seller_id=product_doc.get('seller_id', ''),
                seller_name=product_doc.get('seller_name', ''),
            )
            order_items.append(order_item)
            
            # Prepare stock update
            stock_updates.append({
                'product_id': ObjectId(product_id),
                'quantity': quantity
            })
        
        # Create order
        order = Order(
            user_id=request.user_info['user_id'],
            user_email=user_doc.get('email', ''),
            user_name=user_name,
            items=order_items,
            total_amount=total_amount,
            status=OrderStatus.PENDING,
            shipping_address=data.get('shipping_address', '').strip(),
            shipping_city=data.get('shipping_city', '').strip(),
            shipping_province=data.get('shipping_province', '').strip(),
            shipping_postal_code=data.get('shipping_postal_code', '').strip(),
            shipping_phone=data.get('shipping_phone', '').strip(),
            payment_method=data.get('payment_method', 'cash_on_delivery'),
            notes=data.get('notes', '').strip(),
        )
        
        # Insert order
        result = orders_collection.insert_one(order.to_dict())
        order._id = str(result.inserted_id)
        
        # Update stock for each product
        for update in stock_updates:
            products_collection.update_one(
                {'_id': update['product_id']},
                {
                    '$inc': {
                        'stock': -update['quantity'],
                        'sales_count': update['quantity']
                    },
                    '$set': {'updated_at': datetime.now(timezone.utc)}
                }
            )
        
        # Send order confirmation email with PDF receipt
        try:
            email_service = get_email_service()
            email_service.send_order_receipt(order.to_public_dict(), status_changed=False)
        except Exception as email_error:
            print(f"[Orders] Failed to send confirmation email: {email_error}")
        
        return jsonify({
            'ok': True,
            'message': 'Order placed successfully',
            'order': order.to_public_dict()
        }), 201
    
    except Exception as e:
        return jsonify({'ok': False, 'error': f'Checkout failed: {str(e)}'}), 500


@orders_bp.route('/', methods=['GET'])
@require_auth
def get_my_orders():
    """Get current user's orders"""
    try:
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filter by status
        status = request.args.get('status')
        
        query = {'user_id': request.user_info['user_id']}
        if status:
            query['status'] = status
        
        cursor = orders_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = orders_collection.count_documents(query)
        
        orders = []
        for doc in cursor:
            order = Order.from_dict(doc)
            order._id = str(doc['_id'])
            orders.append(order.to_public_dict())
        
        return jsonify({
            'ok': True,
            'orders': orders,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/<order_id>', methods=['GET'])
@require_auth
def get_order(order_id: str):
    """Get single order by ID"""
    try:
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        order_doc = orders_collection.find_one({'_id': ObjectId(order_id)})
        if not order_doc:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        # Check ownership (unless admin)
        if (order_doc.get('user_id') != request.user_info['user_id'] and 
            request.user_info.get('role') != 'admin'):
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        
        order = Order.from_dict(order_doc)
        order._id = str(order_doc['_id'])
        
        return jsonify({
            'ok': True,
            'order': order.to_public_dict()
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/<order_id>/cancel', methods=['POST'])
@require_auth
def cancel_order(order_id: str):
    """Cancel an order (only if pending)"""
    try:
        orders_collection = _get_orders_collection()
        products_collection = _get_products_collection()
        
        if any(c is None for c in [orders_collection, products_collection]):
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        order_doc = orders_collection.find_one({'_id': ObjectId(order_id)})
        if not order_doc:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        # Check ownership
        if order_doc.get('user_id') != request.user_info['user_id']:
            return jsonify({'ok': False, 'error': 'Access denied'}), 403
        
        # Can only cancel pending orders
        if order_doc.get('status') != 'pending':
            return jsonify({'ok': False, 'error': 'Can only cancel pending orders'}), 400
        
        # Restore stock
        for item in order_doc.get('items', []):
            products_collection.update_one(
                {'_id': ObjectId(item['product_id'])},
                {
                    '$inc': {
                        'stock': item['quantity'],
                        'sales_count': -item['quantity']
                    }
                }
            )
        
        # Update order status
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {
                'status': OrderStatus.CANCELLED.value,
                'updated_at': datetime.now(timezone.utc)
            }}
        )
        
        return jsonify({
            'ok': True,
            'message': 'Order cancelled successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Admin routes

@orders_bp.route('/admin/all', methods=['GET'])
@require_admin
def admin_list_orders():
    """List all orders (admin only)"""
    try:
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Pagination
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Filters
        status = request.args.get('status')
        user_id = request.args.get('user_id')
        
        query = {}
        if status:
            query['status'] = status
        if user_id:
            query['user_id'] = user_id
        
        cursor = orders_collection.find(query).skip(skip).limit(limit).sort('created_at', -1)
        total = orders_collection.count_documents(query)
        
        orders = []
        for doc in cursor:
            order = Order.from_dict(doc)
            order._id = str(doc['_id'])
            orders.append(order.to_public_dict())
        
        return jsonify({
            'ok': True,
            'orders': orders,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/admin/<order_id>/status', methods=['PUT'])
@require_admin
def update_order_status(order_id: str):
    """Update order status (admin only)"""
    try:
        data = request.get_json()
        if not data or 'status' not in data:
            return jsonify({'ok': False, 'error': 'Status required'}), 400
        
        new_status = data['status']
        valid_statuses = [s.value for s in OrderStatus]
        if new_status not in valid_statuses:
            return jsonify({'ok': False, 'error': f'Invalid status. Must be one of: {valid_statuses}'}), 400
        
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        update_data = {
            'status': new_status,
            'updated_at': datetime.now(timezone.utc)
        }
        
        if new_status == 'delivered':
            update_data['delivered_at'] = datetime.now(timezone.utc)
            update_data['payment_status'] = 'paid'
        
        result = orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': update_data}
        )
        
        if result.matched_count == 0:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        # Send status change email with PDF receipt
        try:
            order_doc = orders_collection.find_one({'_id': ObjectId(order_id)})
            if order_doc:
                order = Order.from_dict(order_doc)
                order._id = str(order_doc['_id'])
                
                order_data = order.to_public_dict()
                print(f"[Orders] Sending status update email for order {order_id} to {order_data.get('user_email')}")
                
                email_service = get_email_service()
                if email_service.enabled:
                    email_sent = email_service.send_order_receipt(order_data, status_changed=True)
                    if email_sent:
                        print(f"[Orders] Status change email sent successfully for order {order_id}")
                    else:
                        print(f"[Orders] Failed to send status change email for order {order_id}")
                else:
                    print(f"[Orders] Email service is disabled - skipping status change email")
        except Exception as email_error:
            print(f"[Orders] Failed to send status change email: {email_error}")
            import traceback
            traceback.print_exc()
        
        return jsonify({
            'ok': True,
            'message': f'Order status updated to {new_status}'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/admin/stats', methods=['GET'])
@require_admin
def get_order_stats():
    """Get order statistics (admin only)"""
    try:
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Count by status
        stats = {}
        for status in OrderStatus:
            stats[status.value] = orders_collection.count_documents({'status': status.value})
        
        # Total revenue (from delivered orders)
        pipeline = [
            {'$match': {'status': 'delivered'}},
            {'$group': {'_id': None, 'total': {'$sum': '$total_amount'}}}
        ]
        revenue_result = list(orders_collection.aggregate(pipeline))
        total_revenue = revenue_result[0]['total'] if revenue_result else 0
        
        # Total orders
        total_orders = orders_collection.count_documents({})
        
        return jsonify({
            'ok': True,
            'stats': {
                'by_status': stats,
                'total_orders': total_orders,
                'total_revenue': total_revenue
            }
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/<order_id>', methods=['DELETE'])
@require_auth
def delete_order(order_id: str):
    """Delete an order (only for delivered or cancelled orders)"""
    try:
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
        if not order:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        # Check ownership (unless admin)
        user_id = request.user_id
        is_admin = getattr(request, 'is_admin', False)
        
        if order['user_id'] != user_id and not is_admin:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
        
        # Only allow deletion of delivered or cancelled orders
        if order['status'] not in ['delivered', 'cancelled']:
            return jsonify({
                'ok': False, 
                'error': 'Can only delete delivered or cancelled orders'
            }), 400
        
        result = orders_collection.delete_one({'_id': ObjectId(order_id)})
        
        if result.deleted_count == 0:
            return jsonify({'ok': False, 'error': 'Failed to delete order'}), 500
        
        return jsonify({
            'ok': True,
            'message': 'Order deleted successfully'
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@orders_bp.route('/bulk-delete', methods=['POST'])
@require_auth
def bulk_delete_orders():
    """Delete multiple orders (only for delivered or cancelled orders)"""
    try:
        data = request.get_json()
        if not data or 'order_ids' not in data:
            return jsonify({'ok': False, 'error': 'Order IDs required'}), 400
        
        order_ids = data['order_ids']
        if not isinstance(order_ids, list) or len(order_ids) == 0:
            return jsonify({'ok': False, 'error': 'Invalid order IDs'}), 400
        
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        user_id = request.user_id
        is_admin = getattr(request, 'is_admin', False)
        
        # Convert to ObjectIds
        object_ids = [ObjectId(oid) for oid in order_ids]
        
        # Build query - only delete delivered/cancelled orders owned by user (or all if admin)
        query = {
            '_id': {'$in': object_ids},
            'status': {'$in': ['delivered', 'cancelled']}
        }
        if not is_admin:
            query['user_id'] = user_id
        
        result = orders_collection.delete_many(query)
        
        return jsonify({
            'ok': True,
            'message': f'Deleted {result.deleted_count} order(s)',
            'deleted_count': result.deleted_count
        })
    
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# Helper to check if user purchased a product
def user_purchased_product(user_id: str, product_id: str) -> bool:
    """Check if a user has purchased a specific product"""
    from flask import current_app
    orders_collection = current_app.config.get('db_orders')
    
    if orders_collection is None:
        return False
    
    # Check for delivered orders containing this product
    order = orders_collection.find_one({
        'user_id': user_id,
        'status': 'delivered',
        'items.product_id': product_id
    })
    
    return order is not None
