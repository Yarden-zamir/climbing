"""Process-wide singletons wired at startup by main.py."""

from auth import get_current_user, require_auth  # noqa: F401  (re-exported for routes)

store = None
permissions_manager = None
logger = None
jwt_manager = None


def get_store():
    return store


def get_permissions_manager():
    return permissions_manager


def get_logger():
    return logger


def get_jwt_manager():
    return jwt_manager


def initialize_dependencies(store_instance, permissions_instance, logger_instance, jwt_manager_instance=None):
    global store, permissions_manager, logger, jwt_manager
    store = store_instance
    permissions_manager = permissions_instance
    logger = logger_instance
    jwt_manager = jwt_manager_instance
