import os
import json
import aiofiles
import aiohttp
import threading
import datetime as dt
from typing import Optional, Dict, Any, Tuple
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import requests
from dotenv import load_dotenv

load_dotenv()

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "clicktoearn5_bot"
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"
USERS_FILE = "/tmp/users.json"
OWNER_WALLET = os.getenv("OWNER_WALLET", "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c")  # Replace with actual owner wallet
USDT_CONTRACT = "EQCxE6mUtQJKFnGfaTvjNE2WUmnI9K8WLcpMMM-o3Q5HHB0o"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
json_lock = asyncio.Lock()

# JSON utils
async def read_json() -> Dict[str, Any]:
    async with json_lock:
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                content = await f.read()
                if content.strip():
                    return json.loads(content)
                return {}
        except FileNotFoundError:
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
            pass
        users = await read_json()
        if not users:
            await write_json({})
    except Exception as e:
        logger.error(f"JSON init failed: {e}")
        raise

async def reset_daily_counters_if_needed(user_id: int) -> bool:
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str not in users:
        return False
    user_data = users[user_id_str]
    today = dt.datetime.now().date().isoformat()
    if user_data.get("last_ad_date") != today:
        user_data["daily_ads_watched"] = 0
        user_data["last_ad_date"] = today
        await write_json(users)
        return True
    return False

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
            "withdraw_wallet": None,
            "invited_by": invited_by,
            "created_at": dt.datetime.now().isoformat(),
            "last_ad_start_time": None,
            "connected_wallet": None,
            "plan_purchase_date": None
        }
        await write_json(users)
    return users[user_id_str], is_new

async def get_user_data(user_id: int) -> dict:
    await reset_daily_counters_if_needed(user_id)
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
    else:
        logger.error(f"Cannot update ads: user {user_id} not found")

async def add_invited_friend(user_id: int):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["invited_friends"] += 1
        await write_json(users)
    else:
        logger.error(f"Cannot add friend: user {user_id} not found")

async def withdraw_points(user_id: int, amount: float, withdraw_wallet: str) -> bool:
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users and users[user_id_str]["points"] >= amount:
        users[user_id_str]["points"] -= amount
        users[user_id_str]["withdraw_wallet"] = withdraw_wallet
        await write_json(users)
        await application.bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text=f"Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} USDT\nWallet: {withdraw_wallet}"
        )
        return True
    return False

def is_plan_active(user: dict) -> bool:
    if not user.get("plan_purchase_date"):
        return False
    purchase_date = dt.datetime.fromisoformat(user["plan_purchase_date"])
    return dt.datetime.now() < purchase_date + dt.timedelta(days=7)

