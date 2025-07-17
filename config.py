import os
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

        # OAuth URLs
        self.GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid_configuration"
        self.GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
        self.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
        self.GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

        # OAuth Scopes
        self.OAUTH_SCOPES = ["openid", "email", "profile"]

        # Session Configuration
        self.SESSION_MAX_AGE = 86400 * 7  # 7 days in seconds
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    def validate_oauth_config(self) -> bool:
        """Validate that required OAuth configuration is present"""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

settings = Settings() 
