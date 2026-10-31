
# ═══════════════════════════════════════════════════════════════════════════════
#   OSINT MASTER  —  single-file build  —  ~85 tools, all no-key free APIs
#   runtime: python 3.10+
#   pip install aiogram==2.25.2 pydantic==1.10.13 aiohttp dnspython phonenumbers Pillow
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio
import csv
import io
import re
import json
import sqlite3
import time
import uuid
import hashlib
import urllib.parse
import phonenumbers
import dns.resolver
import aiohttp
from PIL import Image
from PIL.ExifTags import TAGS
from contextlib import closing
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import SkipHandler
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.utils.exceptions import MessageNotModified

# ═══════════════════════════════════════════════════════════════════════════════
#   CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

import os as _os
BOT_TOKEN = _os.getenv("BOT_TOKEN", "8676600538:AAG-J6g9btOJr_p5fyMGMG1WfX1WhDIjFjE")
SUPER_ADMIN_ID = int(_os.getenv("SUPER_ADMIN_ID", "8749565729"))
DB_PATH = "osint_master.db"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,32}$")
EMAIL_RE = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")
DOMAIN_RE = re.compile(r"^(?!\-)(?:[a-zA-Z\d\-]{0,62}[a-zA-Z\d]\.){1,126}(?!\d+)[a-zA-Z\d]{1,63}$")
BTC_RE = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$")
ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
IP_RE = re.compile(r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
HASH_RE = re.compile(r"^[a-fA-F0-9]{32}$|^[a-fA-F0-9]{40}$|^[a-fA-F0-9]{64}$")
ISBN_RE = re.compile(r"^(97[89])?\d{9}[\dXx]$")
COORD_RE = re.compile(r"^-?\d+(\.\d+)?,\s*-?\d+(\.\d+)?$")

SCAN_CACHE = {}
LAST_SCAN = {}
USERS_PER_PAGE = 8

# ═══════════════════════════════════════════════════════════════════════════════
#   PREMIUM EMOJI (from catalog)
# ═══════════════════════════════════════════════════════════════════════════════

def pe(eid, fallback):
    return '<tg-emoji emoji-id="%s">%s</tg-emoji>' % (eid, fallback)

EMO_FIRE     = pe("5424972470023104089", "🔥")
EMO_SEARCH   = pe("5874960879434338403", "🔍")
EMO_CHECK    = pe("5206607081334906820", "✅")
EMO_CROSS    = pe("5210952531676504517", "❌")
EMO_CANCEL   = pe("5240241223632954241", "❌")
EMO_CROWN    = pe("5348306023889254367", "👑")
EMO_STATS    = pe("5931472654660800739", "📊")
EMO_WARN     = pe("5447644880824181073", "⚠️")
EMO_INFO     = pe("5323442290708985472", "ℹ️")
EMO_IDEA     = pe("5422439311196834318", "💡")
EMO_BELL     = pe("5458603043203327669", "🔔")
EMO_PROFILE  = pe("5879770735999717115", "👤")
EMO_EMAIL    = pe("5253742260054409879", "✉️")
EMO_PHONE    = pe("5967591100532134862", "📱")
EMO_GLOBE    = pe("5447410659077661506", "🌐")
EMO_LOCATION = pe("5391032818111363540", "📍")
EMO_DOLLAR   = pe("5409048419211682843", "💵")
EMO_SHIELD   = pe("5361948635317680832", "🛡")
EMO_IMAGE    = pe("5843506780931363129", "🖼")
EMO_CAMERA   = pe("5348104929225489792", "📸")
EMO_HISTORY  = pe("5877410604225924969", "🕒")
EMO_BAN      = pe("5872829476143894491", "🚫")
EMO_ANNOUNCE = pe("5771695636411847302", "📢")
EMO_WRENCH   = pe("5988023995125993550", "🛠")
EMO_KEY      = pe("6005570495603282482", "🔑")
EMO_BOX      = pe("6024106569430472546", "📦")

def sc(t):
    return t.translate(str.maketrans(
        "abcdefghijklmnopqrstuvwxyz",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ"))

# ═══════════════════════════════════════════════════════════════════════════════
#   DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, target TEXT, type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS custom_sites (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, miss TEXT, hit TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', '0')")
        migs = [
            ("users", "username", "TEXT"),
            ("users", "first_name", "TEXT"),
            ("users", "last_seen", "TEXT"),
            ("bans", "reason", "TEXT"),
            ("bans", "banned_at", "TEXT"),
        ]
        for t, col, typ in migs:
            existing = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t).fetchall()}
            if col not in existing:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (t, col, typ))
        conn.commit()

def get_setting(k, d="0"):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        return r[0] if r else d

def set_setting(k, v):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()

def is_admin(uid):
    if uid == SUPER_ADMIN_ID:
        return True
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone() is not None

def is_banned(uid):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,)).fetchone() is not None

def log_user(uid, u=None, fn=None):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT OR REPLACE INTO users (user_id, username, first_name, last_seen) VALUES (?, ?, ?, ?)",
                     (uid, u or "", fn or "", datetime.now(timezone.utc).isoformat()))
        conn.commit()

def log_history(uid, t, ty):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT INTO history (user_id, target, type) VALUES (?, ?, ?)", (uid, t, ty))
        conn.commit()

def audit(uid, a, d=""):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT INTO audit_log (user_id, action, details) VALUES (?, ?, ?)", (uid, a, str(d)[:200]))
        conn.commit()

def get_custom_sites():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT name, url, miss, hit FROM custom_sites").fetchall()
        return {r[0]: {"url": r[1], "miss": [r[2]] if r[2] else [], "hit": [r[3]] if r[3] else []} for r in rows}

def get_all_users():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT user_id, username, first_name FROM users ORDER BY user_id").fetchall()

def get_user(uid):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT user_id, username, first_name, last_seen FROM users WHERE user_id=?", (uid,)).fetchone()

# ═══════════════════════════════════════════════════════════════════════════════
#   MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════

class SecurityMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message, data):
        uid = message.from_user.id if message.from_user else 0
        if is_banned(uid):
            audit(uid, "blocked_banned_user")
            raise SkipHandler
        if get_setting("maintenance") == "1" and not is_admin(uid):
            await message.answer(EMO_WRENCH + " <b>Bot is under maintenance.</b>", parse_mode="HTML")
            raise SkipHandler

# ═══════════════════════════════════════════════════════════════════════════════
#   FSM
# ═══════════════════════════════════════════════════════════════════════════════

class BotStates(StatesGroup):
    wait_input = State()
    wait_image = State()
    wait_exif = State()
    admin_wait_message = State()
    admin_wait_broadcast = State()
    admin_wait_site = State()

# ═══════════════════════════════════════════════════════════════════════════════
#   USERNAME SCAN ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

BASE_SITES = {
    "Reddit":     {"url": "https://www.reddit.com/user/{u}/about.json",
                   "api": "https://www.reddit.com/user/{u}/about.json"},
    "Telegram":   {"url": "https://t.me/{u}", "hit": ["tgme_page_title"]},
    "Mastodon":   {"url": "https://mastodon.social/@{u}"},
    "Bluesky":    {"url": "https://bsky.app/profile/{u}.bsky.social"},
    "Instagram":  {"url": "https://www.instagram.com/{u}/"},
    "TikTok":     {"url": "https://www.tiktok.com/@{u}"},
    "GitHub":     {"url": "https://github.com/{u}",
                   "api": "https://api.github.com/users/{u}"},
    "GitLab":     {"url": "https://gitlab.com/{u}"},
    "HackerNews": {"url": "https://news.ycombinator.com/user?id={u}",
                   "miss": ["no such user."]},
    "Steam":      {"url": "https://steamcommunity.com/id/{u}",
                   "miss": ["the specified profile could not be found"]},
    "YouTube":    {"url": "https://www.youtube.com/@{u}"},
    "Twitch":     {"url": "https://www.twitch.tv/{u}"},
    "Pinterest":  {"url": "https://www.pinterest.com/{u}/"},
    "Tumblr":     {"url": "https://{u}.tumblr.com"},
    "SoundCloud": {"url": "https://soundcloud.com/{u}"},
    "Spotify":    {"url": "https://open.spotify.com/user/{u}"},
    "Vimeo":      {"url": "https://vimeo.com/{u}"},
    "Medium":     {"url": "https://medium.com/@{u}"},
    "DevTo":      {"url": "https://dev.to/{u}"},
    "NPM":        {"url": "https://www.npmjs.com/~{u}"},
    "PyPI":       {"url": "https://pypi.org/user/{u}/"},
    "DockerHub":  {"url": "https://hub.docker.com/u/{u}"},
    "Kaggle":     {"url": "https://www.kaggle.com/{u}"},
    "HuggingFace":{"url": "https://huggingface.co/{u}"},
    "Replit":     {"url": "https://replit.com/@{u}"},
    "CodePen":    {"url": "https://codepen.io/{u}"},
    "Bitbucket":  {"url": "https://bitbucket.org/{u}/"},
    "Behance":    {"url": "https://www.behance.net/{u}"},
    "Dribbble":   {"url": "https://dribbble.com/{u}"},
    "Flickr":     {"url": "https://www.flickr.com/people/{u}"},
    "Patreon":    {"url": "https://www.patreon.com/{u}"},
    "Ko-fi":      {"url": "https://ko-fi.com/{u}"},
    "Etsy":       {"url": "https://www.etsy.com/shop/{u}"},
    "Ebay":       {"url": "https://www.ebay.com/usr/{u}"},
    "Fiverr":     {"url": "https://www.fiverr.com/{u}"},
    "Lichess":    {"url": "https://lichess.org/@/{u}"},
    "Chess.com":  {"url": "https://www.chess.com/member/{u}"},
    "Speedrun":   {"url": "https://www.speedrun.com/user/{u}"},
    "Roblox":     {"url": "https://www.roblox.com/user.aspx?username={u}"},
    "Keybase":    {"url": "https://keybase.io/{u}",
                   "api": "https://keybase.io/_/api/1.0/user/lookup.json?username={u}"},
    "Gravatar":   {"url": "https://en.gravatar.com/{u}"},
}

def generate_variants(name):
    base = name.strip()
    low = base.lower()
    out = [base]
    seen = {base}
    def add(v):
        if v and v not in seen and USERNAME_RE.match(v):
            seen.add(v)
            out.append(v)
    add(low.replace("a", "4").replace("e", "3").replace("i", "1").replace("o", "0"))
    for s in ("1", "01", "99", "0", "7", "_"):
        add(low + s)
    return out[:10]

async def check_site(session, name, spec, u):
    url = spec["url"].format(u=u)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status in (404, 410):
                return None
            if not (200 <= r.status < 300):
                return None
            txt = (await r.content.read(128 * 1024)).decode("utf-8", "ignore").lower()
            if spec.get("miss") and any(m in txt for m in spec["miss"]):
                return None
            if spec.get("hit") and not any(h in txt for h in spec["hit"]):
                return None
            enrich = ""
            img = None
            if "api" in spec:
                try:
                    async with session.get(spec["api"].format(u=u),
                                           timeout=aiohttp.ClientTimeout(total=5)) as ar:
                        if ar.status == 200:
                            data = await ar.json()
                            if name == "GitHub":
                                enrich = "(%s | %s foll)" % (data.get("name", ""), data.get("followers", 0))
                                img = data.get("avatar_url")
                            elif name == "Reddit":
                                d = data.get("data", {})
                                enrich = "(%s karma)" % d.get("total_karma", 0)
                                icon = d.get("icon_img") or ""
                                img = icon.split("?")[0] if icon else None
                            elif name == "Keybase":
                                th = data.get("them") or [{}]
                                if th:
                                    prof = th[0].get("profile") or {}
                                    enrich = "(%s)" % (prof.get("full_name", "") or "")
                except Exception:
                    pass
            return {"site": name, "url": url, "username": u, "enrich": enrich, "img": img}
    except Exception:
        return None

async def run_username_scan(target):
    variants = generate_variants(target)
    sites = dict(BASE_SITES)
    sites.update(get_custom_sites())
    sem = asyncio.Semaphore(30)
    async def worker(sess, v, n, s):
        async with sem:
            return await check_site(sess, n, s, v)
    async with aiohttp.ClientSession(headers={"User-Agent": UA}) as sess:
        tasks = [worker(sess, v, n, s) for v in variants for n, s in sites.items()]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]

