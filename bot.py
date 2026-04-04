import os, sqlite3, logging, re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)

# ═══════════════════════════════════════════════════════
#                        CONFIG
# ═══════════════════════════════════════════════════════

BOT_TOKEN = "8672897851:AAEkQsCaURbJoognoCH2Df9IVzpaKI-yQNQ"
ADMIN_ID  = 8379167923

CHANNELS = [
    {"id": -1003588878017, "link": "https://t.me/srking0001",  "name": "SR King"},
    {"id": -1003862853446, "link": "https://t.me/srking00001", "name": "SR King Group"},
    {"id": -1003862853446, "link": "https://t.me/botdevking",  "name": "Bot Dev King"},
]

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.db")
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#                   CONVERSATION STATES
# ═══════════════════════════════════════════════════════

(
    ADD_FILE_WAIT_FILE,
    ADD_FILE_WAIT_PRICE,
    CREATE_PROMO_WAIT_CODE,
    CREATE_PROMO_WAIT_POINTS,
    CREATE_PROMO_WAIT_MAXUSERS,
    ADD_POINTS_WAIT_USERID,
    ADD_POINTS_WAIT_AMOUNT,
    ADD_POINTS_WAIT_CONFIRM,
    BROADCAST_WAIT_MESSAGE,
    BROADCAST_WAIT_CONFIRM,
    REDEEM_WAIT_CODE,
    POST_WAIT_TEXT,
    POST_WAIT_BTN_NAME,
    POST_WAIT_BTN_LINK,
    POST_WAIT_CHANNEL,
) = range(15)

