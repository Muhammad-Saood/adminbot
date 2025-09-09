import os
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")
PORT = int(os.getenv("PORT", "8000"))
BASE_URL = os.getenv("BASE_URL")  # Optional, for webhook
TELEGRAM_CHANNEL1 = int(os.getenv("TELEGRAM_CHANNEL1", "@InfinityEarn2x"))
TELEGRAM_CHANNEL2 = int(os.getenv("TELEGRAM_CHANNEL2", "@qaidyno804"))
WHATSAPP_LINK = int(os.getenv("WHATSAPP_LINK", "https://chat.whatsapp.com/example"))

# Database connection
def get_db_connection():
    return psycopg2.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD
    )

# Initialize database table
def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        points INTEGER DEFAULT 0,
                        invite_code VARCHAR(50) UNIQUE,
                        invited_by BIGINT,
                        telegram_channel1_joined BOOLEAN DEFAULT FALSE,
                        telegram_channel2_joined BOOLEAN DEFAULT FALSE,
                        whatsapp_clicked BOOLEAN DEFAULT FALSE,
                        channels_verified BOOLEAN DEFAULT FALSE
                    )
                """)
                # Ensure columns exist
                for col in [
                    ("points", "INTEGER DEFAULT 0"),
                    ("invite_code", "VARCHAR(50) UNIQUE"),
                    ("invited_by", "BIGINT"),
                    ("telegram_channel1_joined", "BOOLEAN DEFAULT FALSE"),
                    ("telegram_channel2_joined", "BOOLEAN DEFAULT FALSE"),
                    ("whatsapp_clicked", "BOOLEAN DEFAULT FALSE"),
                    ("channels_verified", "BOOLEAN DEFAULT FALSE")
                ]:
                    cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col[0]} {col[1]}")
                conn.commit()
    except psycopg2.Error as e:
        raise Exception(f"Database error: {e}")

# User data functions
def ensure_user(uid: int, points: int = 0, invited_by: int = None):
    invite_code = f"INVITE_{uid}"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, points, invite_code, invited_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING points
            """, (uid, points, invite_code, invited_by))
            result = cur.fetchone()
            conn.commit()
            return result[0] if result else None

