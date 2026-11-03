# בוט דירות להשכרה באשדוד

בוט טלגרם שסורק פעם בשעה את **יד2**, **הומלס** ו**קומו**. כשמתפרסמת דירה שמתאימה לחיפוש שהגדרת, הוא שולח לך התראה. ההתראה כוללת תמונות, תקציר של Claude, השוואה לחציון המחיר באזור וכפתורים: שמירה, "לא רלוונטי" ווואטסאפ למפרסם.

```
GitHub Actions (כל שעה) ──► scraper/ (Python)
                               ├─ הומלס, קומו   ── ישירות מהאתרים
                               ├─ יד2           ── דרך Apify (יד2 חוסם סריקה ישירה)
                               ├─ איחוד כפילויות + התאמה לכל חיפוש
                               ├─ Claude Haiku   ── תקציר קצר
                               └─ Telegram       ── שליחת ההתראות
Supabase (Postgres חינמי) ◄──► bot/ (Cloudflare Worker) ◄── תפריטים וכפתורים בטלגרם
```

## עלויות

| שירות | עלות |
|---|---|
| GitHub Actions, Supabase, Cloudflare Workers, Telegram | חינם |
| Apify (יד2) | בערך 2–3$ לחודש, בתוך הקרדיט החינמי של 5$ |
| Claude Haiku 5.5 (תקצירים) | פחות מ-1$ לחודש |

---

## התקנה, צעד אחרי צעד

### 1. בוט טלגרם
1. בטלגרם, פתח צ'אט עם **@BotFather** ושלח `/newbot`. תן לבוט שם ושם משתמש.
2. שמור את ה-**token** שתקבל, בלי לשלוח אותו לאף אחד.
3. כדי לגלות את ה-chat id שלך, שלח הודעה ל-**@userinfobot**. המספר שיחזור הוא `ADMIN_CHAT_ID`.

