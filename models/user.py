"""
User Model
Defines the user schema and role management for authentication
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
import hashlib
import secrets


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class SuspensionType(str, Enum):
    """Predefined suspension durations"""
    HOUR_1 = "1_hour"
    HOURS_8 = "8_hours"
    DAY_1 = "1_day"
    DAYS_15 = "15_days"
    MONTH_1 = "1_month"
    PERMANENT = "permanent"


@dataclass
class User:
    """User document model for MongoDB"""
    email: str
    password_hash: str
    first_name: str
    last_name: str
    role: UserRole = UserRole.USER
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    profile_image: Optional[str] = None
    is_active: bool = True
    is_verified: bool = False
    # Google OAuth fields
    google_id: Optional[str] = None
    auth_provider: str = 'local'  # 'local' or 'google'
    # Suspension fields
    is_suspended: bool = False
    suspension_type: Optional[str] = None  # SuspensionType value
    suspension_reason: Optional[str] = None
    suspension_start: Optional[datetime] = None
    suspension_end: Optional[datetime] = None  # None means permanent
    suspended_by: Optional[str] = None  # Admin user ID
    # Wallet/Balance fields for online payments
    wallet_balance: float = 0.0  # User's wallet balance in PHP
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: Optional[datetime] = None
    _id: Optional[str] = None

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using SHA-256 with salt"""
        salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return f"{salt}${password_hash}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verify password against stored hash"""
        try:
            salt, hash_value = stored_hash.split('$')
            computed_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
            return computed_hash == hash_value
        except ValueError:
            return False

    def to_dict(self, include_password: bool = False) -> dict:
        """Convert to dictionary for MongoDB storage"""
        data = {
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'role': self.role.value if isinstance(self.role, UserRole) else self.role,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'province': self.province,
            'postal_code': self.postal_code,
            'profile_image': self.profile_image,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'google_id': self.google_id,
            'auth_provider': self.auth_provider,
            'is_suspended': self.is_suspended,
            'suspension_type': self.suspension_type,
            'suspension_reason': self.suspension_reason,
            'suspension_start': self.suspension_start,
            'suspension_end': self.suspension_end,
            'suspended_by': self.suspended_by,
            'wallet_balance': self.wallet_balance,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'last_login': self.last_login,
        }
        if include_password:
            data['password_hash'] = self.password_hash
        if self._id:
            data['_id'] = self._id
        return data

    def to_public_dict(self) -> dict:
        """Return public user info (no sensitive data)"""
        return {
            '_id': str(self._id) if self._id else None,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': f"{self.first_name} {self.last_name}",
            'role': self.role.value if isinstance(self.role, UserRole) else self.role,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'province': self.province,
            'postal_code': self.postal_code,
            'profile_image': self.profile_image,
            'is_active': self.is_active,
            'is_verified': self.is_verified,
            'auth_provider': self.auth_provider,
            'is_suspended': self.is_suspended,
            'suspension_type': self.suspension_type,
            'suspension_reason': self.suspension_reason,
            'suspension_start': self.suspension_start.isoformat() if self.suspension_start else None,
            'suspension_end': self.suspension_end.isoformat() if self.suspension_end else None,
            'wallet_balance': self.wallet_balance,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'User':
        """Create User instance from MongoDB document"""
        role = data.get('role', UserRole.USER)
        if isinstance(role, str):
            role = UserRole(role)
        
        return cls(
            _id=str(data.get('_id')) if data.get('_id') else None,
            email=data.get('email', ''),
            password_hash=data.get('password_hash', ''),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            role=role,
            phone=data.get('phone'),
            address=data.get('address'),
            city=data.get('city'),
            province=data.get('province'),
            postal_code=data.get('postal_code'),
            profile_image=data.get('profile_image'),
            is_active=data.get('is_active', True),
            is_verified=data.get('is_verified', False),
            google_id=data.get('google_id'),
            auth_provider=data.get('auth_provider', 'local'),
            is_suspended=data.get('is_suspended', False),
            suspension_type=data.get('suspension_type'),
            suspension_reason=data.get('suspension_reason'),
            suspension_start=data.get('suspension_start'),
            suspension_end=data.get('suspension_end'),
            suspended_by=data.get('suspended_by'),
            wallet_balance=float(data.get('wallet_balance', 0.0)),
            created_at=data.get('created_at', datetime.now(timezone.utc)),
            updated_at=data.get('updated_at', datetime.now(timezone.utc)),
            last_login=data.get('last_login'),
        )
