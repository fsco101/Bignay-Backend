"""
Product Model
Defines the product schema for marketplace
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class Product:
    """Product document model for MongoDB"""
    name: str
    description: str
    price: float
    stock: int
    category: str
    seller_id: str  # Reference to user _id
    seller_name: str
    images: List[str] = field(default_factory=list)  # Cloudinary URLs
    unit: str = "per item"
    location: str = ""
    quality: str = "Standard"
    tags: List[str] = field(default_factory=list)
    is_active: bool = True
    views: int = 0
    sales_count: int = 0
    average_rating: float = 0.0
    review_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'name': self.name,
            'description': self.description,
            'price': self.price,
            'stock': self.stock,
            'category': self.category,
            'seller_id': self.seller_id,
            'seller_name': self.seller_name,
            'images': self.images,
            'unit': self.unit,
            'location': self.location,
            'quality': self.quality,
            'tags': self.tags,
            'is_active': self.is_active,
            'views': self.views,
            'sales_count': self.sales_count,
            'average_rating': self.average_rating,
            'review_count': self.review_count,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public product info"""
        return {
            '_id': str(self._id) if self._id else None,
            'name': self.name,
            'description': self.description,
            'price': self.price,
            'stock': self.stock,
            'category': self.category,
            'seller_id': self.seller_id,
            'seller_name': self.seller_name,
            'images': self.images,
            'unit': self.unit,
            'location': self.location,
            'quality': self.quality,
            'tags': self.tags,
            'is_active': self.is_active,
            'views': self.views,
            'sales_count': self.sales_count,
            'average_rating': self.average_rating,
            'review_count': self.review_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'in_stock': self.stock > 0,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Product':
        """Create Product instance from MongoDB document"""
        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            name=data.get('name', ''),
            description=data.get('description', ''),
            price=float(data.get('price', 0)),
            stock=int(data.get('stock', 0)),
            category=data.get('category', ''),
            seller_id=data.get('seller_id', ''),
            seller_name=data.get('seller_name', ''),
            images=data.get('images', []),
            unit=data.get('unit', 'per item'),
            location=data.get('location', ''),
            quality=data.get('quality', 'Standard'),
            tags=data.get('tags', []),
            is_active=data.get('is_active', True),
            views=data.get('views', 0),
            sales_count=data.get('sales_count', 0),
            average_rating=float(data.get('average_rating', 0)),
            review_count=int(data.get('review_count', 0)),
            created_at=data.get('created_at', datetime.now(timezone.utc)),
            updated_at=data.get('updated_at', datetime.now(timezone.utc)),
        )
