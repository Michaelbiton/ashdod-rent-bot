"""One scrape pass. Run hourly by GitHub Actions: python -m scraper.main"""
import logging
import os
import time

from . import dedupe, summarizer
from .db import DB
from .matcher import match
from .notifier import Telegram
from .sources import facebook, homeless, http_session, komo, yad2

log = logging.getLogger("scraper")
MAX_DETAIL_FETCHES = 30   # per source per run; new listings beyond this are matched on list data only
FAILS_BEFORE_WARNING = 3
BACKFILL_LIMIT = 10       # existing listings sent per source when a search is first seen


def enabled_sources():
    sources = [homeless, komo]
    if os.environ.get("APIFY_TOKEN"):
        sources.insert(0, yad2)
        if facebook.groups():
            sources.append(facebook)
    return sources


def run_source(src, db: DB, tg: Telegram, session, searches, recent, admin):
    """Returns True when the source was fetched successfully."""
    fail_key = f"fails:{src.NAME}"
    try:
        items = src.fetch(session)
        if not items and getattr(src, "EMPTY_IS_ERROR", False):  # an empty board: page changed or blocked
            raise RuntimeError("no listings returned")
    except Exception as e:
        fails = (db.kv_get(fail_key) or 0) + 1
        db.kv_set(fail_key, fails)
        log.exception("%s failed (%d in a row)", src.NAME, fails)
        if admin and fails == FAILS_BEFORE_WARNING:
            tg.send_text(admin, f"⚠️ המקור {src.NAME} נכשל {fails} פעמים ברצף.\n<code>{str(e)[:300]}</code>")
        return False
    db.kv_set(fail_key, 0)

    known = db.known_ids(src.NAME, [i.source_id for i in items])
    new = [i for i in items if i.source_id not in known]
    # first listings ever seen from this source are stored quietly (backfill sends the matching ones)
    bootstrap = not db.source_listings(src.NAME, days=3650, limit=1)
    log.info("%s: %d listings, %d new%s", src.NAME, len(items), len(new), " (bootstrap)" if bootstrap else "")

    for n, listing in enumerate(new):
        if src.NEEDS_DETAILS and n < MAX_DETAIL_FETCHES:
            try:
                src.enrich(session, listing)
                time.sleep(1)
            except Exception:
                log.warning("details failed for %s %s", src.NAME, listing.source_id, exc_info=True)

        group_id = dedupe.find_group(listing, recent)
        db.add_listing(listing, group_id)
        recent.insert(0, listing)
        if bootstrap:
            continue

        if group_id and db.group_alerts(listing.group_id):
            continue  # same apartment already alerted: never send it again

        alert_searches(listing, db, tg, searches, recent)

    return True


def backfill(source: str, db: DB, tg: Telegram, searches, recent):
    """A search seen for the first time gets the matching listings that already exist, up to BACKFILL_LIMIT."""
    pending = [s for s in searches if not db.kv_get(f"backfill:{s['id']}:{source}")]
    if not pending:
        return
    existing = db.source_listings(source)
    if not existing:  # nothing collected yet; try again next run
        return
    for s in pending:
        matches = [(l, m) for l in existing if (m := match(l, s))]
        matches.sort(key=lambda lm: not lm[1].full)  # full matches first, newest first within each
        sent = 0
        for listing, m in matches:
            if sent >= BACKFILL_LIMIT:
                break
            alert = db.add_alert(s["chat_id"], listing, s["id"])
            if not alert:
                continue
            try:
                median = dedupe.median_price(listing, recent)
                msg_id = tg.send_alert(s["chat_id"], listing, m, summarizer.summarize(listing, median), median, alert["id"])
                db.update("alerts", {"message_id": msg_id}, id=alert["id"])
                sent += 1
            except Exception:
                log.exception("backfill alert to %s failed", s["chat_id"])
        log.info("backfill %s search %s: %d sent", source, s["id"], sent)
        db.kv_set(f"backfill:{s['id']}:{source}", True)


def alert_searches(listing, db: DB, tg: Telegram, searches, recent):
    matches = {}
    for s in searches:
        m = match(listing, s)
        # one alert per user; prefer a search that matches fully
        if m and (s["chat_id"] not in matches or (m.full and not matches[s["chat_id"]].full)):
            matches[s["chat_id"]] = m
    if not matches:
        return
    median = dedupe.median_price(listing, recent[1:])
    summary = summarizer.summarize(listing, median)
    for chat_id, m in matches.items():
        alert = db.add_alert(chat_id, listing, m.search_id)
        if not alert:
            continue
        try:
            msg_id = tg.send_alert(chat_id, listing, m, summary, median, alert["id"])
            db.update("alerts", {"message_id": msg_id}, id=alert["id"])
        except Exception:
            log.exception("alert to %s failed", chat_id)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db = DB(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"])
    admin = os.environ.get("ADMIN_CHAT_ID")
    searches = db.active_searches()
    recent = db.recent_listings()
    session = http_session()
    log.info("%d active searches, %d recent listings", len(searches), len(recent))
    for src in enabled_sources():
        if run_source(src, db, tg, session, searches, recent, admin):
            backfill(src.NAME, db, tg, searches, recent)


if __name__ == "__main__":
    main()
