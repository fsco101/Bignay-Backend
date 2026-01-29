"""
Payments Routes
Handles payment processing, wallet management, and PayMongo integration
"""

from flask import Blueprint, request, jsonify, g, current_app
from datetime import datetime, timezone
from bson import ObjectId
from functools import wraps
import jwt

from config import get_settings
from models.user import User
from models.order import Order
from utils.paymongo_helper import paymongo_helper

payments_bp = Blueprint('payments', __name__, url_prefix='/api/payments')


def get_users_collection():
    """Get users collection from app config"""
    return current_app.config.get('db_users')


def get_orders_collection():
    """Get orders collection from app config"""
    return current_app.config.get('db_orders')


def get_wallet_topups_collection():
    """Get or create wallet_topups collection"""
    # Access the MongoDB client through the users collection
    users = get_users_collection()
    if users is not None:
        return users.database['wallet_topups']
    return None


def get_token_from_header():
    """Extract token from Authorization header"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ')[1]
    return None


def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_header()
        if not token:
            return jsonify({'ok': False, 'error': 'No token provided'}), 401
        
        try:
            settings = get_settings()
            
            # Try JWT decode first
            try:
                payload = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'])
                user_id = payload.get('user_id')
            except jwt.InvalidTokenError:
                # Fallback to simple token verification from auth routes
                from routes.auth import verify_token
                token_data = verify_token(token)
                if not token_data:
                    return jsonify({'ok': False, 'error': 'Invalid token'}), 401
                user_id = token_data.get('user_id')
            
            users_collection = get_users_collection()
            if not users_collection:
                return jsonify({'ok': False, 'error': 'Database not available'}), 503
            
            user_doc = users_collection.find_one({'_id': ObjectId(user_id)})
            
            if not user_doc:
                return jsonify({'ok': False, 'error': 'User not found'}), 401
            
            g.current_user = User.from_dict(user_doc)
            g.current_user_id = str(user_doc['_id'])
            
        except jwt.ExpiredSignatureError:
            return jsonify({'ok': False, 'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'ok': False, 'error': 'Invalid token'}), 401
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 401
        
        return f(*args, **kwargs)
    return decorated


# ============================================
# WALLET ENDPOINTS
# ============================================

@payments_bp.route('/wallet/balance', methods=['GET'])
@require_auth
def get_wallet_balance():
    """Get current user's wallet balance"""
    try:
        user = g.current_user
        return jsonify({
            'ok': True,
            'balance': user.wallet_balance,
            'formatted_balance': f"₱{user.wallet_balance:,.2f}",
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@payments_bp.route('/wallet/topup', methods=['POST'])
@require_auth
def create_topup():
    """Create a wallet top-up via PayMongo"""
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        
        if amount < 100:
            return jsonify({'ok': False, 'error': 'Minimum top-up amount is ₱100'}), 400
        if amount > 50000:
            return jsonify({'ok': False, 'error': 'Maximum top-up amount is ₱50,000'}), 400
        
        user = g.current_user
        
        # Create PayMongo checkout session for top-up
        # Use app deep link or web URL for redirects
        base_url = request.host_url.rstrip('/')
        success_url = f"{base_url}/api/payments/wallet/topup/success"
        cancel_url = f"{base_url}/api/payments/wallet/topup/cancel"
        
        result = paymongo_helper.create_checkout_session(
            amount=amount,
            description=f"Wallet Top-up",
            order_id=f"TOPUP-{g.current_user_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            customer_email=user.email,
            customer_name=f"{user.first_name} {user.last_name}",
            success_url=success_url,
            cancel_url=cancel_url,
        )
        
        if result['ok']:
            # Store pending top-up in database
            topups_collection = get_wallet_topups_collection()
            if not topups_collection:
                return jsonify({'ok': False, 'error': 'Database not available'}), 503
            
            topup_doc = {
                'user_id': g.current_user_id,
                'amount': amount,
                'checkout_id': result['checkout_id'],
                'status': 'pending',
                'created_at': datetime.now(timezone.utc),
            }
            topups_collection.insert_one(topup_doc)
            
            return jsonify({
                'ok': True,
                'checkout_url': result['checkout_url'],
                'checkout_id': result['checkout_id'],
            })
        else:
            return jsonify({'ok': False, 'error': result.get('error', 'Failed to create checkout')}), 400
            
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@payments_bp.route('/wallet/topup/verify', methods=['POST'])
@require_auth
def verify_topup():
    """Verify a top-up payment"""
    try:
        data = request.get_json()
        checkout_id = data.get('checkout_id')
        
        if not checkout_id:
            return jsonify({'ok': False, 'error': 'Checkout ID required'}), 400
        
        topups_collection = get_wallet_topups_collection()
        users_collection = get_users_collection()
        
        if not topups_collection or not users_collection:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Find the pending top-up
        topup = topups_collection.find_one({
            'checkout_id': checkout_id,
            'user_id': g.current_user_id,
        })
        
        if not topup:
            return jsonify({'ok': False, 'error': 'Top-up not found'}), 404
        
        if topup['status'] == 'completed':
            return jsonify({
                'ok': True,
                'message': 'Top-up already processed',
                'status': 'completed',
            })
        
        # Check payment status with PayMongo
        result = paymongo_helper.get_checkout_session(checkout_id)
        
        if not result['ok']:
            return jsonify({'ok': False, 'error': result.get('error', 'Failed to verify payment')}), 400
        
        payment_status = result['status']
        
        if payment_status == 'paid':
            # Update user's wallet balance
            users_collection.update_one(
                {'_id': ObjectId(g.current_user_id)},
                {
                    '$inc': {'wallet_balance': topup['amount']},
                    '$set': {'updated_at': datetime.now(timezone.utc)},
                }
            )
            
            # Mark top-up as completed
            topups_collection.update_one(
                {'_id': topup['_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'paid_at': datetime.now(timezone.utc),
                        'payment_intent_id': result.get('payment_intent_id'),
                    }
                }
            )
            
            # Get updated balance
            updated_user = users_collection.find_one({'_id': ObjectId(g.current_user_id)})
            new_balance = updated_user.get('wallet_balance', 0)
            
            return jsonify({
                'ok': True,
                'message': 'Top-up successful!',
                'status': 'completed',
                'amount_added': topup['amount'],
                'new_balance': new_balance,
            })
        elif payment_status == 'expired':
            topups_collection.update_one(
                {'_id': topup['_id']},
                {'$set': {'status': 'expired'}}
            )
            return jsonify({'ok': False, 'error': 'Payment session expired', 'status': 'expired'}), 400
        else:
            return jsonify({
                'ok': True,
                'message': 'Payment pending',
                'status': payment_status,
            })
            
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@payments_bp.route('/wallet/transactions', methods=['GET'])
@require_auth
def get_wallet_transactions():
    """Get user's wallet transaction history"""
    try:
        topups_collection = get_wallet_topups_collection()
        orders_collection = get_orders_collection()
        
        if not topups_collection or not orders_collection:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 20))
        skip = (page - 1) * limit
        
        # Get top-ups
        topups = list(topups_collection.find(
            {'user_id': g.current_user_id, 'status': 'completed'}
        ).sort('paid_at', -1))
        
        # Get wallet payments (orders paid with wallet)
        wallet_orders = list(orders_collection.find({
            'user_id': g.current_user_id,
            'payment_method': 'wallet',
            'payment_status': 'paid',
        }).sort('paid_at', -1))
        
        # Combine and format transactions
        transactions = []
        
        for topup in topups:
            transactions.append({
                'type': 'topup',
                'amount': topup['amount'],
                'description': 'Wallet Top-up',
                'date': topup.get('paid_at', topup.get('created_at')).isoformat() if topup.get('paid_at') or topup.get('created_at') else None,
                'status': 'completed',
            })
        
        for order in wallet_orders:
            transactions.append({
                'type': 'payment',
                'amount': -order['total_amount'],  # Negative for payments
                'description': f"Order #{str(order['_id'])[-8:]}",
                'date': order.get('paid_at', order.get('created_at')).isoformat() if order.get('paid_at') or order.get('created_at') else None,
                'status': 'completed',
                'order_id': str(order['_id']),
            })
        
        # Sort by date
        transactions.sort(key=lambda x: x['date'] if x['date'] else '', reverse=True)
        
        # Paginate
        total = len(transactions)
        transactions = transactions[skip:skip + limit]
        
        return jsonify({
            'ok': True,
            'transactions': transactions,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit,
            }
        })
        
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================
# ORDER PAYMENT ENDPOINTS
# ============================================

