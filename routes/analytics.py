"""
Analytics Routes
Handles sales analytics and statistics for users and admin
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from bson import ObjectId

from routes.auth import require_auth, require_admin

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


def _get_orders_collection():
    """Get MongoDB orders collection"""
    from flask import current_app
    return current_app.config.get('db_orders')


def _get_products_collection():
    """Get MongoDB products collection"""
    from flask import current_app
    return current_app.config.get('db_products')


def _get_date_range(period: str):
    """
    Get date range based on period filter
    Returns (start_date, end_date, group_by_format)
    """
    now = datetime.now(timezone.utc)
    
    if period == 'weekly':
        # Last 7 days
        start_date = now - timedelta(days=7)
        group_format = '%Y-%m-%d'  # Daily grouping
    elif period == 'monthly':
        # Last 30 days
        start_date = now - timedelta(days=30)
        group_format = '%Y-%m-%d'  # Daily grouping
    elif period == 'yearly':
        # Last 365 days
        start_date = now - timedelta(days=365)
        group_format = '%Y-%m'  # Monthly grouping
    else:
        # Default to monthly
        start_date = now - timedelta(days=30)
        group_format = '%Y-%m-%d'
    
    return start_date, now, group_format


def _get_period_labels(period: str, start_date: datetime, end_date: datetime):
    """Generate all date labels for the period"""
    labels = []
    current = start_date
    
    if period == 'yearly':
        # Monthly labels
        while current <= end_date:
            labels.append(current.strftime('%Y-%m'))
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
    else:
        # Daily labels
        while current <= end_date:
            labels.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
    
    return labels


@analytics_bp.route('/user/sales', methods=['GET'])
@require_auth
def get_user_sales_analytics():
    """
    Get sales analytics for the authenticated user (as a seller)
    Query params:
        - period: 'weekly', 'monthly', 'yearly' (default: 'monthly')
    
    Returns:
        - total_sales: Total revenue
        - total_orders: Number of completed orders
        - sales_trend: Array of {date, amount} for line chart
        - product_sales: Array of {product_name, quantity, revenue} for pie chart
    """
    try:
        period = request.args.get('period', 'monthly')
        user_id = request.user_info['user_id']
        
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        start_date, end_date, group_format = _get_date_range(period)
        
        # Build base query for completed orders where user is the seller
        # Orders have items with seller_id
        base_match = {
            'status': {'$in': ['delivered', 'completed']},
            'created_at': {'$gte': start_date, '$lte': end_date},
            'items.seller_id': user_id
        }
        
        # Get total sales and order count
        total_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {'$match': {'items.seller_id': user_id}},
            {
                '$group': {
                    '_id': None,
                    'total_sales': {'$sum': '$items.subtotal'},
                    'total_orders': {'$addToSet': '$_id'}
                }
            }
        ]
        
        total_result = list(orders_collection.aggregate(total_pipeline))
        total_sales = total_result[0]['total_sales'] if total_result else 0
        total_orders = len(total_result[0]['total_orders']) if total_result else 0
        
        # Get sales trend data (daily/monthly breakdown)
        if period == 'yearly':
            date_format = {'$dateToString': {'format': '%Y-%m', 'date': '$created_at'}}
        else:
            date_format = {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}}
        
        trend_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {'$match': {'items.seller_id': user_id}},
            {
                '$group': {
                    '_id': date_format,
                    'amount': {'$sum': '$items.subtotal'},
                    'order_count': {'$sum': 1}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        trend_result = list(orders_collection.aggregate(trend_pipeline))
        
        # Fill in missing dates with zero values
        all_labels = _get_period_labels(period, start_date, end_date)
        trend_map = {item['_id']: item['amount'] for item in trend_result}
        
        sales_trend = [
            {
                'date': label,
                'amount': round(trend_map.get(label, 0), 2)
            }
            for label in all_labels
        ]
        
        # Get product breakdown for pie chart
        product_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {'$match': {'items.seller_id': user_id}},
            {
                '$group': {
                    '_id': '$items.product_name',
                    'quantity': {'$sum': '$items.quantity'},
                    'revenue': {'$sum': '$items.subtotal'}
                }
            },
            {'$sort': {'revenue': -1}},
            {'$limit': 10}  # Top 10 products
        ]
        
        product_result = list(orders_collection.aggregate(product_pipeline))
        product_sales = [
            {
                'product_name': item['_id'],
                'quantity': item['quantity'],
                'revenue': round(item['revenue'], 2)
            }
            for item in product_result
        ]
        
        # Get average order value
        avg_order_value = round(total_sales / total_orders, 2) if total_orders > 0 else 0
        
        return jsonify({
            'ok': True,
            'period': period,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'summary': {
                'total_sales': round(total_sales, 2),
                'total_orders': total_orders,
                'avg_order_value': avg_order_value
            },
            'sales_trend': sales_trend,
            'product_sales': product_sales
        })
        
    except Exception as e:
        print(f"[Analytics] Error in user sales: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@analytics_bp.route('/admin/sales', methods=['GET'])
@require_admin
def get_admin_sales_analytics():
    """
    Get platform-wide sales analytics (admin only)
    Query params:
        - period: 'weekly', 'monthly', 'yearly' (default: 'monthly')
    
    Returns:
        - total_sales: Total platform revenue
        - total_orders: Total number of completed orders
        - total_sellers: Number of unique sellers with sales
        - sales_trend: Array of {date, amount} for line chart
        - product_sales: Array of {product_name, quantity, revenue} for pie chart
        - seller_sales: Array of {seller_name, revenue} for top sellers
    """
    try:
        period = request.args.get('period', 'monthly')
        
        orders_collection = _get_orders_collection()
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        start_date, end_date, group_format = _get_date_range(period)
        
        # Build base query for completed orders
        base_match = {
            'status': {'$in': ['delivered', 'completed']},
            'created_at': {'$gte': start_date, '$lte': end_date}
        }
        
        # Get total sales, order count, and unique sellers
        total_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {
                '$group': {
                    '_id': None,
                    'total_sales': {'$sum': '$items.subtotal'},
                    'total_orders': {'$addToSet': '$_id'},
                    'unique_sellers': {'$addToSet': '$items.seller_id'}
                }
            }
        ]
        
        total_result = list(orders_collection.aggregate(total_pipeline))
        total_sales = total_result[0]['total_sales'] if total_result else 0
        total_orders = len(total_result[0]['total_orders']) if total_result else 0
        total_sellers = len(total_result[0]['unique_sellers']) if total_result else 0
        
        # Get sales trend data (daily/monthly breakdown)
        if period == 'yearly':
            date_format = {'$dateToString': {'format': '%Y-%m', 'date': '$created_at'}}
        else:
            date_format = {'$dateToString': {'format': '%Y-%m-%d', 'date': '$created_at'}}
        
        trend_pipeline = [
            {'$match': base_match},
            {
                '$group': {
                    '_id': date_format,
                    'amount': {'$sum': '$total_amount'},
                    'order_count': {'$sum': 1}
                }
            },
            {'$sort': {'_id': 1}}
        ]
        
        trend_result = list(orders_collection.aggregate(trend_pipeline))
        
        # Fill in missing dates with zero values
        all_labels = _get_period_labels(period, start_date, end_date)
        trend_map = {item['_id']: item['amount'] for item in trend_result}
        
        sales_trend = [
            {
                'date': label,
                'amount': round(trend_map.get(label, 0), 2)
            }
            for label in all_labels
        ]
        
        # Get product breakdown for pie chart (platform-wide)
        product_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {
                '$group': {
                    '_id': '$items.product_name',
                    'quantity': {'$sum': '$items.quantity'},
                    'revenue': {'$sum': '$items.subtotal'}
                }
            },
            {'$sort': {'revenue': -1}},
            {'$limit': 10}  # Top 10 products
        ]
        
        product_result = list(orders_collection.aggregate(product_pipeline))
        product_sales = [
            {
                'product_name': item['_id'],
                'quantity': item['quantity'],
                'revenue': round(item['revenue'], 2)
            }
            for item in product_result
        ]
        
        # Get top sellers
        seller_pipeline = [
            {'$match': base_match},
            {'$unwind': '$items'},
            {
                '$group': {
                    '_id': {
                        'seller_id': '$items.seller_id',
                        'seller_name': '$items.seller_name'
                    },
                    'revenue': {'$sum': '$items.subtotal'},
                    'order_count': {'$sum': 1}
                }
            },
            {'$sort': {'revenue': -1}},
            {'$limit': 10}  # Top 10 sellers
        ]
        
        seller_result = list(orders_collection.aggregate(seller_pipeline))
        seller_sales = [
            {
                'seller_id': item['_id']['seller_id'],
                'seller_name': item['_id']['seller_name'] or 'Unknown',
                'seller_email': '',  # Add email if needed
                'total_sales': round(item['revenue'], 2),
                'order_count': item['order_count']
            }
            for item in seller_result
        ]
        
        # Get average order value
        avg_order_value = round(total_sales / total_orders, 2) if total_orders > 0 else 0
        
        # Get payment method breakdown
        payment_pipeline = [
            {'$match': base_match},
            {
                '$group': {
                    '_id': '$payment_method',
                    'count': {'$sum': 1},
                    'amount': {'$sum': '$total_amount'}
                }
            }
        ]
        
        payment_result = list(orders_collection.aggregate(payment_pipeline))
        payment_breakdown = [
            {
                'method': item['_id'] or 'unknown',
                'count': item['count'],
                'total': round(item['amount'], 2)
            }
            for item in payment_result
        ]
        
        return jsonify({
            'ok': True,
            'period': period,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'summary': {
                'total_sales': round(total_sales, 2),
                'total_orders': total_orders,
                'total_sellers': total_sellers,
                'avg_order_value': avg_order_value
            },
            'sales_trend': sales_trend,
            'product_sales': product_sales,
            'seller_sales': seller_sales,
            'payment_breakdown': payment_breakdown
        })
        
    except Exception as e:
        print(f"[Analytics] Error in admin sales: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@analytics_bp.route('/user/orders-summary', methods=['GET'])
@require_auth
def get_user_orders_summary():
    """
    Get order summary for user as buyer
    Returns counts of orders by status
    """
    try:
        user_id = request.user_info['user_id']
        orders_collection = _get_orders_collection()
        
        if orders_collection is None:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Count orders by status
        pipeline = [
            {'$match': {'user_id': user_id}},
            {
                '$group': {
                    '_id': '$status',
                    'count': {'$sum': 1}
                }
            }
        ]
        
        result = list(orders_collection.aggregate(pipeline))
        
        status_counts = {item['_id']: item['count'] for item in result}
        
        return jsonify({
            'ok': True,
            'orders_summary': {
                'pending': status_counts.get('pending', 0),
                'confirmed': status_counts.get('confirmed', 0),
                'processing': status_counts.get('processing', 0),
                'shipped': status_counts.get('shipped', 0),
                'delivered': status_counts.get('delivered', 0),
                'cancelled': status_counts.get('cancelled', 0),
                'total': sum(status_counts.values())
            }
        })
        
    except Exception as e:
        print(f"[Analytics] Error in user orders summary: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@analytics_bp.route('/admin/overview', methods=['GET'])
@require_admin
def get_admin_overview():
    """
    Get admin dashboard overview statistics
    """
    try:
        orders_collection = _get_orders_collection()
        products_collection = _get_products_collection()
        
        from flask import current_app
        users_collection = current_app.config.get('db_users')
        
        if any(c is None for c in [orders_collection, products_collection, users_collection]):
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Today's date range
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        
        # This month's date range
        month_start = today.replace(day=1)
        
        # Total users
        total_users = users_collection.count_documents({})
        
        # Total products
        total_products = products_collection.count_documents({'is_active': True})
        
        # Total orders
        total_orders = orders_collection.count_documents({})
        
        # Today's orders
        today_orders = orders_collection.count_documents({
            'created_at': {'$gte': today, '$lt': tomorrow}
        })
        
        # Today's revenue
        today_revenue_pipeline = [
            {
                '$match': {
                    'status': {'$in': ['delivered', 'completed']},
                    'created_at': {'$gte': today, '$lt': tomorrow}
                }
            },
            {
                '$group': {
                    '_id': None,
                    'revenue': {'$sum': '$total_amount'}
                }
            }
        ]
        today_revenue_result = list(orders_collection.aggregate(today_revenue_pipeline))
        today_revenue = today_revenue_result[0]['revenue'] if today_revenue_result else 0
        
        # This month's revenue
        month_revenue_pipeline = [
            {
                '$match': {
                    'status': {'$in': ['delivered', 'completed']},
                    'created_at': {'$gte': month_start, '$lt': tomorrow}
                }
            },
            {
                '$group': {
                    '_id': None,
                    'revenue': {'$sum': '$total_amount'}
                }
            }
        ]
        month_revenue_result = list(orders_collection.aggregate(month_revenue_pipeline))
        month_revenue = month_revenue_result[0]['revenue'] if month_revenue_result else 0
        
        # Pending orders count
        pending_orders = orders_collection.count_documents({
            'status': {'$in': ['pending', 'confirmed', 'processing']}
        })
        
        return jsonify({
            'ok': True,
            'overview': {
                'total_users': total_users,
                'total_products': total_products,
                'total_orders': total_orders,
                'today_orders': today_orders,
                'today_revenue': round(today_revenue, 2),
                'month_revenue': round(month_revenue, 2),
                'pending_orders': pending_orders
            }
        })
        
    except Exception as e:
        print(f"[Analytics] Error in admin overview: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
