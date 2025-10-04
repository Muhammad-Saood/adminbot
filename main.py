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
from fastapi.responses import HTMLResponse
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
PUBLIC_CHANNEL_USERNAME = os.getenv("PUBLIC_CHANNEL_USERNAME", "@ClicktoEarnAnnouncements")
PUBLIC_CHANNEL_LINK = f"https://t.me/{PUBLIC_CHANNEL_USERNAME.replace('@', '')}"
MONETAG_ZONE = "9859391"
MONETAG_ZONE1 = "9930174"
MONETAG_ZONE2 = "9930913"
MONETAG_ZONE3 = "9930950"
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
        user_data["monetag_daily_ads_watched"] = 0
        user_data["monetag_zone1_daily_ads_watched"] = 0
        user_data["monetag_zone2_daily_ads_watched"] = 0
        user_data["monetag_zone3_daily_ads_watched"] = 0
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
            "monetag_daily_ads_watched": 0,
            "monetag_zone1_daily_ads_watched": 0,
            "monetag_zone2_daily_ads_watched": 0,
            "monetag_zone3_daily_ads_watched": 0,
            "last_ad_date": None,
            "invited_friends": 0,
            "easypaisa_jazzcash": None,
            "invited_by": invited_by,
            "created_at": dt.datetime.now().isoformat(),
            "channel_verified": False,
            "last_ad_start_time": None
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
            user_data["monetag_zone1_daily_ads_watched"] = 0
            user_data["monetag_zone2_daily_ads_watched"] = 0
            user_data["monetag_zone3_daily_ads_watched"] = 0
            user_data[f"{platform}_daily_ads_watched"] = ads_watched
            user_data["last_ad_date"] = today
        await write_json(users)
    else:
        logger.error(f"Cannot update {platform} ads: user {user_id} not found")

async def add_invited_friend(user_id: int):
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users:
        users[user_id_str]["invited_friends"] += 1
        await write_json(users)
    else:
        logger.error(f"Cannot add friend: user {user_id} not found")

async def withdraw_points(user_id: int, amount: float, easypaisa_jazzcash: str) -> bool:
    users = await read_json()
    user_id_str = str(user_id)
    if user_id_str in users and users[user_id_str]["points"] >= amount:
        users[user_id_str]["points"] -= amount
        users[user_id_str]["easypaisa_jazzcash"] = easypaisa_jazzcash
        await write_json(users)
        await application.bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text=f"Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} RS\nEasypaisa/Jazzcash: {easypaisa_jazzcash}"
        )
        return True
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
                        return True
                    return False
                return False
    except Exception as e:
        logger.error(f"Error verifying channel membership for {user_id}: {e}")
        return False

