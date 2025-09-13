import os
import json
import aiofiles
import aiohttp
import datetime as dt
from typing import Optional, Dict, Any, Tuple
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "jdsrhukds_bot"
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"
USERS_FILE = "/tmp/users.json"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
json_lock = asyncio.Lock()

# JSON utils (refactored for consistency)
async def read_json() -> Dict[str, Any]:
    async with json_lock:
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                content = await f.read()
                if content.strip():
                    return json.loads(content)
                return {}
        except FileNotFoundError:
            logger.warning(f"{USERS_FILE} not found")
            return {}
        except Exception as e:
            logger.error(f"Error reading {USERS_FILE}: {e}")
            raise

async def write_json(users: Dict[str, Any]):
    async with json_lock:
        async with aiofiles.open(USERS_FILE, mode='w') as f:
            await f.write(json.dumps(users, indent=2))

async def init_json():
    try:
        async with aiofiles.open(USERS_FILE, mode='a') as f:
            pass  # Ensure file exists
        users = await read_json()
        if not users:
            await write_json({})
        logger.info(f"JSON initialized at {USERS_FILE}")
    except Exception as e:
        logger.error(f"JSON init failed: {e}")
        raise

async def get_or_create_user(user_id: int, invited_by: Optional[int] = None) -> Tuple[dict, bool]:
    users = await read_json()
    user_id_str = str(user_id)
    is_new = user_id_str not in users
    if is_new:
        users[user_id_str] = {
            "user_id": user_id,
            "points": 0.0,
            "daily_ads_watched": 0,
            "last_ad_date": None,
            "invited_friends": 0,
            "binance_id": None,
            "invited_by": invited_by,
            "created_at": dt.datetime.now().isoformat()
        }
        await write_json(users)
        logger.info(f"Created user {user_id} with invited_by {invited_by}")
    return users[user_id_str], is_new

async def get_user_data(user_id: int) -> dict:
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        return users[user_id_str]
    raise ValueError(f"User {user_id} not found")

async def update_points(user_id: int, points: float):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["points"] += points
        await write_json(users)
        logger.info(f"Updated points for {user_id}: +{points}, new total {users[user_id_str]['points']}")
    else:
        logger.error(f"Cannot update points: user {user_id} not found")

async def update_daily_ads(user_id: int, ads_watched: int):
    today = dt.datetime.now().date().isoformat()
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        user_data = users[user_id_str]
        if user_data["last_ad_date"] == today:
            user_data["daily_ads_watched"] += ads_watched
        else:
            user_data["daily_ads_watched"] = ads_watched
            user_data["last_ad_date"] = today
        await write_json(users)
        logger.info(f"Updated ads for {user_id}: {user_data['daily_ads_watched']}/30")
    else:
        logger.error(f"Cannot update ads: user {user_id} not found")

async def add_invited_friend(user_id: int):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["invited_friends"] += 1
        await write_json(users)
        logger.info(f"Incremented invited_friends for {user_id}: {users[user_id_str]['invited_friends']}")
    else:
        logger.error(f"Cannot add friend: user {user_id} not found")

async def withdraw_points(user_id: int, amount: float, binance_id: str) -> bool:
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users and users[user_id_str]["points"] >= amount:
        users[user_id_str]["points"] -= amount
        users[user_id_str]["binance_id"] = binance_id
        await write_json(users)
        await application.bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text=f"Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} $DOGS\nBinance ID: {binance_id}"
        )
        logger.info(f"Withdrawal for {user_id}: {amount} to {binance_id}")
        return True
    else:
        logger.error(f"Withdrawal failed for {user_id}: insufficient balance or user not found")
    return False

