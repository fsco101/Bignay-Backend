"""
Cloudinary Helper - Direct Connection
Handles image upload, deletion, and URL management for product images
Reads credentials DIRECTLY from .env file to ensure reliability
"""

import os
import re
from typing import Tuple, Optional, List
from datetime import datetime
from pathlib import Path

# ============================================================================
# HARDCODED CLOUDINARY CREDENTIALS (from your .env file)
# This ensures the connection ALWAYS works regardless of environment loading
# ============================================================================

# Your Cloudinary credentials - DIRECT from .env
CLOUDINARY_CLOUD_NAME = "dbeghehuz"
CLOUDINARY_API_KEY = "622152818322852"
CLOUDINARY_API_SECRET = "pEay9ee8Gzt_b50b-3765ggpSKc"

print("=" * 60)
print("[Cloudinary] DIRECT CONNECTION MODE")
print(f"[Cloudinary] Cloud Name: {CLOUDINARY_CLOUD_NAME}")
print(f"[Cloudinary] API Key: {CLOUDINARY_API_KEY[:6]}...")
print(f"[Cloudinary] API Secret: {'*' * 10}")
print("=" * 60)

# Configure Cloudinary immediately at module load
_cloudinary_configured = False

def _configure_cloudinary() -> bool:
    """Configure Cloudinary SDK with hardcoded credentials"""
    global _cloudinary_configured
    
    if _cloudinary_configured:
        return True
    
    try:
        import cloudinary
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
        _cloudinary_configured = True
        print(f"[Cloudinary] ✓ SDK configured for cloud: {CLOUDINARY_CLOUD_NAME}")
        return True
    except ImportError:
        print("[Cloudinary] ✗ ERROR: cloudinary package not installed!")
        print("[Cloudinary] Run: pip install cloudinary")
        return False
    except Exception as e:
        print(f"[Cloudinary] ✗ Configuration error: {e}")
        return False

# Configure on module import
_configure_cloudinary()


def upload_image(image_data: str, folder: str = "products", public_id: Optional[str] = None) -> Tuple[bool, str, str]:
    """
    Upload image to Cloudinary
    
    Args:
        image_data: Base64 encoded image (data:image/...) or URL
        folder: Cloudinary folder to store image
        public_id: Optional custom public ID
    
    Returns:
        Tuple of (success, url_or_error, public_id)
    """
    if not _configure_cloudinary():
        return False, "Cloudinary not configured", ""
    
    try:
        import cloudinary.uploader
        
        # Validate input
        if not image_data:
            print("[Cloudinary] ✗ No image data provided")
            return False, "No image data provided", ""
        
        if len(image_data) < 50:
            print(f"[Cloudinary] ✗ Image data too short: {len(image_data)} chars")
            return False, "Image data too short", ""
        
        # Generate unique public_id
        if not public_id:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            public_id = f"bignay_{timestamp}"
        
        # Process image data
        upload_data = image_data
        
        if image_data.startswith('data:'):
            # Already a data URL - ready to upload
            print(f"[Cloudinary] Processing data URL (length: {len(image_data)})")
        elif image_data.startswith(('http://', 'https://')):
            # Already a URL
            if 'cloudinary.com' in image_data or 'res.cloudinary.com' in image_data:
                print(f"[Cloudinary] Already a Cloudinary URL, skipping upload")
                return True, image_data, ""
            print(f"[Cloudinary] Processing external URL")
        else:
            # Raw base64 - detect type and add prefix
            print(f"[Cloudinary] Processing raw base64 (length: {len(image_data)})")
            if image_data.startswith('/9j/'):
                upload_data = f"data:image/jpeg;base64,{image_data}"
            elif image_data.startswith('iVBOR'):
                upload_data = f"data:image/png;base64,{image_data}"
            elif image_data.startswith('R0lGOD'):
                upload_data = f"data:image/gif;base64,{image_data}"
            elif image_data.startswith('UklGR'):
                upload_data = f"data:image/webp;base64,{image_data}"
            else:
                # Default to JPEG
                upload_data = f"data:image/jpeg;base64,{image_data}"
        
        # Upload to Cloudinary
        print(f"[Cloudinary] Uploading to {folder}/{public_id}...")
        
        result = cloudinary.uploader.upload(
            upload_data,
            folder=folder,
            public_id=public_id,
            overwrite=True,
            resource_type='image',
            transformation=[
                {'width': 1200, 'height': 1200, 'crop': 'limit'},
                {'quality': 'auto:good'},
                {'fetch_format': 'auto'}
            ]
        )
        
        url = result.get('secure_url', '')
        pid = result.get('public_id', '')
        
        print(f"[Cloudinary] ✓ Upload successful: {url}")
        return True, url, pid
    
    except Exception as e:
        error_msg = str(e)
        print(f"[Cloudinary] ✗ Upload failed: {error_msg}")
        return False, f"Upload failed: {error_msg}", ""


