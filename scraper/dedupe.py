"""Find the same apartment posted on another source (or reposted on the same one)."""
from statistics import median

from .models import Listing


def _close_price(a: int | None, b: int | None, tolerance=0.05) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance * max(a, b)


def same_apartment(a: Listing, b: Listing) -> bool:
    if a.source == b.source and a.source_id == b.source_id:
        return True
    if a.rooms is not None and b.rooms is not None and a.rooms != b.rooms:
        return False
    if a.phone and a.phone == b.phone and _close_price(a.price, b.price):
        return True
    if not (a.street and a.street == b.street and _close_price(a.price, b.price)):
        return False
    # Same street and price: also need the house number, or the same floor when one side has no number.
    if a.house_number and b.house_number:
        return a.house_number == b.house_number
    return a.floor is not None and a.floor == b.floor


def find_group(listing: Listing, recent: list[Listing]) -> int | None:
    for other in recent:
        if other.group_id and same_apartment(listing, other):
            return other.group_id
    return None


def median_price(listing: Listing, recent: list[Listing]) -> tuple[int, str] | None:
    """Median rent of similar listings: same neighborhood first, else all of Ashdod."""
    if listing.rooms is None:
        return None
    similar = [o for o in recent if o.price and o.rooms is not None and abs(o.rooms - listing.rooms) <= 0.5]
    local = [o.price for o in similar if listing.neighborhood and o.neighborhood == listing.neighborhood]
    if len(local) >= 5:
        return int(median(local)), listing.neighborhood
    city = [o.price for o in similar]
    if len(city) >= 5:
        return int(median(city)), "אשדוד"
    return None
