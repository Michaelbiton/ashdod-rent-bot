"""Telegram messages sent by the scraper (alerts, duplicate notes, admin warnings)."""
import html
import logging
from datetime import datetime
from urllib.parse import quote

import requests

from .matcher import Match
from .models import SOURCE_NAMES, Listing
from .normalize import IL

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, **payload) -> dict:
        r = requests.post(f"{self.base}/{method}", json=payload, timeout=30)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method}: {data.get('description')}")
        return data["result"]

    def send_text(self, chat_id, text, **extra) -> dict:
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         disable_web_page_preview=True, **extra)

    def send_alert(self, chat_id, listing: Listing, m: Match, summary: str | None,
                   median: tuple[int, str] | None, alert_id: int) -> int:
        """Album of photos (if any), then the details message with buttons. Returns the details message id."""
        photos = [p for p in listing.images if p.startswith("http")][:4]
        if len(photos) > 1:
            try:
                self.call("sendMediaGroup", chat_id=chat_id,
                          media=[{"type": "photo", "media": p} for p in photos])
            except RuntimeError as e:  # a dead image URL shouldn't block the alert
                log.warning("album failed: %s", e)
        text = format_alert(listing, m, summary, median)
        markup = keyboard(listing, alert_id)
        if len(photos) == 1 and len(text) <= 1024:  # caption limit
            try:
                return self.call("sendPhoto", chat_id=chat_id, photo=photos[0], caption=text,
                                 parse_mode="HTML", reply_markup=markup)["message_id"]
            except RuntimeError as e:
                log.warning("photo failed: %s", e)
        return self.send_text(chat_id, text, reply_markup=markup)["message_id"]


def format_when(iso: str | None, now: datetime | None = None) -> str | None:
    """ISO timestamp -> 'היום 14:05' / 'אתמול' / 'לפני 3 ימים' / '02/10/2026' (Israel time)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(IL)
    except ValueError:
        return None
    now = now or datetime.now(IL)
    days = (now.date() - dt.date()).days
    has_time = (dt.hour, dt.minute) != (0, 0)
    clock = f" {dt:%H:%M}" if has_time else ""
    if days <= 0:
        return f"היום{clock}"
    if days == 1:
        return f"אתמול{clock}"
    if days < 7:
        return f"לפני {days} ימים"
    return f"{dt:%d/%m/%Y}"


def format_dates(l: Listing, now: datetime | None = None) -> str | None:
    published, bumped = format_when(l.published_at, now), format_when(l.bumped_at, now)
    if published and bumped and bumped != published:
        return f"🗓 פורסם: {published} · 🔄 הוקפץ: {bumped}"
    if published:
        return f"🗓 פורסם: {published}"
    if bumped:
        return f"🔄 עודכן/הוקפץ: {bumped}"
    return None


def _yes_no(v: bool | None) -> str:
    return {True: "✅", False: "❌", None: "❔"}[v]


def format_alert(l: Listing, m: Match, summary: str | None, median: tuple[int, str] | None) -> str:
    e = html.escape
    where = " · ".join(filter(None, [l.neighborhood, " ".join(filter(None, [l.street, l.house_number]))]))
    lines = [f"🏠 <b>דירה חדשה{' · ' + e(where) if where else ''}</b>"]
    specs = [f"{l.rooms:g} חד׳" if l.rooms else None,
             f"קומה {l.floor}" if l.floor is not None else None,
             f"{l.sqm:g} מ״ר" if l.sqm else None]
    if any(specs):
        lines.append("🛏 " + " · ".join(s for s in specs if s))
    if l.price:
        price = f"💰 <b>{l.price:,} ₪</b>"
        if median:
            price += f"  (חציון ב{e(median[1])}: {median[0]:,} ₪)"
        lines.append(price)
    lines.append(f"{_yes_no(l.has_mamad)} ממ״ד  {_yes_no(l.has_balcony)} מרפסת  "
                 f"{_yes_no(l.has_parking)} חניה  {_yes_no(l.has_elevator)} מעלית")
    if l.is_broker is not None:
        lines.append("🧑‍💼 תיווך" if l.is_broker else "👤 פרטי")
    if l.entry_date:
        lines.append(f"📅 כניסה: {e(l.entry_date)}")
    dates = format_dates(l)
    if dates:
        lines.append(dates)
    if m.missing:
        lines.append(f"⚠️ לא צוין במודעה: {e(', '.join(m.missing))}")
    if summary:
        lines.append(f"\n🤖 {e(summary)}")
    if l.phone:
        lines.append(f"\n📞 {e(l.phone)}")
    lines.append(f"\nמקור: <a href=\"{e(l.url)}\">{SOURCE_NAMES.get(l.source, l.source)}</a>")
    return "\n".join(lines)


def whatsapp_link(l: Listing) -> str | None:
    if not l.phone:
        return None
    intl = "972" + l.phone.lstrip("0")
    msg = f"היי, ראיתי את המודעה על הדירה להשכרה{' ב' + l.street if l.street else ''}. היא עדיין רלוונטית?"
    return f"https://wa.me/{intl}?text={quote(msg)}"


def keyboard(l: Listing, alert_id: int) -> dict:
    top = [{"text": "🔗 למודעה", "url": l.url}]
    wa = whatsapp_link(l)
    if wa:
        top.append({"text": "💬 וואטסאפ למפרסם", "url": wa})
    return {"inline_keyboard": [
        top,
        [{"text": "⭐ שמור", "callback_data": f"save:{alert_id}"},
         {"text": "👎 לא רלוונטי", "callback_data": f"dismiss:{alert_id}"}],
    ]}


def format_duplicate(l: Listing) -> str:
    name = SOURCE_NAMES.get(l.source, l.source)
    price = f" · {l.price:,} ₪" if l.price else ""
    return f"🔁 אותה דירה פורסמה גם ב<a href=\"{html.escape(l.url)}\">{name}</a>{price}"
