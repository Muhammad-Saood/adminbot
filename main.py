import os
import json
import aiofiles
import aiohttp
import logging  # New: For reliable logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn
import threading
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio
from typing import Optional, Tuple
import httpx  # New: For token validation

load_dotenv()

# Setup logging (replaces print for Koyeb compatibility)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = "jdsrhukds_bot"  # Hardcoded
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "-1003095776330")
MONETAG_ZONE = "9859391"
USERS_FILE = "/tmp/users.json"

app = FastAPI()
json_lock = asyncio.Lock()

# Validate BOT_TOKEN on startup
async def validate_token():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set in .env")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
        if resp.status_code != 200:
            raise ValueError(f"Invalid BOT_TOKEN: {resp.text}")
    logger.info("BOT_TOKEN validated successfully")

# Initialize JSON file
async def init_json():
    try:
        async with json_lock:
            async with aiofiles.open(USERS_FILE, mode='a') as f:
                pass
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                content = await f.read()
                if not content.strip():
                    async with aiofiles.open(USERS_FILE, mode='w') as f:
                        await f.write(json.dumps({}))
        logger.info(f"JSON storage initialized at {USERS_FILE}")
    except Exception as e:
        logger.error(f"JSON init failed: {e}")
        raise

# User data functions (unchanged, with logging)
async def get_or_create_user(user_id: int, invited_by: Optional[int] = None) -> Tuple[dict, bool]:
    async with json_lock:
        users = {}
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                content = await f.read()
                if content.strip():
                    users = json.loads(content)
        except FileNotFoundError:
            logger.warning(f"users.json not found, creating new: {USERS_FILE}")
        except Exception as e:
            logger.error(f"Error reading users.json: {e}")
        
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
                logger.info(f"Created new user {user_id} in JSON")
            except Exception as e:
                logger.error(f"Error writing new user to JSON: {e}")
        
        return users[user_id_str], is_new

# ... (other functions like update_points, etc. - unchanged, but add logger.error where print was)

async def update_points(user_id: int, points: float):
    async with json_lock:
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                users = json.loads(await f.read())
            
            user_id_str = str(user_id)
            if user_id_str in users:
                users[user_id_str]["points"] += points
                async with aiofiles.open(USERS_FILE, mode='w') as f:
                    await f.write(json.dumps(users, indent=2))
        except Exception as e:
            logger.error(f"Error updating points for user {user_id}: {e}")

# (Similarly for update_daily_ads, add_invited_friend, set_binance_id, withdraw_points - replace print with logger)

async def update_daily_ads(user_id: int, ads_watched: int):
    today = datetime.now().date().isoformat()
    async with json_lock:
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
            logger.error(f"Error updating daily ads for user {user_id}: {e}")

async def add_invited_friend(user_id: int):
    async with json_lock:
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                users = json.loads(await f.read())
            
            user_id_str = str(user_id)
            if user_id_str in users:
                users[user_id_str]["invited_friends"] += 1
                async with aiofiles.open(USERS_FILE, mode='w') as f:
                    await f.write(json.dumps(users, indent=2))
                logger.info(f"Incremented invited_friends for user {user_id}")
        except Exception as e:
            logger.error(f"Error adding invited friend for user {user_id}: {e}")

async def set_binance_id(user_id: int, binance_id: str):
    async with json_lock:
        try:
            async with aiofiles.open(USERS_FILE, mode='r') as f:
                users = json.loads(await f.read())
            
            user_id_str = str(user_id)
            if user_id_str in users:
                users[user_id_str]["binance_id"] = binance_id
                async with aiofiles.open(USERS_FILE, mode='w') as f:
                    await f.write(json.dumps(users, indent=2))
        except Exception as e:
            logger.error(f"Error setting binance_id for user {user_id}: {e}")

async def withdraw_points(user_id: int, amount: float, binance_id: str):
    async with json_lock:
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
            logger.error(f"Error processing withdrawal for user {user_id}: {e}")
        return False

# API endpoints (unchanged)
@app.get("/api/user/{user_id}")
async def get_user(user_id: int):
    user, _ = await get_or_create_user(user_id)
    return {
        "points": user["points"],
        "daily_ads_watched": user["daily_ads_watched"],
        "invited_friends": user["invited_friends"],
        "invited_by": user.get("invited_by")
    }

@app.post("/api/watch_ad/{user_id}")
async def watch_ad(user_id: int):
    user, _ = await get_or_create_user(user_id)
    today = datetime.now().date().isoformat()
    if user["last_ad_date"] == today and user["daily_ads_watched"] >= 30:
        return {"success": False, "limit_reached": True}
    
    await update_daily_ads(user_id, 1)
    await update_points(user_id, 20.0)
    if user.get("invited_by"):
        await update_points(user["invited_by"], 2.0)
    
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

# Health check endpoint (new: to verify bot status)
@app.get("/health")
async def health():
    try:
        me = await application.bot.get_me()
        return {"status": "healthy", "bot_username": me.username}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# Mini App HTML (unchanged - abbreviated for brevity)
@app.get("/app")
async def mini_app():
    # ... (same as before, with logger instead of print if needed)
    html_content = f"""..."""  # Full HTML from previous code
    return HTMLResponse(html_content.replace("{MONETAG_ZONE}", MONETAG_ZONE).replace("{BOT_USERNAME}", BOT_USERNAME))

# Bot setup
application = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start called by user {update.effective_user.id}, args: {context.args}")  # New log
    args = context.args
    invited_by = None
    if args and args[0].startswith("ref"):
        try:
            invited_by = int(args[0].replace("ref", ""))
        except ValueError:
            invited_by = None
    
    existing_user, is_new = await get_or_create_user(update.effective_user.id)
    if is_new and invited_by and invited_by != update.effective_user.id and existing_user.get("invited_by") is None:
        await get_or_create_user(update.effective_user.id, invited_by)
        await add_invited_friend(invited_by)
        logger.info(f"New referral: {update.effective_user.id} by {invited_by}")
        await update.message.reply_text("Welcome! You were referred by a friend. Launch the Mini App to start earning!")
    else:
        await update.message.reply_text("Welcome back! Launch the Mini App to continue earning!")
    
    keyboard = [[InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=f"{BASE_URL}/app"))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Launch the Mini App!", reply_markup=reply_markup)

application.add_handler(CommandHandler("start", start))

# Updated main with validation and full error handling
async def main():
    try:
        logger.info("Starting main...")
        await validate_token()  # New: Validate early
        await init_json()
        logger.info("Initializing bot...")
        await application.initialize()
        await application.start()
        logger.info("Bot initialized successfully")
        
        logger.info("Starting uvicorn in background thread...")
        threading.Thread(
            target=lambda: uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info"),
            daemon=True
        ).start()
        
        logger.info("Starting bot polling...")
        await application.run_polling(drop_pending_updates=True)
    except ValueError as ve:
        logger.error(f"Config error: {ve}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}", exc_info=True)  # Full traceback
        raise

if __name__ == "__main__":
    asyncio.run(main())
