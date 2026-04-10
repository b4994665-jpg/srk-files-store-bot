import os
import sqlite3
import logging
import asyncio
import requests

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# ═══════════════════════════════════════════════════════
#                        CONFIG
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = 8379167923  # Your admin ID

# Default API
DEFAULT_API = "https://aerivue-95q3.onrender.com/tg?userid={userid}&apikey=tg_OkfvJXzSJM4yYxhp9HM52KAw17YBSvh3"

# Hardcoded verification channels
FORCE_CHANNELS = [
    {"username": "srking0001", "link": "https://t.me/srking0001"},
    {"username": "botdevking", "link": "https://t.me/botdevking"},
    {"username": "srk_backup_channel", "link": "https://t.me/srk_backup_channel"},
]

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tgbot.db")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation States
SET_API, BC_WAIT_MSG, BC_WAIT_CONFIRM = range(3)

# ═══════════════════════════════════════════════════════
#                       DATABASE
# ═══════════════════════════════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Settings table for API
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Initialize default API if not exists
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
              ("api_url", DEFAULT_API))
    
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")


def register_user(user_id):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def count_users():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()
    return count


def get_api_url():
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", ("api_url",)).fetchone()
    conn.close()
    return row["value"] if row else DEFAULT_API


def set_api_url(url):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                 ("api_url", url))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════
#                  VERIFICATION SYSTEM
# ═══════════════════════════════════════════════════════

async def check_user_joined_all(bot, user_id):
    """Check if user joined all required channels (admin bypass)"""
    if user_id == ADMIN_ID:
        return True, []
    
    not_joined = []
    for ch in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(f"@{ch['username']}", user_id)
            if member.status in ["left", "kicked"]:
                not_joined.append(ch)
        except Exception as e:
            logger.error(f"Error checking @{ch['username']}: {e}")
            not_joined.append(ch)
    
    return len(not_joined) == 0, not_joined


async def send_verification_message(update: Update, not_joined):
    """Send verification message with join buttons"""
    buttons = []
    for ch in not_joined:
        buttons.append([InlineKeyboardButton(f"Join @{ch['username']}", url=ch['link'])])
    
    buttons.append([InlineKeyboardButton("✅ Joined, Check Again", callback_data="verify_check")])
    
    text = "⚠️ **Please join the following channels to use this bot:**\n\n"
    text += "👇 Click buttons below to join 👇"
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ═══════════════════════════════════════════════════════
#                   API CALL FUNCTION
# ═══════════════════════════════════════════════════════

def fetch_number_from_api(user_id):
    """Fetch phone number from API"""
    api_url = get_api_url()
    
    # Replace {userid} with actual user_id
    url = api_url.replace("{userid}", str(user_id))
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Try different possible response formats
            if isinstance(data, dict):
                # Try common field names
                number = (data.get("phone") or 
                         data.get("number") or 
                         data.get("mobile") or 
                         data.get("phone_number") or
                         data.get("result") or
                         data.get("data"))
                
                if number:
                    return str(number)
            
            # If response is direct number
            elif isinstance(data, (str, int)):
                return str(data)
        
        return None
        
    except Exception as e:
        logger.error(f"API Error: {e}")
        return None


# ═══════════════════════════════════════════════════════
#                      KEYBOARDS
# ═══════════════════════════════════════════════════════

