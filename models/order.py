"""
Order Model
Defines the order schema for marketplace checkout
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class OrderItem:
    """Individual item in an order"""
    product_id: str
    product_name: str
    product_image: str
    quantity: int
    unit_price: float
    subtotal: float
    seller_id: str
    seller_name: str

    def to_dict(self) -> dict:
        return {
            'product_id': self.product_id,
            'product_name': self.product_name,
            'product_image': self.product_image,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'subtotal': self.subtotal,
            'seller_id': self.seller_id,
            'seller_name': self.seller_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'OrderItem':
        return cls(
            product_id=data.get('product_id', ''),
            product_name=data.get('product_name', ''),
            product_image=data.get('product_image', ''),
            quantity=int(data.get('quantity', 0)),
            unit_price=float(data.get('unit_price', 0)),
            subtotal=float(data.get('subtotal', 0)),
            seller_id=data.get('seller_id', ''),
            seller_name=data.get('seller_name', ''),
        )


@dataclass
class Order:
    """Order document model for MongoDB"""
    user_id: str
    user_email: str
    user_name: str
    items: List[OrderItem]
    total_amount: float
    status: OrderStatus = OrderStatus.PENDING
    shipping_address: str = ""
    shipping_city: str = ""
    shipping_province: str = ""
    shipping_postal_code: str = ""
    shipping_phone: str = ""
    payment_method: str = "cash_on_delivery"
    payment_status: str = "pending"
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    delivered_at: Optional[datetime] = None
    _id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_name': self.user_name,
            'items': [item.to_dict() for item in self.items],
            'total_amount': self.total_amount,
            'status': self.status.value if isinstance(self.status, OrderStatus) else self.status,
            'shipping_address': self.shipping_address,
            'shipping_city': self.shipping_city,
            'shipping_province': self.shipping_province,
            'shipping_postal_code': self.shipping_postal_code,
            'shipping_phone': self.shipping_phone,
            'payment_method': self.payment_method,
            'payment_status': self.payment_status,
            'notes': self.notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'delivered_at': self.delivered_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public order info"""
        return {
            '_id': str(self._id) if self._id else None,
            'order_number': str(self._id) if self._id else None,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_name': self.user_name,
            'items': [item.to_dict() for item in self.items],
            'item_count': len(self.items),
            'total_amount': self.total_amount,
            'status': self.status.value if isinstance(self.status, OrderStatus) else self.status,
            'shipping_address': self.shipping_address,
            'shipping_city': self.shipping_city,
            'shipping_province': self.shipping_province,
            'shipping_postal_code': self.shipping_postal_code,
            'shipping_phone': self.shipping_phone,
            'payment_method': self.payment_method,
            'payment_status': self.payment_status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Order':
        """Create Order instance from MongoDB document"""
        status = data.get('status', OrderStatus.PENDING)
        if isinstance(status, str):
            status = OrderStatus(status)

        items = [OrderItem.from_dict(item) for item in data.get('items', [])]

        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            user_id=data.get('user_id', ''),
            user_email=data.get('user_email', ''),
            user_name=data.get('user_name', ''),
            items=items,
            total_amount=float(data.get('total_amount', 0)),
            status=status,
            shipping_address=data.get('shipping_address', ''),
            shipping_city=data.get('shipping_city', ''),
            shipping_province=data.get('shipping_province', ''),
            shipping_postal_code=data.get('shipping_postal_code', ''),
            shipping_phone=data.get('shipping_phone', ''),
            payment_method=data.get('payment_method', 'cash_on_delivery'),
            payment_status=data.get('payment_status', 'pending'),
            notes=data.get('notes', ''),
            created_at=data.get('created_at', datetime.now(timezone.utc)),
            updated_at=data.get('updated_at', datetime.now(timezone.utc)),
            delivered_at=data.get('delivered_at'),
        )
