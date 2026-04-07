import os
import sqlite3
import logging
import asyncio
import random
import string
import emoji as emoji_lib

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
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
ADMIN_ID  = 8379167923

DEVELOPER_USERNAME = "@LRVS12"
UPDATE_CHANNEL     = "https://t.me/srking0001"

PROTECTED_CHANNELS = {"srking0001", "srking00001", "botdevking"}

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "postbot.db")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#                   PREMIUM EMOJIS
# ═══════════════════════════════════════════════════════

PREMIUM_EMOJIS = [
    "6235355429237430006", "6147815573314082674", "5350427505805238170",
    "5287267357427776826", "5222447122586036397", "5224180824789770658",
    "5224663892646452625", "5224205542326557875", "5221953158397321906",
    "5309981979167463973", "5309928798882395910", "5246765089977037900",
    "5285161474833006232", "5285078504654783223", "5426918974971486256",
    "5474143948572223102", "5472057595193743789", "5472159355853888315",
    "6307665627481903641", "6088957586302831521", "6109328624777694916",
    "6109693533789096849", "6109213820301872263", "6109557847182281178",
    "6109447084270684884", "6109281659310312426", "6111423933162981989",
    "6109211870386720327", "6109655025112320594", "6123114099703287427",
    "6122990988760715630", "6123066743393881068", "6120791828066208322",
    "6221756527691173256", "6168137610507062619", "6192627406654671561",
    "6190651597144461028", "6192895915125116350", "6192532968913767492",
    "6217491333108470219", "5463071033256848094", "6235403472741603087",
    "6147565374289220368", "6147464060305676048", "6147524086768604985",
    "5449449325434266744", "6273840152980755328", "6276057176444246654",
    "6273997026661241933", "6273726078649372769", "6274007313107915274",
    "5978776771623914876", "5978686323907628843", "5852873584912896283",
    "5895297528106061174", "5895735846698487922", "5895343514320899727",
    "5913754823643107921", "5197434882321567830", "5463256910851546817",
    "5463423955014529788", "5465443379917629504", "5465465194056525619",
    "6235620067942341623", "6235717714023814969", "6235593671073339928",
    "6147617184479711380", "5346181118884331907", "5971944878815317190",
]


def process_text_and_entities(text: str, original_entities: list) -> tuple:
    """
    Normal emoji → Premium emoji (custom_emoji entity)
    Bold / link / formatting preserved via offset mapping.
    """
    if not text:
        return text, original_entities

    final_text   = ""
    new_entities = []
    offset_map   = {}

    current_old = 0
    current_new = 0

    for char in text:
        offset_map[current_old] = current_new

        if emoji_lib.is_emoji(char):
            rand_id     = random.choice(PREMIUM_EMOJIS)
            placeholder = "✨"
            new_entities.append(MessageEntity(
                type="custom_emoji",
                offset=current_new,
                length=len(placeholder),
                custom_emoji_id=rand_id,
            ))
            final_text  += placeholder
            char_len     = len(char.encode("utf-16-le")) // 2
            current_old += char_len
            current_new += len(placeholder)
        else:
            final_text  += char
            current_old += 1
            current_new += 1

    offset_map[current_old] = current_new

    for ent in (original_entities or []):
        if ent.type == "custom_emoji":
            continue
        new_start = offset_map.get(ent.offset)
        new_end   = offset_map.get(ent.offset + ent.length)
        if new_start is not None and new_end is not None:
            new_entities.append(MessageEntity(
                type=ent.type,
                offset=new_start,
                length=new_end - new_start,
                url=getattr(ent, "url", None),
                user=getattr(ent, "user", None),
                language=getattr(ent, "language", None),
                custom_emoji_id=getattr(ent, "custom_emoji_id", None),
            ))

    return final_text, new_entities


def extract_content(message):
    """Extract text/caption + entities + photo from a message."""
    if message.photo:
        raw_text     = message.caption or ""
        raw_entities = list(message.caption_entities or [])
        photo_id     = message.photo[-1].file_id
    else:
        raw_text     = message.text or ""
        raw_entities = list(message.entities or [])
        photo_id     = None

    proc_text, proc_entities = process_text_and_entities(raw_text, raw_entities)
    return proc_text, proc_entities, photo_id


# ═══════════════════════════════════════════════════════
#                  CONVERSATION STATES
# ═══════════════════════════════════════════════════════

(
    CREATE_WAIT_MSG,
    CREATE_WAIT_BTN_NAME,
    CREATE_WAIT_BTN_LINK,
    ADD_CH_WAIT_LINK,
    ADD_CH_WAIT_DONE,
    PIC_WAIT_OPTION,
    PIC_WAIT_CH_SELECT,
    PIC_WAIT_MSG,
    PIC_WAIT_BTN_NAME,
    PIC_WAIT_BTN_LINK,
    PIC_WAIT_POST_ID,
    BC_WAIT_TARGET,
    BC_WAIT_BTN_OPTION,
    BC_WAIT_MSG,
    BC_WAIT_BTN_NAME,
    BC_WAIT_BTN_LINK,
    BC_WAIT_CONFIRM,
    ADM_POST_CH_SELECT,
    ADM_POST_WAIT_MSG,
    ADM_POST_WAIT_BTN_NAME,
    ADM_POST_WAIT_BTN_LINK,
    ADM_POST_WAIT_CONFIRM,
) = range(22)

