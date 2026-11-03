"""Yad2 via the Apify actor nice_dev/yad2-listings-scraper.

Yad2 blocks plain HTTP clients, so we use a paid Apify actor. `onlyNew` makes the actor
remember what it already returned, so each run only pays for new listings.
"""
import logging
import os
import time

import requests

from ..models import Listing
from ..normalize import norm_neighborhood, norm_phone, norm_street

log = logging.getLogger(__name__)
NAME = "yad2"
NEEDS_DETAILS = False
ACTOR = "nice_dev~yad2-listings-scraper"
API = "https://api.apify.com/v2"
RUN_TIMEOUT = 480  # seconds; the GitHub job allows 15 minutes

ACTOR_INPUT = {
    "dealType": "rent",
    # The actor's "Ashdod" place lookup adds area/region codes that return no cards; the plain city URL works.
    "startUrls": [{"url": "https://www.yad2.co.il/realestate/rent?city=0070"}],
    "sortBy": "newest",
    "onlyNew": True,
    "stateKey": "ashdod-rent-v2",
    "maxItems": int(os.environ.get("YAD2_MAX_ITEMS", "25")),
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
    # Start the run and poll it: the run-sync endpoint gives up after ~5 minutes, and detail pages take longer.
    api = requests.Session()
    api.headers["Authorization"] = f"Bearer {os.environ['APIFY_TOKEN']}"
    r = api.post(f"{API}/acts/{ACTOR}/runs", params={"timeout": RUN_TIMEOUT}, json=ACTOR_INPUT, timeout=30)
    r.raise_for_status()
    run = r.json()["data"]
    deadline = time.time() + RUN_TIMEOUT + 60
    while run["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        run = api.get(f"{API}/actor-runs/{run['id']}", timeout=30).json()["data"]

    items = api.get(f"{API}/datasets/{run['defaultDatasetId']}/items", params={"clean": "true"}, timeout=60).json()
    log.info("yad2: run %s %s, %d items", run["id"], run["status"], len(items))
    if not items:
        run_log = api.get(f"{API}/actor-runs/{run['id']}/log", timeout=30).text
        if run["status"] != "SUCCEEDED":
            raise RuntimeError(f"apify run {run['status']}:\n{run_log[-1500:]}")
        log.info("yad2 actor log (tail):\n%s", run_log[-3000:])
    return [from_item(it) for it in items if it.get("id") and "אשדוד" in str(it.get("city") or "אשדוד")]
