import os
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
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
BASE_URL = os.getenv("BASE_URL")  # Optional, will be set post-deployment

# Database connection
def get_db_connection():
    return psycopg2.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD
    )

# Initialize database table with error handling
def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        points INTEGER DEFAULT 0
                    )
                """)
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS points INTEGER DEFAULT 0")
                conn.commit()
    except psycopg2.Error as e:
        raise

# User data functions
def ensure_user(uid: int, points: int = 0):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, points) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET points = %s", (uid, points, points))
            conn.commit()

def get_user_points(uid: int) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (uid,))
            result = cur.fetchone()
            return result[0] if result else 0

def update_points(uid: int, points: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points = points + %s WHERE user_id = %s", (points, uid))
            conn.commit()

# Bot commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid, 10)
    await update.message.reply_text(f"Welcome! You’ve been given 10 points. Use /quest to earn more and /total to check your balance.")

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
    points = get_user_points(uid)
    await update.message.reply_text(f"Your total points: {points}")

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
    await application.initialize()
    # Set webhook only if BASE_URL is provided
    if BASE_URL:
        await application.bot.set_webhook(url=f"{BASE_URL}/telegram/webhook")
    else:
        print("Warning: BASE_URL not set, webhook not configured. Set it manually after deployment.")

# Uvicorn configuration and startup
if __name__ == "__main__":
    init_db()
    missing = []
    for name in ["BOT_TOKEN", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD", "PORT"]:
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
