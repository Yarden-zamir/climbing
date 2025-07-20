#!/usr/bin/env python3
"""
Generate VAPID keys for web push notifications using webpush library approach.
Creates both PEM files and base64 encoded versions for config.
"""

import base64
import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def generate_vapid_keys():
    """Generate VAPID key pair and save in multiple formats"""
    print("🔧 Generating VAPID keys for webpush library...")
    
    # Generate private key
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    
    # Create keys directory if it doesn't exist
    keys_dir = Path("keys")
    keys_dir.mkdir(exist_ok=True)
    
    # Save private key as PEM
    private_pem_path = keys_dir / "private_key.pem"
    with open(private_pem_path, 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Save public key as PEM
    public_pem_path = keys_dir / "public_key.pem"
    with open(public_pem_path, 'wb') as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    
    # Generate base64 encoded versions for config
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    # Base64 encode for environment variables
    private_b64 = base64.b64encode(private_bytes).decode('utf-8')
    public_b64 = base64.b64encode(public_bytes).decode('utf-8')
    
    # Generate raw public key for browser
    raw_public_key = get_raw_public_key_from_pem(public_pem_path)
    
    print(f"✅ VAPID keys generated successfully!")
    print(f"📁 Private key saved to: {private_pem_path}")
    print(f"📁 Public key saved to: {public_pem_path}")
    print()
    print("🔐 Add these to your .env file:")
    print(f"VAPID_PRIVATE_KEY_B64={private_b64}")
    print(f"VAPID_PUBLIC_KEY_B64={public_b64}")
    print(f"VAPID_SUBSCRIBER=climbing@yarden-zamir.com")
    print()
    print(f"🌐 Raw public key for browser: {raw_public_key}")
    
    return {
        'private_pem_path': str(private_pem_path),
        'public_pem_path': str(public_pem_path),
        'private_b64': private_b64,
        'public_b64': public_b64,
        'raw_public_key': raw_public_key
    }


def get_raw_public_key_from_pem(pem_path):
    """Convert PEM public key to raw format for browser"""
    with open(pem_path, 'rb') as f:
        pem_data = f.read()
    
    public_key = serialization.load_pem_public_key(pem_data)
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    
    return base64.urlsafe_b64encode(public_bytes).decode('utf-8').rstrip('=')


def test_keys():
    """Test the generated keys with webpush library"""
    try:
        from webpush import WebPush
        
        keys_dir = Path("keys")
        private_pem = keys_dir / "private_key.pem"
        public_pem = keys_dir / "public_key.pem"
        
        if not private_pem.exists() or not public_pem.exists():
            print("❌ PEM files not found. Run generate_vapid_keys() first.")
            return False
        
        # Test WebPush initialization
        wp = WebPush(
            public_key=public_pem,
            private_key=private_pem,
            subscriber="climbing@yarden-zamir.com",
        )
        
        print("✅ Keys are compatible with webpush library!")
        return True
        
    except ImportError:
        print("⚠️  webpush library not installed. Install with: uv add webpush")
        return False
    except Exception as e:
        print(f"❌ Key test failed: {e}")
        return False


if __name__ == "__main__":
    keys = generate_vapid_keys()
    print("\n" + "="*50)
    test_keys() 
