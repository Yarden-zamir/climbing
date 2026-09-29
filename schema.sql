-- Climbing app schema (DuckDB). Applied on every start; every statement is idempotent.
-- Counts and flags that used to be stored (climbs, is_new, level, *_created) are derived in queries.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT,
    picture TEXT,
    role TEXT NOT NULL DEFAULT 'pending' CHECK (role IN ('admin', 'user', 'pending')),
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    last_login TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSON NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS climbers (
    name TEXT PRIMARY KEY,
    home_locations JSON NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS skills (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS achievements (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS tags (name TEXT PRIMARY KEY);

-- learned_in: album url where the item was gained, when known
CREATE TABLE IF NOT EXISTS climber_skills (
    climber TEXT NOT NULL,
    skill TEXT NOT NULL,
    learned_in TEXT,
    added_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (climber, skill)
);

CREATE TABLE IF NOT EXISTS climber_achievements (
    climber TEXT NOT NULL,
    achievement TEXT NOT NULL,
    learned_in TEXT,
    added_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (climber, achievement)
);

CREATE TABLE IF NOT EXISTS climber_tags (
    climber TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (climber, tag)
);

CREATE TABLE IF NOT EXISTS locations (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    approach TEXT NOT NULL DEFAULT '',
    latitude DOUBLE,
    longitude DOUBLE,
    custom_markers JSON NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS attribute_keys (name TEXT PRIMARY KEY);

CREATE TABLE IF NOT EXISTS location_attributes (
    location TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (location, key)
);

-- climb_date: the day of the climb resolved from date_text and created_at (see redis_store.parse_album_date lineage in dates.py)
CREATE TABLE IF NOT EXISTS albums (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    date_text TEXT NOT NULL DEFAULT '',
    climb_date DATE,
    image_url TEXT NOT NULL DEFAULT '',
    cover_image TEXT NOT NULL DEFAULT '',
    location TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS album_crew (
    album_url TEXT NOT NULL,
    climber TEXT NOT NULL,
    PRIMARY KEY (album_url, climber)
);

CREATE TABLE IF NOT EXISTS memes (
    id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- kind: climber | profile | meme | temp | notification. expires_at set for temp and notification images.
CREATE TABLE IF NOT EXISTS images (
    kind TEXT NOT NULL,
    identifier TEXT NOT NULL,
    data BLOB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    expires_at TIMESTAMP,
    PRIMARY KEY (kind, identifier)
);
ALTER TABLE images ADD COLUMN IF NOT EXISTS content_type TEXT;

-- resource_type: album | crew_member | meme | location; several owners per resource are allowed
CREATE TABLE IF NOT EXISTS ownership (
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (resource_type, resource_id, user_id)
);

CREATE TABLE IF NOT EXISTS push_devices (
    device_id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    user_id TEXT,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    browser_name TEXT NOT NULL DEFAULT 'unknown',
    platform TEXT NOT NULL DEFAULT 'unknown',
    user_agent TEXT NOT NULL DEFAULT '',
    preferences JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    last_used TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_counters (
    day DATE PRIMARY KEY,
    sent INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    cleaned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    permissions JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    expires_at TIMESTAMP NOT NULL,
    last_used TIMESTAMP,
    revoked BOOLEAN NOT NULL DEFAULT false
);