def upload_multiple_images(images: List[str], folder: str = "products") -> List[dict]:
    """
    Upload multiple images to Cloudinary
    
    Args:
        images: List of base64 images or URLs
        folder: Cloudinary folder
    
    Returns:
        List of upload results
    """
    if not images:
        return []
    
    results = []
    print(f"[Cloudinary] Uploading {len(images)} images...")
    
    for i, image_data in enumerate(images):
        if not image_data or not isinstance(image_data, str):
            results.append({
                'index': i,
                'success': False,
                'url': None,
                'public_id': '',
                'error': 'Invalid image data'
            })
            continue
        
        success, url_or_error, public_id = upload_image(image_data, folder)
        results.append({
            'index': i,
            'success': success,
            'url': url_or_error if success else None,
            'public_id': public_id,
            'error': None if success else url_or_error
        })
    
    successful = sum(1 for r in results if r['success'])
    print(f"[Cloudinary] Batch upload complete: {successful}/{len(images)} successful")
    
    return results


def delete_image(public_id: str) -> Tuple[bool, str]:
    """Delete image from Cloudinary"""
    if not _configure_cloudinary():
        return False, "Cloudinary not configured"
    
    if not public_id:
        return False, "No public_id provided"
    
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.destroy(public_id)
        
        if result.get('result') == 'ok':
            print(f"[Cloudinary] ✓ Deleted: {public_id}")
            return True, "Image deleted successfully"
        else:
            return False, f"Delete failed: {result.get('result', 'Unknown error')}"
    except Exception as e:
        return False, f"Delete failed: {str(e)}"


def delete_multiple_images(public_ids: List[str]) -> List[dict]:
    """Delete multiple images from Cloudinary"""
    results = []
    for public_id in public_ids:
        if public_id:
            success, message = delete_image(public_id)
            results.append({
                'public_id': public_id,
                'success': success,
                'message': message
            })
    return results


def get_image_url(public_id: str, transformation: Optional[dict] = None) -> str:
    """Generate Cloudinary URL for an image"""
    if not _configure_cloudinary() or not public_id:
        return ""
    
    try:
        import cloudinary
        options = {'secure': True}
        if transformation:
            options['transformation'] = transformation
        url, _ = cloudinary.utils.cloudinary_url(public_id, **options)
        return url
    except Exception as e:
        print(f"[Cloudinary] URL generation failed: {e}")
        return ""


def get_thumbnail_url(public_id: str, width: int = 300, height: int = 300) -> str:
    """Generate thumbnail URL"""
    return get_image_url(public_id, {
        'width': width,
        'height': height,
        'crop': 'fill',
        'gravity': 'auto',
        'quality': 'auto:good',
        'fetch_format': 'auto'
    })


def is_cloudinary_configured() -> bool:
    """Check if Cloudinary is configured"""
    return _configure_cloudinary()


# Test connection on import
def _test_connection():
    """Quick test to verify Cloudinary connection"""
    try:
        import cloudinary.api
        # This will fail fast if credentials are wrong
        result = cloudinary.api.ping()
        print(f"[Cloudinary] ✓ Connection test passed: {result}")
        return True
    except Exception as e:
        print(f"[Cloudinary] Connection test: {e}")
        return False

# Run test on module load
if _cloudinary_configured:
    _test_connection()
