// Telegram bot for the Ashdod rent alerts: menus for managing searches, alert buttons, admin approvals.
// Runs as a Cloudflare Worker. Telegram calls POST /webhook; open GET /setup?key=<secret> once to register it.

// Keep in sync with NEIGHBORHOODS in scraper/normalize.py
const QUARTERS = ["א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט", "י", "יא", "יב", "יג", "טו", "טז", "יז"];
export const NEIGHBORHOODS = [...QUARTERS.map((q) => `רובע ${q}`), "מרינה", "סיטי", "קרית איתנים", "בקמה"];
const ROOM_OPTIONS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6];
const TOGGLES = {
  need_mamad: "ממ״ד",
  need_balcony: "מרפסת",
  need_parking: "חניה",
  need_elevator: "מעלית",
  no_broker: "בלי תיווך",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/setup") return setup(url, env);
    if (url.pathname === "/scrape") {
      if (url.searchParams.get("key") !== env.TELEGRAM_WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
      return new Response(`github dispatch: ${await triggerScrape(env)}`);
    }
    if (url.pathname !== "/webhook" || request.method !== "POST") return new Response("not found", { status: 404 });
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const update = await request.json();
    try {
      if (update.message) await onMessage(update.message, env);
      else if (update.callback_query) await onCallback(update.callback_query, env);
    } catch (e) {
      console.error(e.stack || e);
    }
    return new Response("ok"); // always 200, or Telegram retries the update forever
  },

  // Cloudflare cron (wrangler.toml [triggers]): GitHub's own schedule drifts by hours, so we start the scrape here.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerScrape(env));
  },
};

async function triggerScrape(env) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/scrape.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ashdod-rent-bot",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (!r.ok) console.error("scrape dispatch failed", r.status, await r.text());
  return r.status;
}

async function setup(url, env) {
  if (url.searchParams.get("key") !== env.TELEGRAM_WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
  const hook = await tg(env, "setWebhook", {
    url: `${url.origin}/webhook`,
    secret_token: env.TELEGRAM_WEBHOOK_SECRET,
    allowed_updates: ["message", "callback_query"],
  });
  await tg(env, "setMyCommands", {
    commands: [
      { command: "start", description: "תפריט ראשי" },
      { command: "new", description: "חיפוש חדש" },
      { command: "searches", description: "החיפושים שלי" },
      { command: "saved", description: "דירות ששמרתי" },
      { command: "pause", description: "השהיה / חידוש התראות" },
    ],
  });
  return Response.json(hook);
}

// ---------- Telegram & Supabase ----------

async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!data.ok && !String(data.description).includes("message is not modified")) {
    console.error(method, data.description);
  }
  return data.result;
}

const send = (env, chat_id, text, keyboard) =>
  tg(env, "sendMessage", {
    chat_id, text, parse_mode: "HTML", disable_web_page_preview: true,
    ...(keyboard && { reply_markup: { inline_keyboard: keyboard } }),
  });

const edit = (env, chat_id, message_id, text, keyboard) =>
  tg(env, "editMessageText", {
    chat_id, message_id, text, parse_mode: "HTML", disable_web_page_preview: true,
    ...(keyboard && { reply_markup: { inline_keyboard: keyboard } }),
  });

async function sb(env, method, path, body, prefer = "return=representation") {
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: env.SUPABASE_SERVICE_KEY,
      Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: prefer,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`supabase ${method} ${path}: ${r.status} ${await r.text()}`);
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}

const getUser = async (env, chatId) => (await sb(env, "GET", `users?chat_id=eq.${chatId}`))[0];
const setUser = (env, chatId, values) => sb(env, "PATCH", `users?chat_id=eq.${chatId}`, values);
const getSearch = async (env, chatId, id) =>
  (await sb(env, "GET", `searches?id=eq.${Number(id)}&chat_id=eq.${chatId}`))[0];
const setSearch = (env, chatId, id, values) =>
  sb(env, "PATCH", `searches?id=eq.${Number(id)}&chat_id=eq.${chatId}`, values);

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const isAdmin = (env, chatId) => String(chatId) === String(env.ADMIN_CHAT_ID);