# Debug endpoint to inspect JSON
@app.get("/debug/users")
async def debug_users():
    try:
        return await read_json()
    except Exception as e:
        logger.error(f"Debug users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# API endpoints
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user = await get_user_data(user_id)
    return {
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "invited_by": None
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int):
    logger.info(f"Ad watch request for {user_id}")
    user = await get_user_data(user_id)
    today = dt.datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["daily_ads_watched"] >= 30:
        logger.info(f"Ad limit reached for {user_id}")
        return {"success": False, "limit_reached": True}
    
    await update_daily_ads(user_id, 1)
    await update_points(user_id, 20.0)
    
    invited_by = user.get("invited_by")
    logger.info(f"Referrer check for {user_id}: invited_by = {invited_by}")
    if invited_by:
        logger.info(f"Granting 2 $DOGS to referrer {invited_by} for {user_id}'s ad")
        await update_points(invited_by, 2.0)
    else:
        logger.info(f"No referrer for {user_id}")
    
    # Refresh user data after updates
    user = await get_user_data(user_id)
    return {
        "success": True,
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"]
    }

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    binance_id = data["binance_id"]
    if amount < 2 or not binance_id:
        return {"success": False, "message": "Minimum 2000 $DOGS and Binance ID required"}
    if await withdraw_points(user_id, amount, binance_id):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

# Mini App HTML (unchanged)
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
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
        .nav {{ position: fixed; bottom: 0; left: 0; right: 0; display: flex; background: rgba(255,255,255,0.1); border-top: 1px solid rgba(255,255,255,0.2); }}
        .nav-btn {{ flex: 1; padding: 15px; text-align: center; background: none; border: none; cursor: pointer; color: white; }}
        .nav-btn.active {{ background: rgba(255,255,255,0.2); }}
        .page {{ display: none; min-height: 100vh; }}
        .page.active {{ display: block; }}
        .header {{ text-align: center; margin: 20px 0; }}
        .ad-panel {{ background: rgba(255,255,255,0.1); padding: 20px; margin: 20px 0; border-radius: 10px; text-align: center; }}
        .watch-btn {{ background: #4CAF50; color: white; padding: 15px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; width: 100%; }}
        .input {{ padding: 10px; margin: 10px 0; width: 100%; border: 1px solid rgba(255,255,255,0.3); border-radius: 5px; background: rgba(255,255,255,0.1); color: white; }}
        .withdraw-btn {{ background: #f44336; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}
        .copy-btn {{ background: #9E9E9E; color: white; padding: 5px 10px; border: none; border-radius: 3px; cursor: pointer; }}
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

        async function loadData() {{
            try {{
                const response = await fetch('/api/user/' + userId);
                if (!response.ok) throw new Error('API failed: ' + response.status);
                const data = await response.json();
                document.getElementById('balance').textContent = data.points.toFixed(2);
                document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
                document.getElementById('invited-count').textContent = data.invited_friends;
                document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
            }} catch (error) {{
                console.error('loadData error:', error);
                tg.showAlert('Failed to load data');
            }}
        }}

        async function watchAd() {{
            const watchBtn = document.getElementById('watch-ad-btn');
            watchBtn.disabled = true;
            watchBtn.textContent = 'Watching...';
            try {{
                await show_{MONETAG_ZONE}().then(async () => {{
                    const response = await fetch('/api/watch_ad/' + userId, {{ method: 'POST' }});
                    const data = await response.json();
                    if (data.success) {{
                        tg.showAlert('Ad watched! +20 $DOGS');
                    }} else if (data.limit_reached) {{
                        tg.showAlert('Daily limit reached!');
                    }} else {{
                        tg.showAlert('Error watching ad');
                    }}
                    loadData();
                }}).catch(error => {{
                    tg.showAlert('Ad failed to load');
                    console.error('Monetag error:', error);
                }});
            }} finally {{
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Ad';
            }}
        }}

        document.getElementById('watch-ad-btn').addEventListener('click', watchAd);

        async function copyLink() {{
            const link = document.getElementById('invite-link').textContent;
            await navigator.clipboard.writeText(link);
            tg.showAlert('Link copied!');
        }}

        async function withdraw() {{
            const amount = parseFloat(document.getElementById('amount').value);
            const binanceId = document.getElementById('binance-id').value;
            if (amount < 2 || !binanceId) {{
                tg.showAlert('Minimum 2000 $DOGS and Binance ID required!');
                return;
            }}
            const response = await fetch('/api/withdraw/' + userId, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{amount, binance_id: binanceId}})
            }});
            const data = await response.json();
            if (data.success) {{
                tg.showAlert('Withdraw successful! Credited within 24 hours.');
                document.getElementById('amount').value = '';
                document.getElementById('binance-id').value = '';
                loadData();
            }} else {{
                tg.showAlert(data.message || 'Withdraw failed');
            }}
        }}

        function showPage(page) {{
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(page).classList.add('active');
            document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }}

        loadData();
    </script>
</body>
</html>
    """
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE).replace("{BOT_USERNAME}", BOT_USERNAME))

# Telegram webhook
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    update_json = await request.json()
    update = Update.de_json(update_json, application.bot)
    await application.process_update(update)
    return {"ok": True}

@app.get("/set-webhook")
async def set_webhook():
    if not BASE_URL:
        raise HTTPException(status_code=400, detail="BASE_URL not set")
    webhook_url = f"{BASE_URL}/telegram/webhook"
    try:
        await application.bot.set_webhook(webhook_url)
        return {"status": "set", "url": webhook_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Bot handlers
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start by {update.effective_user.id}, args: {context.args}")
    args = context.args
    invited_by = None
    if args and args[0].startswith("ref"):
        try:
            invited_by = int(args[0].replace("ref", ""))
        except ValueError:
            invited_by = None
    
    user, is_new = await get_or_create_user(update.effective_user.id, invited_by)
    
    if is_new and invited_by and invited_by != update.effective_user.id:
        await add_invited_friend(invited_by)
        logger.info(f"New referral: {update.effective_user.id} by {invited_by}")
        welcome_text = "Welcome! Referred by a friend. Launch Mini App!"
    else:
        welcome_text = "Welcome back! Launch Mini App!"
    
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

# Initialize
async def initialize_app():
    await validate_token()
    await init_json()
    await application.initialize()
    if BASE_URL:
        webhook_url = f"{BASE_URL}/telegram/webhook"
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set: {webhook_url}")
    else:
        logger.warning("BASE_URL not set - set manually via /set-webhook")

async def validate_token():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as resp:
            if resp.status != 200:
                raise ValueError(f"Invalid BOT_TOKEN: {await resp.text()}")
    logger.info("BOT_TOKEN validated")

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(initialize_app())
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info", workers=1)
    finally:
        loop.close()
