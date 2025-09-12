import os
import json
import aiofiles
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
import threading
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio
from typing import Optional, Tuple

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")  # New: Load bot username from env
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")  # e.g., https://your-app-name.herokuapp.com
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"
USERS_FILE = "/tmp/users.json"  # Use /tmp for Heroku compatibility

app = FastAPI()

# Initialize JSON file (runs on startup, but not critical if fails)
async def init_json():
    try:
        async with aiofiles.open(USERS_FILE, mode='a') as f:
            pass
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            content = await f.read()
            if not content.strip():
                async with aiofiles.open(USERS_FILE, mode='w') as f:
                    await f.write(json.dumps({}))
        print(f"JSON storage initialized at {USERS_FILE}")
    except Exception as e:
        print(f"Warning: Could not initialize JSON file: {e} (will create on first use)")

# User data functions
async def get_or_create_user(user_id: int, invited_by: Optional[int] = None) -> Tuple[dict, bool]:
    users = {}
    file_exists = False
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            content = await f.read()
            if content.strip():
                users = json.loads(content)
                file_exists = True
    except FileNotFoundError:
        print(f"users.json not found, creating new: {USERS_FILE}")
    except Exception as e:
        print(f"Error reading users.json: {e}")
    
    user_id_str = str(user_id)
    is_new = user_id_str not in users  # New: Track if user is newly created
    if is_new:
        users[user_id_str] = {
            "user_id": user_id,
            "points": 0.0,
            "daily_ads_watched": 0,
            "last_ad_date": None,
            "invited_friends": 0,
            "binance_id": None,
            "invited_by": invited_by,
            "created_at": datetime.now().isoformat()
        }
        try:
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
            print(f"Created new user {user_id} in JSON")
        except Exception as e:
            print(f"Error writing new user to JSON: {e}")
    
    return users[user_id_str], is_new  # New: Return tuple (user, is_new)

async def update_points(user_id: int, points: float):
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users:
            users[user_id_str]["points"] += points
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
    except Exception as e:
        print(f"Error updating points for user {user_id}: {e}")

async def update_daily_ads(user_id: int, ads_watched: int):
    today = datetime.now().date().isoformat()
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users:
            if users[user_id_str]["last_ad_date"] == today:
                users[user_id_str]["daily_ads_watched"] += ads_watched
            else:
                users[user_id_str]["daily_ads_watched"] = ads_watched
                users[user_id_str]["last_ad_date"] = today
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
    except Exception as e:
        print(f"Error updating daily ads for user {user_id}: {e}")

async def add_invited_friend(user_id: int):
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users:
            users[user_id_str]["invited_friends"] += 1
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
    except Exception as e:
        print(f"Error adding invited friend for user {user_id}: {e}")

async def set_binance_id(user_id: int, binance_id: str):
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users:
            users[user_id_str]["binance_id"] = binance_id
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
    except Exception as e:
        print(f"Error setting binance_id for user {user_id}: {e}")

async def withdraw_points(user_id: int, amount: float, binance_id: str):
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users and users[user_id_str]["points"] >= amount:
            users[user_id_str]["points"] -= amount
            users[user_id_str]["binance_id"] = binance_id
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
            await application.bot.send_message(
                chat_id=ADMIN_CHANNEL_ID,
                text=f"Withdrawal Request:\nUser ID: {user_id}\nAmount: {amount} $DOGS\nBinance ID: {binance_id}"
            )
            return True
    except Exception as e:
        print(f"Error processing withdrawal for user {user_id}: {e}")
    return False

# API endpoints for Mini App
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user, _ = await get_or_create_user(user_id)  # New: Unpack tuple, ignore is_new
    return {
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "invited_by": user.get("invited_by")  # New: Include invited_by
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int):
    user, _ = await get_or_create_user(user_id)  # New: Unpack tuple
    today = datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["daily_ads_watched"] >= 30:
        return {"success": False, "limit_reached": True}
    
    await update_daily_ads(user_id, 1)
    await update_points(user_id, 20.0)
    if user.get("invited_by"):
        await update_points(user["invited_by"], 2.0)  # 10% of 20 $DOGS
    
    user, _ = await get_or_create_user(user_id)  # New: Unpack tuple
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
    if amount < 2000 or not binance_id:
        return {"success": False, "message": "Minimum 2000 $DOGS and Binance ID required"}
    if await withdraw_points(user_id, amount, binance_id):
        return {"success": True}
    return {"success": False, "message": "Insufficient balance"}

# Mini App HTML with Monetag SDK
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
            const response = await fetch('/api/user/' + userId);
            const data = await response.json();
            document.getElementById('balance').textContent = data.points.toFixed(2);
            document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
            document.getElementById('invited-count').textContent = data.invited_friends;
            document.getElementById('invite-link').textContent = tg.initDataUnsafe.startParam ? 'https://t.me/{BOT_USERNAME}?start=' + tg.initDataUnsafe.startParam : 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
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
                        document.getElementById('balance').textContent = data.points.toFixed(2);
                        document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
                        tg.showAlert('Ad watched! +20 $DOGS');
                    }} else if (data.limit_reached) {{
                        tg.showAlert('Daily limit reached!');
                    }} else {{
                        tg.showAlert('Error watching ad');
                    }}
                    loadData();
                }}).catch(error => {{
                    tg.showAlert('Ad failed to load');
                    console.error('Monetag ad error:', error);
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
            if (amount < 2000 || !binanceId) {{
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
                tg.showAlert('Withdraw successful! Credited to Binance within 24 hours.');
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

# Telegram bot setup for launching Mini App
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    invited_by = None
    if args and args[0].startswith("ref"):
        try:
            invited_by = int(args[0].replace("ref", ""))
        except ValueError:
            invited_by = None
    
    # New: Check for existing user and prevent duplicate/self-referrals
    existing_user, is_new = await get_or_create_user(update.effective_user.id)
    if is_new and invited_by and invited_by != update.effective_user.id and existing_user.get("invited_by") is None:
        await get_or_create_user(update.effective_user.id, invited_by)  # Set invited_by
        await add_invited_friend(invited_by)  # Increment referrer's count
    
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Launch the Mini App!", reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

async def main():
    await init_json()
    await application.initialize()
    await application.start()
    # New: Run uvicorn in a separate thread to allow Telegram polling
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=PORT), daemon=True).start()
    await application.run_polling(drop_pending_updates=True)  # New: Use run_polling instead of updater.start_polling

if __name__ == "__main__":
    asyncio.run(main())
