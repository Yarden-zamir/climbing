"""Fill missing location data from data/locations_enrichment.json.

Run on the server (or anywhere with the production database file, see CLIMBING_DB_PATH):

    uv run python scripts/enrich_locations.py            # dry run, prints the plan
    uv run python scripts/enrich_locations.py --apply    # write

Rules:
- Only empty fields are filled. Existing descriptions, coordinates, approach text and markers stay.
- Attributes are merged by key; an existing key keeps its value.
- The special "__attribute_key_cleanup__" element deletes junk global attribute keys and renames
  misspelled keys on every location.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from store import Store  # noqa: E402

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "locations_enrichment.json"
CLEANUP_NAME = "__attribute_key_cleanup__"


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


async def enrich_location(store: Store, current: dict, patch: dict, apply: bool) -> list[str]:
    changes: list[str] = []
    fields = {}
    for field in ("description", "approach"):
        if not is_blank(patch.get(field)) and is_blank(current.get(field)):
            fields[field] = patch[field].strip()
            changes.append(f"{field}: {fields[field][:60]}…")
    if (
        patch.get("latitude") is not None
        and patch.get("longitude") is not None
        and is_blank(current.get("latitude"))
    ):
        fields["latitude"] = float(patch["latitude"])
        fields["longitude"] = float(patch["longitude"])
        changes.append(f"coordinates: {fields['latitude']}, {fields['longitude']}")
    if patch.get("custom_markers") and not current.get("custom_markers"):
        fields["custom_markers"] = patch["custom_markers"]
        changes.append(f"markers: {len(fields['custom_markers'])}")

    existing_attributes = {a["key"]: a["value"] for a in current.get("attributes", [])}
    new_attributes = [
        a for a in patch.get("attributes", []) if a.get("key") and a["key"] not in existing_attributes
    ]
    if new_attributes:
        changes.append("attributes: " + ", ".join(f"{a['key']}={a.get('value', '')}" for a in new_attributes))

    if apply and fields:
        await store.update_location(current["name"], **fields)
    if apply and new_attributes:
        merged = [{"key": k, "value": v} for k, v in existing_attributes.items()] + [
            {"key": a["key"], "value": a.get("value", "")} for a in new_attributes
        ]
        await store.set_location_attributes(current["name"], merged)
    return changes


async def cleanup_attribute_keys(store: Store, spec: dict, apply: bool) -> list[str]:
    changes: list[str] = []
    for key in spec.get("delete_keys", []):
        changes.append(f"delete global attribute key {key!r}")
        if apply:
            await store.delete_location_attribute_global(key)
    renames: dict[str, str] = spec.get("rename_keys", {})
    if renames:
        for location in await store.get_all_locations():
            attributes = location.get("attributes", [])
            if not any(a["key"] in renames for a in attributes):
                continue
            renamed = {}
            for a in attributes:
                target = renames.get(a["key"], a["key"])
                renamed.setdefault(target, a["value"])
            changes.append(f"{location['name']}: rename {[a['key'] for a in attributes if a['key'] in renames]}")
            if apply:
                await store.set_location_attributes(location["name"], [{"key": k, "value": v} for k, v in renamed.items()])
        for old_key in renames:
            changes.append(f"delete renamed global attribute key {old_key!r}")
            if apply:
                await store.delete_location_attribute_global(old_key)
    return changes


async def main(apply: bool) -> None:
    store = Store(
        os.environ.get(
            "CLIMBING_DB_PATH", str(Path(os.environ.get("KITSHN_DATA_DIR", ".")) / "climbing.duckdb")
        )
    )
    patches = json.loads(DATA_FILE.read_text())
    locations = {loc["name"]: loc for loc in await store.get_all_locations()}
    for patch in patches:
        name = patch["name"]
        if name == CLEANUP_NAME:
            changes = await cleanup_attribute_keys(store, patch, apply)
        elif name not in locations:
            print(f"!! {name}: not found on this server, skipped")
            continue
        else:
            changes = await enrich_location(store, locations[name], patch, apply)
        marker = "✓" if apply else "·"
        print(f"{marker} {name}: " + ("; ".join(changes) if changes else "nothing to fill"))
    if not apply:
        print("\nDry run. Re-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