# API endpoints
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user = await get_user_data(user_id)
    return {
        "points": user["points"],
        "total_daily_ads_watched": user["daily_ads_watched"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "connected_wallet": user["connected_wallet"],
        "plan_purchase_date": user["plan_purchase_date"],
        "plan_active": is_plan_active(user)
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int, request: Request):
    user = await get_user_data(user_id)
    if not is_plan_active(user):
        return {"success": False, "message": "Please purchase plan first"}

    today = dt.datetime.now().date().isoformat()
    total_ads_watched = user["daily_ads_watched"]

    if user["last_ad_date"] == today and total_ads_watched >= 10:
        return {"success": False, "limit_reached": True}

    data = await request.json()
    ad_completed = data.get("ad_completed", False)

    if not ad_completed:
        return {"success": False, "message": "Ad not completely watched or not opened ad website"}

    # Use single zone
    zone = MONETAG_ZONE

    await update_daily_ads(user_id, 1)
    await update_points(user_id, 0.1)

    invited_by = user.get("invited_by")
    if invited_by:
        await update_points(invited_by, 0.007)

    user = await get_user_data(user_id)
    return {
        "success": True,
        "points": user["points"],
        "total_daily_ads_watched": user["daily_ads_watched"],
        "daily_ads_watched": user["daily_ads_watched"]
    }

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    withdraw_wallet = data["withdraw_wallet"]
    if amount < 1 or not withdraw_wallet:
        return {"success": False, "message": "Minimum 1 USDT and Wallet address required"}
    if await withdraw_points(user_id, amount, withdraw_wallet):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

@app.post("/api/set_wallet/{user_id}")
async def set_wallet(user_id: int, request: Request):
    data = await request.json()
    wallet = data.get("wallet")
    if not wallet:
        return {"success": False}
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["connected_wallet"] = wallet
        await write_json(users)
        return {"success": True}
    return {"success": False}

@app.post("/api/disconnect_wallet/{user_id}")
async def disconnect_wallet(user_id: int):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["connected_wallet"] = None
        await write_json(users)
        return {"success": True}
    return {"success": False}

@app.post("/api/purchase_plan/{user_id}")
async def purchase_plan(user_id: int):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["plan_purchase_date"] = dt.datetime.now().isoformat()
        await write_json(users)
        return {"success": True}
    return {"success": False}

@app.get("/tonconnect-manifest.json")
async def tonconnect_manifest():
    return JSONResponse({
        "url": f"{BASE_URL}/app",
        "name": "Click to Earn",
        "iconUrl": "https://telegram.org/img/t_logo.png",
        "termsOfUseUrl": None,
        "privacyPolicyUrl": None
    })

# Mini App HTML
@app.get("/app")
async def mini_app():
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DOGS Earn App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE}" data-sdk="show_{MONETAG_ZONE}"></script>
    <script src="https://unpkg.com/@ton/ton@13/dist/index.js"></script>
    <script src="https://unpkg.com/tonconnect-ui@latest/dist/tonconnect-ui.min.js"></script>
    <script src="https://raw.githubusercontent.com/Muhammad-Saood/adminbot/main/wallet.js"></script>  <!-- Link to your GitHub file -->
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            background: white;
            min-height: 100vh;
            color: black;
            padding: 20px;
            font-weight: bold;
        }

        .page {
            display: none;
            min-height: 100vh;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding-top: 60px;
            padding-bottom: 5rem;
        }

        .page.active {
            display: flex;
        }

        .header {
            text-align: center;
            margin-bottom: 2rem;
            width: 100%;
        }

        .user-info {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            width: 100%;
            position: fixed;
            top: 0;
            left: 0;
            padding: 10px;
            background: white;
            z-index: 10;
        }

        .id-card, .balance-card {
            background: #f0f0f0;
            color: black;
            padding: 10px;
            border-radius: 10px;
            width: 48%;
            text-align: center;
        }

        .header h2 {
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 0.75rem;
        }

        .header p {
            font-size: 1.125rem;
            font-weight: bold;
            margin-bottom: 0.75rem;
        }

        .highlight {
            color: #0000ff;
            font-weight: bold;
        }

        .card {
            background: #f0f0f0;
            padding: 1rem;
            border-radius: 1rem;
            width: 300px;
            height: 300px;
            text-align: center;
            margin-bottom: 1rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }

        .card h2 {
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 1rem;
        }

        .ad-info {
            display: flex;
            justify-content: space-between;
            margin-bottom: 1rem;
            width: 100%;
        }

        .small-card {
            background: #f0f0f0;
            color: black;
            padding: 10px;
            border-radius: 10px;
            width: 48%;
            text-align: center;
        }

        .nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            display: flex;
            background: #f0f0f0;
            border-top: 1px solid #ccc;
        }

        .nav-btn {
            flex: 1;
            padding: 1rem;
            text-align: center;
            background: none;
            border: none;
            cursor: pointer;
            color: black;
            font-size: 0.9rem;
            font-weight: bold;
        }

        .nav-btn.active {
            background: #ddd;
            border-radius: 0.5rem 0.5rem 0 0;
        }

        .nav-btn svg {
            width: 24px;
            height: 24px;
            margin: 0 auto 0.25rem;
            stroke: black;
        }

        .watch-btn, .btn-primary {
            background: #10b981;
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: bold;
            width: 100%;
            margin-bottom: 1rem;
        }

        .copy-btn {
            background: #6b7280;
            color: white;
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: bold;
            margin-bottom: 1rem;
        }

        .withdraw-btn {
            background: #ef4444;
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: bold;
            width: 100%;
            margin-bottom: 1rem;
        }

        .input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ccc;
            border-radius: 0.5rem;
            background: white;
            color: black;
            font-size: 1rem;
            margin-bottom: 1rem;
        }

        .input::placeholder {
            color: #888;
        }

        .break-all {
            word-break: break-all;
        }

        .loading {
            color: #888;
            font-style: italic;
        }

        @media (max-width: 640px) {
            .page {
                padding-top: 1.5rem;
                padding-bottom: 4rem;
            }
            .header h2 {
                font-size: 1.75rem;
            }
            .header {
                margin-bottom: 1.5rem;
            }
            .card {
                padding: 0.75rem;
                min-height: 30vh;
                margin-bottom: 0.75rem;
            }
            .watch-btn, .btn-primary, .copy-btn, .withdraw-btn, .input {
                margin-bottom: 0.75rem;
            }
            .nav-btn {
                font-size: 0.8rem;
            }
            .nav-btn svg {
                width: 20px;
                height: 20px;
            }
        }
    </style>