// ---------- Messages ----------

async function onMessage(msg, env) {
  if (msg.chat.type !== "private" || !msg.text) return;
  const chatId = msg.chat.id;
  const text = msg.text.trim();
  let user = await getUser(env, chatId);

  if (!user) {
    const admin = isAdmin(env, chatId);
    [user] = await sb(env, "POST", "users", {
      chat_id: chatId, first_name: msg.from.first_name, username: msg.from.username,
      approved: admin, is_admin: admin,
    });
    if (!admin && env.ADMIN_CHAT_ID) {
      const who = `${esc(msg.from.first_name)}${msg.from.username ? ` (@${esc(msg.from.username)})` : ""}`;
      await send(env, env.ADMIN_CHAT_ID, `👋 ${who} מבקש/ת גישה לבוט הדירות.`, [[
        { text: "✅ אשר", callback_data: `approve:${chatId}` },
        { text: "❌ דחה", callback_data: `deny:${chatId}` },
      ]]);
    }
  }
  if (!user.approved) {
    return send(env, chatId, "הבקשה שלך נשלחה למנהל הבוט. אעדכן אותך כשהיא תאושר 🙏");
  }

  if (text.startsWith("/")) {
    if (user.state) await setUser(env, chatId, { state: null, state_data: null });
    const cmd = text.split(/[\s@]/)[0];
    if (cmd === "/new") return newSearch(env, chatId);
    if (cmd === "/searches") return listSearches(env, chatId);
    if (cmd === "/saved") return listSaved(env, chatId);
    if (cmd === "/pause") return togglePause(env, chatId, user);
    return mainMenu(env, chatId, user);
  }

  if (user.state) return onStateReply(env, chatId, user, text);
  return mainMenu(env, chatId, user);
}

function mainMenu(env, chatId, user, messageId) {
  const text =
    "🏠 <b>בוט הדירות של אשדוד</b>\n\n" +
    "אני סורק את יד2, הומלס וקומו פעם בשעה ושולח לך כל דירה חדשה שמתאימה לחיפוש שלך.\n" +
    (user.paused ? "\n⏸ <b>ההתראות מושהות כרגע.</b>" : "");
  const kb = [
    [{ text: "➕ חיפוש חדש", callback_data: "menu:new" }, { text: "📋 החיפושים שלי", callback_data: "menu:list" }],
    [
      { text: "⭐ שמורים", callback_data: "menu:saved" },
      { text: user.paused ? "▶️ חידוש התראות" : "⏸ השהיית התראות", callback_data: "menu:pause" },
    ],
  ];
  return messageId ? edit(env, chatId, messageId, text, kb) : send(env, chatId, text, kb);
}

async function togglePause(env, chatId, user, messageId) {
  await setUser(env, chatId, { paused: !user.paused });
  return mainMenu(env, chatId, { ...user, paused: !user.paused }, messageId);
}

async function newSearch(env, chatId, messageId) {
  const count = (await sb(env, "GET", `searches?chat_id=eq.${chatId}&select=id`)).length;
  const [s] = await sb(env, "POST", "searches", { chat_id: chatId, name: count ? `חיפוש ${count + 1}` : "החיפוש שלי" });
  return showEditor(env, chatId, s, messageId);
}

async function listSearches(env, chatId, messageId) {
  const rows = await sb(env, "GET", `searches?chat_id=eq.${chatId}&order=id`);
  const kb = rows.map((s) => [{ text: `${s.active ? "🟢" : "⚪️"} ${s.name}`, callback_data: `s:${s.id}:open` }]);
  kb.push([{ text: "➕ חיפוש חדש", callback_data: "menu:new" }, { text: "⬅️ תפריט", callback_data: "menu:home" }]);
  const text = rows.length ? "📋 <b>החיפושים שלך</b>\n🟢 פעיל · ⚪️ כבוי" : "עוד אין לך חיפושים.";
  return messageId ? edit(env, chatId, messageId, text, kb) : send(env, chatId, text, kb);
}

