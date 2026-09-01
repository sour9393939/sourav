import asyncio
import logging
import os
import re
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")
API_URL = "http://51.20.5.41:5000/blacklist"
CHECK_INTERVAL = 60

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# chat_id -> {email: asyncio.Task}
AUTO_TASKS = {}

logging.basicConfig(level=logging.INFO)


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📧 ONE CHECK", callback_data="email_help"),
            InlineKeyboardButton("🔄 AUTO CHECK", callback_data="oto_help"),
        ],
        [
            InlineKeyboardButton("🛑 STOP EMAIL", callback_data="stop_help"),
            InlineKeyboardButton("⛔ STOP ALL", callback_data="stopall_help"),
        ],
    ])


def valid_email(email):
    return bool(EMAIL_RE.match(email))


async def api_check(email):
    response = await asyncio.to_thread(
        requests.get,
        API_URL,
        params={"email": email},
        timeout=10
    )
    response.raise_for_status()
    return response.json().get("status", "Unknown")


def result_message(email, status):
    return (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "     📋 EMAIL RESULT\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"📧 Email: {email}\n"
        f"📊 Status: {status}"
    )


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "   👋 Welcome to Email\n"
        "      Blacklist Bot\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        "📧 One-time check:\n"
        "/email your@email.com\n\n"
        "🔄 Automatic check every 1 minute:\n"
        "/oto your@email.com\n\n"
        "🛑 Stop one email:\n"
        "/stop your@email.com\n\n"
        "⛔ Stop all:\n"
        "/stop all",
        reply_markup=menu()
    )


async def email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage:\n/email your@email.com"
        )
        return

    address = " ".join(context.args).strip()

    if not valid_email(address):
        await update.message.reply_text("❌ Invalid email address.")
        return

    await update.message.reply_text("⏳ Checking...")

    try:
        status = await api_check(address)
        await update.message.reply_text(result_message(address, status))
    except requests.RequestException:
        await update.message.reply_text("⚠️ API request failed.")
    except ValueError:
        await update.message.reply_text("⚠️ Invalid API response.")


async def auto_loop(chat_id, context, address):
    try:
        while True:
            try:
                status = await api_check(address)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=result_message(address, status)
                )
            except requests.RequestException:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ API request failed for {address}. Retrying in 1 minute."
                )
            except ValueError:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Invalid API response for {address}. Retrying in 1 minute."
                )

            await asyncio.sleep(CHECK_INTERVAL)
    except asyncio.CancelledError:
        pass


async def oto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage:\n/oto your@email.com"
        )
        return

    address = " ".join(context.args).strip()

    if not valid_email(address):
        await update.message.reply_text("❌ Invalid email address.")
        return

    chat_id = update.effective_chat.id
    tasks = AUTO_TASKS.setdefault(chat_id, {})

    if address in tasks and not tasks[address].done():
        await update.message.reply_text(
            f"🔄 Already running:\n{address}"
        )
        return

    task = asyncio.create_task(auto_loop(chat_id, context, address))
    tasks[address] = task

    # First request immediately; next requests every 60 seconds.
    await update.message.reply_text(
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        "     🔄 AUTO STARTED\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"📧 {address}\n"
        "⏱️ Every 1 minute\n\n"
        "🛑 Use /stop email to stop it."
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Usage:\n/stop your@email.com\n"
            "or /stop all"
        )
        return

    target = " ".join(context.args).strip()
    chat_id = update.effective_chat.id
    tasks = AUTO_TASKS.setdefault(chat_id, {})

    if target.lower() == "all":
        count = 0
        for task in list(tasks.values()):
            if not task.done():
                task.cancel()
                count += 1
        tasks.clear()

        await update.message.reply_text(
            f"⛔ ALL AUTO CHECKS STOPPED\n\n"
            f"📊 Stopped: {count}"
        )
        return

    task = tasks.get(target)
    if task and not task.done():
        task.cancel()
        tasks.pop(target, None)
        await update.message.reply_text(
            f"🛑 AUTO CHECK STOPPED\n\n📧 {target}"
        )
    else:
        await update.message.reply_text(
            f"ℹ️ No auto check running for:\n{target}"
        )


async def button_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    help_text = {
        "email_help": "📧 ONE CHECK\n/email your@email.com",
        "oto_help": "🔄 AUTO CHECK\n/oto your@email.com\n\nRuns every 1 minute.",
        "stop_help": "🛑 STOP EMAIL\n/stop your@email.com",
        "stopall_help": "⛔ STOP ALL\n/stop all",
    }

    await query.message.reply_text(help_text.get(query.data, "Use /start."))


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("email", email))
    app.add_handler(CommandHandler("oto", oto))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CallbackQueryHandler(button_help))

    print("🤖 Email Blacklist Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
