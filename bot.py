# ============================================================
#   SRK AI MANAGER BOT  —  bot.py
#   Library : python-telegram-bot v20+
#   AI      : Google Gemini (3-key rotation)
#   DB      : SQLite3 (sync, WAL mode)
#   Deploy  : Railway.app ready
# ============================================================

import os
import sqlite3
import logging
import asyncio
import base64
import io
import re
from datetime import datetime, timedelta

import google.generativeai as genai
from PIL import Image

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode, ChatMemberStatus, ChatType

# ─────────────────────────────────────────────
#  CONFIG  —  Railway Environment Variables
# ─────────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_ID      = int(os.environ.get("ADMIN_ID", "0"))
GEMINI_KEY_1  = os.environ.get("GEMINI_KEY_1", "")
GEMINI_KEY_2  = os.environ.get("GEMINI_KEY_2", "")
GEMINI_KEY_3  = os.environ.get("GEMINI_KEY_3", "")
ALLOWED_GROUP = os.environ.get("ALLOWED_GROUP", "srking00001").lstrip("@").lower()

GEMINI_KEYS = [k for k in [GEMINI_KEY_1, GEMINI_KEY_2, GEMINI_KEY_3] if k]

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "srk_bot.db")

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("SRK-Bot")

# ─────────────────────────────────────────────
#  GEMINI KEY ROTATION ENGINE
# ─────────────────────────────────────────────
class GeminiEngine:
    def __init__(self, keys: list):
        if not keys:
            raise ValueError("Koi Gemini API key nahi mili! ENV check karo.")
        self.keys  = keys
        self.index = 0
        self._configure(keys[0])

    def _configure(self, key: str):
        genai.configure(api_key=key)
        self.model        = genai.GenerativeModel("gemini-1.5-flash")
        self.vision_model = genai.GenerativeModel("gemini-1.5-flash")
        log.info(f"Gemini key active → index {self.index}")

    def rotate(self):
        self.index = (self.index + 1) % len(self.keys)
        self._configure(self.keys[self.index])
        log.info(f"Gemini key rotated to index {self.index}")

    async def ask(self, prompt: str, image_bytes: bytes = None, retries: int = 6) -> str:
        for attempt in range(retries):
            try:
                if image_bytes:
                    img  = Image.open(io.BytesIO(image_bytes))
                    resp = self.vision_model.generate_content([prompt, img])
                else:
                    resp = self.model.generate_content(prompt)
                return resp.text.strip()
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ("quota", "429", "rate", "limit", "exhausted", "resource")):
                    log.warning(f"Key {self.index} limit hit rotating")
                    self.rotate()
                else:
                    log.error(f"Gemini error attempt {attempt+1}: {e}")
                    await asyncio.sleep(1.5)
        return "Yaar thoda busy hoon abhi, ek minute baad try karo! 😅"


ai = GeminiEngine(GEMINI_KEYS) if GEMINI_KEYS else None

