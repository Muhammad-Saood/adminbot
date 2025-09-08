import os
import psycopg2
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_HOST = os.getenv("DATABASE_HOST")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME")

# Set up logging
print = lambda *args, **kwargs: None  # Disable print for simplicity

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
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    points INTEGER DEFAULT 0
                )
            """)
            conn.commit()

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
    ensure_user(uid, 10)  # Give 10 points on start
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

# Initialize and run the bot
def main():
    init_db()  # Set up the database table
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("quest", quest))
    application.add_handler(CommandHandler("total", total))

    application.run_polling()

if __name__ == "__main__":
    missing = []
    for name in ["BOT_TOKEN", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD"]:
        if not globals().get(name):
            missing.append(name)
    if missing:
        raise RuntimeError(f"Missing required config values: {', '.join(missing)}")
    main()
