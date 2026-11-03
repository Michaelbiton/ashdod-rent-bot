"""homeless.co.il — the /rent board holds private (non-broker) ads; brokers post on /RentTivuch."""
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import norm_neighborhood, parse_float, parse_floor, parse_il_date, parse_int, split_address
from . import get_html

NAME = "homeless"
BASE = "https://www.homeless.co.il"
LIST_URL = f"{BASE}/rent/city={quote('אשדוד')}"
NEEDS_DETAILS = True
EMPTY_IS_ERROR = True

FEATURES = {"ממד": "has_mamad", "מרפסת": "has_balcony", "חניה": "has_parking", "מעלית": "has_elevator"}


def parse_list(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select('tr[id^="ad_"][type="ad"]'):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
        # selection, image, type, city, neighborhood, street, rooms, floor, price, entry, updated, link
        if len(tds) < 11 or "אשדוד" not in tds[3]:
            continue
        ad_id = tr["id"].removeprefix("ad_")
        img = tr.select_one("img.PictureDisplayOnBoard")
        src = img.get("src", "") if img else ""
        images = [src.replace("/300/", "/")] if src.startswith("http") else []
        street, house_number = split_address(tds[5])
        out.append(Listing(
            source=NAME,
            source_id=ad_id,
            url=f"{BASE}/rent/viewad,{ad_id}.aspx",
            title=f"{tds[2]} · {tds[5]}".strip(" ·"),
            neighborhood=norm_neighborhood(tds[4]),
            street=street,
            house_number=house_number,
            rooms=parse_float(tds[6]),
            floor=parse_floor(tds[7]),
            price=parse_int(tds[8]),
            entry_date=tds[9] or None,
            bumped_at=parse_il_date(tds[10]),   # homeless shows the date of the last update/bump
            is_broker=False,
            images=images,
        ))
    return out


def parse_details(html: str, listing: Listing) -> None:
    soup = BeautifulSoup(html, "html.parser")
    for div in soup.select("div.IconOption"):
        classes = div.get("class", [])
        label = div.get_text(" ", strip=True).replace('"', "")
        for key, attr in FEATURES.items():
            if label.startswith(key):
                if "on" in classes:
                    setattr(listing, attr, True)
                elif "off" in classes:
                    setattr(listing, attr, False)
        if label.startswith('מ"ר') or label.startswith("מר:"):
            listing.sqm = parse_float(label.split(":")[-1])
    remarks = soup.select_one("div.remarks")
    if remarks:
        listing.description = remarks.get_text(" ", strip=True).replace("פירוט הריהוט:", "").strip() or None
    thumbs = [i["src"].replace("/300/", "/") for i in soup.select("img.thumbnail") if i.get("src")]
    if thumbs:
        listing.images = thumbs


def fetch(session) -> list[Listing]:
    return parse_list(get_html(session, LIST_URL))


def enrich(session, listing: Listing) -> None:
    parse_details(get_html(session, listing.url), listing)
