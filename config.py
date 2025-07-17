import os
import base64
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    def __init__(self):
        # OAuth Configuration
        self.GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
        self.GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

        # Session Configuration
        self.SECRET_KEY: str = os.getenv("SECRET_KEY") or ""
        if not self.SECRET_KEY:
            print("SECRET_KEY environment variable is must be set to a secure random value to enable google auth")

        # App Configuration
        self.BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8001")
        self.ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

        # Redis Configuration
        self.REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
        self.REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
        self.REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
        self.REDIS_SSL: bool = os.getenv("REDIS_SSL", "false").lower() == "true"

        # VAPID Configuration (new webpush approach)
        self.VAPID_PRIVATE_KEY_B64: str = os.getenv("VAPID_PRIVATE_KEY_B64", "")
        self.VAPID_PUBLIC_KEY_B64: str = os.getenv("VAPID_PUBLIC_KEY_B64", "")
        self.VAPID_SUBSCRIBER: str = os.getenv("VAPID_SUBSCRIBER", "climbing@yarden-zamir.com")
        
        # Key file paths
        self.KEYS_DIR = Path("keys")
        self.PRIVATE_KEY_PATH = self.KEYS_DIR / "private_key.pem"
        self.PUBLIC_KEY_PATH = self.KEYS_DIR / "public_key.pem"

        # OAuth URLs
        self.GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid_configuration"
        self.GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
        self.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
        self.GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

        # OAuth Scopes
        self.OAUTH_SCOPES = ["openid", "email", "profile"]

        # Session Configuration
        self.SESSION_MAX_AGE = 86400 * 7  # 7 days in seconds
        
        # Initialize VAPID keys
        self._ensure_vapid_keys()
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    def validate_oauth_config(self) -> bool:
        """Validate that required OAuth configuration is present"""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    def validate_vapid_config(self) -> bool:
        """Validate that required VAPID configuration is present"""
        return (self.PRIVATE_KEY_PATH.exists() and 
                self.PUBLIC_KEY_PATH.exists())

    def _ensure_vapid_keys(self):
        """Ensure VAPID keys exist, generate them if they don't"""
        if not self.validate_vapid_config():
            print("🔧 VAPID keys not found, generating new ones...")
            self._generate_vapid_keys()
        else:
            print("✅ VAPID keys found")

    def _generate_vapid_keys(self):
        """Generate VAPID keys for web push notifications"""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            
            # Generate private key
            private_key = ec.generate_private_key(ec.SECP256R1())
            public_key = private_key.public_key()
            
            # Create keys directory if it doesn't exist
            self.KEYS_DIR.mkdir(exist_ok=True)
            
            # Save private key as PEM
            with open(self.PRIVATE_KEY_PATH, 'wb') as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            # Save public key as PEM
            with open(self.PUBLIC_KEY_PATH, 'wb') as f:
                f.write(public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))
            
            print(f"✅ Generated VAPID keys:")
            print(f"   Private: {self.PRIVATE_KEY_PATH}")
            print(f"   Public: {self.PUBLIC_KEY_PATH}")
            print(f"🌐 Raw public key: {self.get_raw_public_key()}")
            
        except Exception as e:
            print(f"❌ Failed to generate VAPID keys: {e}")
            raise

    def get_webpush_instance(self):
        """Get a configured WebPush instance"""
        try:
            from webpush import WebPush
            
            if not self.validate_vapid_config():
                raise ValueError("VAPID keys not found")
            
            return WebPush(
                public_key=self.PUBLIC_KEY_PATH,
                private_key=self.PRIVATE_KEY_PATH,
                subscriber=self.VAPID_SUBSCRIBER,
            )
        except ImportError:
            raise ImportError("webpush library not installed. Run: uv add webpush")

    def get_raw_public_key(self) -> str:
        """Get the raw public key for browser subscription"""
        try:
            from cryptography.hazmat.primitives import serialization
            
            if not self.PUBLIC_KEY_PATH.exists():
                raise FileNotFoundError("Public key file not found")
            
            with open(self.PUBLIC_KEY_PATH, 'rb') as f:
                pem_data = f.read()
            
            public_key = serialization.load_pem_public_key(pem_data)
            public_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint
            )
            
            return base64.urlsafe_b64encode(public_bytes).decode('utf-8').rstrip('=')
            
        except Exception as e:
            print(f"❌ Failed to get raw public key: {e}")
            return ""

settings = Settings() 