def get_user_data(uid: int) -> dict:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT points, invite_code, invited_by, telegram_channel1_joined,
                       telegram_channel2_joined, whatsapp_clicked, channels_verified
                FROM users WHERE user_id = %s
            """, (uid,))
            result = cur.fetchone()
            return {
                "points": result[0],
                "invite_code": result[1],
                "invited_by": result[2],
                "telegram_channel1_joined": result[3],
                "telegram_channel2_joined": result[4],
                "whatsapp_clicked": result[5],
                "channels_verified": result[6]
            } if result else None

def update_points(uid: int, points: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points = points + %s WHERE user_id = %s", (points, uid))
            conn.commit()

def update_channel_status(uid: int, channel1: bool = None, channel2: bool = None, whatsapp: bool = None, verified: bool = None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            updates = []
            params = []
            if channel1 is not None:
                updates.append("telegram_channel1_joined = %s")
                params.append(channel1)
            if channel2 is not None:
                updates.append("telegram_channel2_joined = %s")
                params.append(channel2)
            if whatsapp is not None:
                updates.append("whatsapp_clicked = %s")
                params.append(whatsapp)
            if verified is not None:
                updates.append("channels_verified = %s")
                params.append(verified)
            if updates:
                params.append(uid)
                cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s", params)
                conn.commit()

# Bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    invited_by = None
    if args and args[0].startswith("INVITE_"):
        try:
            invited_by = int(args[0].split("_")[1])
        except (IndexError, ValueError):
            pass

    # Check if new user
    points = ensure_user(uid, 10, invited_by)
    user_data = get_user_data(uid)

    # Award invite points to referrer if applicable
    if invited_by and points is not None:  # New user
        update_points(invited_by, 10)

    # Prepare channel join message
    keyboard = [
        [InlineKeyboardButton("Join Telegram Channel 1", url=f"https://t.me/{TELEGRAM_CHANNEL1[1:]}")],
        [InlineKeyboardButton("Join Telegram Channel 2", url=f"https://t.me/{TELEGRAM_CHANNEL2[1:]}")],
        [InlineKeyboardButton("Join WhatsApp Channel", url=WHATSAPP_LINK)]
    ]
    if user_data and not user_data["channels_verified"]:
        keyboard.append([InlineKeyboardButton("Verify", callback_data="verify_channels")])
    elif user_data and user_data["channels_verified"]:
        keyboard.append([InlineKeyboardButton("Verified", callback_data="already_verified")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    message = (
        f"Welcome! {'You’ve been given 10 points.' if points is not None else 'Welcome back!'} "
        f"Use /quest to earn more and /total to check your balance.\n\n"
        f"Join these channels for a one-time 30-point bonus (10 points each):\n"
        f"- Telegram Channel 1: {TELEGRAM_CHANNEL1}\n"
        f"- Telegram Channel 2: {TELEGRAM_CHANNEL2}\n"
        f"- WhatsApp Channel: Click the link below\n"
        f"{'You’ve already verified channels.' if user_data and user_data['channels_verified'] else 'Click Verify after joining.'}"
    )
    await update.message.reply_text(message, reply_markup=reply_markup)

async def quest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_input = " ".join(context.args).strip() if context.args else ""
    if user_input == "4+5=" or user_input == "9":
        update_points(uid, 5)
        await update.message.reply_text("Quest completed! You earned 5 points.")
    else:
        await update.message.reply_text("Try the quest: What is 4+5=? Send /quest 9 to answer.")

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_user_data(uid)
    points = user_data["points"] if user_data else 0
    await update.message.reply_text(f"Your total points: {points}")

async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_data = get_user_data(uid)
    if not user_data:
        ensure_user(uid, 0)
        user_data = get_user_data(uid)
    invite_link = f"https://t.me/{context.bot.username}?start={user_data['invite_code']}"
    await update.message.reply_text(f"Your unique invite link: {invite_link}\nShare it with friends to earn 10 points per successful invite!")

async def verify_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user_data = get_user_data(uid)

    if not user_data:
        await query.message.reply_text("Please use /start first.")
        return

    if user_data["channels_verified"]:
        keyboard = [
            [InlineKeyboardButton("Join Telegram Channel 1", url=f"https://t.me/{TELEGRAM_CHANNEL1[1:]}")],
            [InlineKeyboardButton("Join Telegram Channel 2", url=f"https://t.me/{TELEGRAM_CHANNEL2[1:]}")],
            [InlineKeyboardButton("Join WhatsApp Channel", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("Verified", callback_data="already_verified")]
        ]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text("Already verified.")
        return

    # Check Telegram channel membership
    try:
        chat_member1 = await context.bot.get_chat_member(TELEGRAM_CHANNEL1, uid)
        chat_member2 = await context.bot.get_chat_member(TELEGRAM_CHANNEL2, uid)
        is_member1 = chat_member1.status in ["member", "administrator", "creator"]
        is_member2 = chat_member2.status in ["member", "administrator", "creator"]
    except Exception as e:
        await query.message.reply_text(f"Error checking channel membership: {e}")
        return

    update_channel_status(uid, telegram_channel1_joined=is_member1, telegram_channel2_joined=is_member2)

    if is_member1 and is_member2:
        update_channel_status(uid, whatsapp_clicked=True, channels_verified=True)
        update_points(uid, 30)
        keyboard = [
            [InlineKeyboardButton("Join Telegram Channel 1", url=f"https://t.me/{TELEGRAM_CHANNEL1[1:]}")],
            [InlineKeyboardButton("Join Telegram Channel 2", url=f"https://t.me/{TELEGRAM_CHANNEL2[1:]}")],
            [InlineKeyboardButton("Join WhatsApp Channel", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("Verified", callback_data="already_verified")]
        ]
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text("30 points added!")
    else:
        await query.message.reply_text("Please join both Telegram channels to verify and claim 30 points.")

async def already_verified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Already verified.")

# FastAPI setup for health check and webhook
app = FastAPI()

@app.get("/")
async def health_check():
    return {"status": "healthy"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    global application
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"ok": True}

# Initialize and run the application
async def start_application():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("quest", quest))
    application.add_handler(CommandHandler("total", total))
    application.add_handler(CommandHandler("invite", invite))
    application.add_handler(CallbackQueryHandler(verify_channels, pattern="verify_channels"))
    application.add_handler(CallbackQueryHandler(already_verified, pattern="already_verified"))
    await application.initialize()
    if BASE_URL:
        await application.bot.set_webhook(url=f"{BASE_URL}/telegram/webhook")
    else:
        print("Warning: BASE_URL not set, webhook not configured. Set it manually after deployment.")

# Uvicorn configuration and startup
if __name__ == "__main__":
    init_db()
    missing = []
    for name in ["BOT_TOKEN", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD", "PORT", "TELEGRAM_CHANNEL1", "TELEGRAM_CHANNEL2", "WHATSAPP_LINK"]:
        if not globals().get(name):
            missing.append(name)
    if missing:
        raise RuntimeError(f"Missing required config values: {', '.join(missing)}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_application())

    config = uvicorn.Config(app=app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())
