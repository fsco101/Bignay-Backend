# Routes package initialization
# This package contains all API routes organized by functionality

from flask import Blueprint

# Import all route blueprints
from .auth import auth_bp
from .users import users_bp
from .products import products_bp
from .orders import orders_bp
from .reviews import reviews_bp

__all__ = ['auth_bp', 'users_bp', 'products_bp', 'orders_bp', 'reviews_bp']
