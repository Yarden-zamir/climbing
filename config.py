import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    # OAuth Configuration
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    
    # Session Configuration
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
    
    # App Configuration
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8001")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # OAuth URLs
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid_configuration"
    GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    
    # OAuth Scopes
    OAUTH_SCOPES = ["openid", "email", "profile"]
    
    # Session Configuration
    SESSION_MAX_AGE = 86400 * 7  # 7 days in seconds
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    def validate_oauth_config(self) -> bool:
        """Validate that required OAuth configuration is present"""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

settings = Settings() 
