"""End-to-end pass of scraper.main.run_source with an in-memory DB and a fake Telegram."""
from scraper import main
from scraper.models import Listing


class FakeDB:
    def __init__(self):
        self.kv, self.listings, self.alerts = {}, [], []

    def kv_get(self, k):
        return self.kv.get(k)

    def kv_set(self, k, v):
        self.kv[k] = v

    def known_ids(self, source, ids):
        return {l.source_id for l in self.listings if l.source == source} & set(ids)

    def add_listing(self, l, group_id):
        l.id = len(self.listings) + 1
        l.group_id = group_id or l.id
        self.listings.append(l)
        return l

    def source_listings(self, source, days=14, limit=200):
        return [l for l in reversed(self.listings) if l.source == source]

    def group_alerts(self, gid):
        return [a for a in self.alerts if a["group_id"] == gid]

    def add_alert(self, chat_id, l, search_id):
        if any(a["chat_id"] == chat_id and a["group_id"] == l.group_id for a in self.alerts):
            return None
        a = {"id": len(self.alerts) + 1, "chat_id": chat_id, "group_id": l.group_id,
             "message_id": None, "status": "sent"}
        self.alerts.append(a)
        return a

    def update(self, table, values, id):
        next(a for a in self.alerts if a["id"] == id).update(values)


class FakeTG:
    def __init__(self):
        self.alerts, self.texts = [], []

    def send_alert(self, chat_id, listing, m, summary, median, alert_id):
        self.alerts.append((chat_id, listing.source_id, m.missing))
        return 100 + alert_id

    def send_text(self, chat_id, text, **extra):
        self.texts.append((chat_id, text, extra))


class FakeSource:
    NAME = "fake"
    NEEDS_DETAILS = False

    def __init__(self, batches):
        self.batches = batches

    def fetch(self, session):
        return self.batches.pop(0)


def L(sid, **kw):
    base = dict(source="fake", source_id=sid, url=f"https://x/{sid}", neighborhood="רובע טו",
                street="תל חי", house_number="12", rooms=3.0, price=5500, has_mamad=True)
    return Listing(**{**base, **kw})


SEARCHES = [
    {"id": 1, "chat_id": 111, "neighborhoods": ["רובע טו"], "price_max": 6000, "need_mamad": True},
    {"id": 2, "chat_id": 222, "neighborhoods": ["רובע א"]},
]


def test_bootstrap_then_alert_then_duplicate(monkeypatch):
    monkeypatch.setattr(main.summarizer, "summarize", lambda l, m: None)
    db, tg = FakeDB(), FakeTG()
    src = FakeSource([[L("old", house_number="3")], [L("old", house_number="3"), L("new")]])

    main.run_source(src, db, tg, None, SEARCHES, [], admin=None)    # first run: remember, don't alert
    assert tg.alerts == [] and db.kv["bootstrapped:fake"] is True

    recent = list(db.listings)
    main.run_source(src, db, tg, None, SEARCHES, recent, admin=None)
    assert tg.alerts == [(111, "new", [])]                     # only the matching user

    # a repost of the same apartment: reply under the original alert, no second alert
    other = FakeSource([[L("k1", source="komo", house_number="12", price=5450)]])
    other.NAME = "komo"
    db.kv["bootstrapped:komo"] = True
    main.run_source(other, db, tg, None, SEARCHES, recent, admin=None)
    assert len(tg.alerts) == 1
    assert tg.texts and tg.texts[0][0] == 111 and tg.texts[0][2]["reply_to_message_id"] == 101


def test_backfill_sends_existing_matches_once(monkeypatch):
    monkeypatch.setattr(main.summarizer, "summarize", lambda l, m: None)
    monkeypatch.setattr(main, "BACKFILL_LIMIT", 2)
    db, tg = FakeDB(), FakeTG()
    items = [L("a", house_number="1"), L("b", house_number="2", has_mamad=None),
             L("c", house_number="3"), L("far", neighborhood="רובע א", house_number="4")]
    assert main.run_source(FakeSource([items]), db, tg, None, SEARCHES, [], admin=None)
    assert tg.alerts == []                                   # bootstrap itself stays quiet

    main.backfill("fake", db, tg, SEARCHES, db.listings)
    # user 111: two full matches first (newest first), the partial "b" is cut by the limit
    assert [a for a in tg.alerts if a[0] == 111] == [(111, "c", []), (111, "a", [])]
    # user 222 searches רובע א
    assert [a for a in tg.alerts if a[0] == 222] == [(222, "far", [])]

    main.backfill("fake", db, tg, SEARCHES, db.listings)     # second run: nothing new
    assert len(tg.alerts) == 3


def test_failure_warning(monkeypatch):
    db, tg = FakeDB(), FakeTG()

    class Broken(FakeSource):
        def fetch(self, session):
            raise RuntimeError("blocked")

    for _ in range(3):
        main.run_source(Broken([]), db, tg, None, SEARCHES, [], admin=999)
    assert db.kv["fails:fake"] == 3
    assert len(tg.texts) == 1 and tg.texts[0][0] == 999
