"""Album date handling.

Google Photos shows dates without a year for the current year and as ranges for
multi-day albums. Everything that turns a display date into a real date lives here.
"""

import re
from datetime import datetime
from typing import Any, Dict, Optional

MONTH_ALIASES = {"sept": "sep"}
ALBUM_DATE_FORMATS = (
    "%B %d, %Y",  # December 25, 2025
    "%b %d, %Y",  # Dec 25, 2025
    "%d %B, %Y",  # 25 December, 2025
    "%d %b, %Y",  # 25 Dec, 2025
    "%B %d %Y",  # December 25 2025
    "%b %d %Y",  # Dec 25 2025
    "%d %B %Y",  # 25 December 2025
    "%d %b %Y",  # 25 Dec 2025
)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


def parse_album_date(
    date_str: str, reference: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Central utility to parse album date strings into datetime objects.
    Handles the display formats Google Photos produces, with or without a year,
    with or without a weekday prefix, and date ranges (first day of the range).
    When the range carries a single year at its end ("Dec 27 – 28, 2024"), that
    year applies to the first day too.
    A yearless date is placed in the latest year that keeps it on or before
    `reference` (default: now). Pass the time the album was added as reference:
    a climb can never be later than the moment its album was recorded.
    Returns None if the date cannot be parsed.
    """
    if not date_str or not isinstance(date_str, str):
        return None
    reference = reference or datetime.now()

    try:
        # Remove emoji and extra spaces
        clean_date = re.sub(r"📸.*$", "", date_str).strip()

        # A year anywhere in the full string is the authoritative year
        year_match = YEAR_PATTERN.search(clean_date)
        explicit_year = int(year_match.group(1)) if year_match else None

        # Handle date ranges - use first date
        for separator in ("–", "—", " - "):
            if separator in clean_date:
                clean_date = clean_date.split(separator)[0].strip()
                break

        # Remove day of week prefix (e.g., "Saturday, ")
        clean_date = re.sub(r"^[A-Za-z]+,\s*", "", clean_date)
        clean_date = clean_date.replace(".", "")
        for alias, canonical in MONTH_ALIASES.items():
            clean_date = re.sub(rf"\b{alias}\b", canonical, clean_date, flags=re.IGNORECASE)

        # Ensure the first date carries a year
        if not YEAR_PATTERN.search(clean_date):
            clean_date = f"{clean_date}, {explicit_year or reference.year}"

        parsed_date = None
        for fmt in ALBUM_DATE_FORMATS:
            try:
                parsed_date = datetime.strptime(clean_date, fmt)
                break
            except ValueError:
                continue

        if parsed_date is None:
            return None

        # Only an inferred year can be wrong: a yearless date after the reference is from the year before
        if explicit_year is None and parsed_date > reference:
            parsed_date = parsed_date.replace(year=parsed_date.year - 1)

        return parsed_date

    except Exception:
        return None


NEW_CLIMBER_WINDOW_DAYS = 14


def parse_iso_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp into a naive local datetime. Returns None when unparseable."""
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def album_climb_timestamp(album: Dict) -> Optional[datetime]:
    """When the climb happened: the album date, or the time it was added when the date is unusable."""
    added_at = parse_iso_timestamp(album.get("created_at"))
    return parse_album_date(album.get("date", ""), reference=added_at) or added_at
