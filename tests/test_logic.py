from datetime import datetime

from scraper import dedupe
from scraper.matcher import match
from scraper.models import Listing
from scraper.normalize import IL, parse_ago, parse_il_date
from scraper.notifier import format_alert, format_dates, format_when, keyboard, whatsapp_link

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=IL)


def test_date_parsing_and_display():
    assert parse_il_date("03/11/2026").startswith("2026-11-03T00:00:00+02:00")
    assert parse_ago("עודכן לפני: 2 שעות", NOW).startswith("2026-11-03T13:00")
    assert parse_ago("עודכן לפני: שעה", NOW).startswith("2026-11-03T14:00")
    assert parse_ago("לפני 3 ימים", NOW).startswith("2026-10-31T15:00")
    assert format_when("2026-11-03T10:14:00.000Z", NOW) == "היום 12:14"      # UTC -> Israel
    assert format_when("2026-11-02T00:00:00+02:00", NOW) == "אתמול"         # date only, no clock
    assert format_when("2026-10-30T09:00:00+02:00", NOW) == "לפני 4 ימים"
    assert format_when("2026-10-01T09:00:00+03:00", NOW) == "01/10/2026"
    both = L(published_at="2026-10-01T09:00:00+03:00", bumped_at="2026-11-02T08:30:00+02:00")
    assert format_dates(both, NOW) == "🗓 פורסם: 01/10/2026 · 🔄 הוקפץ: אתמול 08:30"
    assert format_dates(L(bumped_at="2026-11-03T00:00:00+02:00"), NOW) == "🔄 עודכן/הוקפץ: היום"
    assert format_dates(L(), NOW) is None


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



def test_location_required():
    assert match(L(neighborhood=None), S()) is None                                  # nowhere to place it
    assert match(L(neighborhood=None, description="דירה יפה ברובע י״ז ליד הים"), S()).full  # found in the text
    assert match(L(neighborhood=None, description="ברובע י״ז"), S(neighborhoods=["רובע א"])) is None


def test_photo_required_option():
    assert match(L(images=[]), S(need_photo=True)) is None
    assert match(L(images=["/images/nopic.jpg"]), S(need_photo=True)) is None
    assert match(L(images=["https://x/1.jpg"]), S(need_photo=True)).full
    assert match(L(images=[]), S()).full                                             # off by default


def test_no_price_is_never_sent():
    assert match(L(price=None), S()) is None
    assert match(L(price=0), S()) is None


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


def test_dedupe_same_post_in_several_groups():
    text = "להשכרה ברובע טו דירת 3 חדרים משופצת עם ממד ומרפסת, 5500 שח, כניסה מיידית, לפרטים בפרטי"
    a = L(source="facebook", source_id="p1", street=None, description=text)
    a.group_id = 20
    edited = text.replace("כניסה מיידית", "כניסה בדצמבר") + " !!"
    assert dedupe.find_group(L(source="facebook", source_id="p2", street=None, description=edited), [a]) == 20
    other = "דירה אחרת לגמרי בשכונה אחרת, 5500 שקלים, גינה גדולה וחניה פרטית, בלי תיווך"
    assert dedupe.find_group(L(source="facebook", source_id="p3", street=None, description=other), [a]) is None


def test_dedupe_by_neighborhood_rooms_price_floor():
    a = L(source="yad2", source_id="y9", street=None, floor=4)
    a.group_id = 30
    assert dedupe.find_group(L(source="facebook", source_id="f9", street=None, floor=4), [a]) == 30
    assert dedupe.find_group(L(source="facebook", source_id="f9", street=None, floor=5), [a]) is None
    assert dedupe.find_group(L(source="facebook", source_id="f9", street=None, floor=4, price=5600), [a]) is None
    assert dedupe.find_group(L(source="facebook", source_id="f9", street=None, floor=4,
                               neighborhood="רובע א"), [a]) is None


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
