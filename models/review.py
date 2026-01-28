"""
Review Model
Defines the review schema for product reviews and ratings
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class Review:
    """Review document model for MongoDB"""
    product_id: str
    user_id: str
    user_name: str
    order_id: str  # Reference to the order where product was purchased
    rating: int  # 1-5 stars
    comment: str  # Filtered comment (bad words removed)
    original_comment: str = ""  # Original comment before filtering
    is_verified_purchase: bool = True
    is_visible: bool = True
    helpful_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'product_id': self.product_id,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'order_id': self.order_id,
            'rating': self.rating,
            'comment': self.comment,
            'original_comment': self.original_comment,
            'is_verified_purchase': self.is_verified_purchase,
            'is_visible': self.is_visible,
            'helpful_count': self.helpful_count,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public review info"""
        return {
            '_id': str(self._id) if self._id else None,
            'product_id': self.product_id,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'rating': self.rating,
            'comment': self.comment,
            'is_verified_purchase': self.is_verified_purchase,
            'helpful_count': self.helpful_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Review':
        """Create Review instance from MongoDB document"""
        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            product_id=data.get('product_id', ''),
            user_id=data.get('user_id', ''),
            user_name=data.get('user_name', ''),
            order_id=data.get('order_id', ''),
            rating=int(data.get('rating', 5)),
            comment=data.get('comment', ''),
            original_comment=data.get('original_comment', ''),
            is_verified_purchase=data.get('is_verified_purchase', True),
            is_visible=data.get('is_visible', True),
            helpful_count=int(data.get('helpful_count', 0)),
            created_at=data.get('created_at', datetime.now(timezone.utc)),
            updated_at=data.get('updated_at', datetime.now(timezone.utc)),
        )
