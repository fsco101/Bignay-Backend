"""
Harvest Pin Model
Defines the harvest pin schema for the interactive harvest map feature.
Stores user-created pins with geolocation, metadata, and contact information.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List


# Valid pin types for harvest map markers
PIN_TYPES = ['farm', 'blooming_area', 'market', 'other']


@dataclass
class HarvestPin:
    """Harvest pin document model for MongoDB"""
    latitude: float
    longitude: float
    pin_type: str  # 'farm', 'blooming_area', 'market', 'other'
    description: str = ""
    place_name: str = ""
    contact_person: str = ""  # Optional
    contact_details: str = ""  # Optional (phone, email, etc.)
    created_by: str = ""  # Reference to user _id
    created_by_name: str = ""
    created_by_avatar: str = ""  # Profile image URL of pin creator
    is_active: bool = True
    images: List[str] = field(default_factory=list)  # Cloudinary URLs (optional)
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'pin_type': self.pin_type,
            'description': self.description,
            'place_name': self.place_name,
            'contact_person': self.contact_person,
            'contact_details': self.contact_details,
            'created_by': self.created_by,
            'created_by_name': self.created_by_name,
            'created_by_avatar': self.created_by_avatar,
            'is_active': self.is_active,
            'images': self.images,
            'tags': self.tags,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public pin info for map display"""
        return {
            '_id': str(self._id) if self._id else None,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'pin_type': self.pin_type,
            'description': self.description,
            'place_name': self.place_name,
            'contact_person': self.contact_person,
            'contact_details': self.contact_details,
            'created_by': self.created_by,
            'created_by_name': self.created_by_name,
            'created_by_avatar': self.created_by_avatar,
            'is_active': self.is_active,
            'images': self.images,
            'tags': self.tags,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'HarvestPin':
        """Create HarvestPin instance from MongoDB document"""
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        updated_at = data.get('updated_at')
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif not isinstance(updated_at, datetime):
            updated_at = datetime.now(timezone.utc)

        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            latitude=float(data.get('latitude', 0)),
            longitude=float(data.get('longitude', 0)),
            pin_type=data.get('pin_type', 'other'),
            description=data.get('description', ''),
            place_name=data.get('place_name', ''),
            contact_person=data.get('contact_person', ''),
            contact_details=data.get('contact_details', ''),
            created_by=data.get('created_by', ''),
            created_by_name=data.get('created_by_name', ''),
            created_by_avatar=data.get('created_by_avatar', ''),
            is_active=data.get('is_active', True),
            images=data.get('images', []),
            tags=data.get('tags', []),
            created_at=created_at,
            updated_at=updated_at,
        )

    def validate(self) -> list:
        """Validate pin data, return list of errors"""
        errors = []
        if not (-90 <= self.latitude <= 90):
            errors.append('Latitude must be between -90 and 90')
        if not (-180 <= self.longitude <= 180):
            errors.append('Longitude must be between -180 and 180')
        if self.pin_type not in PIN_TYPES:
            errors.append(f'Invalid pin_type. Must be one of: {", ".join(PIN_TYPES)}')
        if len(self.description) > 1000:
            errors.append('Description must be 1000 characters or less')
        if len(self.place_name) > 200:
            errors.append('Place name must be 200 characters or less')
        return errors
