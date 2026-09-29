"""List all users with their roles.

Usage: uv run python scripts/list_users.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from permissions import PermissionsManager  # noqa: E402
from store import Store  # noqa: E402


async def main() -> None:
    store = Store(
        os.environ.get(
            "CLIMBING_DB_PATH", str(Path(os.environ.get("KITSHN_DATA_DIR", ".")) / "climbing.duckdb")
        )
    )
    users = await PermissionsManager(store).get_all_users()
    if not users:
        print("No users found.")
        return
    for user in users:
        print(f"{user['id']}\t{user['email']}\t{user['role']}")
    print(f"Total users: {len(users)}")


if __name__ == "__main__":
    asyncio.run(main())
