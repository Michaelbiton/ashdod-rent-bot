"""One scrape pass. Started hourly by the bot's Cloudflare cron: python -m scraper.main"""
import logging
import os
import time
from datetime import datetime, timezone

import requests

from . import dedupe, summarizer
from .db import DB
from .matcher import match
from .normalize import find_neighborhood
from .notifier import Telegram
from .sources import facebook, homeless, http_session, komo, yad2

log = logging.getLogger("scraper")
MAX_DETAIL_FETCHES = 30   # per source per run; new listings beyond this are matched on list data only
FAILS_BEFORE_WARNING = 3
BACKFILL_LIMIT = 10       # existing listings sent per source when a search is first seen
APIFY_MARGIN_USD = 0.3    # stop paid sources this close to the monthly Apify limit, before Apify blocks the account


def enabled_sources():
    sources = [homeless, komo]
    if os.environ.get("APIFY_TOKEN"):
        sources.insert(0, yad2)
        if facebook.groups():
            sources.append(facebook)
    return sources


def due(src, db: DB) -> bool:
    """Paid sources run every EVERY_HOURS (0 = never); free ones every pass."""
    every = getattr(src, "EVERY_HOURS", 1)
    if every <= 0:
        return False
    last = db.kv_get(f"last_run:{src.NAME}")
    if last:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
        if hours < every - 0.25:  # small slack: the cron fires at :07 but runs take a few minutes
            return False
    return True


def apify_budget_ok(db: DB, tg: Telegram, admin) -> bool:
    """False when this cycle's Apify usage is near the plan limit; tells the admin once per cycle."""
    try:
        r = requests.get("https://api.apify.com/v2/users/me/limits", timeout=30,
                         headers={"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"})
        r.raise_for_status()
        data = r.json()["data"]
    except Exception:
        log.warning("could not read Apify usage; running anyway", exc_info=True)
        return True
    used = data.get("current", {}).get("monthlyUsageUsd") or 0
    limit = data.get("limits", {}).get("maxMonthlyUsageUsd") or 5
    cycle_end = (data.get("monthlyUsageCycle") or {}).get("endAt", "")
    log.info("apify usage %.2f / %.2f USD (cycle ends %s)", used, limit, cycle_end[:10])
    if used < limit - APIFY_MARGIN_USD:
        return True
    if admin and db.kv_get("apify_budget_notice") != cycle_end:
        db.kv_set("apify_budget_notice", cycle_end)
        tg.send_text(admin, f"💸 התקציב החודשי של Apify כמעט נגמר ({used:.2f}$ מתוך {limit:.0f}$).\n"
                            f"יד2 ופייסבוק מושהים עד {cycle_end[:10] or 'תחילת החודש הבא'}. הומלס וקומו ממשיכים כרגיל.")
    return False


def run_source(src, db: DB, tg: Telegram, session, searches, recent, admin):
    """Returns True when the source was fetched successfully."""
    fail_key = f"fails:{src.NAME}"
    try:
        items = src.fetch(session, searches)
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

        if not listing.neighborhood:  # e.g. Yad2/Homeless left it empty but the text says "ברובע י"ז"
            listing.neighborhood = find_neighborhood(listing.text())
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
    budget_ok = None
    for src in enabled_sources():
        if getattr(src, "PAID", False):
            if not searches or not due(src, db):
                log.info("%s: skipped this pass", src.NAME)
                continue
            if budget_ok is None:
                budget_ok = apify_budget_ok(db, tg, admin)
            if not budget_ok:
                continue
            db.kv_set(f"last_run:{src.NAME}", datetime.now(timezone.utc).isoformat())
        if run_source(src, db, tg, session, searches, recent, admin):
            backfill(src.NAME, db, tg, searches, recent)


if __name__ == "__main__":
    main()