async function listSaved(env, chatId, messageId) {
  const rows = await sb(env, "GET",
    `alerts?chat_id=eq.${chatId}&status=eq.saved&order=created_at.desc&limit=20` +
    `&select=id,listings(url,neighborhood,street,rooms,price)`);
  const lines = rows.map((a, i) => {
    const l = a.listings;
    const desc = [l.neighborhood, l.street, l.rooms && `${l.rooms} חד׳`, l.price && `${l.price.toLocaleString("en-US")} ₪`]
      .filter(Boolean).join(" · ");
    return `${i + 1}. <a href="${esc(l.url)}">${esc(desc || "מודעה")}</a>`;
  });
  const text = rows.length ? `⭐ <b>דירות ששמרת</b>\n\n${lines.join("\n")}` : "עוד לא שמרת דירות. לחץ ⭐ על התראה כדי לשמור.";
  const kb = [[{ text: "⬅️ תפריט", callback_data: "menu:home" }]];
  return messageId ? edit(env, chatId, messageId, text, kb) : send(env, chatId, text, kb);
}

// ---------- Search editor ----------

function rangeText(lo, hi, unit = "") {
  const f = (v) => Number(v).toLocaleString("en-US");
  if (lo == null && hi == null) return "לא משנה";
  if (lo == null) return `עד ${f(hi)}${unit}`;
  if (hi == null) return `מ-${f(lo)}${unit}`;
  return `${f(lo)}–${f(hi)}${unit}`;
}

function editorText(s) {
  const must = Object.entries(TOGGLES).filter(([k]) => k !== "no_broker" && s[k]).map(([, v]) => v);
  const lines = [
    `🔎 <b>${esc(s.name)}</b> ${s.active ? "🟢 פעיל" : "⚪️ כבוי"}`,
    "",
    `📍 רובעים: ${s.neighborhoods.length ? esc(s.neighborhoods.join(", ")) : "כל אשדוד"}`,
    `🛏 חדרים: ${rangeText(s.rooms_min, s.rooms_max)}`,
    `💰 מחיר: ${rangeText(s.price_min, s.price_max, " ₪")}`,
    `✅ חובה: ${must.length ? must.join(", ") : "—"}`,
    `🧑‍💼 תיווך: ${s.no_broker ? "בלי תיווך בלבד" : "לא משנה"}`,
  ];
  if (s.exclude_keywords.length) lines.push(`🚫 לחסום: ${esc(s.exclude_keywords.join(", "))}`);
  if (s.include_keywords.length) lines.push(`➕ לחייב: ${esc(s.include_keywords.join(", "))}`);
  if (!s.active) lines.push("", "כשתסיים, לחץ <b>✅ הפעל</b> כדי להתחיל לקבל התראות.");
  return lines.join("\n");
}

function editorKeyboard(s) {
  const b = (text, action) => ({ text, callback_data: `s:${s.id}:${action}` });
  const t = (key) => b(`${s[key] ? "✅" : "▫️"} ${TOGGLES[key]}`, `t:${key}`);
  return [
    [b("📍 רובעים", "nb"), b("🛏 חדרים", "rooms"), b("💰 מחיר", "price")],
    [t("need_mamad"), t("need_balcony")],
    [t("need_parking"), t("need_elevator")],
    [t("no_broker"), b("🔤 מילות מפתח", "kw")],
    [b("✏️ שם", "name"), s.active ? b("⏸ כבה", "off") : b("✅ הפעל", "on"), b("🗑 מחק", "del")],
    [{ text: "⬅️ החיפושים שלי", callback_data: "menu:list" }],
  ];
}

const showEditor = (env, chatId, s, messageId) =>
  messageId ? edit(env, chatId, messageId, editorText(s), editorKeyboard(s))
            : send(env, chatId, editorText(s), editorKeyboard(s));

function neighborhoodKeyboard(s) {
  const rows = [];
  NEIGHBORHOODS.forEach((n, i) => {
    if (i % 3 === 0) rows.push([]);
    rows[rows.length - 1].push({ text: `${s.neighborhoods.includes(n) ? "✅ " : ""}${n}`, callback_data: `s:${s.id}:nbt:${i}` });
  });
  rows.push([
    { text: "🌍 כל אשדוד", callback_data: `s:${s.id}:nball` },
    { text: "✔️ סיום", callback_data: `s:${s.id}:open` },
  ]);
  return rows;
}

