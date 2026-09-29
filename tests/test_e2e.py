"""End-to-end contract tests over HTTP against a real DuckDB-backed app."""

import asyncio
import io
import json
from datetime import date

import duckdb
from PIL import Image

from tests.conftest import session_cookie

ALBUM_1 = "https://photos.app.goo.gl/Test000000000001"
ALBUM_2 = "https://photos.app.goo.gl/Test000000000002"
ALBUM_3 = "https://photos.app.goo.gl/Test000000000003"


def login(client, user):
    client.cookies.clear()  # the refresh middleware may have re-issued a cookie for the previous user
    client.cookies.set("session", session_cookie(user))


def logout(client):
    client.cookies.clear()


def png_bytes(size=(4, 4)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 50, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def crew_form(name, skills=(), location=(), achievements=()):
    return {
        "name": name,
        "skills": json.dumps(list(skills)),
        "location": json.dumps(list(location)),
        "achievements": json.dumps(list(achievements)),
    }


# --------------------------------------------------------------------------- basics


def test_health_and_case_insensitive_paths(client):
    logout(client)
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "healthy"
    assert "revision" in body and "counts" in body
    assert client.get("/API/Health").status_code == 200
    assert client.get("/Albums").status_code == 200


def test_writes_require_login(client):
    logout(client)
    assert client.post("/api/crew/submit", data=crew_form("Nobody")).status_code == 401
    assert client.post("/api/albums/submit", json={"url": ALBUM_1, "crew": []}).status_code == 401
    assert client.delete("/api/crew/delete", params={"crew_name": "Nobody"}).status_code == 401
    assert client.post("/api/skills", json={"name": "x"}).status_code == 401
    detail = client.post("/api/albums/submit", json={"url": ALBUM_1, "crew": []}).json()["detail"]
    assert detail == "Please sign in to continue"


def test_image_proxy_only_google(client):
    assert client.get("/get-image", params={"url": "https://example.com/x.png"}).status_code == 400
    assert client.get("/redis-image/climber/Nobody/face").status_code == 404


# ----------------------------------------------------------------------------- crew


def test_pending_user_cannot_create_crew(client, pending):
    login(client, pending)
    response = client.post("/api/crew/submit", data=crew_form("Blocked Person"))
    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_admin_creates_crew_with_image_and_reads_it_back(client, admin):
    login(client, admin)
    response = client.post(
        "/api/crew/submit",
        data=crew_form("Alice Climber", ["climber", "belayer"], ["Haifa"], ["first lead"]),
        files={"image": ("face.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    crew = {c["name"]: c for c in client.get("/api/crew").json()}
    alice = crew["Alice Climber"]
    assert sorted(alice["skills"]) == ["belayer", "climber"]
    assert alice["achievements"] == ["first lead"]
    assert alice["location"] == ["Haifa"]
    assert alice["climbs"] == 0 and alice["is_new"] is False and alice["first_climb_date"] is None
    assert alice["level"] == 1 + 2 + 1  # base + skills + achievements
    assert client.get("/redis-image/climber/Alice%20Climber/face").status_code == 200
    assert client.post("/api/crew/submit", data=crew_form("Alice Climber")).status_code == 409


def test_member_creation_limit_is_derived_from_ownership(client, member):
    login(client, member)
    assert client.post("/api/crew/submit", data=crew_form("Member Friend")).status_code == 200
    second = client.post("/api/crew/submit", data=crew_form("Member Friend Two"))
    assert second.status_code == 403
    assert "limit" in second.json()["detail"].lower()
    assert client.delete("/api/crew/delete", params={"crew_name": "Member Friend"}).status_code == 200
    assert client.post("/api/crew/submit", data=crew_form("Member Friend Two")).status_code == 200


def test_member_cannot_touch_others_crew(client, member):
    login(client, member)
    edit = client.post(
        "/api/crew/edit", data={"original_name": "Alice Climber", "name": "Alice Climber", **crew_form("x")}
    )
    assert edit.status_code == 403
    assert client.delete("/api/crew/delete", params={"crew_name": "Alice Climber"}).status_code == 403
    assert client.post("/api/crew/add-skills", json={"crew_name": "Alice Climber", "skills": ["rope coiler"]}).status_code == 403


def test_rename_crew_keeps_skills_and_album_membership(client, admin):
    login(client, admin)
    assert client.post("/api/crew/submit", data=crew_form("Bob Temp", ["climber"])).status_code == 200
    assert client.post("/api/albums/submit", json={"url": ALBUM_3, "crew": ["Bob Temp"]}).status_code == 200
    response = client.post(
        "/api/crew/edit",
        data={"original_name": "Bob Temp", "name": "Bob Final", "skills": json.dumps(["climber", "belayer"]), "location": "[]", "achievements": "[]"},
    )
    assert response.status_code == 200, response.text
    crew = {c["name"]: c for c in client.get("/api/crew").json()}
    assert "Bob Temp" not in crew
    assert sorted(crew["Bob Final"]["skills"]) == ["belayer", "climber"]
    assert crew["Bob Final"]["climbs"] == 1
    album = next(a for a in client.get("/api/albums/enriched").json() if a["url"] == ALBUM_3)
    assert [c["name"] for c in album["metadata"]["crew"]] == ["Bob Final"]
    assert client.delete("/api/albums/delete", params={"album_url": ALBUM_3}).status_code == 200


# --------------------------------------------------------------------------- albums


def test_album_submit_with_new_person_and_learned_items(client, admin):
    login(client, admin)
    validation = client.get("/api/albums/validate-url", params={"url": ALBUM_1}).json()
    assert validation == {"valid": True, "exists": False, "title": "Test Album", "description": "Great day out", "imageUrl": "https://lh3.googleusercontent.com/pw/abc=s0"}

    response = client.post(
        "/api/albums/submit",
        json={
            "url": ALBUM_1,
            "crew": ["Alice Climber", "Newbie Person"],
            "location": "Gita",
            "new_people": [{"name": "Newbie Person", "skills": ["climber"]}],
            "learned": [{"name": "Alice Climber", "skills": ["rope coiler"], "achievements": ["first outdoor"]}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_climbers"] == ["Newbie Person"]
    assert body["learned"] == {"Alice Climber": {"skills": ["rope coiler"], "achievements": ["first outdoor"]}}

    albums = client.get("/api/albums/enriched").json()
    album = next(a for a in albums if a["url"] == ALBUM_1)
    assert album["metadata"]["title"] == "Test Album"
    assert album["metadata"]["date_iso"] == "2025-09-27"
    assert album["metadata"]["location"] == "Gita"
    assert sorted(c["name"] for c in album["metadata"]["crew"]) == ["Alice Climber", "Newbie Person"]

    crew = {c["name"]: c for c in client.get("/api/crew").json()}
    assert crew["Alice Climber"]["skill_sources"] == {"rope coiler": ALBUM_1}
    assert crew["Alice Climber"]["achievement_sources"] == {"first outdoor": ALBUM_1}
    assert crew["Alice Climber"]["climbs"] == 1
    assert crew["Alice Climber"]["locations_visited"] == ["Gita"]
    assert crew["Alice Climber"]["first_climb_date"] == "Sep 27, 2025"
    assert crew["Newbie Person"]["skills"] == ["climber"]
    assert "Gita" in [loc["name"] for loc in client.get("/api/locations").json()]
    assert client.post("/api/albums/submit", json={"url": ALBUM_1, "crew": ["Alice Climber"]}).status_code == 409


def test_album_edit_crew_rejects_learning_for_non_crew(client, admin):
    login(client, admin)
    response = client.post(
        "/api/albums/edit-crew",
        json={"album_url": ALBUM_1, "crew": ["Alice Climber"], "learned": [{"name": "Newbie Person", "skills": ["belayer"]}]},
    )
    assert response.status_code == 400
    assert "not in this album's crew" in response.json()["detail"]
    ok = client.post("/api/albums/edit-crew", json={"album_url": ALBUM_1, "crew": ["Alice Climber", "Newbie Person"]})
    assert ok.status_code == 200


def test_new_climber_badge_follows_climb_date(client, admin):
    login(client, admin)
    today = date.today().strftime("%b %d, %Y")
    response = client.post("/api/albums/edit-metadata", json={"album_url": ALBUM_1, "date": today})
    assert response.status_code == 200, response.text
    crew = {c["name"]: c for c in client.get("/api/crew").json()}
    assert crew["Newbie Person"]["is_new"] is True
    assert crew["Newbie Person"]["first_climb_date"] == today
    album = next(a for a in client.get("/api/albums/enriched").json() if a["url"] == ALBUM_1)
    assert album["metadata"]["date_iso"] == date.today().isoformat()


def test_album_permissions_and_delete(client, admin, member):
    login(client, member)
    assert client.delete("/api/albums/delete", params={"album_url": ALBUM_1}).status_code == 403
    assert client.post("/api/albums/submit", json={"url": ALBUM_2, "crew": ["Alice Climber"]}).status_code == 200
    assert client.delete("/api/albums/delete", params={"album_url": ALBUM_2}).status_code == 200
    login(client, admin)
    assert client.delete("/api/albums/delete", params={"album_url": "https://photos.app.goo.gl/Missing0000"}).status_code == 404


# ------------------------------------------------------------------------ locations


def test_location_lifecycle(client, admin, member):
    login(client, member)
    created = client.post(
        "/api/locations",
        json={"name": "Crag One", "custom_markers": [{"emoji": "🅿️", "label": "Parking", "lat": 32.5, "lng": 35.1, "primary": True}]},
    )
    assert created.status_code == 200, created.text
    attributes = client.put(
        "/api/locations/attributes",
        params={"name": "Crag One"},
        json={"attributes": [{"key": "Rock Type", "value": "Limestone"}, "Water"]},
    )
    assert attributes.status_code == 200, attributes.text
    location = next(loc for loc in client.get("/api/locations").json() if loc["name"] == "Crag One")
    assert location["latitude"] == 32.5 and location["longitude"] == 35.1
    assert location["attributes"] == [{"key": "Rock Type", "value": "Limestone"}, {"key": "Water", "value": ""}]
    assert location["owners"] == [member["id"]]
    assert "Rock Type" in client.get("/api/location-attributes").json()

    renamed = client.put("/api/locations", params={"name": "Crag One"}, json={"new_name": "Crag Renamed", "description": "Nice"})
    assert renamed.status_code == 200, renamed.text
    names = [loc["name"] for loc in client.get("/api/locations").json()]
    assert "Crag Renamed" in names and "Crag One" not in names

    login(client, admin)
    tagged = client.post("/api/albums/edit-metadata", json={"album_url": ALBUM_1, "location": "Crag Renamed"})
    assert tagged.status_code == 200
    blocked = client.delete("/api/locations", params={"name": "Crag Renamed"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["blocked_by_albums"] == 1
    moved = client.delete("/api/locations", params={"name": "Crag Renamed", "reassign_to": "Gita"})
    assert moved.status_code == 200, moved.text
    album = next(a for a in client.get("/api/albums/enriched").json() if a["url"] == ALBUM_1)
    assert album["metadata"]["location"] == "Gita"


def test_skill_catalog_delete_removes_from_climbers(client, admin):
    login(client, admin)
    assert client.post("/api/skills", json={"name": "temporary skill"}).status_code == 200
    assert client.post("/api/crew/add-skills", json={"crew_name": "Alice Climber", "skills": ["temporary skill"]}).status_code == 200
    assert client.delete("/api/skills/temporary%20skill").status_code == 200
    crew = {c["name"]: c for c in client.get("/api/crew").json()}
    assert "temporary skill" not in crew["Alice Climber"]["skills"]
    assert "temporary skill" not in client.get("/api/skills").json()


# ---------------------------------------------------------------------------- memes


def test_meme_upload_list_and_owner_only_delete(client, admin, member, pending):
    login(client, member)
    upload = client.post("/api/memes/submit", files={"image": ("m.png", png_bytes((8, 8)), "image/png")})
    assert upload.status_code == 200, upload.text
    memes = client.get("/api/memes").json()
    assert len(memes) == 1
    meme = memes[0]
    image_path = f"/redis-image/meme/{meme['id']}"
    assert client.get(image_path).status_code == 200
    login(client, pending)
    assert client.delete(f"/api/memes/{meme['id']}").status_code == 403
    login(client, member)
    assert client.delete(f"/api/memes/{meme['id']}").status_code == 200
    assert client.get("/api/memes").json() == []
    assert client.get(image_path).status_code == 404


# ------------------------------------------------------------------------ preferences


def test_user_preferences_round_trip_any_json(client, member):
    login(client, member)
    assert client.post("/api/user/preferences/dark_mode", json={"value": True}).status_code == 200
    assert client.post("/api/user/preferences/crew_sort", json={"value": {"sortKey": "level", "sortDir": -1}}).status_code == 200
    assert client.get("/api/user/preferences/dark_mode").json()["preference_value"] is True
    everything = client.get("/api/user/preferences").json()["preferences"]
    assert everything["crew_sort"] == {"sortKey": "level", "sortDir": -1}
    assert client.delete("/api/user/preferences/dark_mode").status_code == 200
    assert "dark_mode" not in client.get("/api/user/preferences").json()["preferences"]


# -------------------------------------------------------------------------- tokens


def test_api_tokens_grant_and_revoke_bearer_access(client, admin):
    login(client, admin)
    created = client.post(
        "/api/auth/token/create",
        json={"token_name": "ci", "permissions": {"can_create_albums": True}, "expires_in_hours": 2},
    )
    assert created.status_code == 200, created.text
    token = created.json()["access_token"]
    tokens = client.get("/api/auth/tokens").json()
    assert [t["name"] for t in tokens] == ["ci"]
    logout(client)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/notifications/devices", headers=headers).status_code == 200
    login(client, admin)
    assert client.delete(f"/api/auth/tokens/{tokens[0]['id']}").status_code == 200
    logout(client)
    assert client.get("/api/notifications/devices", headers=headers).status_code == 401


# --------------------------------------------------------------------- notifications


def test_push_device_lifecycle(client, member, monkeypatch):
    import routes.notifications as notifications

    async def no_push(*args, **kwargs):
        return None

    monkeypatch.setattr(notifications, "send_welcome_notification", no_push)
    monkeypatch.setattr(notifications, "validate_subscriptions_background", no_push)
    login(client, member)
    device_id = "device_test_0001"
    subscribe = client.post(
        "/api/notifications/subscribe",
        json={
            "subscription": {"endpoint": "https://push.example.test/abc", "keys": {"p256dh": "p", "auth": "a"}},
            "deviceInfo": {"deviceId": device_id, "browserName": "Chrome", "platform": "mac", "userAgent": "UA", "lastActive": "now"},
        },
        headers={"X-Device-ID": device_id},
    )
    assert subscribe.status_code == 200, subscribe.text
    devices = client.get("/api/notifications/devices").json()["devices"]
    assert len(devices) == 1 and devices[0]["full_device_id"] == device_id
    assert devices[0]["notification_preferences"]["album_created"] is True

    updated = client.put(f"/api/notifications/devices/{device_id}/preferences", json={"album_created": False})
    assert updated.status_code == 200, updated.text
    prefs = client.get(f"/api/notifications/devices/{device_id}/preferences").json()
    assert prefs["preferences"]["album_created"] is False

    resubscribed = client.post(
        "/api/notifications/subscribe",
        json={
            "subscription": {"endpoint": "https://push.example.test/new", "keys": {"p256dh": "p", "auth": "a"}},
            "deviceInfo": {"deviceId": device_id, "browserName": "Chrome", "platform": "mac", "userAgent": "UA", "lastActive": "now"},
        },
        headers={"X-Device-ID": device_id},
    )
    assert resubscribed.status_code == 200
    assert client.get(f"/api/notifications/devices/{device_id}/preferences").json()["preferences"]["album_created"] is False
    assert client.delete(f"/api/notifications/devices/{device_id}").status_code == 200
    assert client.get("/api/notifications/devices").json()["devices"] == []


# ---------------------------------------------------------------------------- admin


def test_admin_stats_users_roles_and_live_role_in_session(client, admin, pending):
    login(client, admin)
    stats = client.get("/api/admin/stats").json()
    assert stats["users"]["admins"] >= 1 and stats["resources"]["albums"]["total"] >= 1
    users = client.get("/api/admin/users").json()
    assert any(u["email"] == "pending@test.local" for u in users)
    assert client.post(f"/api/admin/users/{pending['id']}/role", data={"new_role": "user"}).status_code == 200
    login(client, pending)  # stale cookie still says pending
    me = client.get("/api/auth/user").json()
    assert me["user"]["role"] == "user"
    login(client, admin)
    assert client.post(f"/api/admin/users/{pending['id']}/role", data={"new_role": "pending"}).status_code == 200


def test_admin_export_is_a_duckdb_snapshot(client, admin, tmp_path):
    login(client, admin)
    response = client.get("/api/admin/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/octet-stream")
    snapshot = tmp_path / "snapshot.duckdb"
    snapshot.write_bytes(response.content)
    connection = duckdb.connect(str(snapshot), read_only=True)
    assert connection.execute("SELECT count(*) FROM climbers").fetchone()[0] >= 2
    assert connection.execute("SELECT count(*) FROM albums").fetchone()[0] >= 1


def test_member_cannot_use_admin_endpoints(client, member):
    login(client, member)
    assert client.get("/api/admin/stats").status_code == 403
    assert client.get("/api/admin/export").status_code == 403


# --------------------------------------------------------------------------- auth flow


def test_login_redirect_carries_next_in_signed_state(client):
    logout(client)
    response = client.get("/auth/login", params={"next": "/albums?people=Alice"}, follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "state=" in location and "prompt=" not in location


def test_backup_keeps_everything(store, tmp_path):
    path = store.backup(tmp_path / "backups")
    connection = duckdb.connect(str(path), read_only=True)
    original = asyncio.run(store.health_check())["counts"]
    for table, count in original.items():
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == count
