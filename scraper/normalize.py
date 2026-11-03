import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IL = ZoneInfo("Asia/Jerusalem")

# Keep in sync with NEIGHBORHOODS in bot/src/index.js
QUARTERS = ["א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט", "י", "יא", "יב", "יג", "טו", "טז", "יז"]
NEIGHBORHOODS = [f"רובע {q}" for q in QUARTERS] + ["מרינה", "סיטי", "קרית איתנים", "בקמה"]

_QUOTES = re.compile(r"[\"'״׳`]|&quot;|&#39;")


def norm_neighborhood(s: str | None) -> str | None:
    """'רובע ט''ו' / 'רובע ט"ו' / 'רובה ב' -> 'רובע טו' ; 'הסיטי' -> 'סיטי'."""
    if not s:
        return None
    t = re.sub(r"\s+", " ", _QUOTES.sub("", s)).strip()
    m = re.match(r"^(?:רובע|רובה)\s*([א-ת]{1,2})$", t)
    if m:
        return f"רובע {m.group(1)}"
    if "מרינה" in t:
        return "מרינה"
    if "סיטי" in t:
        return "סיטי"
    if "איתנים" in t:
        return "קרית איתנים"
    return t or None


def split_address(s: str | None) -> tuple[str | None, str | None]:
    """'שד הרצל 48' -> ('שד הרצל', '48')."""
    street = norm_street(s)
    if not street:
        return None, None
    m = re.match(r"^(.*?\D)\s+(\d+[א-ת]?)$", street)
    return (m.group(1), m.group(2)) if m else (street, None)


def parse_int(s) -> int | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def parse_float(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"\d+(?:\.\d+)?", str(s))
    return float(m.group()) if m else None


def parse_floor(s) -> int | None:
    if s is None:
        return None
    if "קרקע" in str(s):
        return 0
    return parse_int(str(s).split("מתוך")[0])


def norm_phone(s: str | None) -> str | None:
    if not s:
        return None
    d = re.sub(r"\D", "", s)
    if d.startswith("972"):
        d = "0" + d[3:]
    return d if len(d) >= 9 else None


def parse_il_date(s: str | None) -> str | None:
    """'03/11/2026' -> ISO date (midnight, Israel time)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    return datetime(y, mo, d, tzinfo=IL).isoformat()


_UNITS = [("דק", timedelta(minutes=1)), ("שע", timedelta(hours=1)), ("יום", timedelta(days=1)),
          ("ימים", timedelta(days=1)), ("שבוע", timedelta(weeks=1)), ("חודש", timedelta(days=30))]


def parse_ago(s: str | None, now: datetime | None = None) -> str | None:
    """'עודכן לפני: 2 שעות' / 'לפני שעה' / 'לפני 3 ימים' -> ISO timestamp."""
    m = re.search(r"לפני:?\s*(\d+)?\s*(\S+)", s or "")
    if not m:
        return None
    n = int(m.group(1) or 1)
    unit = next((delta for key, delta in _UNITS if m.group(2).startswith(key)), None)
    if unit is None:
        return None
    now = now or datetime.now(IL)
    return (now - n * unit).replace(second=0, microsecond=0).isoformat()


def norm_street(s: str | None) -> str | None:
    if not s or "לא צוין" in s:
        return None
    t = _QUOTES.sub("", s)
    t = re.sub(r"^(רחוב|רח)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t) or None
