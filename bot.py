import asyncio
import aiosqlite
import random
import logging
import sys
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
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
        await db.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, rolls INTEGER DEFAULT 2, diamonds INTEGER DEFAULT 0, total_rolls INTEGER DEFAULT 0, fortune_spins INTEGER DEFAULT 1, event_rolls INTEGER DEFAULT 0, event_guarantor INTEGER DEFAULT 0, bonus_roll_received BOOLEAN DEFAULT 0, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1, banned BOOLEAN DEFAULT 0)""")
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
        await db.execute("""CREATE TABLE IF NOT EXISTS friends (user_id INTEGER, friend_id INTEGER, status TEXT DEFAULT 'pending', PRIMARY KEY (user_id, friend_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, type TEXT, value INTEGER, uses_left INTEGER, created_by INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS level_rewards (user_id INTEGER, level INTEGER, claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, level))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS card_decks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS deck_cards (deck_id INTEGER, card_id INTEGER, PRIMARY KEY (deck_id, card_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS active_events (id INTEGER PRIMARY KEY AUTOINCREMENT, deck_id INTEGER, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP, status TEXT DEFAULT 'active')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        defaults = {'morning_rolls':'2','morning_diamonds':'3','morning_fortune':'1','morning_event':'1','evening_rolls':'2','evening_diamonds':'3','evening_fortune':'1','evening_event':'1','break_R':'1','break_SR':'5','break_SSR':'10','break_L':'20'}
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
    return await get_setting_int(f'break_{rarity}', {'R':1,'SR':5,'SSR':10,'L':20}.get(rarity,1))

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

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            return await c.fetchall()

# ==================== ЗАДАНИЯ (умные) ====================
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

async def refresh_tasks_if_needed(uid):
    tasks = await get_daily_tasks(uid)
    needs_refresh = False
    for t in tasks:
        if t['task_type'] == 'break' and not await has_duplicates(uid): needs_refresh = True; break
        if t['task_type'] == 'event_roll' and not await is_event_active(): needs_refresh = True; break
    if needs_refresh:
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM daily_tasks WHERE user_id=? AND date=?", (uid, today))
            await db.commit()
        await ensure_daily_tasks(uid)
        return await get_daily_tasks(uid)
    return tasks

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

async def get_market_listings(card_id=None, page=0, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if card_id:
            async with db.execute("SELECT m.*, c.name, c.rarity, c.is_L_card, c.file_id FROM market m JOIN cards c ON m.card_id=c.id WHERE m.card_id=? ORDER BY m.price ASC LIMIT ? OFFSET ?", (card_id, limit, page*limit)) as c:
                return await c.fetchall()
        async with db.execute("SELECT m.*, c.name, c.rarity, c.is_L_card, c.file_id FROM market m JOIN cards c ON m.card_id=c.id ORDER BY m.created_at DESC LIMIT ? OFFSET ?", (limit, page*limit)) as c:
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
        await db.execute("INSERT OR IGNORE INTO friends (user_id,friend_id,status) VALUES (?,?,'accepted')", (uid, fid))
        await db.commit()

async def get_friends(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT f.friend_id, u.username FROM friends f JOIN users u ON f.friend_id=u.user_id WHERE f.user_id=? AND f.status='accepted'", (uid,)) as c:
            return await c.fetchall()

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

async def get_war_card(season_id, guild_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_war_cards WHERE season_id=? AND guild_id=? AND user_id=?", (season_id, guild_id, user_id)) as c:
            return await c.fetchone()

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
            [KeyboardButton(text="💥 Разбить всё"), KeyboardButton(text="❓ Помощь")],
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
        await msg.answer("✨ Приветствую тебя путник! ✨\n\n🎲 Выдачи 7:00 и 17:00 МСК\n🌟 L-карты в ивентах\n💎 R=1 SR=5 SSR=10 L=20\n⚔️ /duel @user ID_карты", reply_markup=permanent_keyboard())
    
    # ==================== КРУТКИ ====================
    async def perform_regular_roll(uid):
        cards = await get_regular_cards()
        if not cards: return None, "Нет обычных карт"
        card = random.choice(cards)
        await add_card_to_user(uid, card['id'], is_original=True)
        levels_gained, new_level = await add_xp(uid, 10)
        await update_weekly_progress(uid, 'weekly_rolls')
        if card['rarity'] == 'SSR': await update_weekly_progress(uid, 'weekly_ssr')
        caption = f"{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        if levels_gained > 0: caption += f"\n⬆ Уровень {new_level}!"
        return card, caption, levels_gained, new_level
    
    async def perform_event_roll(uid):
        u = await get_user(uid)
        event = await get_active_event()
        cards = await get_event_cards_active() if event else await get_event_cards()
        if not cards: return None, "🎪 Нет активного ивента!", 0, u['level']
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        progress = u['event_guarantor']
        is_guaranteed = progress >= 50
        guarantee_text = ""
        if is_guaranteed and L_cards:
            card = random.choice(L_cards); await upd_event_guarantor(uid, 0)
            guarantee_text = "🎉 ИВЕНТ-ГАРАНТ! "; progress = 0
        else:
            if L_cards and random.random() < 0.02:
                card = random.choice(L_cards); await upd_event_guarantor(uid, 0)
                guarantee_text = "🌟 L-КАРТА! "; progress = 0
            else:
                card = random.choice(normal if normal else cards)
                progress += 1; await upd_event_guarantor(uid, progress)
        await add_card_to_user(uid, card['id'], is_original=True)
        levels_gained, new_level = await add_xp(uid, 20)
        caption = f"{guarantee_text}{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}\n📊 Гарант: {progress}/50"
        if levels_gained > 0: caption += f"\n⬆ Уровень {new_level}!"
        return card, caption, levels_gained, new_level
    
    async def send_card_with_break(msg, card, caption):
        uid = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id
        user_card = await get_user_card(uid, card['id'])
        kb = None
        if user_card and user_card['quantity'] > 1:
            extra = user_card['quantity'] - 1 if user_card['is_original'] else user_card['quantity']
            price = await get_break_price(card['rarity'])
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
        if u['event_rolls'] <= 0: await msg.answer(f"❌ Нет ивент-круток!\n📊 Гарант: {u['event_guarantor']}/50"); return
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
        for card in cards:
            if card['quantity'] > 1:
                qty = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if qty > 0:
                    price = await get_break_price(card['rarity'])
                    diamonds = qty * price
                    async with aiosqlite.connect(DB_PATH) as db:
                        if card['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (msg.from_user.id, card['id']))
                        await db.commit()
                    total_diamonds += diamonds; broken += qty
        if broken > 0:
            await upd_diamonds(msg.from_user.id, total_diamonds)
            await msg.answer(f"💥 Разбито {broken} повторов!\n💎 +{total_diamonds} алмазов!")
        else: await msg.answer("❌ Нет повторов!")
    
    # ==================== ДУЭЛИ ====================
    @dp.message(F.text == "⚔️ Дуэль")
    async def duel_btn(msg): await msg.answer("⚔️ /duel @user ID_карты\nПример: /duel @username 5")
    
    @dp.message(Command("duel"))
    async def dcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 3: await msg.answer("❌ /duel @user ID_карты"); return
            oun = p[1].replace("@",""); cid = int(p[2])
            my_card = await get_user_card(msg.from_user.id, cid)
            if not my_card: await msg.answer(f"❌ У вас нет карты #{cid}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (oun,)) as c: ou = await c.fetchone()
            if not ou: await msg.answer(f"❌ @{oun} не найден!"); return
            oid = ou[0]
            if oid == msg.from_user.id: await msg.answer("❌ Нельзя себя!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_card_id) VALUES (?,?,?)", (msg.from_user.id, oid, cid))
                await db.commit()
                async with db.execute("SELECT last_insert_rowid()") as c: duel_id = (await c.fetchone())[0]
            card = await get_card_by_id(cid)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"aduel_{duel_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dduel_{duel_id}")],
            ])
            await bot.send_message(oid, f"⚔️ ВЫЗОВ!\nОт: @{msg.from_user.username}\nКарта: {rarity_emoji(card['rarity'])} {card['name']} (#{cid})\nВыбери карту: /pick ID\nИли нажми Принять!", reply_markup=kb)
            await msg.answer(f"✅ Вызов @{oun}!")
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
        await upd_diamonds(wid, 2); await upd_diamonds(lid, -1); await add_xp(wid, 15); await add_xp(lid, 5)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=?", (wid, duel['id'])); await db.commit()
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try: await bot.send_message(uid, f"⚔️ Дуэль завершена! Победитель: {wid}")
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
    
    # ==================== ПРОФИЛЬ, УРОВНИ, ИНВЕНТАРЬ ====================
    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(msg):
        u = await get_user(msg.from_user.id)
        if not u: return
        cards = await get_card_count(msg.from_user.id)
        xp_needed = u['level'] * 100 + 50
        bar = "▓" * int(u['xp']/xp_needed*10) + "░" * (10 - int(u['xp']/xp_needed*10)) if xp_needed > 0 else "▓"*10
        await update_task_progress(msg.from_user.id, 'profile')
        await msg.answer(f"👤 {u['username']} | ⭐ Ур.{u['level']}\n📊 XP: {u['xp']}/{xp_needed} [{bar}]\n💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}\n🎴{cards} 🎡{u['fortune_spins']}\n📊 Гарант: {u['event_guarantor']}/50", reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "⬆ Уровни")
    async def levels_btn(msg):
        u = await get_user(msg.from_user.id)
        rewards = await get_level_rewards(msg.from_user.id)
        text = f"⬆ Уровень: {u['level']}\nXP: {u['xp']}/{u['level']*100+50}\n\n"
        if rewards:
            text += f"🎁 Доступно: {len(rewards)}!"
            buttons = [[InlineKeyboardButton(text=f"🎁 Ур.{r['level']}", callback_data=f"claim_level_{r['level']}")] for r in rewards[:5]]
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.answer(text + "Нет наград", reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("claim_level_"))
    async def claim_level(call):
        level = int(call.data.split("_")[2])
        reward = await claim_level_reward(call.from_user.id, level)
        if reward:
            desc = " ".join([f"+{v}{'🎲' if k=='rolls' else '💎' if k=='diamonds' else '🎪'}" for k,v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else: await call.answer("❌ Уже получена!", show_alert=True)
    
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_btn(msg):
        cards = await get_user_cards(msg.from_user.id)
        if not cards: await msg.answer("🎒 Пусто"); return
        text = "🎒 Карты:\n\n"; buttons = []
        for card in cards[:30]:
            orig = "🔒" if card['is_original'] else ""; ev = "🎪" if card['is_event_card'] else ""
            text += f"{orig}{ev}{rarity_emoji(card['rarity'])} #{card['id']} {card['name']} x{card['quantity']}\n"
            buttons.append([InlineKeyboardButton(text=f"📋 #{card['id']} {card['name']}", callback_data=f"cardinfo_{card['id']}")])
        await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("cardinfo_"))
    async def card_info(call):
        card_id = int(call.data.split("_")[1]); card = await get_card_by_id(card_id)
        if not card: return
        uc = await get_user_card(call.from_user.id, card_id); qty = uc['quantity'] if uc else 0
        text = f"{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        if card['is_L_card']: text += "\n🌟 L-КАРТА!"
        if qty: text += f"\n📦 У вас: {qty}"
        kb_buttons = []
        if qty > 1:
            extra = qty - 1 if uc['is_original'] else qty
            kb_buttons.append([InlineKeyboardButton(text=f"🔨 +1💎", callback_data=f"breakone_{card_id}"), InlineKeyboardButton(text=f"💥 +{extra}💎", callback_data=f"break_{card_id}")])
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
        cid = int(call.data.split("_")[1]); s, _ = await remove_card(call.from_user.id, cid, 1)
        if s: await upd_diamonds(call.from_user.id, 1); await add_xp(call.from_user.id, 2); await call.answer("✅ +1💎!")
        else: await call.answer("❌")
    
    @dp.callback_query(F.data.startswith("break_"))
    async def ba(call):
        cid = int(call.data.split("_")[1]); uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1: return
        bq = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        price = await get_break_price(uc['rarity']); total = bq * price
        async with aiosqlite.connect(DB_PATH) as db:
            if uc['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            await db.commit()
        await upd_diamonds(call.from_user.id, total)
        for _ in range(bq): await add_xp(call.from_user.id, 2)
        await call.answer(f"✅ +{total}💎!")
    
    @dp.callback_query(F.data.startswith("breakcustom_"))
    async def bc(call, state: FSMContext):
        cid = int(call.data.split("_")[1]); uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1: return
        mx = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        await state.update_data(bcid=cid, mx=mx)
        await call.message.answer(f"🔢 Сколько? (1-{mx}):"); await state.set_state(BreakCustomStates.waiting_for_quantity); await call.answer()
    
    @dp.message(StateFilter(BreakCustomStates.waiting_for_quantity))
    async def bcm(msg, state):
        try:
            q = int(msg.text.strip()); d = await state.get_data()
            if q < 1 or q > d['mx']: await msg.answer(f"❌ 1-{d['mx']}!"); return
            uc = await get_user_card(msg.from_user.id, d['bcid'])
            price = await get_break_price(uc['rarity']); total = q * price
            s, _ = await remove_card(msg.from_user.id, d['bcid'], q)
            if s: await upd_diamonds(msg.from_user.id, total); await msg.answer(f"✅ +{total}💎!")
            await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.callback_query(F.data.startswith("sellcard_"))
    async def sc(call): await call.message.answer(f"💱 /sell {call.data.split('_')[1]} ЦЕНА"); await call.answer()
    
    # ==================== ЗАДАНИЯ ====================
    @dp.message(F.text == "📋 Задания")
    async def tasks_btn(msg):
        tasks = await refresh_tasks_if_needed(msg.from_user.id)
        text = "📋 Ежедневные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"; ti = next((x for x in TASK_TYPES if x['type']==t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): text += "\n🎉 +1🎲!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "📅 Неделя")
    async def weekly_btn(msg):
        tasks = await get_weekly_tasks(msg.from_user.id)
        text = "📅 Еженедельные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"; ti = next((x for x in WEEKLY_TASK_TYPES if x['type']==t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        if all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            text += "\n🎁 Награда: +3💎 +2🎲 +1🎪\n/claim_weekly"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("claim_weekly"))
    async def claim_weekly(msg):
        tasks = await get_weekly_tasks(msg.from_user.id)
        if tasks and all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            today = datetime.now(); ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE weekly_tasks SET reward_claimed=1 WHERE user_id=? AND week_start=?", (msg.from_user.id, ws)); await db.commit()
            await upd_diamonds(msg.from_user.id, 3); await upd_rolls(msg.from_user.id, 2); await upd_event_rolls(msg.from_user.id, 1)
            await msg.answer("✅ +3💎 +2🎲 +1🎪")
        else: await msg.answer("❌")
    
    # ==================== БИРЖА, АУКЦИОН, ОБМЕН ====================
    @dp.message(F.text == "💱 Биржа")
    async def market_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Лоты", callback_data="market_view")],
            [InlineKeyboardButton(text="🔍 /find", callback_data="msi")],
            [InlineKeyboardButton(text="📊 /sell", callback_data="msi2")],
        ])
        await msg.answer("💱 Биржа:", reply_markup=kb)
    
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
    async def msi_handler(call): await call.message.answer("/find НОМЕР"); await call.answer()
    @dp.callback_query(F.data == "msi2")
    async def msi2_handler(call): await call.message.answer("/sell НОМЕР ЦЕНА"); await call.answer()
    
    @dp.message(Command("find"))
    async def fc(msg):
        try:
            cid = int(msg.text.replace("/find","").strip()); listings = await get_market_listings(card_id=cid)
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
            uc = await get_user_card(msg.from_user.id, cid)
            if not uc: await msg.answer(f"❌ Нет #{cid}!"); return
            if uc['is_original'] and uc['quantity'] <= 1: await msg.answer("❌ Оригинал!"); return
            await remove_card(msg.from_user.id, cid, 1); await create_market_listing(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ #{cid} за {pr}💎!")
        except: await msg.answer("❌ /sell НОМЕР ЦЕНА")
    
    @dp.callback_query(F.data.startswith("mbuy_"))
    async def mb(call):
        lid = int(call.data.split("_")[1]); s, m = await buy_listing(lid, call.from_user.id)
        await call.answer(f"{'✅' if s else '❌'} {m}", show_alert=True)
    
    @dp.message(F.text == "🏪 Аукцион")
    async def auc_btn(msg):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Активные", callback_data="auction_view")],
            [InlineKeyboardButton(text="📊 /auction", callback_data="auction_info")],
        ])
        await msg.answer("🏪 Аукцион:", reply_markup=kb)
    
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
    
    @dp.message(Command("auction"))
    async def acmd(msg):
        try:
            p = msg.text.split(); cid, pr = int(p[1]), int(p[2])
            await remove_card(msg.from_user.id, cid, 1); await create_auction(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ Аукцион #{cid} от {pr}💎")
        except: await msg.answer("❌")
    
    @dp.callback_query(F.data.startswith("abid_"))
    async def abid(call, state):
        await state.update_data(aid=int(call.data.split("_")[1]))
        await call.message.answer("💰 Сумма:"); await state.set_state(AuctionStates.waiting_for_bid); await call.answer()
    
    @dp.message(StateFilter(AuctionStates.waiting_for_bid))
    async def bid_msg(msg, state):
        try:
            amount = int(msg.text.strip()); data = await state.get_data()
            s, m = await bid_auction(data['aid'], msg.from_user.id, amount)
            await msg.answer(f"{'✅' if s else '❌'} {m}"); await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.message(F.text == "🔄 Обмен")
    async def trade_btn(msg): await msg.answer("🔄 /trade @user ID_моей ID_его")
    
    @dp.message(Command("trade"))
    async def tcmd(msg):
        try:
            p = msg.text.split()
            if len(p) != 4: await msg.answer("❌"); return
            tun = p[1].replace("@",""); fc, tc = int(p[2]), int(p[3])
            mc = await get_user_card(msg.from_user.id, fc)
            if not mc: await msg.answer(f"❌ Нет #{fc}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (tun,)) as c: tu = await c.fetchone()
            if not tu: await msg.answer(f"❌ @{tun}!"); return
            hc = await get_user_card(tu[0], tc)
            if not hc: await msg.answer(f"❌ У @{tun} нет #{tc}!"); return
            fcard = await get_card_by_id(fc); tcard = await get_card_by_id(tc)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"tac_{msg.from_user.id}_{fc}_{tc}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"tdc_{msg.from_user.id}")],
            ])
            await bot.send_message(tu[0], f"🔄 ОБМЕН!\nОт: @{msg.from_user.username}\n{rarity_emoji(fcard['rarity'])} {fcard['name']} (#{fc})\n→ {rarity_emoji(tcard['rarity'])} {tcard['name']} (#{tc})", reply_markup=kb)
            await msg.answer(f"✅ @{tun}!")
        except: await msg.answer("❌")
    
    @dp.callback_query(F.data.startswith("tac_"))
    async def tac(call):
        p = call.data.split("_"); fu, fc, tc = int(p[1]), int(p[2]), int(p[3])
        if not await get_user_card(fu, fc) or not await get_user_card(call.from_user.id, tc): await call.message.edit_text("❌"); return
        await remove_card(fu, fc); await remove_card(call.from_user.id, tc)
        await add_card_to_user(call.from_user.id, fc); await add_card_to_user(fu, tc)
        await call.message.edit_text("✅!"); await call.answer()
    
    @dp.callback_query(F.data.startswith("tdc_"))
    async def tdc(call): await call.message.edit_text("❌"); await call.answer()
    
    # ==================== ДРУЗЬЯ ====================
    @dp.message(F.text == "👥 Друзья")
    async def friends_btn(msg):
        friends = await get_friends(msg.from_user.id)
        text = "👥 Друзья:\n\n" + ("\n".join([f"• @{f['username']}" for f in friends]) if friends else "Пока нет") + "\n\n/friend add @user"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("friend"))
    async def fcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 3: return
            action, un = p[1], p[2].replace("@","")
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c: fu = await c.fetchone()
            if not fu: return
            fid = fu[0]
            if action == "add": await send_friend_request(msg.from_user.id, fid); await msg.answer(f"✅ @{un}!")
            elif action == "accept": await accept_friend(msg.from_user.id, fid); await msg.answer(f"✅ @{un}!")
            elif action == "remove":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (msg.from_user.id, fid, fid, msg.from_user.id)); await db.commit()
                await msg.answer(f"✅ @{un} удален")
        except: pass
    
    # ==================== ГИЛЬДИИ ====================
    @dp.message(F.text == "🏰 Гильдия")
    async def guild_btn(msg):
        guild = await get_user_guild(msg.from_user.id)
        if guild:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id=?", (guild['id'],)) as c: cnt = (await c.fetchone())[0]
            await msg.answer(f"🏰 {guild['name']}\n👥 {cnt}\n/guild info | /guild members | /guild leave")
        else: await msg.answer("🏰 /guild create НАЗВАНИЕ | /guild join НАЗВАНИЕ | /guild list")
    
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
                    await db.execute("INSERT INTO guild_members (guild_id, user_id, role) VALUES (?,?,'owner')", (gid, msg.from_user.id)); await db.commit()
                await msg.answer(f"✅ '{name}' создана!")
            elif action == "join":
                name = " ".join(p[2:])
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c: g = await c.fetchone()
                if not g: return
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT OR IGNORE INTO guild_join_requests (guild_id, user_id) VALUES (?,?)", (g[0], msg.from_user.id)); await db.commit()
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
    
    # ==================== ГИЛЬДЕЙСКИЕ ВОЙНЫ ====================
    @dp.message(F.text == "⚔️ Война гильдий")
    async def war_btn(msg):
        season = await get_active_war_season(); guild = await get_user_guild(msg.from_user.id)
        if not season: await msg.answer("⚔️ Нет активной войны!"); return
        if not guild: await msg.answer("❌ Вы не в гильдии!"); return
        if season['status'] == 'selection': await msg.answer(f"⚔️ Выбор карт!\n/war_pick ID")
        elif season['status'] == 'active':
            ranking = await get_guild_war_ranking(season['id'])
            text = "⚔️ БИТВЫ!\n\n🏆 Рейтинг:\n\n"
            for i,g in enumerate(ranking[:10]): text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} {g['name']} - {g['total_points']} очков\n"
            await msg.answer(text)
    
    @dp.message(Command("war_pick"))
    async def war_pick(msg):
        season = await get_active_war_season()
        if not season or season['status'] != 'selection': await msg.answer("❌"); return
        guild = await get_user_guild(msg.from_user.id)
        if not guild: await msg.answer("❌"); return
        try:
            cid = int(msg.text.replace("/war_pick","").strip())
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            await set_war_card(season['id'], guild['id'], msg.from_user.id, cid)
            await msg.answer(f"✅ #{cid} выбрана!")
        except: await msg.answer("❌ /war_pick ID")
    
    # ==================== ДОСТИЖЕНИЯ ====================
    @dp.message(F.text == "🏅 Достижения")
    async def ach_btn(msg):
        u = await get_user(msg.from_user.id); cards = await get_user_cards(msg.from_user.id)
        tc = sum(c['quantity'] for c in cards); lc = sum(c['quantity'] for c in cards if c['is_L_card'])
        text = "🏅 Достижения:\n\n"
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                    row = await c.fetchone()
                if row and row[0]:
                    text += f"{'🎁' if not row[1] else '✅'} {ach['icon']} {ach['name']}\n"
                else: text += f"🔒 {ach['icon']} {ach['name']}\n"
        text += f"\n📊 Карт: {tc} | L: {lc} | Ур: {u['level']}\nНажми 🎁 чтобы получить награду!"
        buttons = []
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                    row = await c.fetchone()
                if row and row[0] and not row[1]:
                    buttons.append([InlineKeyboardButton(text=f"🎁 {ach['icon']} {ach['name']}", callback_data=f"claim_ach_{ach['id']}")])
        if buttons: await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("claim_ach_"))
    async def claim_ach(call):
        ach_id = call.data.split("_", 2)[2]
        reward = await claim_achievement_reward(call.from_user.id, ach_id)
        if reward:
            desc = " ".join([f"+{v}{'💎' if k=='diamonds' else '🎲' if k=='rolls' else '🎪'}" for k,v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else: await call.answer("❌ Уже получена!", show_alert=True)
    
    # ==================== ПРОМОКОДЫ ====================
    @dp.message(F.text == "🎫 Промокод")
    async def promo_btn(msg, state): await msg.answer("🎫 Введи код:"); await state.set_state(PromoStates.waiting_for_code)
    
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
            elif promo['type']=='card':
                card = await get_card_by_id(promo['value'])
                if card: await add_card_to_user(msg.from_user.id, promo['value'], is_original=True)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE promocodes SET uses_left=uses_left-1 WHERE code=?", (code,)); await db.commit()
            await msg.answer(f"✅ +{promo['value']} {promo['type']}!")
        await state.clear()
    
    # ==================== ЛИДЕРЫ, КАРТЫ, ПОМОЩЬ ====================
    @dp.message(F.text == "🏆 Лидеры")
    async def lead_btn(msg):
        top = await get_leaders(10)
        text = "🏆 Топ-10:\n\n" + ("\n".join([f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} @{u['username']} - {u['total']} карт" for i,u in enumerate(top)]) if top else "Пусто")
        ltop = await get_level_leaders(5)
        if ltop: text += "\n⭐ Топ-5 уровней:\n" + "\n".join([f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} @{u['username']} - Ур.{u['level']}" for i,u in enumerate(ltop)])
        await msg.answer(text)
    
    @dp.message(F.text == "📚 Все карты")
    async def allc_btn(msg):
        cards = await get_all_cards()
        if not cards: return
        buttons = []; row = []
        for c in cards:
            if not c['is_event_card']:
                row.append(InlineKeyboardButton(text=f"#{c['id']}", callback_data=f"cardinfo_{c['id']}"))
                if len(row) == 5: buttons.append(row); row = []
        if row: buttons.append(row)
        await msg.answer("📚 Обычные:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
    
    @dp.message(F.text == "❓ Помощь")
    async def help_btn(msg): await msg.answer("🎲 Крутить | 🛍 Магазин\n🎪 Ивент | 🎡 Колесо\n📋 Задания | 📅 Неделя\n💱 Биржа | 🏪 Аукцион\n⚔️ /duel @user ID\n👥 Друзья | 🏰 Гильдии\n💥 Разбить всё | ⬆ Уровни\n🕐 7:00 и 17:00 МСК")
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg): await msg.answer("🎮 Меню:", reply_markup=permanent_keyboard())
    
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
        ])
        await msg.answer("👑 Админ-панель", reply_markup=kb)
    
    # --- Все админские callback-обработчики ---
    @dp.callback_query(F.data == "admin_add")
    async def aas(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(is_event=False)
        await call.message.answer("📝 Шаг 1/4\nВведи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name); await call.answer()
    
    @dp.callback_query(F.data == "admin_edit")
    async def ae(call): await call.message.answer("✏️ /editcard ID"); await call.answer()
    
    @dp.callback_query(F.data == "admin_list")
    async def alc(call):
        if call.from_user.id not in ADMIN_IDS: return
        await show_cards_list(call.message); await call.answer()
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def agm(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="gd")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="gr")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="ge")],
            [InlineKeyboardButton(text="🎴 Случ.карты", callback_data="gc")],
            [InlineKeyboardButton(text="🎯 Конкр.карта", callback_data="gs")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
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
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        await call.message.edit_text("👥 Выдать всем:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_broadcast")
    async def abr(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("📢 Отправь сообщение для рассылки:")
        await state.set_state(BroadcastStates.waiting_for_broadcast); await call.answer()
    
    @dp.callback_query(F.data == "admin_promo")
    async def apromo(call): await call.message.answer("🎫 /promo КОД ТИП ЗНАЧЕНИЕ ИСП\nТипы: diamonds, rolls, event_rolls, card"); await call.answer()
    
    @dp.callback_query(F.data == "admin_ban")
    async def ab(call): await call.message.answer("/ban @user | /unban @user"); await call.answer()
    
    @dp.callback_query(F.data == "admin_stats")
    async def astats_callback(call):
        if call.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c: users=(await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM cards") as c: cards=(await c.fetchone())[0]
        await call.message.answer(f"📊 Статистика:\n👥 {users}\n🎴 {cards}"); await call.answer()
    
    @dp.callback_query(F.data == "admin_event_menu")
    async def admin_event_menu(call):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📁 Создать колоду", callback_data="event_create_deck")],
            [InlineKeyboardButton(text="➕ В колоду", callback_data="event_add_to_deck_menu")],
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="event_start")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="event_end")],
            [InlineKeyboardButton(text="📋 Колоды", callback_data="event_list_decks")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
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
            [InlineKeyboardButton(text="📊 Рейтинг", callback_data="war_ranking")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        await call.message.edit_text("⚔️ Война:", reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_settings")
    async def admin_settings(call):
        if call.from_user.id not in ADMIN_IDS: return
        text = "⚙️ Настройки:\n\n/set_morning_rolls ЧИСЛО\n/set_morning_diamonds ЧИСЛО\n/set_evening_rolls ЧИСЛО\n/set_evening_diamonds ЧИСЛО\n/set_break_R ЧИСЛО\n/set_break_SR ЧИСЛО\n/set_break_SSR ЧИСЛО\n/set_break_L ЧИСЛО\n/show_settings"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])
        await call.message.edit_text(text, reply_markup=kb); await call.answer()
    
    @dp.callback_query(F.data == "admin_back")
    async def admin_back(call):
        if call.from_user.id not in ADMIN_IDS: return
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
        ])
        await call.message.edit_text("👑 Админ-панель", reply_markup=kb); await call.answer()
    
    # --- Выдача всем (callback) ---
    @dp.callback_query(F.data == "giveall_diamonds")
    async def gald(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='diamonds')
        await call.message.answer("💎 Сколько алмазов выдать всем?\nВведи число:"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_rolls")
    async def galr(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='rolls')
        await call.message.answer("🎲 Сколько круток выдать всем?\nВведи число:"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_event")
    async def gale(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='event')
        await call.message.answer("🎪 Сколько ивент-круток выдать всем?\nВведи число:"); await call.answer()
    
    @dp.callback_query(F.data == "giveall_fortune")
    async def galf(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.set_state(GiveAllStates.waiting_for_amount); await state.update_data(giveall_type='fortune')
        await call.message.answer("🎡 Сколько вращений колеса выдать всем?\nВведи число:"); await call.answer()
    
    # --- Обработчик состояния GiveAllStates ---
    @dp.message(StateFilter(GiveAllStates.waiting_for_amount))
    async def process_giveall(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data(); give_type = data.get('giveall_type')
        try:
            amount = int(msg.text.strip()); users = await get_all_users(); count = 0
            for u in users:
                try:
                    if give_type == 'diamonds': await upd_diamonds(u['user_id'], amount)
                    elif give_type == 'rolls': await upd_rolls(u['user_id'], amount)
                    elif give_type == 'event': await upd_event_rolls(u['user_id'], amount)
                    elif give_type == 'fortune': await upd_fortune_spins(u['user_id'], amount)
                    count += 1
                except: pass
            await msg.answer(f"✅ Выдано {amount} для {count} пользователей!"); await state.clear()
        except: await msg.answer("❌ Введи число!")
    
    # --- Обработчик состояния BroadcastStates (рассылка) ---
    @dp.message(StateFilter(BroadcastStates.waiting_for_broadcast))
    async def process_broadcast(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        users = await get_all_users(); sent = 0
        for u in users:
            try:
                if msg.text: await bot.send_message(u['user_id'], msg.text)
                if msg.photo: await bot.send_photo(u['user_id'], msg.photo[-1].file_id, caption=msg.caption or "")
                sent += 1; await asyncio.sleep(0.05)
            except: pass
        await msg.answer(f"✅ Рассылка: {sent}/{len(users)}"); await state.clear()
    
    # --- Выдача конкретному игроку (callback) ---
    @dp.callback_query(F.data == "gd")
    async def gd(call): await call.message.answer("/givediamonds @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "gr")
    async def gr(call): await call.message.answer("/giverolls @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "ge")
    async def ge(call): await call.message.answer("/giveevent @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "gc")
    async def gc(call): await call.message.answer("/givecards @user кол-во"); await call.answer()
    @dp.callback_query(F.data == "gs")
    async def gs(call): await call.message.answer("/givecard @user ID_карты"); await call.answer()
    
    # --- Команды выдачи ---
    async def resolve_user(username):
        username = username.replace("@","")
        if username.isdigit(): return int(username)
        user = await get_user_by_username(username)
        return user['user_id'] if user else None
    
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
    
    @dp.message(Command("givecards"))
    async def gc_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p=msg.text.split(); uid=await resolve_user(p[1]); am=int(p[2])
            cards=await get_regular_cards()
            for _ in range(am): await add_card_to_user(uid,random.choice(cards)['id'],is_original=True)
            await msg.answer(f"✅ +{am} карт")
        except: await msg.answer("❌")
    
    @dp.message(Command("givecard"))
    async def gs_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p=msg.text.split(); uid=await resolve_user(p[1]); cid=int(p[2])
            await add_card_to_user(uid,cid,is_original=True)
            await msg.answer(f"✅ #{cid}")
        except: await msg.answer("❌")
    
    # --- Добавление карт ---
    @dp.message(Command("addcard"))
    async def ac(msg, state): await state.update_data(is_event=False); await msg.answer("📝 Шаг 1/4"); await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def an(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(name=msg.text.strip()); await msg.answer("📝 Шаг 2/4\nОписание:"); await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def ad(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nРедкость:", reply_markup=rarity_keyboard()); await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def ar(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(rarity=call.data.split("_")[1])
        await call.message.answer("📝 Шаг 4/4\nОтправь фото или 'нет'"); await state.set_state(AddCardStates.waiting_for_photo); await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def ap(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data(); file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity'] == 'L'; is_event = data.get('is_event', False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO cards (name, description, file_id, rarity, is_L_card, is_event_card) VALUES (?,?,?,?,?,?)",
                           (data['name'], data['description'], file_id, data['rarity'], is_L, is_event)); await db.commit()
        await msg.answer(f"✅ {'🎪' if is_event else ''} {data['name']} добавлена!"); await state.clear()
    
    async def show_cards_list(target):
        cards = await get_all_cards()
        if not cards: await target.answer("📋 Нет"); return
        ro = {'L':'🌟L','SSR':'🟣SSR','SR':'🔵SR','R':'⚪R'}; g = {}
        for c in cards: g.setdefault(c['rarity'], []).append(c)
        text = "📋 Карты:\n\n"
        for r,t in ro.items():
            if r in g: text += f"{t} ({len(g[r])}):\n" + "\n".join([f"  #{c['id']} {'🎪' if c['is_event_card'] else ''}{c['name']}" for c in g[r]]) + "\n\n"
        for i in range(0, len(text), 4000): await target.answer(text[i:i+4000])
    
    @dp.message(Command("cards"))
    async def cc(msg): await show_cards_list(msg)
    
    @dp.message(Command("delcard"))
    async def dc(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            cid = int(msg.text.replace("/delcard","").strip())
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (cid,)); await db.commit()
            await msg.answer(f"✅ #{cid} удалена!")
        except: pass
    
    # --- Остальные админ-команды ---
    @dp.message(Command("user"))
    async def user_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            uid=await resolve_user(msg.text.replace("/user","").strip()); u=await get_user(uid)
            await msg.answer(f"👤 @{u['username']} (ID:{uid})\n⭐ Ур.{u['level']}\n💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}")
        except: await msg.answer("❌")
    
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
    
    @dp.message(Command("giveall"))
    async def giveall_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p=msg.text.split(); give_type=p[1]; amount=int(p[2]); users=await get_all_users(); count=0
            for u in users:
                try:
                    if give_type=='diamonds': await upd_diamonds(u['user_id'],amount)
                    elif give_type=='rolls': await upd_rolls(u['user_id'],amount)
                    elif give_type=='event': await upd_event_rolls(u['user_id'],amount)
                    elif give_type=='fortune': await upd_fortune_spins(u['user_id'],amount)
                    count+=1
                except: pass
            await msg.answer(f"✅ {amount} для {count}!")
        except: await msg.answer("❌ /giveall ТИП КОЛ-ВО")
    
    @dp.message(Command("broadcast"))
    async def bcmd(msg, state): await msg.answer("📢 Сообщение:"); await state.set_state(BroadcastStates.waiting_for_broadcast)
    
    @dp.message(Command("stats"))
    async def stats_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c: users=(await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM cards") as c: cards=(await c.fetchone())[0]
        await msg.answer(f"📊 👥{users} 🎴{cards}")
    
    @dp.message(Command("logs"))
    async def logs_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: limit=int(msg.text.replace("/logs","").strip() or "20")
        except: limit=20
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory=aiosqlite.Row
            async with db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?",(limit,)) as c: logs=await c.fetchall()
        text="📋 Логи:\n\n"+("\n".join([f"[{l['timestamp']}] ID{l['user_id']}: {l['action']}" for l in logs]) if logs else "Пусто")
        await msg.answer(text[:4000])
    
    @dp.message(Command("force_morning"))
    async def fm(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await morning_bonus(); await msg.answer("✅")
    
    @dp.message(Command("force_evening"))
    async def fe(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await evening_bonus(); await msg.answer("✅")
    
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
    
    # --- Настройки ---
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
        try: await set_setting('break_R',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_break_SR"))
    async def sbsr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_SR',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_break_SSR"))
    async def sbssr(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_SSR',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("set_break_L"))
    async def sbl(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try: await set_setting('break_L',msg.text.split()[1]); await msg.answer("✅")
        except: pass
    
    @dp.message(Command("show_settings"))
    async def show_settings(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM settings ORDER BY key") as c: rows = await c.fetchall()
        await msg.answer("⚙️ Настройки:\n\n" + "\n".join([f"{r[0]} = {r[1]}" for r in rows])[:4000])
    
    # --- Ивенты (админ) ---
    @dp.callback_query(F.data == "event_create_deck")
    async def ecd(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("📁 Название:"); await state.set_state(EventStates.waiting_for_deck_name); await call.answer()
    
    @dp.message(StateFilter(EventStates.waiting_for_deck_name))
    async def deck_name(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        did = await create_deck(msg.text.strip()); await msg.answer(f"✅ ID:{did}"); await state.clear()
    
    @dp.callback_query(F.data == "event_add_to_deck_menu")
    async def eatdm(call):
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
    
    @dp.callback_query(F.data == "event_list_decks")
    async def eld(call):
        decks = await get_all_decks()
        text = "📋 Колоды:\n\n" + ("\n".join([f"📁 {d['name']} (ID:{d['id']})" for d in decks]) if decks else "Нет")
        await call.message.answer(text); await call.answer()
    
    # --- Война (админ) ---
    @dp.callback_query(F.data == "war_start")
    async def ws_btn(call):
        if call.from_user.id not in ADMIN_IDS: return
        sid = await start_war_season(); await call.message.answer(f"✅ Сезон #{sid}!"); await call.answer()
    
    @dp.callback_query(F.data == "war_battles")
    async def wb_btn(call):
        season = await get_active_war_season()
        if season: await start_war_battles(season['id']); await call.message.answer("⚔️ Битвы!")
        await call.answer()
    
    @dp.callback_query(F.data == "war_end")
    async def we_btn(call): await end_current_war(); await call.message.answer("⏹ Завершена!"); await call.answer()
    
    @dp.callback_query(F.data == "war_reward")
    async def wr_btn(call): await call.message.answer("🏆 Награды вручную:\n/war_reward"); await call.answer()
    
    @dp.callback_query(F.data == "war_ranking")
    async def wrk_btn(call):
        season = await get_active_war_season()
        if season:
            ranking = await get_guild_war_ranking(season['id'])
            text = "📊 Рейтинг:\n\n" + "\n".join([f"{i+1}. {g['name']} - {g['total_points']} очков" for i,g in enumerate(ranking[:10])]) if ranking else "Нет"
        else: text = "Нет активного сезона"
        await call.message.answer(text); await call.answer()
    
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
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
