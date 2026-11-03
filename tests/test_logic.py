from scraper import dedupe
from scraper.matcher import match
from scraper.models import Listing
from scraper.notifier import format_alert, keyboard, whatsapp_link


def L(**kw):
    base = dict(source="homeless", source_id="1", url="https://x/1", neighborhood="רובע טו", street="תל חי",
                rooms=3.0, price=5500, has_mamad=True, has_balcony=True, has_parking=None,
                has_elevator=True, is_broker=False)
    base.update(kw)
    return Listing(**base)


def S(**kw):
    base = dict(id=7, chat_id=1, neighborhoods=[], rooms_min=None, rooms_max=None, price_min=None,
                price_max=None, need_mamad=False, need_balcony=False, need_parking=False,
                need_elevator=False, no_broker=False, exclude_keywords=[], include_keywords=[])
    base.update(kw)
    return base


def test_full_match():
    m = match(L(), S(neighborhoods=["רובע טו"], rooms_min=3, rooms_max=4, price_max=6000, need_mamad=True))
    assert m and m.full


def test_partial_when_unknown():
    m = match(L(), S(need_parking=True))
    assert m and m.missing == ["חניה"]
    m = match(L(neighborhood=None, price=None), S(neighborhoods=["רובע א"], price_max=5000))
    assert m.missing == ["רובע", "מחיר"]


def test_rejections():
    assert match(L(), S(neighborhoods=["רובע א"])) is None
    assert match(L(price=7000), S(price_max=6000)) is None
    assert match(L(rooms=2.5), S(rooms_min=3)) is None
    assert match(L(has_mamad=False), S(need_mamad=True)) is None
    assert match(L(is_broker=True), S(no_broker=True)) is None
    assert match(L(description="מתאים לשותפים"), S(exclude_keywords=["שותפים"])) is None
    assert match(L(description="דירה רגילה"), S(include_keywords=["גינה"])) is None


def test_keywords():
    assert match(L(description="דירת גן עם גינה"), S(include_keywords=["גינה"])).full
    assert match(L(description=None), S(include_keywords=["גינה"])).missing == ["מילות מפתח"]


def test_dedupe_by_address_and_phone():
    a = L(source="yad2", source_id="y1", house_number="12", price=5500)
    a.group_id = 10
    assert dedupe.find_group(L(source="komo", source_id="k1", house_number="12", price=5600), [a]) == 10
    assert dedupe.find_group(L(source="komo", source_id="k1", house_number="14", price=5500), [a]) is None
    assert dedupe.find_group(L(source="komo", source_id="k1", house_number="12", price=7000), [a]) is None
    b = L(source="yad2", source_id="y2", street=None, phone="0501234567", price=4000)
    b.group_id = 11
    assert dedupe.find_group(L(source="komo", source_id="k2", street="אחר", phone="0501234567", price=4100), [b]) == 11
    # different room count is never the same apartment
    assert dedupe.find_group(L(source="komo", source_id="k3", house_number="12", rooms=4.0), [a]) is None


def test_median():
    recent = [L(source_id=str(i), price=p) for i, p in enumerate([4000, 4500, 5000, 5500, 6000])]
    assert dedupe.median_price(L(), recent) == (5000, "רובע טו")
    assert dedupe.median_price(L(), recent[:3]) is None


def test_alert_format_and_buttons():
    l = L(phone="0501234567", house_number="12", floor=4, sqm=85)
    m = match(l, S(need_parking=True))
    text = format_alert(l, m, "דירה במחיר סביר.", (5200, "רובע טו"))
    assert "5,500 ₪" in text and "חציון ברובע טו: 5,200" in text
    assert "⚠️ לא צוין במודעה: חניה" in text
    assert "❔ חניה" in text and "👤 פרטי" in text
    kb = keyboard(l, alert_id=42)["inline_keyboard"]
    assert kb[0][1]["url"].startswith("https://wa.me/972501234567?text=")
    assert kb[1][0]["callback_data"] == "save:42"
    assert whatsapp_link(L()) is None