function roomsKeyboard(s, stage) {
  const options = stage === "min" ? ROOM_OPTIONS : ROOM_OPTIONS.filter((r) => s.rooms_min == null || r >= s.rooms_min);
  const rows = [];
  options.forEach((r, i) => {
    if (i % 5 === 0) rows.push([]);
    rows[rows.length - 1].push({ text: String(r), callback_data: `s:${s.id}:r${stage}:${r}` });
  });
  rows.push([{ text: stage === "min" ? "בלי מינימום" : "בלי מקסימום", callback_data: `s:${s.id}:r${stage}:any` }]);
  return rows;
}

async function onSearchAction(env, chatId, messageId, id, action, arg, cbId) {
  let s = await getSearch(env, chatId, id);
  if (!s) return listSearches(env, chatId, messageId);
  const save = async (values) => { [s] = await setSearch(env, chatId, id, values); };

  switch (action) {
    case "open":
      break;
    case "t":
      if (!(arg in TOGGLES)) return;
      await save({ [arg]: !s[arg] });
      break;
    case "nb":
      return edit(env, chatId, messageId, "📍 בחר רובעים (אפשר כמה). בלי בחירה = כל אשדוד.", neighborhoodKeyboard(s));
    case "nbt": {
      const n = NEIGHBORHOODS[Number(arg)];
      if (!n) return;
      const list = s.neighborhoods.includes(n) ? s.neighborhoods.filter((x) => x !== n) : [...s.neighborhoods, n];
      await save({ neighborhoods: list });
      return edit(env, chatId, messageId, "📍 בחר רובעים (אפשר כמה). בלי בחירה = כל אשדוד.", neighborhoodKeyboard(s));
    }
    case "nball":
      await save({ neighborhoods: [] });
      break;
    case "rooms":
      return edit(env, chatId, messageId, "🛏 מינימום חדרים:", roomsKeyboard(s, "min"));
    case "rmin":
      await save({ rooms_min: arg === "any" ? null : Number(arg), rooms_max: null });
      return edit(env, chatId, messageId, "🛏 מקסימום חדרים:", roomsKeyboard(s, "max"));
    case "rmax":
      await save({ rooms_max: arg === "any" ? null : Number(arg) });
      break;
    case "price":
    case "kw":
    case "name": {
      const prompts = {
        price: "💰 שלח טווח מחירים לחודש, למשל:\n<code>4000-6500</code> · <code>עד 6000</code> · <code>מ 3500</code>\nכדי לבטל סינון לפי מחיר שלח <code>-</code>",
        kw: "🔤 שלח מילים מופרדות בפסיק.\nמילה רגילה = לחסום מודעות שמכילות אותה. מילה עם + = לחייב אותה.\nלמשל: <code>שותף, סאבלט, +גינה</code>\nלניקוי שלח <code>-</code>",
        name: "✏️ שלח שם לחיפוש:",
      };
      await setUser(env, chatId, { state: action, state_data: { search_id: s.id } });
      return send(env, chatId, prompts[action]);
    }
    case "on":
      await save({ active: true });
      await tg(env, "answerCallbackQuery", { callback_query_id: cbId, text: "החיפוש פעיל! בסריקה הקרובה (תוך שעה לכל היותר) תקבל את הדירות הקיימות שמתאימות, ומשם כל דירה חדשה.", show_alert: true });
      break;
    case "off":
      await save({ active: false });
      break;
    case "del":
      await sb(env, "DELETE", `searches?id=eq.${s.id}&chat_id=eq.${chatId}`);
      return listSearches(env, chatId, messageId);
  }
  return showEditor(env, chatId, s, messageId);
}