# API endpoints
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user = await get_user_data(user_id)
    total_ads_watched = (
        user["monetag_daily_ads_watched"] +
        user["monetag_zone1_daily_ads_watched"] +
        user["monetag_zone2_daily_ads_watched"] +
        user["monetag_zone3_daily_ads_watched"]
    )
    return {
        "points": user["points"],
        "total_daily_ads_watched": total_ads_watched,
        "monetag_daily_ads_watched": user["monetag_daily_ads_watched"],
        "monetag_zone1_daily_ads_watched": user["monetag_zone1_daily_ads_watched"],
        "monetag_zone2_daily_ads_watched": user["monetag_zone2_daily_ads_watched"],
        "monetag_zone3_daily_ads_watched": user["monetag_zone3_daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "channel_verified": user["channel_verified"]
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int, request: Request):
    user = await get_user_data(user_id)
    if not user["channel_verified"]:
        return {"success": False, "message": "Channel membership not verified"}

    today = dt.datetime.now().date().isoformat()
    total_ads_watched = (
        user["monetag_daily_ads_watched"] +
        user["monetag_zone1_daily_ads_watched"] +
        user["monetag_zone2_daily_ads_watched"] +
        user["monetag_zone3_daily_ads_watched"]
    )

    if user["last_ad_date"] == today and total_ads_watched >= 28:
        return {"success": False, "limit_reached": True}

    data = await request.json()
    ad_completed = data.get("ad_completed", False)

    if not ad_completed:
        return {"success": False, "message": "Ad not completely watched or not opened ad website"}

    # Determine which zone to use
    zone = None
    zone_key = None
    if user["monetag_daily_ads_watched"] < 7:
        zone = MONETAG_ZONE
        zone_key = "monetag"
    elif user["monetag_zone1_daily_ads_watched"] < 7:
        zone = MONETAG_ZONE1
        zone_key = "monetag_zone1"
    elif user["monetag_zone2_daily_ads_watched"] < 7:
        zone = MONETAG_ZONE2
        zone_key = "monetag_zone2"
    elif user["monetag_zone3_daily_ads_watched"] < 7:
        zone = MONETAG_ZONE3
        zone_key = "monetag_zone3"
    else:
        return {"success": False, "limit_reached": True}

    await update_daily_ads(user_id, zone_key, 1)
    await update_points(user_id, 0.5)

    invited_by = user.get("invited_by")
    if invited_by:
        await update_points(invited_by, 0.035)

    user = await get_user_data(user_id)
    total_ads_watched = (
        user["monetag_daily_ads_watched"] +
        user["monetag_zone1_daily_ads_watched"] +
        user["monetag_zone2_daily_ads_watched"] +
        user["monetag_zone3_daily_ads_watched"]
    )
    return {
        "success": True,
        "points": user["points"],
        "total_daily_ads_watched": total_ads_watched,
        "monetag_daily_ads_watched": user["monetag_daily_ads_watched"],
        "monetag_zone1_daily_ads_watched": user["monetag_zone1_daily_ads_watched"],
        "monetag_zone2_daily_ads_watched": user["monetag_zone2_daily_ads_watched"],
        "monetag_zone3_daily_ads_watched": user["monetag_zone3_daily_ads_watched"]
    }

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: int, request: Request):
    data = await request.json()
    amount = float(data["amount"])
    easypaisa_jazzcash = data["easypaisa_jazzcash"]
    if amount < 150 or not easypaisa_jazzcash:
        return {"success": False, "message": "Minimum 150 RS and Easypaisa/Jazzcash required"}
    if await withdraw_points(user_id, amount, easypaisa_jazzcash):
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
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE}" data-sdk="show_{MONETAG_ZONE}"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE1}" data-sdk="show_{MONETAG_ZONE1}"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE2}" data-sdk="show_{MONETAG_ZONE2}"></script>
    <script src="//libtl.com/sdk.js" data-zone="{MONETAG_ZONE3}" data-sdk="show_{MONETAG_ZONE3}"></script>
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

        .join-btn {
            background: #0284c7;
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            font-size: 1rem;
            font-weight: bold;
            width: 100%;
            text-decoration: none;
            display: inline-block;
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
        }

        .verify-box {
            background: white;
            padding: 1rem;
            border-radius: 1rem;
            text-align: center;
            max-width: 320px;
            width: 100%;
            margin: 0 1rem;
            color: black;
        }

        .verify-box h2 {
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 0.75rem;
        }

        .verify-box p {
            font-size: 0.875rem;
            margin-bottom: 1rem;
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
            <h2>📢 Join Announcements 📢</h2>
            <p>Join Click to Earn Official Announcements Channel and verify your account to start earning!</p>
            <a href="{PUBLIC_CHANNEL_LINK}" class="join-btn" target="_blank">Join Channel</a>
            <button id="verify-btn" class="btn-primary">Verify</button>
        </div>
    </div>
    <div id="tasks" class="page active">
        <div class="header">
            <div class="user-info">
                <div class="id-card">ID: <span id="user-id"></span></div>
                <div class="balance-card">Balance: <span id="balance" class="highlight">0.00</span> RS</div>
            </div>
            <h2>📝 Task 📝</h2>
            <p>💰 Start earning instantly – get 0.5 RS for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings 💰</p>
        </div>
        <div class="card">
            <h2>🚀 Watch Ads 🚀</h2>
            <div class="ad-info">
                <div class="small-card">1 AD = 0.5 RS</div>
                <div class="small-card">Daily Limit: <span id="ad-limit" class="highlight">0/28</span></div>
            </div>
            <button class="watch-btn" id="ad-btn">Watch Ad</button>
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
            <p class="highlight">Minimum withdrawal amount is 150 RS</p>
        </div>
        <div class="card">
            <input type="number" id="amount" placeholder="Enter amount (min 150 RS)" class="input">
            <input type="text" id="easypaisa-jazzcash" placeholder="Enter Easypaisa/Jazzcash Number" class="input">
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

        const MONETAG_ZONE = "{MONETAG_ZONE}";
        const MONETAG_ZONE1 = "{MONETAG_ZONE1}";
        const MONETAG_ZONE2 = "{MONETAG_ZONE2}";
        const MONETAG_ZONE3 = "{MONETAG_ZONE3}";

        let adStartTime = null;
        let adCompleted = false;

        function getCachedVerificationStatus() {
            return localStorage.getItem(`channel_verified_${userId}`) === 'true';
        }

        function setCachedVerificationStatus(status) {
            localStorage.setItem(`channel_verified_${userId}`, status);
        }

        function getCachedUserData() {
            const cachedData = localStorage.getItem(`user_data_${userId}`);
            return cachedData ? JSON.parse(cachedData) : null;
        }

        function setCachedUserData(data) {
            localStorage.setItem(`user_data_${userId}`, JSON.stringify({
                points: data.points,
                total_daily_ads_watched: data.total_daily_ads_watched,
                monetag_daily_ads_watched: data.monetag_daily_ads_watched,
                monetag_zone1_daily_ads_watched: data.monetag_zone1_daily_ads_watched,
                monetag_zone2_daily_ads_watched: data.monetag_zone2_daily_ads_watched,
                monetag_zone3_daily_ads_watched: data.monetag_zone3_daily_ads_watched,
                invited_friends: data.invited_friends,
                channel_verified: data.channel_verified
            }));
        }

        async function loadData() {
            try {
                // Load cached data immediately
                const cachedData = getCachedUserData();
                const overlay = document.getElementById('verify-overlay');
                if (cachedData) {
                    document.getElementById('balance').textContent = cachedData.points.toFixed(2);
                    document.getElementById('ad-limit').textContent = cachedData.total_daily_ads_watched + '/28';
                    document.getElementById('invited-count').textContent = cachedData.invited_friends;
                    document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
                    if (cachedData.channel_verified) {
                        setCachedVerificationStatus(true);
                        overlay.style.display = 'none';
                    } else {
                        setCachedVerificationStatus(false);
                        overlay.style.display = 'flex';
                    }
                } else {
                    // Show default state for first-time users
                    document.getElementById('balance').textContent = '0.00';
                    document.getElementById('ad-limit').textContent = '0/28';
                    document.getElementById('invited-count').textContent = '0';
                    document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
                    overlay.style.display = 'flex';
                    // Add loading indicators
                    document.getElementById('balance').classList.add('loading');
                    document.getElementById('ad-limit').classList.add('loading');
                    document.getElementById('invited-count').classList.add('loading');
                }

                // Fetch fresh data from API
                const response = await fetch('/api/user/' + userId);
                const data = await response.json();
                // Update UI with fresh data
                document.getElementById('balance').textContent = data.points.toFixed(2);
                document.getElementById('balance').classList.remove('loading');
                document.getElementById('ad-limit').textContent = data.total_daily_ads_watched + '/28';
                document.getElementById('ad-limit').classList.remove('loading');
                document.getElementById('invited-count').textContent = data.invited_friends;
                document.getElementById('invited-count').classList.remove('loading');
                document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;

                if (data.channel_verified) {
                    setCachedVerificationStatus(true);
                    overlay.style.display = 'none';
                } else {
                    setCachedVerificationStatus(false);
                    overlay.style.display = 'flex';
                }

                // Cache the fresh data
                setCachedUserData(data);
            } catch (error) {
                // If API fails, keep cached data or show default
                if (!getCachedUserData()) {
                    document.getElementById('balance').textContent = '0.00';
                    document.getElementById('ad-limit').textContent = '0/28';
                    document.getElementById('invited-count').textContent = '0';
                    document.getElementById('balance').classList.remove('loading');
                    document.getElementById('ad-limit').classList.remove('loading');
                    document.getElementById('invited-count').classList.remove('loading');
                }
                tg.showAlert('Failed to load data');
            }
        }

        async function verifyChannel() {
            const verifyBtn = document.getElementById('verify-btn');
            verifyBtn.disabled = true;
            try {
                const response = await fetch('/api/verify_channel/' + userId, { method: 'POST' });
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
                tg.showAlert('Failed to verify channel membership');
            } finally {
                verifyBtn.disabled = false;
            }
        }

        async function watchAd() {
            const watchBtn = document.getElementById('ad-btn');
            watchBtn.disabled = true;
            watchBtn.textContent = 'Watching...';
            try {
                const userResponse = await fetch('/api/user/' + userId);
                const userData = await userResponse.json();

                let zone;
                if (userData.monetag_daily_ads_watched < 7) {
                    zone = MONETAG_ZONE;
                } else if (userData.monetag_zone1_daily_ads_watched < 7) {
                    zone = MONETAG_ZONE1;
                } else if (userData.monetag_zone2_daily_ads_watched < 7) {
                    zone = MONETAG_ZONE2;
                } else if (userData.monetag_zone3_daily_ads_watched < 7) {
                    zone = MONETAG_ZONE3;
                } else {
                    tg.showAlert('Daily ad limit reached!');
                    await loadData();
                    watchBtn.disabled = false;
                    watchBtn.textContent = 'Watch Ad';
                    return;
                }

                adStartTime = Date.now();
                adCompleted = false;

                // Start a timer to check ad completion
                setTimeout(() => {
                    adCompleted = true;
                }, 17000); // 17 seconds

                await window[`show_${zone}`]();

                // Check if ad was watched for at least 17 seconds
                const response = await fetch('/api/watch_ad/' + userId, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ ad_completed: adCompleted })
                });
                const data = await response.json();
                if (data.success) {
                    tg.showAlert('Ad watched! +0.5 RS');
                } else if (data.limit_reached) {
                    tg.showAlert('Daily ad limit reached!');
                } else if (data.message === 'Channel membership not verified') {
                    tg.showAlert('Please verify channel membership first!');
                    setCachedVerificationStatus(false);
                    document.getElementById('verify-overlay').style.display = 'flex';
                } else if (data.message === 'Ad not completely watched or not opened ad website') {
                    tg.showAlert('Ad not completely watched or not opened ad website');
                } else {
                    tg.showAlert('Error watching ad');
                }
                await loadData();
            } catch (error) {
                tg.showAlert('Ad failed to load. Please turn off ad blocker or VPN');
            } finally {
                adStartTime = null;
                adCompleted = false;
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Ad';
            }
        }

        async function copyLink() {
            try {
                const link = document.getElementById('invite-link').textContent;
                await navigator.clipboard.writeText(link);
                tg.showAlert('Link copied!');
            } catch (error) {
                tg.showAlert('Failed to copy link');
            }
        }

        async function withdraw() {
            const amount = parseFloat(document.getElementById('amount').value);
            const easypaisaJazzcash = document.getElementById('easypaisa-jazzcash').value;
            if (amount < 150 || !easypaisaJazzcash) {
                tg.showAlert('Minimum 150 RS and Easypaisa/Jazzcash number required!');
                return;
            }
            const response = await fetch('/api/withdraw/' + userId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({amount, easypaisa_jazzcash: easypaisaJazzcash})
            });
            const data = await response.json();
            if (data.success) {
                tg.showAlert('Withdraw successful! Credited within 24 hours.');
                document.getElementById('amount').value = '';
                document.getElementById('easypaisa-jazzcash').value = '';
                await loadData();
            } else {
                tg.showAlert(data.message || 'Withdraw failed');
            }
        }

        function showPage(page) {
            const overlay = document.getElementById('verify-overlay');
            if (overlay && overlay.style.display === 'flex') {
                return;
            }
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(page).classList.add('active');
            document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelector(`.nav-btn[data-page="${page}"]`).classList.add('active');

            // Check if ad was not watched for 17 seconds
            if (adStartTime && !adCompleted && page === 'tasks') {
                const timeElapsed = (Date.now() - adStartTime) / 1000;
                if (timeElapsed < 17) {
                    adCompleted = false;
                }
            }
        }

        document.getElementById('verify-btn').addEventListener('click', verifyChannel);
        document.getElementById('ad-btn').addEventListener('click', watchAd);
        loadData();
    </script>
</body>
</html>
"""
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE).replace("{MONETAG_ZONE1}", MONETAG_ZONE1).replace("{MONETAG_ZONE2}", MONETAG_ZONE2).replace("{MONETAG_ZONE3}", MONETAG_ZONE3).replace("{BOT_USERNAME}", BOT_USERNAME).replace("{PUBLIC_CHANNEL_LINK}", PUBLIC_CHANNEL_LINK))

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
        welcome_text = "🎉 Welcome to Click to Earn! 🎉 💰 Start earning instantly – get 0.5 RS for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings. ✅ Instant withdraw ✅ Easypaisa/Jazzcash 🚀 Open Mini App , and start your earning!"
    else:
        welcome_text = "🎉 Welcome to Click to Earn! 🎉 💰 Start earning instantly – get 0.5 RS for every ad you watch! 👥 Invite friends and enjoy 7% referral bonus on their earnings. ✅ Instant withdraw ✅ Easypaisa/Jazzcash 🚀 Open Mini App, and start your earning!"
    
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