@payments_bp.route('/order/pay/wallet', methods=['POST'])
@require_auth
def pay_with_wallet():
    """Pay for an order using wallet balance"""
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        
        if not order_id:
            return jsonify({'ok': False, 'error': 'Order ID required'}), 400
        
        orders_collection = get_orders_collection()
        users_collection = get_users_collection()
        
        if not orders_collection or not users_collection:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get the order
        order_doc = orders_collection.find_one({
            '_id': ObjectId(order_id),
            'user_id': g.current_user_id,
        })
        
        if not order_doc:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        if order_doc.get('payment_status') == 'paid':
            return jsonify({'ok': False, 'error': 'Order already paid'}), 400
        
        # Check wallet balance
        user = g.current_user
        order_total = order_doc['total_amount']
        
        if user.wallet_balance < order_total:
            return jsonify({
                'ok': False,
                'error': 'Insufficient wallet balance',
                'required': order_total,
                'available': user.wallet_balance,
            }), 400
        
        # Deduct from wallet and update order
        users_collection.update_one(
            {'_id': ObjectId(g.current_user_id)},
            {
                '$inc': {'wallet_balance': -order_total},
                '$set': {'updated_at': datetime.now(timezone.utc)},
            }
        )
        
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {
                '$set': {
                    'payment_status': 'paid',
                    'payment_method': 'wallet',
                    'paid_at': datetime.now(timezone.utc),
                    'updated_at': datetime.now(timezone.utc),
                    'status': 'confirmed',
                }
            }
        )
        
        # Get updated balance
        updated_user = users_collection.find_one({'_id': ObjectId(g.current_user_id)})
        new_balance = updated_user.get('wallet_balance', 0)
        
        return jsonify({
            'ok': True,
            'message': 'Payment successful!',
            'amount_paid': order_total,
            'new_balance': new_balance,
        })
        
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@payments_bp.route('/order/pay/online', methods=['POST'])
@require_auth
def pay_online():
    """Create online payment session for an order via PayMongo"""
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        
        if not order_id:
            return jsonify({'ok': False, 'error': 'Order ID required'}), 400
        
        orders_collection = get_orders_collection()
        
        if not orders_collection:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get the order
        order_doc = orders_collection.find_one({
            '_id': ObjectId(order_id),
            'user_id': g.current_user_id,
        })
        
        if not order_doc:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        if order_doc.get('payment_status') == 'paid':
            return jsonify({'ok': False, 'error': 'Order already paid'}), 400
        
        user = g.current_user
        order = Order.from_dict(order_doc)
        
        # Build line items for checkout
        line_items = []
        for item in order.items:
            line_items.append({
                "currency": "PHP",
                "amount": int(item.subtotal * 100),  # Convert to centavos
                "name": item.product_name,
                "quantity": item.quantity,
            })
        
        # Create PayMongo checkout session
        base_url = request.host_url.rstrip('/')
        success_url = f"{base_url}/api/payments/order/success?order_id={order_id}"
        cancel_url = f"{base_url}/api/payments/order/cancel?order_id={order_id}"
        
        result = paymongo_helper.create_checkout_session(
            amount=order.total_amount,
            description=f"Order from Bignay Marketplace",
            order_id=order_id,
            customer_email=user.email,
            customer_name=f"{user.first_name} {user.last_name}",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=line_items,
        )
        
        if result['ok']:
            # Update order with checkout info
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {
                    '$set': {
                        'paymongo_checkout_id': result['checkout_id'],
                        'payment_method': 'online_payment',
                        'updated_at': datetime.now(timezone.utc),
                    }
                }
            )
            
            return jsonify({
                'ok': True,
                'checkout_url': result['checkout_url'],
                'checkout_id': result['checkout_id'],
            })
        else:
            return jsonify({'ok': False, 'error': result.get('error', 'Failed to create checkout')}), 400
            
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@payments_bp.route('/order/verify', methods=['POST'])
@require_auth
def verify_order_payment():
    """Verify order payment status"""
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        
        if not order_id:
            return jsonify({'ok': False, 'error': 'Order ID required'}), 400
        
        orders_collection = get_orders_collection()
        
        if not orders_collection:
            return jsonify({'ok': False, 'error': 'Database not available'}), 503
        
        # Get the order
        order_doc = orders_collection.find_one({
            '_id': ObjectId(order_id),
            'user_id': g.current_user_id,
        })
        
        if not order_doc:
            return jsonify({'ok': False, 'error': 'Order not found'}), 404
        
        if order_doc.get('payment_status') == 'paid':
            return jsonify({
                'ok': True,
                'message': 'Payment already verified',
                'status': 'paid',
            })
        
        checkout_id = order_doc.get('paymongo_checkout_id')
        if not checkout_id:
            return jsonify({'ok': False, 'error': 'No payment session found'}), 400
        
        # Check payment status with PayMongo
        result = paymongo_helper.get_checkout_session(checkout_id)
        
        if not result['ok']:
            return jsonify({'ok': False, 'error': result.get('error', 'Failed to verify payment')}), 400
        
        payment_status = result['status']
        
        if payment_status == 'paid':
            # Update order
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {
                    '$set': {
                        'payment_status': 'paid',
                        'paid_at': datetime.now(timezone.utc),
                        'paymongo_payment_intent_id': result.get('payment_intent_id'),
                        'status': 'confirmed',
                        'updated_at': datetime.now(timezone.utc),
                    }
                }
            )
            
            return jsonify({
                'ok': True,
                'message': 'Payment successful!',
                'status': 'paid',
            })
        elif payment_status == 'expired':
            return jsonify({'ok': False, 'error': 'Payment session expired', 'status': 'expired'}), 400
        else:
            return jsonify({
                'ok': True,
                'message': 'Payment pending',
                'status': payment_status,
            })
            
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================
# PAYMONGO CONFIG ENDPOINT
# ============================================

@payments_bp.route('/config', methods=['GET'])
def get_payment_config():
    """Get PayMongo public configuration"""
    try:
        settings = get_settings()
        return jsonify({
            'ok': True,
            'public_key': settings.paymongo_public_key,
            'enabled': bool(settings.paymongo_secret_key and settings.paymongo_public_key),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
