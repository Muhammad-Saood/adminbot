# main.py - Backend FastAPI server for Telegram Mini App with Monetag
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")  # e.g., https://your-app.koyeb.app
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"  # Monetag data-zone

app = FastAPI()

# ---------------- DATABASE ----------------
def get_db_connection():
    return psycopg2.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
        cursor_factory=RealDictCursor
    )

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    points DECIMAL(10, 2) DEFAULT 0,
                    daily_ads_watched INTEGER DEFAULT 0,
                    last_ad_date DATE,
                    invited_friends INTEGER DEFAULT 0,
                    binance_id TEXT,
                    invited_by BIGINT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

def get_user_points(user_id: int) -> float:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return float(result["points"]) if result else 0.0

# ---------------- USER DATA ----------------
def get_or_create_user(user_id: int, invited_by: Optional[int] = None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = cur.fetchone()
            if not user:
                cur.execute(
                    "INSERT INTO users (user_id, invited_by) VALUES (%s, %s)",
                    (user_id, invited_by)
                )
                conn.commit()
                return {"user_id": user_id, "points": 0.0, "daily_ads_watched": 0,
                        "last_ad_date": None, "invited_friends": 0, "binance_id": None, "invited_by": invited_by}
            return dict(user)

def update_points(user_id: int, points: float):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points = points + %s WHERE user_id = %s", (points, user_id))
            conn.commit()

def update_daily_ads(user_id: int, ads_watched: int):
    today = datetime.now().date()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT last_ad_date FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result and result["last_ad_date"] == today:
                cur.execute("UPDATE users SET daily_ads_watched = daily_ads_watched + %s WHERE user_id = %s", (ads_watched, user_id))
            else:
                cur.execute("UPDATE users SET daily_ads_watched = %s, last_ad_date = %s WHERE user_id = %s", (ads_watched, today, user_id))
            conn.commit()

def add_invited_friend(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET invited_friends = invited_friends + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def withdraw_points(user_id: int, amount: float, binance_id: str, app):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result and result["points"] >= amount:
                cur.execute(
                    "UPDATE users SET points = points - %s, binance_id = %s WHERE user_id = %s",
                    (amount, binance_id, user_id)
                )
                conn.commit()
                app.bot.send_message(
                    chat_id=ADMIN_CHANNEL_ID,
                    text=f"💸 Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} $DOGS\nBinance ID: {binance_id}"
                )
                return True
            return False

# ---------------- API ROUTES ----------------
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user = get_or_create_user(user_id)
    return {
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"]
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int):
    user = get_or_create_user(user_id)
    today = datetime.now().date()
    if user["last_ad_date"] == today and user["daily_ads_watched"] >= 30:
        return {"success": False, "limit_reached": True}
    update_daily_ads(user_id, 1)
    update_points(user_id, 20.0)
    if user["invited_by"]:
        update_points(user["invited_by"], 2.0)  # referral bonus
    return {
        "success": True,
        "points": get_user_points(user_id),
        "daily_ads_watched": user["daily_ads_watched"] + 1
    }

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    binance_id = data["binance_id"]
    if amount < 2000 or not binance_id:
        return {"success": False, "message": "Minimum 2000 $DOGS and Binance ID required"}
    if withdraw_points(user_id, amount, binance_id, application):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

# ---------------- HTML MINI APP ----------------
@app.get("/app")
async def mini_app():
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOGS Earn App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE}" data-sdk="show_{MONETAG_ZONE}"></script>
</head>
<body style="background:#222;color:white;font-family:Arial;padding:20px">
    <h2>DOGS Earn</h2>
    <p>ID: <span id="user-id"></span></p>
    <p>Balance: <span id="balance">0.00</span> $DOGS</p>
    <p>Daily Ads: <span id="daily-limit">0</span>/30</p>
    <button id="watch-ad-btn">Watch Ad</button>

    <h3>Invite</h3>
    <p>Your Link: <span id="invite-link"></span></p>
    <button onclick="copyLink()">Copy Link</button>
    <p>Friends Invited: <span id="invited-count">0</span></p>

    <h3>Withdraw</h3>
    <input type="number" id="amount" placeholder="Enter amount (min 2000)">
    <input type="text" id="binance-id" placeholder="Enter Binance ID">
    <button onclick="withdraw()">Withdraw</button>

    <script>
        const tg = window.Telegram.WebApp;
        tg.ready();
        const user = tg.initDataUnsafe.user;
        const userId = user ? user.id : 0;
        document.getElementById("user-id").textContent = userId;

        async function loadData() {{
            const res = await fetch("/api/user/" + userId);
            const data = await res.json();
            document.getElementById("balance").textContent = Number(data.points).toFixed(2);
            document.getElementById("daily-limit").textContent = data.daily_ads_watched + "/30";
            document.getElementById("invited-count").textContent = data.invited_friends;
            document.getElementById("invite-link").textContent = "https://t.me/your_bot?start=ref" + userId;
        }}

        async function watchAd() {{
            const btn = document.getElementById("watch-ad-btn");
            btn.disabled = true; btn.textContent = "Loading...";
            const fn = window["show_{MONETAG_ZONE}"];
            if (typeof fn === "function") {{
                try {{
                    await fn();
                    const res = await fetch("/api/watch_ad/" + userId, {{method:"POST"}});
                    const data = await res.json();
                    if (data.success) {{
                        tg.showAlert("Ad watched! +20 $DOGS");
                    }} else if (data.limit_reached) {{
                        tg.showAlert("Daily limit reached!");
                    }} else {{
                        tg.showAlert("Error watching ad");
                    }}
                    loadData();
                }} catch(err) {{
                    console.error(err);
                    tg.showAlert("Ad failed to load");
                }}
            }} else {{
                tg.showAlert("Ad service not ready, try later");
            }}
            btn.disabled = false; btn.textContent = "Watch Ad";
        }}
        document.getElementById("watch-ad-btn").addEventListener("click", watchAd);

        async function copyLink() {{
            const link = document.getElementById("invite-link").textContent;
            await navigator.clipboard.writeText(link);
            tg.showAlert("Invite link copied!");
        }}

        async function withdraw() {{
            const amount = parseFloat(document.getElementById("amount").value);
            const binanceId = document.getElementById("binance-id").value;
            if (amount < 2000 || !binanceId) {{
                tg.showAlert("Minimum 2000 $DOGS and Binance ID required!");
                return;
            }}
            const res = await fetch("/api/withdraw/" + userId, {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{amount, binance_id: binanceId}})
            }});
            const data = await res.json();
            if (data.success) {{
                tg.showAlert("Withdraw request sent!");
                document.getElementById("amount").value = "";
                document.getElementById("binance-id").value = "";
                loadData();
            }} else {{
                tg.showAlert(data.message || "Withdraw failed");
            }}
        }}

        loadData();
    </script>
</body>
</html>
    """
    return HTMLResponse(html_content)

# ---------------- TELEGRAM BOT ----------------
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    invited_by = None
    if args and args[0].startswith("ref"):
        try:
            invited_by = int(args[0].replace("ref", ""))
            add_invited_friend(invited_by)
        except ValueError:
            pass
    get_or_create_user(update.effective_user.id, invited_by)
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🚀 Launch the Mini App!", reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

# ---------------- RUN SERVER ----------------
if __name__ == "__main__":
    init_db()
    import asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(application.initialize())
    loop.create_task(application.start())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
