from scraper.sources.facebook import from_post, parse_post


def test_typical_offer():
    f = parse_post('להשכרה ברובע ט"ו, דירת 4 חדרים משופצת, ממ"ד, מרפסת שמש, חניה. 5,200 ₪ לחודש. '
                   "כניסה מיידית, ללא תיווך. 050-1234567")
    assert f["price"] == 5200 and f["rooms"] == 4.0 and f["neighborhood"] == "רובע טו"
    assert (f["has_mamad"], f["has_balcony"], f["has_parking"], f["has_elevator"]) == (True, True, True, None)
    assert f["is_broker"] is False and f["phone"] == "0501234567"


def test_half_rooms_and_negations():
    f = parse_post("דירה להשכרה 3 וחצי חדרים במרינה, בלי מעלית, אין ממד. מחיר: 4800")
    assert f["rooms"] == 3.5 and f["neighborhood"] == "מרינה" and f["price"] == 4800
    assert f["has_elevator"] is False and f["has_mamad"] is False


def test_quarter_with_geresh_and_broker():
    f = parse_post("רובע י'א - 2.5 חד׳ קומה 3, 3900 שח, דמי תיווך חודש")
    assert f["neighborhood"] == "רובע יא" and f["rooms"] == 2.5 and f["is_broker"] is True
    assert f["floor"] == 3
    assert parse_post("דירת 2 חדרים בקומת קרקע ברובע ב, 3500 ש\"ח")["floor"] == 0


def test_other_cities_and_no_location():
    assert parse_post("להשכרה בבניין חדש בהרצל בת ים דירת 4 חדרים, ממ\"ד, 7500 ש\"ח") is None
    assert parse_post("דירת 3 חדרים באשקלון ברובע ג, 4000 ש\"ח") is None      # names another city
    assert parse_post("להשכרה דירת 4 חדרים משופצת, 5000 ש\"ח, כניסה מיידית") is None  # no neighborhood
    f = parse_post("אשדוד, רובע ג - דירת 3 חדרים, 4200 ש\"ח (לא אשקלון!)")
    assert f["neighborhood"] == "רובע ג"                                       # Ashdod named too


def test_not_offers():
    assert parse_post("מחפשים דירת 4 חדרים ברובע ז עד 5000 ש\"ח") is None       # seeker
    assert parse_post("דירה למכירה ברובע ב, 4 חדרים, 1,850,000") is None        # sale
    assert parse_post("דירת 3 חדרים להשכרה ברובע ג, מחיר בפרטי") is None         # no price
    assert parse_post("ממליצה בחום על הובלות כהן! 2000 ש\"ח בלבד") is None         # not an apartment
    assert parse_post("סאבלט לחודש בדירת 3 חדרים 3000 ש\"ח") is None


def test_from_post_maps_apify_item():
    l = from_post({"postId": "987", "url": "https://www.facebook.com/groups/1/posts/987",
                   "text": "להשכרה 3 חדרים ברובע ח, 4,300 ₪, מעלית", "time": "2026-11-03T07:00:00.000Z",
                   "attachments": [{"image": {"uri": "https://scontent.fb/x.jpg"}}]})
    assert l.source == "facebook" and l.source_id == "987" and l.price == 4300
    assert l.published_at == "2026-11-03T07:00:00.000Z" and l.images == ["https://scontent.fb/x.jpg"]
    assert from_post({"postId": "1", "url": "u", "text": "בוקר טוב לכולם"}) is None
