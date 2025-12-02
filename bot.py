import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

DATA_FILE = "data.json"
MAX_ACCOUNTS = 5

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ---------------------- START ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if str(user.id) not in data:
        data[str(user.id)] = {"accounts": []}
        save_data(data)

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Commands:\n"
        "/add - Add X account\n"
        "/remove - Remove account\n"
        "/list - Show accounts\n"
        "/stats - Bot usage stats"
    )

# ---------------------- ADD ACCOUNT ----------------------

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()

    if len(data[user_id]["accounts"]) >= MAX_ACCOUNTS:
        await update.message.reply_text("❌ Max 5 accounts allowed.")
        return

    await update.message.reply_text("Send X username (without @):")
    context.user_data["adding"] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    data = load_data()

    if context.user_data.get("adding"):
        if len(data[user_id]["accounts"]) >= MAX_ACCOUNTS:
            await update.message.reply_text("❌ Limit reached!")
            context.user_data["adding"] = False
            return

        data[user_id]["accounts"].append(text)
        save_data(data)
        context.user_data["adding"] = False

        await update.message.reply_text(f"✅ Added: {text}")

# ---------------------- REMOVE ACCOUNT ----------------------

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    accounts = data[user_id]["accounts"]

    if not accounts:
        await update.message.reply_text("No accounts added.")
        return

    keyboard = [
        [InlineKeyboardButton(acc, callback_data=f"rem_{acc}")]
        for acc in accounts
    ]
    await update.message.reply_text(
        "Choose account to remove:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    data = load_data()

    acc = query.data.replace("rem_", "")
    data[user_id]["accounts"].remove(acc)
    save_data(data)

    await query.edit_message_text(f"🗑 Removed: {acc}")

# ---------------------- LIST ACCOUNTS ----------------------

async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    accs = data[user_id]["accounts"]

    if not accs:
        await update.message.reply_text("No accounts added.")
        return
    
    msg = "📌 Your accounts:\n\n" + "\n".join(f"• {a}" for a in accs)
    await update.message.reply_text(msg)

# ---------------------- STATS ----------------------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    total_users = len(data)
    total_accounts = sum(len(v["accounts"]) for v in data.values())

    msg = (
        "📊 Bot Stats\n"
        f"Total users: {total_users}\n"
        f"Total accounts: {total_accounts}"
    )
    await update.message.reply_text(msg)

# ---------------------- RUN BOT ----------------------
import os

TOKEN = os.getenv("BOT_TOKEN")


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("remove", remove))
app.add_handler(CommandHandler("list", list_accounts))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CallbackQueryHandler(callback_remove))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

if __name__ == "__main__":
    app.run_polling()
