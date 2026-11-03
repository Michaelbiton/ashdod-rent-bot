"""Yad2 via the Apify actor nice_dev/yad2-listings-scraper.

Yad2 blocks plain HTTP clients, so we use a paid Apify actor. `onlyNew` makes the actor
remember what it already returned, so each run only pays for new listings.
"""
import os

import requests

from ..models import Listing
from ..normalize import norm_neighborhood, norm_phone, norm_street

NAME = "yad2"
NEEDS_DETAILS = False
ACTOR = "nice_dev~yad2-listings-scraper"
RUN_URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"

ACTOR_INPUT = {
    "dealType": "rent",
    "location": "Ashdod",
    "sortBy": "newest",
    "onlyNew": True,
    "stateKey": "ashdod-rent",
    "maxItems": int(os.environ.get("YAD2_MAX_ITEMS", "40")),
    "extractDetails": True,
    "includeContacts": True,
    "stopOnBlocked": True,
}


def from_item(it: dict) -> Listing:
    phone = norm_phone(it.get("contactPhone"))
    return Listing(
        source=NAME,
        source_id=str(it["id"]),
        url=it.get("url") or f"https://www.yad2.co.il/realestate/item/{it['id']}",
        title=it.get("title"),
        neighborhood=norm_neighborhood(it.get("neighborhood")),
        street=norm_street(it.get("street")),
        house_number=it.get("houseNumber"),
        rooms=it.get("rooms"),
        floor=it.get("floor"),
        sqm=it.get("squareMeters"),
        price=int(it["price"]) if it.get("price") else None,
        has_mamad=it.get("hasSecureRoom"),
        has_balcony=it.get("hasBalcony") if it.get("hasBalcony") is not None
        else (it["balconies"] > 0 if it.get("balconies") is not None else None),
        has_parking=it.get("hasParking") if it.get("hasParking") is not None
        else (it["parkingSpaces"] > 0 if it.get("parkingSpaces") is not None else None),
        has_elevator=it.get("hasElevator"),
        is_broker={"agency": True, "private": False}.get(it.get("sellerType")),
        phone=phone,
        description=it.get("description"),
        images=(it.get("images") or ([it["imageUrl"]] if it.get("imageUrl") else []))[:10],
        entry_date="מיידי" if it.get("isImmediateEntrance") else it.get("entranceDate"),
    )


def fetch(session) -> list[Listing]:
    token = os.environ["APIFY_TOKEN"]
    r = requests.post(
        RUN_URL,
        params={"timeout": 240},
        headers={"Authorization": f"Bearer {token}"},
        json=ACTOR_INPUT,
        timeout=270,
    )
    r.raise_for_status()
    items = r.json()
    return [from_item(it) for it in items if it.get("id") and it.get("city", "אשדוד") == "אשדוד"]
