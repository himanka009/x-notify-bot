# bot.py
import os
import json
import asyncio
import logging
from typing import Optional
from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------- Config ----------
DATA_FILE = "data.json"
MAX_ACCOUNTS = 5
POLL_INTERVAL_SECONDS = 30  # adjust (30-60 recommended)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/119.0 Safari/537.36"

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("x-notify-bot")

# ---------- DB helpers ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load data.json, returning empty DB.")
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed to save data.json")

def ensure_user(data, user_id):
    if user_id not in data:
        data[user_id] = {"accounts": {}, "meta": {}}
    # accounts: dict username -> {last_tweet_id: str or None}
    return data[user_id]

# ---------- Scraping helper ----------
async def fetch_latest_tweet_id_and_text(session: ClientSession, username: str) -> Optional[dict]:
    """
    Return dict {'id': id_str, 'text': text} of latest tweet or None if not found.
    This scrapes https://x.com/<username> and finds first /status/ link.
    """
    url = f"https://x.com/{username}"
    headers = {"User-Agent": USER_AGENT}
    try:
        async with session.get(url, headers=headers, timeout=ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning("Fetch %s returned status %s", url, resp.status)
                return None
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")

            # find first anchor href that contains '/status/'
            a = soup.find("a", href=lambda h: h and "/status/" in h)
            if not a:
                # Try look for "data-testid=tweet" blocks and parse id attribute inside - fallback
                # but minimal reliable approach is the /status/ link
                return None

            href = a.get("href", "")
            # href may be like /username/status/12345 or /i/web/status/12345
            if "/status/" in href:
                tweet_id = href.split("/status/")[-1].split("?")[0].strip("/")
            else:
                return None

            # attempt to extract tweet text (first nearby text)
            text = a.get_text(strip=True)
            if not text:
                # try parent elements
                text = a.parent.get_text(strip=True) if a.parent else ""

            return {"id": tweet_id, "text": text}
    except Exception as e:
        logger.exception("Error fetching latest tweet for %s: %s", username, e)
        return None

# ---------- Background tracker ----------
async def tracker_loop(app):
    """
    Background task that periodically checks latest tweets for all tracked usernames
    across all users and notifies the respective Telegram chat when a new tweet is found.
    """
    logger.info("Tracker started with interval %s seconds", POLL_INTERVAL_SECONDS)
    # use a single shared aiohttp session
    timeout = ClientTimeout(total=20)
    async with ClientSession(timeout=timeout) as session:
        while True:
            try:
                data = load_data()
                # Build a map username -> list of user_ids (chats) that track it
                watch_map = {}  # username -> list of (user_id)
                for user_id, uobj in data.items():
                    accounts = uobj.get("accounts", {})
                    for uname, info in accounts.items():
                        watch_map.setdefault(uname, []).append(user_id)

                if not watch_map:
                    # nothing to track
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                # iterate through usernames
                for username, users_watching in watch_map.items():
                    info = await fetch_latest_tweet_id_and_text(session, username)
                    if not info or "id" not in info:
                        # nothing found or fetch error
                        continue
                    latest_id = info["id"]
                    latest_text = info.get("text", "")

                    # For each user watching this username, compare with stored last id
                    for user_id in users_watching:
                        # ensure user entry exists
                        if user_id not in data:
                            data[user_id] = {"accounts": {}, "meta": {}}
                        user_accounts = data[user_id].setdefault("accounts", {})
                        acc_info = user_accounts.get(username, {})
                        last_id = acc_info.get("last_tweet_id")

                        if last_id != latest_id:
                            # New tweet — send notification
                            try:
                                chat_id = int(user_id)
                                link = f"https://x.com/{username}/status/{latest_id}"
                                text_msg = f"🟦 New Tweet by @{username}:\n\n{latest_text or link}\n\n{link}"
                                await app.bot.send_message(chat_id=chat_id, text=text_msg)
                                logger.info("Notified %s about new tweet %s by %s", user_id, latest_id, username)
                            except Exception:
                                logger.exception("Failed to send notification to %s for %s", user_id, username)
                            # update stored last id
                            user_accounts[username] = {"last_tweet_id": latest_id}
                            save_data(data)
                # done checking all
            except Exception:
                logger.exception("Tracker loop exception")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

# ---------- Bot Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    ensure_user(data, str(user.id))
    save_data(data)
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Commands:\n"
        "/add - Add X account\n"
        "/remove - Remove account\n"
        "/list - Show accounts\n"
        "/stats - Bot usage stats\n\n"
        "How to add: send /add then type username without @\n"
        "Tracker will auto-check newest tweets and notify you."
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    user_obj = ensure_user(data, user_id)
    save_data(data)

    if len(user_obj.get("accounts", {})) >= MAX_ACCOUNTS:
        await update.message.reply_text("❌ Max 5 accounts allowed.")
        return

    await update.message.reply_text("Send X username (without @):")
    context.user_data["adding"] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    data = load_data()
    user_obj = ensure_user(data, user_id)

    if context.user_data.get("adding"):
        if len(user_obj.get("accounts", {})) >= MAX_ACCOUNTS:
            await update.message.reply_text("❌ Limit reached!")
            context.user_data["adding"] = False
            save_data(data)
            return

        username = text.replace("@", "").strip()
        if not username:
            await update.message.reply_text("❌ Invalid username.")
            context.user_data["adding"] = False
            return

        if username in user_obj.get("accounts", {}):
            await update.message.reply_text(f"✅ @{username} already in your list.")
            context.user_data["adding"] = False
            return

        # add with last_tweet_id = None so tracker will fetch but not notify immediately
        user_obj.setdefault("accounts", {})[username] = {"last_tweet_id": None}
        save_data(data)
        context.user_data["adding"] = False
        await update.message.reply_text(f"✅ Added: {username}\nTracker will pick up the latest tweet shortly.")
        return

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    user_obj = ensure_user(data, user_id)
    accounts = list(user_obj.get("accounts", {}).keys())

    if not accounts:
        await update.message.reply_text("No accounts added.")
        return

    keyboard = [[InlineKeyboardButton(acc, callback_data=f"rem_{acc}")] for acc in accounts]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="CLOSE")])
    await update.message.reply_text("Choose account to remove:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = load_data()
    user_obj = ensure_user(data, user_id)

    if query.data == "CLOSE":
        try:
            await query.delete_message()
        except:
            pass
        return

    acc = query.data.replace("rem_", "")
    if acc in user_obj.get("accounts", {}):
        user_obj["accounts"].pop(acc, None)
        save_data(data)
        await query.edit_message_text(f"🗑 Removed: {acc}")
    else:
        await query.edit_message_text("Account not found or already removed.")

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    user_obj = ensure_user(data, user_id)
    accs = list(user_obj.get("accounts", {}).keys())

    if not accs:
        await update.message.reply_text("No accounts added.")
        return

    msg = "📌 Your accounts:\n\n" + "\n".join(f"• {a}" for a in accs)
    await update.message.reply_text(msg)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    total_users = len(data)
    total_accounts = sum(len(v.get("accounts", {})) for v in data.values())
    msg = f"📊 Bot Stats\nTotal users: {total_users}\nTotal accounts: {total_accounts}"
    await update.message.reply_text(msg)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# ---------- Run Bot and tracker ----------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not found in environment. Bot will not start.")
else:
    app = ApplicationBuilder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_accounts))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback_remove))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

# --- replace your current __main__ / startup with this block ---
import asyncio
import signal

async def start_bot():
    await app.initialize()
    await app.start()
    logger.info("Bot started. Listening for updates.")

    # start tracker AFTER app is running
    app.create_task(tracker_loop(app))

    # start polling
    await app.updater.start_polling()
    logger.info("Updater polling started.")

    # block until termination signal from Railway (SIGTERM) or Ctrl-C
    stop_event = asyncio.Event()
    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _stop)
        loop.add_signal_handler(signal.SIGINT, _stop)
    except NotImplementedError:
        # some platforms (Windows) don't support add_signal_handler; ignore
        pass

    await stop_event.wait()

    # graceful shutdown
    logger.info("Shutdown signal received. Stopping app...")
    await app.updater.stop_polling()
    await app.stop()
    await app.shutdown()
    logger.info("Bot stopped cleanly.")

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except Exception:
        logger.exception("Fatal error in main")
