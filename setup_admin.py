"""
Setup Admin User Script
Run this script once to create the initial admin user

Usage: python setup_admin.py
"""

import os
import sys

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_settings
from models.user import User, UserRole


def create_admin():
    settings = get_settings()
    
    if not settings.mongodb_uri:
        print("❌ Error: MONGODB_URI not set in environment")
        print("Please set up your .env file first")
        return False
    
    try:
        from pymongo import MongoClient
        
        client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        db = client[settings.mongodb_db]
        users_collection = db['users']
        
        # Check if admin already exists
        existing_admin = users_collection.find_one({'role': 'admin'})
        if existing_admin:
            print(f"✓ Admin user already exists: {existing_admin['email']}")
            return True
        
        # Get admin details from user
        print("\n=== Create Admin User ===\n")
        
        email = input("Admin Email: ").strip().lower()
        if not email:
            print("❌ Email is required")
            return False
        
        # Check if email already exists
        if users_collection.find_one({'email': email}):
            print(f"❌ User with email {email} already exists")
            return False
        
        first_name = input("First Name: ").strip()
        if not first_name:
            print("❌ First name is required")
            return False
        
        last_name = input("Last Name: ").strip()
        if not last_name:
            print("❌ Last name is required")
            return False
        
        password = input("Password (min 8 chars, 1 uppercase, 1 lowercase, 1 number, 1 special): ").strip()
        if len(password) < 8:
            print("❌ Password must be at least 8 characters")
            return False
        
        confirm_password = input("Confirm Password: ").strip()
        if password != confirm_password:
            print("❌ Passwords do not match")
            return False
        
        # Create admin user
        admin = User(
            email=email,
            password_hash=User.hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=UserRole.ADMIN,
            is_verified=True,
            is_active=True,
        )
        
        result = users_collection.insert_one(admin.to_dict(include_password=True))
        
        print(f"\n✓ Admin user created successfully!")
        print(f"  Email: {email}")
        print(f"  Name: {first_name} {last_name}")
        print(f"  ID: {result.inserted_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = create_admin()
    sys.exit(0 if success else 1)
