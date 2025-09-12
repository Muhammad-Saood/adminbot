import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
from dotenv import load_dotenv
from datetime import datetime, timedelta
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
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")  # Your admin channel ID
MONETAG_ZONE = "9859391"  # Your Monetag data-zone

app = FastAPI()

# Database connection
def get_db_connection():
    return psycopg2.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
        cursor_factory=RealDictCursor
    )

# Initialize database
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

# Call init_db at startup
init_db()

# User data functions
def get_or_create_user(user_id: int, invited_by: Optional[int] = None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = cur.fetchone()
            if not user:
                cur.execute("INSERT INTO users (user_id, invited_by) VALUES (%s, %s)", (user_id, invited_by))
                conn.commit()
                return {"user_id": user_id, "points": 0.0, "daily_ads_watched": 0, "last_ad_date": None, "invited_friends": 0, "binance_id": None, "invited_by": invited_by}
            return dict(user)

def get_user_points(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return result["points"] if result else 0.0

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
            if result and result['last_ad_date'] == today:
                cur.execute("UPDATE users SET daily_ads_watched = daily_ads_watched + %s WHERE user_id = %s", (ads_watched, user_id))
            else:
                cur.execute("UPDATE users SET daily_ads_watched = %s, last_ad_date = %s WHERE user_id = %s", (ads_watched, today, user_id))
            conn.commit()

def add_invited_friend(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET invited_friends = invited_friends + 1 WHERE user_id = %s", (user_id,))
            conn.commit()

def set_binance_id(user_id: int, binance_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET binance_id = %s WHERE user_id = %s", (binance_id, user_id))
            conn.commit()

def withdraw_points(user_id: int, amount: float, binance_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result and result['points'] >= amount:
                cur.execute("UPDATE users SET points = points - %s, binance_id = %s WHERE user_id = %s", (amount, binance_id, user_id))
                conn.commit()
                application.bot.send_message(chat_id=ADMIN_CHANNEL_ID, text=f"Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} $DOGS\nBinance ID: {binance_id}")
                return True
            return False

# API endpoints for Mini App
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user = get_or_create_user(user_id)
    return {"points": user["points"], "daily_ads_watched": user["daily_ads_watched"], "invited_friends": user["invited_friends"]}

@app.get("/monetag/postback")
async def monetag_postback(
    ymid: str = None,
    event: str = None,
    zone_id: str = None,
    request_var: str = None,
    telegram_id: str = None,
    estimated_price: str = None
):
    try:
        user_id = int(ymid) if ymid else None
        if user_id and event in ["impression", "click"] and zone_id == MONETAG_ZONE:
            user = get_or_create_user(user_id)
            today = datetime.now().date()
            if not (user["last_ad_date"] == today and user["daily_ads_watched"] >= 30):
                update_daily_ads(user_id, 1)
                update_points(user_id, 20.0)  # Award 20 $DOGS
                if user["invited_by"]:
                    referrer_id = user["invited_by"]
                    update_points(referrer_id, 2.0)  # 10% bonus
    except ValueError:
        pass
    return {"status": "ok"}

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    binance_id = data["binance_id"]
    if amount < 2000 or not binance_id:
        return {"success": False, "message": "Minimum 2000 $DOGS and Binance ID required"}
    if withdraw_points(user_id, amount, binance_id):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

# Mini App HTML with Monetag postback and real-time updates
@app.get("/app")
async def mini_app():
    html_content = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOGS Earn App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; margin: 20px; }
        button { padding: 10px 20px; margin: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <h1>Earn $DOGS</h1>
    <p>Points: <span id="points">0</span></p>
    <p>Daily Ads Watched: <span id="ads_watched">0</span></p>
    <p>Invited Friends: <span id="invited_friends">0</span></p>
    <button id="watch_ad">Watch Ad (+20 $DOGS)</button>
    <button id="invite">Invite Friends (+2 $DOGS per friend)</button>
    <button id="withdraw">Withdraw ($DOGS)</button>
    <p id="status"></p>

    <script>
        let userId = Telegram.WebApp.initDataUnsafe.user ? Telegram.WebApp.initDataUnsafe.user.id : null;
        if (!userId) userId = Math.floor(Math.random() * 10000000000);

        async function updateUserData() {
            const response = await fetch(`/api/user/${userId}`);
            const data = await response.json();
            document.getElementById("points").textContent = data.points.toFixed(2);
            document.getElementById("ads_watched").textContent = data.daily_ads_watched;
            document.getElementById("invited_friends").textContent = data.invited_friends;
        }

        document.getElementById("watch_ad").addEventListener("click", () => {
            window.location.href = `https://ads.monetag.com/click/${MONETAG_ZONE}?ymid=${userId}&request_var=telegram_id=${userId}`;
        });

        document.getElementById("invite").addEventListener("click", () => {
            Telegram.WebApp.openTelegramLink(`https://t.me/share/url?url=${BASE_URL}/app?invited_by=${userId}`);
        });

        document.getElementById("withdraw").addEventListener("click", async () => {
            const amount = prompt("Enter amount (min 2000 $DOGS):");
            const binanceId = prompt("Enter your Binance ID:");
            if (amount && binanceId) {
                const response = await fetch(`/api/withdraw/${userId}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ amount: parseFloat(amount), binance_id: binanceId })
                });
                const result = await response.json();
                document.getElementById("status").textContent = result.message || "Withdrawal requested!";
                updateUserData();
            }
        });

        setInterval(updateUserData, 5000); // Update every 5 seconds
        updateUserData();
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

# Telegram bot handlers
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_or_create_user(user_id)
    await update.message.reply_text(
        "Welcome to DOGS Earn App! Use the Mini App to earn $DOGS by watching ads and inviting friends.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Mini App", web_app={"url": f"{BASE_URL}/app"})]])
    )

application.add_handler(CommandHandler("start", start))

# Run bot and server
if __name__ == "__main__":
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
