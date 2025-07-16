# Shared dependencies for the climbing app

# Import dependencies from auth module
from auth import get_current_user, require_auth

# Global instances that will be injected at startup
redis_store = None
permissions_manager = None
logger = None
jwt_manager = None

def get_redis_store():
    """Get the Redis store instance"""
    return redis_store

def get_permissions_manager():
    """Get the permissions manager instance"""
    return permissions_manager

def get_logger():
    """Get the logger instance"""
    return logger


def get_jwt_manager():
    """Get the JWT manager instance"""
    return jwt_manager


def initialize_dependencies(redis_instance, permissions_instance, logger_instance, jwt_manager_instance=None):
    """Initialize global dependencies at startup"""
    global redis_store, permissions_manager, logger, jwt_manager
    redis_store = redis_instance
    permissions_manager = permissions_instance
    logger = logger_instance
    jwt_manager = jwt_manager_instance