</head>
<body>
    <div id="tasks" class="page active">
        <div class="header">
            <div class="user-info">
                <div class="id-card">ID: <span id="user-id"></span></div>
                <div class="balance-card">Balance: <span id="balance" class="highlight">0.00</span> USDT</div>
            </div>
            <h2>📝 Task 📝</h2>
            <p>💰 Start earning instantly – get 0.1 USDT for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings 💰</p>
        </div>
        <div class="card">
            <h2>🚀 Watch Ads 🚀</h2>
            <div class="ad-info">
                <div class="small-card">1 AD = 0.1 USDT</div>
                <div class="small-card">Daily Limit: <span id="ad-limit" class="highlight">0/10</span></div>
            </div>
            <button class="watch-btn" id="ad-btn">Watch Ad</button>
            <button class="btn-primary" id="upgrade-plan">Upgrade Plan</button>
        </div>
    </div>
    <div id="invite" class="page">
        <div class="header">
            <h2>👥 Invite Friends 👥</h2>
            <p>Invite friends by using the link given below and get 7% bonus of friend's earning</p>
        </div>
        <div class="card">
            <p>Your Invite Link:</p>
            <p id="invite-link" class="highlight break-all"></p>
            <button class="copy-btn" onclick="copyLink()">Copy Invite Link</button>
            <p>Total Friends: <span id="invited-count" class="highlight">0</span></p>
        </div>
    </div>
    <div id="withdraw" class="page">
        <div class="header">
            <h2>💸 Withdraw 💸</h2>
            <p class="highlight">Minimum withdrawal amount is 1 USDT</p>
        </div>
        <div id="wallet-connect-section" style="width:100%; margin-bottom:1rem;"></div>
        <div class="card">
            <input type="number" id="amount" placeholder="Enter amount (min 1 USDT)" class="input">
            <input type="text" id="withdraw-wallet" placeholder="Enter Wallet Address" class="input">
            <button class="withdraw-btn" onclick="withdraw()">Withdraw</button>
        </div>
    </div>
    <div class="nav">
        <button class="nav-btn active" onclick="showPage('tasks')" data-page="tasks">
            <svg class="w-6 h-6 mx-auto mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
            Tasks
        </button>
        <button class="nav-btn" onclick="showPage('invite')" data-page="invite">
            <svg class="w-6 h-6 mx-auto mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v1m6 11h2m-6 0h-2v4m0-11v3m-3 4h.01M9 16h.01"></path></svg>
            Invite
        </button>
        <button class="nav-btn" onclick="showPage('withdraw')" data-page="withdraw">
            <svg class="w-6 h-6 mx-auto mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>
            Withdraw
        </button>
    </div>
</body>
</html>
"""
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE).replace("{BOT_USERNAME}", BOT_USERNAME).replace("{OWNER_WALLET}", OWNER_WALLET).replace("{USDT_CONTRACT}", USDT_CONTRACT))

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
        welcome_text = "🎉 Welcome to Click to Earn! 🎉 💰 Start earning instantly – get 0.1 USDT for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings. ✅ Instant withdraw ✅ Wallet 🚀 Open Mini App , and start your earning!"
    else:
        welcome_text = "🎉 Welcome to Click to Earn! 🎉 💰 Start earning instantly – get 0.1 USDT for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings. ✅ Instant withdraw ✅ Wallet 🚀 Open Mini App, and start your earning!"
    
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

# SELF-PINGING TASK
PING_INTERVAL = 240

def start_ping_task():
    async def ping_self():
        while True:
            try:
                if not BASE_URL:
                    await asyncio.sleep(PING_INTERVAL)
                    continue
                response = requests.get(f"{BASE_URL}/", timeout=10)
                response.raise_for_status()
            except Exception as e:
                pass
            await asyncio.sleep(PING_INTERVAL)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ping_self())

threading.Thread(target=start_ping_task, daemon=True).start()

# Initialize
async def initialize_app():
    await validate_token()
    await init_json()
    await application.initialize()
    if BASE_URL:
        webhook_url = f"{BASE_URL}/telegram/webhook"
        await application.bot.set_webhook(webhook_url)

async def validate_token():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe") as resp:
            if resp.status != 200:
                raise ValueError(f"Invalid BOT_TOKEN: {await resp.text()}")

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(initialize_app())
        uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1)
    finally:
        loop.close()