def main_menu_kb():
    keyboard = [
        [KeyboardButton("🔍 Find Number")],
        [KeyboardButton("ℹ️ How to Use"), KeyboardButton("📊 Stats")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def admin_panel_kb():
    keyboard = [
        [KeyboardButton("🔧 API Management")],
        [KeyboardButton("📣 Broadcast"), KeyboardButton("📊 Stats")],
        [KeyboardButton("🏠 Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)


# ═══════════════════════════════════════════════════════
#                    START COMMAND
# ═══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    
    register_user(user_id)
    
    # Group usage
    if chat_type in ["group", "supergroup"]:
        help_text = """
🤖 **TG Number Finder Bot - Group Usage**

**How to use in groups:**

1️⃣ **Reply to user's message:**
   Reply to any user's message with `/tg`
   Bot will find their number automatically

2️⃣ **Search by User ID:**
   Use `/tg <userid>` to search directly
   Example: `/tg 123456789`

That's it! 🎯
"""
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return
    
    # DM usage - check verification
    if user_id != ADMIN_ID:
        joined, not_joined = await check_user_joined_all(context.bot, user_id)
        if not joined:
            await send_verification_message(update, not_joined)
            return
    
    # Welcome message
    first_name = update.effective_user.first_name
    welcome = f"👋 **Welcome {first_name}!**\n\n"
    welcome += "🔍 **TG Number Finder Bot**\n\n"
    welcome += "Send me any **User ID** and I'll find the phone number!\n\n"
    welcome += "Click **ℹ️ How to Use** for more info."
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            welcome,
            parse_mode="Markdown",
            reply_markup=admin_panel_kb()
        )
    else:
        await update.message.reply_text(
            welcome,
            parse_mode="Markdown",
            reply_markup=main_menu_kb()
        )


# ═══════════════════════════════════════════════════════
#                  VERIFICATION CALLBACK
# ═══════════════════════════════════════════════════════

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id == ADMIN_ID:
        await query.message.delete()
        await context.bot.send_message(
            user_id,
            "✅ Admin verified!",
            reply_markup=admin_panel_kb()
        )
        return
    
    joined, not_joined = await check_user_joined_all(context.bot, user_id)
    
    if joined:
        await query.message.delete()
        await context.bot.send_message(
            user_id,
            "✅ **Verified Successfully!**\n\nYou can now use the bot. Send any User ID to find number!",
            parse_mode="Markdown",
            reply_markup=main_menu_kb()
        )
    else:
        await query.answer("❌ You haven't joined all channels yet!", show_alert=True)


# ═══════════════════════════════════════════════════════
#                    MENU HANDLERS
# ═══════════════════════════════════════════════════════

async def how_to_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
ℹ️ **How to Use TG Number Finder**

**In Direct Message (DM):**
1️⃣ Send any Telegram User ID
2️⃣ Bot will search and return phone number
3️⃣ If not found, you'll get "Not Found" message

**In Groups:**
1️⃣ Reply to any message with `/tg` command
2️⃣ Or use `/tg <userid>` to search directly

**Example:**
Send: `123456789`
Get: `📱 +1234567890`

That's it! Simple and fast 🚀
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = count_users()
    
    stats = f"""
📊 **Bot Statistics**

👥 Total Users: `{total_users}`
📢 Verification Channels: `3`
🤖 Status: Active ✅
"""
    
    if update.effective_user.id == ADMIN_ID:
        current_api = get_api_url()
        stats += f"\n🔗 Current API:\n`{current_api}`"
    
    await update.message.reply_text(stats, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════
#                 ADMIN - API MANAGEMENT
# ═══════════════════════════════════════════════════════

async def api_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    current_api = get_api_url()
    text = f"""
🔧 **API Management**

**Current API:**
`{current_api}`

**To change API, send new URL with {"{userid}"} placeholder**

**Example:**
`https://api.example.com/user?id={"{userid}"}&key=xxx`

⚠️ **Important:** Keep `{"{userid}"}` in URL where user ID should go!
"""
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return SET_API


async def set_api_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text(
            "❌ Cancelled",
            reply_markup=admin_panel_kb()
        )
        return ConversationHandler.END
    
    new_api = update.message.text.strip()
    
    if "{userid}" not in new_api:
        await update.message.reply_text(
            "❌ **Error:** API must contain `{userid}` placeholder!\n\nTry again or click Cancel.",
            parse_mode="Markdown"
        )
        return SET_API
    
    set_api_url(new_api)
    
    await update.message.reply_text(
        f"✅ **API Updated Successfully!**\n\n**New API:**\n`{new_api}`",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#                 ADMIN - BROADCAST
# ═══════════════════════════════════════════════════════

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    await update.message.reply_text(
        "📣 **Broadcast Message**\n\n"
        "Send the message you want to broadcast to all users.\n\n"
        "You can send: Text, Photo, Video, Document, etc.",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return BC_WAIT_MSG


async def broadcast_receive_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text(
            "❌ Broadcast cancelled",
            reply_markup=admin_panel_kb()
        )
        return ConversationHandler.END
    
    context.user_data["bc_message"] = update.message
    
    total_users = count_users()
    
    keyboard = [
        [KeyboardButton("✅ Send Broadcast")],
        [KeyboardButton("❌ Cancel")]
    ]
    
    await update.message.reply_text(
        f"📊 **Broadcast Preview**\n\n"
        f"Total Users: `{total_users}`\n\n"
        f"Confirm to send?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return BC_WAIT_CONFIRM


async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text(
            "❌ Broadcast cancelled",
            reply_markup=admin_panel_kb()
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    if update.message.text != "✅ Send Broadcast":
        return BC_WAIT_CONFIRM
    
    bc_msg = context.user_data.get("bc_message")
    if not bc_msg:
        await update.message.reply_text("❌ Error: Message not found")
        return ConversationHandler.END
    
    users = get_all_users()
    
    await update.message.reply_text(
        f"⏳ Starting broadcast to {len(users)} users...",
        reply_markup=admin_panel_kb()
    )
    
    success = 0
    failed = 0
    
    for user_id in users:
        try:
            await bc_msg.copy(user_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast error for {user_id}: {e}")
    
    await update.message.reply_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"✅ Sent: {success}\n"
        f"❌ Failed: {failed}",
        parse_mode="Markdown"
    )
    
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#                 NUMBER SEARCH - DM
# ═══════════════════════════════════════════════════════

async def search_number_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user ID search in DM"""
    user_id = update.effective_user.id
    
    # Admin bypass verification
    if user_id != ADMIN_ID:
        joined, not_joined = await check_user_joined_all(context.bot, user_id)
        if not joined:
            await send_verification_message(update, not_joined)
            return
    
    text = update.message.text.strip()
    
    # Check if it's a valid user ID
    if not text.isdigit():
        await update.message.reply_text(
            "❌ Please send a valid **User ID** (numbers only)",
            parse_mode="Markdown"
        )
        return
    
    search_uid = text
    
    # Show searching message
    msg = await update.message.reply_text(
        f"🔍 Searching for User ID: `{search_uid}`...",
        parse_mode="Markdown"
    )
    
    # Fetch from API
    number = fetch_number_from_api(search_uid)
    
    if number:
        await msg.edit_text(
            f"✅ **Found!**\n\n"
            f"👤 User ID: `{search_uid}`\n"
            f"📱 Phone: `{number}`",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text(
            f"❌ **Not Found**\n\n"
            f"User ID: `{search_uid}`\n\n"
            f"Number not found in database.",
            parse_mode="Markdown"
        )


# ═══════════════════════════════════════════════════════
#              NUMBER SEARCH - GROUP
# ═══════════════════════════════════════════════════════

async def tg_command_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tg command in groups"""
    chat_type = update.effective_chat.type
    
    if chat_type not in ["group", "supergroup"]:
        return
    
    # Check if reply to message
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user:
            search_uid = str(replied_user.id)
            user_name = replied_user.first_name
        else:
            await update.message.reply_text("❌ Could not get user info")
            return
    
    # Check if user ID provided
    elif context.args:
        search_uid = context.args[0].strip()
        user_name = "Unknown"
        
        if not search_uid.isdigit():
            await update.message.reply_text("❌ Please provide a valid User ID")
            return
    
    else:
        await update.message.reply_text(
            "ℹ️ **Usage:**\n"
            "• Reply to user's message with `/tg`\n"
            "• Or use `/tg <userid>`",
            parse_mode="Markdown"
        )
        return
    
    # Search in API
    msg = await update.message.reply_text(f"🔍 Searching...")
    
    number = fetch_number_from_api(search_uid)
    
    if number:
        await msg.edit_text(
            f"✅ **Found!**\n\n"
            f"👤 Name: {user_name}\n"
            f"🆔 User ID: `{search_uid}`\n"
            f"📱 Phone: `{number}`",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text(
            f"❌ **Not Found**\n\n"
            f"User ID: `{search_uid}`",
            parse_mode="Markdown"
        )


# ═══════════════════════════════════════════════════════
#                  BUTTON HANDLERS
# ═══════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "ℹ️ How to Use":
        await how_to_use(update, context)
    
    elif text == "📊 Stats":
        await stats_handler(update, context)
    
    elif text == "🏠 Main Menu":
        if user_id == ADMIN_ID:
            await update.message.reply_text(
                "🏠 Main Menu",
                reply_markup=admin_panel_kb()
            )
        else:
            await update.message.reply_text(
                "🏠 Main Menu",
                reply_markup=main_menu_kb()
            )
    
    elif text == "🔧 API Management" and user_id == ADMIN_ID:
        return await api_management(update, context)
    
    elif text == "📣 Broadcast" and user_id == ADMIN_ID:
        return await broadcast_start(update, context)


# ═══════════════════════════════════════════════════════
#                    CANCEL HANDLER
# ═══════════════════════════════════════════════════════

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "❌ Cancelled",
            reply_markup=admin_panel_kb()
        )
    else:
        await update.message.reply_text(
            "❌ Cancelled",
            reply_markup=main_menu_kb()
        )
    
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#                        MAIN
# ═══════════════════════════════════════════════════════

async def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN not set!")
    
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handlers
    api_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex("^🔧 API Management$"), button_handler)],
        states={
            SET_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_api_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False
    )
    
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & filters.Regex("^📣 Broadcast$"), button_handler)],
        states={
            BC_WAIT_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_receive_msg)],
            BC_WAIT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_confirm)]
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        per_message=False
    )
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tg", tg_command_group))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify_check$"))
    
    app.add_handler(api_conv)
    app.add_handler(broadcast_conv)
    
    # Button handlers
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex("^(ℹ️ How to Use|📊 Stats|🏠 Main Menu)$"),
        button_handler
    ))
    
    # Number search in DM
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        search_number_dm
    ))
    
    logger.info("✅ Bot handlers loaded!")
    
    # Start polling
    async with app:
        await app.initialize()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        await app.start()
        logger.info("✅ Bot is running!")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
