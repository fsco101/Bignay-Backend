"""
Ngrok Tunnel Setup Script
Creates a secure tunnel for mobile device access
"""

import os
import sys
import json
import time
import subprocess
import threading
from pathlib import Path

# Configuration
BACKEND_PORT = 5000
NGROK_AUTH_TOKEN = None  # Set this or use environment variable

def check_ngrok_installed():
    """Check if ngrok is installed"""
    try:
        result = subprocess.run(['ngrok', 'version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ ngrok is installed: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    return False

def install_ngrok_instructions():
    """Print instructions to install ngrok"""
    print("\n" + "=" * 60)
    print("NGROK INSTALLATION REQUIRED")
    print("=" * 60)
    print("\nngrok is not installed. Please install it:")
    print("\n1. Download from: https://ngrok.com/download")
    print("2. Extract and add to PATH")
    print("3. Sign up at https://ngrok.com and get your auth token")
    print("4. Run: ngrok config add-authtoken YOUR_AUTH_TOKEN")
    print("\nAlternatively, install via package managers:")
    print("  - Windows (Chocolatey): choco install ngrok")
    print("  - Windows (Scoop): scoop install ngrok")
    print("  - macOS: brew install ngrok")
    print("=" * 60)

def configure_ngrok_auth(token):
    """Configure ngrok auth token"""
    try:
        result = subprocess.run(
            ['ngrok', 'config', 'add-authtoken', token],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("✓ ngrok auth token configured")
            return True
        else:
            print(f"✗ Failed to configure auth token: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ Error configuring auth token: {e}")
        return False

def get_ngrok_tunnel_url():
    """Get the public URL from running ngrok tunnel"""
    try:
        import requests
        response = requests.get('http://127.0.0.1:4040/api/tunnels', timeout=5)
        tunnels = response.json().get('tunnels', [])
        for tunnel in tunnels:
            if tunnel.get('proto') == 'https':
                return tunnel.get('public_url')
        # Fallback to http if no https
        for tunnel in tunnels:
            return tunnel.get('public_url')
    except Exception as e:
        print(f"Could not get tunnel URL: {e}")
    return None

def update_frontend_env(tunnel_url):
    """Update frontend .env file with tunnel URL"""
    frontend_dir = Path(__file__).parent.parent / 'frontend'
    env_file = frontend_dir / '.env'
    
    if not env_file.exists():
        print(f"Creating frontend .env file at {env_file}")
    
    # Read existing content
    existing_lines = []
    if env_file.exists():
        with open(env_file, 'r') as f:
            existing_lines = f.readlines()
    
    # Update or add EXPO_PUBLIC_API_URL
    new_lines = []
    url_updated = False
    
    for line in existing_lines:
        stripped = line.strip()
        # Skip existing API URL lines (both commented and uncommented)
        if stripped.startswith('EXPO_PUBLIC_API_URL=') and not stripped.startswith('#'):
            # Replace with new tunnel URL
            new_lines.append(f"EXPO_PUBLIC_API_URL={tunnel_url}\n")
            url_updated = True
        else:
            new_lines.append(line)
    
    if not url_updated:
        new_lines.append(f"\n# Ngrok Tunnel URL (auto-generated)\n")
        new_lines.append(f"EXPO_PUBLIC_API_URL={tunnel_url}\n")
    
    with open(env_file, 'w') as f:
        f.writelines(new_lines)
    
    print(f"✓ Updated frontend .env with tunnel URL: {tunnel_url}")
    return True

def start_ngrok_tunnel(port=BACKEND_PORT):
    """Start ngrok tunnel for the backend"""
    print(f"\n🚀 Starting ngrok tunnel for port {port}...")
    
    try:
        # Start ngrok in background
        process = subprocess.Popen(
            ['ngrok', 'http', str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for tunnel to establish
        print("Waiting for tunnel to establish...")
        time.sleep(3)
        
        # Get the tunnel URL
        tunnel_url = get_ngrok_tunnel_url()
        
        if tunnel_url:
            print("\n" + "=" * 60)
            print("🎉 NGROK TUNNEL ACTIVE")
            print("=" * 60)
            print(f"\n📱 Public URL: {tunnel_url}")
            print(f"🖥️  Local URL:  http://localhost:{port}")
            print("\n📋 Copy this URL to your mobile app or share with others!")
            print("=" * 60)
            
            # Update frontend .env
            update_frontend_env(tunnel_url)
            
            print("\n⚠️  Press Ctrl+C to stop the tunnel")
            print("=" * 60)
            
            return process, tunnel_url
        else:
            print("✗ Failed to get tunnel URL")
            process.terminate()
            return None, None
            
    except Exception as e:
        print(f"✗ Error starting tunnel: {e}")
        return None, None

def main():
    print("\n" + "=" * 60)
    print("🌐 BIGNAY APP - NGROK TUNNEL SETUP")
    print("=" * 60)
    
    # Check if ngrok is installed
    if not check_ngrok_installed():
        install_ngrok_instructions()
        return
    
    # Check for auth token
    auth_token = os.environ.get('NGROK_AUTH_TOKEN') or NGROK_AUTH_TOKEN
    if auth_token:
        configure_ngrok_auth(auth_token)
    
    # Start the tunnel
    process, tunnel_url = start_ngrok_tunnel()
    
    if process:
        try:
            # Keep running until interrupted
            while True:
                time.sleep(1)
                # Check if process is still running
                if process.poll() is not None:
                    print("\n✗ ngrok process ended unexpectedly")
                    break
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping ngrok tunnel...")
            process.terminate()
            print("✓ Tunnel stopped")
    
    print("\n👋 Goodbye!")

if __name__ == '__main__':
    main()