# ─────────────────────────────────────────────
#  DATABASE  —  SQLite3 (sync + WAL)
# ─────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name  TEXT DEFAULT '',
            joined_at  TEXT DEFAULT (datetime('now')),
            is_banned  INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chat_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            chat_id    INTEGER,
            chat_type  TEXT,
            role       TEXT,
            content    TEXT,
            timestamp  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            chat_id    INTEGER,
            reason     TEXT,
            warn_count INTEGER DEFAULT 1,
            timestamp  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id        INTEGER PRIMARY KEY,
            welcome_msg    TEXT DEFAULT '',
            welcome_image  TEXT DEFAULT '',
            rules          TEXT DEFAULT '',
            antilink       INTEGER DEFAULT 1,
            antispam       INTEGER DEFAULT 1,
            antiabuse      INTEGER DEFAULT 1,
            warn_limit     INTEGER DEFAULT 3,
            mute_on_warn   INTEGER DEFAULT 0,
            locked         INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS banned_words (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            word    TEXT,
            UNIQUE(chat_id, word)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            keyword TEXT,
            content TEXT,
            UNIQUE(chat_id, keyword)
        );
        CREATE TABLE IF NOT EXISTS filters_table (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  INTEGER,
            trigger  TEXT,
            response TEXT,
            UNIQUE(chat_id, trigger)
        );
        CREATE TABLE IF NOT EXISTS afk_users (
            user_id INTEGER PRIMARY KEY,
            reason  TEXT DEFAULT '',
            since   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS admin_config (
            key_name TEXT PRIMARY KEY,
            value    TEXT
        );
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized")


# ─── DB Helpers ──────────────────────────────

def db_upsert_user(user):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (user_id, username, first_name, last_name)
        VALUES (?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name
    """, (user.id, user.username or "", user.first_name or "", user.last_name or ""))
    conn.commit()
    conn.close()


def db_save_message(user_id: int, chat_id: int, chat_type: str, role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO chat_history (user_id, chat_id, chat_type, role, content) VALUES (?,?,?,?,?)",
        (user_id, chat_id, chat_type, role, content)
    )
    conn.commit()
    conn.close()


def db_get_history(user_id: int, chat_id: int, limit: int = 60) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT role, content FROM chat_history
        WHERE user_id=? AND chat_id=?
        ORDER BY id DESC LIMIT ?
    """, (user_id, chat_id, limit)).fetchall()
    conn.close()
    return list(reversed(rows))


def db_get_warnings(user_id: int, chat_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(warn_count),0) FROM warnings WHERE user_id=? AND chat_id=?",
        (user_id, chat_id)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def db_add_warning(user_id: int, chat_id: int, reason: str):
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id)
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE warnings SET warn_count=warn_count+1, reason=?, timestamp=datetime('now')
            WHERE user_id=? AND chat_id=?
        """, (reason, user_id, chat_id))
    else:
        conn.execute(
            "INSERT INTO warnings (user_id, chat_id, reason) VALUES (?,?,?)",
            (user_id, chat_id, reason)
        )
    conn.commit()
    conn.close()


def db_reset_warnings(user_id: int, chat_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
    conn.commit()
    conn.close()


def db_get_setting(chat_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM group_settings WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def db_set_setting(chat_id: int, key: str, value):
    conn = get_conn()
    conn.execute(f"""
        INSERT INTO group_settings (chat_id, {key}) VALUES (?,?)
        ON CONFLICT(chat_id) DO UPDATE SET {key}=excluded.{key}
    """, (chat_id, value))
    conn.commit()
    conn.close()


def db_get_banned_words(chat_id: int) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT word FROM banned_words WHERE chat_id=?", (chat_id,)).fetchall()
    conn.close()
    return [r["word"].lower() for r in rows]


def db_add_banned_word(chat_id: int, word: str):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO banned_words (chat_id, word) VALUES (?,?)",
                 (chat_id, word.lower()))
    conn.commit()
    conn.close()


def db_del_banned_word(chat_id: int, word: str):
    conn = get_conn()
    conn.execute("DELETE FROM banned_words WHERE chat_id=? AND word=?",
                 (chat_id, word.lower()))
    conn.commit()
    conn.close()


def db_save_note(chat_id: int, keyword: str, content: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO notes (chat_id, keyword, content) VALUES (?,?,?)",
                 (chat_id, keyword.lower(), content))
    conn.commit()
    conn.close()


def db_get_note(chat_id: int, keyword: str):
    conn = get_conn()
    row = conn.execute("SELECT content FROM notes WHERE chat_id=? AND keyword=?",
                       (chat_id, keyword.lower())).fetchone()
    conn.close()
    return row["content"] if row else None


def db_list_notes(chat_id: int) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT keyword FROM notes WHERE chat_id=?", (chat_id,)).fetchall()
    conn.close()
    return [r["keyword"] for r in rows]


def db_save_filter(chat_id: int, trigger: str, response: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO filters_table (chat_id, trigger, response) VALUES (?,?,?)",
                 (chat_id, trigger.lower(), response))
    conn.commit()
    conn.close()


def db_get_filters(chat_id: int) -> list:
    conn = get_conn()
    rows = conn.execute("SELECT trigger, response FROM filters_table WHERE chat_id=?",
                        (chat_id,)).fetchall()
    conn.close()
    return [(r["trigger"], r["response"]) for r in rows]


def db_del_filter(chat_id: int, trigger: str):
    conn = get_conn()
    conn.execute("DELETE FROM filters_table WHERE chat_id=? AND trigger=?",
                 (chat_id, trigger.lower()))
    conn.commit()
    conn.close()


def db_set_afk(user_id: int, reason: str = ""):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO afk_users (user_id, reason) VALUES (?,?)",
                 (user_id, reason))
    conn.commit()
    conn.close()


def db_remove_afk(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM afk_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def db_is_afk(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT reason, since FROM afk_users WHERE user_id=?",
                       (user_id,)).fetchone()
    conn.close()
    return (row["reason"], row["since"]) if row else None


def db_admin_get(key: str):
    conn = get_conn()
    row = conn.execute("SELECT value FROM admin_config WHERE key_name=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def db_admin_set(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO admin_config (key_name, value) VALUES (?,?)",
                 (key, value))
    conn.commit()
    conn.close()


def db_count_users() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
    conn.close()
    return row["c"] if row else 0


def db_count_messages() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM chat_history").fetchone()
    conn.close()
    return row["c"] if row else 0


def db_count_warnings() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) as c FROM warnings WHERE warn_count > 0").fetchone()
    conn.close()
    return row["c"] if row else 0


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def mention_html(user) -> str:
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    name = name.strip() or "User"
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def is_admin(bot, chat_id: int, user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return True
    username = (chat.username or "").lower().lstrip("@")
    return username == ALLOWED_GROUP


URL_PATTERN = re.compile(r"(https?://\S+|t\.me/\S+|@\w{3,}|www\.\S+)", re.IGNORECASE)

def has_link(text: str) -> bool:
    return bool(URL_PATTERN.search(text or ""))


DEFAULT_ABUSE = [
    "madarchod","bhadwa","randi","chutiya","gaandu","bhosdi",
    "loda","lund","chut","harami","bastard","bitch","fuck",
    "motherfucker","asshole","sala","saala","kutte","kamine",
    "bkl","mkc","bc","mc","lc","teri maa","teri behen",
]

# ─────────────────────────────────────────────
#  SRK PERSONALITY
# ─────────────────────────────────────────────
SRK_PERSONA = """
Tu ek AI Manager hai jiska naam hai "SRK AI Manager".
Tu SRK King Official Telegram group ka official assistant aur dost hai.

Tu kaise baat karta hai:
- Bilkul ek real dost ki tarah: "Bhai", "Yaar", "Dost" bolega
- Hinglish mein (Hindi + English mix)
- Witty, funny, kabhi roast, kabhi serious
- Emoji SIRF situation ke hisaab se: happy pe 😄, serious pe 🤔, warning pe ⚠️, fact pe 📌, sad pe 😢
- Kabhi robot jaisa dry jawab nahi
- Real facts deta hai logon ko hoshiyaar banane ke liye:
  * Ameer banne ki baat pe: "Duniya ka sabse ameer Elon Musk (~$200B+), India mein Mukesh Ambani (~$100B+). Tu abhi bahut door hai! 😂 Par sapna rakh!"
  * General knowledge, tips, current affairs sab share karta hai