### 2. Supabase (מסד הנתונים)
1. היכנס ל-[supabase.com](https://supabase.com) ← **New project** (מסלול חינמי, אזור Frankfurt).
2. **SQL Editor** ← **New query**. הדבק את כל התוכן של [supabase/schema.sql](supabase/schema.sql) ולחץ **Run**.
3. **Project Settings → API**: שמור את **Project URL** ואת המפתח **service_role**. זה המפתח הסודי, לא anon.

### 3. Apify (יד2)
1. הירשם ב-[apify.com](https://apify.com).
2. **Settings → API & Integrations**: העתק את ה-**API token**.
3. **Settings → Usage & billing**: הגדר תקרת הוצאה חודשית של 5$.
4. הסורק שבשימוש: [nice_dev/yad2-listings-scraper](https://apify.com/nice_dev/yad2-listings-scraper). הוא מחייב רק על מודעות חדשות, כי הוא זוכר מה כבר החזיר. דלג על השלב הזה אם אתה רוצה להתחיל בלי יד2: בלי `APIFY_TOKEN` הבוט פשוט מדלג על יד2.

### 4. Claude API (תקצירים, אופציונלי)
1. היכנס ל-[console.anthropic.com](https://console.anthropic.com) ← **API Keys** ← **Create Key**.
2. **Billing → Limits**: הגדר תקרה חודשית של 5$.
3. המנוי ל-Claude.ai לא מכסה את זה, זה חיוב נפרד. בלי מפתח ההתראות יעבדו כרגיל, רק בלי שורת התקציר.

### 5. הבוט ב-Cloudflare
צריך Node.js מותקן.
```bash
cd bot
npx wrangler login
```
ערוך את [bot/wrangler.toml](bot/wrangler.toml): שים את `SUPABASE_URL` ואת `ADMIN_CHAT_ID`. אחרי זה הגדר את הסודות. כל פקודה תבקש להדביק ערך:
```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN
```
```bash
npx wrangler secret put SUPABASE_SERVICE_KEY
```
```bash
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET
```
ב-`TELEGRAM_WEBHOOK_SECRET` המציא מחרוזת אקראית ארוכה (אותיות ומספרים בלבד). אחר כך:
```bash
npx wrangler deploy
```
תקבל כתובת כמו `https://ashdod-rent-bot.<שם>.workers.dev`. פתח בדפדפן פעם אחת:
`https://ashdod-rent-bot.<שם>.workers.dev/setup?key=<TELEGRAM_WEBHOOK_SECRET>`.
אמור להופיע `true`. מעכשיו שלח `/start` לבוט בטלגרם.

### 6. הסורק ב-GitHub Actions
1. צור ריפו **ציבורי** חדש ב-GitHub. בריפו ציבורי הדקות של Actions בחינם וללא הגבלה, ובפרטי יש 2,000 דקות בחודש. הסודות לא נחשפים בקוד.
2. העלה את התיקייה הזו לריפו.
3. בריפו: **Settings → Secrets and variables → Actions → New repository secret**. הוסף:

| שם | ערך |
|---|---|
| `SUPABASE_URL` | Project URL מ-Supabase |
| `SUPABASE_SERVICE_KEY` | מפתח service_role |
| `TELEGRAM_BOT_TOKEN` | ה-token מ-BotFather |
| `ADMIN_CHAT_ID` | ה-chat id שלך |
| `APIFY_TOKEN` | ה-token מ-Apify (אופציונלי) |
| `ANTHROPIC_API_KEY` | המפתח מ-Anthropic (אופציונלי) |

4. **Actions → scrape → Run workflow** כדי להריץ פעם ראשונה.
   - בפעם הראשונה שהסורק רואה חיפוש, הוא שולח את הדירות **הקיימות** שמתאימות לו: עד 10 מכל אתר, קודם ההתאמות המלאות.
   - משם והלאה מגיעות התראות רק על מודעות חדשות. גם חיפוש שנפתח בהמשך מקבל קודם את הדירות הקיימות.
5. מעכשיו זה רץ לבד כל שעה (ב-:07). GitHub לפעמים מאחר ריצות בכמה דקות.

---

## שימוש

- **/start**: תפריט ראשי. משתמש חדש שולח בקשה, ואתה (המנהל) מאשר אותה בכפתור.
- **/new**: חיפוש חדש. כל ההגדרות בכפתורים: רובעים, חדרים, מחיר, ממ"ד, מרפסת, חניה, מעלית, בלי תיווך ומילות מפתח. בסוף לוחצים **✅ הפעל**.
- **/searches**: עריכה, כיבוי או מחיקה של חיפושים. אפשר כמה חיפושים לכל משתמש.
- **/saved**: הדירות שסימנת ב-⭐.
- **/pause**: השהיית כל ההתראות, למשל אחרי שמצאת דירה 🎉

### כללי ההתאמה
- **✅ התאמה מלאה**: כל מה שביקשת ידוע ומתאים.
- **⚠️ חסר מידע**: שום דבר לא סותר את החיפוש, אבל המודעה לא מציינת חלק מהפרטים (למשל ממ"ד). ההתראה נשלחת עם הסימון "לא צוין במודעה".
- **לא נשלח**: משהו ידוע סותר את החיפוש, למשל מחיר מעל התקרה, אין ממ"ד, או מילה חסומה.
- **כפילויות**: אם אותה דירה (אותה כתובת ומחיר, או אותו טלפון) מופיעה במקור נוסף, לא תגיע התראה שנייה. במקום זה תגיע תגובה קצרה מתחת להתראה המקורית: "🔁 פורסמה גם ב…".

---

## פיתוח

```bash
pip install -r requirements.txt
```
```bash
python -m pytest
```
```bash
node --test bot/test/bot.test.mjs
```

| קובץ | מה יש בו |
|---|---|
| [scraper/main.py](scraper/main.py) | ריצה אחת: משיכה ← מודעות חדשות ← כפילויות ← התאמה ← התראה |
| [scraper/sources/](scraper/sources) | מקור לכל אתר. מקור חדש צריך `NAME`, `NEEDS_DETAILS`, `fetch()` ו-`enrich()` |
| [scraper/matcher.py](scraper/matcher.py) | כללי ההתאמה |
| [scraper/dedupe.py](scraper/dedupe.py) | זיהוי כפילויות וחציון מחיר |
| [scraper/notifier.py](scraper/notifier.py) | נוסח ההתראה והכפתורים |
| [scraper/summarizer.py](scraper/summarizer.py) | התקציר של Claude Haiku |
| [bot/src/index.js](bot/src/index.js) | הבוט: תפריטים, עורך חיפוש, כפתורי התראה ואישור משתמשים |

## מגבלות ידועות
- **מדלן כבוי**: הסורק של מדלן ב-Apify מחייב על כל מודעה בכל ריצה, גם אם כבר ראה אותה. בריצה שעתית זה יוצא בערך 6$ ומעלה לחודש.
- **קומו**: הבוט קורא רק את עמוד התוצאות הראשון (22 מודעות). לא ברור אם קומו ממיין לפי תאריך, אז מודעה חדשה שלא מופיעה בעמוד הראשון עלולה להתפספס. בקומו גם אין שדה של מרפסת או חניה, ולכן הם מזוהים רק מטקסט המודעה.
- **יד2 תלוי בשירות צד שלישי ב-Apify**. אם הוא יפסיק לעבוד, תגיע אליך הודעת אזהרה אחרי 3 כישלונות ברצף.
- **קבוצות פייסבוק**: עוד לא נבנו (שלב 3 באפיון).
