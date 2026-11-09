from datetime import datetime, timedelta, timezone

from scraper import main
from scraper.sources import yad2
from tests.test_run import FakeDB, FakeTG


class Src:
    NAME = "paid"
    PAID = True

    def __init__(self, every):
        self.EVERY_HOURS = every


def test_due_respects_interval():
    db = FakeDB()
    assert main.due(Src(4), db)                                   # never ran
    db.kv["last_run:paid"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert not main.due(Src(4), db)
    db.kv["last_run:paid"] = (datetime.now(timezone.utc) - timedelta(hours=3, minutes=50)).isoformat()
    assert main.due(Src(4), db)                                   # cron slack
    assert not main.due(Src(0), db)                               # 0 = off


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self.data}


def limits(used):
    return {"current": {"monthlyUsageUsd": used}, "limits": {"maxMonthlyUsageUsd": 5},
            "monthlyUsageCycle": {"endAt": "2026-12-03T00:00:00.000Z"}}


def test_budget_guard_notifies_once(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "t")
    db, tg = FakeDB(), FakeTG()
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Resp(limits(2.0)))
    assert main.apify_budget_ok(db, tg, admin=1) is True
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: Resp(limits(4.8)))
    assert main.apify_budget_ok(db, tg, admin=1) is False
    assert main.apify_budget_ok(db, tg, admin=1) is False
    assert len(tg.texts) == 1 and "2026-12-03" in tg.texts[0][1]


def test_yad2_filters_cover_all_searches():
    assert yad2.search_filters([]) == {}
    one = [{"price_min": 4000, "price_max": 6000, "rooms_min": 3, "rooms_max": 4}]
    assert yad2.search_filters(one) == {"minPrice": 4000, "maxPrice": 6000, "minRooms": 3.0, "maxRooms": 4.0}
    two = one + [{"price_min": None, "price_max": 7500, "rooms_min": 2.5, "rooms_max": None}]
    assert yad2.search_filters(two) == {"maxPrice": 7500, "minRooms": 2.5}   # open ends stay open
