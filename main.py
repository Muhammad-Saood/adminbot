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
PUBLIC_CHANNEL_USERNAME = os.getenv("PUBLIC_CHANNEL_USERNAME", "@qaidyno804")
PUBLIC_CHANNEL_LINK = f"https://t.me/{PUBLIC_CHANNEL_USERNAME.replace('@', '')}"
MONETAG_ZONE = "9859391"
ADEXIUM_WID = "7de35f31-1b0a-4dbd-8132-d9b725c40e38"
USERS_FILE = "/tmp/users.json"

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
            "monetag_daily_ads_watched": 0,
            "adexium_daily_ads_watched": 0,
            "last_ad_date": None,
            "invited_friends": 0,
            "binance_id": None,
            "invited_by": invited_by,
            "created_at": dt.datetime.now().isoformat(),
            "channel_verified": False
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

async def update_daily_ads(user_id: int, platform: str, ads_watched: int):
    today = dt.datetime.now().date().isoformat()
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        user_data = users[user_id_str]
        if user_data["last_ad_date"] == today:
            user_data[f"{platform}_daily_ads_watched"] += ads_watched
        else:
            user_data["monetag_daily_ads_watched"] = 0
            user_data["adexium_daily_ads_watched"] = 0
            user_data[f"{platform}_daily_ads_watched"] = ads_watched
            user_data["last_ad_date"] = today
        await write_json(users)
        logger.info(f"Updated {platform} ads for {user_id}: {user_data[f'{platform}_daily_ads_watched']}/7")
    else:
        logger.error(f"Cannot update {platform} ads: user {user_id} not found")

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