PRIVATE = filters.ChatType.PRIVATE

# ═══════════════════════════════════════════════════════
#                       DATABASE
# ═══════════════════════════════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            post_id    TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            msg_text   TEXT,
            photo_id   TEXT,
            btn_name   TEXT,
            btn_link   TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            ch_link     TEXT NOT NULL,
            ch_id       INTEGER NOT NULL,
            ch_title    TEXT,
            ch_username TEXT,
            added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ DB initialized")


# ── DB helpers ────────────────────────────────────────

def generate_post_id():
    chars = string.ascii_uppercase + string.digits
    conn  = get_conn()
    while True:
        pid    = "".join(random.choices(chars, k=10))
        exists = conn.execute("SELECT post_id FROM posts WHERE post_id=?", (pid,)).fetchone()
        if not exists:
            conn.close()
            return pid


def save_post(post_id, user_id, msg_text, btn_name, btn_link, photo_id=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO posts (post_id,user_id,msg_text,photo_id,btn_name,btn_link) VALUES (?,?,?,?,?,?)",
        (post_id, user_id, msg_text, photo_id, btn_name, btn_link),
    )
    conn.commit()
    conn.close()


def get_post(post_id):
    conn = get_conn()
    row  = conn.execute("SELECT * FROM posts WHERE post_id=?", (post_id.upper(),)).fetchone()
    conn.close()
    return row


def save_channel(user_id, ch_link, ch_id, ch_title, ch_username):
    conn = get_conn()
    ex   = conn.execute(
        "SELECT id FROM channels WHERE user_id=? AND ch_id=?", (user_id, ch_id)
    ).fetchone()
    if not ex:
        conn.execute(
            "INSERT INTO channels (user_id,ch_link,ch_id,ch_title,ch_username) VALUES (?,?,?,?,?)",
            (user_id, ch_link, ch_id, ch_title, ch_username),
        )
        conn.commit()
    conn.close()


def get_user_channels(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM channels WHERE user_id=? ORDER BY added_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_all_channel_ids_db():
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT ch_id FROM channels").fetchall()
    conn.close()
    return [r["ch_id"] for r in rows]


def count_users():
    conn = get_conn()
    c    = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    conn.close()
    return c


def count_channels():
    conn = get_conn()
    c    = conn.execute("SELECT COUNT(DISTINCT ch_id) as c FROM channels").fetchone()["c"]
    conn.close()
    return c


def register_user(user_id):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_all_user_ids():
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


# ── Live scan ─────────────────────────────────────────

async def live_scan_channels(bot):
    """Returns list of channels where bot is admin with post permission."""
    ch_ids = get_all_channel_ids_db()
    result = []
    seen   = set()
    for ch_id in ch_ids:
        if ch_id in seen:
            continue
        seen.add(ch_id)
        try:
            member   = await bot.get_chat_member(ch_id, bot.id)
            if member.status not in ("administrator", "creator"):
                continue
            can_post = getattr(member, "can_post_messages", None)
            if member.status == "administrator" and can_post is False:
                continue
            chat  = await bot.get_chat(ch_id)
            title = chat.title or str(ch_id)
            link  = None
            if chat.username:
                link = f"https://t.me/{chat.username}"
            else:
                can_invite = getattr(member, "can_invite_users", None)
                if member.status == "creator" or can_invite:
                    try:
                        link = await bot.export_chat_invite_link(ch_id)
                    except Exception:
                        link = None
            result.append({"ch_id": ch_id, "ch_title": title, "link": link})
        except Exception as e:
            logger.warning(f"Scan error {ch_id}: {e}")
    return result


# ═══════════════════════════════════════════════════════
#                   REPLY KEYBOARDS
# ═══════════════════════════════════════════════════════

def main_menu_kb(user_id=None):
    buttons = [
        [KeyboardButton("📝 Create Post"), KeyboardButton("📢 Add Channel")],
        [KeyboardButton("📤 Post in Channel")],
        [KeyboardButton("👨‍💻 Developer"),   KeyboardButton("🔄 Update Channel")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton("🛠 Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)


def done_cancel_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✅ Done — I made it admin")],
         [KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
    )


def pic_option_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📝 Make Post"), KeyboardButton("🔖 Post with Post ID")],
         [KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
    )


def admin_panel_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📣 Broadcast"),     KeyboardButton("📊 Stats")],
         [KeyboardButton("📡 Scan Channels"), KeyboardButton("📤 Admin Post")],
         [KeyboardButton("🏠 Main Menu")]],
        resize_keyboard=True,
    )


def bc_target_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📢 Only Channels"), KeyboardButton("👥 Only Users")],
         [KeyboardButton("📣 Both"),          KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
    )


def bc_btn_option_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🔘 With Button"), KeyboardButton("📄 Without Button")],
         [KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
    )


def confirm_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✅ Confirm"), KeyboardButton("❌ Cancel")]],
        resize_keyboard=True,
    )


# ═══════════════════════════════════════════════════════
#                   SEND HELPERS
# ═══════════════════════════════════════════════════════

async def send_post(bot, chat_id, msg_text, entities, photo_id, btn_name=None, btn_link=None):
    """Send a processed (premium emoji) post to a chat."""
    markup = None
    if btn_name and btn_link:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_name, url=btn_link)]])

    if photo_id:
        await bot.send_photo(
            chat_id, photo_id,
            caption=msg_text or None,
            caption_entities=entities if msg_text else None,
            reply_markup=markup,
        )
    else:
        await bot.send_message(
            chat_id, msg_text,
            entities=entities,
            reply_markup=markup,
        )


