"""Minimal Supabase (PostgREST) client using the service-role key."""
from datetime import datetime, timedelta, timezone

import requests

from .models import Listing


class DB:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.s = requests.Session()
        self.s.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    def _req(self, method, table, params=None, json=None, prefer=None):
        headers = {"Prefer": prefer} if prefer else {}
        r = self.s.request(method, f"{self.base}/{table}", params=params, json=json, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json() if r.content else None

    def select(self, table, **params):
        return self._req("GET", table, params=params)

    def insert(self, table, rows):
        return self._req("POST", table, json=rows, prefer="return=representation")

    def update(self, table, values, **match):
        params = {k: f"eq.{v}" for k, v in match.items()}
        return self._req("PATCH", table, params=params, json=values, prefer="return=representation")

    # --- domain helpers ---

    def kv_get(self, key):
        rows = self.select("kv", key=f"eq.{key}", select="value")
        return rows[0]["value"] if rows else None

    def kv_set(self, key, value):
        self._req("POST", "kv", json={"key": key, "value": value},
                  prefer="resolution=merge-duplicates,return=minimal")

    def active_searches(self) -> list[dict]:
        users = self.select("users", approved="eq.true", paused="eq.false", select="chat_id")
        ids = [u["chat_id"] for u in users]
        if not ids:
            return []
        return self.select("searches", active="eq.true", chat_id=f"in.({','.join(map(str, ids))})")

    def recent_listings(self, days=30) -> list[Listing]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.select("listings", first_seen=f"gte.{since}", order="first_seen.desc", limit=5000,
                           select="id,group_id,source,source_id,url,neighborhood,street,house_number,"
                                  "rooms,floor,price,phone,description")
        return [Listing.from_row(r) for r in rows]

    def source_listings(self, source: str, days=14, limit=200) -> list[Listing]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.select("listings", source=f"eq.{source}", first_seen=f"gte.{since}",
                           order="first_seen.desc", limit=limit)
        return [Listing.from_row(r) for r in rows]

    def known_ids(self, source: str, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        quoted = ",".join(f'"{i}"' for i in ids)
        rows = self.select("listings", source=f"eq.{source}", source_id=f"in.({quoted})", select="source_id")
        return {r["source_id"] for r in rows}

    def add_listing(self, listing: Listing, group_id: int | None) -> Listing:
        row = self.insert("listings", [{**listing.to_row(), "group_id": group_id}])[0]
        listing.id = row["id"]
        listing.group_id = group_id or row["id"]
        if not group_id:
            self.update("listings", {"group_id": listing.id}, id=listing.id)
        return listing

    def group_alerts(self, group_id: int) -> list[dict]:
        return self.select("alerts", group_id=f"eq.{group_id}", select="id,chat_id,message_id,status")

    def add_alert(self, chat_id, listing: Listing, search_id) -> dict | None:
        try:
            return self.insert("alerts", [{"chat_id": chat_id, "group_id": listing.group_id,
                                           "listing_id": listing.id, "search_id": search_id}])[0]
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 409:  # already alerted this user
                return None
            raise
