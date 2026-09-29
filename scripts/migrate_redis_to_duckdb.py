"""One-off migration of the legacy Redis data into the DuckDB store.

Reads every key family the old redis_store wrote and inserts rows with their original
timestamps. Idempotent for an empty target: refuses to run when the target already has
climbers, so a restart cannot double-import.

    REDIS_HOST=... REDIS_PASSWORD=... uv run python scripts/migrate_redis_to_duckdb.py [target.duckdb]

main.py calls `migrate_if_empty()` on startup, so the first deploy with the store migrates by itself.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dates import album_climb_timestamp, parse_iso_timestamp  # noqa: E402
from store import Store  # noqa: E402

logger = logging.getLogger("climbing_app")


def _ts(value: Any) -> datetime:
    return parse_iso_timestamp(value) or datetime.now()


def _loads(value: Any, default: Any) -> Any:
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return default
    return loaded if isinstance(loaded, type(default)) else default


def migrate(store: Store, redis_client, binary_client) -> Dict[str, int]:
    db = store.db
    counts: Dict[str, int] = {}

    def count(name: str, n: int = 1) -> None:
        counts[name] = counts.get(name, 0) + n

    with db.transaction():
        # Catalogs
        for table, key in (("skills", "index:skills:all"), ("achievements", "index:achievements:all"), ("tags", "index:tags:all"), ("attribute_keys", "index:location_attributes:all")):
            for item in sorted(redis_client.smembers(key)):
                if item.strip():
                    db.run(f"INSERT OR IGNORE INTO {table} VALUES (?)", [item.strip()])

        # Climbers
        for name in sorted(redis_client.smembers("index:climbers:all")):
            data = redis_client.hgetall(f"climber:{name}")
            if not data:
                continue
            db.run(
                "INSERT OR IGNORE INTO climbers (name, home_locations, created_at, updated_at) VALUES (?, ?, ?, ?)",
                [name, json.dumps(_loads(data.get("location"), [])), _ts(data.get("created_at")), _ts(data.get("updated_at"))],
            )
            count("climbers")
            skill_sources = redis_client.hgetall(f"climber:{name}:skill_sources")
            achievement_sources = redis_client.hgetall(f"climber:{name}:achievement_sources")
            for skill in sorted(redis_client.smembers(f"climber:{name}:skills")):
                db.run("INSERT OR IGNORE INTO skills VALUES (?)", [skill])
                db.run(
                    "INSERT OR IGNORE INTO climber_skills (climber, skill, learned_in, added_at) VALUES (?, ?, ?, ?)",
                    [name, skill, skill_sources.get(skill), _ts(data.get("created_at"))],
                )
            for achievement in sorted(redis_client.smembers(f"climber:{name}:achievements")):
                db.run("INSERT OR IGNORE INTO achievements VALUES (?)", [achievement])
                db.run(
                    "INSERT OR IGNORE INTO climber_achievements (climber, achievement, learned_in, added_at) VALUES (?, ?, ?, ?)",
                    [name, achievement, achievement_sources.get(achievement), _ts(data.get("created_at"))],
                )
            for tag in sorted(redis_client.smembers(f"climber:{name}:tags")):
                db.run("INSERT OR IGNORE INTO tags VALUES (?)", [tag])
                db.run("INSERT OR IGNORE INTO climber_tags VALUES (?, ?)", [name, tag])

        # Locations
        for name in sorted(redis_client.smembers("index:locations:all")):
            data = redis_client.hgetall(f"location:{name}") or {"name": name}
            db.run(
                "INSERT OR IGNORE INTO locations (name, description, approach, latitude, longitude, custom_markers, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    name,
                    data.get("description") or "",
                    data.get("approach") or "",
                    float(data["latitude"]) if data.get("latitude") else None,
                    float(data["longitude"]) if data.get("longitude") else None,
                    json.dumps(_loads(data.get("custom_markers"), [])),
                    _ts(data.get("created_at")),
                    _ts(data.get("updated_at")),
                ],
            )
            count("locations")
            attributes = {k: "" for k in redis_client.smembers(f"location:{name}:attributes")}
            attributes.update(redis_client.hgetall(f"location:{name}:attributes_map"))
            for key, value in attributes.items():
                if key.strip():
                    db.run("INSERT OR IGNORE INTO attribute_keys VALUES (?)", [key])
                    db.run("INSERT OR IGNORE INTO location_attributes VALUES (?, ?, ?)", [name, key, value or ""])

        # Albums
        known_climbers = set(redis_client.smembers("index:climbers:all"))
        for url in sorted(redis_client.smembers("index:albums:all")):
            data = redis_client.hgetall(f"album:{url}")
            if not data:
                continue
            location = (data.get("location") or "").strip() or None
            if location:
                db.run("INSERT OR IGNORE INTO locations (name) VALUES (?)", [location])
            created_at = _ts(data.get("created_at"))
            climb = album_climb_timestamp({"date": data.get("date", ""), "created_at": created_at.isoformat()})
            db.run(
                "INSERT OR IGNORE INTO albums (url, title, description, date_text, climb_date, image_url, cover_image, location, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    url,
                    data.get("title", ""),
                    data.get("description", ""),
                    data.get("date", ""),
                    climb.date() if climb else None,
                    data.get("image_url", ""),
                    data.get("cover_image", ""),
                    location,
                    created_at,
                    _ts(data.get("updated_at")),
                ],
            )
            count("albums")
            for member in sorted(redis_client.smembers(f"album:{url}:crew")):
                if member in known_climbers:
                    db.run("INSERT OR IGNORE INTO album_crew VALUES (?, ?)", [url, member])
                else:
                    logger.warning(f"Album {url} lists unknown climber {member!r}; skipped")

        # Users and preferences
        for user_id in sorted(redis_client.smembers("index:users:all")):
            data = redis_client.hgetall(f"user:{user_id}")
            if not data or not data.get("email"):
                continue
            role = data.get("role") if data.get("role") in ("admin", "user", "pending") else "pending"
            db.run(
                "INSERT OR IGNORE INTO users (id, email, name, picture, role, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [user_id, data["email"], data.get("name"), data.get("picture"), role, _ts(data.get("created_at")), _ts(data.get("last_login"))],
            )
            count("users")
            for field, value in data.items():
                if field.startswith("preferences:"):
                    try:
                        parsed = json.loads(value)
                    except (TypeError, ValueError):
                        parsed = value
                    db.run("INSERT OR IGNORE INTO user_preferences VALUES (?, ?, ?)", [user_id, field.removeprefix("preferences:"), json.dumps(parsed)])

        # Ownership
        for key in redis_client.keys("ownership:*"):
            _, resource_type, resource_id = key.split(":", 2)
            if redis_client.type(key) != "set":
                continue
            for owner in redis_client.smembers(key):
                db.run("INSERT OR IGNORE INTO ownership VALUES (?, ?, ?)", [resource_type, resource_id, owner])
                count("ownership")

        # Memes
        for meme_id in sorted(redis_client.smembers("index:memes:all")):
            data = redis_client.hgetall(f"meme:{meme_id}")
            if data and data.get("creator_id"):
                db.run("INSERT OR IGNORE INTO memes (id, creator_id, created_at) VALUES (?, ?, ?)", [meme_id, data["creator_id"], _ts(data.get("created_at"))])
                count("memes")

        # Images (binary database): image:<kind>:<identifier>
        for raw_key in binary_client.keys("image:*"):
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            _, kind, identifier = key.split(":", 2)
            data = binary_client.get(raw_key)
            if not data:
                continue
            ttl = binary_client.ttl(raw_key)
            expires = datetime.now() + timedelta(seconds=ttl) if ttl and ttl > 0 else None
            db.run("INSERT OR IGNORE INTO images (kind, identifier, data, expires_at) VALUES (?, ?, ?, ?)", [kind, identifier, data, expires])
            count("images")

        # Push devices
        for key in redis_client.keys("device:*:subscription"):
            sub = _loads(redis_client.get(key), {})
            keys = sub.get("keys") or {}
            if not sub.get("endpoint") or not keys.get("p256dh") or not keys.get("auth") or not sub.get("device_id"):
                continue
            user_id = sub.get("user_id")
            db.run(
                "INSERT OR IGNORE INTO push_devices (device_id, subscription_id, user_id, endpoint, p256dh, auth, browser_name, platform, user_agent, preferences, created_at, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    sub["device_id"],
                    sub.get("subscription_id") or sub["device_id"],
                    None if user_id in (None, "", "anonymous") else user_id,
                    sub["endpoint"],
                    keys["p256dh"],
                    keys["auth"],
                    sub.get("browser_name") or "unknown",
                    sub.get("platform") or "unknown",
                    (sub.get("user_agent") or "")[:200],
                    json.dumps(_loads(sub.get("notification_preferences"), {}) or {"album_created": True, "crew_member_added": True, "meme_uploaded": True, "system_announcements": True}),
                    _ts(sub.get("created_at")),
                    parse_iso_timestamp(sub.get("last_used")),
                ],
            )
            count("push_devices")

        # API tokens
        for key in redis_client.keys("token_metadata:*"):
            _, user_id, token_id = key.split(":", 2)
            data = redis_client.hgetall(key)
            if not data.get("expires_at"):
                continue
            db.run(
                "INSERT OR IGNORE INTO api_tokens (token_id, user_id, name, permissions, created_at, expires_at, last_used, revoked) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    token_id,
                    user_id,
                    data.get("name") or "API Token",
                    json.dumps(_loads(data.get("permissions"), {})),
                    _ts(data.get("created_at")),
                    _ts(data.get("expires_at")),
                    parse_iso_timestamp(data.get("last_used")),
                    bool(redis_client.exists(f"blacklisted_token:{token_id}")),
                ],
            )
            count("api_tokens")

        # Faces of climbers that no longer exist were never cleaned up in Redis
        db.run(
            "DELETE FROM images WHERE kind = 'climber' AND NOT EXISTS "
            "(SELECT 1 FROM climbers c WHERE c.name || '/face' = images.identifier)"
        )

        # Notification counters: notifications:daily:<day>:<counter>
        for key in redis_client.keys("notifications:daily:*"):
            _, _, day, counter = key.split(":", 3)
            if counter not in ("sent", "failed", "cleaned"):
                continue
            value = int(redis_client.get(key) or 0)
            db.run("INSERT OR IGNORE INTO notification_counters (day) VALUES (?)", [day])
            db.run(f"UPDATE notification_counters SET {counter} = ? WHERE day = ?", [value, day])

    return counts


def connect_redis():
    try:
        import redis
    except ImportError as e:
        raise SystemExit("redis-py is not installed; run: uv run --with redis python scripts/migrate_redis_to_duckdb.py") from e

    from config import settings

    common = dict(host=settings.REDIS_HOST or "localhost", port=settings.REDIS_PORT, password=settings.REDIS_PASSWORD or None, socket_timeout=5)
    text = redis.Redis(db=0, decode_responses=True, **common)
    binary = redis.Redis(db=1, decode_responses=False, **common)
    text.ping()
    return text, binary


def migrate_if_empty(store: Store) -> Optional[Dict[str, int]]:
    """Import from Redis when the store is empty and REDIS_HOST is configured. Returns counts or None."""
    if not os.getenv("REDIS_HOST"):
        return None
    try:
        import redis  # noqa: F401
    except ImportError:
        logger.warning("REDIS_HOST is set but redis-py is not installed; skipping legacy migration")
        return None
    if store.db.value("SELECT count(*) FROM climbers") or store.db.value("SELECT count(*) FROM users"):
        return None
    try:
        text, binary = connect_redis()
    except Exception as e:  # Redis gone: nothing to migrate
        logger.warning(f"Redis not reachable, skipping legacy migration: {e}")
        return None
    if not text.scard("index:climbers:all"):
        return None
    counts = migrate(store, text, binary)
    store.db.run("CHECKPOINT")
    logger.info(f"Migrated legacy Redis data: {counts}")
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CLIMBING_DB_PATH", "climbing.duckdb")
    text_client, binary_client = connect_redis()
    result = migrate(Store(target), text_client, binary_client)
    print(json.dumps(result, indent=2))
