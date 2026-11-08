"""Public Facebook groups via the Apify actor memo23/facebook-public-group-posts-scraper.

Groups are listed in config/facebook_groups.txt (one URL per line). Posts are free text, so
parse_post() pulls out price, rooms, neighborhood, amenities and phone with simple rules and
drops posts that are not apartment offers (people looking for a place, sales, etc.).
"""
import logging
import os
import re
import time
from pathlib import Path

import requests

from ..models import Listing
from ..normalize import norm_neighborhood, norm_phone, parse_floor

log = logging.getLogger(__name__)
NAME = "facebook"
NEEDS_DETAILS = False
ACTOR = "memo23~facebook-public-group-posts-scraper"
API = "https://api.apify.com/v2"
RUN_TIMEOUT = 420
GROUPS_FILE = Path(__file__).resolve().parents[2] / "config" / "facebook_groups.txt"


def groups() -> list[str]:
    if not GROUPS_FILE.exists():
        return []
    lines = (l.split("#")[0].strip() for l in GROUPS_FILE.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l.startswith("http")]


# --- parsing free text ---

_SEEKING = re.compile(r"\b(מחפש|מחפשת|מחפשים|מחפשות|דרוש|דרושה|looking for)\b")
_NOT_RENT = re.compile(r"למכירה|נמכר|מוכר(?:ת|ים)? דירה|סאבלט|חדר בדירת שותפים|לטווח קצר|ללילה|צימר")
_PRICE = re.compile(
    r"(?:מחיר|שכירות|שכ\"ד|שכ״ד)\s*[:\-]?\s*(\d{1,2}[,.]?\d{3})"
    r"|(\d{1,2}[,.]?\d{3})\s*(?:₪|ש\"ח|ש״ח|שח|שקל|ש\b|לחודש)"
)
_ROOMS = re.compile(r"(\d(?:[.,]5)?)\s*(?:וחצי\s*)?(?:חדרים|חדר|חד['׳\"]?)(?!\S*שינה)")
_HALF = re.compile(r"(\d)\s*וחצי\s*(?:חדרים|חד)")
_QUARTER = re.compile(r"(?:רובע|רובה)\s*([א-ת]{1,2})(?:['׳\"״]+([א-ת]))?")
_FLOOR = re.compile(r"קומ(?:ה|ת)\s*[:\-]?\s*(קרקע|\d{1,2})")
_PHONE = re.compile(r"(?:\+?972[-\s]?|0)5\d[-\s]?\d{3}[-\s]?\d{4}")


def _flag(text: str, positive: str) -> bool | None:
    """True if the word appears, False if it's negated ('בלי מרפסת', 'אין ממ"ד'), None if absent."""
    if re.search(rf"(?:בלי|ללא|אין)\s+{positive}", text):
        return False
    if re.search(positive, text):
        return True
    return None


def parse_price(text: str) -> int | None:
    for m in _PRICE.finditer(text):
        value = int(re.sub(r"[,.]", "", m.group(1) or m.group(2)))
        if 1000 <= value <= 30000:
            return value
    return None


def parse_post(text: str) -> dict | None:
    """Fields for a Listing, or None when the post isn't an apartment-for-rent offer."""
    t = re.sub(r"\s+", " ", text or "")
    if len(t) < 20 or _SEEKING.search(t[:80]) or _NOT_RENT.search(t):
        return None
    price = parse_price(t)
    if not price:
        return None
    half = _HALF.search(t)
    rooms = _ROOMS.search(t)
    rooms_value = float(half.group(1)) + 0.5 if half else (float(rooms.group(1).replace(",", ".")) if rooms else None)
    if rooms_value is not None and not 1 <= rooms_value <= 8:
        rooms_value = None
    if rooms_value is None and not re.search(r"דיר[הת]|להשכרה|פנטהאוז|דופלקס|יחידת דיור", t):
        return None
    q = _QUARTER.search(t)
    neighborhood = norm_neighborhood(f"רובע {q.group(1)}{q.group(2) or ''}") if q else None
    if not neighborhood:
        neighborhood = next((n for n in ("מרינה", "סיטי", "קרית איתנים", "בקמה") if n in t), None)
    phone = _PHONE.search(t)
    broker = _flag(t, r"תיווך")
    if broker is None and re.search(r"מתווך|משרד תיווך|דמי תיווך", t):
        broker = True
    if re.search(r"מבעלים|ישירות מהבעלים|מבעל הדירה", t):
        broker = False
    return dict(
        price=price,
        rooms=rooms_value,
        neighborhood=neighborhood,
        has_mamad=_flag(t, r"ממ[\"״]?ד"),
        has_balcony=_flag(t, r"מרפס(?:ת|ות)"),
        has_parking=_flag(t, r"חני(?:י)?(?:ה|ות)"),
        has_elevator=_flag(t, r"מעלית"),
        is_broker=broker,
        phone=norm_phone(phone.group()) if phone else None,
        floor=parse_floor(floor.group(1)) if (floor := _FLOOR.search(t)) else None,
    )


# --- Apify ---

def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def _images(post: dict) -> list[str]:
    out = []
    for a in post.get("attachments") or post.get("media") or post.get("images") or []:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict):
            url = _first(a, "image", "url", "src", "thumbnail", "photo_image")
            if isinstance(url, dict):
                url = url.get("uri") or url.get("url")
            if isinstance(url, str) and url.startswith("http"):
                out.append(url)
    return out[:10]


def from_post(post: dict) -> Listing | None:
    text = _first(post, "text", "message", "postText", "content") or ""
    fields = parse_post(text)
    post_id = _first(post, "postId", "id", "legacyId", "post_id")
    url = _first(post, "url", "postUrl", "link", "facebookUrl")
    if not fields or not post_id or not url:
        return None
    return Listing(
        source=NAME,
        source_id=str(post_id),
        url=url,
        title=text[:80],
        description=text[:3000],
        images=_images(post),
        published_at=_first(post, "time", "timestamp", "createdAt", "date", "creation_time"),
        **fields,
    )


def fetch(session) -> list[Listing]:
    urls = groups()
    if not urls:
        return []
    api = requests.Session()
    api.headers["Authorization"] = f"Bearer {os.environ['APIFY_TOKEN']}"
    actor_input = {
        "startUrls": [{"url": u} for u in urls],
        "viewOption": "CHRONOLOGICAL",
        "monitoringMode": True,          # only posts not returned by an earlier run
        "onlyPostsNewerThanHours": 72,   # never reach back further than three days
        "maxItems": int(os.environ.get("FB_MAX_POSTS_PER_GROUP", "30")),
    }
    r = api.post(f"{API}/acts/{ACTOR}/runs", params={"timeout": RUN_TIMEOUT}, json=actor_input, timeout=30)
    r.raise_for_status()
    run = r.json()["data"]
    deadline = time.time() + RUN_TIMEOUT + 60
    while run["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        run = api.get(f"{API}/actor-runs/{run['id']}", timeout=30).json()["data"]
    posts = api.get(f"{API}/datasets/{run['defaultDatasetId']}/items", params={"clean": "true"}, timeout=60).json()
    if run["status"] != "SUCCEEDED" and not posts:
        run_log = api.get(f"{API}/actor-runs/{run['id']}/log", timeout=30).text
        raise RuntimeError(f"apify run {run['status']}:\n{run_log[-1500:]}")
    listings = [l for l in (from_post(p) for p in posts) if l]
    log.info("facebook: %d posts from %d groups, %d apartment offers", len(posts), len(urls), len(listings))
    if posts and not listings:
        log.info("facebook sample post keys: %s", sorted(posts[0].keys())[:30])
    return listings
