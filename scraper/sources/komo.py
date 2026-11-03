"""komo.co.il — list page has address/price/rooms; amenities and broker flag come from the ad page."""
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import norm_neighborhood, parse_ago, parse_float, parse_floor, parse_int, split_address
from . import get_html

NAME = "komo"
BASE = "https://www.komo.co.il"
LIST_URL = f"{BASE}/code/nadlan/apartments-for-rent.asp?cityName={quote('אשדוד')}"
NEEDS_DETAILS = True
EMPTY_IS_ERROR = True

NON_RESIDENTIAL = ("משרד", "חנו", "מחסן", "מגרש", "חניה", "מבנה", "אולם", "מסחרי", "קליניק")
FEATURES = {"mamad": "has_mamad", "maalit": "has_elevator"}


def parse_list(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for box in soup.select("div.modaaPPC__box[id^=modaaPPC], div.modaa__box[id^=modaaRowDv]"):
        ad_id = re.sub(r"\D", "", box["id"])
        if ad_id in seen:
            continue
        seen.add(ad_id)
        title = box.select_one("h2.title")
        parts = [p.strip() for p in title.get_text().split(",")] if title else []
        if not parts or parts[0] != "אשדוד":
            continue
        desc = box.select_one("div.description")
        desc_text = desc.get_text(" ", strip=True) if desc else ""
        if desc_text.startswith(NON_RESIDENTIAL):
            continue
        rooms = re.search(r"(\d+(?:\.\d)?)\s*חדרים", desc_text)
        sqm = re.search(r"\((\d+)\s*מ", desc_text)
        floor = re.search(r"קומה:\s*(\S+)", desc_text)
        img = box.select_one(".image__wrapper img")
        src = img.get("src", "") if img else ""
        price = box.select_one("div.price")
        street, house_number = split_address(parts[2]) if len(parts) > 2 else (None, None)
        out.append(Listing(
            source=NAME,
            source_id=ad_id,
            url=f"{BASE}/code/nadlan/details/?modaaNum={ad_id}",
            title=title.get_text(strip=True) if title else None,
            neighborhood=norm_neighborhood(parts[1]) if len(parts) > 1 else None,
            street=street,
            house_number=house_number,
            rooms=parse_float(rooms.group(1)) if rooms else None,
            sqm=parse_float(sqm.group(1)) if sqm else None,
            floor=parse_floor(floor.group(1)) if floor else None,
            price=parse_int(price.get_text()) if price else None,
            images=[BASE + src] if src and "picNum=0&" not in src else [],
        ))
    return out


def parse_details(html: str, listing: Listing) -> None:
    for m in re.finditer(r"<li class='(\w+)( add)? ?'>", html):
        attr = FEATURES.get(m.group(1))
        if attr:
            setattr(listing, attr, bool(m.group(2)))
    listing.is_broker = "tivuhName" in html or "רישיון תיווך" in html
    updated = re.search(r'class="m_updateDate[^"]*">([^<]+)<', html)
    if updated:
        listing.bumped_at = parse_ago(updated.group(1))
    # Komo has no balcony/parking flags, so we only learn them from the ad text (never "False").
    about = BeautifulSoup(html, "html.parser").select_one("#teurWrap")
    if about:
        listing.description = about.get_text(" ", strip=True) or None
    text = listing.description or ""
    if "מרפסת" in text:
        listing.has_balcony = True
    if re.search(r"חני(?:י)?(?:ה|ות)", text):
        listing.has_parking = True


def fetch(session) -> list[Listing]:
    return parse_list(get_html(session, LIST_URL))


def enrich(session, listing: Listing) -> None:
    parse_details(get_html(session, listing.url), listing)
