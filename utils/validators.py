"""
Input Validators
Validates user input for registration, login, and other forms
"""

import re
from typing import Tuple, List, Optional


def validate_email(email: str) -> Tuple[bool, str]:
    """
    Validate email format
    Returns (is_valid, error_message)
    """
    if not email:
        return False, "Email is required"
    
    email = email.strip().lower()
    
    # RFC 5322 compliant email regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Please enter a valid email address"
    
    if len(email) > 254:
        return False, "Email address is too long"
    
    return True, ""


def validate_password(password: str) -> Tuple[bool, List[str]]:
    """
    Validate password strength
    Returns (is_valid, list_of_errors)
    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    """
    errors = []
    
    if not password:
        return False, ["Password is required"]
    
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    
    if len(password) > 128:
        errors.append("Password must be less than 128 characters")
    
    if not re.search(r'[A-Z]', password):
        errors.append("Password must contain at least one uppercase letter")
    
    if not re.search(r'[a-z]', password):
        errors.append("Password must contain at least one lowercase letter")
    
    if not re.search(r'\d', password):
        errors.append("Password must contain at least one number")
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)")
    
    return len(errors) == 0, errors


def validate_phone(phone: str) -> Tuple[bool, str]:
    """
    Validate Philippine phone number format
    Returns (is_valid, error_message)
    Accepts formats: +639xxxxxxxxx, 09xxxxxxxxx, 9xxxxxxxxx
    """
    if not phone:
        return True, ""  # Phone is optional
    
    phone = phone.strip().replace(" ", "").replace("-", "")
    
    # Philippine mobile number patterns
    patterns = [
        r'^\+639\d{9}$',      # +639xxxxxxxxx
        r'^09\d{9}$',         # 09xxxxxxxxx
        r'^9\d{9}$',          # 9xxxxxxxxx
    ]
    
    for pattern in patterns:
        if re.match(pattern, phone):
            return True, ""
    
    return False, "Please enter a valid Philippine mobile number (e.g., 09171234567)"


def validate_required_fields(data: dict, required_fields: List[str]) -> Tuple[bool, List[str]]:
    """
    Validate that all required fields are present and not empty
    Returns (is_valid, list_of_missing_fields)
    """
    missing = []
    
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            # Convert field name to readable format
            readable_name = field.replace('_', ' ').title()
            missing.append(f"{readable_name} is required")
    
    return len(missing) == 0, missing


def validate_name(name: str, field_name: str = "Name") -> Tuple[bool, str]:
    """
    Validate name fields (first name, last name)
    Returns (is_valid, error_message)
    """
    if not name:
        return False, f"{field_name} is required"
    
    name = name.strip()
    
    if len(name) < 2:
        return False, f"{field_name} must be at least 2 characters long"
    
    if len(name) > 50:
        return False, f"{field_name} must be less than 50 characters"
    
    # Only allow letters, spaces, hyphens, and apostrophes
    if not re.match(r"^[a-zA-Z\s\-']+$", name):
        return False, f"{field_name} can only contain letters, spaces, hyphens, and apostrophes"
    
    return True, ""


def validate_positive_number(value, field_name: str = "Value", min_val: float = 0, max_val: Optional[float] = None) -> Tuple[bool, str]:
    """
    Validate that a value is a positive number
    Returns (is_valid, error_message)
    """
    try:
        num = float(value)
    except (ValueError, TypeError):
        return False, f"{field_name} must be a valid number"
    
    if num < min_val:
        return False, f"{field_name} must be at least {min_val}"
    
    if max_val is not None and num > max_val:
        return False, f"{field_name} must be at most {max_val}"
    
    return True, ""


def validate_rating(rating) -> Tuple[bool, str]:
    """
    Validate rating (1-5)
    Returns (is_valid, error_message)
    """
    try:
        rating = int(rating)
    except (ValueError, TypeError):
        return False, "Rating must be a number between 1 and 5"
    
    if rating < 1 or rating > 5:
        return False, "Rating must be between 1 and 5"
    
    return True, ""
