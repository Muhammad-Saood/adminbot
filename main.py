import os
import json
import aiofiles
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio
from typing import Optional

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")  # e.g., https://your-app-name.herokuapp.com
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"
USERS_FILE = "/tmp/users.json"  # Use /tmp for Heroku compatibility

app = FastAPI()

# Mount static files directory to serve favicon.ico
app.mount("/static", StaticFiles(directory="static"), name="static")  # Create a 'static' folder with favicon.ico

# Initialize JSON file silently
async def init_json():
    try:
        async with aiofiles.open(USERS_FILE, mode='a') as f:
            pass
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            content = await f.read()
            if not content.strip():
                async with aiofiles.open(USERS_FILE, mode='w') as f:
                    await f.write(json.dumps({}))
    except Exception as e:
        pass  # Silent initialization

# User data functions
async def get_or_create_user(user_id: int, invited_by: Optional[int] = None):
    users = {}
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            content = await f.read()
            if content.strip():
                users = json.loads(content)
    except FileNotFoundError:
        pass  # Silent file creation
    except Exception as e:
        pass  # Silent error handling
    
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
            "created_at": datetime.now().isoformat()
        }
        try:
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
        except Exception as e:
            pass  # Silent write
    return users[user_id_str], is_new

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
        pass  # Silent update

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
        pass  # Silent update

async def add_invited_friend(user_id: int):
    try:
        async with aiofiles.open(USERS_FILE, mode='r') as f:
            users = json.loads(await f.read())
        
        user_id_str = str(user_id)
        if user_id_str in users:
            users[user_id_str]["invited_friends"] += 1
            async with aiofiles.open(USERS_FILE, mode='w') as f:
                await f.write(json.dumps(users, indent=2))
            return True
        return False
    except Exception as e:
        return False  # Silent error

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
        pass  # Silent update

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
        pass
    return False

# Self-ping task
async def self_ping():
    if not BASE_URL:
        return
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(f"{BASE_URL}/") as response:
                    pass  # Silent ping
            except Exception:
                pass  # Silent error
            await asyncio.sleep(240)  # 4 minutes

# API endpoints for Mini App
@app.get("/")
async def root():
    return {"status": "DOGS Earn App is running!"}

@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user, _ = await get_or_create_user(user_id)
    return {
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"]
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int):
    user, _ = await get_or_create_user(user_id)
    today = datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["daily_ads_watched"] >= 30:
        return {"success": False, "limit_reached": True}
    
    ad_points = 20.0  # Points for watching one ad
    await update_daily_ads(user_id, 1)
    await update_points(user_id, ad_points)
    if user.get("invited_by"):
        bonus_points = ad_points * 0.05  # 5% of friend's earnings
        await update_points(user["invited_by"], bonus_points)
    
    user, _ = await get_or_create_user(user_id)
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
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
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
                if (!response.ok) {{
                    throw new Error('Failed to load data');
                }}
                const data = await response.json();
                document.getElementById('balance').textContent = data.points.toFixed(2);
                document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
                document.getElementById('invited-count').textContent = data.invited_friends;
                const myRefParam = 'ref' + userId;
                document.getElementById('invite-link').textContent = 'https://t.me/jdsrhukds_bot?start=' + myRefParam;
            }} catch (error) {{
                tg.showAlert('Failed to load data: ' + error.message);
                console.error('Load data error:', error);
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
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE))

# Telegram bot setup for launching Mini App
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    invited_by = None
    if args and args[0].startswith("ref"):
        try:
            invited_by = int(args[0].replace("ref", ""))
            await get_or_create_user(invited_by)
            await add_invited_friend(invited_by)
        except ValueError:
            pass
    await get_or_create_user(update.effective_user.id, invited_by)
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Launch the Mini App!", reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

async def main():
    await init_json()
    asyncio.create_task(self_ping())  # Start self-ping task
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    uvicorn.run(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    asyncio.run(main())