async def verify_channel_membership(user_id: int) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                json={"chat_id": PUBLIC_CHANNEL_USERNAME, "user_id": user_id}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok") and data.get("result").get("status") in ["member", "administrator", "creator"]:
                        users = await read_json()
                        user_id_str = str(user_id)
                        if user_id_str in users:
                            users[user_id_str]["channel_verified"] = True
                            await write_json(users)
                            logger.info(f"User {user_id} verified channel membership for {PUBLIC_CHANNEL_USERNAME}")
                        return True
                    else:
                        logger.info(f"User {user_id} not a member of channel {PUBLIC_CHANNEL_USERNAME}")
                        return False
                else:
                    logger.error(f"Failed to verify channel membership for {user_id}: {await resp.text()}")
                    return False
    except Exception as e:
        logger.error(f"Error verifying channel membership for {user_id}: {e}")
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
        "monetag_daily_ads_watched": user["monetag_daily_ads_watched"],
        "adexium_daily_ads_watched": user["adexium_daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "invited_by": None,
        "channel_verified": user["channel_verified"]
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_monetag_ad(user_id: int):
    logger.info(f"Monetag ad watch request for {user_id}")
    user = await get_user_data(user_id)
    if not user["channel_verified"]:
        logger.info(f"User {user_id} not verified for channel membership")
        return {"success": False, "message": "Channel membership not verified"}
    
    today = dt.datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["monetag_daily_ads_watched"] >= 7:
        logger.info(f"Monetag ad limit reached for {user_id}")
        return {"success": False, "limit_reached": True}
    
    await update_daily_ads(user_id, "monetag", 1)
    await update_points(user_id, 20.0)
    
    invited_by = user.get("invited_by")
    if invited_by:
        logger.info(f"Granting 2 $DOGS to referrer {invited_by} for {user_id}'s ad")
        await update_points(invited_by, 2.0)
    
    user = await get_user_data(user_id)
    return {
        "success": True,
        "points": user["points"],
        "monetag_daily_ads_watched": user["monetag_daily_ads_watched"]
    }

@app.post("/api/watch_adexium/{user_id}")
async def watch_adexium_ad(user_id: int):
    logger.info(f"Adexium ad watch request for {user_id}")
    user = await get_user_data(user_id)
    if not user["channel_verified"]:
        return {"success": False, "message": "Channel membership not verified"}
    
    today = dt.datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["adexium_daily_ads_watched"] >= 7:
        return {"success": False, "limit_reached": True}
    
    await update_daily_ads(user_id, "adexium", 1)
    await update_points(user_id, 20.0)
    
    invited_by = user.get("invited_by")
    if invited_by:
        logger.info(f"Granting 2 $DOGS to referrer {invited_by} for {user_id}'s ad")
        await update_points(invited_by, 2.0)
    
    user = await get_user_data(user_id)
    return {
        "success": True,
        "points": user["points"],
        "adexium_daily_ads_watched": user["adexium_daily_ads_watched"]
    }

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    binance_id = data["binance_id"]
    if amount < 2000 or not binance_id:
        return {"success": False, "message": "Minimum 2000 $DOGS and Binance ID required"}
    if await withdraw_points(user_id, amount, binance_id):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

@app.post("/api/verify_channel/{user_id}")
async def verify_channel(user_id: int):
    if await verify_channel_membership(user_id):
        return {"success": True, "message": "Channel membership verified"}
    return {"success": False, "message": "You must join the channel first"}

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
    <script src="https://telegram.org/js/telegram-web-app.js?56"></script>
    <script src="//monetag.com/sdk.js" data-zone="{MONETAG_ZONE}" data-sdk="show_{MONETAG_ZONE}"></script>
    <script type="text/javascript" src="https://cdn.tgads.space/assets/js/adexium-widget.min.js"></script>
    <script type="text/javascript">
        document.addEventListener('DOMContentLoaded', () => {
            const adexiumWidget = new AdexiumWidget({wid: '{ADEXIUM_WID}', adFormat: 'interstitial'});
            adexiumWidget.autoMode();
        });
    </script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            background: linear-gradient(135deg, #4b6cb7, #182848);
            min-height: 100vh;
            color: #ffffff;
            padding: 20px;
        }

        .page {
            display: none;
            min-height: 100vh;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding-top: 2rem;
            padding-bottom: 5rem;
        }

        .page.active {
            display: flex;
        }

        .header {
            text-align: center;
            margin-bottom: 2rem;
        }

        .header h2 {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.75rem;
            text-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }

        .header p {
            font-size: 1.125rem;
            font-weight: 400;
            opacity: 0.9;
            margin-bottom: 0.75rem;
        }

        .highlight {
            color: #ffd700;
            font-weight: 600;
        }

        .card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            padding: 1rem;
            border-radius: 1rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
            width: 100%;
            max-width: 400px;
            min-height: 200px;
            text-align: center;
            margin-bottom: 1rem;
            transition: transform 0.3s ease;
        }

        .card:hover {
            transform: translateY(-5px);
        }

        .card h3 {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1rem;
        }

        .card p {
            font-size: 1rem;
            margin-bottom: 1rem;
            opacity: 0.9;
        }

        .ad-provider {
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
        }

        .ad-provider:last-child {
            border-bottom: none;
        }

        .ad-provider h4 {
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
        }

        .nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            display: flex;
            background: rgba(255, 255, 255, 0.1);
            border-top: 1px solid rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
        }

        .nav-btn {
            flex: 1;
            padding: 1rem;
            text-align: center;
            background: none;
            border: none;
            cursor: pointer;
            color: #ffffff;
            font-size: 0.9rem;
            font-weight: 500;
            transition: background 0.3s ease, transform 0.2s ease;
        }

        .nav-btn:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        .nav-btn.active {
            background: rgba(255, 255, 255, 0.25);
            border-radius: 0.5rem 0.5rem 0 0;
        }

        .nav-btn svg {
            width: 24px;
            height: 24px;
            margin: 0 auto 0.25rem;
            stroke: #ffffff;
        }

        .watch-btn, .btn-primary {
            background: #10b981;
            color: #ffffff;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: 600;
            width: 100%;
            margin-bottom: 1rem;
            transition: background 0.2s ease, transform 0.2s ease;
        }

        .watch-btn:hover, .btn-primary:hover {
            background: #059669;
            transform: scale(1.02);
        }

        .join-btn {
            background: #0284c7;
            color: #ffffff;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: 600;
            width: 100%;
            text-decoration: none;
            display: inline-block;
            margin-bottom: 1rem;
            transition: background 0.2s ease, transform 0.2s ease;
        }

        .join-btn:hover {
            background: #026ea5;
            transform: scale(1.02);
        }

        .copy-btn {
            background: #6b7280;
            color: #ffffff;
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 1rem;
            transition: background 0.2s ease, transform 0.2s ease;
        }

        .copy-btn:hover {
            background: #5b616e;
            transform: scale(1.02);
        }

        .withdraw-btn {
            background: #ef4444;
            color: #ffffff;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: 600;
            width: 100%;
            margin-bottom: 1rem;
            transition: background 0.2s ease, transform 0.2s ease;
        }

        .withdraw-btn:hover {
            background: #dc2626;
            transform: scale(1.02);
        }

        .input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 0.5rem;
            background: rgba(255, 255, 255, 0.1);
            color: #ffffff;
            font-size: 1rem;
            margin-bottom: 1rem;
            transition: border 0.2s ease, box-shadow 0.2s ease;
        }

        .input::placeholder {
            color: rgba(255, 255, 255, 0.5);
        }

        .input:focus {
            outline: none;
            border: 1px solid #60a5fa;
            box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2);
        }

        .verify-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.85);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            transition: opacity 0.3s ease;
        }

        .verify-box {
            background: #ffffff;
            padding: 1rem;
            border-radius: 1rem;
            text-align: center;
            max-width: 320px;
            width: 100%;
            margin: 0 1rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            transform: scale(1);
            transition: transform 0.3s ease;
            color: #1f2937;
        }

        .verify-box:hover {
            transform: scale(1.05);
        }

        .verify-box h2 {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 0.75rem;
        }

        .verify-box p {
            font-size: 0.875rem;
            margin-bottom: 1rem;
            opacity: 0.8;
        }

        .verified-btn {
            background: #d1d5db;
            color: #6b7280;
            cursor: not-allowed;
            opacity: 0.7;
            pointer-events: none;
        }

        .break-all {
            word-break: break-all;
        }

        @media (max-width: 640px) {
            .page {
                justify-content: center;
                padding-top: 1.5rem;
                padding-bottom: 4rem;
            }
            .header h2 {
                font-size: 1.75rem;
            }
            .header {
                margin-bottom: 1.5rem;
            }
            .header p {
                font-size: 1rem;
                margin-bottom: 0.5rem;
            }
            .card {
                padding: 0.75rem;
                min-height: 30vh;
                margin-bottom: 0.75rem;
            }
            .card h3 {
                margin-bottom: 0.75rem;
            }
            .card p {
                margin-bottom: 0.75rem;
            }
            .watch-btn, .btn-primary, .join-btn, .copy-btn, .withdraw-btn, .input {
                margin-bottom: 0.75rem;
            }
            .nav-btn {
                font-size: 0.8rem;
            }
            .nav-btn svg {
                width: 20px;
                height: 20px;
            }
            .verify-box {
                max-width: 280px;
                padding: 0.75rem;
            }
        }
    </style>
