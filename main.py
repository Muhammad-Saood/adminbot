import json
import os
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from datetime import datetime, timezone
import logging

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONETAG_ZONE = os.getenv("MONETAG_ZONE", "YOUR_MONETAG_ZONE_ID")
USERS_FILE = "/tmp/users.json"

# Load or initialize users data
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    else:
        logger.info(f"{USERS_FILE} not found, creating new")
        users = {}
        save_users(users)
        return users

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

# Self-ping to prevent sleep
async def self_ping():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://clever-lucine-infinityearn2x-bot-6fb68bd3.koyeb.app/") as response:
                    logger.info(f"Self-ping status: {response.status}")
        except Exception as e:
            logger.error(f"Self-ping error: {e}")
        await asyncio.sleep(240)  # Every 4 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(self_ping())

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
        const userId = tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : null;
        const startParam = tg.initDataUnsafe.startParam || '';
        document.getElementById('user-id').textContent = userId || 'Unknown';

        async function loadData() {{
            if (!userId) {{
                tg.showAlert('User ID not found. Please restart the app.');
                return;
            }}
            console.log('Start param:', startParam); // Debug log
            // Process referral from start_param if present
            if (startParam && startParam.startsWith('ref')) {{
                try {{
                    const response = await fetch(`/api/init_referral/${{userId}}`, {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{start_param: startParam}})
                    }});
                    const data = await response.json();
                    if (data.success) {{
                        tg.showAlert(`Referral set! Invited by ${{data.invited_by}}`);
                    }} else {{
                        console.error('Referral failed:', data.message);
                        tg.showAlert('Failed to process referral: ' + data.message);
                    }}
                }} catch (error) {{
                    console.error('Error processing referral:', error);
                    tg.showAlert('Error processing referral. Please try again.');
                }}
            }}
            
            // Load user data
            try {{
                const response = await fetch('/api/user/' + userId);
                const data = await response.json();
                document.getElementById('balance').textContent = data.points.toFixed(2);
                document.getElementById('daily-limit').textContent = data.daily_ads_watched + '/30';
                document.getElementById('invited-count').textContent = data.invited_friends;
                document.getElementById('invite-link').textContent = `https://t.me/jdsrhukds_bot?start=ref${{userId}}`;
            }} catch (error) {{
                console.error('Error loading user data:', error);
                tg.showAlert('Failed to load user data. Please try again.');
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
                        tg.showAlert('Error watching ad: ' + data.message);
                    }}
                }}).catch(error => {{
                    tg.showAlert('Ad failed to load');
                    console.error('Monetag ad error:', error);
                }});
            }} finally {{
                watchBtn.disabled = false;
                watchBtn.textContent = 'Watch Ad';
                await loadData();
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
            try {{
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
                    await loadData();
                }} else {{
                    tg.showAlert(data.message || 'Withdraw failed');
                }}
            }} catch (error) {{
                console.error('Error processing withdrawal:', error);
                tg.showAlert('Withdrawal failed. Please try again.');
            }}
        }}

        function showPage(page) {{
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(page).classList.add('active');
            document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        }}

        // Load initial data
        loadData();
    </script>
</body>
</html>
    """
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE))

@app.get("/api/user/{user_id}")
async def get_user(user_id: str):
    users = load_users()
    if user_id not in users:
        users[user_id] = {
            "points": 0.0,
            "daily_ads_watched": 0,
            "last_ad_date": "",
            "invited_friends": 0,
            "invited_by": None
        }
        logger.info(f"Created new user {user_id} with invited_by: None")
        save_users(users)
    return users[user_id]

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: str):
    users = load_users()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user = users[user_id]
    
    if user["last_ad_date"] != today:
        user["daily_ads_watched"] = 0
        user["last_ad_date"] = today
    
    if user["daily_ads_watched"] >= 30:
        return {"success": False, "limit_reached": True, "message": "Daily ad limit reached"}
    
    user["daily_ads_watched"] += 1
    user["points"] += 20.0
    logger.info(f"Updated daily ads for user {user_id}: {user['daily_ads_watched']}")
    logger.info(f"Updated points for user {user_id}: +20.0")
    
    # Update referrer's points (5% of earned points)
    if user["invited_by"]:
        referrer_id = user["invited_by"]
        if referrer_id in users:
            referrer_points = 20.0 * 0.05
            users[referrer_id]["points"] += referrer_points
            logger.info(f"Added {referrer_points} points to referrer {referrer_id}")
    
    save_users(users)
    return {"success": True, "points": user["points"], "daily_ads_watched": user["daily_ads_watched"]}

@app.post("/api/init_referral/{user_id}")
async def init_referral(user_id: str, data: dict):
    start_param = data.get("start_param", "")
    if not start_param or not start_param.startswith("ref"):
        logger.error(f"Invalid start_param for user {user_id}: {start_param}")
        return {"success": False, "message": "Invalid referral link"}
    
    referrer_id = start_param[3:]  # Extract ID after 'ref'
    if not referrer_id.isdigit() or referrer_id == user_id:
        logger.error(f"Invalid referrer_id for user {user_id}: {referrer_id}")
        return {"success": False, "message": "Invalid referrer ID"}
    
    users = load_users()
    if user_id not in users:
        users[user_id] = {
            "points": 0.0,
            "daily_ads_watched": 0,
            "last_ad_date": "",
            "invited_friends": 0,
            "invited_by": None
        }
    
    if users[user_id]["invited_by"]:
        logger.info(f"User {user_id} already has referrer: {users[user_id]['invited_by']}")
        return {"success": False, "message": "User already referred"}
    
    if referrer_id not in users:
        logger.error(f"Referrer {referrer_id} not found for user {user_id}")
        return {"success": False, "message": "Referrer not found"}
    
    users[user_id]["invited_by"] = referrer_id
    users[referrer_id]["invited_friends"] += 1
    logger.info(f"Set invited_by for user {user_id} to {referrer_id}")
    logger.info(f"Incremented invited_friends for referrer {referrer_id}")
    save_users(users)
    return {"success": True, "invited_by": referrer_id}

@app.post("/api/withdraw/{user_id}")
async def withdraw(user_id: str, data: dict):
    amount = data.get("amount", 0)
    binance_id = data.get("binance_id", "")
    
    if amount < 2000 or not binance_id:
        raise HTTPException(status_code=400, detail="Minimum 2000 $DOGS and Binance ID required")
    
    users = load_users()
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    if users[user_id]["points"] < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    
    users[user_id]["points"] -= amount
    save_users(users)
    return {"success": True}
