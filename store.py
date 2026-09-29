"""DuckDB-backed data store.

One process owns the database file (DuckDB is single-writer). All access goes through
`Store`, whose methods are async so call sites read naturally, while the work itself is
short synchronous SQL under one lock. Derived facts (climb counts, levels, "new" climbers,
creation counts per user) are computed in queries and never stored.
"""

import hashlib
import json
import logging
import re
import shutil
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import duckdb

from dates import NEW_CLIMBER_WINDOW_DAYS, album_climb_timestamp

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9\s\-_'.()]+$")
ALBUM_URL_PATTERN = re.compile(r"^https://photos\.app\.goo\.gl/[a-zA-Z0-9]+$")
DEFAULT_NOTIFICATION_PREFERENCES = {
    "album_created": True,
    "crew_member_added": True,
    "meme_uploaded": True,
    "system_announcements": True,
}
IMAGE_URL_PREFIX = "/redis-image"  # kept: every stored image_url and the frontend use this path


class ValidationError(Exception):
    """Input rejected by the store; the message is safe to show to users."""


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(value) if value is not None else {}
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def validate_name(name: Any) -> str:
    if not name or not isinstance(name, str):
        raise ValidationError("Name must be a non-empty string")
    name = name.strip()
    if len(name) > 100:
        raise ValidationError("Name must be between 1 and 100 characters")
    if not NAME_PATTERN.match(name):
        raise ValidationError("Name contains invalid characters")
    return name


def validate_album_url(url: Any) -> str:
    if not url or not isinstance(url, str) or not ALBUM_URL_PATTERN.match(url):
        raise ValidationError("Invalid Google Photos URL format")
    return url


def clean_items(items: Optional[Iterable[Any]], what: str) -> List[str]:
    """Strip, drop empties and duplicates, keep order."""
    cleaned: List[str] = []
    for item in items or []:
        if not isinstance(item, str):
            raise ValidationError(f"{what} must be a string: {item!r}")
        item = item.strip()
        if not item:
            raise ValidationError(f"{what} cannot be empty")
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


