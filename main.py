# main.py - Backend FastAPI server for Telegram Mini App with Monetag
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

@app.post("/monetag/postback")
async def monetag_postback(request: Request):
    data = await request.json()
    event_type = data.get("event_type")
    user_id = data.get("user_id")  # From Monetag macro {USER_ID}
    if event_type == "ad_completed" and user_id:
        user = get_or_create_user(user_id)
        today = datetime.now().date()
        if not (user["last_ad_date"] == today and user["daily_ads_watched"] >= 30):
            update_daily_ads(user_id, 1)
            update_points(user_id, 20.0)
            if user["invited_by"]:
                referrer_id = user["invited_by"]
                update_points(referrer_id, 2.0)  # 10% bonus
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

# Mini App HTML with Monetag SDK and real-time updates
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
    <script src="//libtl.com/sdk.js" data-zone="9859391" data-sdk="show_9859391"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        .nav { position: fixed; bottom: 0; left: 0; right: 0; display: flex; background: rgba(255,255,255,0.1); border-top: 1px solid rgba(255,255,255,0.2); }
        .nav-btn { flex: 1; padding: 15px; text-align: center; background: none; border: none; cursor: pointer; color: white; }
        .nav-btn.active { background: rgba(255,255,255,0.2); }
        .page { display: none; min-height: 100vh; }
        .page.active { display: block; }
        .header { text-align: center; margin: 20px 0; }
        .ad-panel { background: rgba(255,255,255,0.1); padding: 20px; margin: 20px 0; border-radius: 10px; text-align: center; }
        .watch-btn { background: #4CAF50; color: white; padding: 15px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; width: 100%; }
        .input { padding: 10px; margin: 10px 0; width: 100%; border: 1px solid rgba(255,255,255,0.3); border-radius: 5px; background: rgba(255,255,255,0.1); color: white; }
        .withdraw-btn { background: #f44336; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
        .copy-btn { background: #9E9E9E; color: white; padding: 5px 10px; border: none; border-radius: 3px; cursor: pointer; }
    </style>
</head>
<body>
    <div id="tasks" class="page active">
        <div class="header">
            <h2>Tasks</h2>
            <p>ID: <span id="user-id"></span></p>
            <p>Balance: <span id="balance">0.00</span> $DOGS</p>
        </div>
        <div class="ad-panel">
            <h3>Watch Ads</h3>
            <p>1 Ad watch = 20 $DOGS</p>
            <p>Daily Limit: <span id="daily-limit">0</span>/30</p>
            <button class="watch-btn" id="watch-ad-btn">Watch Ad</button>
        </div>
    </div>
    <div id="invite" class="page">
        <div class="header">
            <h2>Invite</h2>
            <p>Your Invite Link: <span id="invite-link"></span></p>
            <button class="copy-btn" onclick="copyLink()">Copy Link</button>
            <p>Total Friends Invited: <span id="invited-count">0</span></p>
        </div>
    </div>
    <div id="withdraw" class="page">
        <div class="header">
            <h2>Withdraw</h2>
            <p>Minimum 2000 $DOGS</p>
        </div>
        <div class="input-group">
            <input type="number" id="amount" placeholder="Enter amount (min 2000)" class="input">
            <input type="text" id="binance-id" placeholder="Enter Binance ID" class="input">
            <button class="withdraw-btn" onclick="withdraw()">Withdraw</button>
        </div>
    </div>
    <div class="nav">
        <button class="nav-btn active" onclick="showPage('tasks')">Tasks</button>
        <button class="nav-btn" onclick="showPage('invite')">Invite</button>
        <button class="nav-btn" onclick="showPage('withdraw')">Withdraw</button>
    </div>

    <script>
        const tg = window.Telegram.WebApp;
        tg.ready();
        const userId = tg.initDataUnsafe.user.id;
        document.getElementById('user-id').textContent = userId;

        async function loadData() {
            const response = await fetch('/api/user/' + userId);
            const data = await response.json();
            document.getElementById('balance').textContent = data.points.toFixed(2);
            document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
            document.getElementById('invited-count').textContent = data.invited_friends;
            document.getElementById('invite-link').textContent = tg.initDataUnsafe.startParam ? 'https://t.me/jdsrhukds_bot?start=' + tg.initDataUnsafe.startParam : 'https://t.me/jdsrhukds_bot?start=ref' + userId;
        }

        async function watchAd() {
            const watchBtn = document.getElementById('watch-ad-btn');
            watchBtn.disabled = true;
            watchBtn.textContent = 'Watching...';
            try {
                await show_9859391().then(() => {
                    tg.showAlert('Ad watched! Reward processing...');
                }).catch(error => {
                    tg.showAlert('Ad failed to load');
                    console.error('Monetag ad error:', error);
                });
            } finally {
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Ad';
            }
        }

        document.getElementById('watch-ad-btn').addEventListener('click', watchAd);

        async function copyLink() {
            const link = document.getElementById('invite-link').textContent;
            await navigator.clipboard.writeText(link);
            tg.showAlert('Link copied!');
        }

        async function withdraw() {
            const amount = parseFloat(document.getElementById('amount').value);
            const binanceId = document.getElementById('binance-id').value;
            if (amount < 2000 || !binanceId) {
                tg.showAlert('Minimum 2000 $DOGS and Binance ID required!');
                return;
            }
            const response = await fetch('/api/withdraw/' + userId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({amount, binance_id: binanceId})
            });
            const data = await response.json();
            if (data.success) {
                tg.showAlert('Withdraw successful! Credited to Binance within 24 hours.');
                document.getElementById('amount').value = '';
                document.getElementById('binance-id').value = '';
                loadData();
            } else {
                tg.showAlert(data.message || 'Withdraw failed');
            }
        }

        function showPage(page) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(page).classList.add('active');
            document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }

        // Real-time data polling
        setInterval(loadData, 5000); // Update every 5 seconds
        loadData(); // Initial load
    </script>
</body>
</html>
    """
    return HTMLResponse(html_content)

# Telegram bot setup for launching Mini App
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle referral
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
    await update.message.reply_text("Launch the Mini App!", reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

# Run the application
if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