- Conversation history yaad rakhta hai aur refer karta hai
- Kabhi nahi batata ki peeche kaunsa AI hai
- Har action mein SRK King Official brand promote karta hai
- Short sawaal ka short jawab, complex ka detailed
"""


def build_prompt(user_id: int, chat_id: int, user_name: str, user_text: str) -> str:
    history = db_get_history(user_id, chat_id, limit=60)
    hist_str = ""
    for row in history:
        tag = "User" if row[0] == "user" else "SRK Manager"
        hist_str += f"{tag}: {row[1]}\n"
    custom  = db_admin_get("custom_persona")
    persona = custom if custom else SRK_PERSONA
    return (
        f"{persona}\n\n"
        f"--- Conversation History ---\n{hist_str}---\n\n"
        f"User ka naam: {user_name}\n"
        f"User ka message: {user_text}\n\n"
        f"Ab SRK Manager ki tarah naturally jawab de. Situation ke hisaab se emoji use kar."
    )


# ─────────────────────────────────────────────
#  AI MODERATION
# ─────────────────────────────────────────────

async def check_spam_ai(text: str) -> bool:
    if not ai:
        return False
    result = await ai.ask(
        f'Telegram group spam/promotion detector.\nMessage: "{text}"\nSirf: YES ya NO'
    )
    return result.strip().upper().startswith("YES")


async def check_abuse_ai(text: str) -> bool:
    if not ai:
        return False
    result = await ai.ask(
        f'Telegram group abuse/gaali detector.\nMessage: "{text}"\nSirf: YES ya NO'
    )
    return result.strip().upper().startswith("YES")


async def apply_warning(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         target_user, reason: str, settings: dict):
    chat_id    = update.effective_chat.id
    warn_limit = settings.get("warn_limit", 3)
    try:
        await update.effective_message.delete()
    except Exception:
        pass
    db_add_warning(target_user.id, chat_id, reason)
    warn_count = db_get_warnings(target_user.id, chat_id)

    if warn_count >= warn_limit:
        try:
            await context.bot.ban_chat_member(chat_id, target_user.id)
            db_reset_warnings(target_user.id, chat_id)
            text = (
                f"🔨 {mention_html(target_user)} ko <b>PERMANENT BAN</b>!\n"
                f"📋 Reason: {reason}\n"
                f"⚠️ {warn_limit} warnings = BAN. Yahi rule hai.\n\n"
                f"— <b>SRK King Official</b> 👑"
            )
        except Exception as e:
            text = f"Ban error: {e}"
    elif warn_count == warn_limit - 1:
        if settings.get("mute_on_warn"):
            try:
                until = datetime.now() + timedelta(hours=1)
                await context.bot.restrict_chat_member(
                    chat_id, target_user.id,
                    ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                text = (
                    f"🔇 {mention_html(target_user)} — Warning <b>{warn_count}/{warn_limit}</b>\n"
                    f"Reason: {reason}\n1 ghanta mute + agle baar BAN! 😤\n"
                    f"— <b>SRK King Official</b> 👑"
                )
            except Exception:
                text = (
                    f"⚠️ {mention_html(target_user)} — Warning <b>{warn_count}/{warn_limit}</b>\n"
                    f"Reason: {reason}\nEk aur = PERMANENT BAN! 🚫\n"
                    f"— <b>SRK King Official</b> 👑"
                )
        else:
            text = (
                f"⚠️ {mention_html(target_user)} — Warning <b>{warn_count}/{warn_limit}</b>\n"
                f"Reason: {reason}\nAgle baar BAN! 😠\n"
                f"— <b>SRK King Official</b> 👑"
            )
    else:
        text = (
            f"⚠️ {mention_html(target_user)} — Warning <b>{warn_count}/{warn_limit}</b>\n"
            f"Reason: {reason}\nGroup rules follow karo bhai! 🙏\n"
            f"— <b>SRK King Official</b> 👑"
        )
    await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────
#  COMMAND HANDLERS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    user = update.effective_user
    db_upsert_user(user)
    name = user.first_name or "Bhai"
    await update.message.reply_text(
        f"Oye {name}! 👋 Kya haal hai?\n\n"
        f"Main hoon <b>SRK AI Manager</b> — SRK King Official ka dost aur manager! 😎\n\n"
        f"<b>Kya kar sakta hoon?</b>\n"
        f"• Koi bhi sawaal pooch 🤓\n"
        f"• /getprompt — Photo se AI prompt 🎨\n"
        f"• /help — Puri command list 📋\n\n"
        f"Bol bhai, kya scene hai? 🚀\n\n"
        f"— <b>SRK King Official</b> 👑",
        parse_mode=ParseMode.HTML
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    await update.message.reply_text(
        "📋 <b>SRK AI Manager — Commands</b>\n\n"
        "<b>👤 General</b>\n"
        "/start — Bot se milna\n"
        "/help — Ye list\n"
        "/id — ID dekhna\n"
        "/info — User info\n"
        "/getprompt — Photo → AI Prompt\n"
        "/afk [reason] — AFK on\n"
        "/removafk — AFK off\n\n"
        "<b>📝 Notes & Filters</b>\n"
        "/save [keyword] [text] — Note save\n"
        "/get [keyword] — Note get\n"
        "/notes — Saare notes\n"
        "/delnote [keyword] — Note delete\n"
        "/filter [trigger] [response] — Auto reply\n"
        "/filters — Saare filters\n"
        "/delfilter [trigger] — Filter delete\n\n"
        "<b>🛡️ Moderation (Admin)</b>\n"
        "/warn [reason] — Warning do\n"
        "/warns — Warnings dekho\n"
        "/resetwarn — Reset warnings\n"
        "/ban [reason] — Ban karo\n"
        "/unban — Unban karo\n"
        "/unbanall — Sabko unban\n"
        "/kick — Kick karo\n"
        "/mute [30m/2h/1d] — Mute\n"
        "/unmute — Unmute\n"
        "/promote — Admin banao\n"
        "/demote — Admin hatao\n"
        "/pin — Message pin\n"
        "/unpin — Unpin\n"
        "/del — Message delete\n"
        "/lock — Group lock\n"
        "/unlock — Group unlock\n\n"
        "<b>⚙️ Settings (Admin)</b>\n"
        "/setwelcome [text] — Welcome set\n"
        "/antilink on/off\n"
        "/antispam on/off\n"
        "/antiabuse on/off\n"
        "/warnlimit [n]\n"
        "/addword [word]\n"
        "/delword [word]\n"
        "/bannedwords\n\n"
        "— <b>SRK King Official</b> 👑",
        parse_mode=ParseMode.HTML
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        await update.message.reply_text(
            f"👤 <b>{u.first_name}</b> ka ID: <code>{u.id}</code>",
            parse_mode=ParseMode.HTML
        )
    else:
        u = update.effective_user
        await update.message.reply_text(
            f"👤 Tera ID: <code>{u.id}</code>\n💬 Chat ID: <code>{update.effective_chat.id}</code>",
            parse_mode=ParseMode.HTML
        )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    target   = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    warns    = db_get_warnings(target.id, update.effective_chat.id)
    settings = db_get_setting(update.effective_chat.id)
    limit    = settings.get("warn_limit", 3)
    await update.message.reply_text(
        f"📊 <b>User Info</b>\n\n"
        f"👤 Name: {target.first_name} {target.last_name or ''}\n"
        f"🆔 ID: <code>{target.id}</code>\n"
        f"📎 Username: @{target.username or 'None'}\n"
        f"⚠️ Warnings: {warns}/{limit}",
        parse_mode=ParseMode.HTML
    )


async def cmd_getprompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not ai:
        await update.message.reply_text("AI engine load nahi hua! ENV check karo 😅")
        return
    target      = update.message.reply_to_message if update.message.reply_to_message else update.message
    photo       = target.photo
    doc         = target.document
    has_photo   = bool(photo)
    has_img_doc = doc and doc.mime_type and "image" in doc.mime_type
    if not has_photo and not has_img_doc:
        await update.message.reply_text(
            "Bhai 😅 koi photo bhej ya photo pe reply karke /getprompt likho!\n"
            "Main uska detailed AI prompt bana dunga 🎨"
        )
        return
    wait_msg = await update.message.reply_text("🔍 Image scan ho rahi hai... ek second! ⏳")
    try:
        file      = await context.bot.get_file(photo[-1].file_id if has_photo else doc.file_id)
        img_bytes = await file.download_as_bytearray()
        result    = await ai.ask(
            "Ye image dekh aur iska ek detailed creative AI image generation prompt bana. "
            "Include karo: style, colors, mood, composition, lighting, subject details. "
            "Pehle ek line Hinglish mein describe, phir full English prompt.",
            image_bytes=bytes(img_bytes)
        )
        await wait_msg.delete()
        await update.message.reply_text(
            f"🎨 <b>Image ka AI Prompt ready hai bhai!</b>\n\n{result}\n\n"
            f"<i>Copy kar aur kisi bhi AI image tool mein paste karo!</i> ✨",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await wait_msg.delete()
        log.error(f"getprompt error: {e}")
        await update.message.reply_text("😅 Image process nahi ho payi! Dobara try karo.")


async def cmd_afk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    reason = " ".join(context.args) if context.args else "Kuch kaam hai"
    db_set_afk(update.effective_user.id, reason)
    await update.message.reply_text(
        f"😴 {mention_html(update.effective_user)} AFK ho gaye!\n"
        f"📝 Reason: <i>{reason}</i>",
        parse_mode=ParseMode.HTML
    )


async def cmd_removafk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    data = db_is_afk(update.effective_user.id)
    if data:
        db_remove_afk(update.effective_user.id)
        since = datetime.fromisoformat(data[1])
        mins  = int((datetime.now() - since).total_seconds() // 60)
        await update.message.reply_text(
            f"👋 Welcome back {mention_html(update.effective_user)}!\n"
            f"⏱️ Tu {mins} minute AFK tha! Kya chuuta? 😄",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("Bhai tu AFK mein tha hi nahi! 😂")


async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        await update.message.reply_text("Sirf admins notes save kar sakte hain! 😅")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /save [keyword] [content]")
        return
    db_save_note(update.effective_chat.id, context.args[0], " ".join(context.args[1:]))
    await update.message.reply_text(
        f"✅ Note <b>'{context.args[0]}'</b> save! 📝", parse_mode=ParseMode.HTML
    )


async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /get [keyword]")
        return
    content = db_get_note(update.effective_chat.id, context.args[0])
    await update.message.reply_text(content if content else f"'{context.args[0]}' nahi mila!")


async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    notes = db_list_notes(update.effective_chat.id)
    text  = ("📋 <b>Saved Notes:</b>\n" + "\n".join(f"• <code>{n}</code>" for n in notes)
             if notes else "Koi notes nahi!")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_delnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delnote [keyword]")
        return
    conn = get_conn()
    conn.execute("DELETE FROM notes WHERE chat_id=? AND keyword=?",
                 (update.effective_chat.id, context.args[0].lower()))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"🗑️ Note '{context.args[0]}' delete!")


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /filter [trigger] [response]")
        return
    db_save_filter(update.effective_chat.id, context.args[0], " ".join(context.args[1:]))
    await update.message.reply_text(
        f"✅ Filter <b>'{context.args[0]}'</b> set! 🎯", parse_mode=ParseMode.HTML
    )


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    fltrs = db_get_filters(update.effective_chat.id)
    text  = ("🔍 <b>Active Filters:</b>\n" + "\n".join(f"• <code>{f[0]}</code>" for f in fltrs)
             if fltrs else "Koi filter nahi!")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_delfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delfilter [trigger]")
        return
    db_del_filter(update.effective_chat.id, context.args[0])
    await update.message.reply_text(f"🗑️ Filter '{context.args[0]}' delete!")


async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        await update.message.reply_text("Sirf admins welcome set kar sakte hain! 🔐")
        return
    welcome_text = " ".join(context.args) if context.args else ""
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo     = update.message.reply_to_message.photo[-1]
        file_obj  = await context.bot.get_file(photo.file_id)
        img_bytes = await file_obj.download_as_bytearray()
        img_b64   = base64.b64encode(bytes(img_bytes)).decode()
        db_set_setting(update.effective_chat.id, "welcome_image", img_b64)
        await update.message.reply_text(
            "✅ Welcome image save! 🖼️\nPlaceholders: <code>{name}</code> <code>{mention}</code> <code>{count}</code>",
            parse_mode=ParseMode.HTML
        )
    if welcome_text:
        db_set_setting(update.effective_chat.id, "welcome_msg", welcome_text)
        await update.message.reply_text(
            f"✅ Welcome message save! 🎉\nPreview:\n<i>{welcome_text}</i>",
            parse_mode=ParseMode.HTML
        )
    elif not update.message.reply_to_message:
        await update.message.reply_text(
            "Usage: <code>/setwelcome Oye {name}, welcome!</code>\n"
            "Ya image pe reply karke: <code>/setwelcome [text]</code>",
            parse_mode=ParseMode.HTML
        )


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = update.chat_member
        if not result:
            return
        chat     = result.chat
        username = (chat.username or "").lower().lstrip("@")
        if username != ALLOWED_GROUP:
            return
        new_status = result.new_chat_member.status
        old_status = result.old_chat_member.status if result.old_chat_member else None
        if not (new_status == ChatMemberStatus.MEMBER and
                old_status in (None, ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)):
            return
        user = result.new_chat_member.user
        db_upsert_user(user)
        settings    = db_get_setting(chat.id)
        welcome_msg = settings.get("welcome_msg", "")
        welcome_img = settings.get("welcome_image", "")
        try:
            count = await context.bot.get_chat_member_count(chat.id)
        except Exception:
            count = "?"
        if not welcome_msg:
            welcome_msg = (
                "🎉 Oye {name}, SRK King Official mein aane ka swagat hai!\n"
                "Group rules padhna mat bhoolo! 😄\nAbhi {count} members hain!"
            )
        formatted = (welcome_msg
                     .replace("{name}", user.first_name or "Dost")
                     .replace("{mention}", f'<a href="tg://user?id={user.id}">{user.first_name or "Dost"}</a>')
                     .replace("{count}", str(count)))
        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("📜 Group Rules", callback_data=f"rules_{chat.id}"),
            InlineKeyboardButton("👑 SRK King", url=f"https://t.me/{ALLOWED_GROUP}"),
        ]])
        if welcome_img:
            try:
                bio      = io.BytesIO(base64.b64decode(welcome_img))
                bio.name = "welcome.jpg"
                await context.bot.send_photo(
                    chat.id, photo=bio, caption=formatted,
                    reply_markup=btn, parse_mode=ParseMode.HTML
                )
                return
            except Exception as e:
                log.error(f"Welcome image error: {e}")
        await context.bot.send_message(
            chat.id, formatted, reply_markup=btn, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.error(f"New member handler error: {e}")


async def cb_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    chat_id  = int(query.data.split("_")[1])
    settings = db_get_setting(chat_id)
    rules    = settings.get("rules", "")
    await query.answer(
        rules[:200] if rules else "Rules abhi set nahi! Admin se poochho. 😅",
        show_alert=True
    )


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        await update.message.reply_text("Ye admin ka kaam hai! 😅")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke /warn use karo!")
        return
    target = update.message.reply_to_message.from_user
    if await is_admin(context.bot, update.effective_chat.id, target.id):
        await update.message.reply_text("Admin ko warn nahi kar sakte! 😂")
        return
    reason   = " ".join(context.args) if context.args else "Group rules violation"
    settings = db_get_setting(update.effective_chat.id)
    await apply_warning(update, context, target, reason, settings)


async def cmd_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    target   = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
    settings = db_get_setting(update.effective_chat.id)
    warns    = db_get_warnings(target.id, update.effective_chat.id)
    limit    = settings.get("warn_limit", 3)
    await update.message.reply_text(
        f"⚠️ {mention_html(target)} warnings: <b>{warns}/{limit}</b>",
        parse_mode=ParseMode.HTML
    )


async def cmd_resetwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo!")
        return
    target = update.message.reply_to_message.from_user
    db_reset_warnings(target.id, update.effective_chat.id)
    await update.message.reply_text(
        f"✅ {mention_html(target)} warnings reset! Fresh start 😊",
        parse_mode=ParseMode.HTML
    )


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        await update.message.reply_text("Tu admin nahi hai! 😅")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke /ban use karo!")
        return
    target = update.message.reply_to_message.from_user
    if await is_admin(context.bot, update.effective_chat.id, target.id):
        await update.message.reply_text("Admin ko ban nahi kar sakte! 🤦")
        return
    reason = " ".join(context.args) if context.args else "Admin decision"
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            f"🔨 {mention_html(target)} <b>BANNED!</b>\nReason: {reason}\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target = await context.bot.get_chat(context.args[0].lstrip("@"))
        except Exception:
            await update.message.reply_text("User nahi mila!")
            return
    if not target:
        await update.message.reply_text("Kisko unban karna hai?")
        return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            f"✅ {mention_html(target)} unban! Ek aur mauka 😊\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_unbanall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Ye sirf main admin (SRK) chala sakta hai! 😤")
        return
    wait  = await update.message.reply_text("⏳ Sabko unban kar raha hoon...")
    count = 0
    conn  = get_conn()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    for row in users:
        try:
            await context.bot.unban_chat_member(
                update.effective_chat.id, row["user_id"], only_if_banned=True
            )
            count += 1
            await asyncio.sleep(0.3)
        except Exception:
            pass
    await wait.edit_text(
        f"✅ Done! <b>{count}</b> log unban!\n"
        f"SRK King Official ki taraf se maafi! 🙏\n— <b>SRK King Official</b> 👑",
        parse_mode=ParseMode.HTML
    )


async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo!")
        return
    target = update.message.reply_to_message.from_user
    if await is_admin(context.bot, update.effective_chat.id, target.id):
        await update.message.reply_text("Admin ko kick nahi kar sakte! 😂")
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            f"👢 {mention_html(target)} kicked! Sudhar ke aa sakte ho. 😤\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo! /mute 30m")
        return
    target = update.message.reply_to_message.from_user
    if await is_admin(context.bot, update.effective_chat.id, target.id):
        await update.message.reply_text("Admin ko mute nahi kar sakte! 🙈")
        return
    until_date    = None
    duration_text = "jab tak unmute na ho"
    if context.args:
        match = re.match(r"(\d+)([mhd])", context.args[0])
        if match:
            num, unit = int(match.group(1)), match.group(2)
            delta = {"m": timedelta(minutes=num), "h": timedelta(hours=num),
                     "d": timedelta(days=num)}.get(unit, timedelta(hours=1))
            until_date    = datetime.now() + delta
            duration_text = f"{num} {'minute' if unit=='m' else 'ghante' if unit=='h' else 'din'}"
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await update.message.reply_text(
            f"🔇 {mention_html(target)} mute!\nDuration: {duration_text}\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo!")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
            )
        )
        await update.message.reply_text(
            f"🔊 {mention_html(target)} unmute! Sambhal ke rehna 😊\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo!")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, target.id,
            can_delete_messages=True, can_restrict_members=True,
            can_pin_messages=True, can_promote_members=False,
        )
        await update.message.reply_text(
            f"⭐ {mention_html(target)} ab Admin! Zimedaari nibhana 💪\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply karke use karo!")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, target.id,
            can_delete_messages=False, can_restrict_members=False,
            can_pin_messages=False,
        )
        await update.message.reply_text(
            f"📉 {mention_html(target)} demote! Ab normal member. 😐\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Kisi message pe reply karke /pin use karo!")
        return
    try:
        await context.bot.pin_chat_message(
            update.effective_chat.id, update.message.reply_to_message.message_id
        )
        await update.message.reply_text("📌 Message pin!")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
        await update.message.reply_text("📌 Unpin ho gaya!")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if update.message.reply_to_message:
        try:
            await update.message.reply_to_message.delete()
        except Exception:
            pass
    try:
        await update.message.delete()
    except Exception:
        pass


async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions())
        db_set_setting(update.effective_chat.id, "locked", 1)
        await update.message.reply_text(
            "🔒 Group lock! Sirf admins message kar sakte hain.\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True,
        ))
        db_set_setting(update.effective_chat.id, "locked", 0)
        await update.message.reply_text(
            "🔓 Group unlock! Sab baat kar sakte hain! 🎉\n— <b>SRK King Official</b> 👑",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_antilink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    val = 1 if context.args and context.args[0].lower() == "on" else 0
    db_set_setting(update.effective_chat.id, "antilink", val)
    await update.message.reply_text(
        f"🔗 Anti-Link: <b>{'ON ✅' if val else 'OFF ❌'}</b>", parse_mode=ParseMode.HTML
    )


async def cmd_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    val = 1 if context.args and context.args[0].lower() == "on" else 0
    db_set_setting(update.effective_chat.id, "antispam", val)
    await update.message.reply_text(
        f"🛡️ Anti-Spam: <b>{'ON ✅' if val else 'OFF ❌'}</b>", parse_mode=ParseMode.HTML
    )


async def cmd_antiabuse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    val = 1 if context.args and context.args[0].lower() == "on" else 0
    db_set_setting(update.effective_chat.id, "antiabuse", val)
    await update.message.reply_text(
        f"🤬 Anti-Abuse: <b>{'ON ✅' if val else 'OFF ❌'}</b>", parse_mode=ParseMode.HTML
    )


async def cmd_warnlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /warnlimit [number]")
        return
    db_set_setting(update.effective_chat.id, "warn_limit", int(context.args[0]))
    await update.message.reply_text(
        f"⚠️ Warn limit: <b>{context.args[0]}</b>", parse_mode=ParseMode.HTML
    )


async def cmd_addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addword [word]")
        return
    db_add_banned_word(update.effective_chat.id, context.args[0])
    await update.message.reply_text(
        f"✅ <b>'{context.args[0]}'</b> banned! 🚫", parse_mode=ParseMode.HTML
    )


async def cmd_delword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delword [word]")
        return
    db_del_banned_word(update.effective_chat.id, context.args[0])
    await update.message.reply_text(f"✅ '{context.args[0]}' list se hata diya!")


async def cmd_bannedwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update) or not await is_admin(context.bot, update.effective_chat.id, update.effective_user.id):
        return
    words = db_get_banned_words(update.effective_chat.id)
    text  = ("🚫 <b>Banned Words:</b>\n" + ", ".join(f"<code>{w}</code>" for w in words)
             if words else "Koi banned word nahi!")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        f"📊 <b>SRK Bot Stats</b>\n\n"
        f"👤 Users: <code>{db_count_users()}</code>\n"
        f"💬 Messages: <code>{db_count_messages()}</code>\n"
        f"⚠️ Warnings: <code>{db_count_warnings()}</code>\n"
        f"🤖 AI Keys: <code>{len(GEMINI_KEYS)}</code>\n\n"
        f"— <b>SRK King Official</b> 👑",
        parse_mode=ParseMode.HTML
    )


async def cmd_getdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        await update.message.reply_document(
            DB_PATH, caption="📦 SRK Bot Database — SRK King Official 👑"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_setpersona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("/setpersona [new personality text]")
        return
    db_admin_set("custom_persona", " ".join(context.args))
    await update.message.reply_text("✅ Personality update! 🎭")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast [message]")
        return
    text = " ".join(context.args)
    conn = get_conn()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    sent, failed = 0, 0
    for row in users:
        try:
            await context.bot.send_message(
                row["user_id"],
                f"📢 <b>SRK King Official:</b>\n\n{text}",
                parse_mode=ParseMode.HTML
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 Done! ✅ {sent} sent | ❌ {failed} failed")


async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "🔧 <b>Admin DM Commands</b>\n\n"
        "/stats — Bot stats\n"
        "/getdb — Database file\n"
        "/setpersona [text] — Personality change\n"
        "/broadcast [text] — Sab users ko message\n\n"
        "— <b>SRK King Official</b> 👑",
        parse_mode=ParseMode.HTML
    )


# ─────────────────────────────────────────────
#  MAIN MESSAGE HANDLER  (AI + Moderation)
# ─────────────────────────────────────────────

COMMAND_LIST = {
    "start","help","id","info","getprompt","afk","removafk",
    "save","get","notes","delnote","filter","filters","delfilter",
    "setwelcome","warn","warns","resetwarn","ban","unban","unbanall",
    "kick","mute","unmute","promote","demote","pin","unpin","del",
    "lock","unlock","antilink","antispam","antiabuse","warnlimit",
    "addword","delword","bannedwords","stats","getdb","setpersona",
    "broadcast","adminhelp",
}


async def main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_allowed_chat(update):
        return
    user = update.effective_user
    if not user or user.is_bot:
        return

    chat    = update.effective_chat
    message = update.message
    text    = message.text or message.caption or ""
    is_grp  = chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    # Skip commands
    if text.startswith("/"):
        cmd = text.split()[0].lstrip("/").split("@")[0].lower()
        if cmd in COMMAND_LIST:
            return

    db_upsert_user(user)

    # AFK auto-remove
    if is_grp:
        afk_data = db_is_afk(user.id)
        if afk_data:
            db_remove_afk(user.id)
            try:
                await message.reply_text(
                    f"👋 Welcome back {mention_html(user)}! AFK off 😄",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    # AFK check on reply
    if is_grp and message.reply_to_message and message.reply_to_message.from_user:
        t = message.reply_to_message.from_user
        if not t.is_bot:
            afk_info = db_is_afk(t.id)
            if afk_info:
                since = datetime.fromisoformat(afk_info[1])
                mins  = int((datetime.now() - since).total_seconds() // 60)
                try:
                    await message.reply_text(
                        f"😴 {mention_html(t)} AFK mein hai!\n"
                        f"📝 Reason: <i>{afk_info[0]}</i> | ⏱️ {mins} min\nBaad mein ping karo! 🙏",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass

    # Filter check
    if is_grp and text:
        for trigger, response in db_get_filters(chat.id):
            if trigger in text.lower():
                try:
                    await message.reply_text(response)
                except Exception:
                    pass
                return

    # MODERATION
    if is_grp and not await is_admin(context.bot, chat.id, user.id):
        settings = db_get_setting(chat.id)

        if text:
            all_abuse  = DEFAULT_ABUSE + db_get_banned_words(chat.id)
            lower_text = text.lower()
            for word in all_abuse:
                if word in lower_text:
                    await apply_warning(update, context, user, f"Banned word: '{word}'", settings)
                    return

        if settings.get("antiabuse", 1) and text:
            if await check_abuse_ai(text):
                await apply_warning(update, context, user, "Abusive language detected", settings)
                return

        if settings.get("antilink", 1) and has_link(text):
            if await check_spam_ai(text):
                await apply_warning(update, context, user, "Unauthorized link/promotion", settings)
                return

        if settings.get("antispam", 1) and text and not has_link(text):
            if await check_spam_ai(text):
                await apply_warning(update, context, user, "Spam detected", settings)
                return

    # AI CHAT
    if not ai:
        return

    should_respond = False
    if not is_grp:
        should_respond = True
    else:
        bot_info     = await context.bot.get_me()
        bot_username = (bot_info.username or "").lower()
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.is_bot:
                should_respond = True
        if f"@{bot_username}" in text.lower():
            should_respond = True
        if not should_respond and text:
            if any(k in text.lower() for k in ["bhai", "yaar", "bot", "srk", "manager",
                                                "help me", "kya", "kaun", "kaise", "kyun",
                                                "batao", "bata"]):
                should_respond = True

    if not should_respond:
        if text:
            db_save_message(user.id, chat.id,
                            "private" if not is_grp else "group", "user", text)
        return

    db_save_message(user.id, chat.id,
                    "private" if not is_grp else "group", "user", text or "[media]")

    user_name = user.first_name or "Dost"

    if message.photo or (message.document and message.document.mime_type and
                          "image" in (message.document.mime_type or "")):
        try:
            media     = message.photo[-1] if message.photo else message.document
            file      = await context.bot.get_file(media.file_id)
            img_bytes = await file.download_as_bytearray()
            hist      = db_get_history(user.id, chat.id, 30)
            hist_str  = "\n".join(
                f"{'User' if r[0]=='user' else 'SRK Manager'}: {r[1]}" for r in hist
            )
            custom   = db_admin_get("custom_persona")
            persona  = custom if custom else SRK_PERSONA
            response = await ai.ask(
                f"{persona}\n\nHistory:\n{hist_str}\n\n"
                f"User ({user_name}) ne image bheji{' aur kaha: ' + text if text else ''}. "
                f"Naturally react kar, situation ke hisaab se emoji.",
                image_bytes=bytes(img_bytes)
            )
        except Exception as e:
            log.error(f"Image AI error: {e}")
            response = "Yaar image nahi dekh paya! 😅 Dobara bhej!"
    else:
        response = await ai.ask(build_prompt(user.id, chat.id, user_name, text))

    db_save_message(user.id, chat.id,
                    "private" if not is_grp else "group", "assistant", response)
    try:
        await message.reply_text(response)
    except Exception as e:
        log.error(f"Reply error: {e}")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable set nahi hai!")

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start",       cmd_start))
    application.add_handler(CommandHandler("help",        cmd_help))
    application.add_handler(CommandHandler("id",          cmd_id))
    application.add_handler(CommandHandler("info",        cmd_info))
    application.add_handler(CommandHandler("getprompt",   cmd_getprompt))
    application.add_handler(CommandHandler("afk",         cmd_afk))
    application.add_handler(CommandHandler("removafk",    cmd_removafk))
    application.add_handler(CommandHandler("save",        cmd_save))
    application.add_handler(CommandHandler("get",         cmd_get))
    application.add_handler(CommandHandler("notes",       cmd_notes))
    application.add_handler(CommandHandler("delnote",     cmd_delnote))
    application.add_handler(CommandHandler("filter",      cmd_filter))
    application.add_handler(CommandHandler("filters",     cmd_filters))
    application.add_handler(CommandHandler("delfilter",   cmd_delfilter))
    application.add_handler(CommandHandler("setwelcome",  cmd_setwelcome))
    application.add_handler(CommandHandler("warn",        cmd_warn))
    application.add_handler(CommandHandler("warns",       cmd_warns))
    application.add_handler(CommandHandler("resetwarn",   cmd_resetwarn))
    application.add_handler(CommandHandler("ban",         cmd_ban))
    application.add_handler(CommandHandler("unban",       cmd_unban))
    application.add_handler(CommandHandler("unbanall",    cmd_unbanall))
    application.add_handler(CommandHandler("kick",        cmd_kick))
    application.add_handler(CommandHandler("mute",        cmd_mute))
    application.add_handler(CommandHandler("unmute",      cmd_unmute))
    application.add_handler(CommandHandler("promote",     cmd_promote))
    application.add_handler(CommandHandler("demote",      cmd_demote))
    application.add_handler(CommandHandler("pin",         cmd_pin))
    application.add_handler(CommandHandler("unpin",       cmd_unpin))
    application.add_handler(CommandHandler("del",         cmd_del))
    application.add_handler(CommandHandler("lock",        cmd_lock))
    application.add_handler(CommandHandler("unlock",      cmd_unlock))
    application.add_handler(CommandHandler("antilink",    cmd_antilink))
    application.add_handler(CommandHandler("antispam",    cmd_antispam))
    application.add_handler(CommandHandler("antiabuse",   cmd_antiabuse))
    application.add_handler(CommandHandler("warnlimit",   cmd_warnlimit))
    application.add_handler(CommandHandler("addword",     cmd_addword))
    application.add_handler(CommandHandler("delword",     cmd_delword))
    application.add_handler(CommandHandler("bannedwords", cmd_bannedwords))
    application.add_handler(CommandHandler("stats",       cmd_stats))
    application.add_handler(CommandHandler("getdb",       cmd_getdb))
    application.add_handler(CommandHandler("setpersona",  cmd_setpersona))
    application.add_handler(CommandHandler("broadcast",   cmd_broadcast))
    application.add_handler(CommandHandler("adminhelp",   cmd_adminhelp))
    application.add_handler(ChatMemberHandler(on_new_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(cb_rules, pattern=r"^rules_"))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, main_handler))

    log.info(f"SRK AI Manager Bot starting — group: @{ALLOWED_GROUP}")

    async with application:
        await application.initialize()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        await application.start()
        log.info("Bot is LIVE!")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
