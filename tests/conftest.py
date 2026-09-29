"""End-to-end fixtures: a real FastAPI app over a temporary DuckDB file.

Google Photos is never contacted: album metadata fetching is patched to return canned data.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="climbing-test-")
os.environ["CLIMBING_DB_PATH"] = str(Path(_TMP) / "test.duckdb")
os.environ["CLIMBING_BACKUP_DIR"] = str(Path(_TMP) / "backups")
os.environ["KEYS_DIR"] = str(Path(_TMP) / "keys")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENVIRONMENT"] = "test"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ.pop("REDIS_HOST", None)
os.chdir(ROOT)  # static files and schema are resolved relative to the repo


class FakeResponse:
    def __init__(self, text: str, content: bytes = b"", content_type: str = "text/html"):
        self.text = text
        self.content = content or text.encode()
        self.headers = {"content-type": content_type}


def fake_album_html(title: str = "Test Album", date: str = "Sep 27, 2025") -> str:
    return (
        f'<html><head><title>{title} · {date}</title>'
        f'<meta property="og:title" content="{title} · {date}">'
        '<meta property="og:description" content="Great day out">'
        '<meta property="og:image" content="https://lh3.googleusercontent.com/pw/abc=w1200-h630">'
        "</head><body></body></html>"
    )


@pytest.fixture(scope="session")
def app():
    import utils.metadata_parser as metadata_parser
    import routes.albums as albums_routes

    async def fake_fetch_url(client, url):
        from fastapi import HTTPException

        if not metadata_parser.is_allowed_fetch_url(url):
            raise HTTPException(status_code=400, detail="Only Google Photos URLs can be fetched")
        return FakeResponse(fake_album_html())

    metadata_parser.fetch_url = fake_fetch_url
    albums_routes.fetch_url = fake_fetch_url

    import main

    return main.app


@pytest.fixture(scope="session")
def store(app):
    import dependencies

    return dependencies.get_store()


@pytest.fixture(scope="session")
def client(app):
    from starlette.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def session_cookie(user: dict) -> str:
    from auth import session_manager

    return session_manager.create_session_token(user)


@pytest.fixture(scope="session")
def admin(client, store):
    import asyncio

    user = {"id": "admin1", "email": "admin@test.local", "name": "Admin", "picture": ""}
    asyncio.run(store.upsert_user(user_id=user["id"], email=user["email"], name=user["name"], picture=""))
    asyncio.run(store.set_user_role(user["id"], "admin"))
    return {**user, "role": "admin", "authenticated": True, "permissions": {"can_create_albums": True}}


@pytest.fixture(scope="session")
def member(client, store):
    import asyncio

    user = {"id": "member1", "email": "member@test.local", "name": "Member", "picture": ""}
    asyncio.run(store.upsert_user(user_id=user["id"], email=user["email"], name=user["name"], picture=""))
    asyncio.run(store.set_user_role(user["id"], "user"))
    return {**user, "role": "user", "authenticated": True, "permissions": {}}


@pytest.fixture(scope="session")
def pending(client, store):
    import asyncio

    user = {"id": "pending1", "email": "pending@test.local", "name": "Pending", "picture": ""}
    asyncio.run(store.upsert_user(user_id=user["id"], email=user["email"], name=user["name"], picture=""))
    return {**user, "role": "pending", "authenticated": True, "permissions": {}}


def as_user(client, user: dict):
    """Return kwargs for client calls that carry this user's session cookie."""
    return {"cookies": {"session": session_cookie(user)}}