async def copy_message_raw(bot, msg, chat_id, extra_markup=None):
    """Copy a raw message (for broadcast without premium processing)."""
    if msg.photo:
        await bot.send_photo(chat_id, msg.photo[-1].file_id,
            caption=msg.caption, caption_entities=msg.caption_entities,
            reply_markup=extra_markup)
    elif msg.video:
        await bot.send_video(chat_id, msg.video.file_id,
            caption=msg.caption, caption_entities=msg.caption_entities,
            reply_markup=extra_markup)
    elif msg.document:
        await bot.send_document(chat_id, msg.document.file_id,
            caption=msg.caption, caption_entities=msg.caption_entities,
            reply_markup=extra_markup)
    elif msg.audio:
        await bot.send_audio(chat_id, msg.audio.file_id,
            caption=msg.caption, reply_markup=extra_markup)
    elif msg.sticker:
        await bot.send_sticker(chat_id, msg.sticker.file_id)
    elif msg.animation:
        await bot.send_animation(chat_id, msg.animation.file_id,
            caption=msg.caption, reply_markup=extra_markup)
    elif msg.voice:
        await bot.send_voice(chat_id, msg.voice.file_id)
    elif msg.video_note:
        await bot.send_video_note(chat_id, msg.video_note.file_id)
    else:
        await bot.send_message(chat_id, msg.text,
            entities=msg.entities, reply_markup=extra_markup)


# ═══════════════════════════════════════════════════════
#                   /start  &  /help
# ═══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    register_user(user_id)
    await update.message.reply_text(
        "✨ *Welcome to Premium Post Bot!*\n\n"
        "Yahan se apne channel mein *premium emoji* ke saath button wala post kar sakte ho — bilkul FREE!\n\n"
        "📖 Use `/help` to see how to use this bot.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(user_id),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    text = (
        "📖 *How to Use This Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "✨ *Premium Emoji System*\n"
        "Jab bhi aap message likhte ho normal emoji ke saath (😊🔥✅) — bot automatically unhe *premium animated emoji* mein convert kar deta hai!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📢 *Step 1 — Channel Add Karo*\n"
        "➊ `📢 Add Channel` button dabaao\n"
        "➋ Apne channel ka link bhejo\n"
        "➌ Bot ko channel mein Admin banaao\n"
        "　　✅ Permission: *Post Messages*\n"
        "➍ Bot mein `✅ Done` dabaao\n"
        "　→ Channel add ho jaayega! 🎉\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 *Step 2 — Post Banao (Create Post)*\n"
        "➊ `📝 Create Post` dabaao\n"
        "➋ Apna message bhejo *normal emoji ke saath*\n"
        "　　(Bold, link, quote sab chalega)\n"
        "➌ Button ka naam bhejo\n"
        "➍ Button ka link bhejo\n"
        "➎ ✅ Post ID milegi — *save kar lo!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📤 *Step 3 — Channel Mein Post Karo*\n\n"
        "*Option A — Make Post (Direct):*\n"
        "➊ `📤 Post in Channel` → `📝 Make Post`\n"
        "➋ Channel select karo\n"
        "➌ Message → Button Name → Button Link\n"
        "➍ ✅ Post ho jaayega!\n\n"
        "*Option B — Post ID Se:*\n"
        "➊ Pehle `📝 Create Post` se post banao\n"
        "➋ Post ID save karo\n"
        "➌ `📤 Post in Channel` → `🔖 Post with Post ID`\n"
        "➍ Channel select → Post ID bhejo → ✅ Done!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 *Tips:*\n"
        "• Post ID kisi bhi device se use ho sakta hai\n"
        "• Normal emoji likho — premium automatic ban jaata hai\n"
        "• /cancel se kisi bhi step se bahar aa sakte ho\n"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_kb(update.effective_user.id),
    )


async def check_joined_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("✅ *Welcome!*", parse_mode="Markdown")
    await context.bot.send_message(
        q.from_user.id,
        "👋 *Welcome!*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(q.from_user.id),
    )


# ═══════════════════════════════════════════════════════
#                STATIC MENU HANDLER
# ═══════════════════════════════════════════════════════