class Database:
    """Thin lock-guarded wrapper over one DuckDB connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.path))
        self.lock = threading.RLock()
        with self.lock:
            sql = "\n".join(
                line for line in SCHEMA_PATH.read_text().splitlines() if not line.lstrip().startswith("--")
            )
            for statement in sql.split(";"):
                if statement.strip():
                    self.conn.execute(statement)

    def rows(self, sql: str, params: Sequence[Any] = ()) -> List[dict]:
        with self.lock:
            cursor = self.conn.execute(sql, list(params))
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def row(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
        result = self.rows(sql, params)
        return result[0] if result else None

    def value(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self.lock:
            row = self.conn.execute(sql, list(params)).fetchone()
            return row[0] if row else None

    def run(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self.lock:
            self.conn.execute(sql, list(params))

    def run_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        with self.lock:
            self.conn.executemany(sql, [list(r) for r in rows])

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")


class Store:
    def __init__(self, path: str | Path):
        self.db = Database(path)
        self._metadata_cache: Dict[str, tuple[datetime, Dict]] = {}
        self.purge_expired_images()

    # ------------------------------------------------------------------ levels

    @staticmethod
    def calculate_climber_level(
        skills_count: int, climbs: int, achievements_count: int = 0, locations_count: int = 0
    ) -> tuple[int, int, int, int, int]:
        """Returns (total, from_skills, from_climbs, from_achievements, from_locations)."""
        from_climbs = climbs // 5
        total = 1 + skills_count + from_climbs + achievements_count + locations_count
        return total, skills_count, from_climbs, achievements_count, locations_count

    @staticmethod
    def calculate_climbs_to_next_level(climbs: int) -> int:
        remainder = climbs % 5
        return 5 - remainder if remainder else 0

    # ---------------------------------------------------------------- climbers

    async def add_climber(
        self,
        name: str,
        location: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        achievements: Optional[List[str]] = None,
    ) -> None:
        name = validate_name(name)
        skills = clean_items(skills, "Skill")
        tags = clean_items(tags, "Tag")
        achievements = clean_items(achievements, "Achievement")
        if self.db.value("SELECT count(*) FROM climbers WHERE name = ?", [name]):
            raise ValidationError(f"Climber already exists: {name}")
        with self.db.transaction():
            self.db.run(
                "INSERT INTO climbers (name, home_locations) VALUES (?, ?)",
                [name, json.dumps(location or [])],
            )
            self._set_climber_items(name, skills, tags, achievements)
        logger.info(f"Added climber: {name}")

    def _set_climber_items(
        self, name: str, skills: List[str], tags: List[str], achievements: List[str]
    ) -> None:
        """Replace a climber's skills, tags and achievements. Provenance survives for kept items."""
        self.db.run_many("INSERT OR IGNORE INTO skills VALUES (?)", [[s] for s in skills])
        self.db.run_many("INSERT OR IGNORE INTO tags VALUES (?)", [[t] for t in tags])
        self.db.run_many("INSERT OR IGNORE INTO achievements VALUES (?)", [[a] for a in achievements])
        self.db.run(
            "DELETE FROM climber_skills WHERE climber = ? AND skill NOT IN (SELECT unnest(?::TEXT[]))",
            [name, skills],
        )
        self.db.run(
            "DELETE FROM climber_achievements WHERE climber = ? AND achievement NOT IN (SELECT unnest(?::TEXT[]))",
            [name, achievements],
        )
        self.db.run("DELETE FROM climber_tags WHERE climber = ?", [name])
        self.db.run_many(
            "INSERT OR IGNORE INTO climber_skills (climber, skill) VALUES (?, ?)", [[name, s] for s in skills]
        )
        self.db.run_many(
            "INSERT OR IGNORE INTO climber_achievements (climber, achievement) VALUES (?, ?)",
            [[name, a] for a in achievements],
        )
        self.db.run_many("INSERT INTO climber_tags VALUES (?, ?)", [[name, t] for t in tags])

    def _climber_rows(self, names: Optional[List[str]] = None) -> List[dict]:
        where = "WHERE c.name IN (SELECT unnest(?::TEXT[]))" if names is not None else ""
        params = [names] if names is not None else []
        cutoff = date.today() - timedelta(days=NEW_CLIMBER_WINDOW_DAYS)
        rows = self.db.rows(
            f"""
            WITH participation AS (
                SELECT ac.climber,
                       count(*) AS climbs,
                       min(coalesce(a.climb_date, CAST(a.created_at AS DATE))) AS first_seen,
                       list_sort(list_distinct(list(a.location) FILTER (WHERE a.location IS NOT NULL AND a.location <> ''))) AS locations_visited
                FROM album_crew ac JOIN albums a ON a.url = ac.album_url
                GROUP BY ac.climber
            )
            SELECT c.name, c.home_locations, c.created_at, c.updated_at,
                   coalesce(p.climbs, 0) AS climbs, p.first_seen,
                   coalesce(p.locations_visited, []) AS locations_visited
            FROM climbers c LEFT JOIN participation p ON p.climber = c.name
            {where}
            """,
            params,
        )
        if not rows:
            return []
        selected = [r["name"] for r in rows]
        skills = self._group(
            "SELECT climber, skill AS item, learned_in FROM climber_skills WHERE climber IN (SELECT unnest(?::TEXT[])) ORDER BY added_at, skill",
            selected,
        )
        achievements = self._group(
            "SELECT climber, achievement AS item, learned_in FROM climber_achievements WHERE climber IN (SELECT unnest(?::TEXT[])) ORDER BY added_at, achievement",
            selected,
        )
        tags = self._group(
            "SELECT climber, tag AS item, NULL AS learned_in FROM climber_tags WHERE climber IN (SELECT unnest(?::TEXT[])) ORDER BY tag",
            selected,
        )
        result = []
        for r in rows:
            name = r["name"]
            skill_rows = skills.get(name, [])
            achievement_rows = achievements.get(name, [])
            locations_visited = list(r["locations_visited"] or [])
            total, from_skills, from_climbs, from_achievements, from_locations = self.calculate_climber_level(
                len(skill_rows), r["climbs"], len(achievement_rows), len(locations_visited)
            )
            first_seen = r["first_seen"]
            result.append(
                {
                    "name": name,
                    "location": _json_list(r["home_locations"]),
                    "skills": [s["item"] for s in skill_rows],
                    "achievements": [a["item"] for a in achievement_rows],
                    "tags": [t["item"] for t in tags.get(name, [])],
                    "skill_sources": {s["item"]: s["learned_in"] for s in skill_rows if s["learned_in"]},
                    "achievement_sources": {
                        a["item"]: a["learned_in"] for a in achievement_rows if a["learned_in"]
                    },
                    "climbs": r["climbs"],
                    "is_new": bool(first_seen and first_seen >= cutoff),
                    "first_seen_at": _iso(first_seen),
                    "first_climb_date": first_seen.strftime("%b %d, %Y") if first_seen else None,
                    "level": total,
                    "level_from_skills": from_skills,
                    "level_from_climbs": from_climbs,
                    "level_from_achievements": from_achievements,
                    "level_from_locations": from_locations,
                    "locations_visited": locations_visited,
                    "face": f"{IMAGE_URL_PREFIX}/climber/{name}/face",
                    "created_at": _iso(r["created_at"]),
                    "updated_at": _iso(r["updated_at"]),
                }
            )
        return result

    def _group(self, sql: str, names: List[str]) -> Dict[str, List[dict]]:
        grouped: Dict[str, List[dict]] = {}
        for row in self.db.rows(sql, [names]):
            grouped.setdefault(row["climber"], []).append(row)
        return grouped

    async def get_climber(self, name: str) -> Optional[Dict]:
        rows = self._climber_rows([name])
        return rows[0] if rows else None

    async def get_all_climbers(self) -> List[Dict]:
        climbers = self._climber_rows()
        climbers.sort(key=lambda c: (-c["level"], c["name"]))
        return climbers

    async def get_new_climbers(self) -> set[str]:
        return {c["name"] for c in self._climber_rows() if c["is_new"]}

    async def update_climber(
        self,
        original_name: str,
        name: Optional[str] = None,
        location: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        achievements: Optional[List[str]] = None,
    ) -> None:
        current = await self.get_climber(original_name)
        if not current:
            raise ValidationError(f"Climber not found: {original_name}")
        new_name = validate_name(name) if name else current["name"]
        skills = clean_items(skills, "Skill") if skills is not None else current["skills"]
        tags = clean_items(tags, "Tag") if tags is not None else current["tags"]
        achievements = (
            clean_items(achievements, "Achievement") if achievements is not None else current["achievements"]
        )
        location = location if location is not None else current["location"]
        with self.db.transaction():
            if new_name != current["name"]:
                if self.db.value("SELECT count(*) FROM climbers WHERE name = ?", [new_name]):
                    raise ValidationError(f"Climber already exists: {new_name}")
                self.db.run(
                    "INSERT INTO climbers (name, home_locations, created_at, updated_at) "
                    "SELECT ?, home_locations, created_at, current_timestamp FROM climbers WHERE name = ?",
                    [new_name, current["name"]],
                )
                for table in ("climber_skills", "climber_achievements", "climber_tags", "album_crew"):
                    self.db.run(f"UPDATE {table} SET climber = ? WHERE climber = ?", [new_name, current["name"]])
                self.db.run(
                    "UPDATE images SET identifier = ? WHERE kind = 'climber' AND identifier = ?",
                    [f"{new_name}/face", f"{current['name']}/face"],
                )
                self.db.run("DELETE FROM climbers WHERE name = ?", [current["name"]])
            self.db.run(
                "UPDATE climbers SET home_locations = ?, updated_at = current_timestamp WHERE name = ?",
                [json.dumps(location), new_name],
            )
            self._set_climber_items(new_name, skills, tags, achievements)
        logger.info(f"Updated climber: {original_name} -> {new_name}")

    async def delete_climber(self, name: str) -> bool:
        name = validate_name(name)
        if not self.db.value("SELECT count(*) FROM climbers WHERE name = ?", [name]):
            return False
        with self.db.transaction():
            for table in ("climber_skills", "climber_achievements", "climber_tags", "album_crew"):
                self.db.run(f"DELETE FROM {table} WHERE climber = ?", [name])
            self.db.run("DELETE FROM images WHERE kind = 'climber' AND identifier = ?", [f"{name}/face"])
            self.db.run("DELETE FROM climbers WHERE name = ?", [name])
        logger.info(f"Deleted climber: {name}")
        return True

    async def record_learned_items(
        self, name: str, album_url: str, skills: List[str], achievements: List[str]
    ) -> Dict[str, List[str]]:
        """Add items gained in one album; items the climber already has are ignored."""
        name = validate_name(name)
        album_url = validate_album_url(album_url)
        climber = await self.get_climber(name)
        if not climber:
            raise ValidationError(f"Climber not found: {name}")
        new_skills = [s for s in clean_items(skills, "Skill") if s not in climber["skills"]]
        new_achievements = [
            a for a in clean_items(achievements, "Achievement") if a not in climber["achievements"]
        ]
        with self.db.transaction():
            self.db.run_many("INSERT OR IGNORE INTO skills VALUES (?)", [[s] for s in new_skills])
            self.db.run_many("INSERT OR IGNORE INTO achievements VALUES (?)", [[a] for a in new_achievements])
            self.db.run_many(
                "INSERT INTO climber_skills (climber, skill, learned_in) VALUES (?, ?, ?)",
                [[name, s, album_url] for s in new_skills],
            )
            self.db.run_many(
                "INSERT INTO climber_achievements (climber, achievement, learned_in) VALUES (?, ?, ?)",
                [[name, a, album_url] for a in new_achievements],
            )
            self.db.run("UPDATE climbers SET updated_at = current_timestamp WHERE name = ?", [name])
        if new_skills or new_achievements:
            logger.info(f"{name} learned {new_skills} / {new_achievements} in {album_url}")
        return {"skills": new_skills, "achievements": new_achievements}

    async def get_all_skills(self) -> List[str]:
        return [r["name"] for r in self.db.rows("SELECT name FROM skills ORDER BY name")]

    async def get_all_achievements(self) -> List[str]:
        return [r["name"] for r in self.db.rows("SELECT name FROM achievements ORDER BY name")]

    async def get_all_tags(self) -> List[str]:
        return [r["name"] for r in self.db.rows("SELECT name FROM tags ORDER BY name")]

    async def add_catalog_item(self, table: str, name: str) -> None:
        self._check_catalog(table)
        self.db.run(f"INSERT OR IGNORE INTO {table} VALUES (?)", [name.strip()])

    async def delete_catalog_item(self, table: str, name: str) -> int:
        """Remove a skill or achievement everywhere. Returns how many climbers lost it."""
        self._check_catalog(table)
        link_table, column = {
            "skills": ("climber_skills", "skill"),
            "achievements": ("climber_achievements", "achievement"),
        }[table]
        with self.db.transaction():
            affected = self.db.value(f"SELECT count(*) FROM {link_table} WHERE {column} = ?", [name])
            self.db.run(f"DELETE FROM {link_table} WHERE {column} = ?", [name])
            self.db.run(f"DELETE FROM {table} WHERE name = ?", [name])
        return int(affected or 0)

    @staticmethod
    def _check_catalog(table: str) -> None:
        if table not in ("skills", "achievements"):
            raise ValueError(f"Unknown catalog: {table}")

    # ------------------------------------------------------------------ albums

    def _album_dict(self, row: dict, crew: List[str]) -> Dict:
        return {
            "url": row["url"],
            "title": row["title"],
            "description": row["description"],
            "date": row["date_text"],
            "climb_date": _iso(row["climb_date"]),
            "image_url": row["image_url"],
            "cover_image": row["cover_image"],
            "location": row["location"] or "",
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "crew": crew,
        }

    @staticmethod
    def _climb_date(date_text: str, created_at: Optional[datetime]) -> Optional[date]:
        moment = album_climb_timestamp(
            {"date": date_text, "created_at": created_at.isoformat() if created_at else ""}
        )
        return moment.date() if moment else None

    async def add_album(
        self, url: str, crew: List[str], metadata: Optional[Dict] = None, location: Optional[str] = None
    ) -> None:
        url = validate_album_url(url)
        crew = [validate_name(m) for m in crew]
        metadata = metadata or {}
        location = (location or "").strip() or None
        if self.db.value("SELECT count(*) FROM albums WHERE url = ?", [url]):
            raise ValidationError("Album already exists")
        missing = self._missing_climbers(crew)
        if missing:
            raise ValidationError(f"Crew member '{missing[0]}' does not exist")
        now = datetime.now()
        with self.db.transaction():
            if location:
                self._ensure_location(location)
            self.db.run(
                "INSERT INTO albums (url, title, description, date_text, climb_date, image_url, cover_image, location, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    url,
                    metadata.get("title", ""),
                    metadata.get("description", ""),
                    metadata.get("date", ""),
                    self._climb_date(metadata.get("date", ""), now),
                    metadata.get("imageUrl", ""),
                    metadata.get("cover_image", ""),
                    location,
                    now,
                    now,
                ],
            )
            self.db.run_many("INSERT INTO album_crew VALUES (?, ?)", [[url, m] for m in crew])
        logger.info(f"Added album: {url} with crew: {crew}")

    def _missing_climbers(self, names: List[str]) -> List[str]:
        if not names:
            return []
        existing = {
            r["name"]
            for r in self.db.rows("SELECT name FROM climbers WHERE name IN (SELECT unnest(?::TEXT[]))", [names])
        }
        return [n for n in names if n not in existing]

    async def get_album(self, url: str) -> Optional[Dict]:
        row = self.db.row("SELECT * FROM albums WHERE url = ?", [url])
        if not row:
            return None
        crew = [r["climber"] for r in self.db.rows("SELECT climber FROM album_crew WHERE album_url = ? ORDER BY climber", [url])]
        return self._album_dict(row, crew)

    async def get_all_albums(self) -> List[Dict]:
        """Newest climb first, then most recently updated."""
        rows = self.db.rows(
            "SELECT * FROM albums ORDER BY climb_date DESC NULLS LAST, updated_at DESC"
        )
        crew_by_album: Dict[str, List[str]] = {}
        for r in self.db.rows("SELECT album_url, climber FROM album_crew ORDER BY climber"):
            crew_by_album.setdefault(r["album_url"], []).append(r["climber"])
        return [self._album_dict(r, crew_by_album.get(r["url"], [])) for r in rows]

    async def update_album_crew(self, url: str, new_crew: List[str]) -> None:
        url = validate_album_url(url)
        new_crew = [validate_name(m) for m in new_crew]
        if not self.db.value("SELECT count(*) FROM albums WHERE url = ?", [url]):
            raise ValidationError(f"Album not found: {url}")
        missing = self._missing_climbers(new_crew)
        if missing:
            raise ValidationError(f"Crew member '{missing[0]}' does not exist")
        with self.db.transaction():
            self.db.run("DELETE FROM album_crew WHERE album_url = ?", [url])
            self.db.run_many("INSERT INTO album_crew VALUES (?, ?)", [[url, m] for m in new_crew])
            self.db.run("UPDATE albums SET updated_at = current_timestamp WHERE url = ?", [url])
        logger.info(f"Updated album crew: {url} -> {new_crew}")

    async def update_album_metadata(
        self, url: str, metadata: Dict, location: Optional[str] = None
    ) -> None:
        """Replace title, description, date and images. location=None keeps the current one, "" clears it."""
        url = validate_album_url(url)
        current = self.db.row("SELECT created_at, location FROM albums WHERE url = ?", [url])
        if not current:
            raise ValidationError(f"Album not found: {url}")
        date_text = metadata.get("date", "")
        with self.db.transaction():
            if location is not None:
                location = location.strip() or None
                if location:
                    self._ensure_location(location)
            else:
                location = current["location"]
            self.db.run(
                "UPDATE albums SET title = ?, description = ?, date_text = ?, climb_date = ?, image_url = ?, "
                "cover_image = ?, location = ?, updated_at = current_timestamp WHERE url = ?",
                [
                    metadata.get("title", ""),
                    metadata.get("description", ""),
                    date_text,
                    self._climb_date(date_text, current["created_at"]),
                    metadata.get("imageUrl", ""),
                    metadata.get("cover_image", ""),
                    location,
                    url,
                ],
            )

    async def delete_album(self, url: str) -> bool:
        url = validate_album_url(url)
        if not self.db.value("SELECT count(*) FROM albums WHERE url = ?", [url]):
            return False
        with self.db.transaction():
            self.db.run("DELETE FROM album_crew WHERE album_url = ?", [url])
            self.db.run("UPDATE climber_skills SET learned_in = NULL WHERE learned_in = ?", [url])
            self.db.run("UPDATE climber_achievements SET learned_in = NULL WHERE learned_in = ?", [url])
            self.db.run("DELETE FROM albums WHERE url = ?", [url])
        logger.info(f"Deleted album: {url}")
        return True

    def cache_album_metadata(self, url: str, metadata: Dict, ttl: int = 300) -> None:
        self._metadata_cache[url] = (datetime.now() + timedelta(seconds=ttl), metadata)

    def get_cached_metadata(self, url: str) -> Optional[Dict]:
        entry = self._metadata_cache.get(url)
        if not entry:
            return None
        expires, metadata = entry
        if expires < datetime.now():
            del self._metadata_cache[url]
            return None
        return metadata

    # --------------------------------------------------------------- locations

    def _ensure_location(self, name: str) -> None:
        self.db.run("INSERT OR IGNORE INTO locations (name) VALUES (?)", [validate_name(name)])

    async def ensure_location_exists(self, name: str) -> None:
        self._ensure_location(name)

    def _location_dict(self, row: dict, attributes: List[dict], owners: List[str]) -> Dict:
        return {
            "name": row["name"],
            "description": row["description"],
            "approach": row["approach"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "custom_markers": _json_list(row["custom_markers"]),
            "attributes": [{"key": a["key"], "value": a["value"]} for a in attributes],
            "owners": owners,
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
        }

    async def get_all_locations(self) -> List[Dict]:
        rows = self.db.rows("SELECT * FROM locations ORDER BY name")
        attributes: Dict[str, List[dict]] = {}
        for a in self.db.rows("SELECT location, key, value FROM location_attributes ORDER BY key"):
            attributes.setdefault(a["location"], []).append(a)
        owners: Dict[str, List[str]] = {}
        for o in self.db.rows(
            "SELECT resource_id, user_id FROM ownership WHERE resource_type = 'location' ORDER BY user_id"
        ):
            owners.setdefault(o["resource_id"], []).append(o["user_id"])
        return [self._location_dict(r, attributes.get(r["name"], []), owners.get(r["name"], [])) for r in rows]

    async def get_location(self, name: str) -> Optional[Dict]:
        return next((loc for loc in await self.get_all_locations() if loc["name"] == name), None)

    async def add_location(
        self,
        name: str,
        description: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        approach: Optional[str] = None,
        custom_markers: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Create a location, or fill the given fields of an existing one (idempotent create)."""
        name = validate_name(name)
        with self.db.transaction():
            self._ensure_location(name)
            self._update_location_fields(name, description, latitude, longitude, approach, custom_markers)

    def _update_location_fields(
        self,
        name: str,
        description: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        approach: Optional[str],
        custom_markers: Optional[List[Dict[str, Any]]],
    ) -> None:
        if custom_markers is not None:
            primary = next((m for m in custom_markers if isinstance(m, dict) and m.get("primary")), None)
            if primary and latitude is None and longitude is None:
                try:
                    latitude, longitude = float(primary["lat"]), float(primary["lng"])
                except (KeyError, TypeError, ValueError):
                    pass
        assignments = {
            "description": description,
            "approach": approach,
            "latitude": latitude,
            "longitude": longitude,
            "custom_markers": json.dumps(custom_markers) if custom_markers is not None else None,
        }
        changes = {k: v for k, v in assignments.items() if v is not None}
        if not changes:
            return
        set_clause = ", ".join(f"{k} = ?" for k in changes)
        self.db.run(
            f"UPDATE locations SET {set_clause}, updated_at = current_timestamp WHERE name = ?",
            [*changes.values(), name],
        )

    async def update_location(
        self,
        name: str,
        description: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        approach: Optional[str] = None,
        custom_markers: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        name = validate_name(name)
        if not self.db.value("SELECT count(*) FROM locations WHERE name = ?", [name]):
            return False
        with self.db.transaction():
            self._update_location_fields(name, description, latitude, longitude, approach, custom_markers)
        return True

    async def set_location_attributes(
        self, name: str, attributes: List[str] | List[Dict[str, str]]
    ) -> bool:
        """Replace a location's attributes. Accepts ["key", ...] or [{"key", "value"}, ...]."""
        name = validate_name(name)
        if not self.db.value("SELECT count(*) FROM locations WHERE name = ?", [name]):
            return False
        desired: Dict[str, str] = {}
        for item in attributes or []:
            if isinstance(item, str):
                key, value = item, ""
            elif isinstance(item, dict):
                key, value = str(item.get("key") or ""), str(item.get("value") or "")
            else:
                raise ValidationError("Attributes must be a list of strings or {key,value} objects")
            key = key.strip()
            if key:
                desired[key] = value
        with self.db.transaction():
            self.db.run_many("INSERT OR IGNORE INTO attribute_keys VALUES (?)", [[k] for k in desired])
            self.db.run("DELETE FROM location_attributes WHERE location = ?", [name])
            self.db.run_many(
                "INSERT INTO location_attributes VALUES (?, ?, ?)", [[name, k, v] for k, v in desired.items()]
            )
            self.db.run("UPDATE locations SET updated_at = current_timestamp WHERE name = ?", [name])
        return True

    async def get_all_location_attributes(self) -> List[str]:
        return [r["name"] for r in self.db.rows("SELECT name FROM attribute_keys ORDER BY name")]

    async def add_location_attribute_key(self, key: str) -> None:
        key = key.strip()
        if not key:
            raise ValidationError("Attribute name cannot be empty")
        self.db.run("INSERT OR IGNORE INTO attribute_keys VALUES (?)", [key])

    async def delete_location_attribute_global(self, key: str) -> bool:
        key = (key or "").strip()
        if not key:
            return False
        with self.db.transaction():
            self.db.run("DELETE FROM location_attributes WHERE key = ?", [key])
            self.db.run("DELETE FROM attribute_keys WHERE name = ?", [key])
        return True

    async def rename_location(self, old_name: str, new_name: str) -> bool:
        """Rename everywhere: albums, attributes, ownership and climbers' home locations."""
        old_name, new_name = validate_name(old_name), validate_name(new_name)
        if old_name == new_name:
            return bool(self.db.value("SELECT count(*) FROM locations WHERE name = ?", [old_name]))
        if not self.db.value("SELECT count(*) FROM locations WHERE name = ?", [old_name]):
            return False
        if self.db.value("SELECT count(*) FROM locations WHERE name = ?", [new_name]):
            raise ValidationError(f"Location already exists: {new_name}")
        with self.db.transaction():
            self.db.run(
                "INSERT INTO locations SELECT ?, description, approach, latitude, longitude, custom_markers, created_at, current_timestamp "
                "FROM locations WHERE name = ?",
                [new_name, old_name],
            )
            self.db.run("UPDATE location_attributes SET location = ? WHERE location = ?", [new_name, old_name])
            self.db.run("UPDATE albums SET location = ? WHERE location = ?", [new_name, old_name])
            self.db.run(
                "UPDATE ownership SET resource_id = ? WHERE resource_type = 'location' AND resource_id = ?",
                [new_name, old_name],
            )
            for climber in self.db.rows("SELECT name, home_locations FROM climbers"):
                homes = _json_list(climber["home_locations"])
                if old_name in homes:
                    homes = [new_name if h == old_name else h for h in homes]
                    self.db.run("UPDATE climbers SET home_locations = ? WHERE name = ?", [json.dumps(homes), climber["name"]])
            self.db.run("DELETE FROM locations WHERE name = ?", [old_name])
        logger.info(f"Renamed location: {old_name} -> {new_name}")
        return True

    async def delete_location(
        self, name: str, force_clear: bool = False, reassign_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete a location. Albums tagged with it block the delete unless reassigned or cleared."""
        name = validate_name(name)
        if not self.db.value("SELECT count(*) FROM locations WHERE name = ?", [name]):
            return {"deleted": False, "affected_albums": 0}
        affected = int(self.db.value("SELECT count(*) FROM albums WHERE location = ?", [name]) or 0)
        if affected and not force_clear and not reassign_to:
            return {"deleted": False, "affected_albums": affected, "blocked_by_albums": affected}
        target = validate_name(reassign_to) if reassign_to else None
        with self.db.transaction():
            if target:
                self._ensure_location(target)
            self.db.run("UPDATE albums SET location = ? WHERE location = ?", [target, name])
            self.db.run("DELETE FROM location_attributes WHERE location = ?", [name])
            self.db.run("DELETE FROM ownership WHERE resource_type = 'location' AND resource_id = ?", [name])
            self.db.run("DELETE FROM locations WHERE name = ?", [name])
        return {"deleted": True, "affected_albums": affected, "reassigned_to": target}

    # ------------------------------------------------------------------ images

    async def store_image(
        self, kind: str, identifier: str, data: bytes, ttl_seconds: Optional[int] = None
    ) -> str:
        expires = datetime.now() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        self.db.run(
            "INSERT OR REPLACE INTO images (kind, identifier, data, created_at, expires_at) VALUES (?, ?, ?, current_timestamp, ?)",
            [kind, identifier, data, expires],
        )
        return f"{IMAGE_URL_PREFIX}/{kind}/{identifier}"

    async def get_image(self, kind: str, identifier: str) -> Optional[bytes]:
        row = self.db.row(
            "SELECT data FROM images WHERE kind = ? AND identifier = ? AND (expires_at IS NULL OR expires_at > current_timestamp)",
            [kind, identifier],
        )
        return bytes(row["data"]) if row else None

    async def delete_image(self, kind: str, identifier: str) -> bool:
        existed = self.db.value("SELECT count(*) FROM images WHERE kind = ? AND identifier = ?", [kind, identifier])
        self.db.run("DELETE FROM images WHERE kind = ? AND identifier = ?", [kind, identifier])
        return bool(existed)

    async def list_images(self, kind: str) -> List[Dict]:
        return [
            {
                "identifier": r["identifier"],
                "image_url": f"{IMAGE_URL_PREFIX}/{kind}/{r['identifier']}",
                "size_bytes": r["size_bytes"],
                "created_at": _iso(r["created_at"]),
                "expires_at": _iso(r["expires_at"]),
            }
            for r in self.db.rows(
                "SELECT identifier, octet_length(data) AS size_bytes, created_at, expires_at FROM images "
                "WHERE kind = ? AND (expires_at IS NULL OR expires_at > current_timestamp) ORDER BY created_at DESC",
                [kind],
            )
        ]

    def purge_expired_images(self) -> int:
        count = self.db.value("SELECT count(*) FROM images WHERE expires_at IS NOT NULL AND expires_at <= current_timestamp")
        self.db.run("DELETE FROM images WHERE expires_at IS NOT NULL AND expires_at <= current_timestamp")
        return int(count or 0)

    # ------------------------------------------------------------------- memes

    def _meme_dict(self, row: dict) -> Dict:
        return {
            "id": row["id"],
            "image_path": f"{IMAGE_URL_PREFIX}/meme/{row['id']}",
            "creator_id": row["creator_id"],
            "created_at": _iso(row["created_at"]),
        }

    async def add_meme(self, meme_id: str, image_data: bytes, creator_id: str) -> Dict:
        with self.db.transaction():
            self.db.run("INSERT INTO memes (id, creator_id) VALUES (?, ?)", [meme_id, creator_id])
            await self.store_image("meme", meme_id, image_data)
        return await self.get_meme(meme_id)

    async def get_meme(self, meme_id: str) -> Optional[Dict]:
        row = self.db.row("SELECT * FROM memes WHERE id = ?", [meme_id])
        return self._meme_dict(row) if row else None

    async def get_all_memes(self) -> List[Dict]:
        return [self._meme_dict(r) for r in self.db.rows("SELECT * FROM memes ORDER BY created_at DESC")]

    async def get_memes_by_creator(self, creator_id: str) -> List[Dict]:
        return [
            self._meme_dict(r)
            for r in self.db.rows("SELECT * FROM memes WHERE creator_id = ? ORDER BY created_at DESC", [creator_id])
        ]

    async def delete_meme(self, meme_id: str) -> bool:
        if not self.db.value("SELECT count(*) FROM memes WHERE id = ?", [meme_id]):
            return False
        with self.db.transaction():
            self.db.run("DELETE FROM images WHERE kind = 'meme' AND identifier = ?", [meme_id])
            self.db.run("DELETE FROM memes WHERE id = ?", [meme_id])
        return True

    # ------------------------------------------------------------------- users

    def _user_dict(self, row: dict) -> Dict:
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "picture": row["picture"],
            "role": row["role"],
            "created_at": _iso(row["created_at"]),
            "last_login": _iso(row["last_login"]),
            "albums_created": row.get("albums_created", 0),
            "crew_members_created": row.get("crew_members_created", 0),
            "memes_created": row.get("memes_created", 0),
        }

    USER_QUERY = """
        SELECT u.*,
               (SELECT count(*) FROM ownership o WHERE o.user_id = u.id AND o.resource_type = 'album') AS albums_created,
               (SELECT count(*) FROM ownership o WHERE o.user_id = u.id AND o.resource_type = 'crew_member') AS crew_members_created,
               (SELECT count(*) FROM ownership o WHERE o.user_id = u.id AND o.resource_type = 'meme') AS memes_created
        FROM users u
    """

    async def get_user(self, user_id: str) -> Optional[Dict]:
        row = self.db.row(self.USER_QUERY + " WHERE u.id = ?", [user_id])
        return self._user_dict(row) if row else None

    async def get_user_by_email(self, email: str) -> Optional[Dict]:
        row = self.db.row(self.USER_QUERY + " WHERE lower(u.email) = lower(?)", [email])
        return self._user_dict(row) if row else None

    async def get_all_users(self) -> List[Dict]:
        return [self._user_dict(r) for r in self.db.rows(self.USER_QUERY + " ORDER BY u.created_at DESC")]

    async def get_users_by_role(self, role: str) -> List[Dict]:
        return [
            self._user_dict(r)
            for r in self.db.rows(self.USER_QUERY + " WHERE u.role = ? ORDER BY u.created_at DESC", [role])
        ]

    async def upsert_user(self, user_id: str, email: str, name: str, picture: str) -> Dict:
        """Create a pending user on first login; refresh name, picture and last_login afterwards."""
        with self.db.transaction():
            if self.db.value("SELECT count(*) FROM users WHERE id = ?", [user_id]):
                self.db.run(
                    "UPDATE users SET name = coalesce(?, name), picture = coalesce(?, picture), last_login = current_timestamp WHERE id = ?",
                    [name, picture, user_id],
                )
            else:
                self.db.run(
                    "INSERT INTO users (id, email, name, picture, role) VALUES (?, ?, ?, ?, 'pending')",
                    [user_id, email, name, picture],
                )
        return await self.get_user(user_id)

    async def set_user_role(self, user_id: str, role: str) -> bool:
        if not self.db.value("SELECT count(*) FROM users WHERE id = ?", [user_id]):
            return False
        self.db.run("UPDATE users SET role = ? WHERE id = ?", [role, user_id])
        return True

    # preferences

    async def set_user_preference(self, user_id: str, key: str, value: Any) -> None:
        if not user_id or not key:
            raise ValidationError("User ID and preference key are required")
        self.db.run(
            "INSERT OR REPLACE INTO user_preferences VALUES (?, ?, ?)", [user_id, key, json.dumps(value)]
        )

    async def get_user_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        row = self.db.row("SELECT value FROM user_preferences WHERE user_id = ? AND key = ?", [user_id, key])
        return json.loads(row["value"]) if row else default

    async def get_all_user_preferences(self, user_id: str) -> Dict[str, Any]:
        return {
            r["key"]: json.loads(r["value"])
            for r in self.db.rows("SELECT key, value FROM user_preferences WHERE user_id = ?", [user_id])
        }

    async def delete_user_preference(self, user_id: str, key: str) -> bool:
        existed = self.db.value("SELECT count(*) FROM user_preferences WHERE user_id = ? AND key = ?", [user_id, key])
        self.db.run("DELETE FROM user_preferences WHERE user_id = ? AND key = ?", [user_id, key])
        return bool(existed)

    # --------------------------------------------------------------- ownership

    async def add_owner(self, resource_type: str, resource_id: str, user_id: str) -> None:
        self.db.run("INSERT OR IGNORE INTO ownership VALUES (?, ?, ?)", [resource_type, resource_id, user_id])

    async def remove_owner(self, resource_type: str, resource_id: str, user_id: str) -> None:
        self.db.run(
            "DELETE FROM ownership WHERE resource_type = ? AND resource_id = ? AND user_id = ?",
            [resource_type, resource_id, user_id],
        )

    async def get_owners(self, resource_type: str, resource_id: str) -> List[str]:
        return [
            r["user_id"]
            for r in self.db.rows(
                "SELECT user_id FROM ownership WHERE resource_type = ? AND resource_id = ? ORDER BY user_id",
                [resource_type, resource_id],
            )
        ]

    async def is_owner(self, resource_type: str, resource_id: str, user_id: str) -> bool:
        return bool(
            self.db.value(
                "SELECT count(*) FROM ownership WHERE resource_type = ? AND resource_id = ? AND user_id = ?",
                [resource_type, resource_id, user_id],
            )
        )

    async def get_user_resources(self, user_id: str, resource_type: str) -> set[str]:
        return {
            r["resource_id"]
            for r in self.db.rows(
                "SELECT resource_id FROM ownership WHERE user_id = ? AND resource_type = ?", [user_id, resource_type]
            )
        }

    async def count_owned(self, user_id: str, resource_type: str) -> int:
        return int(
            self.db.value(
                "SELECT count(*) FROM ownership WHERE user_id = ? AND resource_type = ?", [user_id, resource_type]
            )
            or 0
        )

    async def release_resource(self, resource_type: str, resource_id: str) -> None:
        self.db.run("DELETE FROM ownership WHERE resource_type = ? AND resource_id = ?", [resource_type, resource_id])

    async def rename_resource(self, resource_type: str, old_id: str, new_id: str) -> None:
        if old_id != new_id:
            self.db.run(
                "UPDATE ownership SET resource_id = ? WHERE resource_type = ? AND resource_id = ?",
                [new_id, resource_type, old_id],
            )

    async def get_unowned_resources(self, resource_type: str) -> List[str]:
        source = {"album": ("albums", "url"), "crew_member": ("climbers", "name"), "location": ("locations", "name"), "meme": ("memes", "id")}
        table, column = source[resource_type]
        return [
            r["id"]
            for r in self.db.rows(
                f"SELECT t.{column} AS id FROM {table} t WHERE NOT EXISTS "
                f"(SELECT 1 FROM ownership o WHERE o.resource_type = ? AND o.resource_id = t.{column}) ORDER BY 1",
                [resource_type],
            )
        ]

    async def count_rows(self, table: str) -> int:
        if table not in ("albums", "climbers", "locations", "memes", "users", "push_devices", "images"):
            raise ValueError(f"Unknown table: {table}")
        return int(self.db.value(f"SELECT count(*) FROM {table}") or 0)

    # -------------------------------------------------------------- api tokens
    # Sync on purpose: the only caller is the JWT dependency, which FastAPI runs synchronously.

    def create_token(
        self, token_id: str, user_id: str, name: str, permissions: Dict[str, bool], expires_at: datetime
    ) -> None:
        self.db.run(
            "INSERT INTO api_tokens (token_id, user_id, name, permissions, expires_at) VALUES (?, ?, ?, ?, ?)",
            [token_id, user_id, name, json.dumps(permissions), expires_at],
        )

    def touch_token(self, token_id: str) -> None:
        self.db.run("UPDATE api_tokens SET last_used = current_timestamp WHERE token_id = ?", [token_id])

    def is_token_revoked(self, token_id: str) -> bool:
        row = self.db.row("SELECT revoked FROM api_tokens WHERE token_id = ?", [token_id])
        return bool(row and row["revoked"])

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        if not self.db.value("SELECT count(*) FROM api_tokens WHERE token_id = ? AND user_id = ?", [token_id, user_id]):
            return False
        self.db.run("UPDATE api_tokens SET revoked = true WHERE token_id = ?", [token_id])
        return True

    def revoke_user_tokens(self, user_id: str) -> int:
        count = self.db.value("SELECT count(*) FROM api_tokens WHERE user_id = ? AND NOT revoked", [user_id])
        self.db.run("UPDATE api_tokens SET revoked = true WHERE user_id = ?", [user_id])
        return int(count or 0)

    def list_tokens(self, user_id: str) -> List[Dict]:
        return [
            {
                "id": r["token_id"],
                "name": r["name"],
                "created_at": _iso(r["created_at"]),
                "expires_at": _iso(r["expires_at"]),
                "last_used": _iso(r["last_used"]),
                "permissions": _json_dict(r["permissions"]),
            }
            for r in self.db.rows(
                "SELECT * FROM api_tokens WHERE user_id = ? AND NOT revoked AND expires_at > current_timestamp ORDER BY created_at DESC",
                [user_id],
            )
        ]

    # ------------------------------------------------------------ push devices

    def _device_dict(self, row: dict) -> Dict:
        return {
            "device_id": row["device_id"],
            "subscription_id": row["subscription_id"],
            "user_id": row["user_id"],
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
            "browser_name": row["browser_name"],
            "platform": row["platform"],
            "user_agent": row["user_agent"],
            "notification_preferences": _json_dict(row["preferences"]),
            "created_at": _iso(row["created_at"]),
            "last_used": _iso(row["last_used"]),
        }

    async def store_push_subscription(
        self,
        device_id: str,
        user_id: Optional[str],
        subscription_data: Dict[str, Any],
        device_info: Dict[str, Any],
    ) -> str:
        """One subscription per device. Re-subscribing keeps the device's preferences."""
        if not device_id or not isinstance(subscription_data, dict):
            raise ValidationError("Device ID and subscription data are required")
        endpoint = subscription_data.get("endpoint")
        keys = subscription_data.get("keys") or {}
        if not endpoint:
            raise ValidationError("Subscription must have an endpoint")
        if not keys.get("p256dh") or not keys.get("auth"):
            raise ValidationError("Subscription must have p256dh and auth keys")
        subscription_id = hashlib.md5(
            f"{device_id}:{endpoint}:{keys['p256dh']}:{keys['auth']}".encode()
        ).hexdigest()
        existing = self.db.row("SELECT preferences FROM push_devices WHERE device_id = ?", [device_id])
        preferences = _json_dict(existing["preferences"]) if existing else dict(DEFAULT_NOTIFICATION_PREFERENCES)
        self.db.run(
            "INSERT OR REPLACE INTO push_devices (device_id, subscription_id, user_id, endpoint, p256dh, auth, browser_name, platform, user_agent, preferences, created_at, last_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp, NULL)",
            [
                device_id,
                subscription_id,
                user_id or None,
                endpoint,
                keys["p256dh"],
                keys["auth"],
                device_info.get("browserName") or "unknown",
                device_info.get("platform") or "unknown",
                (device_info.get("userAgent") or "")[:200],
                json.dumps(preferences),
            ],
        )
        return subscription_id

    async def get_device_push_subscription(self, device_id: str) -> Optional[Dict]:
        row = self.db.row("SELECT * FROM push_devices WHERE device_id = ?", [device_id])
        return self._device_dict(row) if row else None

    async def get_push_subscription(self, subscription_id: str) -> Optional[Dict]:
        row = self.db.row("SELECT * FROM push_devices WHERE subscription_id = ?", [subscription_id])
        return self._device_dict(row) if row else None

    async def get_user_device_subscriptions(self, user_id: str) -> List[Dict]:
        return [
            self._device_dict(r)
            for r in self.db.rows("SELECT * FROM push_devices WHERE user_id = ? ORDER BY created_at", [user_id])
        ]

    async def get_all_device_push_subscriptions(self) -> List[Dict]:
        return [self._device_dict(r) for r in self.db.rows("SELECT * FROM push_devices ORDER BY created_at")]

    async def delete_device_push_subscription(self, device_id: str) -> bool:
        existed = self.db.value("SELECT count(*) FROM push_devices WHERE device_id = ?", [device_id])
        self.db.run("DELETE FROM push_devices WHERE device_id = ?", [device_id])
        return bool(existed)

    async def delete_push_subscription(self, subscription_id: str) -> bool:
        existed = self.db.value("SELECT count(*) FROM push_devices WHERE subscription_id = ?", [subscription_id])
        self.db.run("DELETE FROM push_devices WHERE subscription_id = ?", [subscription_id])
        return bool(existed)

    async def update_device_notification_preferences(self, device_id: str, preferences: Dict[str, bool]) -> bool:
        if not self.db.value("SELECT count(*) FROM push_devices WHERE device_id = ?", [device_id]):
            return False
        self.db.run("UPDATE push_devices SET preferences = ? WHERE device_id = ?", [json.dumps(preferences), device_id])
        return True

    async def get_device_notification_preferences(self, device_id: str) -> Optional[Dict[str, bool]]:
        row = self.db.row("SELECT preferences FROM push_devices WHERE device_id = ?", [device_id])
        return _json_dict(row["preferences"]) if row else None

    async def update_subscription_last_used(self, subscription_id: str) -> None:
        self.db.run("UPDATE push_devices SET last_used = current_timestamp WHERE subscription_id = ?", [subscription_id])

    async def record_notification_counters(self, sent: int = 0, failed: int = 0, cleaned: int = 0) -> None:
        if not (sent or failed or cleaned):
            return
        self.db.run(
            "INSERT INTO notification_counters (day, sent, failed, cleaned) VALUES (current_date, ?, ?, ?) "
            "ON CONFLICT (day) DO UPDATE SET sent = sent + excluded.sent, failed = failed + excluded.failed, cleaned = cleaned + excluded.cleaned",
            [sent, failed, cleaned],
        )

    async def get_notification_counters(self, days: int) -> List[Dict]:
        """One entry per day for the last `days` days, oldest first, zeros where nothing happened."""
        start = date.today() - timedelta(days=days - 1)
        rows = {
            r["day"]: r
            for r in self.db.rows("SELECT * FROM notification_counters WHERE day >= ? ORDER BY day", [start])
        }
        return [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "sent": rows.get(start + timedelta(days=i), {}).get("sent", 0),
                "failed": rows.get(start + timedelta(days=i), {}).get("failed", 0),
                "cleaned": rows.get(start + timedelta(days=i), {}).get("cleaned", 0),
            }
            for i in range(days)
        ]

    # -------------------------------------------------------- health & backups

    async def health_check(self) -> Dict[str, Any]:
        counts = {
            table: int(self.db.value(f"SELECT count(*) FROM {table}") or 0)
            for table in ("climbers", "albums", "locations", "memes", "users", "push_devices", "images")
        }
        return {"status": "healthy", "database": str(self.db.path), "counts": counts}

    def backup(self, directory: str | Path, keep: int = 14) -> Path:
        """Consistent snapshot into directory/climbing-<timestamp>.duckdb, keeping the newest `keep` files."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"climbing-{datetime.now():%Y%m%d-%H%M%S}.duckdb"
        with self.db.lock:
            # Fold the write-ahead log into the main file first, so the file on disk is complete too
            self.db.conn.execute("CHECKPOINT")
            self.db.conn.execute(f"ATTACH '{target}' AS backup_target")
            try:
                self.db.conn.execute("COPY FROM DATABASE memory TO backup_target" if str(self.db.path) == ":memory:" else f"COPY FROM DATABASE \"{self.db.path.stem}\" TO backup_target")
            finally:
                self.db.conn.execute("DETACH backup_target")
        backups = sorted(directory.glob("climbing-*.duckdb"))
        for old in backups[:-keep]:
            old.unlink()
        logger.info(f"Database backed up to {target}")
        return target

    def close(self) -> None:
        with self.db.lock:
            self.db.conn.close()


def copy_file_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
