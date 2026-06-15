import asyncio
import aiosqlite
import random
import logging
import sys
import os
import shutil
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
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
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_seasons (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'pending', started_at TIMESTAMP, ended_at TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_points (guild_id INTEGER, user_id INTEGER, points INTEGER DEFAULT 0, season_id INTEGER, PRIMARY KEY (guild_id, user_id, season_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS guild_war_cards (season_id INTEGER, guild_id INTEGER, user_id INTEGER, card_id INTEGER, PRIMARY KEY (season_id, guild_id, user_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS duels (id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_card_id INTEGER, opponent_card_id INTEGER, bet_amount INTEGER DEFAULT 1, status TEXT DEFAULT 'pending', winner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS duel_stats (user_id INTEGER PRIMARY KEY, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS friends (user_id INTEGER, friend_id INTEGER, status TEXT DEFAULT 'pending', PRIMARY KEY (user_id, friend_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, type TEXT, value INTEGER, uses_left INTEGER, created_by INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS level_rewards (user_id INTEGER, level INTEGER, claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, level))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS card_decks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS deck_cards (deck_id INTEGER, card_id INTEGER, PRIMARY KEY (deck_id, card_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS active_events (id INTEGER PRIMARY KEY AUTOINCREMENT, deck_id INTEGER, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP, status TEXT DEFAULT 'active')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS daily_login (user_id INTEGER, date TEXT, PRIMARY KEY (user_id, date))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS boosters (user_id INTEGER, type TEXT, multiplier REAL, ends_at TIMESTAMP, PRIMARY KEY (user_id, type))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        defaults = {'morning_rolls':'2','morning_diamonds':'3','morning_fortune':'1','morning_event':'1','evening_rolls':'2','evening_diamonds':'3','evening_fortune':'1','evening_event':'1','break_R':'1','break_SR':'5','break_SSR':'10','break_L':'20','guarantor_limit':'50','event_rate_L':'2'}
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
    prices = {'R': 1, 'SR': 5, 'SSR': 10, 'L': 20}
    custom = await get_setting(f'break_{rarity}')
    return int(custom) if custom else prices.get(rarity, 1)

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
        await db.execute("INSERT OR REPLACE INTO boosters VALUES (?,?,?,?)", (uid, btype, 1.5, ends))
        await db.commit()
    return True

# ==================== ЕЖЕДНЕВНЫЙ ВХОД ====================
async def check_daily_login(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM daily_login WHERE user_id=? AND date=?", (uid, today)) as c:
            if not await c.fetchone():
                await db.execute("INSERT INTO daily_login VALUES (?,?)", (uid, today))
                await db.commit()
                user = await get_user(uid)
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                streak = (user['login_streak'] + 1) if user and user['last_login'] == yesterday else 1
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
        # Убеждаемся что у нового пользователя есть вращения
        await db.execute("UPDATE users SET fortune_spins=1 WHERE user_id=? AND fortune_spins=0", (uid,))
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
                await db.execute("INSERT OR IGNORE INTO level_rewards VALUES (?,?,0)", (uid, l))
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
            if (await c.fetchone())[0]: return None
        if 'rolls' in r: await upd_rolls(uid, r['rolls'])
        if 'diamonds' in r: await upd_diamonds(uid, r['diamonds'])
        if 'event_rolls' in r: await upd_event_rolls(uid, r['event_rolls'])
        await db.execute("UPDATE level_rewards SET claimed=1 WHERE user_id=? AND level=?", (uid, level))
        await db.commit()
    return r

async def get_all_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards ORDER BY id") as c:
            return await c.fetchall()

async def get_regular_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards WHERE is_event_card=0 ORDER BY id") as c:
            cards = await c.fetchall()
            if cards: return cards
        async with db.execute("SELECT * FROM cards ORDER BY id") as c:
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
        else: await db.execute("INSERT INTO user_cards VALUES (?,?,1,?)", (uid, cid, is_original))
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
        if not row: return False
        cq, io = row[0], row[1]
        if io and cq <= qty: return False
        if cq >= qty:
            nq = cq - qty
            if nq <= 0: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
            else: await db.execute("UPDATE user_cards SET quantity=? WHERE user_id=? AND card_id=?", (nq, uid, cid))
            await db.commit()
            return True
        return False

async def get_card_count(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT SUM(quantity) FROM user_cards WHERE user_id=?", (uid,)) as c:
            row = await c.fetchone()
            return row[0] or 0

async def get_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""SELECT u.username, SUM(uc.quantity) as total FROM users u LEFT JOIN user_cards uc ON u.user_id=uc.user_id GROUP BY u.user_id HAVING total>0 ORDER BY total DESC LIMIT ?""", (limit,)) as c:
            return await c.fetchall()

async def get_level_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT username, level FROM users ORDER BY level DESC LIMIT ?", (limit,)) as c:
            return await c.fetchall()

async def get_duel_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT u.username, ds.wins, ds.losses FROM duel_stats ds JOIN users u ON ds.user_id=u.user_id ORDER BY ds.wins DESC LIMIT ?", (limit,)) as c:
            return await c.fetchall()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            return await c.fetchall()

# ==================== ДУЭЛИ ====================
async def update_duel_stats(uid, is_win):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO duel_stats VALUES (?,0,0)", (uid,))
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
    {"type":"weekly_fortune","desc":"🎡 Колесо 5 раз","target":5},
    {"type":"weekly_break","desc":"🔨 Разбить 10 повторов","target":10},
    {"type":"weekly_ssr","desc":"🟣 Выбить 3 SSR","target":3},
]

async def has_duplicates(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=? AND quantity>1", (uid,)) as c:
            return (await c.fetchone())[0] > 0

async def is_event_active():
    return await get_active_event() is not None or len(await get_event_cards()) > 0

async def ensure_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
            if (await c.fetchone())[0] == 0:
                available = [t for t in TASK_TYPES if t['type'] != 'break' or await has_duplicates(uid)]
                if not await is_event_active(): available = [t for t in available if t['type'] != 'event_roll']
                if len(available) < 2: available = [t for t in TASK_TYPES if t['type'] not in ('break','event_roll')]
                selected = random.sample(available, min(2, len(available)))
                for i, t in enumerate(selected):
                    await db.execute("INSERT INTO daily_tasks VALUES (?,?,?,?,?,?,?)", (uid, i, t['type'], t['target'], 0, 0, today))
                await db.commit()

async def ensure_weekly_tasks(uid):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, ws)) as c:
            if (await c.fetchone())[0] == 0:
                available = [t for t in WEEKLY_TASK_TYPES if t['type'] != 'weekly_break' or await has_duplicates(uid)]
                if len(available) < 3:
                    available = [t for t in WEEKLY_TASK_TYPES if t['type'] in ('weekly_rolls','weekly_fortune')]
                selected = random.sample(available, min(3, len(available)))
                for i, t in enumerate(selected):
                    await db.execute("INSERT INTO weekly_tasks VALUES (?,?,?,?,?,?,?,?)", (uid, i, t['type'], t['target'], 0, 0, 0, ws))
                await db.commit()

async def get_daily_tasks(uid):
    await ensure_daily_tasks(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=?", (uid, datetime.now().strftime("%Y-%m-%d"))) as c:
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) as t, SUM(completed) as d FROM daily_tasks WHERE user_id=? AND date=?", (uid, datetime.now().strftime("%Y-%m-%d"))) as c:
            row = await c.fetchone()
            return row[0] >= 2 and row[1] == row[0]

async def give_bonus_roll(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        u = await get_user(uid)
        if not u['bonus_roll_received']:
            await db.execute("UPDATE users SET bonus_roll_received=1, rolls=rolls+1 WHERE user_id=?", (uid,))
            await db.commit()
            return True
    return False

# ==================== ДОСТИЖЕНИЯ ====================
ACHIEVEMENTS = [
    {"id":"cards_10","name":"Начинающий коллекционер","desc":"Собрать 10 карт","icon":"📚","reward":{"diamonds":5}},
    {"id":"cards_50","name":"Опытный","desc":"Собрать 50 карт","icon":"📚","reward":{"diamonds":10,"rolls":3}},
    {"id":"cards_100","name":"Мастер","desc":"Собрать 100 карт","icon":"📚","reward":{"diamonds":25,"rolls":5}},
    {"id":"rolls_100","name":"Крутильщик","desc":"100 круток","icon":"🎲","reward":{"rolls":10}},
    {"id":"l_cards_1","name":"Первая L","desc":"Получить L-карту","icon":"🌟","reward":{"diamonds":20,"event_rolls":3}},
    {"id":"level_5","name":"Игрок","desc":"5 уровень","icon":"⭐","reward":{"diamonds":5}},
    {"id":"level_10","name":"Мастер","desc":"10 уровень","icon":"⭐","reward":{"diamonds":10,"rolls":5}},
]

async def check_achievements(uid):
    u = await get_user(uid)
    cards = await get_user_cards(uid)
    tc = sum(c['quantity'] for c in cards)
    lc = sum(c['quantity'] for c in cards if c['is_L_card'])
    new_ach = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            completed = (ach['id']=='cards_10' and tc>=10) or (ach['id']=='cards_50' and tc>=50) or (ach['id']=='cards_100' and tc>=100) or (ach['id']=='rolls_100' and u['total_rolls']>=100) or (ach['id']=='l_cards_1' and lc>=1) or (ach['id']=='level_5' and u['level']>=5) or (ach['id']=='level_10' and u['level']>=10)
            if not completed: continue
            async with db.execute("SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach['id'])) as c:
                if not (await c.fetchone())[0]:
                    await db.execute("INSERT OR REPLACE INTO achievements VALUES (?,?,1,0)", (uid, ach['id']))
                    await db.commit()
                    new_ach.append(ach)
    return new_ach

async def claim_achievement_reward(uid, ach_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach_id)) as c:
            if (await c.fetchone())[0]: return None
        ach = next((a for a in ACHIEVEMENTS if a['id']==ach_id), None)
        if not ach: return None
        r = ach['reward']
        if 'diamonds' in r: await upd_diamonds(uid, r['diamonds'])
        if 'rolls' in r: await upd_rolls(uid, r['rolls'])
        if 'event_rolls' in r: await upd_event_rolls(uid, r['event_rolls'])
        await db.execute("UPDATE achievements SET reward_claimed=1 WHERE user_id=? AND achievement_id=?", (uid, ach_id))
        await db.commit()
    return r

# ==================== БИРЖА ====================
async def create_market_listing(sid, cid, price, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO market (seller_id,card_id,price,quantity) VALUES (?,?,?,?)", (sid, cid, price, qty))
        await db.commit()

async def get_market_listings(card_id=None, page=0, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if card_id:
            async with db.execute("SELECT m.*, c.name, c.rarity FROM market m JOIN cards c ON m.card_id=c.id WHERE m.card_id=? ORDER BY m.price ASC LIMIT ? OFFSET ?", (card_id, limit, page*limit)) as c:
                return await c.fetchall()
        async with db.execute("SELECT m.*, c.name, c.rarity FROM market m JOIN cards c ON m.card_id=c.id ORDER BY m.created_at DESC LIMIT ? OFFSET ?", (limit, page*limit)) as c:
            return await c.fetchall()

async def buy_listing(lid, bid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM market WHERE id=?", (lid,)) as c:
            l = await c.fetchone()
        if not l or l['seller_id']==bid: return False
        buyer = await get_user(bid)
        if buyer['diamonds'] < l['price']: return False
        await upd_diamonds(bid, -l['price']); await upd_diamonds(l['seller_id'], l['price'])
        await add_card_to_user(bid, l['card_id'])
        if l['quantity']>1: await db.execute("UPDATE market SET quantity=quantity-1 WHERE id=?", (lid,))
        else: await db.execute("DELETE FROM market WHERE id=?", (lid,))
        await db.commit()
        return True

# ==================== АУКЦИОНЫ ====================
async def create_auction(sid, cid, sp, dh=24):
    et = datetime.now() + timedelta(hours=dh)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO auctions (seller_id,card_id,start_price,current_price,end_time) VALUES (?,?,?,?,?)", (sid, cid, sp, sp, et))
        await db.commit()

async def get_active_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT a.*, c.name, c.rarity FROM auctions a JOIN cards c ON a.card_id=c.id WHERE a.status='active' AND a.end_time > datetime('now') ORDER BY a.end_time ASC") as c:
            return await c.fetchall()

async def bid_auction(aid, bid, amt):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (aid,)) as c:
            a = await c.fetchone()
        if not a or amt <= a['current_price'] or (await get_user(bid))['diamonds'] < amt: return False
        await db.execute("UPDATE auctions SET current_price=?, current_bidder_id=? WHERE id=?", (amt, bid, aid))
        await db.commit()
        return True

async def finish_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.execute("INSERT OR IGNORE INTO friends VALUES (?,?,'pending')", (uid, fid))
        await db.commit()

async def accept_friend(uid, fid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (fid, uid))
        await db.execute("INSERT OR IGNORE INTO friends VALUES (?,?,'accepted')", (uid, fid))
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
            if f['user_id']!=uid and f['user_id'] not in seen: friends.append(f); seen.add(f['user_id'])
        return friends

# ==================== КОЛОДЫ И ИВЕНТЫ ====================
async def create_deck(name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO card_decks (name) VALUES (?)", (name,))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c: return (await c.fetchone())[0]

async def get_all_decks():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM card_decks ORDER BY id") as c: return await c.fetchall()

async def add_card_to_deck(did, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO deck_cards VALUES (?,?)", (did, cid))
        await db.commit()

async def get_deck_cards(did):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT c.* FROM cards c JOIN deck_cards dc ON c.id=dc.card_id WHERE dc.deck_id=?", (did,)) as c: return await c.fetchall()

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
        async with db.execute("SELECT * FROM active_events WHERE status='active'") as c: return await c.fetchone()

async def get_event_cards_active():
    event = await get_active_event()
    return await get_deck_cards(event['deck_id']) if event else []

# ==================== ГИЛЬДЕЙСКИЕ ВОЙНЫ ====================
async def get_active_war_season():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_war_seasons WHERE status IN ('active','selection')") as c: return await c.fetchone()

async def start_war_season():
    await end_current_war()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO guild_war_seasons (status, started_at) VALUES ('selection', CURRENT_TIMESTAMP)")
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as c: return (await c.fetchone())[0]

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
        await db.execute("INSERT INTO guild_war_points VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,season_id) DO UPDATE SET points=points+?", (guild_id, user_id, points, season_id, points))
        await db.commit()

async def set_war_card(season_id, guild_id, user_id, card_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO guild_war_cards VALUES (?,?,?,?)", (season_id, guild_id, user_id, card_id))
        await db.commit()

async def get_guild_war_ranking(season_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT g.id, g.name, SUM(gwp.points) as total FROM guilds g JOIN guild_war_points gwp ON g.id=gwp.guild_id WHERE gwp.season_id=? GROUP BY g.id ORDER BY total DESC", (season_id,)) as c:
            return await c.fetchall()

async def get_user_guild(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT g.* FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=?", (uid,)) as c: return await c.fetchone()

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
    
    # Исправляем fortune_spins всем у кого 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
        await db.commit()
    
    # ==================== 1. КОМАНДЫ ====================
    @dp.message(CommandStart())
    async def start(msg: types.Message):
        user = await get_user(msg.from_user.id)
        if user and user['banned']: await msg.answer("⛔ Вы заблокированы."); return
        await create_user(msg.from_user.id, msg.from_user.username or "Аноним")
        login_bonus, streak = await check_daily_login(msg.from_user.id)
        text = "✨ Приветствую тебя путник! ✨\n\n🎲 Выдачи 7:00 и 17:00 МСК\n🌟 L-карты в ивентах\n💎 R=1 SR=5 SSR=10 L=20\n⚔️ /duel @user ID [ставка]"
        if login_bonus:
            bonus = min(streak, 7)
            await upd_rolls(msg.from_user.id, bonus)
            text += f"\n\n🔥 Серия: {streak} дн!\n🎁 +{bonus}🎲 за вход!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg): await msg.answer("🎮 Меню:", reply_markup=permanent_keyboard())
    
    @dp.message(Command("duel"))
    async def dcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 3: await msg.answer("❌ /duel @user ID [ставка]"); return
            oun, cid = p[1].replace("@",""), int(p[2])
            bet = int(p[3]) if len(p) > 3 else 1
            if bet < 1: await msg.answer("❌ Ставка > 0!"); return
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет карты #{cid}!"); return
            u = await get_user(msg.from_user.id)
            if u['diamonds'] < bet: await msg.answer(f"❌ Нужно {bet}💎!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (oun,)) as c: ou = await c.fetchone()
            if not ou: await msg.answer(f"❌ @{oun} не найден!"); return
            oid = ou[0]
            if oid == msg.from_user.id: await msg.answer("❌ Нельзя себя!"); return
            if (await get_user(oid))['diamonds'] < bet: await msg.answer(f"❌ У @{oun} нет {bet}💎!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_card_id, bet_amount) VALUES (?,?,?,?)", (msg.from_user.id, oid, cid, bet))
                await db.commit()
                async with db.execute("SELECT last_insert_rowid()") as c: duel_id = (await c.fetchone())[0]
            card = await get_card_by_id(cid)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"aduel_{duel_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dduel_{duel_id}")],
            ])
            await bot.send_message(oid, f"⚔️ ВЫЗОВ!\nОт: @{msg.from_user.username}\n{rarity_emoji(card['rarity'])} {card['name']} (#{cid})\nСтавка: {bet}💎\nВыбери карту: /pick ID", reply_markup=kb)
            await msg.answer(f"✅ Вызов @{oun}!\nСтавка: {bet}💎")
        except: await msg.answer("❌ /duel @user ID [ставка]")
    
    @dp.message(Command("pick"))
    async def pcmd(msg):
        try:
            cid = int(msg.text.replace("/pick","").strip())
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT * FROM duels WHERE opponent_id=? AND status='pending'", (msg.from_user.id,)) as c: duel = await c.fetchone()
            if not duel: await msg.answer("❌ Нет дуэли!"); return
            await db.execute("UPDATE duels SET opponent_card_id=? WHERE id=?", (cid, duel['id'])); await db.commit()
            async with db.execute("SELECT * FROM duels WHERE id=?", (duel['id'],)) as c: updated = await c.fetchone()
            if updated['challenger_card_id'] and updated['opponent_card_id']: await resolve_duel(updated)
            else: await msg.answer(f"✅ Карта #{cid} выбрана!")
        except: await msg.answer("❌ /pick ID")
    
    @dp.message(Command("find"))
    async def fc(msg):
        try:
            cid = int(msg.text.replace("/find","").strip())
            listings = await get_market_listings(card_id=cid)
            if not listings: await msg.answer(f"📋 Нет #{cid}"); return
            text = f"📋 #{cid}:\n\n"; buttons = []
            for l in listings[:10]:
                text += f"#{l['id']} | {l['price']}💎\n"
                buttons.append([InlineKeyboardButton(text=f"{l['price']}💎", callback_data=f"mbuy_{l['id']}")])
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except: await msg.answer("❌ /find НОМЕР")
    
    @dp.message(Command("sell"))
    async def scmd(msg):
        try:
            p = msg.text.split(); cid, pr = int(p[1]), int(p[2])
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            await remove_card(msg.from_user.id, cid, 1); await create_market_listing(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ #{cid} за {pr}💎!")
        except: await msg.answer("❌ /sell НОМЕР ЦЕНА")
    
    @dp.message(Command("auction"))
    async def acmd(msg):
        try:
            p = msg.text.split(); cid, pr = int(p[1]), int(p[2])
            await remove_card(msg.from_user.id, cid, 1); await create_auction(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ Аукцион #{cid} от {pr}💎")
        except: await msg.answer("❌")
    
    @dp.message(Command("trade"))
    async def tcmd(msg):
        try:
            p = msg.text.split()
            if len(p) != 4: await msg.answer("❌"); return
            tun, fc, tc = p[1].replace("@",""), int(p[2]), int(p[3])
            if not await get_user_card(msg.from_user.id, fc): await msg.answer(f"❌ Нет #{fc}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (tun,)) as c: tu = await c.fetchone()
            if not tu: await msg.answer(f"❌ @{tun}!"); return
            if not await get_user_card(tu[0], tc): await msg.answer(f"❌ У @{tun} нет #{tc}!"); return
            fcard, tcard = await get_card_by_id(fc), await get_card_by_id(tc)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"tac_{msg.from_user.id}_{fc}_{tc}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"tdc_{msg.from_user.id}")],
            ])
            await bot.send_message(tu[0], f"🔄 ОБМЕН!\nОт: @{msg.from_user.username}\n{rarity_emoji(fcard['rarity'])} {fcard['name']} (#{fc})\n→ {rarity_emoji(tcard['rarity'])} {tcard['name']} (#{tc})", reply_markup=kb)
            await msg.answer(f"✅ @{tun}!")
        except: await msg.answer("❌")
    
    @dp.message(Command("friend"))
    async def fcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 3: return
            action, un = p[1], p[2].replace("@","")
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c: fu = await c.fetchone()
            if not fu or fu[0]==msg.from_user.id: return
            fid = fu[0]
            if action == "add":
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT * FROM friends WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)) AND status='accepted'", (msg.from_user.id, fid, fid, msg.from_user.id)) as c:
                        if await c.fetchone(): await msg.answer("❌ Уже друзья!"); return
                await send_friend_request(msg.from_user.id, fid)
                await msg.answer(f"✅ Заявка @{un}!")
                try: await bot.send_message(fid, f"👥 @{msg.from_user.username} хочет в друзья!\n/friend accept @{msg.from_user.username}")
                except: pass
            elif action == "accept": await accept_friend(msg.from_user.id, fid); await msg.answer(f"✅ @{un} друг!")
            elif action == "remove":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (msg.from_user.id, fid, fid, msg.from_user.id)); await db.commit()
                await msg.answer("✅ Удалён")
        except: pass
    
    @dp.message(Command("guild"))
    async def gcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 2: return
            action = p[1]
            if action == "create":
                name = " ".join(p[2:]); u = await get_user(msg.from_user.id)
                if u['diamonds'] < 10: await msg.answer("❌ 10💎!"); return
                await upd_diamonds(msg.from_user.id, -10)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT INTO guilds (name, owner_id) VALUES (?,?)", (name, msg.from_user.id)); await db.commit()
                    async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c: gid = (await c.fetchone())[0]
                    await db.execute("INSERT INTO guild_members VALUES (?,?,'owner',CURRENT_TIMESTAMP)", (gid, msg.from_user.id)); await db.commit()
                await msg.answer(f"✅ '{name}' создана!")
            elif action == "join":
                name = " ".join(p[2:])
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c: g = await c.fetchone()
                if not g: return
                await db.execute("INSERT OR IGNORE INTO guild_join_requests VALUES (?,?,?,'pending')", (g[0], msg.from_user.id)); await db.commit()
                async with db.execute("SELECT owner_id FROM guilds WHERE id=?", (g[0],)) as c: oid = (await c.fetchone())[0]
                await msg.answer("✅ Заявка отправлена!")
                try: await bot.send_message(oid, f"📩 @{msg.from_user.username} хочет в '{name}'\n/guild accept @{msg.from_user.username}")
                except: pass
            elif action == "list":
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute("SELECT g.name, COUNT(gm.user_id) as cnt FROM guilds g LEFT JOIN guild_members gm ON g.id=gm.guild_id GROUP BY g.id") as c: guilds = await c.fetchall()
                await msg.answer("📋 Гильдии:\n\n" + "\n".join([f"• {g['name']} ({g['cnt']}👥)" for g in guilds]) if guilds else "Нет")
        except: pass
    
    @dp.message(Command("war_pick"))
    async def war_pick(msg):
        season = await get_active_war_season()
        if not season or season['status']!='selection': return
        guild = await get_user_guild(msg.from_user.id)
        if not guild: return
        try:
            cid = int(msg.text.replace("/war_pick","").strip())
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            await set_war_card(season['id'], guild['id'], msg.from_user.id, cid)
            await msg.answer(f"✅ #{cid} выбрана!")
        except: pass
    
    @dp.message(Command("claim_weekly"))
    async def claim_weekly(msg):
        tasks = await get_weekly_tasks(msg.from_user.id)
        if tasks and all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            today = datetime.now(); ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE weekly_tasks SET reward_claimed=1 WHERE user_id=? AND week_start=?", (msg.from_user.id, ws)); await db.commit()
            await upd_diamonds(msg.from_user.id, 3); await upd_rolls(msg.from_user.id, 2); await upd_event_rolls(msg.from_user.id, 1)
            await msg.answer("✅ +3💎 +2🎲 +1🎪")
        else: await msg.answer("❌ Не все задания выполнены или награда получена")
    
    @dp.message(Command("test_cards"))
    async def test_cards(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        regular = await get_regular_cards()
        all_cards = await get_all_cards()
        await msg.answer(f"📊 Карт в базе: {len(all_cards)}\nОбычных (для крутки): {len(regular)}")
    
    # Админ-команды
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Карта", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="👥 Всем", callback_data="admin_give_all")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="⛔ Бан", callback_data="admin_ban")],
            [InlineKeyboardButton(text="🎪 Ивенты", callback_data="admin_event_menu")],
            [InlineKeyboardButton(text="⚔️ Война", callback_data="admin_war_menu")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
            [InlineKeyboardButton(text="💾 Бекап", callback_data="admin_backup")],
        ])
        await msg.answer("👑 Админ-панель", reply_markup=kb)
    
    @dp.message(Command("addcard"))
    async def ac(msg, state): await state.update_data(is_event=False); await msg.answer("📝 Шаг 1/4\nВведи #НОМЕР ИМЯ"); await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(Command("cards"))
    async def cc(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        cards = await get_all_cards()
        if not cards: await msg.answer("📋 Нет"); return
        text = "📋 Карты:\n\n"
        for c in cards: text += f"#{c['id']} {rarity_emoji(c['rarity'])} {c['name']}\n"
        for i in range(0, len(text), 4000): await msg.answer(text[i:i+4000])
    
    @dp.message(Command("delcard"))
    async def dc(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            cid = int(msg.text.replace("/delcard","").strip())
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (cid,)); await db.commit()
            await msg.answer(f"✅ #{cid} удалена!")
        except: pass
    
    @dp.message(Command("givediamonds"))
    async def gd_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: p=msg.text.split(); uid=await resolve_user(p[1]); await upd_diamonds(uid,int(p[2])); await msg.answer(f"✅ +{p[2]}💎")
        except: await msg.answer("❌")
    
    @dp.message(Command("giverolls"))
    async def gr_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: p=msg.text.split(); uid=await resolve_user(p[1]); await upd_rolls(uid,int(p[2])); await msg.answer(f"✅ +{p[2]}🎲")
        except: await msg.answer("❌")
    
    @dp.message(Command("giveevent"))
    async def ge_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: p=msg.text.split(); uid=await resolve_user(p[1]); await upd_event_rolls(uid,int(p[2])); await msg.answer(f"✅ +{p[2]}🎪")
        except: await msg.answer("❌")
    
    @dp.message(Command("giveall"))
    async def giveall_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p=msg.text.split(); t, am = p[1], int(p[2]); users=await get_all_users()
            for u in users:
                try:
                    if t=='diamonds': await upd_diamonds(u['user_id'],am)
                    elif t=='rolls': await upd_rolls(u['user_id'],am)
                    elif t=='event': await upd_event_rolls(u['user_id'],am)
                    elif t=='fortune': await upd_fortune_spins(u['user_id'],am)
                except: pass
            await msg.answer(f"✅ {am} для всех!")
        except: await msg.answer("❌ /giveall ТИП КОЛ-ВО")
    
    @dp.message(Command("broadcast"))
    async def bcmd(msg, state): await msg.answer("📢 Сообщение:"); await state.set_state(BroadcastStates.waiting_for_broadcast)
    
    @dp.message(Command("ban"))
    async def ban_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            uid=await resolve_user(msg.text.replace("/ban","").strip())
            async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE users SET banned=1 WHERE user_id=?",(uid,)); await db.commit()
            await msg.answer("⛔ Забанен!")
        except: await msg.answer("❌")
    
    @dp.message(Command("unban"))
    async def unban_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            uid=await resolve_user(msg.text.replace("/unban","").strip())
            async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE users SET banned=0 WHERE user_id=?",(uid,)); await db.commit()
            await msg.answer("✅ Разбанен!")
        except: await msg.answer("❌")
    
    @dp.message(Command("promo"))
    async def promo_create(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p=msg.text.split(); code=p[1].upper(); ptype=p[2]; value=int(p[3]); uses=int(p[4]) if len(p)>4 else 1
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR REPLACE INTO promocodes VALUES (?,?,?,?,?)",(code,ptype,value,uses,msg.from_user.id)); await db.commit()
            await msg.answer(f"✅ {code}")
        except: await msg.answer("❌")
    
    @dp.message(Command("user"))
    async def user_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            uid=await resolve_user(msg.text.replace("/user","").strip()); u=await get_user(uid)
            await msg.answer(f"👤 @{u['username']}\n⭐ Ур.{u['level']}\n💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}")
        except: await msg.answer("❌")
    
    @dp.message(Command("reset"))
    async def reset_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            uid=await resolve_user(msg.text.replace("/reset","").strip())
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=0,diamonds=0,event_rolls=0,fortune_spins=0,total_rolls=0,xp=0,level=1 WHERE user_id=?",(uid,))
                await db.execute("DELETE FROM user_cards WHERE user_id=?",(uid,)); await db.commit()
            await msg.answer("✅ Сброшен!")
        except: await msg.answer("❌")
    
    @dp.message(Command("stats"))
    async def stats_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c: users=(await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM cards") as c: cards=(await c.fetchone())[0]
        await msg.answer(f"📊 👥{users} 🎴{cards}")
    
    @dp.message(Command("force_morning"))
    async def fm(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await morning_bonus(); await msg.answer("✅")
    
    @dp.message(Command("force_evening"))
    async def fe(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await evening_bonus(); await msg.answer("✅")
    
    @dp.message(Command("logs"))
    async def logs_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: limit=int(msg.text.replace("/logs","").strip() or "20")
        except: limit=20
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory=aiosqlite.Row
            async with db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?",(limit,)) as c: logs=await c.fetchall()
        await msg.answer("📋 Логи:\n\n"+("\n".join([f"[{l['timestamp']}] {l['action']}" for l in logs]) if logs else "Пусто")[:4000])
    
    @dp.message(Command("backup"))
    async def backup_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            await msg.answer_document(FSInputFile(DB_PATH), caption="📦 Бекап базы данных")
        else: await msg.answer("❌ База пуста!")
    
    @dp.message(Command("restore"))
    async def restore_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        if not msg.document: await msg.answer("❌ Отправь файл .db"); return
        try:
            file = await bot.get_file(msg.document.file_id)
            await bot.download_file(file.file_path, DB_PATH)
            await init_db()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
                await db.commit()
            await msg.answer("✅ База восстановлена!")
        except Exception as e: await msg.answer(f"❌ {e}")
    
    @dp.message(Command("check_db"))
    async def check_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM cards") as c: cards=(await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM users") as c: users=(await c.fetchone())[0]
        await msg.answer(f"📊 🎴{cards} 👥{users}")
    
    @dp.message(Command("fix_fortune"))
    async def fix_fortune(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
            await db.commit()
        await msg.answer("✅ Всем выдано по 1 вращению колеса!")
    
    @dp.message(Command("set_rate"))
    async def set_rate(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: p=msg.text.split(); await set_setting(f'rate_{p[1]}',p[2]); await msg.answer(f"✅ {p[1]}={p[2]}%")
        except: await msg.answer("❌")
    
    @dp.message(Command("set_guarantor"))
    async def set_guar(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: p=msg.text.split(); await set_setting('guarantor_limit',p[1]); await msg.answer(f"✅ Гарант={p[1]}")
        except: await msg.answer("❌")
    
    @dp.message(Command("set_morning_rolls"))
    async def smr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('morning_rolls',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_morning_diamonds"))
    async def smd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('morning_diamonds',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_evening_rolls"))
    async def ser(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('evening_rolls',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_evening_diamonds"))
    async def sed(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('evening_diamonds',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_break_R"))
    async def sbr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_R',msg.text.split()[1]); await msg.answer("✅ R: +"+msg.text.split()[1]+"💎")
        except: pass
    
    @dp.message(Command("set_break_SR"))
    async def sbsr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_SR',msg.text.split()[1]); await msg.answer("✅ SR: +"+msg.text.split()[1]+"💎")
        except: pass
    
    @dp.message(Command("set_break_SSR"))
    async def sbssr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_SSR',msg.text.split()[1]); await msg.answer("✅ SSR: +"+msg.text.split()[1]+"💎")
        except: pass
    
    @dp.message(Command("set_break_L"))
    async def sbl(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_L',msg.text.split()[1]); await msg.answer("✅ L: +"+msg.text.split()[1]+"💎")
        except: pass
    
    @dp.message(Command("show_settings"))
    async def show_settings(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM settings ORDER BY key") as c: rows = await c.fetchall()
        await msg.answer("⚙️:\n\n" + "\n".join([f"{r[0]}={r[1]}" for r in rows])[:4000])
    
    async def resolve_user(username):
        username = username.replace("@","")
        if username.isdigit(): return int(username)
        user = await get_user_by_username(username)
        return user['user_id'] if user else None
    
    # ==================== 2. ТЕКСТОВЫЕ КНОПКИ ====================
    async def perform_regular_roll(uid):
        try:
            cards = await get_regular_cards()
            if not cards:
                return None, "В базе нет карт! Добавь через /addcard"
            card = random.choice(cards)
            if not card or not card['id']:
                return None, "Ошибка: невалидная карта"
            await add_card_to_user(uid, card['id'], is_original=True)
            booster = await get_booster(uid, 'luck')
            xp = int(10 * (1.5 if booster else 1.0))
            levels_gained, new_level = await add_xp(uid, xp)
            caption = f"{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
            if booster: caption += "\n⚡ Бустер удачи!"
            if levels_gained > 0: caption += f"\n⬆ Уровень {new_level}!"
            return card, caption
        except Exception as e:
            logger.error(f"Ошибка крутки: {e}")
            return None, f"Ошибка: {e}"
    
    async def perform_event_roll(uid):
        u = await get_user(uid)
        cards = await get_event_cards_active() if await get_active_event() else await get_event_cards()
        if not cards: return None, "🎪 Нет ивента!"
        L = [c for c in cards if c['is_L_card']]; N = [c for c in cards if not c['is_L_card']]
        prog = u['event_guarantor']; lim = await get_setting_int('guarantor_limit',50)
        if prog>=lim and L: card = random.choice(L); await upd_event_guarantor(uid,0); g="🎉 ГАРАНТ! "
        elif L and random.random()<await get_setting_int('event_rate_L',2)/100: card = random.choice(L); await upd_event_guarantor(uid,0); g="🌟 L! "
        else: card = random.choice(N if N else cards); await upd_event_guarantor(uid,prog+1); g=""
        await add_card_to_user(uid, card['id'], is_original=True)
        booster = await get_booster(uid, 'event')
        lvl, nl = await add_xp(uid, int(20*(1.5 if booster else 1)))
        cap = f"{g}{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        if booster: cap += "\n⚡ Бустер!"
        if lvl>0: cap += f"\n⬆ Ур.{nl}!"
        return card, cap
    
    async def send_card(msg, card, caption):
        uid = msg.from_user.id
        uc = await get_user_card(uid, card['id'])
        kb = None
        if uc and uc['quantity']>1:
            extra = uc['quantity']-1 if uc['is_original'] else uc['quantity']
            price = await get_break_price(card['rarity'])
            if await get_booster(uid,'break'): price = int(price*1.5)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔨 Разбить (+{extra*price}💎)", callback_data=f"break_{card['id']}")]
            ])
        try:
            if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=kb)
            else: await msg.answer(caption, reply_markup=kb)
        except: await msg.answer(caption, reply_markup=kb)
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_btn(msg):
        u = await get_user(msg.from_user.id)
        if not u or u['rolls']<=0: await msg.answer("❌ Нет круток!"); return
        await upd_rolls(msg.from_user.id, -1)
        card, caption = await perform_regular_roll(msg.from_user.id)
        if card is None:
            await msg.answer(f"❌ {caption}")
            return
        await update_task_progress(msg.from_user.id, 'roll')
        await update_weekly_progress(msg.from_user.id, 'weekly_rolls')
        ach = await check_achievements(msg.from_user.id)
        await send_card(msg, card, caption)
        if ach:
            for a in ach: await msg.answer(f"🏅 {a['icon']} {a['name']}!")
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): await msg.answer("🎉 +1 бонусная крутка!")
    
    @dp.message(F.text == "🎪 Ивент-крутка")
    async def event_btn(msg):
        u = await get_user(msg.from_user.id)
        if u['event_rolls']<=0: await msg.answer("❌ Нет ивент-круток!"); return
        await upd_event_rolls(msg.from_user.id, -1)
        card, caption = await perform_event_roll(msg.from_user.id)
        if card is None: await msg.answer(caption); return
        await update_task_progress(msg.from_user.id, 'event_roll')
        ach = await check_achievements(msg.from_user.id)
        await send_card(msg, card, caption)
        if ach:
            for a in ach: await msg.answer(f"🏅 {a['icon']} {a['name']}!")
    
    @dp.message(F.text == "💥 Разбить всё")
    async def break_all_btn(msg):
        cards = await get_user_cards(msg.from_user.id)
        total = 0; broken = 0
        booster = await get_booster(msg.from_user.id, 'break')
        for card in cards:
            if card['quantity']>1:
                qty = card['quantity']-1 if card['is_original'] else card['quantity']
                if qty>0:
                    price = await get_break_price(card['rarity'])
                    if booster: price = int(price*1.5)
                    diamonds = qty*price
                    async with aiosqlite.connect(DB_PATH) as db:
                        if card['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        await db.commit()
                    total += diamonds; broken += qty
                    for _ in range(qty):
                        await add_xp(msg.from_user.id, 2)
                        await update_task_progress(msg.from_user.id, 'break')
                        await update_weekly_progress(msg.from_user.id, 'weekly_break')
        if broken>0:
            await upd_diamonds(msg.from_user.id, total)
            await msg.answer(f"💥 Разбито {broken} повторов!\n💎 +{total} алмазов!" + ("\n⚡ Бустер!" if booster else ""))
        else: await msg.answer("❌ Нет повторов!")
    
    @dp.message(F.text == "🛍 Магазин")
    async def shop_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Обычные крутки", callback_data="shop_regular")],
            [InlineKeyboardButton(text="🎪 Ивент-крутки", callback_data="shop_event")],
        ])
        await msg.answer("🛍 Магазин:", reply_markup=kb)
    
    @dp.message(F.text == "⚡ Бустеры")
    async def booster_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍀 Удача - 5💎/1ч", callback_data="buy_booster_luck")],
            [InlineKeyboardButton(text="🎪 Ивент - 10💎/1ч", callback_data="buy_booster_event")],
            [InlineKeyboardButton(text="💎 Разбитие - 3💎/1ч", callback_data="buy_booster_break")],
        ])
        await msg.answer("⚡ Бустеры (x1.5 на 1 час):", reply_markup=kb)
    
    # ==================== КОЛЕСО ФОРТУНЫ (ИСПРАВЛЕНО) ====================
    async def spin_fortune(uid):
        """Вращает колесо фортуны для пользователя"""
        prizes = [p for p in FORTUNE_PRIZES for _ in range(p['weight'])]
        prize = random.choice(prizes)
        
        if prize['prize'] == 'roll':
            await upd_rolls(uid, prize['value'])
        elif prize['prize'] == 'diamond':
            await upd_diamonds(uid, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_regular_cards()
            if cards:
                card = random.choice(cards)
                await add_card_to_user(uid, card['id'], is_original=True)
                return card, f"🎡 Колесо фортуны!\n\n🎴 {rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        
        return None, f"🎡 Колесо фортуны!\n\n{prize['desc']}"
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_btn(msg):
        u = await get_user(msg.from_user.id)
        
        # Проверяем и исправляем значение
        if u['fortune_spins'] <= 0:
            await upd_fortune_spins(msg.from_user.id, 1)
            u = await get_user(msg.from_user.id)
        
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вр. - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вр. - 3💎", callback_data="fortune_buy_5")],
            ])
            await msg.answer("🎡 Нет вращений!\nКупить за алмазы:", reply_markup=kb)
        else:
            # Используем вращение
            await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
            await update_task_progress(msg.from_user.id, 'fortune')
            await update_weekly_progress(msg.from_user.id, 'weekly_fortune')
            
            card, caption = await spin_fortune(msg.from_user.id)
            await send_card(msg, card, caption) if card else await msg.answer(caption)
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call):
        am = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3}
        u = await get_user(call.from_user.id)
        
        if u['diamonds'] < prices[am]:
            await call.answer(f"❌ Нужно {prices[am]}💎!", show_alert=True)
            return
        
        await upd_diamonds(call.from_user.id, -prices[am])
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + am)
        
        # Запускаем вращения
        for _ in range(am):
            card, caption = await spin_fortune(call.from_user.id)
            if card:
                await send_card(call.message, card, caption)
            else:
                await call.message.answer(caption)
        
        await call.answer(f"✅ +{am} вращений!", show_alert=True)
    
    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(msg):
        u = await get_user(msg.from_user.id)
        if not u: return
        cards = await get_card_count(msg.from_user.id)
        xp_need = u['level']*100+50
        bar = "▓"*int(u['xp']/xp_need*10)+"░"*(10-int(u['xp']/xp_need*10)) if xp_need>0 else "▓"*10
        ds = await get_duel_stats(msg.from_user.id)
        w, l = (ds['wins'], ds['losses']) if ds else (0,0)
        await update_task_progress(msg.from_user.id, 'profile')
        await msg.answer(f"👤 {u['username']} | ⭐ Ур.{u['level']}\n📊 XP: {u['xp']}/{xp_need} [{bar}]\n💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}\n🎴{cards} 🎡{u['fortune_spins']}\n⚔️ Дуэли: {w}W/{l}L\n🔥 Серия: {u['login_streak']} дн.", reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "⬆ Уровни")
    async def levels_btn(msg):
        u = await get_user(msg.from_user.id)
        rewards = await get_level_rewards(msg.from_user.id)
        text = f"⬆ Ур.{u['level']} | XP: {u['xp']}/{u['level']*100+50}\n\n"
        if rewards:
            text += f"🎁 Доступно: {len(rewards)}!"
            buttons = [[InlineKeyboardButton(text=f"🎁 Ур.{r['level']}", callback_data=f"claim_level_{r['level']}")] for r in rewards[:5]]
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.answer(text+"Нет наград", reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "🎒 Инвентарь")
    @dp.callback_query(F.data.startswith("inv_page_"))
    async def inv_btn(msg_or_call, page: int = 0):
        if isinstance(msg_or_call, types.CallbackQuery):
            call = msg_or_call; msg = call.message
            if call.data.startswith("inv_page_"): page = int(call.data.split("_")[2])
            await call.answer(); uid = call.from_user.id; is_callback = True
        else:
            msg = msg_or_call; uid = msg.from_user.id; is_callback = False
        
        cards = await get_user_cards(uid)
        if not cards:
            if is_callback: await msg.edit_text("🎒 Инвентарь пуст")
            else: await msg.answer("🎒 Инвентарь пуст", reply_markup=permanent_keyboard())
            return
        
        cards_per_page = 10
        total_pages = (len(cards) + cards_per_page - 1) // cards_per_page
        page = max(0, min(page, total_pages - 1))
        start = page * cards_per_page; end = start + cards_per_page
        page_cards = cards[start:end]
        
        text = f"🎒 Инвентарь ({page+1}/{total_pages}):\n\n"; buttons = []
        for card in page_cards:
            orig = "🔒" if card['is_original'] else ""; ev = "🎪" if card['is_event_card'] else ""
            text += f"{orig}{ev}{rarity_emoji(card['rarity'])} #{card['id']} {card['name']} x{card['quantity']}\n"
            buttons.append([InlineKeyboardButton(text=f"📋 #{card['id']} {card['name']}", callback_data=f"cardinfo_{card['id']}")])
        
        nav_buttons = []
        if page > 0: nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_page_{page-1}"))
        if page < total_pages - 1: nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"inv_page_{page+1}"))
        if nav_buttons: buttons.append(nav_buttons)
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        if is_callback: await msg.edit_text(text, reply_markup=kb)
        else: await msg.answer(text, reply_markup=kb)
    
    @dp.message(F.text == "📋 Задания")
    async def tasks_btn(msg):
        tasks = await get_daily_tasks(msg.from_user.id)
        text = "📋 Ежедневные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            ti = next((x for x in TASK_TYPES if x['type']==t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): text += "\n🎉 +1🎲!"
        await msg.answer(text)
    
    @dp.message(F.text == "📅 Неделя")
    async def weekly_btn(msg):
        await ensure_weekly_tasks(msg.from_user.id)
        tasks = await get_weekly_tasks(msg.from_user.id)
        text = "📅 Еженедельные:\n\n"
        names = {"weekly_rolls":"🎲 20 круток","weekly_fortune":"🎡 Колесо 5 раз","weekly_break":"🔨 Разбить 10","weekly_ssr":"🟣 Выбить 3 SSR"}
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            text += f"{st} {names.get(t['task_type'],t['task_type'])} ({t['progress']}/{t['task_target']})\n"
        if all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            text += "\n🎁 +3💎 +2🎲 +1🎪\n/claim_weekly"
        elif all(t['completed'] for t in tasks):
            text += "\n✅ Награда получена"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "💱 Биржа")
    async def market_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Лоты", callback_data="market_view")],
            [InlineKeyboardButton(text="🔍 /find", callback_data="msi")],
            [InlineKeyboardButton(text="📊 /sell", callback_data="msi2")],
        ])
        await msg.answer("💱 Биржа:", reply_markup=kb)
    
    @dp.message(F.text == "🏪 Аукцион")
    async def auc_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Активные", callback_data="auction_view")],
            [InlineKeyboardButton(text="📊 /auction", callback_data="auction_info")],
        ])
        await msg.answer("🏪 Аукцион:", reply_markup=kb)
    
    @dp.message(F.text == "🔄 Обмен")
    async def trade_btn(msg): await msg.answer("🔄 /trade @user ID_моей ID_его")
    
    @dp.message(F.text == "⚔️ Дуэль")
    async def duel_btn(msg): await msg.answer("⚔️ /duel @user ID [ставка]")
    
    @dp.message(F.text == "👥 Друзья")
    async def friends_btn(msg):
        friends = await get_friends(msg.from_user.id)
        text = "👥 Друзья:\n\n"+("\n".join([f"• @{f['username']}" for f in friends]) if friends else "Пока нет")+"\n\n/friend add @user"
        await msg.answer(text)
    
    @dp.message(F.text == "🏰 Гильдия")
    async def guild_btn(msg):
        guild = await get_user_guild(msg.from_user.id)
        if guild:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id=?", (guild['id'],)) as c: cnt = (await c.fetchone())[0]
            await msg.answer(f"🏰 {guild['name']}\n👥 {cnt}")
        else: await msg.answer("🏰 /guild create НАЗВАНИЕ | /guild join НАЗВАНИЕ")
    
    @dp.message(F.text == "⚔️ Война гильдий")
    async def war_btn(msg):
        season = await get_active_war_season(); guild = await get_user_guild(msg.from_user.id)
        if not season: await msg.answer("⚔️ Нет войны!"); return
        if not guild: await msg.answer("❌ Не в гильдии!"); return
        if season['status']=='selection': await msg.answer("⚔️ Выбор карт!\n/war_pick ID")
        else:
            ranking = await get_guild_war_ranking(season['id'])
            text = "⚔️ БИТВЫ!\n\n🏆:\n"+("\n".join([f"{i+1}. {g['name']} - {g['total_points']} очков" for i,g in enumerate(ranking[:10])]) if ranking else "Нет")
            await msg.answer(text)
    
    @dp.message(F.text == "📚 Все карты")
    async def allc_btn(msg):
        cards = await get_all_cards()
        if not cards: return
        buttons = []; row = []
        for c in cards:
            if not c['is_event_card']:
                row.append(InlineKeyboardButton(text=f"#{c['id']}", callback_data=f"cardinfo_{c['id']}"))
                if len(row)==5: buttons.append(row); row=[]
        if row: buttons.append(row)
        await msg.answer("📚 Обычные:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
    
    @dp.message(F.text == "🏆 Лидеры")
    async def lead_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎴 По картам", callback_data="lead_cards")],
            [InlineKeyboardButton(text="⭐ По уровню", callback_data="lead_level")],
            [InlineKeyboardButton(text="⚔️ По дуэлям", callback_data="lead_duels")],
        ])
        await msg.answer("🏆 Лидеры:", reply_markup=kb)
    
    @dp.callback_query(F.data == "lead_cards")
    async def lead_cards(call: types.CallbackQuery):
        top = await get_leaders(10)
        text = "🏆 Топ-10 по картам:\n\n"
        if top:
            for i, u in enumerate(top):
                text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} {u['username']} - {u['total']} карт\n"
        else: text += "Пусто\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_cards")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "lead_level")
    async def lead_level(call: types.CallbackQuery):
        top = await get_level_leaders(10)
        text = "⭐ Топ-10 по уровню:\n\n"
        if top:
            for i, u in enumerate(top):
                text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} {u['username']} - Ур.{u['level']}\n"
        else: text += "Пусто\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_level")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "lead_duels")
    async def lead_duels(call: types.CallbackQuery):
        top = await get_duel_leaders(10)
        text = "⚔️ Топ-10 дуэлянтов:\n\n"
        if top:
            for i, u in enumerate(top):
                text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} {u['username']} - {u['wins']}W/{u['losses']}L\n"
        else: text += "Пусто\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_duels")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "lead_back")
    async def lead_back(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎴 По картам", callback_data="lead_cards")],
            [InlineKeyboardButton(text="⭐ По уровню", callback_data="lead_level")],
            [InlineKeyboardButton(text="⚔️ По дуэлям", callback_data="lead_duels")],
        ])
        await call.message.edit_text("🏆 Лидеры:", reply_markup=kb); await call.answer()
    
    @dp.message(F.text == "🏅 Достижения")
    async def ach_btn(msg):
        u = await get_user(msg.from_user.id); cards = await get_user_cards(msg.from_user.id)
        tc = sum(c['quantity'] for c in cards)
        text = "🏅 Достижения:\n\n"
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                    row = await c.fetchone()
                text += f"{'🎁' if row and row[0] and not row[1] else '✅' if row and row[0] else '🔒'} {ach['icon']} {ach['name']}\n"
        buttons = []
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                    row = await c.fetchone()
                if row and row[0] and not row[1]:
                    buttons.append([InlineKeyboardButton(text=f"🎁 {ach['icon']} {ach['name']}", callback_data=f"claim_ach_{ach['id']}")])
        await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else permanent_keyboard())
    
    @dp.message(F.text == "🎫 Промокод")
    async def promo_btn(msg, state): await msg.answer("🎫 Введи код:"); await state.set_state(PromoStates.waiting_for_code)
    
    @dp.message(F.text == "❓ Помощь")
    async def help_btn(msg): await msg.answer("🎲 Крутить | 🛍 Магазин\n🎪 Ивент | 🎡 Колесо\n📋 Задания | 📅 Неделя\n💱 Биржа | 🏪 Аукцион\n⚔️ /duel @user ID\n👥 Друзья | 🏰 Гильдии\n💥 Разбить всё | ⚡ Бустеры\n💎 R=1 SR=5 SSR=10 L=20\n🕐 7:00 и 17:00 МСК")
    
    # ==================== 3. FSM ====================
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def an(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(name=msg.text.strip()); await msg.answer("📝 Шаг 2/4\nОписание:"); await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def ad(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nРедкость:", reply_markup=rarity_keyboard()); await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def ap(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data(); file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity']=='L'
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?,?,?,?,?)",(data['name'],data['description'],file_id,data['rarity'],is_L)); await db.commit()
        await msg.answer(f"✅ {data['name']} добавлена!"); await state.clear()
    
    @dp.message(StateFilter(BreakCustomStates.waiting_for_quantity))
    async def bcm(msg, state):
        try:
            q = int(msg.text.strip()); d = await state.get_data()
            if q<1 or q>d['mx']: await msg.answer(f"❌ 1-{d['mx']}!"); return
            uc = await get_user_card(msg.from_user.id, d['bcid'])
            if not uc: await state.clear(); return
            price = await get_break_price(uc['rarity'])
            if await get_booster(msg.from_user.id,'break'): price = int(price*1.5)
            if await remove_card(msg.from_user.id, d['bcid'], q): await upd_diamonds(msg.from_user.id, q*price); await msg.answer(f"✅ +{q*price}💎!")
            await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(GiveAllStates.waiting_for_amount))
    async def process_giveall(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data(); t = data.get('giveall_type')
        try:
            am = int(msg.text.strip()); users = await get_all_users()
            for u in users:
                try:
                    if t=='diamonds': await upd_diamonds(u['user_id'],am)
                    elif t=='rolls': await upd_rolls(u['user_id'],am)
                    elif t=='event': await upd_event_rolls(u['user_id'],am)
                    elif t=='fortune': await upd_fortune_spins(u['user_id'],am)
                except: pass
            await msg.answer(f"✅ {am} для всех!"); await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(BroadcastStates.waiting_for_broadcast))
    async def process_broadcast(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        users = await get_all_users(); sent = 0
        for u in users:
            try: await bot.send_message(u['user_id'], msg.text or "📢"); sent+=1; await asyncio.sleep(0.05)
            except: pass
        await msg.answer(f"✅ {sent}/{len(users)}"); await state.clear()
    
    @dp.message(StateFilter(AuctionStates.waiting_for_bid))
    async def bid_msg(msg, state):
        try:
            am = int(msg.text.strip()); d = await state.get_data()
            if await bid_auction(d['aid'], msg.from_user.id, am): await msg.answer("✅ Ставка!")
            else: await msg.answer("❌")
            await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(PromoStates.waiting_for_code))
    async def promo_code(msg, state):
        code = msg.text.strip().upper()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM promocodes WHERE code=? AND uses_left>0", (code,)) as c: promo = await c.fetchone()
        if not promo: await msg.answer("❌ Недействителен!")
        else:
            if promo['type']=='diamonds': await upd_diamonds(msg.from_user.id, promo['value'])
            elif promo['type']=='rolls': await upd_rolls(msg.from_user.id, promo['value'])
            elif promo['type']=='event_rolls': await upd_event_rolls(msg.from_user.id, promo['value'])
            async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE promocodes SET uses_left=uses_left-1 WHERE code=?",(code,)); await db.commit()
            await msg.answer(f"✅ +{promo['value']} {promo['type']}!")
        await state.clear()
    
    @dp.message(StateFilter(EventStates.waiting_for_deck_name))
    async def deck_name(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        did = await create_deck(msg.text.strip()); await msg.answer(f"✅ ID:{did}"); await state.clear()
    
    # ==================== 4. CALLBACK-ОБРАБОТЧИКИ ====================
    @dp.callback_query(F.data == "shop_regular")
    async def shop_reg(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1🎲 - 2💎", callback_data="buy_reg_1")],
            [InlineKeyboardButton(text="5🎲 - 10💎", callback_data="buy_reg_5")],
            [InlineKeyboardButton(text="10🎲 - 50💎", callback_data="buy_reg_10")],
        ])
        await call.message.edit_text("🎲 Обычные:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "shop_event")
    async def shop_evt(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1🎪 - 10💎", callback_data="buy_evt_1")],
            [InlineKeyboardButton(text="5🎪 - 35💎", callback_data="buy_evt_5")],
            [InlineKeyboardButton(text="10🎪 - 70💎", callback_data="buy_evt_10")],
        ])
        await call.message.edit_text("🎪 Ивент:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data.startswith("buy_reg_"))
    async def buy_reg(call):
        am = int(call.data.split("_")[2]); prices = {1:2,5:10,10:50}
        u = await get_user(call.from_user.id)
        if u['diamonds']<prices[am]: await call.answer(f"❌ {prices[am]}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -prices[am]); await upd_rolls(call.from_user.id, am)
        await call.answer(f"✅ +{am}🎲!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("buy_evt_"))
    async def buy_evt(call):
        am = int(call.data.split("_")[2]); prices = {1:10,5:35,10:70}
        u = await get_user(call.from_user.id)
        if u['diamonds']<prices[am]: await call.answer(f"❌ {prices[am]}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -prices[am]); await upd_event_rolls(call.from_user.id, am)
        await call.answer(f"✅ +{am}🎪!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_luck")
    async def bbl(call):
        if await buy_booster(call.from_user.id,'luck',1,5): await call.answer("✅ Активирован!")
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_event")
    async def bbe(call):
        if await buy_booster(call.from_user.id,'event',1,10): await call.answer("✅ Активирован!")
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_break")
    async def bbb(call):
        if await buy_booster(call.from_user.id,'break',1,3): await call.answer("✅ Активирован!")
        else: await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("claim_level_"))
    async def claim_level(call):
        level = int(call.data.split("_")[2])
        reward = await claim_level_reward(call.from_user.id, level)
        if reward:
            desc = " ".join([f"+{v}{'🎲' if k=='rolls' else '💎' if k=='diamonds' else '🎪'}" for k,v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else: await call.answer("❌ Уже получена!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("cardinfo_"))
    async def card_info(call):
        card_id = int(call.data.split("_")[1]); card = await get_card_by_id(card_id)
        if not card: return
        uc = await get_user_card(call.from_user.id, card_id); qty = uc['quantity'] if uc else 0
        price = await get_break_price(card['rarity'])
        text = f"{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']} ({price}💎)\n📎 #{card['id']}"
        if card['is_L_card']: text += "\n🌟 L-КАРТА!"
        if qty: text += f"\n📦 У вас: {qty}"
        kb_buttons = []
        if qty>1:
            extra = qty-1 if uc['is_original'] else qty
            kb_buttons.append([InlineKeyboardButton(text=f"🔨 +{price}💎", callback_data=f"breakone_{card_id}"),InlineKeyboardButton(text=f"💥 +{extra*price}💎", callback_data=f"break_{card_id}")])
            kb_buttons.append([InlineKeyboardButton(text="🔢 Число...", callback_data=f"breakcustom_{card_id}")])
        if qty: kb_buttons.append([InlineKeyboardButton(text="💱 Продать", callback_data=f"sellcard_{card_id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        try:
            if card['file_id']: await call.message.answer_photo(photo=card['file_id'], caption=text, reply_markup=kb)
            else: await call.message.answer(text, reply_markup=kb)
        except: await call.message.answer(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("breakone_"))
    async def bo(call):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc: return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id,'break'): price = int(price*1.5)
        if await remove_card(call.from_user.id, cid, 1): await upd_diamonds(call.from_user.id, price); await call.answer(f"✅ +{price}💎!", show_alert=True)
        else: await call.answer("❌", show_alert=True)
    
    @dp.callback_query(F.data.startswith("break_"))
    async def ba(call):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity']<=1: return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id,'break'): price = int(price*1.5)
        bq = uc['quantity']-1 if uc['is_original'] else uc['quantity']; total = bq*price
        async with aiosqlite.connect(DB_PATH) as db:
            if uc['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            await db.commit()
        await upd_diamonds(call.from_user.id, total); await call.answer(f"✅ +{total}💎!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("breakcustom_"))
    async def bc(call, state):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity']<=1: return
        mx = uc['quantity']-1 if uc['is_original'] else uc['quantity']
        await state.update_data(bcid=cid, mx=mx)
        await call.message.answer(f"🔢 Сколько? (1-{mx}):"); await state.set_state(BreakCustomStates.waiting_for_quantity); await call.answer()
    
    @dp.callback_query(F.data.startswith("sellcard_"))
    async def sc(call): await call.message.answer(f"💱 /sell {call.data.split('_')[1]} ЦЕНА"); await call.answer()
    
    @dp.callback_query(F.data == "market_view")
    async def mv(call):
        listings = await get_market_listings()
        if not listings: await call.message.answer("📋 Пусто"); await call.answer(); return
        text = "📋 Лоты:\n\n"; buttons = []
        for l in listings[:10]:
            text += f"#{l['id']} {rarity_emoji(l['rarity'])} {l['name']} | {l['price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f"{l['price']}💎", callback_data=f"mbuy_{l['id']}")])
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await call.answer()
    
    @dp.callback_query(F.data == "msi")
    async def msi(call): await call.message.answer("/find НОМЕР"); await call.answer()
    @dp.callback_query(F.data == "msi2")
    async def msi2(call): await call.message.answer("/sell НОМЕР ЦЕНА"); await call.answer()
    
    @dp.callback_query(F.data.startswith("mbuy_"))
    async def mb(call):
        lid = int(call.data.split("_")[1])
        if await buy_listing(lid, call.from_user.id): await call.answer("✅ Куплено!", show_alert=True)
        else: await call.answer("❌", show_alert=True)
    
    @dp.callback_query(F.data == "auction_view")
    async def av(call):
        auctions = await get_active_auctions()
        if not auctions: await call.message.answer("📋 Нет"); await call.answer(); return
        text = "📋 Аукционы:\n\n"; buttons = []
        for a in auctions[:10]:
            text += f"#{a['id']} {rarity_emoji(a['rarity'])} {a['name']} | {a['current_price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f">{a['current_price']}💎", callback_data=f"abid_{a['id']}")])
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await call.answer()
    
    @dp.callback_query(F.data == "auction_info")
    async def ai(call): await call.message.answer("📊 /auction ID СТАРТ_ЦЕНА"); await call.answer()
    
    @dp.callback_query(F.data.startswith("abid_"))
    async def abid(call, state):
        await state.update_data(aid=int(call.data.split("_")[1]))
        await call.message.answer("💰 Сумма:"); await state.set_state(AuctionStates.waiting_for_bid); await call.answer()
    
    @dp.callback_query(F.data.startswith("aduel_"))
    async def ad(call):
        duel_id = int(call.data.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM duels WHERE id=? AND status='pending'", (duel_id,)) as c: duel = await c.fetchone()
        if not duel: await call.answer("Дуэль не найдена!", show_alert=True); return
        await call.message.answer("⚔️ Выбери карту: /pick ID"); await call.answer()
    
    @dp.callback_query(F.data.startswith("dduel_"))
    async def dd(call):
        duel_id = int(call.data.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='declined' WHERE id=?", (duel_id,)); await db.commit()
            async with db.execute("SELECT challenger_id FROM duels WHERE id=?", (duel_id,)) as c: row = await c.fetchone()
        if row:
            try: await bot.send_message(row[0], f"❌ @{call.from_user.username} отклонил")
            except: pass
        await call.message.edit_text("❌ Отклонен"); await call.answer()
    
    @dp.callback_query(F.data.startswith("tac_"))
    async def tac(call):
        p = call.data.split("_"); fu, fc, tc = int(p[1]), int(p[2]), int(p[3])
        if not await get_user_card(fu, fc) or not await get_user_card(call.from_user.id, tc): await call.message.edit_text("❌"); return
        await remove_card(fu, fc); await remove_card(call.from_user.id, tc)
        await add_card_to_user(call.from_user.id, fc); await add_card_to_user(fu, tc)
        await call.message.edit_text("✅!"); await call.answer()
    
    @dp.callback_query(F.data.startswith("tdc_"))
    async def tdc(call): await call.message.edit_text("❌"); await call.answer()
    
    @dp.callback_query(F.data.startswith("claim_ach_"))
    async def claim_ach(call):
        ach_id = call.data.split("_", 2)[2]
        reward = await claim_achievement_reward(call.from_user.id, ach_id)
        if reward:
            desc = " ".join([f"+{v}{'💎' if k=='diamonds' else '🎲' if k=='rolls' else '🎪'}" for k,v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else: await call.answer("❌ Уже получена!", show_alert=True)
    
    # Админские callback
    @dp.callback_query(F.data == "admin_add")
    async def aas(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(is_event=False)
        await call.message.answer("📝 Шаг 1/4\nВведи #НОМЕР ИМЯ"); await state.set_state(AddCardStates.waiting_for_name); await call.answer()
    
    @dp.callback_query(F.data == "admin_list")
    async def alc(call):
        if call.from_user.id not in ADMIN_IDS: return
        cards = await get_all_cards()
        if not cards: await call.message.answer("📋 Нет"); await call.answer(); return
        text = "📋 Карты:\n\n"
        for c in cards: text += f"#{c['id']} {rarity_emoji(c['rarity'])} {c['name']}\n"
        for i in range(0, len(text), 4000): await call.message.answer(text[i:i+4000])
        await call.answer()
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def agm(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="gd")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="gr")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="ge")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("🎁 Выдача:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_give_all")
    async def admin_give_all(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Всем алмазы", callback_data="giveall_diamonds")],
            [InlineKeyboardButton(text="🎲 Всем крутки", callback_data="giveall_rolls")],
            [InlineKeyboardButton(text="🎪 Всем ивент", callback_data="giveall_event")],
            [InlineKeyboardButton(text="🎡 Всем колесо", callback_data="giveall_fortune")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("👥 Всем:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_broadcast")
    async def abr(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("📢 Сообщение:"); await state.set_state(BroadcastStates.waiting_for_broadcast); await call.answer()
    
    @dp.callback_query(F.data == "admin_ban")
    async def ab(call): await call.message.answer("/ban @user | /unban @user"); await call.answer()
    
    @dp.callback_query(F.data == "admin_event_menu")
    async def admin_event_menu(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📁 Создать колоду", callback_data="event_create_deck")],
            [InlineKeyboardButton(text="➕ В колоду", callback_data="event_add_to_deck_menu")],
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="event_start")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="event_end")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("🎪 Ивенты:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_war_menu")
    async def awm(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать", callback_data="war_start")],
            [InlineKeyboardButton(text="⚔️ Битвы", callback_data="war_battles")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="war_end")],
            [InlineKeyboardButton(text="🏆 Награды", callback_data="war_reward")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("⚔️ Война:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_settings")
    async def admin_settings(call):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.edit_text("⚙️ /set_rate R 70\n/set_guarantor 50\n/set_break_R 1\n/set_morning_rolls 2\n/show_settings", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="🔙", callback_data="admin_back")]])); await call.answer()
    
    @dp.callback_query(F.data == "admin_backup")
    async def admin_backup_info(call): await call.message.answer("💾 /backup - скачать\n/restore - восстановить\n/check_db - проверить"); await call.answer()
    
    @dp.callback_query(F.data == "admin_back")
    async def admin_back(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Карта", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="👥 Всем", callback_data="admin_give_all")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="⛔ Бан", callback_data="admin_ban")],
            [InlineKeyboardButton(text="🎪 Ивенты", callback_data="admin_event_menu")],
            [InlineKeyboardButton(text="⚔️ Война", callback_data="admin_war_menu")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
            [InlineKeyboardButton(text="💾 Бекап", callback_data="admin_backup")],
        ])
        await call.message.edit_text("👑 Админ-панель", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "gd")
    async def gd(call): await call.message.answer("/givediamonds @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "gr")
    async def gr(call): await call.message.answer("/giverolls @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "ge")
    async def ge(call): await call.message.answer("/giveevent @user кол-во"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_diamonds")
    async def gald(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='diamonds')
        await call.message.answer("💎 Сколько?"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_rolls")
    async def galr(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='rolls')
        await call.message.answer("🎲 Сколько?"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_event")
    async def gale(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='event')
        await call.message.answer("🎪 Сколько?"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_fortune")
    async def galf(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='fortune')
        await call.message.answer("🎡 Сколько?"); await call.answer()
    
    @dp.callback_query(F.data == "event_create_deck")
    async def ecd(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("📁 Название:"); await state.set_state(EventStates.waiting_for_deck_name); await call.answer()
    
    @dp.callback_query(F.data == "event_add_to_deck_menu")
    async def eatdm(call):
        if call.from_user.id not in ADMIN_IDS: return
        decks = await get_all_decks()
        if not decks: await call.message.answer("❌ Нет колод!"); await call.answer(); return
        buttons = [[InlineKeyboardButton(text=f"📁 {d['name']}", callback_data=f"addtodeck_{d['id']}")] for d in decks]
        await call.message.answer("Выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await call.answer()
    
    @dp.callback_query(F.data.startswith("addtodeck_"))
    async def atd(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(current_deck_id=int(call.data.split("_")[1]), is_event=True)
        await call.message.answer("📝 Введи #НОМЕР ИМЯ"); await state.set_state(AddCardStates.waiting_for_name); await call.answer()
    
    @dp.callback_query(F.data == "event_start")
    async def es(call):
        if call.from_user.id not in ADMIN_IDS: return
        decks = await get_all_decks()
        if not decks: await call.message.answer("❌"); await call.answer(); return
        buttons = [[InlineKeyboardButton(text=f"📁 {d['name']}", callback_data=f"startev_{d['id']}")] for d in decks]
        await call.message.answer("▶️ Выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await call.answer()
    
    @dp.callback_query(F.data.startswith("startev_"))
    async def se(call):
        if call.from_user.id not in ADMIN_IDS: return
        did = int(call.data.split("_")[1]); await start_event(did); await call.message.answer("✅ Запущен!"); await call.answer()
    
    @dp.callback_query(F.data == "event_end")
    async def ee(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="confirm_end_event")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="admin_event_menu")],
        ])
        await call.message.answer("⏹ Завершить?", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "confirm_end_event")
    async def cee(call):
        if call.from_user.id not in ADMIN_IDS: return
        await end_current_event(); await call.message.answer("✅ Завершён!"); await call.answer()
    
    @dp.callback_query(F.data == "war_start")
    async def ws_btn(call):
        if call.from_user.id not in ADMIN_IDS: return
        sid = await start_war_season(); await call.message.answer(f"✅ Сезон #{sid}!"); await call.answer()
    
    @dp.callback_query(F.data == "war_battles")
    async def wb_btn(call):
        season = await get_active_war_season()
        if season: await start_war_battles(season['id']); await call.message.answer("⚔️ Битвы!"); await call.answer()
    
    @dp.callback_query(F.data == "war_end")
    async def we_btn(call): await end_current_war(); await call.message.answer("⏹ Завершена!"); await call.answer()
    
    @dp.callback_query(F.data == "war_reward")
    async def wr_btn(call):
        if call.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM guild_war_seasons WHERE status='ended' ORDER BY id DESC LIMIT 1") as c: last = await c.fetchone()
        if not last: await call.message.answer("❌ Нет сезонов!"); await call.answer(); return
        ranking = await get_guild_war_ranking(last['id'])
        if not ranking: await call.message.answer("❌ Нет данных!"); await call.answer(); return
        text = "🏆 Награды:\n\n"
        rewards = [(100,10,5),(70,7,3),(50,5,2),(30,3,1),(15,1,0)]
        for i, g in enumerate(ranking[:5]):
            if i < len(rewards):
                r = rewards[i]; text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} {g['name']}: 💎{r[0]} 🎲{r[1]} 🎪{r[2]}\n"
                async with aiosqlite.connect(DB_PATH) as db2:
                    async with db2.execute("SELECT user_id FROM guild_members WHERE guild_id=?", (g['id'],)) as c2:
                        for m in await c2.fetchall(): await upd_diamonds(m[0], r[0]); await upd_rolls(m[0], r[1]); await upd_event_rolls(m[0], r[2])
        await call.message.answer(text); await call.answer()
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def ar(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(rarity=call.data.split("_")[1])
        await call.message.answer("📝 Шаг 4/4\nОтправь фото или 'нет'"); await state.set_state(AddCardStates.waiting_for_photo); await call.answer()
    
    # ==================== ДУЭЛИ ====================
    async def resolve_duel(duel):
        cc = await get_card_by_id(duel['challenger_card_id']); oc = await get_card_by_id(duel['opponent_card_id'])
        rp = {'R':1,'SR':2,'SSR':3,'L':4}; cp, op = rp.get(cc['rarity'],0), rp.get(oc['rarity'],0)
        wid = duel['challenger_id'] if cp>op else (duel['opponent_id'] if op>cp else (duel['challenger_id'] if cc['id']>oc['id'] else duel['opponent_id']))
        lid = duel['opponent_id'] if wid==duel['challenger_id'] else duel['challenger_id']
        await upd_diamonds(wid, duel['bet_amount']); await upd_diamonds(lid, -duel['bet_amount'])
        await add_xp(wid, 15); await add_xp(lid, 5)
        await update_duel_stats(wid, True); await update_duel_stats(lid, False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=?", (wid, duel['id'])); await db.commit()
        winner = await get_user(wid)
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try: await bot.send_message(uid, f"⚔️ Победитель: @{winner['username']}\n💎 Ставка: {duel['bet_amount']}")
            except: pass
    
    # ==================== ВЫДАЧИ ====================
    async def morning_bonus():
        try:
            mr = await get_setting_int('morning_rolls',2); md = await get_setting_int('morning_diamonds',3)
            mf = await get_setting_int('morning_fortune',1); me = await get_setting_int('morning_event',1)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(f"UPDATE users SET rolls=rolls+{mr}, diamonds=diamonds+{md}, fortune_spins={mf}, event_rolls=event_rolls+{me}, bonus_roll_received=0")
                await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),)); await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c: users = await c.fetchall()
            for u in users:
                try: await bot.send_message(u['user_id'], f"🌅 Доброе утро!\n\n🎲+{mr} 🎡+{mf} 🎪+{me} 💎+{md}")
                except: pass
            try: shutil.copy2(DB_PATH, DB_PATH + ".backup")
            except: pass
            logger.info("☀️ Утро")
        except Exception as e: logger.error(f"Утро: {e}")
    
    async def evening_bonus():
        try:
            er = await get_setting_int('evening_rolls',2); ed = await get_setting_int('evening_diamonds',3)
            ef = await get_setting_int('evening_fortune',1); ee = await get_setting_int('evening_event',1)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(f"UPDATE users SET rolls=rolls+{er}, diamonds=diamonds+{ed}, fortune_spins={ef}, event_rolls=event_rolls+{ee}"); await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c: users = await c.fetchall()
            for u in users:
                try: await bot.send_message(u['user_id'], f"🌆 Добрый вечер!\n\n🎲+{er} 🎡+{ef} 🎪+{ee} 💎+{ed}")
                except: pass
            logger.info("🌆 Вечер")
        except Exception as e: logger.error(f"Вечер: {e}")
    
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(morning_bonus, 'cron', hour=7, minute=0)
    scheduler.add_job(evening_bonus, 'cron', hour=17, minute=0)
    scheduler.add_job(finish_auctions, 'interval', minutes=10)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
