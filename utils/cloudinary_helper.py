"""
Cloudinary Helper
Handles image upload, deletion, and URL management for product images
"""

import os
import base64
from typing import Tuple, Optional, List
from datetime import datetime


_cloudinary_configured = False


def _get_cloudinary_config():
    """Get Cloudinary configuration from environment (called at runtime, not import time)"""
    return {
        'cloud_name': os.getenv('CLOUDINARY_CLOUD_NAME', ''),
        'api_key': os.getenv('CLOUDINARY_API_KEY', ''),
        'api_secret': os.getenv('CLOUDINARY_API_SECRET', ''),
    }


def _configure_cloudinary() -> bool:
    """Configure Cloudinary SDK"""
    global _cloudinary_configured
    
    if _cloudinary_configured:
        return True
    
    # Get config at runtime (after .env is loaded)
    config = _get_cloudinary_config()
    
    if not all([config['cloud_name'], config['api_key'], config['api_secret']]):
        print(f"[Cloudinary] Missing configuration:")
        print(f"  - CLOUDINARY_CLOUD_NAME: {'SET' if config['cloud_name'] else 'MISSING'}")
        print(f"  - CLOUDINARY_API_KEY: {'SET' if config['api_key'] else 'MISSING'}")
        print(f"  - CLOUDINARY_API_SECRET: {'SET' if config['api_secret'] else 'MISSING'}")
        return False
    
    try:
        import cloudinary
        cloudinary.config(
            cloud_name=config['cloud_name'],
            api_key=config['api_key'],
            api_secret=config['api_secret'],
            secure=True
        )
        _cloudinary_configured = True
        print(f"[Cloudinary] Configured successfully for cloud: {config['cloud_name']}")
        return True
    except ImportError:
        print("Cloudinary SDK not installed. Run: pip install cloudinary")
        return False
    except Exception as e:
        print(f"Failed to configure Cloudinary: {e}")
        return False


def upload_image(image_data: str, folder: str = "products", public_id: Optional[str] = None) -> Tuple[bool, str, str]:
    """
    Upload image to Cloudinary
    
    Args:
        image_data: Base64 encoded image or URL
        folder: Cloudinary folder to store image
        public_id: Optional custom public ID for the image
    
    Returns:
        (success, url_or_error, public_id)
    """
    if not _configure_cloudinary():
        print("[Cloudinary] Not configured - missing environment variables")
        return False, "Cloudinary not configured. Please set environment variables.", ""
    
    try:
        import cloudinary.uploader
        
        # Generate unique public_id if not provided
        if not public_id:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            public_id = f"bignay_{timestamp}"
        
        # Prepare upload data
        upload_data = image_data
        
        # Log the type of image data being processed
        if image_data.startswith('data:'):
            print(f"[Cloudinary] Processing data URL image (length: {len(image_data)})")
        elif image_data.startswith(('http://', 'https://')):
            print(f"[Cloudinary] Processing URL image: {image_data[:50]}...")
        else:
            # Assume it's raw base64, add data URL prefix
            print(f"[Cloudinary] Processing raw base64 image (length: {len(image_data)})")
            upload_data = f"data:image/jpeg;base64,{image_data}"
        
        # Upload options
        options = {
            'folder': folder,
            'public_id': public_id,
            'overwrite': True,
            'resource_type': 'image',
            'transformation': [
                {'width': 1200, 'height': 1200, 'crop': 'limit'},
                {'quality': 'auto:good'},
                {'fetch_format': 'auto'}
            ]
        }
        
        print(f"[Cloudinary] Uploading to folder: {folder}, public_id: {public_id}")
        result = cloudinary.uploader.upload(upload_data, **options)
        
        print(f"[Cloudinary] Upload successful: {result['secure_url']}")
        return True, result['secure_url'], result['public_id']
    
    except Exception as e:
        print(f"[Cloudinary] Upload failed: {str(e)}")
        return False, f"Upload failed: {str(e)}", ""


def upload_multiple_images(images: List[str], folder: str = "products") -> List[dict]:
    """
    Upload multiple images to Cloudinary
    
    Args:
        images: List of base64 encoded images or URLs
        folder: Cloudinary folder to store images
    
    Returns:
        List of dicts with success, url, public_id, and error
    """
    results = []
    
    for i, image_data in enumerate(images):
        success, url_or_error, public_id = upload_image(image_data, folder)
        results.append({
            'index': i,
            'success': success,
            'url': url_or_error if success else None,
            'public_id': public_id,
            'error': None if success else url_or_error
        })
    
    return results


def delete_image(public_id: str) -> Tuple[bool, str]:
    """
    Delete image from Cloudinary
    
    Args:
        public_id: The public ID of the image to delete
    
    Returns:
        (success, message)
    """
    if not _configure_cloudinary():
        return False, "Cloudinary not configured"
    
    try:
        import cloudinary.uploader
        
        result = cloudinary.uploader.destroy(public_id)
        
        if result.get('result') == 'ok':
            return True, "Image deleted successfully"
        else:
            return False, f"Delete failed: {result.get('result', 'Unknown error')}"
    
    except Exception as e:
        return False, f"Delete failed: {str(e)}"


def delete_multiple_images(public_ids: List[str]) -> List[dict]:
    """
    Delete multiple images from Cloudinary
    
    Args:
        public_ids: List of public IDs to delete
    
    Returns:
        List of dicts with success and message
    """
    results = []
    
    for public_id in public_ids:
        success, message = delete_image(public_id)
        results.append({
            'public_id': public_id,
            'success': success,
            'message': message
        })
    
    return results


def get_image_url(public_id: str, transformation: Optional[dict] = None) -> str:
    """
    Generate Cloudinary URL for an image with optional transformations
    
    Args:
        public_id: The public ID of the image
        transformation: Optional transformation options
    
    Returns:
        The generated URL
    """
    if not _configure_cloudinary():
        return ""
    
    try:
        import cloudinary
        
        options = {'secure': True}
        
        if transformation:
            options['transformation'] = transformation
        
        url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
        return url
    
    except Exception as e:
        print(f"Failed to generate URL: {e}")
        return ""


def get_thumbnail_url(public_id: str, width: int = 300, height: int = 300) -> str:
    """
    Generate thumbnail URL for an image
    
    Args:
        public_id: The public ID of the image
        width: Thumbnail width
        height: Thumbnail height
    
    Returns:
        The thumbnail URL
    """
    return get_image_url(public_id, {
        'width': width,
        'height': height,
        'crop': 'fill',
        'gravity': 'auto',
        'quality': 'auto:good',
        'fetch_format': 'auto'
    })


def is_cloudinary_configured() -> bool:
    """Check if Cloudinary is properly configured"""
    return _configure_cloudinary()
