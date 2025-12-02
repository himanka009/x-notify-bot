import json
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

DATA_FILE = "data.json"
MAX_ACCOUNTS = 5

# ------------------ Load & Save ------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ------------------ Commands ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    if user_id not in data:
        data[user_id] = {"accounts": []}
        save_data(data)

    await update.message.reply_text(
        "👋 Welcome to X Watch Bot!\n\n"
        "Commands:\n"
        "/add - Add X account\n"
        "/remove - Remove account\n"
        "/list - Show accounts\n"
        "/stats - Bot usage stats"
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    if len(data[user_id]["accounts"]) >= MAX_ACCOUNTS:
        await update.message.reply_text("❌ Maximum 5 accounts allowed!")
        return

    await update.message.reply_text("Send me X username (without @)")

    context.user_data["awaiting_add"] = True

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text.strip()
    data = load_data()

    if context.user_data.get("awaiting_add"):
        if len(data[user_id]["accounts"]) >= MAX_ACCOUNTS:
            await update.message.reply_text("❌ Limit reached (5 accounts).")
            return

        data[user_id]["accounts"].append(text)
        save_data(data)

        context.user_data["awaiting_add"] = False
        await update.message.reply_text(f"✅ Added: {text}")
        return

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    accounts = data[user_id]["accounts"]

    if not accounts:
        await update.message.reply_text("❌ No accounts added.")
        return

    buttons = [
        [InlineKeyboardButton(acc, callback_data=f"remove_{acc}")]
        for acc in accounts
    ]

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Select account to remove:", reply_markup=keyboard)

async def remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    data = load_data()

    acc = query.data.replace("remove_", "")
    data[user_id]["accounts"].remove(acc)
    save_data(data)

    await query.edit_message_text(f"🗑 Removed: {acc}")

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    accounts = data[user_id]["accounts"]

    if not accounts:
        await update.message.reply_text("❌ No accounts added.")
        return

    msg = "📌 Your watched accounts:\n\n" + "\n".join(f"• {a}" for a in accounts)
    await update.message.reply_text(msg)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    total_users = len(data)
    total_accounts = sum(len(info["accounts"]) for info in data.values())

    msg = (
        f"📊 Bot Stats\n"
        f"Users: {total_users}\n"
        f"Total tracked accounts: {total_accounts}\n"
    )

    await update.message.reply_text(msg)

# ------------------ Run Bot ------------------

TOKEN = os.getenv("BOT_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("remove", remove))
app.add_handler(CommandHandler("list", list_accounts))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CallbackQueryHandler(remove_callback))
app.add_handler(CommandHandler("help", start))
app.add_handler(CommandHandler("menu", start))

# Text handler for username input
from telegram.ext import MessageHandler, filters
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

app.run_polling()
