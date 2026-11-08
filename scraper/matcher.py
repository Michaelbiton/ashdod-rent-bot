"""Decide whether a listing fits a saved search.

full    -> every field the search cares about is known and fits
partial -> nothing contradicts the search, but some fields are unknown (listed in `missing`)
None    -> something known contradicts the search
"""
from dataclasses import dataclass, field

from .models import Listing
from .normalize import find_neighborhood

AMENITIES = [
    ("need_mamad", "has_mamad", 'ממ"ד'),
    ("need_balcony", "has_balcony", "מרפסת"),
    ("need_parking", "has_parking", "חניה"),
    ("need_elevator", "has_elevator", "מעלית"),
]


@dataclass
class Match:
    search_id: int
    missing: list[str] = field(default_factory=list)

    @property
    def full(self) -> bool:
        return not self.missing


def _in_range(value, lo, hi) -> bool:
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def match(listing: Listing, s: dict) -> Match | None:
    # Never sent: no price, or no known location (the ad doesn't say where in Ashdod it is).
    if not listing.price:
        return None
    neighborhood = listing.neighborhood or find_neighborhood(listing.text())
    if not neighborhood:
        return None
    if s.get("need_photo") and not any(i.startswith("http") for i in listing.images or []):
        return None
    missing = []

    if s.get("neighborhoods") and neighborhood not in s["neighborhoods"]:
        return None

    for value, lo, hi, label in [
        (listing.rooms, s.get("rooms_min"), s.get("rooms_max"), "חדרים"),
        (listing.price, s.get("price_min"), s.get("price_max"), "מחיר"),
    ]:
        if lo is None and hi is None:
            continue
        if value is None:
            missing.append(label)
        elif not _in_range(float(value), lo and float(lo), hi and float(hi)):
            return None

    for need, has, label in AMENITIES:
        if not s.get(need):
            continue
        value = getattr(listing, has)
        if value is False:
            return None
        if value is None:
            missing.append(label)

    if s.get("no_broker"):
        if listing.is_broker:
            return None
        if listing.is_broker is None:
            missing.append("תיווך")

    text = listing.text().lower()
    if any(k.lower() in text for k in s.get("exclude_keywords") or []):
        return None
    if s.get("include_keywords"):
        if not listing.description:
            missing.append("מילות מפתח")
        elif not any(k.lower() in text for k in s["include_keywords"]):
            return None

    return Match(search_id=s["id"], missing=missing)
