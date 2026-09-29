"""Give a user the admin role.

Usage: uv run python scripts/make_admin.py <user_email>
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from permissions import PermissionsManager  # noqa: E402
from store import Store  # noqa: E402


async def main(email: str) -> None:
    store = Store(
        os.environ.get(
            "CLIMBING_DB_PATH", str(Path(os.environ.get("KITSHN_DATA_DIR", ".")) / "climbing.duckdb")
        )
    )
    permissions_manager = PermissionsManager(store)
    user = await permissions_manager.get_user_by_email(email)
    if not user:
        sys.exit(f"User with email '{email}' not found.")
    if user["role"] == "admin":
        print(f"User '{email}' is already an admin.")
        return
    if not await permissions_manager.assign_admin_user(email):
        sys.exit(f"Failed to make '{email}' an admin.")
    print(f"Made '{email}' an admin (previous role: {user['role']}).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python scripts/make_admin.py <user_email>")
    asyncio.run(main(sys.argv[1]))
