import asyncio
import aiosqlite
import random
import logging
import sys
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, BufferedInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_IDS, DB_PATH

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, rolls INTEGER DEFAULT 2, diamonds INTEGER DEFAULT 0, total_rolls INTEGER DEFAULT 0, fortune_spins INTEGER DEFAULT 1, event_rolls INTEGER DEFAULT 0, event_guarantor INTEGER DEFAULT 0, bonus_roll_received BOOLEAN DEFAULT 0, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1, banned BOOLEAN DEFAULT 0, login_streak INTEGER DEFAULT 0, last_login TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT DEFAULT '', file_id TEXT, rarity TEXT DEFAULT 'R', is_L_card BOOLEAN DEFAULT 0, is_event_card BOOLEAN DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER, quantity INTEGER DEFAULT 1, is_original BOOLEAN DEFAULT 1, PRIMARY KEY (user_id, card_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (user_id INTEGER, task_id INTEGER, task_type TEXT, task_target INTEGER DEFAULT 1, progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT 0, date TEXT, PRIMARY KEY (user_id, task_id, date))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS weekly_tasks (user_id INTEGER, task_id INTEGER, task_type TEXT, task_target INTEGER DEFAULT 1, progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT 0, reward_claimed BOOLEAN DEFAULT 0, week_start TEXT, PRIMARY KEY (user_id, task_id, week_start))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS achievements (user_id INTEGER, achievement_id TEXT, completed BOOLEAN DEFAULT 0, reward_claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, achievement_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS market (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, card_id INTEGER, price INTEGER, quantity INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS auctions (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, card_id INTEGER, start_price INTEGER, current_price INTEGER, current_bidder_id INTEGER, end_time TIMESTAMP, status TEXT DEFAULT 'active')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guilds (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, owner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_members (guild_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id, user_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_join_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, status TEXT DEFAULT 'pending')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_seasons (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'pending', started_at TIMESTAMP, ended_at TIMESTAMP, card_selection_end TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_points (guild_id INTEGER, user_id INTEGER, points INTEGER DEFAULT 0, season_id INTEGER, PRIMARY KEY (guild_id, user_id, season_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_cards (season_id INTEGER, guild_id INTEGER, user_id INTEGER, card_id INTEGER, PRIMARY KEY (season_id, guild_id, user_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_votes (guild_id INTEGER, user_id INTEGER, vote TEXT, season_id INTEGER, PRIMARY KEY (guild_id, user_id, season_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS duels (id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_card_id INTEGER, opponent_card_id INTEGER, bet_type TEXT DEFAULT 'diamond', bet_amount INTEGER DEFAULT 1, status TEXT DEFAULT 'pending', winner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS duel_stats (user_id INTEGER PRIMARY KEY, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS friends (user_id INTEGER, friend_id INTEGER, status TEXT DEFAULT 'pending', PRIMARY KEY (user_id, friend_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, type TEXT, value INTEGER, uses_left INTEGER, created_by INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS level_rewards (user_id INTEGER, level INTEGER, claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, level))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS card_decks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS deck_cards (deck_id INTEGER, card_id INTEGER, PRIMARY KEY (deck_id, card_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS active_events (id INTEGER PRIMARY KEY AUTOINCREMENT, deck_id INTEGER, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP, status TEXT DEFAULT 'active')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS daily_login (user_id INTEGER, date TEXT, PRIMARY KEY (user_id, date))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS boosters (user_id INTEGER, type TEXT, multiplier REAL, ends_at TIMESTAMP, PRIMARY KEY (user_id, type))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        defaults = {
            'morning_rolls':'2','morning_diamonds':'3','morning_fortune':'1','morning_event':'1',
            'evening_rolls':'2','evening_diamonds':'3','evening_fortune':'1','evening_event':'1',
            'break_R':'1','break_SR':'5','break_SSR':'10','break_L':'20',
            'rate_R':'70','rate_SR':'20','rate_SSR':'8','rate_L':'2',
            'event_rate_L':'2','guarantor_limit':'50'
        }
        for key, value in defaults.items(): await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()
        logger.info("✅ БД готова")

# ==================== НАСТРОЙКИ ====================
async def get_setting(key, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default

async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        await db.commit()

async def get_setting_int(key, default=0):
    val = await get_setting(key)
    return int(val) if val else default

async def get_break_price(rarity):
    default_prices = {'R': 1, 'SR': 5, 'SSR': 10, 'L': 20}
    custom = await get_setting(f'break_{rarity}')
    if custom and int(custom) > 0: return int(custom)
    return default_prices.get(rarity, 1)

# ==================== БУСТЕРЫ ====================
async def get_booster(uid, btype):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM boosters WHERE user_id=? AND type=? AND ends_at > datetime('now')", (uid, btype)) as c:
            return await c.fetchone()

async def buy_booster(uid, btype, hours, cost):
    u = await get_user(uid)
    if u['diamonds'] < cost: return False
    await upd_diamonds(uid, -cost)
    ends = datetime.now() + timedelta(hours=hours)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO boosters (user_id, type, multiplier, ends_at) VALUES (?,?,?,?)", (uid, btype, 1.5, ends))
        await db.commit()
    return True

# ==================== ЕЖЕДНЕВНЫЙ ВХОД ====================
async def check_daily_login(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM daily_login WHERE user_id=? AND date=?", (uid, today)) as c:
            if not await c.fetchone():
                await db.execute("INSERT INTO daily_login VALUES (?,?)", (uid, today))
                user = await get_user(uid)
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                if user['last_login'] == yesterday: streak = user['login_streak'] + 1
                else: streak = 1
                await db.execute("UPDATE users SET login_streak=?, last_login=? WHERE user_id=?", (streak, today, uid))
                await db.commit()
                return True, streak
    return False, 0

# ==================== СОСТОЯНИЯ FSM ====================
class AddCardStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_rarity = State()
    waiting_for_photo = State()

class EditCardStates(StatesGroup):
    waiting_for_value = State()

class BreakCustomStates(StatesGroup):
    waiting_for_quantity = State()

class BroadcastStates(StatesGroup):
    waiting_for_broadcast = State()

class GiveAllStates(StatesGroup):
    waiting_for_amount = State()

class AuctionStates(StatesGroup):
    waiting_for_bid = State()

class PromoStates(StatesGroup):
    waiting_for_code = State()

class EventStates(StatesGroup):
    waiting_for_deck_name = State()

# ==================== ФУНКЦИИ БД ====================
async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as c:
            return await c.fetchone()

async def get_user_by_username(username):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE username=?", (username,)) as c:
            return await c.fetchone()

async def create_user(uid, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id,username) VALUES (?,?)", (uid, name))
        await db.commit()

async def add_xp(uid, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (amount, uid))
        await db.commit()
        user = await get_user(uid)
        xp, level = user['xp'], user['level']
        xp_needed = level * 100 + 50
        levels_gained = 0
        while xp >= xp_needed:
            xp -= xp_needed; level += 1; levels_gained += 1
            xp_needed = level * 100 + 50
        if levels_gained > 0:
            await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (xp, level, uid))
            await db.commit()
            for l in range(level - levels_gained + 1, level + 1):
                await db.execute("INSERT OR IGNORE INTO level_rewards (user_id, level) VALUES (?,?)", (uid, l))
            await db.commit()
            return levels_gained, level
    return 0, user['level']

async def get_level_rewards(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM level_rewards WHERE user_id=? AND claimed=0 ORDER BY level", (uid,)) as c:
            return await c.fetchall()

async def claim_level_reward(uid, level):
    rewards = {2:{'rolls':1},3:{'diamonds':2},4:{'rolls':1,'diamonds':1},5:{'event_rolls':1},6:{'rolls':2},7:{'diamonds':3},8:{'rolls':1,'event_rolls':1},9:{'diamonds':5},10:{'rolls':3,'diamonds':3,'event_rolls':1}}
    if level > 10 and level % 5 == 0: rewards[level] = {'rolls':level//2,'diamonds':level,'event_rolls':level//5}
    if level not in rewards: return None
    r = rewards[level]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT claimed FROM level_rewards WHERE user_id=? AND level=?", (uid, level)) as c:
            row = await c.fetchone()
            if row and row[0]: return None
        if 'rolls' in r: await upd_rolls(uid, r['rolls'])
        if 'diamonds' in r: await upd_diamonds(uid, r['diamonds'])
        if 'event_rolls' in r: await upd_event_rolls(uid, r['event_rolls'])
        await db.execute("UPDATE level_rewards SET claimed=1 WHERE user_id=? AND level=?", (uid, level))
        await db.commit()
    return r

async def log_action(uid, action, details=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO activity_log (user_id, action, details) VALUES (?,?,?)", (uid, action, details))
        await db.commit()

async def get_all_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards ORDER BY id") as c:
            return await c.fetchall()

async def get_regular_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards WHERE is_event_card=0 AND is_L_card=0 ORDER BY id") as c:
            return await c.fetchall()

async def get_event_cards():
    cards = await get_event_cards_active()
    if cards: return cards
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards WHERE is_event_card=1 ORDER BY id") as c:
            return await c.fetchall()

async def get_card_by_id(card_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards WHERE id=?", (card_id,)) as c:
            return await c.fetchone()

async def add_card_to_user(uid, cid, is_original=False):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_original FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid)) as c:
            ex = await c.fetchone()
        if ex: await db.execute("UPDATE user_cards SET quantity=quantity+1 WHERE user_id=? AND card_id=?", (uid, cid))
        else: await db.execute("INSERT INTO user_cards (user_id,card_id,quantity,is_original) VALUES (?,?,1,?)", (uid, cid, is_original))
        await db.commit()

async def upd_rolls(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rolls=rolls+?, total_rolls=total_rolls+? WHERE user_id=?", (d, abs(d), uid))
        await db.commit()

async def upd_diamonds(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET diamonds=diamonds+? WHERE user_id=?", (d, uid))
        await db.commit()

async def upd_fortune_spins(uid, s):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET fortune_spins=? WHERE user_id=?", (s, uid))
        await db.commit()

async def upd_event_rolls(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET event_rolls=event_rolls+? WHERE user_id=?", (d, uid))
        await db.commit()

async def upd_event_guarantor(uid, p):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET event_guarantor=? WHERE user_id=?", (p, uid))
        await db.commit()

async def get_user_cards(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc JOIN cards c ON uc.card_id=c.id WHERE uc.user_id=? AND uc.quantity>0 ORDER BY c.id""", (uid,)) as c:
            return await c.fetchall()

async def get_user_card(uid, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc JOIN cards c ON uc.card_id=c.id WHERE uc.user_id=? AND uc.card_id=?""", (uid, cid)) as c:
            return await c.fetchone()

async def remove_card(uid, cid, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT quantity, is_original FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid)) as c:
            row = await c.fetchone()
        if not row: return False, "Карта не найдена"
        cq, io = row[0], row[1]
        if io and cq <= qty: return False, "❌ Нельзя удалить оригинал!"
        if cq >= qty:
            nq = cq - qty
            if nq <= 0: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
            else: await db.execute("UPDATE user_cards SET quantity=? WHERE user_id=? AND card_id=?", (nq, uid, cid))
            await db.commit()
            return True, None
        return False, "Недостаточно карт"

async def get_card_count(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT SUM(quantity) FROM user_cards WHERE user_id=?", (uid,)) as c:
            row = await c.fetchone()
            return row[0] or 0

async def get_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT u.user_id, u.username, SUM(uc.quantity) as total FROM users u LEFT JOIN user_cards uc ON u.user_id=uc.user_id GROUP BY u.user_id HAVING total>0 ORDER BY total DESC LIMIT ?""", (limit,)) as c:
            return await c.fetchall()

async def get_level_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, username, level, xp FROM users ORDER BY level DESC, xp DESC LIMIT ?", (limit,)) as c:
            return await c.fetchall()

async def get_duel_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT ds.user_id, u.username, ds.wins, ds.losses FROM duel_stats ds JOIN users u ON ds.user_id=u.user_id ORDER BY ds.wins DESC LIMIT ?", (limit,)) as c:
            return await c.fetchall()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            return await c.fetchall()

# ==================== ДУЭЛИ (СТАТИСТИКА) ====================
async def update_duel_stats(uid, is_win):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO duel_stats (user_id, wins, losses) VALUES (?,0,0)", (uid,))
        if is_win: await db.execute("UPDATE duel_stats SET wins=wins+1 WHERE user_id=?", (uid,))
        else: await db.execute("UPDATE duel_stats SET losses=losses+1 WHERE user_id=?", (uid,))
        await db.commit()

async def get_duel_stats(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM duel_stats WHERE user_id=?", (uid,)) as c:
            return await c.fetchone()

# ==================== ЗАДАНИЯ ====================
TASK_TYPES = [
    {"type":"roll","desc":"🎲 Прокрутить один раз","target":1},
    {"type":"profile","desc":"👤 Зайти в профиль","target":1},
    {"type":"break","desc":"🔨 Разбить повторку","target":1},
    {"type":"fortune","desc":"🎡 Крутануть колесо","target":1},
    {"type":"event_roll","desc":"🎪 Ивент-крутка","target":1},
]

WEEKLY_TASK_TYPES = [
    {"type":"weekly_rolls","desc":"🎲 Сделать 20 круток","target":20},
    {"type":"weekly_ssr","desc":"🟣 Выбить 3 SSR","target":3},
    {"type":"weekly_break","desc":"🔨 Разбить 10 повторов","target":10},
    {"type":"weekly_fortune","desc":"🎡 Колесо 5 раз","target":5},
]

async def has_duplicates(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=? AND quantity>1", (uid,)) as c:
            return (await c.fetchone())[0] > 0

async def has_ssr_cards_available(uid, needed=3):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM cards WHERE rarity='SSR' AND is_L_card=0") as c:
            return (await c.fetchone())[0] >= needed

async def is_event_active():
    event = await get_active_event()
    if event: return True
    cards = await get_event_cards()
    return len(cards) > 0

async def get_available_task_types(uid):
    available = []
    for task in TASK_TYPES:
        if task['type'] == 'break':
            if await has_duplicates(uid): available.append(task)
        elif task['type'] == 'event_roll':
            if await is_event_active(): available.append(task)
        else: available.append(task)
    return available

async def get_available_weekly_task_types(uid):
    available = []
    for task in WEEKLY_TASK_TYPES:
        if task['type'] == 'weekly_break':
            if await has_duplicates(uid): available.append(task)
        elif task['type'] == 'weekly_ssr':
            if await has_ssr_cards_available(uid): available.append(task)
        else: available.append(task)
    return available

async def ensure_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
            if (await c.fetchone())[0] == 0:
                available = await get_available_task_types(uid)
                if len(available) < 2: available = [t for t in TASK_TYPES if t['type'] not in ['break','event_roll']]
                selected = random.sample(available, min(2, len(available)))
                for i, t in enumerate(selected):
                    await db.execute("INSERT INTO daily_tasks (user_id,task_id,task_type,task_target,date) VALUES (?,?,?,?,?)", (uid, i, t['type'], t['target'], today))
                await db.commit()

async def ensure_weekly_tasks(uid):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, ws)) as c:
            if (await c.fetchone())[0] == 0:
                available = await get_available_weekly_task_types(uid)
                if len(available) < 3:
                    fallback = [{"type":"weekly_rolls","desc":"🎲 20 круток","target":20},{"type":"weekly_fortune","desc":"🎡 Колесо 5 раз","target":5}]
                    available = fallback + [t for t in available if t['type'] not in ['weekly_rolls','weekly_fortune']]
                    available = available[:3]
                selected = random.sample(available, min(3, len(available)))
                for i, t in enumerate(selected):
                    await db.execute("INSERT INTO weekly_tasks (user_id,task_id,task_type,task_target,week_start) VALUES (?,?,?,?,?)", (uid, i, t['type'], t['target'], ws))
                await db.commit()

async def get_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    await ensure_daily_tasks(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
            return await c.fetchall()

async def get_weekly_tasks(uid):
    await ensure_weekly_tasks(uid)
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, ws)) as c:
            return await c.fetchall()

async def update_task_progress(uid, tt):
    date = datetime.now().strftime("%Y-%m-%d")
    await ensure_daily_tasks(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE daily_tasks SET progress=progress+1 WHERE user_id=? AND task_type=? AND date=? AND completed=0 AND progress<task_target", (uid, tt, date))
        await db.execute("UPDATE daily_tasks SET completed=1 WHERE user_id=? AND task_type=? AND date=? AND progress>=task_target", (uid, tt, date))
        await db.commit()

async def update_weekly_progress(uid, tt):
    await ensure_weekly_tasks(uid)
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE weekly_tasks SET progress=progress+1 WHERE user_id=? AND task_type=? AND week_start=? AND completed=0 AND progress<task_target", (uid, tt, ws))
        await db.execute("UPDATE weekly_tasks SET completed=1 WHERE user_id=? AND task_type=? AND week_start=? AND progress>=task_target", (uid, tt, ws))
        await db.commit()

async def check_all_tasks_completed(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) as t, SUM(completed) as d FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
            row = await c.fetchone()
            return row[0] >= 2 and row[1] == row[0]

async def give_bonus_roll(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        u = await get_user(uid)
        if not u['bonus_roll_received']:
            await db.execute("UPDATE users SET bonus_roll_received=1 WHERE user_id=?", (uid,))
            await db.execute("UPDATE users SET rolls=rolls+1 WHERE user_id=?", (uid,))
            await db.commit()
            return True
    return False

# ==================== ДОСТИЖЕНИЯ ====================
ACHIEVEMENTS = [
    {"id":"cards_10","name":"Начинающий коллекционер","desc":"Собрать 10 карт","icon":"📚","reward":{"diamonds":5}},
    {"id":"cards_50","name":"Опытный коллекционер","desc":"Собрать 50 карт","icon":"📚","reward":{"diamonds":10,"rolls":3}},
    {"id":"cards_100","name":"Мастер","desc":"Собрать 100 карт","icon":"📚","reward":{"diamonds":25,"rolls":5,"event_rolls":2}},
    {"id":"rolls_100","name":"Крутильщик","desc":"100 круток","icon":"🎲","reward":{"rolls":10}},
    {"id":"l_cards_1","name":"Первая L-карта","desc":"Получить L","icon":"🌟","reward":{"diamonds":20,"event_rolls":3}},
    {"id":"level_5","name":"Опытный игрок","desc":"5 уровень","icon":"⭐","reward":{"diamonds":5}},
    {"id":"level_10","name":"Мастер","desc":"10 уровень","icon":"⭐","reward":{"diamonds":10,"rolls":5}},
    {"id":"level_20","name":"Легенда","desc":"20 уровень","icon":"⭐","reward":{"diamonds":30,"rolls":10,"event_rolls":5}},
]

async def check_achievements(uid):
    u = await get_user(uid)
    cards = await get_user_cards(uid)
    tc = sum(c['quantity'] for c in cards)
    lc = sum(c['quantity'] for c in cards if c['is_L_card'])
    new_ach = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            completed = False
            if ach['id'] == 'cards_10' and tc >= 10: completed = True
            elif ach['id'] == 'cards_50' and tc >= 50: completed = True
            elif ach['id'] == 'cards_100' and tc >= 100: completed = True
            elif ach['id'] == 'rolls_100' and u['total_rolls'] >= 100: completed = True
            elif ach['id'] == 'l_cards_1' and lc >= 1: completed = True
            elif ach['id'] == 'level_5' and u['level'] >= 5: completed = True
            elif ach['id'] == 'level_10' and u['level'] >= 10: completed = True
            elif ach['id'] == 'level_20' and u['level'] >= 20: completed = True
            if not completed: continue
            async with db.execute("SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach['id'])) as c:
                row = await c.fetchone()
                if not row or not row[0]:
                    await db.execute("INSERT OR REPLACE INTO achievements (user_id, achievement_id, completed, reward_claimed) VALUES (?,?,1,0)", (uid, ach['id']))
                    await db.commit()
                    new_ach.append(ach)
    return new_ach

async def claim_achievement_reward(uid, ach_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach_id)) as c:
            row = await c.fetchone()
            if row and row[0]: return None
        ach = next((a for a in ACHIEVEMENTS if a['id'] == ach_id), None)
        if not ach or 'reward' not in ach: return None
        r = ach['reward']
        if 'diamonds' in r: await upd_diamonds(uid, r['diamonds'])
        if 'rolls' in r: await upd_rolls(uid, r['rolls'])
        if 'event_rolls' in r: await upd_event_rolls(uid, r['event_rolls'])
        await db.execute("UPDATE achievements SET reward_claimed=1 WHERE user_id=? AND achievement_id=?", (uid, ach_id))
        await db.commit()
    return r

# ==================== БИРЖА И АУКЦИОНЫ ====================
async def create_market_listing(sid, cid, price, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO market (seller_id,card_id,price,quantity) VALUES (?,?,?,?)", (sid, cid, price, qty))
        await db.commit()

async def get_market_listings(card_id=None, rarity=None, page=0, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT m.*, c.name, c.rarity, c.is_L_card, c.file_id FROM market m JOIN cards c ON m.card_id=c.id WHERE 1=1"
        params = []
        if card_id: query += " AND m.card_id=?"; params.append(card_id)
        if rarity: query += " AND c.rarity=?"; params.append(rarity)
        query += " ORDER BY m.price ASC LIMIT ? OFFSET ?"
        params.extend([limit, page*limit])
        async with db.execute(query, params) as c:
            return await c.fetchall()

async def buy_listing(lid, bid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM market WHERE id=?", (lid,)) as c:
            l = await c.fetchone()
        if not l: return False, "Лот не найден"
        if l['seller_id'] == bid: return False, "Нельзя купить своё"
        buyer = await get_user(bid)
        if buyer['diamonds'] < l['price']: return False, f"Нужно {l['price']}💎"
        await upd_diamonds(bid, -l['price']); await upd_diamonds(l['seller_id'], l['price'])
        await add_card_to_user(bid, l['card_id'])
        if l['quantity'] > 1: await db.execute("UPDATE market SET quantity=quantity-1 WHERE id=?", (lid,))
        else: await db.execute("DELETE FROM market WHERE id=?", (lid,))
        await db.commit()
        return True, "Куплено!"

async def create_auction(sid, cid, sp, dh=24):
    et = datetime.now() + timedelta(hours=dh)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO auctions (seller_id,card_id,start_price,current_price,end_time) VALUES (?,?,?,?,?)", (sid, cid, sp, sp, et))
        await db.commit()

async def get_active_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT a.*, c.name, c.rarity, c.is_L_card, c.file_id FROM auctions a JOIN cards c ON a.card_id=c.id WHERE a.status='active' AND a.end_time > datetime('now') ORDER BY a.end_time ASC") as c:
            return await c.fetchall()

async def bid_auction(aid, bid, amt):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (aid,)) as c:
            a = await c.fetchone()
        if not a: return False, "Аукцион не найден"
        if amt <= a['current_price']: return False, "Ставка больше текущей"
        if (await get_user(bid))['diamonds'] < amt: return False, "Недостаточно 💎"
        await db.execute("UPDATE auctions SET current_price=?, current_bidder_id=? WHERE id=?", (amt, bid, aid))
        await db.commit()
        return True, "Ставка принята!"

async def finish_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auctions WHERE status='active' AND end_time <= datetime('now')") as c:
            for a in await c.fetchall():
                if a['current_bidder_id']:
                    await upd_diamonds(a['seller_id'], a['current_price'])
                    await add_card_to_user(a['current_bidder_id'], a['card_id'])
                    await db.execute("UPDATE auctions SET status='sold' WHERE id=?", (a['id'],))
                else: await db.execute("UPDATE auctions SET status='expired' WHERE id=?", (a['id'],))
        await db.commit()

# ==================== ДРУЗЬЯ ====================
async def send_friend_request(uid, fid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO friends (user_id,friend_id) VALUES (?,?)", (uid, fid))
        await db.commit()

async def accept_friend(uid, fid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (fid, uid))
        await db.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'accepted')", (uid, fid))
        await db.commit()

async def get_friends(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT u.user_id, u.username FROM friends f JOIN users u ON f.friend_id=u.user_id WHERE f.user_id=? AND f.status='accepted'", (uid,)) as c:
            sent = await c.fetchall()
        async with db.execute("SELECT u.user_id, u.username FROM friends f JOIN users u ON f.user_id=u.user_id WHERE f.friend_id=? AND f.status='accepted'", (uid,)) as c:
            received = await c.fetchall()
        friends = []; seen = set()
        for f in sent + received:
            if f['user_id'] != uid and f['user_id'] not in seen:
                friends.append(f); seen.add(f['user_id'])
        return friends

# ==================== КОЛОДЫ И ИВЕНТЫ ====================
async def create_deck(name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO card_decks (name) VALUES (?)", (name,))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            return (await c.fetchone())[0]

async def get_all_decks():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM card_decks ORDER BY id") as c:
            return await c.fetchall()

async def get_deck_by_id(did):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM card_decks WHERE id=?", (did,)) as c:
            return await c.fetchone()

async def add_card_to_deck(did, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO deck_cards (deck_id,card_id) VALUES (?,?)", (did, cid))
        await db.commit()

async def get_deck_cards(did):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT c.* FROM cards c JOIN deck_cards dc ON c.id=dc.card_id WHERE dc.deck_id=?", (did,)) as c:
            return await c.fetchall()

async def start_event(did):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE active_events SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status='active'")
        await db.execute("INSERT INTO active_events (deck_id, status) VALUES (?, 'active')", (did,))
        await db.commit()

async def end_current_event():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE active_events SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status='active'")
        await db.commit()

async def get_active_event():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM active_events WHERE status='active'") as c:
            return await c.fetchone()

async def get_event_cards_active():
    event = await get_active_event()
    if not event: return []
    return await get_deck_cards(event['deck_id'])

# ==================== ГИЛЬДЕЙСКИЕ ВОЙНЫ ====================
async def get_active_war_season():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_war_seasons WHERE status='active' OR status='selection'") as c:
            return await c.fetchone()

async def start_war_season():
    await end_current_war()
    async with aiosqlite.connect(DB_PATH) as db:
        card_selection_end = datetime.now() + timedelta(days=2)
        await db.execute("INSERT INTO guild_war_seasons (status, started_at, card_selection_end) VALUES ('selection', CURRENT_TIMESTAMP, ?)", (card_selection_end,))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c:
            return (await c.fetchone())[0]

async def start_war_battles(season_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE guild_war_seasons SET status='active' WHERE id=?", (season_id,))
        await db.commit()

async def end_current_war():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE guild_war_seasons SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status IN ('active','selection')")
        await db.commit()

async def add_war_points(guild_id, user_id, season_id, points):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO guild_war_points (guild_id, user_id, points, season_id) VALUES (?,?,?,?) ON CONFLICT(guild_id, user_id, season_id) DO UPDATE SET points=points+?", (guild_id, user_id, points, season_id, points))
        await db.commit()

async def set_war_card(season_id, guild_id, user_id, card_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO guild_war_cards VALUES (?,?,?,?)", (season_id, guild_id, user_id, card_id))
        await db.commit()

async def get_guild_war_ranking(season_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT g.id, g.name, SUM(gwp.points) as total_points FROM guilds g JOIN guild_war_points gwp ON g.id=gwp.guild_id WHERE gwp.season_id=? GROUP BY g.id ORDER BY total_points DESC", (season_id,)) as c:
            return await c.fetchall()

async def get_user_guild(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT g.* FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=?", (uid,)) as c:
            return await c.fetchone()

# ==================== КОЛЕСО ФОРТУНЫ ====================
FORTUNE_PRIZES = [
    {"prize":"roll","value":1,"desc":"🎲 +1 крутка","weight":30},
    {"prize":"diamond","value":1,"desc":"💎 +1 алмаз","weight":25},
    {"prize":"diamond","value":2,"desc":"💎 +2 алмаза","weight":15},
    {"prize":"random_card","value":1,"desc":"🎴 Случайная карта","weight":15},
    {"prize":"nothing","value":0,"desc":"❌ Ничего","weight":15},
]

# ==================== КЛАВИАТУРЫ ====================
def permanent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="🛍 Магазин")],
            [KeyboardButton(text="🎪 Ивент-крутка"), KeyboardButton(text="🎡 Колесо фортуны")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎒 Инвентарь")],
            [KeyboardButton(text="📋 Задания"), KeyboardButton(text="📅 Неделя")],
            [KeyboardButton(text="💱 Биржа"), KeyboardButton(text="🏪 Аукцион")],
            [KeyboardButton(text="🔄 Обмен"), KeyboardButton(text="⚔️ Дуэль")],
            [KeyboardButton(text="👥 Друзья"), KeyboardButton(text="🏰 Гильдия")],
            [KeyboardButton(text="📚 Все карты"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="🏅 Достижения"), KeyboardButton(text="🎫 Промокод")],
            [KeyboardButton(text="⬆ Уровни"), KeyboardButton(text="⚔️ Война гильдий")],
            [KeyboardButton(text="💥 Разбить всё"), KeyboardButton(text="⚡ Бустеры")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True, persistent=True
    )

def rarity_emoji(rarity):
    return {'R':'⚪','SR':'🔵','SSR':'🟣','L':'🌟'}.get(rarity,'⚪')

def rarity_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="R - Обычная", callback_data="rarity_R")],
        [InlineKeyboardButton(text="SR - Редкая", callback_data="rarity_SR")],
        [InlineKeyboardButton(text="SSR - Эпическая", callback_data="rarity_SSR")],
        [InlineKeyboardButton(text="🌟 L - Легендарная", callback_data="rarity_L")],
    ])

# ==================== БОТ ====================
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    @dp.message(CommandStart())
    async def start(msg: types.Message):
        user = await get_user(msg.from_user.id)
        if user and user['banned']: await msg.answer("⛔ Вы заблокированы."); return
        await create_user(msg.from_user.id, msg.from_user.username or "Аноним")
        login_bonus, streak = await check_daily_login(msg.from_user.id)
        text = "✨ Приветствую тебя путник! ✨\n\n🎲 Выдачи 7:00 и 17:00 МСК\n🌟 L-карты в ивентах\n💎 R=1 SR=5 SSR=10 L=20\n⚔️ /duel @user ID [ставка]"
        if login_bonus:
            bonus_rolls = min(streak, 7)
            await upd_rolls(msg.from_user.id, bonus_rolls)
            text += f"\n\n🔥 Серия входов: {streak} дней!\n🎁 +{bonus_rolls}🎲 за вход!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== КРУТКИ ====================
    async def perform_regular_roll(uid):
        cards = await get_regular_cards()
        if not cards: return None, "Нет обычных карт"
        card = random.choice(cards)
        await add_card_to_user(uid, card['id'], is_original=True)
        booster = await get_booster(uid, 'luck')
        xp_mult = 1.5 if booster else 1.0
        levels_gained, new_level = await add_xp(uid, int(10 * xp_mult))
        await update_weekly_progress(uid, 'weekly_rolls')
        if card['rarity'] == 'SSR': await update_weekly_progress(uid, 'weekly_ssr')
        caption = f"{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        if booster: caption += "\n⚡ Бустер удачи активен!"
        if levels_gained > 0: caption += f"\n⬆ Уровень {new_level}!"
        return card, caption, levels_gained, new_level
    
    async def perform_event_roll(uid):
        u = await get_user(uid)
        event = await get_active_event()
        cards = await get_event_cards_active() if event else await get_event_cards()
        if not cards: return None, "🎪 Нет активного ивента!", 0, u['level']
        booster = await get_booster(uid, 'event')
        event_rate = await get_setting_float('event_rate_L', 2.0)
        if booster: event_rate *= 1.5
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        progress = u['event_guarantor']
        guarantor_limit = await get_setting_int('guarantor_limit', 50)
        is_guaranteed = progress >= guarantor_limit
        guarantee_text = ""
        if is_guaranteed and L_cards:
            card = random.choice(L_cards); await upd_event_guarantor(uid, 0)
            guarantee_text = "🎉 ИВЕНТ-ГАРАНТ! "; progress = 0
        else:
            if L_cards and random.random() < event_rate / 100:
                card = random.choice(L_cards); await upd_event_guarantor(uid, 0)
                guarantee_text = "🌟 L-КАРТА! "; progress = 0
            else:
                card = random.choice(normal if normal else cards)
                progress += 1; await upd_event_guarantor(uid, progress)
        await add_card_to_user(uid, card['id'], is_original=True)
        xp_mult = 1.5 if booster else 1.0
        levels_gained, new_level = await add_xp(uid, int(20 * xp_mult))
        caption = f"{guarantee_text}{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}\n📊 Гарант: {progress}/{guarantor_limit}"
        if booster: caption += "\n⚡ Бустер ивента активен!"
        if levels_gained > 0: caption += f"\n⬆ Уровень {new_level}!"
        return card, caption, levels_gained, new_level
    
    async def send_card_with_break(msg, card, caption):
        uid = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id
        user_card = await get_user_card(uid, card['id'])
        kb = None
        if user_card and user_card['quantity'] > 1:
            extra = user_card['quantity'] - 1 if user_card['is_original'] else user_card['quantity']
            price = await get_break_price(card['rarity'])
            booster = await get_booster(uid, 'break')
            if booster: price = int(price * 1.5)
            total = extra * price
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔨 Разбить (+{total}💎)", callback_data=f"break_{card['id']}")]
            ])
        try:
            if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=kb)
            else: await msg.answer(caption, reply_markup=kb)
        except: await msg.answer(caption, reply_markup=kb)
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_btn(msg):
        u = await get_user(msg.from_user.id)
        if not u or u['rolls'] <= 0: await msg.answer("❌ Нет круток!"); return
        await upd_rolls(msg.from_user.id, -1)
        card, caption, levels, new_level = await perform_regular_roll(msg.from_user.id)
        if card is None: await msg.answer(caption); return
        await update_task_progress(msg.from_user.id, 'roll')
        achievements = await check_achievements(msg.from_user.id)
        await send_card_with_break(msg, card, caption)
        if achievements:
            for ach in achievements: await msg.answer(f"🏅 {ach['icon']} {ach['name']}!\nНажми 🏅 для награды!")
        if levels > 0: await msg.answer(f"🎉 Уровень {new_level}! Нажми ⬆ Уровни для награды!")
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): await msg.answer("🎉 +1 бонусная крутка!")
    
    @dp.message(F.text == "🎪 Ивент-крутка")
    async def event_btn(msg):
        u = await get_user(msg.from_user.id)
        if u['event_rolls'] <= 0: await msg.answer(f"❌ Нет ивент-круток!\n📊 Гарант: {u['event_guarantor']}/{await get_setting_int('guarantor_limit',50)}"); return
        await upd_event_rolls(msg.from_user.id, -1)
        await update_task_progress(msg.from_user.id, 'event_roll')
        card, caption, levels, new_level = await perform_event_roll(msg.from_user.id)
        if card is None: await msg.answer(caption); return
        achievements = await check_achievements(msg.from_user.id)
        await send_card_with_break(msg, card, caption)
        if achievements:
            for ach in achievements: await msg.answer(f"🏅 {ach['icon']} {ach['name']}!")
        if levels > 0: await msg.answer(f"🎉 Уровень {new_level}!")
    
    # ==================== РАЗБИТЬ ВСЁ ====================
    @dp.message(F.text == "💥 Разбить всё")
    async def break_all_btn(msg):
        cards = await get_user_cards(msg.from_user.id)
        total_diamonds = 0; broken = 0
        booster = await get_booster(msg.from_user.id, 'break')
        for card in cards:
            if card['quantity'] > 1:
                qty = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if qty > 0:
                    price = await get_break_price(card['rarity'])
                    if booster: price = int(price * 1.5)
                    diamonds = qty * price
                    async with aiosqlite.connect(DB_PATH) as db:
                        if card['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        await db.commit()
                    total_diamonds += diamonds; broken += qty
                    for _ in range(qty):
                        await add_xp(msg.from_user.id, 2)
                        await update_task_progress(msg.from_user.id, 'break')
                        await update_weekly_progress(msg.from_user.id, 'weekly_break')
        if broken > 0:
            await upd_diamonds(msg.from_user.id, total_diamonds)
            msg_text = f"💥 Разбито {broken} повторов!\n💎 +{total_diamonds} алмазов!"
            if booster: msg_text += "\n⚡ Бустер разбития активен!"
            await msg.answer(msg_text)
        else: await msg.answer("❌ Нет повторов!")
    
    # ==================== ДУЭЛИ ====================
    @dp.message(F.text == "⚔️ Дуэль")
    async def duel_btn(msg): await msg.answer("⚔️ /duel @user ID_карты [СТАВКА]\nПример: /duel @username 5 10")
    
    @dp.message(Command("duel"))
    async def dcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 3: await msg.answer("❌ /duel @user ID_карты [СТАВКА]"); return
            oun = p[1].replace("@",""); cid = int(p[2])
            bet = int(p[3]) if len(p) > 3 else 1
            if bet < 1: await msg.answer("❌ Ставка > 0!"); return
            my_card = await get_user_card(msg.from_user.id, cid)
            if not my_card: await msg.answer(f"❌ У вас нет карты #{cid}!"); return
            u = await get_user(msg.from_user.id)
            if u['diamonds'] < bet: await msg.answer(f"❌ Нужно {bet}💎!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (oun,)) as c: ou = await c.fetchone()
            if not ou: await msg.answer(f"❌ @{oun} не найден!"); return
            oid = ou[0]
            if oid == msg.from_user.id: await msg.answer("❌ Нельзя себя!"); return
            opp = await get_user(oid)
            if opp['diamonds'] < bet: await msg.answer(f"❌ У @{oun} нет {bet}💎!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_card_id, bet_amount) VALUES (?,?,?,?)", (msg.from_user.id, oid, cid, bet))
                await db.commit()
                async with db.execute("SELECT last_insert_rowid()") as c: duel_id = (await c.fetchone())[0]
            card = await get_card_by_id(cid)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"aduel_{duel_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dduel_{duel_id}")],
            ])
            await bot.send_message(oid, f"⚔️ ВЫЗОВ!\nОт: @{msg.from_user.username}\nКарта: {rarity_emoji(card['rarity'])} {card['name']} (#{cid})\nСтавка: {bet}💎\nВыбери карту: /pick ID", reply_markup=kb)
            await msg.answer(f"✅ Вызов @{oun}!\nСтавка: {bet}💎")
        except Exception as e: await msg.answer(f"❌ Ошибка: {e}")
    
    @dp.callback_query(F.data.startswith("aduel_"))
    async def ad(call):
        duel_id = int(call.data.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM duels WHERE id=? AND status='pending'", (duel_id,)) as c: duel = await c.fetchone()
        if not duel: await call.answer("Дуэль не найдена!", show_alert=True); return
        await call.message.answer("⚔️ Выбери карту: /pick ID_карты"); await call.answer()
    
    @dp.callback_query(F.data.startswith("dduel_"))
    async def dd(call):
        duel_id = int(call.data.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='declined' WHERE id=?", (duel_id,)); await db.commit()
            async with db.execute("SELECT challenger_id FROM duels WHERE id=?", (duel_id,)) as c: row = await c.fetchone()
        if row:
            try: await bot.send_message(row[0], f"❌ @{call.from_user.username} отклонил вызов")
            except: pass
        await call.message.edit_text("❌ Отклонен"); await call.answer()
    
    @dp.message(Command("pick"))
    async def pcmd(msg):
        try:
            cid = int(msg.text.replace("/pick","").strip())
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE opponent_id=? AND status='pending'", (msg.from_user.id,)) as c: duel = await c.fetchone()
            if not duel: await msg.answer("❌ Нет активной дуэли!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE duels SET opponent_card_id=? WHERE id=?", (cid, duel['id'])); await db.commit()
            await msg.answer(f"✅ Карта #{cid} выбрана!")
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE id=?", (duel['id'],)) as c: updated = await c.fetchone()
            if updated['challenger_card_id'] and updated['opponent_card_id']: await resolve_duel(updated)
        except: await msg.answer("❌ /pick ID")
    
    async def resolve_duel(duel):
        cc = await get_card_by_id(duel['challenger_card_id']); oc = await get_card_by_id(duel['opponent_card_id'])
        rp = {'R':1,'SR':2,'SSR':3,'L':4}; cp, op = rp.get(cc['rarity'],0), rp.get(oc['rarity'],0)
        wid = duel['challenger_id'] if cp > op else (duel['opponent_id'] if op > cp else (duel['challenger_id'] if cc['id'] > oc['id'] else duel['opponent_id']))
        lid = duel['opponent_id'] if wid == duel['challenger_id'] else duel['challenger_id']
        bet = duel['bet_amount']
        await upd_diamonds(wid, bet); await upd_diamonds(lid, -bet)
        await add_xp(wid, 15); await add_xp(lid, 5)
        await update_duel_stats(wid, True); await update_duel_stats(lid, False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=?", (wid, duel['id'])); await db.commit()
        winner = await get_user(wid)
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try: await bot.send_message(uid, f"⚔️ Дуэль завершена!\n🏆 Победитель: @{winner['username']}\n💎 Ставка: {bet}")
            except: pass
    
    # ==================== МАГАЗИН ====================
    @dp.message(F.text == "🛍 Магазин")
    async def shop_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Обычные крутки", callback_data="shop_regular")],
            [InlineKeyboardButton(text="🎪 Ивент-крутки", callback_data="shop_event")],
        ])
        await msg.answer("🛍 Магазин:", reply_markup=kb)
    
    @dp.callback_query(F.data == "shop_regular")
    async def shop_regular(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 1 крутка - 2💎", callback_data="buy_reg_1")],
            [InlineKeyboardButton(text="🎲 5 круток - 10💎", callback_data="buy_reg_5")],
            [InlineKeyboardButton(text="🎲 10 круток - 50💎", callback_data="buy_reg_10")],
        ])
        await call.message.edit_text("🎲 Обычные:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "shop_event")
    async def shop_event(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎪 1 ивент - 10💎", callback_data="buy_evt_1")],
            [InlineKeyboardButton(text="🎪 5 ивентов - 35💎", callback_data="buy_evt_5")],
            [InlineKeyboardButton(text="🎪 10 ивентов - 70💎", callback_data="buy_evt_10")],
        ])
        await call.message.edit_text("🎪 Ивент:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data.startswith("buy_reg_"))
    async def buy_reg(call):
        amount = int(call.data.split("_")[2]); prices = {1:2,5:10,10:50}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[amount]: await call.answer(f"❌ {prices[amount]}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -prices[amount]); await upd_rolls(call.from_user.id, amount)
        await call.answer(f"✅ +{amount}🎲!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("buy_evt_"))
    async def buy_evt(call):
        amount = int(call.data.split("_")[2]); prices = {1:10,5:35,10:70}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[amount]: await call.answer(f"❌ {prices[amount]}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -prices[amount]); await upd_event_rolls(call.from_user.id, amount)
        await call.answer(f"✅ +{amount}🎪!", show_alert=True)
    
    # ==================== БУСТЕРЫ ====================
    @dp.message(F.text == "⚡ Бустеры")
    async def booster_shop_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍀 Удача (SSR x1.5) - 5💎/1ч", callback_data="buy_booster_luck")],
            [InlineKeyboardButton(text="🎪 Ивент (L x1.5) - 10💎/1ч", callback_data="buy_booster_event")],
            [InlineKeyboardButton(text="💎 Разбитие (x1.5) - 3💎/1ч", callback_data="buy_booster_break")],
        ])
        await msg.answer("⚡ Магазин бустеров:\n\nБустеры увеличивают награды на 50% на 1 час!", reply_markup=kb)
    
    @dp.callback_query(F.data == "buy_booster_luck")
    async def bbl(call):
        if await buy_booster(call.from_user.id, 'luck', 1, 5): await call.answer("✅ Бустер удачи активирован!", show_alert=True)
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_event")
    async def bbe(call):
        if await buy_booster(call.from_user.id, 'event', 1, 10): await call.answer("✅ Бустер ивента активирован!", show_alert=True)
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_break")
    async def bbb(call):
        if await buy_booster(call.from_user.id, 'break', 1, 3): await call.answer("✅ Бустер разбития активирован!", show_alert=True)
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    # ==================== КОЛЕСО ====================
    async def spin_fortune(msg):
        prizes = [p for p in FORTUNE_PRIZES for _ in range(p['weight'])]
        prize = random.choice(prizes)
        if prize['prize'] == 'roll': await upd_rolls(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'diamond': await upd_diamonds(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_regular_cards()
            if cards:
                card = random.choice(cards); await add_card_to_user(msg.from_user.id, card['id'], is_original=True)
                caption = f"🎡 Колесо!\n🎴 {rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
                await send_card_with_break(msg, card, caption)
                return
            else: prize = {"desc":"❌ Ничего"}
        await msg.answer(f"🎡 Колесо!\n\n{prize['desc']}")
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_btn(msg):
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вр. - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вр. - 3💎", callback_data="fortune_buy_5")],
            ])
            await msg.answer("🎡 Нет вращений!\nКупить:", reply_markup=kb)
        else:
            await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
            await update_task_progress(msg.from_user.id, 'fortune')
            await update_weekly_progress(msg.from_user.id, 'weekly_fortune')
            await spin_fortune(msg)
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call):
        amount = int(call.data.split("_")[2]); prices = {1:1,5:3}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[amount]: await call.answer(f"❌ {prices[amount]}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -prices[amount])
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + amount)
        await call.answer(f"✅ +{amount}!", show_alert=True)
        for _ in range(amount): await spin_fortune(call.message)
    
    # ==================== ПРОФИЛЬ ====================
    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(msg):
        u = await get_user(msg.from_user.id)
        if not u: return
        cards = await get_card_count(msg.from_user.id)
        xp_needed = u['level'] * 100 + 50
        bar = "▓" * int(u['xp']/xp_needed*10) + "░" * (10 - int(u['xp']/xp_needed*10)) if xp_needed > 0 else "▓"*10
        duel_stats = await get_duel_stats(msg.from_user.id)
        wins = duel_stats['wins'] if duel_stats else 0
        losses = duel_stats['losses'] if duel_stats else 0
        await update_task_progress(msg.from_user.id, 'profile')
        await msg.answer(
            f"👤 {u['username']} | ⭐ Ур.{u['level']}\n📊 XP: {u['xp']}/{xp_needed} [{bar}]\n"
            f"💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}\n🎴{cards} 🎡{u['fortune_spins']}\n"
            f"⚔️ Дуэли: {wins}W / {losses}L\n📊 Гарант: {u['event_guarantor']}/{await get_setting_int('guarantor_limit',50)}"
            f"\n🔥 Серия входов: {u['login_streak']} дн.",
            reply_markup=permanent_keyboard()
        )
    
    # ==================== УРОВНИ, ИНВЕНТАРЬ, ЗАДАНИЯ, БИРЖА, АУКЦИОН, ОБМЕН, ДРУЗЬЯ, ГИЛЬДИИ, ВОЙНЫ, ДОСТИЖЕНИЯ, ПРОМОКОДЫ, ЛИДЕРЫ, КАРТЫ, ПОМОЩЬ ====================
    # (Все эти секции остаются без изменений из предыдущего полного кода)
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Карта", callback_data="admin_add")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="admin_edit")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="👥 Всем выдать", callback_data="admin_give_all")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🎫 Промо", callback_data="admin_promo")],
            [InlineKeyboardButton(text="⛔ Бан", callback_data="admin_ban")],
            [InlineKeyboardButton(text="📊 Статы", callback_data="admin_stats")],
            [InlineKeyboardButton(text="🎪 Ивенты", callback_data="admin_event_menu")],
            [InlineKeyboardButton(text="⚔️ Война", callback_data="admin_war_menu")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
            [InlineKeyboardButton(text="💾 Бекап БД", callback_data="admin_backup")],
        ])
        await msg.answer("👑 Админ-панель\n\n💾 /backup - сохранить базу\n📥 /restore - восстановить\n📊 /check_db - проверить", reply_markup=kb)
    
    # ==================== БЕКАП БАЗЫ ДАННЫХ ====================
    @dp.callback_query(F.data == "admin_backup")
    async def admin_backup_info(call):
        await call.message.answer("💾 Бекап базы данных:\n\n/backup - скачать базу\n/restore - восстановить (отправь файл)\n/check_db - проверить количество карт")
        await call.answer()
    
    @dp.message(Command("backup"))
    async def backup_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
                await msg.answer_document(FSInputFile(DB_PATH), caption="📦 Бекап базы данных\nСохрани этот файл!")
                await msg.answer("✅ Сохрани этот файл! Если карты пропадут после обновления - отправь его с командой /restore")
            else:
                await msg.answer("❌ База данных пуста или не найдена!")
        except Exception as e:
            await msg.answer(f"❌ Ошибка бекапа: {e}")
    
    @dp.message(Command("restore"))
    async def restore_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        if not msg.document:
            await msg.answer("❌ Отправь файл базы данных (.db) с командой /restore")
            return
        try:
            file_id = msg.document.file_id
            file = await bot.get_file(file_id)
            await bot.download_file(file.file_path, DB_PATH)
            await msg.answer("✅ База данных восстановлена! Перезапусти бота командой /reload")
        except Exception as e:
            await msg.answer(f"❌ Ошибка восстановления: {e}")
    
    @dp.message(Command("check_db"))
    async def check_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM cards") as c: cards = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM user_cards") as c: user_cards = (await c.fetchone())[0]
            await msg.answer(f"📊 База данных:\n🎴 Карт в базе: {cards}\n👥 Пользователей: {users}\n📦 Карт у игроков: {user_cards}\n📁 Размер: {os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0} байт")
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    
    @dp.message(Command("reload"))
    async def reload_bot(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        await msg.answer("🔄 Бот продолжает работать. База данных уже загружена.")
    
    # --- Остальная админка (без изменений) ---
    
    # ==================== ВЫДАЧИ ====================
    async def morning_bonus():
        try:
            mr = await get_setting_int('morning_rolls', 2); md = await get_setting_int('morning_diamonds', 3)
            mf = await get_setting_int('morning_fortune', 1); me = await get_setting_int('morning_event', 1)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(f"UPDATE users SET rolls=rolls+{mr}, diamonds=diamonds+{md}, fortune_spins={mf}, event_rolls=event_rolls+{me}, bonus_roll_received=0")
                await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),)); await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c: users = await c.fetchall()
            sent = 0
            for u in users:
                try: await bot.send_message(u['user_id'], f"🌅 Доброе утро!\n\n🎲 +{mr} 🎡 +{mf} 🎪 +{me} 💎 +{md}\n🕐 В 17:00 МСК жди ещё!"); sent += 1; await asyncio.sleep(0.05)
                except: pass
            logger.info(f"☀️ Утро: {sent}/{len(users)}")
        except Exception as e: logger.error(f"Утро: {e}")
    
    async def evening_bonus():
        try:
            er = await get_setting_int('evening_rolls', 2); ed = await get_setting_int('evening_diamonds', 3)
            ef = await get_setting_int('evening_fortune', 1); ee = await get_setting_int('evening_event', 1)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(f"UPDATE users SET rolls=rolls+{er}, diamonds=diamonds+{ed}, fortune_spins={ef}, event_rolls=event_rolls+{ee}"); await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c: users = await c.fetchall()
            sent = 0
            for u in users:
                try: await bot.send_message(u['user_id'], f"🌆 Добрый вечер!\n\n🎲 +{er} 🎡 +{ef} 🎪 +{ee} 💎 +{ed}\n😊 Хорошего вечера!"); sent += 1; await asyncio.sleep(0.05)
                except: pass
            logger.info(f"🌆 Вечер: {sent}/{len(users)}")
        except Exception as e: logger.error(f"Вечер: {e}")
    
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(morning_bonus, 'cron', hour=7, minute=0)
    scheduler.add_job(evening_bonus, 'cron', hour=17, minute=0)
    scheduler.add_job(finish_auctions, 'interval', minutes=10)
    scheduler.start()
    
    # Проверка базы при старте
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM cards") as c:
            count = (await c.fetchone())[0]
    if count == 0:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, "⚠️ База данных пуста! Используй /restore чтобы восстановить карты из бекапа.")
            except: pass
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