</head>
<body>
    <div id="verify-overlay" class="verify-overlay">
        <div class="verify-box">
            <h2>Join Our Channel</h2>
            <p>You must join our Telegram channel to start earning!</p>
            <a href="{PUBLIC_CHANNEL_LINK}" class="join-btn" target="_blank">Join Channel</a>
            <button id="verify-btn" class="btn-primary">Verify</button>
        </div>
    </div>
    <div id="tasks" class="page active">
        <div class="header">
            <h2>Tasks</h2>
            <p>ID: <span id="user-id"></span></p>
            <p>Balance: <span id="balance" class="highlight">0.00</span> $DOGS</p>
        </div>
        <div class="card">
            <h3>Watch Ads</h3>
            <p>1 Ad = <span class="highlight">20 $DOGS</span></p>
            <div class="ad-provider">
                <h4>Monetag Ads</h4>
                <p>Daily Limit: <span id="monetag-limit" class="highlight">0/7</span></p>
                <button class="watch-btn" id="monetag-ad-btn">Watch Monetag Ad</button>
            </div>
            <div class="ad-provider">
                <h4>Adexium Ads</h4>
                <p>Daily Limit: <span id="adexium-limit" class="highlight">0/7</span></p>
                <button class="watch-btn" id="adexium-ad-btn">Watch Adexium Ad</button>
            </div>
        </div>
    </div>
    <div id="invite" class="page">
        <div class="header">
            <h2>Invite Friends</h2>
            <p class="small-text">Invite friends by using the link given below and get 10% bonus of friends earning</p>
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
            <h2>Withdraw</h2>
            <p class="highlight">Minimum 2000 $DOGS</p>
        </div>
        <div class="card">
            <input type="number" id="amount" placeholder="Enter amount (min 2000)" class="input">
            <input type="text" id="binance-id" placeholder="Enter Binance ID" class="input">
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

    <script>
        const tg = window.Telegram.WebApp;
        tg.ready();
        const userId = tg.initDataUnsafe.user.id;
        document.getElementById('user-id').textContent = userId;

        function getCachedVerificationStatus() {
            return localStorage.getItem(`channel_verified_${userId}`) === 'true';
        }

        function setCachedVerificationStatus(status) {
            localStorage.setItem(`channel_verified_${userId}`, status);
        }

        async function loadData() {
            try {
                const isVerified = getCachedVerificationStatus();
                const overlay = document.getElementById('verify-overlay');
                if (isVerified) {
                    overlay.style.display = 'none';
                } else {
                    overlay.style.display = 'flex';
                }

                const response = await Promise.race([
                    fetch('/api/user/' + userId),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Request timed out')), 5000))
                ]);
                if (!response.ok) throw new Error('API failed: ' + response.status);
                const data = await response.json();
                document.getElementById('balance').textContent = data.points.toFixed(2);
                document.getElementById('monetag-limit').textContent = data.monetag_daily_ads_watched + '/7';
                document.getElementById('adexium-limit').textContent = data.adexium_daily_ads_watched + '/7';
                document.getElementById('invited-count').textContent = data.invited_friends;
                document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;

                if (data.channel_verified) {
                    setCachedVerificationStatus(true);
                    overlay.style.display = 'none';
                } else {
                    setCachedVerificationStatus(false);
                    overlay.style.display = 'flex';
                }
            } catch (error) {
                console.error('loadData error:', error);
                tg.showAlert('Failed to load data: ' + error.message);
            }
        }

        async function verifyChannel() {
            const verifyBtn = document.getElementById('verify-btn');
            verifyBtn.disabled = true;
            try {
                const response = await Promise.race([
                    fetch('/api/verify_channel/' + userId, { method: 'POST' }),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Request timed out')), 5000))
                ]);
                const data = await response.json();
                if (data.success) {
                    verifyBtn.textContent = 'Verified';
                    verifyBtn.classList.add('verified-btn');
                    document.getElementById('verify-overlay').style.display = 'none';
                    setCachedVerificationStatus(true);
                    tg.showAlert('Channel membership verified!');
                    await loadData();
                } else {
                    tg.showAlert('Please join the channel first!');
                }
            } catch (error) {
                console.error('verifyChannel error:', error);
                tg.showAlert('Failed to verify channel membership: ' + error.message);
            } finally {
                verifyBtn.disabled = false;
            }
        }

        async function watchMonetagAd() {
            const watchBtn = document.getElementById('monetag-ad-btn');
            watchBtn.disabled = true;
            watchBtn.textContent = 'Watching...';
            try {
                await window[`show_{MONETAG_ZONE}`]();
                const response = await Promise.race([
                    fetch('/api/watch_ad/' + userId, { method: 'POST' }),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Request timed out')), 5000))
                ]);
                const data = await response.json();
                if (data.success) {
                    tg.showAlert('Monetag ad watched! +20 $DOGS');
                } else if (data.limit_reached) {
                    tg.showAlert('Monetag daily limit reached!');
                } else if (data.message === 'Channel membership not verified') {
                    tg.showAlert('Please verify channel membership first!');
                    setCachedVerificationStatus(false);
                    document.getElementById('verify-overlay').style.display = 'flex';
                } else {
                    tg.showAlert('Error watching Monetag ad');
                }
                await loadData();
            } catch (error) {
                console.error('Monetag ad error:', error);
                tg.showAlert('Monetag ad failed to load: ' + error.message);
            } finally {
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Monetag Ad';
            }
        }

        async function watchAdexiumAd() {
            const watchBtn = document.getElementById('adexium-ad-btn');
            watchBtn.disabled = true;
            watchBtn.textContent = 'Watching...';
            try {
                const response = await Promise.race([
                    fetch('/api/watch_adexium/' + userId, { method: 'POST' }),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Request timed out')), 5000))
                ]);
                const data = await response.json();
                if (data.success) {
                    tg.showAlert('Adexium ad watched! +20 $DOGS');
                } else if (data.limit_reached) {
                    tg.showAlert('Adexium daily limit reached!');
                } else if (data.message === 'Channel membership not verified') {
                    tg.showAlert('Please verify channel membership first!');
                    setCachedVerificationStatus(false);
                    document.getElementById('verify-overlay').style.display = 'flex';
                } else {
                    tg.showAlert('Error watching Adexium ad');
                }
                await loadData();
            } catch (error) {
                console.error('Adexium ad error:', error);
                tg.showAlert('Adexium ad failed to load: ' + error.message);
            } finally {
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Adexium Ad';
            }
        }

        async function copyLink() {
            try {
                const link = document.getElementById('invite-link').textContent;
                await navigator.clipboard.writeText(link);
                tg.showAlert('Link copied!');
            } catch (error) {
                console.error('copyLink error:', error);
                tg.showAlert('Failed to copy link: ' + error.message);
            }
        }

        async function withdraw() {
            const amount = parseFloat(document.getElementById('amount').value);
            const binanceId = document.getElementById('binance-id').value;
            if (amount < 2000 || !binanceId) {
                tg.showAlert('Minimum 2000 $DOGS and Binance ID required!');
                return;
            }
            try {
                const response = await Promise.race([
                    fetch('/api/withdraw/' + userId, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({amount, binance_id: binanceId})
                    }),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Request timed out')), 5000))
                ]);
                const data = await response.json();
                if (data.success) {
                    tg.showAlert('Withdraw successful! Credited within 24 hours.');
                    document.getElementById('amount').value = '';
                    document.getElementById('binance-id').value = '';
                    await loadData();
                } else {
                    tg.showAlert(data.message || 'Withdraw failed');
                }
            } catch (error) {
                console.error('withdraw error:', error);
                tg.showAlert('Withdraw failed: ' + error.message);
            }
        }

        function showPage(page) {
            const overlay = document.getElementById('verify-overlay');
            if (overlay && overlay.style.display === 'flex') {
                console.log('Navigation blocked: Verification overlay is visible');
                return;
            }
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            const targetPage = document.getElementById(page);
            if (targetPage) {
                targetPage.classList.add('active');
            } else {
                console.error(`Page ${page} not found`);
                return;
            }
            document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
            const targetBtn = document.querySelector(`.nav-btn[data-page="${page}"]`);
            if (targetBtn) {
                targetBtn.classList.add('active');
            } else {
                console.error(`Button for page ${page} not found`);
            }
        }

        document.getElementById('verify-btn').addEventListener('click', verifyChannel);
        document.getElementById('monetag-ad-btn').addEventListener('click', watchMonetagAd);
        document.getElementById('adexium-ad-btn').addEventListener('click', watchAdexiumAd);
        loadData();
    </script>