# ═══════════════════════════════════════════════════════
#                      DATABASE
# ═══════════════════════════════════════════════════════

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, full_name TEXT,
        points INTEGER DEFAULT 0,
        referred_by INTEGER DEFAULT NULL,
        total_refers INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT UNIQUE,
        file_name TEXT, file_type TEXT,
        price INTEGER DEFAULT 1,
        sold_count INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, file_id TEXT,
        bought_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY,
        points INTEGER, max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_uses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, code TEXT
    )""")
    conn.commit()
    conn.close()
    logger.info("✅ DB initialized")

# ── Users ──────────────────────────────────────────────

def get_user(uid):
    c = get_conn()
    u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    c.close(); return u

def add_user(uid, username, full_name, referred_by=None):
    conn = get_conn()
    exists = conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
    is_new = False
    if not exists:
        conn.execute(
            "INSERT INTO users (user_id,username,full_name,referred_by) VALUES (?,?,?,?)",
            (uid, username or "", full_name or "", referred_by)
        )
        conn.commit(); is_new = True
    conn.close(); return is_new

def update_points(uid, amt):
    conn = get_conn()
    conn.execute("UPDATE users SET points=points+? WHERE user_id=?", (amt, uid))
    conn.commit(); conn.close()

def increment_refers(uid):
    conn = get_conn()
    conn.execute("UPDATE users SET total_refers=total_refers+1 WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def get_all_user_ids():
    conn = get_conn()
    rows = conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
    conn.close(); return [r["user_id"] for r in rows]

def get_stats():
    conn = get_conn()
    tu = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    tf = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    ts = conn.execute("SELECT COUNT(*) as c FROM purchases").fetchone()["c"]
    tp = conn.execute("SELECT COUNT(*) as c FROM promo_uses").fetchone()["c"]
    tpt= conn.execute("SELECT COALESCE(SUM(points),0) as s FROM users").fetchone()["s"]
    conn.close(); return tu, tf, ts, tp, tpt

# ── Files ──────────────────────────────────────────────

def add_file_db(file_id, file_name, file_type, price):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO files (file_id,file_name,file_type,price) VALUES (?,?,?,?)",
        (file_id, file_name, file_type, price)
    )
    conn.commit(); conn.close()

def remove_file_db(fid):          # fid = integer id column
    conn = get_conn()
    conn.execute("DELETE FROM files WHERE id=?", (fid,))
    conn.commit(); conn.close()

def get_all_files():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM files ORDER BY added_at DESC").fetchall()
    conn.close(); return rows

def get_file_by_id(fid):          # fid = integer id
    conn = get_conn()
    f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    conn.close(); return f

def get_file_by_tg(file_id):      # file_id = telegram file_id string
    conn = get_conn()
    f = conn.execute("SELECT * FROM files WHERE file_id=?", (file_id,)).fetchone()
    conn.close(); return f

# ── Purchases ──────────────────────────────────────────

def has_purchased(uid, file_id):
    conn = get_conn()
    p = conn.execute("SELECT id FROM purchases WHERE user_id=? AND file_id=?", (uid, file_id)).fetchone()
    conn.close(); return p is not None

def add_purchase(uid, file_id, db_id):
    conn = get_conn()
    conn.execute("INSERT INTO purchases (user_id,file_id) VALUES (?,?)", (uid, file_id))
    conn.execute("UPDATE files SET sold_count=sold_count+1 WHERE id=?", (db_id,))
    conn.commit(); conn.close()

def get_purchase_count(uid):
    conn = get_conn()
    c = conn.execute("SELECT COUNT(*) as c FROM purchases WHERE user_id=?", (uid,)).fetchone()["c"]
    conn.close(); return c

# ── Promo ──────────────────────────────────────────────

def add_promo_db(code, points, max_uses):
    conn = get_conn()
    conn.execute("INSERT INTO promo_codes (code,points,max_uses) VALUES (?,?,?)", (code, points, max_uses))
    conn.commit(); conn.close()

def get_promo(code):
    conn = get_conn()
    p = conn.execute("SELECT * FROM promo_codes WHERE code=?", (code,)).fetchone()
    conn.close(); return p

def has_used_promo(uid, code):
    conn = get_conn()
    r = conn.execute("SELECT id FROM promo_uses WHERE user_id=? AND code=?", (uid, code)).fetchone()
    conn.close(); return r is not None

def use_promo(uid, code):
    conn = get_conn()
    conn.execute("INSERT INTO promo_uses (user_id,code) VALUES (?,?)", (uid, code))
    conn.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
    conn.commit(); conn.close()

# ═══════════════════════════════════════════════════════
#                      HELPERS
# ═══════════════════════════════════════════════════════

async def check_channels(bot, uid):
    not_joined = []
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch["id"], uid)
            if m.status in ("left", "kicked", "banned"):
                not_joined.append(ch)
        except:
            not_joined.append(ch)
    return not_joined

def is_valid_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url.strip()))

def main_menu_kb(uid):
    kb = [
        [InlineKeyboardButton("📁 Files",       callback_data="menu_files"),
         InlineKeyboardButton("👤 My Profile",  callback_data="menu_profile")],
        [InlineKeyboardButton("🎁 Promo Code",  callback_data="menu_promo"),
         InlineKeyboardButton("🔗 Refer & Earn",callback_data="menu_refer")],
    ]
    if uid == ADMIN_ID:
        kb.append([InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

def join_kb(not_joined):
    kb = [[InlineKeyboardButton(f"✅ Join {ch['name']}", url=ch["link"])] for ch in not_joined]
    kb.append([InlineKeyboardButton("🔄 Check Again", callback_data="check_joined")])
    return InlineKeyboardMarkup(kb)

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add File",      callback_data="adm_add_file"),
         InlineKeyboardButton("🗑 Remove File",   callback_data="adm_rem_file")],
        [InlineKeyboardButton("🎟 Create Promo",  callback_data="adm_crt_promo"),
         InlineKeyboardButton("💰 Add Points",    callback_data="adm_add_pts")],
        [InlineKeyboardButton("📢 Broadcast",     callback_data="adm_broadcast"),
         InlineKeyboardButton("📊 Statistics",    callback_data="adm_stats")],
        [InlineKeyboardButton("📁 View Files",    callback_data="adm_view_files"),
         InlineKeyboardButton("📣 Post Now",      callback_data="adm_post_now")],
        [InlineKeyboardButton("🏠 Home",          callback_data="back_home")],
    ])

def home_text(user):
    db_user = get_user(user.id)
    pts = db_user["points"] if db_user else 0
    return (
        f"👋 *Namaste, {user.full_name}!*\n\n"
        f"💰 Tumhare Points: *{pts}* pts\n\n"
        f"📁 Rare files dekho, refer karo aur points se kharido!\n"
        f"Neeche se choose karo 👇"
    )

# ═══════════════════════════════════════════════════════
#                    /START
# ═══════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None

    if args and args[0].startswith("ref_"):
        try:
            ref = int(args[0][4:])
            if ref != user.id:
                referred_by = ref
        except:
            pass

    is_new = add_user(user.id, user.username, user.full_name, referred_by)

    if is_new and referred_by:
        update_points(referred_by, 1)
        increment_refers(referred_by)
        try:
            await context.bot.send_message(
                referred_by,
                f"🎉 *Yay!* Tumhare refer link se *{user.full_name}* join kiya!\n"
                f"💰 Tumhe *+1 Point* mila! 🔥",
                parse_mode="Markdown"
            )
        except: pass

    not_joined = await check_channels(context.bot, user.id)
    if not_joined:
        await update.message.reply_text(
            "👋 *Welcome!*\n\n"
            "⚠️ Pehle neeche diye *channels join karo*, phir bot use kar sakte ho!\n\n"
            "✅ Join karne ke baad *Check Again* dabao. 👇",
            parse_mode="Markdown",
            reply_markup=join_kb(not_joined)
        )
        return

    await update.message.reply_text(
        home_text(user), parse_mode="Markdown",
        reply_markup=main_menu_kb(user.id)
    )

# ═══════════════════════════════════════════════════════
#                 CHECK JOINED
# ═══════════════════════════════════════════════════════

async def check_joined_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user = q.from_user
    not_joined = await check_channels(context.bot, user.id)
    if not_joined:
        await q.edit_message_text(
            "❌ Abhi bhi kuch channels join nahi kiye!\nSab join karo phir try karo. 👇",
            parse_mode="Markdown", reply_markup=join_kb(not_joined)
        )
        return
    await q.edit_message_text(
        home_text(user), parse_mode="Markdown",
        reply_markup=main_menu_kb(user.id)
    )

# ═══════════════════════════════════════════════════════
#                 BACK HOME
# ═══════════════════════════════════════════════════════

async def back_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        home_text(q.from_user), parse_mode="Markdown",
        reply_markup=main_menu_kb(q.from_user.id)
    )

# ═══════════════════════════════════════════════════════
#                    FILES
# ═══════════════════════════════════════════════════════

async def menu_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    not_joined = await check_channels(context.bot, q.from_user.id)
    if not_joined:
        await q.edit_message_text("⚠️ Pehle channels join karo!", reply_markup=join_kb(not_joined))
        return
    files = get_all_files()
    if not files:
        await q.edit_message_text(
            "📭 Abhi koi file available nahi hai.\nThodi der baad check karo!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back", callback_data="back_home")]])
        )
        return
    kb = []
    for f in files:
        kb.append([InlineKeyboardButton(
            f"📄 {f['file_name']}  |  💰 {f['price']} pts",
            callback_data=f"bf_{f['id']}"          # ✅ short int id — no 64-char limit issue
        )])
    kb.append([InlineKeyboardButton("🏠 Back", callback_data="back_home")])
    await q.edit_message_text(
        "📁 *Available Files*\n\nFile select karo aur points se kharido! 👇",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def buy_file_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    try:
        db_id = int(q.data.split("_", 1)[1])
    except:
        await q.answer("❌ Invalid!", show_alert=True); return

    not_joined = await check_channels(context.bot, uid)
    if not_joined:
        await q.edit_message_text("⚠️ Pehle channels join karo!", reply_markup=join_kb(not_joined))
        return

    f = get_file_by_id(db_id)
    if not f:
        await q.answer("❌ File nahi mili!", show_alert=True); return

    # Already purchased — resend
    if has_purchased(uid, f["file_id"]):
        await q.answer("✅ Yeh file tumhari hai! Neeche bhej raha hoon.", show_alert=True)
        try:
            await context.bot.send_document(
                uid, document=f["file_id"],
                caption=f"📄 *{f['file_name']}*\n\n✅ Tumne yeh pehle kharidi thi!",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Resend err: {e}")
        return

    db_user = get_user(uid)
    if db_user["points"] < f["price"]:
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        await q.edit_message_text(
            f"❌ *Insufficient Points!*\n\n"
            f"💰 Tumhare paas: *{db_user['points']}* pts\n"
            f"💸 Chahiye: *{f['price']}* pts\n\n"
            f"🔗 *Refer karo aur points kamao!*\n"
            f"Har refer = 1 point 💰\n\n"
            f"`{ref_link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back", callback_data="back_home")]])
        )
        return

    update_points(uid, -f["price"])
    add_purchase(uid, f["file_id"], db_id)

    await q.edit_message_text(
        f"✅ *Purchase Successful!*\n\n"
        f"📄 {f['file_name']}\n"
        f"💰 {f['price']} points kate gaye\n\n"
        f"File neeche bhej rahi hai... 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]])
    )
    try:
        await context.bot.send_document(
            uid, document=f["file_id"],
            caption=f"📄 *{f['file_name']}*\n\n🎉 Enjoy!",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Send err: {e}")
        await context.bot.send_message(uid, "⚠️ File bhejne mein problem. Admin se contact karo.")

# ═══════════════════════════════════════════════════════
#                   PROFILE
# ═══════════════════════════════════════════════════════

async def menu_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user = q.from_user
    db_user = get_user(user.id)
    pc = get_purchase_count(user.id)
    await q.edit_message_text(
        f"👤 *My Profile*\n\n"
        f"📛 Name: *{db_user['full_name']}*\n"
        f"🆔 User ID: `{db_user['user_id']}`\n"
        f"👤 Username: @{db_user['username'] or 'N/A'}\n\n"
        f"💰 Points: *{db_user['points']}* pts\n"
        f"🔗 Total Refers: *{db_user['total_refers']}*\n"
        f"📁 Files Bought: *{pc}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back", callback_data="back_home")]])
    )

# ═══════════════════════════════════════════════════════
#                   REFER
# ═══════════════════════════════════════════════════════

async def menu_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    user = q.from_user
    db_user = get_user(user.id)
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
    await q.edit_message_text(
        f"🔗 *Refer & Earn*\n\n"
        f"Apna refer link share karo!\n"
        f"Har ek join = *1 Point* 💰\n\n"
        f"📊 Total Refers: *{db_user['total_refers']}*\n"
        f"💰 Points: *{db_user['points']}* pts\n\n"
        f"🔗 *Tumhara Refer Link:*\n`{ref_link}`\n\n"
        f"👆 Copy karo aur dosto ko bhejo!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back", callback_data="back_home")]])
    )

# ═══════════════════════════════════════════════════════
#              PROMO REDEEM CONVERSATION
# ═══════════════════════════════════════════════════════

async def menu_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "🎁 *Promo Code Redeem*\n\nApna promo code bhejo 👇\n\n❌ Cancel: /cancel",
        parse_mode="Markdown"
    )
    return REDEEM_WAIT_CODE

async def redeem_code_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    code = update.message.text.strip().upper()
    promo = get_promo(code)
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="back_home")]])

    if not promo:
        await update.message.reply_text("❌ *Invalid Code!*\nYeh code exist nahi karta.", parse_mode="Markdown", reply_markup=back_kb)
        return ConversationHandler.END
    if promo["used_count"] >= promo["max_uses"]:
        await update.message.reply_text("❌ *Code Expired!*\nIs code ki limit khatam ho gayi.", parse_mode="Markdown", reply_markup=back_kb)
        return ConversationHandler.END
    if has_used_promo(uid, code):
        await update.message.reply_text("⚠️ *Already Used!*\nTumne yeh code pehle use kar liya.", parse_mode="Markdown", reply_markup=back_kb)
        return ConversationHandler.END

    use_promo(uid, code)
    update_points(uid, promo["points"])
    await update.message.reply_text(
        f"🎉 *Code Redeemed!*\n\n💰 *+{promo['points']} Points* add ho gaye!\n\n🛍️ Ab files kharido!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📁 Files Dekho", callback_data="menu_files"),
            InlineKeyboardButton("🏠 Home",        callback_data="back_home"),
        ]])
    )
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════
#                  ADMIN PANEL
# ═══════════════════════════════════════════════════════

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID:
        await q.answer("❌ Access Denied!", show_alert=True); return
    await q.edit_message_text("🛠️ *Admin Panel*\n\nKya karna hai? 👇", parse_mode="Markdown", reply_markup=admin_kb())

# ─── ADD FILE ──────────────────────────────────────────

async def adm_add_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    await q.edit_message_text("➕ *File Add Karo*\n\n📄 File bhejo (Document/PDF/ZIP)...\n\n❌ /cancel", parse_mode="Markdown")
    return ADD_FILE_WAIT_FILE

async def adm_add_file_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ Sirf document/file bhejo!"); return ADD_FILE_WAIT_FILE
    context.user_data.update({"nf_id": doc.file_id, "nf_name": doc.file_name or "File", "nf_type": doc.mime_type or "doc"})
    await update.message.reply_text(
        f"✅ File mili: *{doc.file_name}*\n\n💰 Price bhejo (kitne points?)\n\n❌ /cancel",
        parse_mode="Markdown"
    )
    return ADD_FILE_WAIT_PRICE

async def adm_add_file_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        price = int(update.message.text.strip())
        if price < 1: raise ValueError
    except:
        await update.message.reply_text("❌ Valid number bhejo (e.g. 5)"); return ADD_FILE_WAIT_PRICE
    add_file_db(context.user_data["nf_id"], context.user_data["nf_name"], context.user_data["nf_type"], price)
    await update.message.reply_text(
        f"✅ *File Added!*\n\n📄 {context.user_data['nf_name']}\n💰 {price} pts",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

# ─── REMOVE FILE ───────────────────────────────────────

async def adm_rem_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    files = get_all_files()
    if not files:
        await q.edit_message_text("📭 Koi file nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Back", callback_data="admin_panel")]]))
        return
    kb = [[InlineKeyboardButton(f"🗑 {f['file_name']} ({f['price']} pts)", callback_data=f"dorm_{f['id']}")] for f in files]
    kb.append([InlineKeyboardButton("🛠️ Back", callback_data="admin_panel")])
    await q.edit_message_text("🗑 *Kaunsi file remove karni hai?*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def adm_do_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    fid = int(q.data.split("_", 1)[1])
    f = get_file_by_id(fid)
    if f:
        remove_file_db(fid)
        await q.edit_message_text(f"✅ *File Removed!*\n\n📄 {f['file_name']} delete ho gayi.", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]]))
    else:
        await q.edit_message_text("❌ File nahi mili!")

# ─── CREATE PROMO ──────────────────────────────────────

async def adm_crt_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    await q.edit_message_text("🎟 *Promo Code Create Karo*\n\nCode likhke bhejo (e.g. KING2024)\n\n❌ /cancel", parse_mode="Markdown")
    return CREATE_PROMO_WAIT_CODE

async def adm_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    code = update.message.text.strip().upper()
    if get_promo(code):
        await update.message.reply_text(f"❌ Code *{code}* already exist karta hai! Alag daalo.", parse_mode="Markdown")
        return CREATE_PROMO_WAIT_CODE
    context.user_data["pc"] = code
    await update.message.reply_text(f"✅ Code: *{code}*\n\n💰 Kitne points milenge?", parse_mode="Markdown")
    return CREATE_PROMO_WAIT_POINTS

async def adm_promo_pts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        pts = int(update.message.text.strip())
        if pts < 1: raise ValueError
    except:
        await update.message.reply_text("❌ Valid number bhejo!"); return CREATE_PROMO_WAIT_POINTS
    context.user_data["pp"] = pts
    await update.message.reply_text(f"✅ Points: *{pts}*\n\n👥 Max kitne users use kar sakte?", parse_mode="Markdown")
    return CREATE_PROMO_WAIT_MAXUSERS

async def adm_promo_maxu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        max_u = int(update.message.text.strip())
        if max_u < 1: raise ValueError
    except:
        await update.message.reply_text("❌ Valid number bhejo!"); return CREATE_PROMO_WAIT_MAXUSERS

    code, pts = context.user_data["pc"], context.user_data["pp"]
    add_promo_db(code, pts, max_u)

    # ✅ Stylish promo card
    card = (
        f"🎟 *PROMO CODE* 🎟\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑  Code:  `{code}`\n"
        f"💰  Reward:  *{pts} Points*\n"
        f"👥  Max Uses:  *{max_u}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📲 Bot mein jaake redeem karo!\n"
        f"👉 Promo Code button dabao\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *SR King File Store*"
    )
    await update.message.reply_text(
        f"✅ *Promo Created!*\n\n{card}\n\n📢 _Yeh card channels mein forward kar sakte ho!_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

# ─── ADD POINTS ────────────────────────────────────────

async def adm_add_pts_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    await q.edit_message_text("💰 *User ko Points Add Karo*\n\nUser ka Telegram ID bhejo:\n\n❌ /cancel", parse_mode="Markdown")
    return ADD_POINTS_WAIT_USERID

async def adm_pts_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        uid = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ Valid User ID bhejo!"); return ADD_POINTS_WAIT_USERID
    u = get_user(uid)
    if not u:
        await update.message.reply_text("❌ Yeh user registered nahi hai!"); return ADD_POINTS_WAIT_USERID
    context.user_data.update({"pt_uid": uid, "pt_name": u["full_name"], "pt_cur": u["points"]})
    await update.message.reply_text(
        f"✅ User: *{u['full_name']}*\n💰 Current Points: *{u['points']}*\n\nKitne points add karne hain?",
        parse_mode="Markdown"
    )
    return ADD_POINTS_WAIT_AMOUNT

async def adm_pts_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    try:
        amt = int(update.message.text.strip())
        if amt < 1: raise ValueError
    except:
        await update.message.reply_text("❌ Valid number bhejo!"); return ADD_POINTS_WAIT_AMOUNT
    context.user_data["pt_amt"] = amt
    uid, name = context.user_data["pt_uid"], context.user_data["pt_name"]
    await update.message.reply_text(
        f"⚠️ *Confirm karo:*\n\n👤 User: *{name}* (`{uid}`)\n💰 Add: *+{amt} pts*\n\nSahi hai?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data="pts_ok"),
            InlineKeyboardButton("❌ Reject",  callback_data="pts_no"),
        ]])
    )
    return ADD_POINTS_WAIT_CONFIRM

async def adm_pts_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid, name, amt = context.user_data["pt_uid"], context.user_data["pt_name"], context.user_data["pt_amt"]
    update_points(uid, amt)
    await q.edit_message_text(
        f"✅ *Done!*\n\n👤 {name} ko *+{amt} pts* diye gaye!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
    )
    try:
        await context.bot.send_message(uid, f"🎉 Admin ne tumhe *+{amt} Points* diye!\n💰 Ab files kharido! 🔥", parse_mode="Markdown")
    except: pass
    return ConversationHandler.END

async def adm_pts_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("❌ Cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]]))
    return ConversationHandler.END

# ─── BROADCAST ─────────────────────────────────────────

async def adm_bc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    await q.edit_message_text(
        "📢 *Broadcast Message*\n\nJo message sabko bhejna hai woh bhejo.\n"
        "✅ Text, Video, Sticker, Emoji, Link — sab chalega!\n\n❌ /cancel",
        parse_mode="Markdown"
    )
    return BROADCAST_WAIT_MESSAGE

async def adm_bc_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    context.user_data["bc_msg"] = update.message
    await update.message.reply_text(
        "📢 *Confirm — yeh message sabko bhejna hai?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Send Karo", callback_data="bc_ok"),
            InlineKeyboardButton("❌ Cancel",    callback_data="bc_no"),
        ]])
    )
    return BROADCAST_WAIT_CONFIRM

async def adm_bc_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    msg = context.user_data.get("bc_msg")
    if not msg:
        await q.edit_message_text("❌ Message nahi mila!"); return ConversationHandler.END
    users = get_all_user_ids()
    sent = failed = 0
    await q.edit_message_text(f"📤 Sending to {len(users)} users... Please wait.")
    for uid in users:
        try:
            await msg.forward(uid); sent += 1
        except: failed += 1
    await context.bot.send_message(
        ADMIN_ID,
        f"✅ *Broadcast Done!*\n\n✅ Sent: *{sent}*\n❌ Failed: *{failed}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
    )
    return ConversationHandler.END

async def adm_bc_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("❌ Broadcast cancel.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]]))
    return ConversationHandler.END

# ─── STATS ─────────────────────────────────────────────

async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    tu, tf, ts, tp, tpt = get_stats()
    await q.edit_message_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total Users:        *{tu}*\n"
        f"📁 Total Files:        *{tf}*\n"
        f"🛍 Total Sales:        *{ts}*\n"
        f"🎟 Promo Redeems:     *{tp}*\n"
        f"💰 Total Points (all): *{tpt}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
    )

# ─── VIEW FILES ────────────────────────────────────────

async def adm_view_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    files = get_all_files()
    if not files:
        await q.edit_message_text("📭 Koi file nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Back", callback_data="admin_panel")]]))
        return
    text = "📁 *All Files:*\n\n"
    for i, f in enumerate(files, 1):
        text += f"{i}. *{f['file_name']}*\n   💰 {f['price']} pts  |  🛍 Sold: {f['sold_count']}\n\n"
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]]))

# ─── POST NOW ──────────────────────────────────────────

async def adm_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return
    await q.edit_message_text(
        "📣 *Post Now*\n\n"
        "Step 1️⃣: Jo post karna hai woh *message likh ke bhejo* 👇\n\n"
        "❌ /cancel",
        parse_mode="Markdown"
    )
    return POST_WAIT_TEXT

async def adm_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    context.user_data["post_text"] = update.message.text or update.message.caption or ""
    await update.message.reply_text(
        "✅ Message mila!\n\nStep 2️⃣: *Button ka naam* likhke bhejo (e.g. Visit Now)\n\n❌ /cancel",
        parse_mode="Markdown"
    )
    return POST_WAIT_BTN_NAME

async def adm_post_btn_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    context.user_data["post_btn_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Button naam: *{update.message.text.strip()}*\n\n"
        f"Step 3️⃣: *Button ka link* bhejo (https:// se shuru hona chahiye)\n\n❌ /cancel",
        parse_mode="Markdown"
    )
    return POST_WAIT_BTN_LINK

async def adm_post_btn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    link = update.message.text.strip()
    if not is_valid_url(link):
        await update.message.reply_text(
            "❌ *Invalid Link!*\n\nLink http:// ya https:// se shuru hona chahiye.\n\nDobara bhejo 👇",
            parse_mode="Markdown"
        )
        return POST_WAIT_BTN_LINK

    context.user_data["post_btn_link"] = link

    # Show channel selection — only channels where bot is admin
    kb = []
    for i, ch in enumerate(CHANNELS):
        kb.append([InlineKeyboardButton(f"📢 {ch['name']}", callback_data=f"postch_{i}")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")])

    await update.message.reply_text(
        f"✅ Link set!\n\n"
        f"Step 4️⃣: *Kis channel mein post karna hai?* 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return POST_WAIT_CHANNEL

async def adm_post_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.from_user.id != ADMIN_ID: return ConversationHandler.END

    idx = int(q.data.split("_", 1)[1])
    ch  = CHANNELS[idx]
    post_text  = context.user_data.get("post_text", "")
    btn_name   = context.user_data.get("post_btn_name", "Click Here")
    btn_link   = context.user_data.get("post_btn_link", "")

    post_kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_name, url=btn_link)]])

    try:
        await context.bot.send_message(
            ch["id"],
            post_text,
            parse_mode="Markdown",
            reply_markup=post_kb
        )
        await q.edit_message_text(
            f"✅ *Post Sent!*\n\n📢 Channel: *{ch['name']}*\n📝 Message sent with button!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
        )
    except Exception as e:
        logger.error(f"Post err: {e}")
        await q.edit_message_text(
            f"❌ *Post Failed!*\n\nError: `{e}`\n\nBot ko channel mein admin banao!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛠️ Admin Panel", callback_data="admin_panel")]])
        )
    return ConversationHandler.END

# ─── CANCEL ────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ *Cancelled!*", parse_mode="Markdown",
        reply_markup=main_menu_kb(update.effective_user.id)
    )
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════
#                       MAIN
# ═══════════════════════════════════════════════════════

def main():
    init_db()
    print("✅ DB ready!")
    print("🤖 Bot start ho raha hai...")

    app = Application.builder().token(BOT_TOKEN).build()
    cx  = CommandHandler("cancel", cancel)

    # Promo redeem
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_promo, pattern="^menu_promo$")],
        states={REDEEM_WAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, redeem_code_recv)]},
        fallbacks=[cx], per_message=False,
    ))

    # Add file
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_add_file_start, pattern="^adm_add_file$")],
        states={
            ADD_FILE_WAIT_FILE:  [MessageHandler(filters.Document.ALL, adm_add_file_recv)],
            ADD_FILE_WAIT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_file_price)],
        },
        fallbacks=[cx], per_message=False,
    ))

    # Create promo
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_crt_promo_start, pattern="^adm_crt_promo$")],
        states={
            CREATE_PROMO_WAIT_CODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_promo_code)],
            CREATE_PROMO_WAIT_POINTS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_promo_pts)],
            CREATE_PROMO_WAIT_MAXUSERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_promo_maxu)],
        },
        fallbacks=[cx], per_message=False,
    ))

    # Add points
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_add_pts_start, pattern="^adm_add_pts$")],
        states={
            ADD_POINTS_WAIT_USERID:  [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_pts_uid)],
            ADD_POINTS_WAIT_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_pts_amt)],
            ADD_POINTS_WAIT_CONFIRM: [
                CallbackQueryHandler(adm_pts_ok, pattern="^pts_ok$"),
                CallbackQueryHandler(adm_pts_no, pattern="^pts_no$"),
            ],
        },
        fallbacks=[cx], per_message=False,
    ))

    # Broadcast
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_bc_start, pattern="^adm_broadcast$")],
        states={
            BROADCAST_WAIT_MESSAGE: [MessageHandler(
                filters.TEXT | filters.Document.ALL | filters.VIDEO |
                filters.PHOTO | filters.Sticker.ALL | filters.ANIMATION,
                adm_bc_recv
            )],
            BROADCAST_WAIT_CONFIRM: [
                CallbackQueryHandler(adm_bc_ok, pattern="^bc_ok$"),
                CallbackQueryHandler(adm_bc_no, pattern="^bc_no$"),
            ],
        },
        fallbacks=[cx], per_message=False,
    ))

    # Post Now
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_post_start, pattern="^adm_post_now$")],
        states={
            POST_WAIT_TEXT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_post_text)],
            POST_WAIT_BTN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_post_btn_name)],
            POST_WAIT_BTN_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_post_btn_link)],
            POST_WAIT_CHANNEL:  [CallbackQueryHandler(adm_post_send, pattern="^postch_")],
        },
        fallbacks=[cx], per_message=False,
    ))

    # Static callbacks
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_joined_cb,   pattern="^check_joined$"))
    app.add_handler(CallbackQueryHandler(back_home,         pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(menu_files,        pattern="^menu_files$"))
    app.add_handler(CallbackQueryHandler(buy_file_cb,       pattern="^bf_"))
    app.add_handler(CallbackQueryHandler(menu_profile,      pattern="^menu_profile$"))
    app.add_handler(CallbackQueryHandler(menu_refer,        pattern="^menu_refer$"))
    app.add_handler(CallbackQueryHandler(admin_panel,       pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(adm_rem_file,      pattern="^adm_rem_file$"))
    app.add_handler(CallbackQueryHandler(adm_do_remove,     pattern="^dorm_"))
    app.add_handler(CallbackQueryHandler(adm_stats,         pattern="^adm_stats$"))
    app.add_handler(CallbackQueryHandler(adm_view_files,    pattern="^adm_view_files$"))

    print("✅ Sab handlers load ho gaye!")
    print("🚀 Bot chal raha hai... Ctrl+C se band karo.\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
