"""
Forum/Blog Post Model
Defines the forum/blog post schema for content management
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class ForumPost:
    """Forum/Blog post document model for MongoDB"""
    title: str
    content: str
    category: str  # 'news', 'events', 'about_us', 'about_bignay'
    author_id: str  # Reference to user _id (admin)
    author_name: str
    excerpt: str = ""  # Short summary for listing
    cover_image: str = ""  # Cloudinary URL for cover image
    images: List[str] = field(default_factory=list)  # Additional images
    tags: List[str] = field(default_factory=list)
    is_published: bool = False
    is_featured: bool = False
    is_pinned: bool = False
    views: int = 0
    likes: int = 0
    published_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'title': self.title,
            'content': self.content,
            'category': self.category,
            'author_id': self.author_id,
            'author_name': self.author_name,
            'excerpt': self.excerpt,
            'cover_image': self.cover_image,
            'images': self.images,
            'tags': self.tags,
            'is_published': self.is_published,
            'is_featured': self.is_featured,
            'is_pinned': self.is_pinned,
            'views': self.views,
            'likes': self.likes,
            'published_at': self.published_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public post info"""
        return {
            '_id': str(self._id) if self._id else None,
            'title': self.title,
            'content': self.content,
            'category': self.category,
            'author_id': self.author_id,
            'author_name': self.author_name,
            'excerpt': self.excerpt,
            'cover_image': self.cover_image,
            'images': self.images,
            'tags': self.tags,
            'is_published': self.is_published,
            'is_featured': self.is_featured,
            'is_pinned': self.is_pinned,
            'views': self.views,
            'likes': self.likes,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_list_dict(self) -> dict:
        """Return minimal info for listing"""
        return {
            '_id': str(self._id) if self._id else None,
            'title': self.title,
            'category': self.category,
            'author_name': self.author_name,
            'excerpt': self.excerpt,
            'cover_image': self.cover_image,
            'is_featured': self.is_featured,
            'is_pinned': self.is_pinned,
            'views': self.views,
            'likes': self.likes,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ForumPost':
        """Create ForumPost instance from MongoDB document"""
        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            title=data.get('title', ''),
            content=data.get('content', ''),
            category=data.get('category', ''),
            author_id=data.get('author_id', ''),
            author_name=data.get('author_name', ''),
            excerpt=data.get('excerpt', ''),
            cover_image=data.get('cover_image', ''),
            images=data.get('images', []),
            tags=data.get('tags', []),
            is_published=data.get('is_published', False),
            is_featured=data.get('is_featured', False),
            is_pinned=data.get('is_pinned', False),
            views=data.get('views', 0),
            likes=data.get('likes', 0),
            published_at=data.get('published_at'),
            created_at=data.get('created_at', datetime.now(timezone.utc)),
            updated_at=data.get('updated_at', datetime.now(timezone.utc)),
        )


# Forum category constants
FORUM_CATEGORIES = [
    {'id': 'news', 'name': 'News', 'icon': 'newspaper', 'color': '#2196F3'},
    {'id': 'events', 'name': 'Events', 'icon': 'calendar', 'color': '#9C27B0'},
    {'id': 'about_us', 'name': 'About Us', 'icon': 'people', 'color': '#4CAF50'},
    {'id': 'about_bignay', 'name': 'About Bignay', 'icon': 'leaf', 'color': '#FF9800'},
]