</body>
</html>
"""
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE).replace("{BOT_USERNAME}", BOT_USERNAME).replace("{PUBLIC_CHANNEL_LINK}", PUBLIC_CHANNEL_LINK).replace("{ADEXIUM_WID}", ADEXIUM_WID))

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

# ----------------- SELF-PINGING TASK -----------------
PING_INTERVAL = 240  # 4 minutes in seconds

def start_ping_task():
    async def ping_self():
        while True:
            try:
                if not BASE_URL:
                    logger.error("BASE_URL is not set, cannot ping self")
                    await asyncio.sleep(PING_INTERVAL)
                    continue
                current_time = dt.datetime.now(dt.UTC).strftime("%H:%M:%S UTC")
                logger.info(f"Pinging self at {BASE_URL} at {current_time}")
                response = requests.get(f"{BASE_URL}/", timeout=10)
                response.raise_for_status()
                logger.info(f"Self-ping successful: {response.status_code} at {current_time}")
            except requests.exceptions.Timeout:
                logger.error(f"Self-ping timed out for {BASE_URL} at {current_time}")
            except requests.exceptions.ConnectionError:
                logger.error(f"Self-ping connection error for {BASE_URL} at {current_time}")
            except Exception as e:
                logger.error(f"Self-ping failed: {str(e)} at {current_time}")
            await asyncio.sleep(PING_INTERVAL)

    async def run_ping():
        await ping_self()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_ping())

# Start the ping task in a separate thread
threading.Thread(target=start_ping_task, daemon=True).start()

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
