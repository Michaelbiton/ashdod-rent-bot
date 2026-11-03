from pathlib import Path

from scraper.normalize import norm_neighborhood, norm_phone, parse_floor, split_address
from scraper.sources import homeless, komo, yad2

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_norm_neighborhood_variants():
    assert norm_neighborhood("רובע ט''ו") == "רובע טו"
    assert norm_neighborhood('רובע ט"ו') == "רובע טו"
    assert norm_neighborhood("רובע י״א") == "רובע יא"
    assert norm_neighborhood("רובע ח'") == "רובע ח"
    assert norm_neighborhood("רובה ב") == "רובע ב"
    assert norm_neighborhood("רובע ט&quot;ז") == "רובע טז"
    assert norm_neighborhood("הסיטי") == "סיטי"
    assert norm_neighborhood("") is None


def test_small_parsers():
    assert split_address("שד הרצל 48") == ("שד הרצל", "48")
    assert split_address("לא צוין רחוב") == (None, None)
    assert split_address("הרב הרצוג") == ("הרב הרצוג", None)
    assert parse_floor("קרקע מתוך 8") == 0
    assert parse_floor("4 מתוך 9") == 4
    assert norm_phone("+972-50-123-4567") == "0501234567"


def test_homeless_list():
    items = homeless.parse_list(read("homeless_list.html"))
    assert len(items) >= 15
    first = next(i for i in items if i.source_id == "701591")
    assert first.neighborhood == "רובע ב"
    assert first.street == "הרב הרצוג"
    assert (first.rooms, first.floor, first.price) == (2.5, 1, 3600)
    assert first.is_broker is False
    assert first.bumped_at.startswith("2026-11-03")
    assert all(img.startswith("http") for i in items for img in i.images)


def test_homeless_details():
    item = next(i for i in homeless.parse_list(read("homeless_list.html")) if i.source_id == "715191")
    homeless.parse_details(read("homeless_ad.html"), item)
    assert (item.has_mamad, item.has_balcony, item.has_parking, item.has_elevator) == (True, True, True, True)
    assert item.sqm == 85
    assert "תל חי" in item.description


def test_komo_list():
    items = komo.parse_list(read("komo_list.html"))
    assert len(items) >= 20
    ad = next(i for i in items if i.source_id == "4944624")
    assert (ad.neighborhood, ad.street, ad.house_number) == ("רובע א", "שד הרצל", "48")
    assert (ad.rooms, ad.sqm, ad.floor, ad.price) == (5.0, 125.0, 4, 7500)
    assert not any(i.title and "משרדים" in (i.title or "") for i in items)
    # the office listing on the page is skipped
    assert "4844364" not in {i.source_id for i in items}


def test_komo_details():
    item = komo.Listing(source="komo", source_id="4944624", url="x")
    komo.parse_details(read("komo_ad.html"), item)
    assert item.has_mamad is True and item.has_elevator is True
    assert item.is_broker is True
    assert item.has_parking is True          # "פלוס חנייה" in the ad text
    assert item.has_balcony is None          # not mentioned -> unknown, never False
    assert item.description.startswith("5 חדרים")
    assert item.bumped_at is not None        # "עודכן לפני: 2 שעות"


def test_yad2_mapping():
    l = yad2.from_item({
        "id": "abc123", "url": "https://www.yad2.co.il/realestate/item/abc123", "title": "תל חי 12",
        "neighborhood": 'רובע ט"ו', "street": "תל חי", "houseNumber": "12", "rooms": 3.5, "floor": 4,
        "squareMeters": 90, "price": 5500, "hasSecureRoom": True, "hasBalcony": None, "balconies": 2,
        "hasParking": False, "hasElevator": True, "sellerType": "private", "contactPhone": "050-1234567",
        "images": ["https://img.yad2.co.il/a.jpg"], "isImmediateEntrance": True, "city": "אשדוד",
        "publishedAt": "2026-10-01T06:00:00.000Z", "bumpedAt": "2026-11-02T06:30:00.000Z",
    })
    assert (l.published_at, l.bumped_at) == ("2026-10-01T06:00:00.000Z", "2026-11-02T06:30:00.000Z")
    assert l.neighborhood == "רובע טו"
    assert l.has_balcony is True and l.has_parking is False and l.is_broker is False
    assert l.phone == "0501234567" and l.entry_date == "מיידי"
