// Run: node --test bot/test
// Drives the Worker through a full chat flow against an in-memory fake of Supabase (PostgREST) and Telegram.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { NEIGHBORHOODS, parsePrice, parseKeywords } from "../src/index.js";

const env = {
  TELEGRAM_BOT_TOKEN: "T",
  TELEGRAM_WEBHOOK_SECRET: "S",
  SUPABASE_URL: "https://db.test",
  SUPABASE_SERVICE_KEY: "K",
  ADMIN_CHAT_ID: "1",
};

const db = { users: [], searches: [], alerts: [], listings: [] };
const sent = [];
let nextId = 1;

function filterRows(rows, params) {
  return rows.filter((r) =>
    [...params].every(([k, v]) => {
      if (["select", "order", "limit"].includes(k)) return true;
      if (v.startsWith("eq.")) return String(r[k]) === v.slice(3);
      if (v.startsWith("in.(")) return v.slice(4, -1).split(",").includes(String(r[k]));
      return true;
    }));
}

globalThis.fetch = async (url, opts = {}) => {
  const u = new URL(url);
  const body = opts.body ? JSON.parse(opts.body) : undefined;
  if (u.hostname === "api.telegram.org") {
    sent.push({ method: u.pathname.split("/").pop(), ...body });
    return Response.json({ ok: true, result: { message_id: 500 + sent.length } });
  }
  const table = u.pathname.split("/").pop();
  const rows = db[table];
  const matched = filterRows(rows, u.searchParams);
  let out;
  if (opts.method === "GET") {
    out = matched.map((r) => ({ ...r }));
    if ((u.searchParams.get("select") || "").includes("listings(")) {
      out = out.map((a) => ({ ...a, listings: db.listings.find((l) => l.id === a.listing_id) }));
    }
  } else if (opts.method === "POST") {
    const defaults = table === "searches"
      ? { active: false, neighborhoods: [], exclude_keywords: [], include_keywords: [], rooms_min: null,
          rooms_max: null, price_min: null, price_max: null, need_mamad: false, need_balcony: false,
          need_parking: false, need_elevator: false, need_photo: false, no_broker: false }
      : { approved: false, paused: false, state: null, state_data: null };
    const row = { id: nextId++, ...defaults, ...body };
    rows.push(row);
    out = [row];
  } else if (opts.method === "PATCH") {
    matched.forEach((r) => Object.assign(r, body));
    out = matched;
  } else if (opts.method === "DELETE") {
    db[table] = rows.filter((r) => !matched.includes(r));
    out = [];
  }
  return new Response(JSON.stringify(out), { status: 200 });
};

const post = (update, secret = "S") =>
  worker.fetch(new Request("https://bot.test/webhook", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": secret },
    body: JSON.stringify(update),
  }), env);

const msg = (chatId, text) => post({ message: { chat: { id: chatId, type: "private" }, from: { id: chatId, first_name: `u${chatId}` }, text } });
const click = (chatId, data) => post({ callback_query: { id: "cb", from: { id: chatId }, data, message: { chat: { id: chatId }, message_id: 9, text: "x", reply_markup: { inline_keyboard: [[{ text: "🔗", url: "https://x" }], []] } } } });
const last = (method) => [...sent].reverse().find((m) => m.method === method);

test("rejects requests without the webhook secret", async () => {
  const r = await post({ message: {} }, "wrong");
  assert.equal(r.status, 403);
});

test("price and keyword parsing", () => {
  assert.deepEqual(parsePrice("4,000-6,500"), { price_min: 4000, price_max: 6500 });
  assert.deepEqual(parsePrice("עד 6000 ₪"), { price_min: null, price_max: 6000 });
  assert.deepEqual(parsePrice("מ 3500"), { price_min: 3500, price_max: null });
  assert.deepEqual(parsePrice("-"), { price_min: null, price_max: null });
  assert.equal(parsePrice("זול"), null);
  assert.deepEqual(parseKeywords("שותף, סאבלט, +גינה"), { include_keywords: ["גינה"], exclude_keywords: ["שותף", "סאבלט"] });
});

test("full chat flow", async () => {
  await msg(1, "/start");
  assert.equal(db.users[0].approved, true, "admin is auto-approved");

  await msg(2, "/start");
  assert.equal(db.users.find((u) => u.chat_id === 2).approved, false);
  const req = sent.find((m) => m.chat_id === "1" && m.text?.includes("מבקש/ת גישה"));
  assert.ok(req, "admin got an approval request");
  assert.equal(req.reply_markup.inline_keyboard[0][0].callback_data, "approve:2");

  await msg(2, "/new");
  assert.equal(db.searches.length, 0, "unapproved users can't create searches");

  await click(2, "approve:2");
  assert.equal(db.users.find((u) => u.chat_id === 2).approved, false, "only the admin can approve");
  await click(1, "approve:2");
  assert.equal(db.users.find((u) => u.chat_id === 2).approved, true);

  await msg(2, "/new");
  const s = db.searches[0];
  assert.equal(s.chat_id, 2);
  assert.ok(last("sendMessage").text.includes("החיפוש שלי"));

  await click(2, `s:${s.id}:t:need_mamad`);
  assert.equal(s.need_mamad, true);
  await click(2, `s:${s.id}:t:need_photo`);
  assert.equal(s.need_photo, true);
  const idx = NEIGHBORHOODS.indexOf("רובע טו");
  await click(2, `s:${s.id}:nbt:${idx}`);
  assert.deepEqual(s.neighborhoods, ["רובע טו"]);
  await click(2, `s:${s.id}:rmin:3`);
  await click(2, `s:${s.id}:rmax:4`);
  assert.deepEqual([s.rooms_min, s.rooms_max], [3, 4]);

  await click(2, `s:${s.id}:price`);
  assert.equal(db.users.find((u) => u.chat_id === 2).state, "price");
  await msg(2, "זה לא מחיר");
  assert.ok(last("sendMessage").text.includes("לא הבנתי"));
  await msg(2, "4,000-6,500");
  assert.deepEqual([s.price_min, s.price_max], [4000, 6500]);
  assert.equal(db.users.find((u) => u.chat_id === 2).state, null);

  await click(2, `s:${s.id}:kw`);
  await msg(2, "שותף, +גינה");
  assert.deepEqual(s.exclude_keywords, ["שותף"]);

  await click(2, `s:${s.id}:on`);
  assert.equal(s.active, true);
  const editor = last("editMessageText").text;
  assert.ok(editor.includes("🟢 פעיל") && editor.includes("4,000–6,500 ₪") && editor.includes("ממ״ד"));

  await click(1, `s:${s.id}:t:need_balcony`);
  assert.equal(s.need_balcony, false, "another user can't edit this search");

  // alert buttons
  db.listings.push({ id: 77, url: "https://www.homeless.co.il/rent/viewad,1.aspx", neighborhood: "רובע טו", street: "תל חי", rooms: 3, price: 5500 });
  db.alerts.push({ id: 5, chat_id: 2, listing_id: 77, status: "sent" });
  await click(1, "save:5");
  assert.equal(db.alerts[0].status, "sent", "can't save someone else's alert");
  await click(2, "save:5");
  assert.equal(db.alerts[0].status, "saved");
  await msg(2, "/saved");
  assert.ok(last("sendMessage").text.includes("תל חי"));

  await click(2, `s:${s.id}:del`);
  assert.equal(db.searches.length, 0);
});