async def static_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    text    = update.message.text

    if text == "👨‍💻 Developer":
        await update.message.reply_text(
            f"👨‍💻 *Developer*\n\nContact: {DEVELOPER_USERNAME}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    elif text == "🔄 Update Channel":
        await update.message.reply_text(
            f"🔄 *Update Channel*\n\n{UPDATE_CHANNEL}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    elif text == "🏠 Main Menu":
        context.user_data.clear()
        await update.message.reply_text(
            "🏠 *Main Menu*",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    elif text == "🛠 Admin Panel" and user_id == ADMIN_ID:
        await update.message.reply_text(
            "🛠 *Admin Panel*\n\nChoose an action 👇",
            parse_mode="Markdown",
            reply_markup=admin_panel_kb(),
        )
    elif text == "📊 Stats" and user_id == ADMIN_ID:
        await update.message.reply_text(
            f"📊 *Stats*\n\n"
            f"👥 Total Users: *{count_users()}*\n"
            f"📢 Total Channels: *{count_channels()}*",
            parse_mode="Markdown",
            reply_markup=admin_panel_kb(),
        )
    elif text == "📡 Scan Channels" and user_id == ADMIN_ID:
        msg = await update.message.reply_text("🔄 *Scanning... please wait*", parse_mode="Markdown")
        channels = await live_scan_channels(context.bot)
        if not channels:
            await msg.edit_text(
                "📡 *Scan Complete!*\n\n❌ No channels found where bot is admin with post permission.",
                parse_mode="Markdown",
            )
        else:
            lines = []
            for ch in channels:
                if ch["link"]:
                    lines.append(f"✅ [{ch['ch_title']}]({ch['link']})")
                else:
                    lines.append(f"✅ {ch['ch_title']}")
            await msg.edit_text(
                "📡 *Scan Complete!*\n\nChannels with post permission:\n\n" + "\n".join(lines),
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        await update.message.reply_text("👇", reply_markup=admin_panel_kb())


# ═══════════════════════════════════════════════════════
#              CREATE POST CONVERSATION
# ═══════════════════════════════════════════════════════

async def create_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return ConversationHandler.END
    await update.message.reply_text(
        "📝 *Create Post — Step 1/3*\n\n"
        "Apna message bhejo *normal emoji ke saath* 😊🔥\n"
        "(Bold, link, quote sab chalega — premium emoji automatic ban jaayega!)\n\n"
        "Photo ke saath caption bhi bhej sakte ho 📸\n\n"
        "❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return CREATE_WAIT_MSG


async def create_recv_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    if update.message.content_type not in ("text", "photo"):
        await update.message.reply_text(
            "❌ Sirf text ya photo (with caption) bhejo.\n\n❌ /cancel",
            reply_markup=cancel_kb(),
        )
        return CREATE_WAIT_MSG

    proc_text, proc_entities, photo_id = extract_content(update.message)
    context.user_data["post_text"]     = proc_text
    context.user_data["post_entities"] = proc_entities
    context.user_data["post_photo"]    = photo_id

    await update.message.reply_text(
        "✅ Message mila!\n\n📝 *Step 2/3* — Button ka *naam* bhejo 👇\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return CREATE_WAIT_BTN_NAME


async def create_recv_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    context.user_data["btn_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Button naam: *{context.user_data['btn_name']}*\n\n"
        "📝 *Step 3/3* — Button ka *link* bhejo (https:// se shuru hona chahiye)\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return CREATE_WAIT_BTN_LINK


async def create_recv_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    link = update.message.text.strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "❌ *Invalid link!* https:// se shuru hona chahiye.\n\nDobara bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return CREATE_WAIT_BTN_LINK

    proc_text  = context.user_data["post_text"]
    entities   = context.user_data["post_entities"]
    photo_id   = context.user_data.get("post_photo")
    btn_name   = context.user_data["btn_name"]
    user_id    = update.effective_user.id
    post_id    = generate_post_id()

    save_post(post_id, user_id, proc_text, btn_name, link, photo_id)

    await update.message.reply_text(
        "✨ *Preview dekho:*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(user_id),
    )
    await send_post(context.bot, update.effective_chat.id,
                    proc_text, entities, photo_id, btn_name, link)
    await update.message.reply_text(
        f"🎉 *Post ID:* `{post_id}`\n\n"
        "📌 Is ID ko save karo. Isse *Post in Channel* mein kabhi bhi use kar sakte ho!",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(user_id),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#              ADD CHANNEL CONVERSATION
# ═══════════════════════════════════════════════════════

async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 *Add Channel — Step 1/2*\n\n"
        "Apne channel ya group ka link bhejo 👇\n"
        "Example: https://t.me/yourchannel\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return ADD_CH_WAIT_LINK


async def add_ch_recv_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    link = update.message.text.strip()
    if "t.me/" not in link:
        await update.message.reply_text(
            "❌ *Invalid link!* Valid Telegram link bhejo.\n\nDobara bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return ADD_CH_WAIT_LINK

    username = link.split("t.me/")[-1].strip("/").split("/")[0]
    if username in PROTECTED_CHANNELS and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "❌ *Yeh channel protected hai!*\n\nAap ise add nahi kar sakte.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(update.effective_user.id),
        )
        return ConversationHandler.END

    context.user_data["ch_link"]     = link
    context.user_data["ch_username"] = username
    bot_info = await context.bot.get_me()
    await update.message.reply_text(
        f"✅ *Link mila!*\n\n"
        f"📝 *Step 2/2* — Ab *@{bot_info.username}* ko apne channel mein *Admin* banaao\n"
        f"Permission chahiye: ✅ *Post Messages*\n\n"
        f"Admin banane ke baad ✅ *Done* dabaao 👇\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=done_cancel_kb(),
    )
    return ADD_CH_WAIT_DONE


async def add_ch_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    user_id  = update.effective_user.id
    username = context.user_data.get("ch_username", "")
    ch_link  = context.user_data.get("ch_link", "")
    try:
        chat       = await context.bot.get_chat(f"@{username}")
        ch_id      = chat.id
        ch_title   = chat.title or username
        bot_member = await context.bot.get_chat_member(f"@{username}", context.bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                f"❌ *Bot abhi admin nahi hai!*\n\n"
                f"*{ch_title}* mein mujhe admin banaao Post Messages permission ke saath.\n\n"
                "Phir ✅ Done dabaao 👇",
                parse_mode="Markdown",
                reply_markup=done_cancel_kb(),
            )
            return ADD_CH_WAIT_DONE
        save_channel(user_id, ch_link, ch_id, ch_title, username)
        await update.message.reply_text(
            f"✅ *Channel Add Ho Gaya!*\n\n📢 *{ch_title}*\n🔗 {ch_link}",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Add channel error: {e}")
        await update.message.reply_text(
            "❌ *Error!* Verify nahi ho paya.\n\n"
            "• Link check karo\n• Bot admin hona chahiye\n\n"
            "Phir ✅ Done dabaao 👇",
            parse_mode="Markdown",
            reply_markup=done_cancel_kb(),
        )
        return ADD_CH_WAIT_DONE


# ═══════════════════════════════════════════════════════
#           POST IN CHANNEL CONVERSATION
# ═══════════════════════════════════════════════════════

async def post_in_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return ConversationHandler.END
    user_id  = update.effective_user.id
    channels = get_user_channels(user_id)
    if not channels:
        await update.message.reply_text(
            "❌ *Koi channel add nahi hai!*\n\nPehle *📢 Add Channel* use karo.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "📤 *Post in Channel*\n\nKya karna hai? 👇",
        parse_mode="Markdown",
        reply_markup=pic_option_kb(),
    )
    return PIC_WAIT_OPTION


async def pic_option_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text
    user_id = update.effective_user.id
    if text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    if text == "📝 Make Post":
        context.user_data["pic_mode"] = "make_post"
    elif text == "🔖 Post with Post ID":
        context.user_data["pic_mode"] = "with_id"
    else:
        return PIC_WAIT_OPTION

    channels = get_user_channels(user_id)
    context.user_data["ch_map"]       = {ch["ch_title"]: ch["ch_id"] for ch in channels}
    context.user_data["ch_protected"] = {ch["ch_id"]: ch["ch_username"] for ch in channels}

    ch_buttons = [[KeyboardButton(f"📢 {ch['ch_title']}")] for ch in channels]
    ch_buttons.append([KeyboardButton("❌ Cancel")])
    await update.message.reply_text(
        "📢 *Channel select karo* 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ch_buttons, resize_keyboard=True),
    )
    return PIC_WAIT_CH_SELECT


async def pic_ch_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text
    user_id = update.effective_user.id
    if text == "❌ Cancel":
        return await _cancel_to_menu(update, context)

    ch_map = context.user_data.get("ch_map", {})
    title  = text.replace("📢 ", "")
    if title not in ch_map:
        ch_buttons = [[KeyboardButton(f"📢 {t}")] for t in ch_map]
        ch_buttons.append([KeyboardButton("❌ Cancel")])
        await update.message.reply_text(
            "❌ Buttons mein se select karo 👇",
            reply_markup=ReplyKeyboardMarkup(ch_buttons, resize_keyboard=True),
        )
        return PIC_WAIT_CH_SELECT

    ch_id = ch_map[title]
    ch_protected = context.user_data.get("ch_protected", {})
    if ch_protected.get(ch_id, "") in PROTECTED_CHANNELS and user_id != ADMIN_ID:
        await update.message.reply_text(
            "❌ *Yeh channel protected hai!*",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data["selected_ch_id"] = ch_id
    mode = context.user_data.get("pic_mode")

    if mode == "make_post":
        await update.message.reply_text(
            "📝 *Make Post — Step 1/3*\n\n"
            "Apna message bhejo *normal emoji ke saath* 😊🔥\n"
            "(Premium emoji automatic ban jaayega!)\n\n"
            "Photo ke saath caption bhi bhej sakte ho 📸\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return PIC_WAIT_MSG
    else:
        await update.message.reply_text(
            "🔖 *Post with Post ID*\n\nApna Post ID bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return PIC_WAIT_POST_ID


async def pic_recv_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    if update.message.content_type not in ("text", "photo"):
        await update.message.reply_text(
            "❌ Sirf text ya photo bhejo.\n\n❌ /cancel",
            reply_markup=cancel_kb(),
        )
        return PIC_WAIT_MSG
    proc_text, proc_entities, photo_id = extract_content(update.message)
    context.user_data["pic_text"]     = proc_text
    context.user_data["pic_entities"] = proc_entities
    context.user_data["pic_photo"]    = photo_id
    await update.message.reply_text(
        "✅ Message mila!\n\n📝 *Step 2/3* — Button ka *naam* bhejo 👇\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return PIC_WAIT_BTN_NAME


async def pic_recv_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    context.user_data["pic_btn_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Button naam: *{context.user_data['pic_btn_name']}*\n\n"
        "📝 *Step 3/3* — Button ka *link* bhejo (https:// se shuru)\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return PIC_WAIT_BTN_LINK


async def pic_recv_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    link = update.message.text.strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "❌ *Invalid link!*\n\nDobara bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return PIC_WAIT_BTN_LINK

    proc_text = context.user_data["pic_text"]
    entities  = context.user_data["pic_entities"]
    photo_id  = context.user_data.get("pic_photo")
    btn_name  = context.user_data["pic_btn_name"]
    ch_id     = context.user_data["selected_ch_id"]
    user_id   = update.effective_user.id
    post_id   = generate_post_id()

    try:
        await send_post(context.bot, ch_id, proc_text, entities, photo_id, btn_name, link)
        save_post(post_id, user_id, proc_text, btn_name, link, photo_id)
        await update.message.reply_text(
            f"✅ *Post ho gaya!*\n\n📌 Post ID: `{post_id}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    except Exception as e:
        logger.error(f"pic post error: {e}")
        await update.message.reply_text(
            f"❌ *Failed!*\n\nError: `{e}`\n\nBot admin hai ya nahi check karo.",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def pic_recv_post_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _cancel_to_menu(update, context)
    post_id = update.message.text.strip().upper()
    ch_id   = context.user_data.get("selected_ch_id")
    user_id = update.effective_user.id
    post    = get_post(post_id)

    if not post:
        await update.message.reply_text(
            "❌ *Post ID nahi mila!*\n\nCheck karo aur dobara bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return PIC_WAIT_POST_ID

    try:
        # Stored text already premium-processed, send with entities=None (stored as plain)
        post_kb = None
        if post["btn_name"] and post["btn_link"]:
            post_kb = InlineKeyboardMarkup([[InlineKeyboardButton(post["btn_name"], url=post["btn_link"])]])

        if post["photo_id"]:
            await context.bot.send_photo(ch_id, post["photo_id"],
                caption=post["msg_text"] or None,
                reply_markup=post_kb)
        else:
            await context.bot.send_message(ch_id, post["msg_text"],
                reply_markup=post_kb)

        await update.message.reply_text(
            f"✅ *Post ho gaya!*\n\n📌 Post ID: `{post_id}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    except Exception as e:
        logger.error(f"pic post id error: {e}")
        await update.message.reply_text(
            f"❌ *Failed!*\n\nError: `{e}`",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(user_id),
        )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#              ADMIN BROADCAST CONVERSATION
# ═══════════════════════════════════════════════════════

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "📣 *Broadcast*\n\nKahan bhejni hai? 👇",
        parse_mode="Markdown",
        reply_markup=bc_target_kb(),
    )
    return BC_WAIT_TARGET


async def bc_target_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Cancel":
        return await _admin_cancel(update, context)
    mapping = {"📢 Only Channels": "channels", "👥 Only Users": "users", "📣 Both": "both"}
    if text not in mapping:
        return BC_WAIT_TARGET
    context.user_data["bc_target"] = mapping[text]
    await update.message.reply_text(
        "✅ Target set!\n\nButton ke saath bhejni hai ya without button? 👇",
        parse_mode="Markdown",
        reply_markup=bc_btn_option_kb(),
    )
    return BC_WAIT_BTN_OPTION


async def bc_btn_option_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Cancel":
        return await _admin_cancel(update, context)
    if text == "🔘 With Button":
        context.user_data["bc_with_btn"] = True
    elif text == "📄 Without Button":
        context.user_data["bc_with_btn"] = False
    else:
        return BC_WAIT_BTN_OPTION
    await update.message.reply_text(
        "✅ Option set!\n\nAb message/photo/video bhejo 👇",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return BC_WAIT_MSG


async def bc_recv_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    context.user_data["bc_message"] = update.message
    if context.user_data.get("bc_with_btn"):
        await update.message.reply_text(
            "✅ Message mila!\n\nButton ka *naam* bhejo 👇",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return BC_WAIT_BTN_NAME
    await update.message.reply_text(
        "✅ Message mila!\n\nConfirm broadcast? 👇",
        parse_mode="Markdown",
        reply_markup=confirm_kb(),
    )
    return BC_WAIT_CONFIRM


async def bc_recv_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    context.user_data["bc_btn_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Button naam: *{context.user_data['bc_btn_name']}*\n\n"
        "Button ka *link* bhejo (https:// se shuru) 👇",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return BC_WAIT_BTN_LINK


async def bc_recv_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    link = update.message.text.strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "❌ Invalid link!\n\nDobara bhejo 👇",
            reply_markup=cancel_kb(),
        )
        return BC_WAIT_BTN_LINK
    context.user_data["bc_btn_link"] = link
    await update.message.reply_text(
        "✅ Button set!\n\nConfirm broadcast? 👇",
        parse_mode="Markdown",
        reply_markup=confirm_kb(),
    )
    return BC_WAIT_CONFIRM


async def bc_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Cancel":
        return await _admin_cancel(update, context)
    if text != "✅ Confirm":
        return BC_WAIT_CONFIRM

    target   = context.user_data.get("bc_target", "users")
    msg      = context.user_data.get("bc_message")
    with_btn = context.user_data.get("bc_with_btn", False)
    btn_name = context.user_data.get("bc_btn_name", "")
    btn_link = context.user_data.get("bc_btn_link", "")

    markup = None
    if with_btn and btn_name and btn_link:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_name, url=btn_link)]])

    ids = []
    if target in ("users", "both"):
        ids += get_all_user_ids()
    if target in ("channels", "both"):
        ids += get_all_channel_ids_db()
    ids = list(set(ids))

    sent = failed = 0
    for tid in ids:
        try:
            await copy_message_raw(context.bot, msg, tid, markup)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast fail {tid}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ *Broadcast Done!*\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#              ADMIN POST CONVERSATION
# ═══════════════════════════════════════════════════════

async def admin_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    wait = await update.message.reply_text("🔄 *Scanning channels...*", parse_mode="Markdown")
    channels = await live_scan_channels(context.bot)
    await wait.delete()

    if not channels:
        await update.message.reply_text(
            "❌ *Koi channel nahi mila!*\n\nPehle Add Channel ya Scan karo.",
            parse_mode="Markdown",
            reply_markup=admin_panel_kb(),
        )
        return ConversationHandler.END

    context.user_data["adm_ch_map"] = {ch["ch_title"]: ch["ch_id"] for ch in channels}

    ch_buttons = [[KeyboardButton(f"📢 {ch['ch_title']}")] for ch in channels]
    ch_buttons.append([KeyboardButton("📣 All Channels")])
    ch_buttons.append([KeyboardButton("❌ Cancel")])
    await update.message.reply_text(
        "📤 *Admin Post*\n\nKis channel mein post karna hai? 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(ch_buttons, resize_keyboard=True),
    )
    return ADM_POST_CH_SELECT


async def admin_post_ch_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text   = update.message.text
    ch_map = context.user_data.get("adm_ch_map", {})
    if text == "❌ Cancel":
        return await _admin_cancel(update, context)
    if text == "📣 All Channels":
        context.user_data["adm_ch_ids"] = list(ch_map.values())
        context.user_data["adm_all"]    = True
    else:
        title = text.replace("📢 ", "")
        if title not in ch_map:
            ch_buttons = [[KeyboardButton(f"📢 {t}")] for t in ch_map]
            ch_buttons.append([KeyboardButton("📣 All Channels")])
            ch_buttons.append([KeyboardButton("❌ Cancel")])
            await update.message.reply_text(
                "❌ Buttons mein se select karo 👇",
                reply_markup=ReplyKeyboardMarkup(ch_buttons, resize_keyboard=True),
            )
            return ADM_POST_CH_SELECT
        context.user_data["adm_ch_ids"] = [ch_map[title]]
        context.user_data["adm_all"]    = False

    await update.message.reply_text(
        "📝 *Admin Post — Step 1/3*\n\n"
        "Apna message bhejo *normal emoji ke saath* 😊🔥\n"
        "(Premium emoji automatic ban jaayega!)\n\n"
        "Photo ke saath caption bhi bhej sakte ho 📸\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return ADM_POST_WAIT_MSG


async def admin_post_recv_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    if update.message.content_type not in ("text", "photo"):
        await update.message.reply_text("❌ Sirf text ya photo bhejo.\n\n❌ /cancel", reply_markup=cancel_kb())
        return ADM_POST_WAIT_MSG
    proc_text, proc_entities, photo_id = extract_content(update.message)
    context.user_data["adm_text"]     = proc_text
    context.user_data["adm_entities"] = proc_entities
    context.user_data["adm_photo"]    = photo_id
    await update.message.reply_text(
        "✅ Message mila!\n\n📝 *Step 2/3* — Button ka *naam* bhejo 👇\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return ADM_POST_WAIT_BTN_NAME


async def admin_post_recv_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    context.user_data["adm_btn_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Button naam: *{context.user_data['adm_btn_name']}*\n\n"
        "📝 *Step 3/3* — Button ka *link* bhejo (https:// se shuru)\n\n❌ /cancel",
        parse_mode="Markdown",
        reply_markup=cancel_kb(),
    )
    return ADM_POST_WAIT_BTN_LINK


async def admin_post_recv_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await _admin_cancel(update, context)
    link = update.message.text.strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "❌ *Invalid link!*\n\nDobara bhejo 👇\n\n❌ /cancel",
            parse_mode="Markdown",
            reply_markup=cancel_kb(),
        )
        return ADM_POST_WAIT_BTN_LINK

    context.user_data["adm_btn_link"] = link
    proc_text  = context.user_data["adm_text"]
    entities   = context.user_data["adm_entities"]
    photo_id   = context.user_data.get("adm_photo")
    btn_name   = context.user_data["adm_btn_name"]

    await update.message.reply_text("📋 *Preview:*", parse_mode="Markdown")
    await send_post(context.bot, update.effective_chat.id,
                    proc_text, entities, photo_id, btn_name, link)

    post_to = "All Channels" if context.user_data.get("adm_all") else f"{len(context.user_data['adm_ch_ids'])} channel(s)"
    await update.message.reply_text(
        f"📤 Post to: *{post_to}*\n\nConfirm? 👇",
        parse_mode="Markdown",
        reply_markup=confirm_kb(),
    )
    return ADM_POST_WAIT_CONFIRM


async def admin_post_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Cancel":
        return await _admin_cancel(update, context)
    if text != "✅ Confirm":
        return ADM_POST_WAIT_CONFIRM

    proc_text = context.user_data["adm_text"]
    entities  = context.user_data["adm_entities"]
    photo_id  = context.user_data.get("adm_photo")
    btn_name  = context.user_data["adm_btn_name"]
    btn_link  = context.user_data["adm_btn_link"]
    ch_ids    = context.user_data["adm_ch_ids"]
    user_id   = update.effective_user.id

    sent = failed = 0
    for ch_id in ch_ids:
        try:
            await send_post(context.bot, ch_id, proc_text, entities, photo_id, btn_name, btn_link)
            sent += 1
        except Exception as e:
            logger.error(f"admin post error {ch_id}: {e}")
            failed += 1

    post_id = generate_post_id()
    save_post(post_id, user_id, proc_text, btn_name, btn_link, photo_id)

    await update.message.reply_text(
        f"✅ *Post ho gaya!*\n\n✅ Sent: {sent}\n❌ Failed: {failed}\n\n📌 Post ID: `{post_id}`",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════
#                    CANCEL HELPERS
# ═══════════════════════════════════════════════════════

async def _cancel_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ *Cancel ho gaya.*",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(update.effective_user.id),
    )
    return ConversationHandler.END


async def _admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ *Cancel ho gaya.*",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb(),
    )
    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    return await _cancel_to_menu(update, context)


# ═══════════════════════════════════════════════════════
#                        MAIN
# ═══════════════════════════════════════════════════════

async def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN not set!")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    cx  = CommandHandler("cancel", cancel_cmd)

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(PRIVATE & filters.Regex("^📝 Create Post$"), create_post_start)],
        states={
            CREATE_WAIT_MSG:      [MessageHandler(PRIVATE & (filters.TEXT | filters.PHOTO), create_recv_msg)],
            CREATE_WAIT_BTN_NAME: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, create_recv_btn_name)],
            CREATE_WAIT_BTN_LINK: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, create_recv_btn_link)],
        },
        fallbacks=[cx], per_message=False,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(PRIVATE & filters.Regex("^📢 Add Channel$"), add_channel_start)],
        states={
            ADD_CH_WAIT_LINK: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, add_ch_recv_link)],
            ADD_CH_WAIT_DONE: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, add_ch_done)],
        },
        fallbacks=[cx], per_message=False,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(PRIVATE & filters.Regex("^📤 Post in Channel$"), post_in_channel_start)],
        states={
            PIC_WAIT_OPTION:    [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, pic_option_handler)],
            PIC_WAIT_CH_SELECT: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, pic_ch_select)],
            PIC_WAIT_MSG:       [MessageHandler(PRIVATE & (filters.TEXT | filters.PHOTO), pic_recv_msg)],
            PIC_WAIT_BTN_NAME:  [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, pic_recv_btn_name)],
            PIC_WAIT_BTN_LINK:  [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, pic_recv_btn_link)],
            PIC_WAIT_POST_ID:   [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, pic_recv_post_id)],
        },
        fallbacks=[cx], per_message=False,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(PRIVATE & filters.Regex("^📣 Broadcast$"), broadcast_start)],
        states={
            BC_WAIT_TARGET:     [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, bc_target_handler)],
            BC_WAIT_BTN_OPTION: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, bc_btn_option_handler)],
            BC_WAIT_MSG: [MessageHandler(
                PRIVATE & (filters.TEXT | filters.PHOTO | filters.VIDEO |
                           filters.Document.ALL | filters.AUDIO | filters.Sticker.ALL |
                           filters.ANIMATION | filters.VOICE | filters.VIDEO_NOTE),
                bc_recv_msg,
            )],
            BC_WAIT_BTN_NAME:   [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, bc_recv_btn_name)],
            BC_WAIT_BTN_LINK:   [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, bc_recv_btn_link)],
            BC_WAIT_CONFIRM:    [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, bc_confirm_handler)],
        },
        fallbacks=[cx], per_message=False,
    ))

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(PRIVATE & filters.Regex("^📤 Admin Post$"), admin_post_start)],
        states={
            ADM_POST_CH_SELECT:     [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, admin_post_ch_select)],
            ADM_POST_WAIT_MSG:      [MessageHandler(PRIVATE & (filters.TEXT | filters.PHOTO), admin_post_recv_msg)],
            ADM_POST_WAIT_BTN_NAME: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, admin_post_recv_btn_name)],
            ADM_POST_WAIT_BTN_LINK: [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, admin_post_recv_btn_link)],
            ADM_POST_WAIT_CONFIRM:  [MessageHandler(PRIVATE & filters.TEXT & ~filters.COMMAND, admin_post_confirm)],
        },
        fallbacks=[cx], per_message=False,
    ))

    app.add_handler(CommandHandler("start", start, filters=PRIVATE))
    app.add_handler(CommandHandler("help",  help_cmd, filters=PRIVATE))
    app.add_handler(CallbackQueryHandler(check_joined_cb, pattern="^check_joined$"))
    app.add_handler(MessageHandler(
        PRIVATE & filters.Regex(
            "^(👨‍💻 Developer|🔄 Update Channel|🛠 Admin Panel|🏠 Main Menu|📊 Stats|📡 Scan Channels)$"
        ),
        static_menu_handler,
    ))

    logger.info("✅ All handlers loaded!")
    async with app:
        await app.initialize()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        await app.start()
        logger.info("✅ Bot running!")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