function parsePrice(text) {
  const t = text.replace(/[,₪]/g, "").replace(/ש"?ח/g, "").trim();
  if (t === "-") return { price_min: null, price_max: null };
  const nums = (t.match(/\d+/g) || []).map(Number);
  if (nums.length >= 2) return { price_min: Math.min(...nums), price_max: Math.max(...nums) };
  if (nums.length === 1) {
    if (/^(מ|מעל|החל)/.test(t)) return { price_min: nums[0], price_max: null };
    return { price_min: null, price_max: nums[0] };
  }
  return null;
}

function parseKeywords(text) {
  if (text.trim() === "-") return { exclude_keywords: [], include_keywords: [] };
  const words = text.split(/[,\n،]/).map((w) => w.trim()).filter(Boolean);
  return {
    include_keywords: words.filter((w) => w.startsWith("+")).map((w) => w.slice(1).trim()).filter(Boolean),
    exclude_keywords: words.filter((w) => !w.startsWith("+")),
  };
}

async function onStateReply(env, chatId, user, text) {
  const id = user.state_data?.search_id;
  let values;
  if (user.state === "price") values = parsePrice(text);
  else if (user.state === "kw") values = parseKeywords(text);
  else if (user.state === "name") values = { name: text.slice(0, 40) };
  if (!values) return send(env, chatId, "לא הבנתי 🙃 נסה שוב, למשל <code>4000-6500</code>");
  await setUser(env, chatId, { state: null, state_data: null });
  const [s] = await setSearch(env, chatId, id, values);
  if (!s) return mainMenu(env, chatId, user);
  return showEditor(env, chatId, s);
}

// ---------- Callbacks ----------

async function onCallback(cb, env) {
  const chatId = cb.message?.chat.id;
  const messageId = cb.message?.message_id;
  const [kind, a, b, c] = (cb.data || "").split(":");
  let answer = "";

  if (kind === "approve" || kind === "deny") {
    if (!isAdmin(env, cb.from.id)) return tg(env, "answerCallbackQuery", { callback_query_id: cb.id });
    if (kind === "approve") {
      await setUser(env, a, { approved: true });
      await send(env, a, "✅ אושרת! שלח /new כדי להגדיר חיפוש ראשון.");
    } else {
      await sb(env, "DELETE", `users?chat_id=eq.${Number(a)}`);
    }
    await edit(env, chatId, messageId, `${cb.message.text}\n\n${kind === "approve" ? "✅ אושר" : "❌ נדחה"}`);
    return tg(env, "answerCallbackQuery", { callback_query_id: cb.id });
  }

  const user = await getUser(env, chatId);
  if (!user?.approved) return tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: "ממתין לאישור" });

  if (kind === "menu") {
    if (a === "new") await newSearch(env, chatId, messageId);
    else if (a === "list") await listSearches(env, chatId, messageId);
    else if (a === "saved") await listSaved(env, chatId, messageId);
    else if (a === "pause") await togglePause(env, chatId, user, messageId);
    else await mainMenu(env, chatId, user, messageId);
  } else if (kind === "s") {
    await onSearchAction(env, chatId, messageId, a, b, c, cb.id);
    if (b === "on") return; // already answered with a popup
  } else if (kind === "save" || kind === "dismiss") {
    const status = kind === "save" ? "saved" : "dismissed";
    await sb(env, "PATCH", `alerts?id=eq.${Number(a)}&chat_id=eq.${chatId}`, { status }, "return=minimal");
    const rows = cb.message.reply_markup?.inline_keyboard || [];
    if (kind === "dismiss") {
      // keep only the link row, and mark the alert as dismissed
      await tg(env, "editMessageReplyMarkup", { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: [rows[0] || []] } });
      answer = "סומן כלא רלוונטי 👎";
    } else {
      const kb = [rows[0] || [], [{ text: "⭐ נשמר", callback_data: "noop" }, { text: "👎 לא רלוונטי", callback_data: `dismiss:${a}` }]];
      await tg(env, "editMessageReplyMarkup", { chat_id: chatId, message_id: messageId, reply_markup: { inline_keyboard: kb } });
      answer = "נשמר ⭐ (/saved)";
    }
  }
  return tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: answer });
}

export { parsePrice, parseKeywords, editorText };