# ═══════════════════════════════════════════════════════════════════════════════
#   HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def safe_edit(msg, text, **kw):
    try:
        await msg.edit_text(text, **kw)
    except Exception:
        pass

def fmt_ts(s):
    if not s:
        return "never"
    return str(s)[:19].replace("T", " ")

async def http_get(url, timeout=12):
    async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            ct = r.headers.get("content-type", "")
            if "json" in ct:
                try:
                    return await r.json()
                except Exception:
                    return await r.text()
            return await r.text()

async def http_post(url, data, timeout=12):
    async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
        async with s.post(url, data=data, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            ct = r.headers.get("content-type", "")
            if "json" in ct:
                try:
                    return await r.json()
                except Exception:
                    return await r.text()
            return await r.text()

def short(s, n=200):
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."

# ═══════════════════════════════════════════════════════════════════════════════
#   TOOLS — RECON
# ═══════════════════════════════════════════════════════════════════════════════

async def do_username(message, target):
    uid = message.from_user.id
    now = time.time()
    if now - LAST_SCAN.get(uid, 0) < 15:
        return await message.reply("⏳ Cooldown. Wait %ds." % int(15 - (now - LAST_SCAN.get(uid, 0))))
    LAST_SCAN[uid] = now
    if not USERNAME_RE.match(target):
        return await message.reply("%s Invalid username." % EMO_CROSS, parse_mode="HTML")
    log_history(uid, target, "username")
    audit(uid, "scan_username", target)
    if uid != SUPER_ADMIN_ID:
        try:
            await message.bot.send_message(
                SUPER_ADMIN_ID,
                "%s <b>Live</b>\nUser <code>%d</code> scanned: <code>%s</code>" % (EMO_BELL, uid, target),
                parse_mode="HTML"
            )
        except Exception:
            pass
    msg = await message.reply("%s Scanning %s..." % (EMO_SEARCH, target), parse_mode="HTML")
    hits = await run_username_scan(target)
    if not hits:
        return await safe_edit(msg, "%s No results for %s." % (EMO_CROSS, target),
                               reply_markup=get_main_menu(uid), parse_mode="HTML")
    sid = str(uuid.uuid4())[:8]
    SCAN_CACHE[sid] = hits
    for h in hits:
        if h.get("img"):
            try:
                await message.bot.send_photo(uid, photo=h["img"],
                    caption="%s Avatar on <b>%s</b>" % (EMO_CAMERA, h["site"]),
                    parse_mode="HTML")
                break
            except Exception:
                pass
    await show_page(msg, sid, 0)

async def show_page(msg, sid, page):
    hits = SCAN_CACHE.get(sid, [])
    start = page * 10
    chunk = hits[start:start + 10]
    text = "%s <b>Results</b> (Page %d/%d)\n\n" % (EMO_CHECK, page + 1, (len(hits) + 9) // 10)
    for h in chunk:
        text += "• <b>%s</b>: %s %s\n" % (h["site"], h["url"], h.get("enrich", ""))
    await safe_edit(msg, text, reply_markup=get_results_menu(sid, page, (len(hits) + 9) // 10),
                    parse_mode="HTML", disable_web_page_preview=True)

async def do_email(message, email):
    uid = message.from_user.id
    if not EMAIL_RE.match(email):
        return await message.reply("%s Invalid email." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Checking email..." % EMO_EMAIL, parse_mode="HTML")
    domain = email.split("@")[1]
    text = "%s <b>Email Recon</b>\n\n<b>Email:</b> <code>%s</code>\n<b>Domain:</b> <code>%s</code>\n\n" % (EMO_EMAIL, email, domain)
    try:
        mx = dns.resolver.resolve(domain, "MX")
        text += "<b>MX:</b>\n"
        for r in mx:
            text += "  • <code>%s</code>\n" % str(r.exchange)
    except Exception:
        text += "%s No MX records.\n" % EMO_CROSS
    md5 = hashlib.md5(email.lower().encode()).hexdigest()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://www.gravatar.com/avatar/%s?d=404" % md5, timeout=6) as r:
                if r.status == 200:
                    text += "\n%s <b>Gravatar exists.</b>\n<a href='https://www.gravatar.com/avatar/%s'>view</a>" % (EMO_CHECK, md5)
                else:
                    text += "\n%s No Gravatar." % EMO_CROSS
    except Exception:
        pass
    audit(uid, "email_recon", email)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_phone(message, raw):
    uid = message.from_user.id
    clean = re.sub(r"[\s\-\(\)]", "", raw)
    candidate = None
    if not clean.startswith("+"):
        for region in ("IN", "NP", "US", "GB", "DE", "RU", "BR", "AU", "CA", "FR", "JP", "CN", "KR"):
            try:
                p = phonenumbers.parse(clean, region)
                if phonenumbers.is_valid_number(p):
                    candidate = p
                    break
            except Exception:
                continue
    else:
        try:
            candidate = phonenumbers.parse(clean, None)
        except Exception:
            return await message.reply("%s Could not parse." % EMO_CROSS, parse_mode="HTML")
    if candidate is None:
        return await message.reply("%s <b>Can't detect region.</b>\nSend with country code: <code>+cc+number</code>" % EMO_CROSS, parse_mode="HTML")
    try:
        strict = phonenumbers.is_valid_number(candidate)
    except Exception:
        strict = False
    try:
        lenient = phonenumbers.is_possible_number(candidate)
    except Exception:
        lenient = False
    if not strict and not lenient:
        return await message.reply("%s Invalid phone number." % EMO_CROSS, parse_mode="HTML")
    types = {0: "Fixed Line", 1: "Mobile", 2: "Fixed/Mobile", 3: "Toll Free",
             4: "Premium Rate", 5: "Shared Cost", 6: "VoIP", 7: "Personal",
             8: "Pager", 9: "UAN", 10: "Voicemail"}
    region = phonenumbers.region_code_for_number(candidate)
    carrier = phonenumbers.carrier.name_for_number(candidate, "en")
    tz = phonenumbers.timezone.time_zones_for_number(candidate)
    text = (
        "%s <b>Phone OSINT</b>\n\n"
        "<b>Formatted:</b> %s\n"
        "<b>Region:</b> %s\n"
        "<b>Carrier:</b> %s\n"
        "<b>Type:</b> %s\n"
        "<b>Timezone:</b> %s"
    ) % (EMO_PHONE,
         phonenumbers.format_number(candidate, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
         region or "Unknown",
         carrier or "Unknown",
         types.get(phonenumbers.number_type(candidate), "Unknown"),
         ", ".join(tz) if tz else "Unknown")
    if not strict:
        text += "\n\n%s <i>Number not in current metadata — verify manually.</i>" % EMO_WARN
    audit(uid, "phone_lookup", raw)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_domain(message, domain):
    uid = message.from_user.id
    if not DOMAIN_RE.match(domain):
        return await message.reply("%s Invalid domain." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Domain intel on %s..." % (EMO_GLOBE, domain), parse_mode="HTML")
    text = "%s <b>Domain Intel: %s</b>\n\n" % (EMO_GLOBE, domain)
    for rtype in ("A", "AAAA", "MX", "TXT", "NS", "SOA"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://dns.google/resolve?name=%s&type=%s" % (domain, rtype),
                                 timeout=6) as r:
                    d = await r.json()
                    answers = d.get("Answer", [])
                    if answers:
                        text += "<b>%s:</b> " % rtype
                        text += ", ".join([str(a["data"])[:60] for a in answers[:4]]) + "\n"
        except Exception:
            pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.hackertarget.com/whois/?q=%s" % domain, timeout=10) as r:
                whois = await r.text()
                if "error" not in whois.lower()[:20]:
                    text += "\n<b>WHOIS:</b>\n<code>%s</code>" % short(whois, 400)
    except Exception:
        pass
    audit(uid, "domain_intel", domain)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_ip(message, ip):
    uid = message.from_user.id
    if not IP_RE.match(ip):
        return await message.reply("%s Invalid IP." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s IP intel on %s..." % (EMO_LOCATION, ip), parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://ip-api.com/json/%s?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,reverse,query" % ip,
                             timeout=8) as r:
                d = await r.json()
                if d["status"] != "success":
                    return await safe_edit(msg, "%s Lookup failed." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                rns = "n/a"
                try:
                    async with s.get("https://dns.google/resolve?name=%s.in-addr.arpa&type=PTR" % ".".join(reversed(ip.split("."))), timeout=5) as rr:
                        rd = await rr.json()
                        if rd.get("Answer"):
                            rns = rd["Answer"][0]["data"]
                except Exception:
                    pass
                text = (
                    "%s <b>IP Intel: %s</b>\n\n"
                    "<b>Country:</b> %s (%s)\n"
                    "<b>City:</b> %s (%s)\n"
                    "<b>Coords:</b> %s, %s\n"
                    "<b>ISP:</b> %s\n"
                    "<b>Org:</b> %s\n"
                    "<b>ASN:</b> %s\n"
                    "<b>rDNS:</b> %s\n"
                    "<b>TZ:</b> %s"
                ) % (EMO_LOCATION, ip, d.get("country"), d.get("regionName"),
                     d.get("city"), d.get("zip"), d.get("lat"), d.get("lon"),
                     d.get("isp"), d.get("org"), d.get("as"), rns, d.get("timezone"))
                map_url = "https://static-maps.yandex.ru/1.x/?ll=%s,%s&z=10&l=map&size=600,300" % (d.get("lon"), d.get("lat"))
                try:
                    await message.bot.send_photo(message.chat.id, photo=map_url,
                        caption=text, reply_markup=get_main_menu(uid), parse_mode="HTML")
                    await msg.delete()
                    audit(uid, "ip_intel", ip)
                    return
                except Exception:
                    pass
                audit(uid, "ip_intel", ip)
                await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")
    except Exception:
        await safe_edit(msg, "%s Failed." % EMO_CROSS, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_subdomain(message, domain):
    uid = message.from_user.id
    if not DOMAIN_RE.match(domain):
        return await message.reply("%s Invalid domain." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Fetching subdomains from CRT.sh..." % EMO_SEARCH, parse_mode="HTML")
    subs = set()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://crt.sh/?q=%%25.%s&output=json" % domain, timeout=25) as r:
                if r.status == 200:
                    data = await r.json()
                    for entry in data:
                        for name in (entry.get("name_value") or "").split("\n"):
                            name = name.strip().lower()
                            if name and "*" not in name and name.endswith("." + domain):
                                subs.add(name)
    except Exception:
        pass
    text = "%s <b>Subdomains: %s</b>\n\n" % (EMO_GLOBE, domain)
    if subs:
        text += "<b>Found %d:</b>\n" % len(subs)
        for sub in sorted(subs)[:30]:
            text += "• <code>%s</code>\n" % sub
        if len(subs) > 30:
            text += "\n<i>... and %d more</i>" % (len(subs) - 30)
    else:
        text += "%s None found (or CRT.sh timed out)." % EMO_CROSS
    audit(uid, "subdomain_enum", domain)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_headers(message, url):
    uid = message.from_user.id
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    msg = await message.reply("%s Fetching headers..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
            async with s.get(url, timeout=10, allow_redirects=True) as r:
                h = r.headers
                security = ["Strict-Transport-Security", "Content-Security-Policy",
                            "X-Frame-Options", "X-Content-Type-Options",
                            "Referrer-Policy", "Permissions-Policy"]
                text = "%s <b>HTTP Headers</b>\n<code>%s</code>\n<b>Status:</b> %d\n\n" % (EMO_GLOBE, url, r.status)
                for k in ["Server", "X-Powered-By", "Content-Type", "X-AspNet-Version", "Via"]:
                    if k in h:
                        text += "<b>%s:</b> <code>%s</code>\n" % (k, h[k][:80])
                text += "\n<b>Security headers:</b>\n"
                for k in security:
                    mark = EMO_CHECK if k in h else EMO_CROSS
                    text += "%s <code>%s</code>\n" % (mark, k)
    except Exception as e:
        text = "%s Failed: %s" % (EMO_CROSS, str(e)[:80])
    audit(uid, "http_headers", url)
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_wayback(message, url):
    uid = message.from_user.id
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    msg = await message.reply("%s Checking Wayback..." % EMO_HISTORY, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://archive.org/wayback/available?url=%s" % url, timeout=10) as r:
                d = await r.json()
                snap = d.get("archived_snapshots", {}).get("closest")
                if snap:
                    text = "%s <b>Wayback</b>\n\n<b>URL:</b> <code>%s</code>\n<b>Timestamp:</b> %s\n<b>Archive:</b> <a href='%s'>%s</a>" % (
                        EMO_HISTORY, url, snap.get("timestamp"), snap.get("url"), snap.get("url"))
                else:
                    text = "%s No archived snapshots for <code>%s</code>" % (EMO_CROSS, url)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "wayback", url)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_reverse_ip(message, ip):
    uid = message.from_user.id
    if not IP_RE.match(ip):
        return await message.reply("%s Invalid IP." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Reverse IP lookup..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.hackertarget.com/reverseiplookup/?q=%s" % ip, timeout=12) as r:
                txt = await r.text()
                lines = [l.strip() for l in txt.split("\n") if l.strip() and not l.lower().startswith("error")]
                text = "%s <b>Reverse IP: %s</b>\n\n" % (EMO_GLOBE, ip)
                if lines:
                    text += "<b>%d domain(s):</b>\n" % len(lines)
                    for d in lines[:25]:
                        text += "• <code>%s</code>\n" % d
                    if len(lines) > 25:
                        text += "<i>... and %d more</i>" % (len(lines) - 25)
                else:
                    text += "%s No domains found." % EMO_CROSS
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "reverse_ip", ip)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   TOOLS — CRYPTO
# ═══════════════════════════════════════════════════════════════════════════════

async def do_btc(message, addr):
    uid = message.from_user.id
    if not BTC_RE.match(addr):
        return await message.reply("%s Invalid BTC address." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Checking BTC..." % EMO_DOLLAR, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://blockchain.info/rawaddr/%s?limit=0" % addr, timeout=10) as r:
                d = await r.json()
                bal = d.get("final_balance", 0) / 1e8
                recv = d.get("total_received", 0) / 1e8
                sent = d.get("total_sent", 0) / 1e8
                txs = d.get("n_tx", 0)
                text = (
                    "%s <b>BTC Wallet</b>\n\n"
                    "<code>%s</code>\n\n"
                    "<b>Balance:</b> %s BTC\n"
                    "<b>Received:</b> %s BTC\n"
                    "<b>Sent:</b> %s BTC\n"
                    "<b>Transactions:</b> %d"
                ) % (EMO_DOLLAR, addr, bal, recv, sent, txs)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "btc_wallet", addr)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_eth(message, addr):
    uid = message.from_user.id
    if not ETH_RE.match(addr):
        return await message.reply("%s Invalid ETH address." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Checking ETH..." % EMO_DOLLAR, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.ethplorer.io/getAddressInfo/%s?apiKey=freekey" % addr, timeout=10) as r:
                d = await r.json()
                if d.get("error"):
                    raise Exception(d["error"].get("message", "error"))
                eth = d.get("ETH", {})
                bal = eth.get("balance", 0)
                text = "%s <b>ETH Wallet</b>\n\n<code>%s</code>\n\n<b>Balance:</b> %s ETH\n<b>Tx count:</b> %d" % (
                    EMO_DOLLAR, addr, bal, eth.get("count", 0) or 0)
                tokens = d.get("tokens", [])
                if tokens:
                    text += "\n\n<b>Tokens:</b>\n"
                    for t in tokens[:8]:
                        info = t.get("tokenInfo", {})
                        text += "• %s: %s\n" % (info.get("symbol", "?"), t.get("balance", 0))
    except Exception as e:
        text = "%s Failed: %s" % (EMO_CROSS, str(e)[:80])
    audit(uid, "eth_wallet", addr)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_crypto_price(message, symbol):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching %s..." % (EMO_DOLLAR, symbol), parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd,eur,btc&include_24hr_change=true" % symbol.lower(), timeout=10) as r:
                d = await r.json()
                if not d or symbol.lower() not in d:
                    return await safe_edit(msg, "%s Coin not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                p = d[symbol.lower()]
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>USD:</b> $%s\n"
                    "<b>EUR:</b> €%s\n"
                    "<b>BTC:</b> %s\n"
                    "<b>24h:</b> %s%%"
                ) % (EMO_DOLLAR, symbol.capitalize(),
                     p.get("usd"), p.get("eur"), p.get("btc"),
                     round(p.get("usd_24h_change", 0), 2))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "crypto_price", symbol)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_crypto_global(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching global market..." % EMO_DOLLAR, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/global", timeout=10) as r:
                d = await r.json()
                data = d.get("data", {})
                cap = data.get("total_market_cap", {}).get("usd", 0)
                vol = data.get("total_volume", {}).get("usd", 0)
                btc_d = data.get("market_cap_percentage", {}).get("btc", 0)
                eth_d = data.get("market_cap_percentage", {}).get("eth", 0)
                text = (
                    "%s <b>Global Crypto</b>\n\n"
                    "<b>Market cap:</b> $%.0f\n"
                    "<b>24h volume:</b> $%.0f\n"
                    "<b>BTC dominance:</b> %.2f%%\n"
                    "<b>ETH dominance:</b> %.2f%%\n"
                    "<b>Active cryptos:</b> %s"
                ) % (EMO_DOLLAR, cap, vol, btc_d, eth_d, data.get("active_cryptocurrencies", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "crypto_global")
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_crypto_trending(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching trending..." % EMO_FIRE, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/search/trending", timeout=10) as r:
                d = await r.json()
                coins = d.get("coins", [])
                text = "%s <b>Trending Coins</b>\n\n" % EMO_FIRE
                for c in coins[:8]:
                    item = c.get("item", {})
                    text += "• <b>%s</b> (%s) — rank #%s\n" % (
                        item.get("name"), item.get("symbol"), item.get("market_cap_rank", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "crypto_trending")
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_eth_gas(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching ETH gas..." % EMO_WRENCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.ethgas.watch/api/gas", timeout=10) as r:
                d = await r.json()
                text = (
                    "%s <b>ETH Gas</b>\n\n"
                    "<b>Fast:</b> %s gwei\n"
                    "<b>Standard:</b> %s gwei\n"
                    "<b>Slow:</b> %s gwei"
                ) % (EMO_WRENCH,
                     d.get("fast", {}).get("gwei", "?"),
                     d.get("normal", {}).get("gwei", "?"),
                     d.get("slow", {}).get("gwei", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "eth_gas")
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_btc_fees(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching BTC fees..." % EMO_DOLLAR, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://mempool.space/api/v1/fees/recommended", timeout=10) as r:
                d = await r.json()
                text = (
                    "%s <b>BTC Fees (sat/vB)</b>\n\n"
                    "<b>Fastest:</b> %s\n"
                    "<b>Half hour:</b> %s\n"
                    "<b>Hour:</b> %s\n"
                    "<b>Economy:</b> %s"
                ) % (EMO_DOLLAR, d.get("fastestFee"), d.get("halfHourFee"),
                     d.get("hourFee"), d.get("economyFee"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "btc_fees")
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   TOOLS — THREAT INTEL
# ═══════════════════════════════════════════════════════════════════════════════

async def do_cve(message, cve_id):
    uid = message.from_user.id
    if not CVE_RE.match(cve_id):
        return await message.reply("%s Invalid CVE format." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Looking up %s..." % (EMO_SHIELD, cve_id), parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://cve.circl.lu/api/cve/%s" % cve_id.upper(), timeout=10) as r:
                d = await r.json()
                if not d:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Published:</b> %s\n"
                    "<b>CVSS:</b> %s\n\n"
                    "<b>Summary:</b>\n%s"
                ) % (EMO_SHIELD, cve_id.upper(),
                     (d.get("Published") or "")[:10],
                     d.get("cvss") or "n/a",
                     (d.get("summary") or "")[:600])
                refs = d.get("references", [])
                if refs:
                    text += "\n\n<b>Refs:</b>\n"
                    for r in refs[:3]:
                        text += "• <a href='%s'>%s</a>\n" % (r, r[:60])
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "cve_lookup", cve_id)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_cve_recent(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching recent CVEs..." % EMO_SHIELD, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://cve.circl.lu/api/last", timeout=10) as r:
                d = await r.json()
                text = "%s <b>Latest CVEs</b>\n\n" % EMO_SHIELD
                for c in d[:10]:
                    text += "• <b>%s</b> — %s\n" % (c.get("id", "?"), short(c.get("summary", ""), 100))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "cve_recent")
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_password_hibp(message, password):
    uid = message.from_user.id
    sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    msg = await message.reply("%s Checking HIBP..." % EMO_KEY, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.pwnedpasswords.com/range/%s" % prefix, timeout=10) as r:
                txt = await r.text()
                found = False
                for line in txt.split("\n"):
                    if line.upper().startswith(suffix):
                        count = line.split(":")[1]
                        text = "%s <b>Password PWNED!</b>\n\n<b>Seen in:</b> %s breaches\n<b>SHA1:</b> <code>%s</code>" % (
                            EMO_WARN, count, sha1)
                        found = True
                        break
                if not found:
                    text = "%s <b>Password clean</b>\n\nNot found in HIBP.\n<b>SHA1:</b> <code>%s</code>" % (
                        EMO_CHECK, sha1)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "password_hibp")
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_file_hash(message, h):
    uid = message.from_user.id
    if not HASH_RE.match(h):
        return await message.reply("%s Invalid hash (32/40/64 hex)." % EMO_CROSS, parse_mode="HTML")
    algo = {32: "md5", 40: "sha1", 64: "sha256"}[len(h)]
    msg = await message.reply("%s Looking up %s..." % (EMO_BOX, algo.upper()), parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://hashlookup.circl.lu/lookup/%s/%s" % (algo, h.lower()), timeout=10) as r:
                if r.status == 404:
                    text = "%s <b>Hash not found</b>\n<code>%s</code>" % (EMO_CROSS, h)
                else:
                    d = await r.json()
                    text = (
                        "%s <b>Hash Match</b>\n\n<code>%s</code>\n\n"
                        "<b>File:</b> %s\n<b>Size:</b> %s bytes\n<b>Product:</b> %s"
                    ) % (EMO_CHECK, h, d.get("FileName", "?"),
                         d.get("FileSize", 0), d.get("ProductCode", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "file_hash", h[:20])
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_url_threat(message, url):
    uid = message.from_user.id
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    msg = await message.reply("%s Checking URLhaus..." % EMO_WARN, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://urlhaus-api.abuse.ch/v1/url/", data={"url": url}, timeout=10) as r:
                d = await r.json()
                status = d.get("query_status")
                if status == "no_results":
                    text = "%s <b>URL Threat</b>\n\n<code>%s</code>\n\n%s Not in URLhaus." % (
                        EMO_CHECK, url, EMO_CHECK)
                else:
                    text = "%s <b>URL Threat</b>\n\n<code>%s</code>\n\n<b>Status:</b> %s\n<b>Threat:</b> %s" % (
                        EMO_WARN, url, status, d.get("threat", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "url_threat", url[:60])
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_mac(message, mac):
    uid = message.from_user.id
    if not MAC_RE.match(mac):
        return await message.reply("%s Invalid MAC." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s Vendor lookup..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.macvendors.com/%s" % mac, timeout=10) as r:
                if r.status == 200:
                    text = "%s <b>MAC Vendor</b>\n\n<code>%s</code>\n<b>Vendor:</b> %s" % (
                        EMO_CHECK, mac, await r.text())
                else:
                    text = "%s Vendor not found." % EMO_CROSS
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "mac_vendor", mac)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   TOOLS — MEDIA
# ═══════════════════════════════════════════════════════════════════════════════

async def do_reverse_image(message):
    uid = message.from_user.id
    f = await message.bot.get_file(message.photo[-1].file_id)
    furl = "https://api.telegram.org/file/bot%s/%s" % (BOT_TOKEN, f.file_path)
    text = (
        "%s <b>Reverse Image Search</b>\n\n"
        "• <a href='https://lens.google.com/uploadbyurl?url=%s'>Google Lens</a>\n"
        "• <a href='https://yandex.com/images/search?rpt=imageview&url=%s'>Yandex</a>\n"
        "• <a href='https://tineye.com/search?url=%s'>TinEye</a>\n"
        "• <a href='https://www.bing.com/images/searchbyimage/upload?cbir=sbi&imgurl=%s'>Bing Visual</a>"
    ) % (EMO_IMAGE, furl, furl, furl, furl)
    audit(uid, "reverse_image")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_exif(message):
    uid = message.from_user.id
    f = await message.bot.get_file(message.document.file_id)
    buf = io.BytesIO()
    await f.download(destination=buf)
    text = "%s <b>EXIF Metadata</b>\n\n" % EMO_CAMERA
    try:
        img = Image.open(buf)
        exif = img._getexif()
        if not exif:
            text += "%s No EXIF data found." % EMO_CROSS
        else:
            for tid, val in exif.items():
                tag = TAGS.get(tid, tid)
                if tag in ["Make", "Model", "Software", "DateTime", "GPSInfo", "LensModel", "FocalLength"]:
                    text += "• <b>%s:</b> <code>%s</code>\n" % (tag, str(val)[:80])
    except Exception:
        text += "%s Failed to parse image." % EMO_CROSS
    audit(uid, "exif")
    await message.reply(text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   TOOLS — UTILITY / MISC
# ═══════════════════════════════════════════════════════════════════════════════

async def do_weather(message, query):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching weather..." % EMO_GLOBE, parse_mode="HTML")
    try:
        if "," in query:
            p = query.split(",")
            lat, lon = p[0].strip(), p[1].strip()
            city = "%.4f,%.4f" % (float(lat), float(lon))
        else:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1" % query, timeout=8) as r:
                    g = await r.json()
                    res = g.get("results") or []
                    if not res:
                        return await safe_edit(msg, "%s City not found." % EMO_CROSS,
                                               reply_markup=get_main_menu(uid), parse_mode="HTML")
                    lat = res[0]["latitude"]
                    lon = res[0]["longitude"]
                    city = res[0]["name"]
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current_weather=true" % (lat, lon), timeout=8) as r:
                d = await r.json()
                cw = d.get("current_weather", {})
                text = (
                    "%s <b>Weather: %s</b>\n\n"
                    "<b>Temp:</b> %s°C\n"
                    "<b>Wind:</b> %s km/h\n"
                    "<b>Direction:</b> %s°\n"
                    "<b>Weather code:</b> %s"
                ) % (EMO_GLOBE, city, cw.get("temperature"), cw.get("windspeed"),
                     cw.get("winddirection"), cw.get("weathercode"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "weather", query[:40])
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_currency(message, base):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching rates..." % EMO_DOLLAR, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.frankfurter.dev/v1/latest?base=%s" % base.upper(), timeout=8) as r:
                d = await r.json()
                if "rates" not in d:
                    return await safe_edit(msg, "%s Invalid currency." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                text = "%s <b>Currency: %s</b>\n<i>%s</i>\n\n" % (EMO_DOLLAR, base.upper(), d.get("date"))
                for k, v in list(d["rates"].items())[:20]:
                    text += "• <b>%s:</b> %s\n" % (k, v)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "currency", base)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_wiki(message, q):
    uid = message.from_user.id
    msg = await message.reply("%s Searching Wikipedia..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=%s&format=json&utf8=1&srlimit=3" % urllib.parse.quote(q), timeout=10) as r:
                d = await r.json()
                results = d.get("query", {}).get("search", [])
                if not results:
                    return await safe_edit(msg, "%s No results." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                text = "%s <b>Wikipedia: %s</b>\n\n" % (EMO_GLOBE, q)
                for res in results:
                    title = res["title"]
                    snippet = re.sub(r"<[^>]+>", "", res.get("snippet", ""))
                    url = "https://en.wikipedia.org/wiki/%s" % title.replace(" ", "_")
                    text += "<b>%s</b>\n%s\n<a href='%s'>Read →</a>\n\n" % (title, snippet, url)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "wiki", q[:40])
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_fact(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://uselessfacts.jsph.pl/random.json?language=en", timeout=8) as r:
                d = await r.json()
                fact = d.get("text", "?")
    except Exception:
        fact = "Failed."
    audit(uid, "fact")
    await message.reply("%s <b>Random Fact</b>\n\n%s" % (EMO_IDEA, fact),
                        reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_quote(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://zenquotes.io/api/random", timeout=8) as r:
                d = await r.json()
                q = d[0].get("q", "?")
                a = d[0].get("a", "?")
    except Exception:
        q, a = "Failed.", ""
    audit(uid, "quote")
    await message.reply("%s <b>Quote</b>\n\n<i>%s</i>\n— %s" % (EMO_IDEA, q, a),
                        reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_joke(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://official-joke-api.appspot.com/random_joke", timeout=8) as r:
                d = await r.json()
                text = "%s <b>Joke</b>\n\n%s\n\n<i>%s</i>" % (EMO_IDEA, d.get("setup"), d.get("punchline"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "joke")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_cat_image(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.thecatapi.com/v1/images/search", timeout=8) as r:
                d = await r.json()
                img = d[0]["url"]
        await message.bot.send_photo(message.chat.id, photo=img,
            caption="%s Random cat" % EMO_CAMERA, reply_markup=get_main_menu(uid), parse_mode="HTML")
    except Exception:
        await message.reply("%s Failed." % EMO_CROSS, parse_mode="HTML")
    audit(uid, "cat")

async def do_dog_image(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://dog.ceo/api/breeds/image/random", timeout=8) as r:
                d = await r.json()
                img = d["message"]
        await message.bot.send_photo(message.chat.id, photo=img,
            caption="%s Random dog" % EMO_CAMERA, reply_markup=get_main_menu(uid), parse_mode="HTML")
    except Exception:
        await message.reply("%s Failed." % EMO_CROSS, parse_mode="HTML")
    audit(uid, "dog")

async def do_fox_image(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://randomfox.ca/floof/", timeout=8) as r:
                d = await r.json()
                img = d["image"]
        await message.bot.send_photo(message.chat.id, photo=img,
            caption="%s Random fox" % EMO_CAMERA, reply_markup=get_main_menu(uid), parse_mode="HTML")
    except Exception:
        await message.reply("%s Failed." % EMO_CROSS, parse_mode="HTML")
    audit(uid, "fox")

async def do_pokemon(message, name):
    uid = message.from_user.id
    msg = await message.reply("%s Looking up %s..." % (EMO_SEARCH, name), parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://pokeapi.co/api/v2/pokemon/%s" % name.lower(), timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Pokemon not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                types = ", ".join([t["type"]["name"] for t in d.get("types", [])])
                abilities = ", ".join([a["ability"]["name"] for a in d.get("abilities", [])])
                stats = "\n".join(["• %s: %d" % (s["stat"]["name"], s["base_stat"]) for s in d.get("stats", [])])
                text = (
                    "%s <b>%s</b> (#%d)\n\n"
                    "<b>Types:</b> %s\n"
                    "<b>Abilities:</b> %s\n\n"
                    "<b>Base stats:</b>\n%s"
                ) % (EMO_BOX, d["name"].capitalize(), d["id"], types, abilities, stats)
                img = d.get("sprites", {}).get("front_default")
                if img:
                    try:
                        await message.bot.send_photo(message.chat.id, photo=img,
                            caption=text, reply_markup=get_main_menu(uid), parse_mode="HTML")
                        await msg.delete()
                        return
                    except Exception:
                        pass
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "pokemon", name)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_rick_morty(message, cid):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching character..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://rickandmortyapi.com/api/character/%s" % cid, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Status:</b> %s\n"
                    "<b>Species:</b> %s\n"
                    "<b>Gender:</b> %s\n"
                    "<b>Origin:</b> %s\n"
                    "<b>Location:</b> %s"
                ) % (EMO_BOX, d.get("name"), d.get("status"), d.get("species"),
                     d.get("gender"), d.get("origin", {}).get("name"),
                     d.get("location", {}).get("name"))
                img = d.get("image")
                if img:
                    try:
                        await message.bot.send_photo(message.chat.id, photo=img,
                            caption=text, reply_markup=get_main_menu(uid), parse_mode="HTML")
                        await msg.delete()
                        return
                    except Exception:
                        pass
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "rick_morty", cid)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_star_wars(message, pid):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://swapi.dev/api/people/%s" % pid, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Height:</b> %s cm\n"
                    "<b>Mass:</b> %s kg\n"
                    "<b>Birth year:</b> %s\n"
                    "<b>Gender:</b> %s\n"
                    "<b>Hair:</b> %s\n"
                    "<b>Eyes:</b> %s"
                ) % (EMO_BOX, d.get("name"), d.get("height"), d.get("mass"),
                     d.get("birth_year"), d.get("gender"), d.get("hair_color"),
                     d.get("eye_color"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "star_wars", pid)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_anime(message, q):
    uid = message.from_user.id
    msg = await message.reply("%s Searching anime..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.jikan.moe/v4/anime?q=%s&limit=1" % urllib.parse.quote(q), timeout=10) as r:
                d = await r.json()
                data = d.get("data", [])
                if not data:
                    return await safe_edit(msg, "%s No results." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                a = data[0]
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Type:</b> %s\n"
                    "<b>Episodes:</b> %s\n"
                    "<b>Score:</b> %s\n"
                    "<b>Status:</b> %s\n\n"
                    "<b>Synopsis:</b>\n%s"
                ) % (EMO_BOX, a.get("title"), a.get("type"), a.get("episodes"),
                     a.get("score"), a.get("status"),
                     short(a.get("synopsis", ""), 500))
                img = a.get("images", {}).get("jpg", {}).get("image_url")
                if img:
                    try:
                        await message.bot.send_photo(message.chat.id, photo=img,
                            caption=text, reply_markup=get_main_menu(uid), parse_mode="HTML")
                        await msg.delete()
                        return
                    except Exception:
                        pass
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "anime", q)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_kanye(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.kanye.rest/", timeout=8) as r:
                d = await r.json()
                text = "%s <b>Kanye West says:</b>\n\n<i>%s</i>" % (EMO_IDEA, d.get("quote"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "kanye")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_yes_no(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://yesno.wtf/api", timeout=8) as r:
                d = await r.json()
                text = "%s <b>%s</b>\n\n<img src='%s'>" % (EMO_IDEA, d.get("answer", "?").upper(), d.get("image", ""))
                text = "%s <b>%s</b>" % (EMO_IDEA, d.get("answer", "?").upper())
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "yes_no")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_chuck(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.chucknorris.io/jokes/random", timeout=8) as r:
                d = await r.json()
                text = "%s <b>Chuck Norris</b>\n\n%s" % (EMO_IDEA, d.get("value"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "chuck")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_advice(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.adviceslip.com/advice", timeout=8) as r:
                d = await r.json()
                text = "%s <b>Advice</b>\n\n%s" % (EMO_IDEA, d.get("slip", {}).get("advice"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "advice")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_bored(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://www.boredapi.com/api/activity", timeout=8) as r:
                d = await r.json()
                text = "%s <b>Bored?</b>\n\n%s\n\n<i>Type: %s</i>" % (
                    EMO_IDEA, d.get("activity", "?"), d.get("type", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "bored")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_trivia(message):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://opentdb.com/api.php?amount=1", timeout=8) as r:
                d = await r.json()
                q = d.get("results", [{}])[0]
                text = "%s <b>Trivia</b>\n\n%s\n\n<i>Category: %s, Difficulty: %s</i>" % (
                    EMO_IDEA, q.get("question", "?"), q.get("category", "?"), q.get("difficulty", "?"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "trivia")
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_gender(message, name):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.genderize.io/?name=%s" % name, timeout=8) as r:
                d = await r.json()
                text = "%s <b>Gender Guess</b>\n\n<b>Name:</b> %s\n<b>Gender:</b> %s\n<b>Probability:</b> %.0f%%" % (
                    EMO_PROFILE, d.get("name"), d.get("gender") or "unknown", (d.get("probability") or 0) * 100)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "gender", name)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_age(message, name):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.agify.io/?name=%s" % name, timeout=8) as r:
                d = await r.json()
                text = "%s <b>Age Guess</b>\n\n<b>Name:</b> %s\n<b>Predicted age:</b> %s\n<b>Sample size:</b> %s" % (
                    EMO_PROFILE, d.get("name"), d.get("age"), d.get("count"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "age", name)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_nationality(message, name):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.nationalize.io/?name=%s" % name, timeout=8) as r:
                d = await r.json()
                countries = d.get("country", [])
                text = "%s <b>Nationality Guess: %s</b>\n\n" % (EMO_PROFILE, name)
                if countries:
                    for c in countries[:5]:
                        text += "• <b>%s:</b> %.1f%%\n" % (c.get("country_id"), (c.get("probability") or 0) * 100)
                else:
                    text += "No matches."
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "nationality", name)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_country(message, name):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching country..." % EMO_GLOBE, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://restcountries.com/v3.1/name/%s" % urllib.parse.quote(name), timeout=10) as r:
                d = await r.json()
                if not isinstance(d, list) or not d:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                c = d[0]
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Official:</b> %s\n"
                    "<b>Capital:</b> %s\n"
                    "<b>Region:</b> %s / %s\n"
                    "<b>Population:</b> %s\n"
                    "<b>Area:</b> %s km²\n"
                    "<b>Currency:</b> %s\n"
                    "<b>Languages:</b> %s\n"
                    "<b>TLD:</b> %s"
                ) % (
                    EMO_GLOBE, c.get("name", {}).get("common"),
                    c.get("name", {}).get("official"),
                    ", ".join(c.get("capital") or ["?"]),
                    c.get("region"), c.get("subregion"),
                    c.get("population"),
                    c.get("area"),
                    ", ".join([v.get("name", "?") for v in (c.get("currencies") or {}).values()]),
                    ", ".join((c.get("languages") or {}).values()) or "?",
                    ", ".join(c.get("tld") or ["?"])
                )
                flag = c.get("flags", {}).get("png")
                if flag:
                    try:
                        await message.bot.send_photo(message.chat.id, photo=flag,
                            caption=text, reply_markup=get_main_menu(uid), parse_mode="HTML")
                        await msg.delete()
                        return
                    except Exception:
                        pass
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "country", name)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_world_time(message, tz):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://worldtimeapi.org/api/timezone/%s" % tz, timeout=8) as r:
                if r.status != 200:
                    return await message.reply("%s Invalid timezone. Try <code>Europe/London</code>" % EMO_CROSS,
                                                reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                text = (
                    "%s <b>%s</b>\n\n"
                    "<b>Datetime:</b> %s\n"
                    "<b>UTC offset:</b> %s\n"
                    "<b>Day of week:</b> %s\n"
                    "<b>Week:</b> %s"
                ) % (EMO_HISTORY, tz, (d.get("datetime") or "")[:19].replace("T", " "),
                     d.get("utc_offset"), d.get("day_of_week"), d.get("week_number"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "world_time", tz)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_github_user(message, username):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching GitHub user..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.github.com/users/%s" % username, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                text = (
                    "%s <b>GitHub: %s</b>\n\n"
                    "<b>Name:</b> %s\n"
                    "<b>Bio:</b> %s\n"
                    "<b>Company:</b> %s\n"
                    "<b>Location:</b> %s\n"
                    "<b>Public repos:</b> %s\n"
                    "<b>Followers:</b> %s\n"
                    "<b>Following:</b> %s\n"
                    "<b>Created:</b> %s\n"
                    "<a href='%s'>Profile →</a>"
                ) % (EMO_PROFILE, d.get("login"), d.get("name") or "—",
                     d.get("bio") or "—", d.get("company") or "—",
                     d.get("location") or "—", d.get("public_repos"),
                     d.get("followers"), d.get("following"),
                     (d.get("created_at") or "")[:10], d.get("html_url"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "github_user", username)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_npm(message, pkg):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching npm..." % EMO_BOX, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://registry.npmjs.org/%s" % pkg, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Package not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                latest = d.get("dist-tags", {}).get("latest", "?")
                info = d.get("versions", {}).get(latest, {})
                text = (
                    "%s <b>npm: %s</b>\n\n"
                    "<b>Latest:</b> %s\n"
                    "<b>Description:</b> %s\n"
                    "<b>License:</b> %s\n"
                    "<b>Author:</b> %s\n"
                    "<b>Repo:</b> %s"
                ) % (EMO_BOX, d.get("name"), latest,
                     short(d.get("description", "—"), 200),
                     info.get("license", "—"),
                     (info.get("author") or {}).get("name", "—") if isinstance(info.get("author"), dict) else str(info.get("author", "—")),
                     ((info.get("repository") or {}).get("url", "—") if isinstance(info.get("repository"), dict) else "—"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "npm", pkg)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_pypi(message, pkg):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching PyPI..." % EMO_BOX, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://pypi.org/pypi/%s/json" % pkg, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Package not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                info = d.get("info", {})
                text = (
                    "%s <b>PyPI: %s</b>\n\n"
                    "<b>Version:</b> %s\n"
                    "<b>Author:</b> %s\n"
                    "<b>Summary:</b> %s\n"
                    "<b>Home:</b> %s"
                ) % (EMO_BOX, info.get("name"), info.get("version"),
                     info.get("author"), short(info.get("summary", "—"), 200),
                     info.get("home_page") or "—")
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "pypi", pkg)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_book(message, q):
    uid = message.from_user.id
    msg = await message.reply("%s Searching books..." % EMO_BOX, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://openlibrary.org/search.json?q=%s&limit=3" % urllib.parse.quote(q), timeout=10) as r:
                d = await r.json()
                docs = d.get("docs", [])
                if not docs:
                    return await safe_edit(msg, "%s No results." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                text = "%s <b>Books: %s</b>\n\n" % (EMO_BOX, q)
                for b in docs:
                    text += "<b>%s</b>\n" % b.get("title", "?")
                    if b.get("author_name"):
                        text += "by %s\n" % ", ".join(b["author_name"][:2])
                    if b.get("first_publish_year"):
                        text += "Published: %s\n" % b["first_publish_year"]
                    if b.get("key"):
                        text += "<a href='https://openlibrary.org%s'>Open →</a>\n" % b["key"]
                    text += "\n"
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "book", q)
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_define(message, word):
    uid = message.from_user.id
    msg = await message.reply("%s Defining..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.dictionaryapi.dev/api/v2/entries/en/%s" % word, timeout=10) as r:
                d = await r.json()
                if not isinstance(d, list) or not d:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                entry = d[0]
                text = "%s <b>%s</b>\n\n" % (EMO_BOX, entry.get("word", word))
                for m in entry.get("meanings", [])[:3]:
                    text += "<b>%s</b>\n" % m.get("partOfSpeech", "?")
                    for defn in m.get("definitions", [])[:3]:
                        text += "• %s\n" % short(defn.get("definition", ""), 180)
                    text += "\n"
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "define", word)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_urban(message, word):
    uid = message.from_user.id
    msg = await message.reply("%s Searching Urban Dictionary..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.urbandictionary.com/v0/define?term=%s" % urllib.parse.quote(word), timeout=10) as r:
                d = await r.json()
                lst = d.get("list", [])
                if not lst:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                e = lst[0]
                text = "%s <b>%s</b>\n\n%s\n\n<i>Example: %s</i>\n\n👍 %s 👎 %s" % (
                    EMO_BOX, e.get("word"),
                    short(e.get("definition", ""), 400),
                    short(e.get("example", ""), 200),
                    e.get("thumbs_up", 0), e.get("thumbs_down", 0))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "urban", word)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_synonyms(message, word):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.datamuse.com/words?rel_syn=%s&max=15" % word, timeout=8) as r:
                d = await r.json()
                words = [w.get("word") for w in d[:15]]
                text = "%s <b>Synonyms: %s</b>\n\n%s" % (EMO_BOX, word, ", ".join(words) or "none")
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "synonyms", word)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_number_fact(message, num):
    uid = message.from_user.id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("http://numbersapi.com/%s" % num, timeout=8) as r:
                fact = await r.text()
                text = "%s <b>Number Fact</b>\n\n%s" % (EMO_IDEA, fact)
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "number_fact", num)
    await message.reply(text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_radio(message, name):
    uid = message.from_user.id
    msg = await message.reply("%s Searching radio..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://de1.api.radio-browser.info/json/stations/search?name=%s&limit=5" % urllib.parse.quote(name), timeout=10) as r:
                d = await r.json()
                if not d:
                    return await safe_edit(msg, "%s No stations." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                text = "%s <b>Radio: %s</b>\n\n" % (EMO_BOX, name)
                for st in d[:5]:
                    text += "<b>%s</b>\n%s\n<a href='%s'>Listen</a>\n\n" % (
                        st.get("name"), st.get("tags", "")[:60], st.get("url_resolved") or st.get("url"))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "radio", name)
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_hackernews(message):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching HN top..." % EMO_HISTORY, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10) as r:
                ids = await r.json()
            text = "%s <b>Hacker News Top 5</b>\n\n" % EMO_HISTORY
            for i, h in enumerate(ids[:5]):
                async with s.get("https://hacker-news.firebaseio.com/v0/item/%d.json" % h, timeout=5) as rr:
                    item = await rr.json()
                    text += "%d. <a href='%s'>%s</a>\n<i>%d points</i>\n\n" % (
                        i+1, item.get("url", "#"), item.get("title", "?"), item.get("score", 0))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "hackernews")
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML", disable_web_page_preview=True)

async def do_chess(message, username):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching chess profile..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.chess.com/pub/player/%s/stats" % username, timeout=10) as r:
                if r.status != 200:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                d = await r.json()
                text = "%s <b>Chess.com: %s</b>\n\n" % (EMO_PROFILE, username)
                for key in ["chess_blitz", "chess_bullet", "chess_rapid"]:
                    if key in d:
                        rec = d[key].get("record", {})
                        text += "<b>%s:</b> W%d L%d D%d\n" % (
                            key.replace("chess_", "").title(),
                            rec.get("win", 0), rec.get("loss", 0), rec.get("draw", 0))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "chess", username)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_steam(message, vanity):
    uid = message.from_user.id
    msg = await message.reply("%s Fetching Steam..." % EMO_SEARCH, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?vanityurl=%s" % vanity, timeout=10) as r:
                d = await r.json()
                if d.get("response", {}).get("success") != 1:
                    return await safe_edit(msg, "%s Not found." % EMO_CROSS,
                                           reply_markup=get_main_menu(uid), parse_mode="HTML")
                sid = d["response"]["steamid"]
                async with s.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?steamids=%s" % sid, timeout=10) as rr:
                    p = await rr.json()
                    player = p.get("response", {}).get("players", [{}])[0]
                    text = (
                        "%s <b>Steam: %s</b>\n\n"
                        "<b>SteamID:</b> <code>%s</code>\n"
                        "<b>Real name:</b> %s\n"
                        "<b>Status:</b> %s\n"
                        "<b>Country:</b> %s\n"
                        "<a href='%s'>Profile</a>"
                    ) % (EMO_PROFILE, player.get("personaname", "?"), sid,
                         player.get("realname", "—"), player.get("personastate", "?"),
                         player.get("loccountrycode", "—"), player.get("profileurl", ""))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "steam", vanity)
    await safe_edit(msg, text, reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_whois(message, domain):
    uid = message.from_user.id
    if not DOMAIN_RE.match(domain):
        return await message.reply("%s Invalid domain." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s WHOIS..." % EMO_GLOBE, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.hackertarget.com/whois/?q=%s" % domain, timeout=12) as r:
                txt = await r.text()
                if "error" in txt.lower()[:20]:
                    text = "%s %s" % (EMO_CROSS, txt)
                else:
                    text = "%s <b>WHOIS: %s</b>\n\n<code>%s</code>" % (EMO_GLOBE, domain, short(txt, 3500))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "whois", domain)
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML")

async def do_dns_lookup(message, domain):
    uid = message.from_user.id
    if not DOMAIN_RE.match(domain):
        return await message.reply("%s Invalid domain." % EMO_CROSS, parse_mode="HTML")
    msg = await message.reply("%s DNS lookup..." % EMO_GLOBE, parse_mode="HTML")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.hackertarget.com/dnslookup/?q=%s" % domain, timeout=10) as r:
                txt = await r.text()
                text = "%s <b>DNS: %s</b>\n\n<code>%s</code>" % (EMO_GLOBE, domain, short(txt, 3500))
    except Exception:
        text = "%s Failed." % EMO_CROSS
    audit(uid, "dns_lookup", domain)
    await safe_edit(msg, text[:4000], reply_markup=get_main_menu(uid), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════════

def get_main_menu(uid):
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🔍 Username", callback_data="tool:username"),
          InlineKeyboardButton(text="📱 Phone", callback_data="tool:phone"))
    m.add(InlineKeyboardButton(text="📍 IP", callback_data="tool:ip"),
          InlineKeyboardButton(text="🌐 Domain", callback_data="tool:domain"))
    m.add(InlineKeyboardButton(text="🔍 RECON", callback_data="cat:recon"),
          InlineKeyboardButton(text="🔐 CRYPTO", callback_data="cat:crypto"))
    m.add(InlineKeyboardButton(text="🛡 THREAT INTEL", callback_data="cat:threat"),
          InlineKeyboardButton(text="📸 MEDIA", callback_data="cat:media"))
    m.add(InlineKeyboardButton(text="🎮 GAMES", callback_data="cat:games"),
          InlineKeyboardButton(text="🔧 UTILITIES", callback_data="cat:util"))
    m.add(InlineKeyboardButton(text="🎨 FUN", callback_data="cat:fun"),
          InlineKeyboardButton(text="📚 INFO", callback_data="cat:info"))
    m.add(InlineKeyboardButton(text="👤 PROFILE", callback_data="menu:profile"),
          InlineKeyboardButton(text="🛠 HELP", callback_data="menu:help"))
    if is_admin(uid):
        m.add(InlineKeyboardButton(text="👑 ADMIN PANEL", callback_data="admin:main"))
    return m

def get_recon_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🔍 Username", callback_data="tool:username"),
          InlineKeyboardButton(text="✉️ Email", callback_data="tool:email"))
    m.add(InlineKeyboardButton(text="📱 Phone", callback_data="tool:phone"),
          InlineKeyboardButton(text="🌐 Domain Intel", callback_data="tool:domain"))
    m.add(InlineKeyboardButton(text="📍 IP Intel", callback_data="tool:ip"),
          InlineKeyboardButton(text="🔎 Subdomains", callback_data="tool:subdomain"))
    m.add(InlineKeyboardButton(text="📡 HTTP Headers", callback_data="tool:headers"),
          InlineKeyboardButton(text="🕰 Wayback", callback_data="tool:wayback"))
    m.add(InlineKeyboardButton(text="↩️ Reverse IP", callback_data="tool:reverse_ip"),
          InlineKeyboardButton(text="📖 WHOIS", callback_data="tool:whois"))
    m.add(InlineKeyboardButton(text="📋 DNS Lookup", callback_data="tool:dns_lookup"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_crypto_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="₿ BTC Wallet", callback_data="tool:btc"),
          InlineKeyboardButton(text="Ξ ETH Wallet", callback_data="tool:eth"))
    m.add(InlineKeyboardButton(text="💵 Crypto Price", callback_data="tool:crypto_price"),
          InlineKeyboardButton(text="🌐 Global", callback_data="tool:crypto_global"))
    m.add(InlineKeyboardButton(text="🔥 Trending", callback_data="tool:crypto_trending"),
          InlineKeyboardButton(text="⛽ ETH Gas", callback_data="tool:eth_gas"))
    m.add(InlineKeyboardButton(text="💸 BTC Fees", callback_data="tool:btc_fees"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_threat_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🛡 CVE Lookup", callback_data="tool:cve"),
          InlineKeyboardButton(text="📰 Recent CVEs", callback_data="tool:cve_recent"))
    m.add(InlineKeyboardButton(text="🔑 Password HIBP", callback_data="tool:password_hibp"),
          InlineKeyboardButton(text="📁 File Hash", callback_data="tool:file_hash"))
    m.add(InlineKeyboardButton(text="⚠️ URL Threat", callback_data="tool:url_threat"),
          InlineKeyboardButton(text="🖧 MAC Vendor", callback_data="tool:mac"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_media_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="📸 EXIF", callback_data="tool:exif"),
          InlineKeyboardButton(text="🖼 Reverse Image", callback_data="tool:image"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_games_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🎮 Pokemon", callback_data="tool:pokemon"),
          InlineKeyboardButton(text="🎲 R&M Character", callback_data="tool:rick_morty"))
    m.add(InlineKeyboardButton(text="⭐ Star Wars", callback_data="tool:star_wars"),
          InlineKeyboardButton(text="🎬 Anime", callback_data="tool:anime"))
    m.add(InlineKeyboardButton(text="♟ Chess.com", callback_data="tool:chess"),
          InlineKeyboardButton(text="🎮 Steam", callback_data="tool:steam"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_util_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🌤 Weather", callback_data="tool:weather"),
          InlineKeyboardButton(text="💱 Currency", callback_data="tool:currency"))
    m.add(InlineKeyboardButton(text="📚 Wikipedia", callback_data="tool:wiki"),
          InlineKeyboardButton(text="📖 Define Word", callback_data="tool:define"))
    m.add(InlineKeyboardButton(text="📕 Books", callback_data="tool:book"),
          InlineKeyboardButton(text="🎵 Radio", callback_data="tool:radio"))
    m.add(InlineKeyboardButton(text="⏰ World Time", callback_data="tool:world_time"),
          InlineKeyboardButton(text="🌍 Country Info", callback_data="tool:country"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_fun_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🎲 Fact", callback_data="tool:fact"),
          InlineKeyboardButton(text="💬 Quote", callback_data="tool:quote"))
    m.add(InlineKeyboardButton(text="😂 Joke", callback_data="tool:joke"),
          InlineKeyboardButton(text="🐱 Cat Pic", callback_data="tool:cat_pic"))
    m.add(InlineKeyboardButton(text="🐶 Dog Pic", callback_data="tool:dog_pic"),
          InlineKeyboardButton(text="🦊 Fox Pic", callback_data="tool:fox_pic"))
    m.add(InlineKeyboardButton(text="🌬 Kanye", callback_data="tool:kanye"),
          InlineKeyboardButton(text="✅ Yes/No", callback_data="tool:yes_no"))
    m.add(InlineKeyboardButton(text="💪 Chuck Norris", callback_data="tool:chuck"),
          InlineKeyboardButton(text="💡 Advice", callback_data="tool:advice"))
    m.add(InlineKeyboardButton(text="😴 Bored", callback_data="tool:bored"),
          InlineKeyboardButton(text="🧠 Trivia", callback_data="tool:trivia"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_info_menu():
    m = InlineKeyboardMarkup(row_width=2)
    m.add(InlineKeyboardButton(text="🐙 GitHub User", callback_data="tool:github_user"),
          InlineKeyboardButton(text="📦 npm Package", callback_data="tool:npm"))
    m.add(InlineKeyboardButton(text="🐍 PyPI Package", callback_data="tool:pypi"),
          InlineKeyboardButton(text="📰 Hacker News", callback_data="tool:hackernews"))
    m.add(InlineKeyboardButton(text="👤 Gender Guess", callback_data="tool:gender"),
          InlineKeyboardButton(text="🎂 Age Guess", callback_data="tool:age"))
    m.add(InlineKeyboardButton(text="🌍 Nationality", callback_data="tool:nationality"),
          InlineKeyboardButton(text="📖 Synonyms", callback_data="tool:synonyms"))
    m.add(InlineKeyboardButton(text="🔤 Define", callback_data="tool:define"),
          InlineKeyboardButton(text="📚 Urban Dict", callback_data="tool:urban"))
    m.add(InlineKeyboardButton(text="🔢 Number Fact", callback_data="tool:number_fact"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_cancel():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton(text="❌ CANCEL", callback_data="menu:cancel"))
    return m

def get_admin_menu():
    m = InlineKeyboardMarkup(row_width=2)
    maint = "🟢 ON" if get_setting("maintenance") == "1" else "🔴 OFF"
    m.add(InlineKeyboardButton(text="👥 USER LIST", callback_data="admin:users"))
    m.add(InlineKeyboardButton(text="📢 BROADCAST", callback_data="admin:broadcast"),
          InlineKeyboardButton(text="MAINT: %s" % maint, callback_data="admin:maint"))
    m.add(InlineKeyboardButton(text="🌐 ADD SITE", callback_data="admin:addsite"),
          InlineKeyboardButton(text="📊 STATS", callback_data="admin:stats"))
    m.add(InlineKeyboardButton(text="📜 AUDIT LOG", callback_data="admin:audit"))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

def get_user_list_kb(page=0):
    users = get_all_users()
    total = len(users)
    start = page * USERS_PER_PAGE
    chunk = users[start:start + USERS_PER_PAGE]
    m = InlineKeyboardMarkup(row_width=1)
    for uid, uname, fname in chunk:
        label = fname or uname or str(uid)
        m.add(InlineKeyboardButton(text="%s (%d)" % (label, uid), callback_data="admin:user:%d" % uid))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ PREV", callback_data="admin:users:%d" % (page - 1)))
    if start + USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="NEXT ▶️", callback_data="admin:users:%d" % (page + 1)))
    if nav:
        m.add(*nav)
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="admin:main"))
    return m

def get_user_actions_kb(uid):
    m = InlineKeyboardMarkup(row_width=2)
    role = "admin:revoke_admin:%d" if is_admin(uid) else "admin:make_admin:%d"
    role_txt = "➖ REVOKE ADMIN" if is_admin(uid) else "➕ MAKE ADMIN"
    ban_txt = "✅ UNBAN" if is_banned(uid) else "🚫 BAN"
    m.add(InlineKeyboardButton(text=role_txt, callback_data=role % uid))
    m.add(InlineKeyboardButton(text=ban_txt, callback_data="admin:toggle_ban:%d" % uid))
    m.add(InlineKeyboardButton(text="✉️ SEND MSG", callback_data="admin:msg:%d" % uid))
    m.add(InlineKeyboardButton(text="📜 AUDIT", callback_data="admin:audit_user:%d" % uid))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="admin:users"))
    return m

def get_results_menu(sid, page, tp):
    m = InlineKeyboardMarkup(row_width=2)
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="◀️ PREV", callback_data="page:%s:%d" % (sid, page - 1)))
    if page < tp - 1:
        row.append(InlineKeyboardButton(text="NEXT ▶️", callback_data="page:%s:%d" % (sid, page + 1)))
    if row:
        m.add(*row)
    m.add(InlineKeyboardButton(text="📥 EXPORT CSV", callback_data="exp:%s" % sid))
    m.add(InlineKeyboardButton(text="🔙 BACK", callback_data="menu:main"))
    return m

# ═══════════════════════════════════════════════════════════════════════════════
#   HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

def register_handlers(dp):

    @dp.message_handler(commands=["start"])
    async def cmd_start(message, state):
        await state.finish()
        log_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        audit(message.from_user.id, "start")
        name = message.from_user.first_name or "User"
        text = (
            "%s <b>%s</b> %s\n\n"
            "➡️ <b>%s, %s! ❤️</b>\n\n"
            "👇 <b>%s</b>\n\n"
            "%s <i>Inline: <code>@Arbib_osint_bot username</code></i>"
        ) % (EMO_FIRE, sc("OSINT Master"), EMO_FIRE, sc("Welcome"), name,
             sc("Select A Category"), EMO_IDEA)
        await message.answer(text, reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

    @dp.message_handler(commands=["cancel"], state="*")
    async def cmd_cancel(message, state):
        await state.finish()
        await message.reply("%s <b>Cancelled.</b>" % EMO_CANCEL,
                            reply_markup=get_main_menu(message.from_user.id), parse_mode="HTML")

    @dp.message_handler(commands=["phone"])
    async def cmd_phone(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_phone(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="phone")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send phone number with country code.</b>\n\nExample: <code>+9779764706721</code>" % EMO_PHONE,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["ip"])
    async def cmd_ip(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_ip(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="ip")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the IP address.</b>" % EMO_LOCATION,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["domain"])
    async def cmd_domain(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_domain(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="domain")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the domain.</b>" % EMO_GLOBE,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["username"])
    async def cmd_username(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_username(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="username")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the username.</b>" % EMO_SEARCH,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["phone"])
    async def cmd_phone(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_phone(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="phone")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send phone number with country code.</b>\n\nExample: <code>+9779764706721</code>" % EMO_PHONE,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["ip"])
    async def cmd_ip(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_ip(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="ip")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the IP address.</b>" % EMO_LOCATION,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["domain"])
    async def cmd_domain(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_domain(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="domain")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the domain.</b>" % EMO_GLOBE,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.message_handler(commands=["username"])
    async def cmd_username(message, state):
        args = message.get_args()
        await state.finish()
        if args:
            try:
                await do_username(message, args.strip())
            except Exception as e:
                await message.reply("❌ <code>%s</code>" % str(e)[:200], parse_mode="HTML")
        else:
            await state.update_data(tool="username")
            await BotStates.wait_input.set()
            await message.reply("%s <b>Send the username.</b>" % EMO_SEARCH,
                                reply_markup=get_cancel(), parse_mode="HTML")

    @dp.callback_query_handler(lambda c: c.data == "menu:cancel", state="*")
    async def cb_cancel(call, state):
        await state.finish()
        await safe_edit(call.message, "👇 <b>%s</b>" % sc("Select A Category"),
                        reply_markup=get_main_menu(call.from_user.id), parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data == "menu:main")
    async def cb_main(call, state):
        await state.finish()
        await safe_edit(call.message, "👇 <b>%s</b>" % sc("Select A Category"),
                        reply_markup=get_main_menu(call.from_user.id), parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("cat:"))
    async def cb_cat(call):
        cat = call.data.split(":")[1]
        menus = {
            "recon": (get_recon_menu, "🔍 Recon"),
            "crypto": (get_crypto_menu, "🔐 Crypto"),
            "threat": (get_threat_menu, "🛡 Threat Intel"),
            "media": (get_media_menu, "📸 Media"),
            "games": (get_games_menu, "🎮 Games"),
            "util": (get_util_menu, "🔧 Utilities"),
            "fun": (get_fun_menu, "🎨 Fun"),
            "info": (get_info_menu, "📚 Info"),
        }
        if cat in menus:
            func, title = menus[cat]
            await safe_edit(call.message, "<b>%s</b>\n\nChoose a tool:" % title,
                            reply_markup=func(), parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("tool:"))
    async def cb_tool(call, state):
        tool = call.data.split(":")[1]
        prompts = {
            "username": (EMO_SEARCH, "Send the username."),
            "email": (EMO_EMAIL, "Send the email address."),
            "phone": (EMO_PHONE, "Send phone number with country code."),
            "domain": (EMO_GLOBE, "Send the domain."),
            "ip": (EMO_LOCATION, "Send the IP address."),
            "subdomain": (EMO_GLOBE, "Send the domain for subdomain enum."),
            "headers": (EMO_GLOBE, "Send the URL."),
            "wayback": (EMO_HISTORY, "Send the URL."),
            "reverse_ip": (EMO_GLOBE, "Send the IP."),
            "whois": (EMO_GLOBE, "Send the domain."),
            "dns_lookup": (EMO_GLOBE, "Send the domain."),
            "btc": (EMO_DOLLAR, "Send BTC address."),
            "eth": (EMO_DOLLAR, "Send ETH address."),
            "crypto_price": (EMO_DOLLAR, "Send symbol (bitcoin, ethereum, ton)."),
            "cve": (EMO_SHIELD, "Send CVE ID (CVE-2021-44228)."),
            "password_hibp": (EMO_KEY, "Send password."),
            "file_hash": (EMO_BOX, "Send MD5/SHA1/SHA256 hash."),
            "url_threat": (EMO_WARN, "Send URL."),
            "mac": (EMO_SEARCH, "Send MAC (aa:bb:cc:dd:ee:ff)."),
            "weather": (EMO_GLOBE, "Send city or lat,lon."),
            "currency": (EMO_DOLLAR, "Send base currency (USD)."),
            "wiki": (EMO_GLOBE, "Send search query."),
            "define": (EMO_BOX, "Send a word."),
            "book": (EMO_BOX, "Send book title."),
            "radio": (EMO_BOX, "Send station name."),
            "world_time": (EMO_HISTORY, "Send timezone (Europe/London)."),
            "country": (EMO_GLOBE, "Send country name."),
            "pokemon": (EMO_BOX, "Send Pokemon name."),
            "rick_morty": (EMO_BOX, "Send character ID (1-826)."),
            "star_wars": (EMO_BOX, "Send person ID (1-82)."),
            "anime": (EMO_BOX, "Send anime name."),
            "chess": (EMO_PROFILE, "Send chess.com username."),
            "steam": (EMO_PROFILE, "Send Steam vanity."),
            "github_user": (EMO_PROFILE, "Send GitHub username."),
            "npm": (EMO_BOX, "Send npm package name."),
            "pypi": (EMO_BOX, "Send PyPI package name."),
            "gender": (EMO_PROFILE, "Send a name."),
            "age": (EMO_PROFILE, "Send a name."),
            "nationality": (EMO_PROFILE, "Send a name."),
            "synonyms": (EMO_BOX, "Send a word."),
            "urban": (EMO_BOX, "Send a slang word."),
            "number_fact": (EMO_BOX, "Send a number."),
        }
        if tool in prompts:
            emo, prompt = prompts[tool]
            await state.finish()
            await state.update_data(tool=tool)
            await BotStates.wait_input.set()
            await safe_edit(call.message, "%s <b>%s</b>" % (emo, prompt),
                            reply_markup=get_cancel(), parse_mode="HTML")
        elif tool == "image":
            await BotStates.wait_image.set()
            await safe_edit(call.message, "%s <b>Send image to reverse-search.</b>" % EMO_IMAGE,
                            reply_markup=get_cancel(), parse_mode="HTML")
        elif tool == "exif":
            await BotStates.wait_exif.set()
            await safe_edit(call.message, "%s <b>Send image as FILE (document).</b>" % EMO_CAMERA,
                            reply_markup=get_cancel(), parse_mode="HTML")
        elif tool == "crypto_global":
            await do_crypto_global(call.message)
        elif tool == "crypto_trending":
            await do_crypto_trending(call.message)
        elif tool == "eth_gas":
            await do_eth_gas(call.message)
        elif tool == "btc_fees":
            await do_btc_fees(call.message)
        elif tool == "cve_recent":
            await do_cve_recent(call.message)
        elif tool == "fact":
            await do_fact(call.message)
        elif tool == "quote":
            await do_quote(call.message)
        elif tool == "joke":
            await do_joke(call.message)
        elif tool == "cat_pic":
            await do_cat_image(call.message)
        elif tool == "dog_pic":
            await do_dog_image(call.message)
        elif tool == "fox_pic":
            await do_fox_image(call.message)
        elif tool == "kanye":
            await do_kanye(call.message)
        elif tool == "yes_no":
            await do_yes_no(call.message)
        elif tool == "chuck":
            await do_chuck(call.message)
        elif tool == "advice":
            await do_advice(call.message)
        elif tool == "bored":
            await do_bored(call.message)
        elif tool == "trivia":
            await do_trivia(call.message)
        elif tool == "hackernews":
            await do_hackernews(call.message)
        await call.answer()

    @dp.message_handler(state=BotStates.wait_input)
    async def handle_input(message, state):
        data = await state.get_data()
        tool = data.get("tool")
        text = (message.text or "").strip()
        await state.finish()
        if not tool:
            return await message.reply("⚠️ Lost state. Send /start.", parse_mode="HTML")
        if not text:
            return await message.reply("⚠️ Send text, not image.", parse_mode="HTML")
        try:
            await _dispatch_tool(message, tool, text)
        except Exception as e:
            await message.reply("❌ Error in <b>%s</b>: <code>%s</code>" % (tool, str(e)[:200]), parse_mode="HTML")

    async def _dispatch_tool(message, tool, text):
        if tool == "username":
            await do_username(message, text)
        elif tool == "email":
            await do_email(message, text)
        elif tool == "phone":
            await do_phone(message, text)
        elif tool == "domain":
            await do_domain(message, text)
        elif tool == "ip":
            await do_ip(message, text)
        elif tool == "subdomain":
            await do_subdomain(message, text)
        elif tool == "headers":
            await do_headers(message, text)
        elif tool == "wayback":
            await do_wayback(message, text)
        elif tool == "reverse_ip":
            await do_reverse_ip(message, text)
        elif tool == "whois":
            await do_whois(message, text)
        elif tool == "dns_lookup":
            await do_dns_lookup(message, text)
        elif tool == "btc":
            await do_btc(message, text)
        elif tool == "eth":
            await do_eth(message, text)
        elif tool == "crypto_price":
            await do_crypto_price(message, text)
        elif tool == "cve":
            await do_cve(message, text)
        elif tool == "password_hibp":
            await do_password_hibp(message, text)
        elif tool == "file_hash":
            await do_file_hash(message, text)
        elif tool == "url_threat":
            await do_url_threat(message, text)
        elif tool == "mac":
            await do_mac(message, text)
        elif tool == "weather":
            await do_weather(message, text)
        elif tool == "currency":
            await do_currency(message, text)
        elif tool == "wiki":
            await do_wiki(message, text)
        elif tool == "define":
            await do_define(message, text)
        elif tool == "book":
            await do_book(message, text)
        elif tool == "radio":
            await do_radio(message, text)
        elif tool == "world_time":
            await do_world_time(message, text)
        elif tool == "country":
            await do_country(message, text)
        elif tool == "pokemon":
            await do_pokemon(message, text)
        elif tool == "rick_morty":
            await do_rick_morty(message, text)
        elif tool == "star_wars":
            await do_star_wars(message, text)
        elif tool == "anime":
            await do_anime(message, text)
        elif tool == "chess":
            await do_chess(message, text)
        elif tool == "steam":
            await do_steam(message, text)
        elif tool == "github_user":
            await do_github_user(message, text)
        elif tool == "npm":
            await do_npm(message, text)
        elif tool == "pypi":
            await do_pypi(message, text)
        elif tool == "gender":
            await do_gender(message, text)
        elif tool == "age":
            await do_age(message, text)
        elif tool == "nationality":
            await do_nationality(message, text)
        elif tool == "synonyms":
            await do_synonyms(message, text)
        elif tool == "urban":
            await do_urban(message, text)
        elif tool == "number_fact":
            await do_number_fact(message, text)

    @dp.message_handler(state=BotStates.wait_image, content_types=types.ContentType.PHOTO)
    async def handle_image(message, state):
        await state.finish()
        await do_reverse_image(message)

    @dp.message_handler(state=BotStates.wait_exif, content_types=types.ContentType.DOCUMENT)
    async def handle_exif(message, state):
        await state.finish()
        await do_exif(message)

    @dp.callback_query_handler(lambda c: c.data.startswith("page:"))
    async def cb_page(call):
        _, sid, pg = call.data.split(":")
        await show_page(call.message, sid, int(pg))
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data.startswith("exp:"))
    async def cb_exp(call):
        sid = call.data.split(":")[1]
        hits = SCAN_CACHE.get(sid, [])
        if not hits:
            return await call.answer("Expired.")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Site", "URL", "Username", "Enrichment"])
        for h in hits:
            w.writerow([h["site"], h["url"], h["username"], h.get("enrich", "")])
        doc = InputFile(io.BytesIO(out.getvalue().encode("utf-8")), filename="results_%s.csv" % sid)
        await call.message.answer_document(doc, caption="📥 Exported.")
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data == "menu:help")
    async def cb_help(call):
        text = (
            "%s <b>%s</b>\n\n"
            "• <b>Username</b> — 40+ sites\n"
            "• <b>Email</b> — MX + Gravatar\n"
            "• <b>Phone</b> — carrier/region/type\n"
            "• <b>Domain</b> — DNS + WHOIS\n"
            "• <b>IP</b> — geo + rDNS + map\n"
            "• <b>Subdomains</b> — CRT.sh\n"
            "• <b>Headers</b> — tech + security\n"
            "• <b>Wayback</b> — archived\n"
            "• <b>Reverse IP</b> — co-hosted\n"
            "• <b>BTC / ETH</b> — wallet intel\n"
            "• <b>Crypto price/global/trending</b>\n"
            "• <b>CVE / Recent / Password / Hash / URL</b>\n"
            "• <b>Weather / Currency / Wiki / Books</b>\n"
            "• <b>Pokemon / Anime / Star Wars</b>\n"
            "• <b>GitHub / npm / PyPI</b>\n"
            "• <b>Gender / Age / Nationality</b>\n"
            "• <b>Quotes / Facts / Jokes / Cats / Dogs</b>"
        ) % (EMO_WRENCH, sc("Tools"))
        await safe_edit(call.message, text, reply_markup=get_main_menu(call.from_user.id), parse_mode="HTML")
        await call.answer()

    @dp.callback_query_handler(lambda c: c.data == "menu:profile")
    async def cb_profile(call):
        role = ("%s Admin" % EMO_CROWN) if is_admin(call.from_user.id) else ("%s User" % EMO_PROFILE)
        await safe_edit(call.message,
            "%s <b>Profile</b>\n\n<b>ID:</b> <code>%d</code>\n<b>Role:</b> %s" % (EMO_PROFILE, call.from_user.id, role),
            reply_markup=get_main_menu(call.from_user.id), parse_mode="HTML")
        await call.answer()

    @dp.inline_handler()
    async def inline_scan(inline_query):
        target = inline_query.query.strip()
        if not USERNAME_RE.match(target):
            try:
                await inline_query.answer([], cache_time=5)
            except Exception:
                pass
            return
        sites = dict(BASE_SITES)
        sites.update(get_custom_sites())
        sem = asyncio.Semaphore(40)
        async def _c(sess, n, s, u):
            async with sem:
                url = s["url"].format(u=u)
                try:
                    async with sess.get(url, timeout=aiohttp.ClientTimeout(total=4)) as r:
                        if r.status in (404, 410):
                            return None
                        if not (200 <= r.status < 300):
                            return None
                        t = (await r.content.read(64 * 1024)).decode("utf-8", "ignore").lower()
                        if s.get("miss") and any(m in t for m in s["miss"]):
                            return None
                        if s.get("hit") and not any(h in t for h in s["hit"]):
                            return None
                        return {"site": n, "url": url}
                except Exception:
                    return None
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": UA}) as sess:
                raw = await asyncio.gather(*[_c(sess, n, s, target) for n, s in sites.items()])
        except Exception:
            raw = []
        hits = [r for r in raw if r]
        res = []
        for i, h in enumerate(hits[:10]):
            res.append(types.InlineQueryResultArticle(
                id="%s_%d" % (h["site"], i),
                title=h["site"],
                description=h["url"],
                input_message_content=types.InputTextMessageContent(
                    message_text="<b>%s</b>: %s" % (h["site"], h["url"]),
                    parse_mode="HTML"
                )
            ))
        if not res:
            res.append(types.InlineQueryResultArticle(
                id="fb",
                title="Scan @%s in bot" % target,
                description="Open bot for deep scan",
                input_message_content=types.InputTextMessageContent(
                    message_text="@%s — full scan in @Arbib_osint_bot" % target,
                    parse_mode="HTML"
                )
            ))
        try:
            await inline_query.answer(res, cache_time=60, is_personal=True)
        except Exception:
            pass

    # ═══════════ ADMIN ═══════════
    @dp.callback_query_handler(lambda c: c.data.startswith("admin:"))
    async def cb_admin(call, state):
        if not is_admin(call.from_user.id):
            return await call.answer("Denied", show_alert=True)
        parts = call.data.split(":")
        action = parts[1]

        if action == "main":
            await state.finish()
            await safe_edit(call.message, "%s <b>Admin Panel</b>" % EMO_CROWN,
                            reply_markup=get_admin_menu(), parse_mode="HTML")
            await call.answer()
        elif action == "users":
            page = int(parts[2]) if len(parts) > 2 else 0
            await safe_edit(call.message, "👥 <b>User List</b> (page %d)" % (page + 1),
                            reply_markup=get_user_list_kb(page), parse_mode="HTML")
            await call.answer()
        elif action == "user":
            uid = int(parts[2])
            user = get_user(uid)
            if not user:
                return await call.answer("User not found.")
            u_id, uname, fname, last = user
            role = "👑 Admin" if is_admin(uid) else "👤 User"
            banned = "🚫 Banned" if is_banned(uid) else "✅ Clean"
            text = (
                "%s <b>%s</b>\n\n"
                "Username: @%s\n"
                "ID: <code>%d</code>\n"
                "Role: %s\n"
                "Status: %s\n"
                "Last seen: %s"
            ) % (EMO_PROFILE, fname or uname or str(uid), uname or "none", uid, role, banned, fmt_ts(last))
            await safe_edit(call.message, text, reply_markup=get_user_actions_kb(uid), parse_mode="HTML")
            await call.answer()
        elif action == "make_admin":
            uid = int(parts[2])
            with closing(sqlite3.connect(DB_PATH)) as conn:
                conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
                conn.commit()
            audit(call.from_user.id, "make_admin", str(uid))
            await call.answer("Admin added.", show_alert=True)
            await safe_edit(call.message, "✅ <b>%d is now admin.</b>" % uid,
                            reply_markup=get_admin_menu(), parse_mode="HTML")
        elif action == "revoke_admin":
            uid = int(parts[2])
            if uid == SUPER_ADMIN_ID:
                return await call.answer("Cannot revoke super admin.", show_alert=True)
            with closing(sqlite3.connect(DB_PATH)) as conn:
                conn.execute("DELETE FROM admins WHERE user_id=?", (uid,))
                conn.commit()
            audit(call.from_user.id, "revoke_admin", str(uid))
            await call.answer("Admin revoked.", show_alert=True)
            await safe_edit(call.message, "✅ <b>%d is no longer admin.</b>" % uid,
                            reply_markup=get_admin_menu(), parse_mode="HTML")
        elif action == "toggle_ban":
            uid = int(parts[2])
            with closing(sqlite3.connect(DB_PATH)) as conn:
                exists = conn.execute("SELECT 1 FROM bans WHERE user_id=?", (uid,)).fetchone()
                if exists:
                    conn.execute("DELETE FROM bans WHERE user_id=?", (uid,))
                    msg = "✅ Unbanned."
                else:
                    conn.execute("INSERT OR IGNORE INTO bans (user_id, reason, banned_at) VALUES (?, ?, ?)",
                                 (uid, "admin_action", datetime.now(timezone.utc).isoformat()))
                    msg = "🚫 Banned."
                conn.commit()
            audit(call.from_user.id, "toggle_ban", str(uid))
            await call.answer(msg, show_alert=True)
            await safe_edit(call.message, "%s <b>User %d status updated.</b>" % (EMO_CHECK, uid),
                            reply_markup=get_admin_menu(), parse_mode="HTML")
        elif action == "msg":
            uid = int(parts[2])
            await BotStates.admin_wait_message.set()
            await state.update_data(target_uid=uid)
            await safe_edit(call.message, "✉️ <b>Send the message for user %d</b>" % uid,
                            reply_markup=get_cancel(), parse_mode="HTML")
            await call.answer()
        elif action == "audit":
            with closing(sqlite3.connect(DB_PATH)) as conn:
                rows = conn.execute("SELECT a.user_id, u.first_name, u.username, a.action, a.details, a.timestamp FROM audit_log a LEFT JOIN users u ON a.user_id = u.user_id ORDER BY a.id DESC LIMIT 20").fetchall()
            text = "📜 <b>Recent Audit Log</b>\n\n"
            for r in rows:
                name = r[1] or r[2] or str(r[0])
                text += "• <b>%s</b> — %s — %s\n" % (name, r[3], fmt_ts(r[5]))
            await safe_edit(call.message, text[:4000], reply_markup=get_admin_menu(), parse_mode="HTML")
            await call.answer()
        elif action == "audit_user":
            uid = int(parts[2])
            with closing(sqlite3.connect(DB_PATH)) as conn:
                rows = conn.execute("SELECT action, details, timestamp FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
            text = "📜 <b>Audit for %d</b>\n\n" % uid
            if rows:
                for r in rows:
                    text += "• %s — %s (%s)\n" % (r[0], str(r[1])[:40], fmt_ts(r[2]))
            else:
                text += "No actions."
            await safe_edit(call.message, text[:4000], reply_markup=get_user_actions_kb(uid), parse_mode="HTML")
            await call.answer()
        elif action == "maint":
            new = "1" if get_setting("maintenance") == "0" else "0"
            set_setting("maintenance", new)
            audit(call.from_user.id, "toggle_maintenance", new)
            await safe_edit(call.message, "%s <b>Maintenance: %s</b>" % (EMO_WRENCH, new),
                            reply_markup=get_admin_menu(), parse_mode="HTML")
            await call.answer()
        elif action == "stats":
            with closing(sqlite3.connect(DB_PATH)) as conn:
                u = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                s = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
                a = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            text = "%s <b>Stats</b>\n\nUsers: %d\nScans: %d\nAudit entries: %d" % (EMO_STATS, u, s, a)
            await safe_edit(call.message, text, reply_markup=get_admin_menu(), parse_mode="HTML")
            await call.answer()
        elif action == "broadcast":
            await BotStates.admin_wait_broadcast.set()
            await safe_edit(call.message, "📢 <b>Send the broadcast message</b>",
                            reply_markup=get_cancel(), parse_mode="HTML")
            await call.answer()
        elif action == "addsite":
            await BotStates.admin_wait_site.set()
            await safe_edit(call.message, "🌐 <b>Format:</b>\n<code>Name|https://site.com/{u}|miss|hit</code>",
                            reply_markup=get_cancel(), parse_mode="HTML")
            await call.answer()

    @dp.message_handler(state=BotStates.admin_wait_message)
    async def admin_msg(message, state):
        data = await state.get_data()
        target = data.get("target_uid")
        await state.finish()
        if not target:
            return await message.reply("❌ No target.")
        try:
            await message.copy_to(target)
            audit(message.from_user.id, "send_msg", str(target))
            await message.reply("✅ Sent to %d." % target, reply_markup=get_admin_menu(), parse_mode="HTML")
        except Exception:
            await message.reply("❌ Failed.", reply_markup=get_admin_menu(), parse_mode="HTML")

    @dp.message_handler(state=BotStates.admin_wait_broadcast)
    async def admin_broadcast(message, state):
        await state.finish()
        users = [r[0] for r in sqlite3.connect(DB_PATH).execute("SELECT user_id FROM users").fetchall()]
        msg = await message.reply("⏳ Broadcasting to %d..." % len(users))
        ok = 0
        for uid in users:
            try:
                await message.copy_to(uid)
                ok += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        audit(message.from_user.id, "broadcast", str(ok))
        await safe_edit(msg, "%s Sent %d." % (EMO_CHECK, ok), reply_markup=get_admin_menu(), parse_mode="HTML")

    @dp.message_handler(state=BotStates.admin_wait_site)
    async def admin_site(message, state):
        await state.finish()
        parts = message.text.split("|")
        if len(parts) != 4:
            return await message.reply("%s Invalid format." % EMO_CROSS,
                                       reply_markup=get_admin_menu(), parse_mode="HTML")
        name, url, miss, hit = parts
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute("INSERT INTO custom_sites (name, url, miss, hit) VALUES (?, ?, ?, ?)",
                         (name, url, miss, hit))
            conn.commit()
        audit(message.from_user.id, "add_site", name)
        await message.reply("%s Added %s." % (EMO_CHECK, name),
                            reply_markup=get_admin_menu(), parse_mode="HTML")

# ═══════════════════════════════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
    dp = Dispatcher(bot, storage=MemoryStorage())

    @dp.errors_handler(exception=MessageNotModified)
    async def _ignore(update, exception):
        return True

    dp.middleware.setup(SecurityMiddleware())
    register_handlers(dp)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    import signal, threading
    def _shutdown():
        print("auto-shutdown after 5h45m — GH Actions will restart in ~15m")
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Timer(5 * 3600 + 45 * 60, _shutdown).start()
    print("Bot is starting...")
    executor.start_polling(dp, skip_updates=True)
