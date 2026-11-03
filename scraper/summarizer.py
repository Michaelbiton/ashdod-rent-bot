"""One-or-two line Hebrew take on a listing, written by Claude Haiku. Optional: skipped without ANTHROPIC_API_KEY."""
import json
import logging
import os

import anthropic

from .models import Listing

log = logging.getLogger(__name__)
MODEL = "claude-haiku-5-5"

SYSTEM = (
    "אתה עוזר למחפשי דירות להשכרה באשדוד. תקבל מודעה כ-JSON ומחיר חציוני של דירות דומות. "
    "כתוב בעברית משפט או שניים בלבד, בלי כותרת ובלי רשימות: מה בולט בדירה, "
    "האם המחיר זול, סביר או יקר ביחס לחציון, ודגלים אדומים אם יש "
    "(מחיר נמוך באופן חשוד, מודעה שנראית כמו תיווך למרות שסומנה כפרטית, פרטים סותרים). "
    "אם אין מה להגיד, כתוב משפט קצר אחד."
)

_client = None


def summarize(listing: Listing, median: tuple[int, str] | None) -> str | None:
    global _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    _client = _client or anthropic.Anthropic(max_retries=2, timeout=30.0)
    data = {k: v for k, v in listing.to_row().items() if v not in (None, [], "") and k not in ("images", "url")}
    data["description"] = (data.get("description") or "")[:1500]
    prompt = json.dumps(
        {"listing": data, "median_price": {"price": median[0], "area": median[1]} if median else None},
        ensure_ascii=False,
    )
    try:
        resp = _client.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        log.warning("summary failed: %s", e)
        return None
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or None
