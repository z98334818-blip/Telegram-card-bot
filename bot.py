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
        # Пользователи с уровнями
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                rolls INTEGER DEFAULT 2,
                diamonds INTEGER DEFAULT 0,
                total_rolls INTEGER DEFAULT 0,
                fortune_spins INTEGER DEFAULT 1,
                event_rolls INTEGER DEFAULT 0,
                event_guarantor INTEGER DEFAULT 0,
                bonus_roll_received BOOLEAN DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                banned BOOLEAN DEFAULT 0
            )
        """)
        # Карты
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT DEFAULT '',
                file_id TEXT,
                rarity TEXT DEFAULT 'R',
                is_L_card BOOLEAN DEFAULT 0,
                is_event_card BOOLEAN DEFAULT 0
            )
        """)
        # Инвентарь
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id INTEGER,
                card_id INTEGER,
                quantity INTEGER DEFAULT 1,
                is_original BOOLEAN DEFAULT 1,
                PRIMARY KEY (user_id, card_id)
            )
        """)
        # Задания
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_tasks (
                user_id INTEGER,
                task_id INTEGER,
                task_type TEXT,
                task_target INTEGER DEFAULT 1,
                progress INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT 0,
                date TEXT,
                PRIMARY KEY (user_id, task_id, date)
            )
        """)
        # Еженедельные задания
        await db.execute("""
            CREATE TABLE IF NOT EXISTS weekly_tasks (
                user_id INTEGER,
                task_id INTEGER,
                task_type TEXT,
                task_target INTEGER DEFAULT 1,
                progress INTEGER DEFAULT 0,
                completed BOOLEAN DEFAULT 0,
                reward_claimed BOOLEAN DEFAULT 0,
                week_start TEXT,
                PRIMARY KEY (user_id, task_id, week_start)
            )
        """)
        # Достижения
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                achievement_id TEXT,
                completed BOOLEAN DEFAULT 0,
                PRIMARY KEY (user_id, achievement_id)
            )
        """)
        # Биржа
        await db.execute("""
            CREATE TABLE IF NOT EXISTS market (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                card_id INTEGER,
                price INTEGER,
                quantity INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Аукционы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS auctions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER,
                card_id INTEGER,
                start_price INTEGER,
                current_price INTEGER,
                current_bidder_id INTEGER,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """)
        # Гильдии
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guilds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                owner_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_members (
                guild_id INTEGER,
                user_id INTEGER,
                role TEXT DEFAULT 'member',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                status TEXT DEFAULT 'pending'
            )
        """)
        # Дуэли
        await db.execute("""
            CREATE TABLE IF NOT EXISTS duels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger_id INTEGER,
                opponent_id INTEGER,
                challenger_card_id INTEGER,
                opponent_card_id INTEGER,
                bet_type TEXT DEFAULT 'diamond',
                bet_amount INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                winner_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Друзья
        await db.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                user_id INTEGER,
                friend_id INTEGER,
                status TEXT DEFAULT 'pending',
                PRIMARY KEY (user_id, friend_id)
            )
        """)
        # Промокоды
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                type TEXT,
                value INTEGER,
                uses_left INTEGER,
                created_by INTEGER
            )
        """)
        # Логи
        await db.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Уровни и награды
        await db.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                user_id INTEGER,
                level INTEGER,
                claimed BOOLEAN DEFAULT 0,
                PRIMARY KEY (user_id, level)
            )
        """)
        await db.commit()
        logger.info("✅ База данных готова")

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

class AuctionStates(StatesGroup):
    waiting_for_bid = State()

class PromoStates(StatesGroup):
    waiting_for_code = State()

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
    """Добавляет XP и проверяет повышение уровня"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (amount, uid))
        await db.commit()
        
        user = await get_user(uid)
        xp = user['xp']
        level = user['level']
        xp_needed = level * 100 + 50  # Формула: уровень * 100 + 50
        
        levels_gained = 0
        while xp >= xp_needed:
            xp -= xp_needed
            level += 1
            levels_gained += 1
            xp_needed = level * 100 + 50
        
        if levels_gained > 0:
            await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (xp, level, uid))
            await db.commit()
            
            # Записываем доступные награды за уровни
            for l in range(level - levels_gained + 1, level + 1):
                await db.execute("INSERT OR IGNORE INTO level_rewards (user_id, level) VALUES (?,?)", (uid, l))
            await db.commit()
            
            return levels_gained, level
    return 0, user['level']

async def get_level_rewards(uid):
    """Получает непОлученные награды за уровни"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM level_rewards WHERE user_id=? AND claimed=0 ORDER BY level", (uid,)) as c:
            return await c.fetchall()

async def claim_level_reward(uid, level):
    """Выдает награду за уровень"""
    # Награды по уровням
    rewards = {
        2: {'rolls': 1},
        3: {'diamonds': 2},
        4: {'rolls': 1, 'diamonds': 1},
        5: {'event_rolls': 1},
        6: {'rolls': 2},
        7: {'diamonds': 3},
        8: {'rolls': 1, 'event_rolls': 1},
        9: {'diamonds': 5},
        10: {'rolls': 3, 'diamonds': 3, 'event_rolls': 1},
    }
    
    # Для уровней выше 10 - каждые 5 уровней
    if level > 10 and level % 5 == 0:
        rewards[level] = {'rolls': level//2, 'diamonds': level, 'event_rolls': level//5}
    
    if level not in rewards:
        return False
    
    reward = rewards[level]
    if 'rolls' in reward: await upd_rolls(uid, reward['rolls'])
    if 'diamonds' in reward: await upd_diamonds(uid, reward['diamonds'])
    if 'event_rolls' in reward: await upd_event_rolls(uid, reward['event_rolls'])
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE level_rewards SET claimed=1 WHERE user_id=? AND level=?", (uid, level))
        await db.commit()
    
    return reward

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
            existing = await c.fetchone()
        if existing:
            await db.execute("UPDATE user_cards SET quantity=quantity+1 WHERE user_id=? AND card_id=?", (uid, cid))
        else:
            await db.execute("INSERT INTO user_cards (user_id, card_id, quantity, is_original) VALUES (?,?,1,?)", 
                           (uid, cid, is_original))
        await db.commit()

async def upd_rolls(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rolls=rolls+?, total_rolls=total_rolls+? WHERE user_id=?", 
                        (d, abs(d), uid))
        await db.commit()

async def upd_diamonds(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET diamonds=diamonds+? WHERE user_id=?", (d, uid))
        await db.commit()

async def upd_fortune_spins(uid, spins):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET fortune_spins=? WHERE user_id=?", (spins, uid))
        await db.commit()

async def upd_event_rolls(uid, d):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET event_rolls=event_rolls+? WHERE user_id=?", (d, uid))
        await db.commit()

async def upd_event_guarantor(uid, progress):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET event_guarantor=? WHERE user_id=?", (progress, uid))
        await db.commit()

async def get_user_cards(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc
            JOIN cards c ON uc.card_id=c.id
            WHERE uc.user_id=? AND uc.quantity>0
            ORDER BY c.id
        """, (uid,)) as c:
            return await c.fetchall()

async def get_user_card(uid, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc
            JOIN cards c ON uc.card_id=c.id
            WHERE uc.user_id=? AND uc.card_id=?
        """, (uid, cid)) as c:
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
        async with db.execute("""
            SELECT u.user_id, u.username, SUM(uc.quantity) as total
            FROM users u LEFT JOIN user_cards uc ON u.user_id=uc.user_id
            GROUP BY u.user_id HAVING total>0
            ORDER BY total DESC LIMIT ?
        """, (limit,)) as c:
            return await c.fetchall()

async def get_level_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, username, level, xp FROM users
            ORDER BY level DESC, xp DESC LIMIT ?
        """, (limit,)) as c:
            return await c.fetchall()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            return await c.fetchall()

# ==================== ЗАДАНИЯ ====================
TASK_TYPES = [
    {"type": "roll", "desc": "🎲 Прокрутить один раз", "target": 1},
    {"type": "profile", "desc": "👤 Зайти в профиль", "target": 1},
    {"type": "break", "desc": "🔨 Разбить повторку", "target": 1},
    {"type": "fortune", "desc": "🎡 Крутануть колесо", "target": 1},
    {"type": "event_roll", "desc": "🎪 Ивент-крутка", "target": 1},
]

WEEKLY_TASK_TYPES = [
    {"type": "weekly_rolls", "desc": "🎲 Сделать 20 круток", "target": 20},
    {"type": "weekly_ssr", "desc": "🟣 Выбить 3 SSR карты", "target": 3},
    {"type": "weekly_break", "desc": "🔨 Разбить 10 повторов", "target": 10},
    {"type": "weekly_fortune", "desc": "🎡 Крутануть колесо 5 раз", "target": 5},
]

async def ensure_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
            row = await c.fetchone()
            if row[0] == 0:
                selected = random.sample(TASK_TYPES, 2)
                for i, task in enumerate(selected):
                    await db.execute(
                        "INSERT INTO daily_tasks (user_id, task_id, task_type, task_target, date) VALUES (?,?,?,?,?)",
                        (uid, i, task['type'], task['target'], today))
                await db.commit()

async def ensure_weekly_tasks(uid):
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, week_start)) as c:
            row = await c.fetchone()
            if row[0] == 0:
                selected = random.sample(WEEKLY_TASK_TYPES, 3)
                for i, task in enumerate(selected):
                    await db.execute(
                        "INSERT INTO weekly_tasks (user_id, task_id, task_type, task_target, week_start) VALUES (?,?,?,?,?)",
                        (uid, i, task['type'], task['target'], week_start))
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
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, week_start)) as c:
            return await c.fetchall()

async def update_task_progress(uid, task_type):
    date = datetime.now().strftime("%Y-%m-%d")
    await ensure_daily_tasks(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE daily_tasks SET progress=progress+1 
            WHERE user_id=? AND task_type=? AND date=? AND completed=0 AND progress<task_target
        """, (uid, task_type, date))
        await db.execute("""
            UPDATE daily_tasks SET completed=1 
            WHERE user_id=? AND task_type=? AND date=? AND progress>=task_target
        """, (uid, task_type, date))
        await db.commit()

async def update_weekly_progress(uid, task_type):
    await ensure_weekly_tasks(uid)
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE weekly_tasks SET progress=progress+1 
            WHERE user_id=? AND task_type=? AND week_start=? AND completed=0 AND progress<task_target
        """, (uid, task_type, week_start))
        await db.execute("""
            UPDATE weekly_tasks SET completed=1 
            WHERE user_id=? AND task_type=? AND week_start=? AND progress>=task_target
        """, (uid, task_type, week_start))
        await db.commit()

async def check_all_tasks_completed(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) as t, SUM(completed) as d FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)
        ) as c:
            row = await c.fetchone()
            return row[0] >= 2 and row[1] == row[0]

async def give_bonus_roll(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        user = await get_user(uid)
        if not user['bonus_roll_received']:
            await db.execute("UPDATE users SET bonus_roll_received=1 WHERE user_id=?", (uid,))
            await db.execute("UPDATE users SET rolls=rolls+1 WHERE user_id=?", (uid,))
            await db.commit()
            return True
    return False

# ==================== ДОСТИЖЕНИЯ ====================
ACHIEVEMENTS = [
    {"id": "cards_10", "name": "Начинающий коллекционер", "desc": "Собрать 10 карт", "icon": "📚"},
    {"id": "cards_50", "name": "Опытный коллекционер", "desc": "Собрать 50 карт", "icon": "📚"},
    {"id": "cards_100", "name": "Мастер коллекционирования", "desc": "Собрать 100 карт", "icon": "📚"},
    {"id": "rolls_100", "name": "Крутильщик", "desc": "Сделать 100 круток", "icon": "🎲"},
    {"id": "l_cards_1", "name": "Первая L-карта", "desc": "Получить L-карту", "icon": "🌟"},
    {"id": "level_5", "name": "Опытный игрок", "desc": "Достигнуть 5 уровня", "icon": "⭐"},
    {"id": "level_10", "name": "Мастер", "desc": "Достигнуть 10 уровня", "icon": "⭐"},
    {"id": "level_20", "name": "Легенда", "desc": "Достигнуть 20 уровня", "icon": "⭐"},
]

async def check_achievements(uid):
    user = await get_user(uid)
    cards = await get_user_cards(uid)
    total_cards = sum(c['quantity'] for c in cards)
    l_cards = sum(c['quantity'] for c in cards if c['is_L_card'])
    new_ach = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            completed = False
            if ach['id'] == 'cards_10' and total_cards >= 10: completed = True
            elif ach['id'] == 'cards_50' and total_cards >= 50: completed = True
            elif ach['id'] == 'cards_100' and total_cards >= 100: completed = True
            elif ach['id'] == 'rolls_100' and user['total_rolls'] >= 100: completed = True
            elif ach['id'] == 'l_cards_1' and l_cards >= 1: completed = True
            elif ach['id'] == 'level_5' and user['level'] >= 5: completed = True
            elif ach['id'] == 'level_10' and user['level'] >= 10: completed = True
            elif ach['id'] == 'level_20' and user['level'] >= 20: completed = True
            if not completed: continue
            async with db.execute(
                "SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach['id'])
            ) as c:
                row = await c.fetchone()
                if not row or not row[0]:
                    await db.execute(
                        "INSERT OR REPLACE INTO achievements (user_id, achievement_id, completed) VALUES (?,?,1)",
                        (uid, ach['id']))
                    await db.commit()
                    new_ach.append(ach)
    return new_ach

# ==================== БИРЖА И АУКЦИОНЫ ====================
async def create_market_listing(seller_id, card_id, price, quantity=1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO market (seller_id, card_id, price, quantity) VALUES (?,?,?,?)",
                        (seller_id, card_id, price, quantity))
        await db.commit()

async def get_market_listings(card_id=None, page=0, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if card_id:
            async with db.execute("""
                SELECT m.*, c.name, c.rarity, c.is_L_card, c.file_id
                FROM market m JOIN cards c ON m.card_id=c.id
                WHERE m.card_id=? ORDER BY m.price ASC LIMIT ? OFFSET ?
            """, (card_id, limit, page*limit)) as c:
                return await c.fetchall()
        else:
            async with db.execute("""
                SELECT m.*, c.name, c.rarity, c.is_L_card, c.file_id
                FROM market m JOIN cards c ON m.card_id=c.id
                ORDER BY m.created_at DESC LIMIT ? OFFSET ?
            """, (limit, page*limit)) as c:
                return await c.fetchall()

async def buy_listing(listing_id, buyer_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM market WHERE id=?", (listing_id,)) as c:
            listing = await c.fetchone()
        if not listing: return False, "Лот не найден"
        if listing['seller_id'] == buyer_id: return False, "Нельзя купить свою карту"
        buyer = await get_user(buyer_id)
        if buyer['diamonds'] < listing['price']: return False, f"Нужно {listing['price']}💎"
        await upd_diamonds(buyer_id, -listing['price'])
        await upd_diamonds(listing['seller_id'], listing['price'])
        await add_card_to_user(buyer_id, listing['card_id'])
        if listing['quantity'] > 1:
            await db.execute("UPDATE market SET quantity=quantity-1 WHERE id=?", (listing_id,))
        else:
            await db.execute("DELETE FROM market WHERE id=?", (listing_id,))
        await db.commit()
        return True, "Покупка успешна"

async def create_auction(seller_id, card_id, start_price, duration_hours=24):
    end_time = datetime.now() + timedelta(hours=duration_hours)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO auctions (seller_id, card_id, start_price, current_price, end_time) VALUES (?,?,?,?,?)",
            (seller_id, card_id, start_price, start_price, end_time))
        await db.commit()

async def get_active_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT a.*, c.name, c.rarity, c.is_L_card, c.file_id
            FROM auctions a JOIN cards c ON a.card_id=c.id
            WHERE a.status='active' AND a.end_time > datetime('now')
            ORDER BY a.end_time ASC
        """) as c:
            return await c.fetchall()

async def bid_auction(auction_id, bidder_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (auction_id,)) as c:
            auction = await c.fetchone()
        if not auction: return False, "Аукцион не найден"
        if amount <= auction['current_price']: return False, "Ставка должна быть больше текущей"
        bidder = await get_user(bidder_id)
        if bidder['diamonds'] < amount: return False, "Недостаточно алмазов"
        await db.execute("UPDATE auctions SET current_price=?, current_bidder_id=? WHERE id=?", (amount, bidder_id, auction_id))
        await db.commit()
        return True, "Ставка принята!"

async def finish_auctions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auctions WHERE status='active' AND end_time <= datetime('now')") as c:
            expired = await c.fetchall()
        for auction in expired:
            if auction['current_bidder_id']:
                await upd_diamonds(auction['seller_id'], auction['current_price'])
                await add_card_to_user(auction['current_bidder_id'], auction['card_id'])
                await db.execute("UPDATE auctions SET status='sold' WHERE id=?", (auction['id'],))
            else:
                await db.execute("UPDATE auctions SET status='expired' WHERE id=?", (auction['id'],))
        await db.commit()

# ==================== ДРУЗЬЯ ====================
async def send_friend_request(uid, friend_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?,?)", (uid, friend_id))
        await db.commit()

async def accept_friend(uid, friend_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (friend_id, uid))
        await db.execute("INSERT OR IGNORE INTO friends (user_id, friend_id, status) VALUES (?,?,'accepted')", (uid, friend_id))
        await db.commit()

async def get_friends(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT f.friend_id, u.username FROM friends f JOIN users u ON f.friend_id=u.user_id
            WHERE f.user_id=? AND f.status='accepted'
        """, (uid,)) as c:
            return await c.fetchall()

# ==================== КОЛЕСО ФОРТУНЫ ====================
FORTUNE_PRIZES = [
    {"prize": "roll", "value": 1, "desc": "🎲 +1 крутка", "weight": 30},
    {"prize": "diamond", "value": 1, "desc": "💎 +1 алмаз", "weight": 25},
    {"prize": "diamond", "value": 2, "desc": "💎 +2 алмаза", "weight": 15},
    {"prize": "random_card", "value": 1, "desc": "🎴 Случайная карта", "weight": 15},
    {"prize": "nothing", "value": 0, "desc": "❌ Ничего", "weight": 15},
]

# ==================== КЛАВИАТУРЫ ====================
def permanent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="💎 Премиум крутка")],
            [KeyboardButton(text="🎪 Ивент-крутка"), KeyboardButton(text="🎡 Колесо фортуны")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎒 Инвентарь")],
            [KeyboardButton(text="📋 Задания"), KeyboardButton(text="📅 Неделя")],
            [KeyboardButton(text="💱 Биржа"), KeyboardButton(text="🏪 Аукцион")],
            [KeyboardButton(text="🔄 Обмен"), KeyboardButton(text="⚔️ Дуэль")],
            [KeyboardButton(text="👥 Друзья"), KeyboardButton(text="🏰 Гильдия")],
            [KeyboardButton(text="📚 Все карты"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="🏅 Достижения"), KeyboardButton(text="🎫 Промокод")],
            [KeyboardButton(text="⬆ Уровни"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True, persistent=True
    )

def rarity_emoji(rarity):
    return {'R': '⚪', 'SR': '🔵', 'SSR': '🟣', 'L': '🌟'}.get(rarity, '⚪')

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
        if user and user['banned']:
            await msg.answer("⛔ Вы заблокированы в боте.")
            return
        await create_user(msg.from_user.id, msg.from_user.username or "Аноним")
        await msg.answer(
            "✨ Приветствую тебя путник в великолепном боте с женщинами визуальных новелл! ✨\n\n"
            "🎲 Выдачи в 7:00 и 17:00 МСК\n🌟 L-карты только в ивент-крутках!\n"
            "⭐ Система уровней! Зарабатывай XP и получай награды!\n"
            "⚔️ PvP дуэли | 🏰 Гильдии | 🏪 Аукционы | 👥 Друзья",
            reply_markup=permanent_keyboard()
        )
    
    # ==================== КРУТКИ ====================
    async def perform_regular_roll(uid):
        cards = await get_regular_cards()
        if not cards: return None, "В базе нет обычных карт"
        card = random.choice(cards)
        await add_card_to_user(uid, card['id'], is_original=True)
        levels_gained, new_level = await add_xp(uid, 10)
        await update_weekly_progress(uid, 'weekly_rolls')
        if card['rarity'] == 'SSR': await update_weekly_progress(uid, 'weekly_ssr')
        caption = f"{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']: caption += f"📝 {card['description']}\n"
        caption += f"⭐ {card['rarity']}\n📎 #{card['id']}"
        if levels_gained > 0: caption += f"\n\n⬆ Поздравляем! Вы достигли {new_level} уровня!"
        await log_action(uid, 'roll', f"Card #{card['id']} {card['rarity']}")
        return card, caption, levels_gained, new_level
    
    async def perform_event_roll(uid):
        u = await get_user(uid)
        cards = await get_event_cards()
        if not cards: return None, "В базе нет ивентовых карт!", 0, u['level']
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        progress = u['event_guarantor']
        is_guaranteed = progress >= 50
        guarantee_text = ""
        if is_guaranteed and L_cards:
            card = random.choice(L_cards)
            await upd_event_guarantor(uid, 0)
            guarantee_text = "🎉 ИВЕНТ-ГАРАНТ! "
            progress = 0
        else:
            if L_cards and random.random() < 0.02:
                card = random.choice(L_cards)
                await upd_event_guarantor(uid, 0)
                guarantee_text = "🌟 L-КАРТА! "
                progress = 0
            else:
                card = random.choice(normal if normal else cards)
                progress += 1
                await upd_event_guarantor(uid, progress)
        await add_card_to_user(uid, card['id'], is_original=True)
        levels_gained, new_level = await add_xp(uid, 20)
        caption = f"{guarantee_text}{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']: caption += f"📝 {card['description']}\n"
        caption += f"⭐ {card['rarity']}\n📎 #{card['id']}\n📊 Ивент-гарант: {progress}/50"
        if levels_gained > 0: caption += f"\n\n⬆ Поздравляем! Вы достигли {new_level} уровня!"
        await log_action(uid, 'event_roll', f"Card #{card['id']} {card['rarity']}")
        return card, caption, levels_gained, new_level
    
    async def send_card_with_break(msg, card, caption):
        uid = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id
        user_card = await get_user_card(uid, card['id'])
        kb = None
        if user_card and user_card['quantity'] > 1:
            extra = user_card['quantity'] - 1 if user_card['is_original'] else user_card['quantity']
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔨 Разбить (+{extra}💎)", callback_data=f"break_{card['id']}")]
            ])
        try:
            if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=kb)
            else: await msg.answer(caption, reply_markup=kb)
        except: await msg.answer(caption, reply_markup=kb)
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u or u['rolls'] <= 0:
            await msg.answer("❌ Нет круток!", reply_markup=permanent_keyboard()); return
        await upd_rolls(msg.from_user.id, -1)
        card, caption, levels, new_level = await perform_regular_roll(msg.from_user.id)
        if card is None: await msg.answer(caption); return
        await update_task_progress(msg.from_user.id, 'roll')
        achievements = await check_achievements(msg.from_user.id)
        await send_card_with_break(msg, card, caption)
        if achievements:
            for ach in achievements: await msg.answer(f"🏅 {ach['icon']} {ach['name']}!")
        if levels > 0:
            await msg.answer(f"🎉 Вы достигли {new_level} уровня!\nНажми ⬆ Уровни чтобы получить награду!")
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): await msg.answer("🎉 +1 бонусная крутка!")
    
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5: await msg.answer("❌ 5💎!"); return
        await upd_diamonds(msg.from_user.id, -5)
        card, caption, levels, new_level = await perform_regular_roll(msg.from_user.id)
        if card: await send_card_with_break(msg, card, "💎 Премиум!\n" + caption)
        if levels > 0: await msg.answer(f"🎉 {new_level} уровень!")
    
    @dp.message(F.text == "🎪 Ивент-крутка")
    async def event_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['event_rolls'] <= 0:
            await msg.answer(f"❌ Нет ивент-круток!\n📊 Гарант: {u['event_guarantor']}/50"); return
        await upd_event_rolls(msg.from_user.id, -1)
        await update_task_progress(msg.from_user.id, 'event_roll')
        card, caption, levels, new_level = await perform_event_roll(msg.from_user.id)
        if card is None: await msg.answer(caption); return
        achievements = await check_achievements(msg.from_user.id)
        await send_card_with_break(msg, card, caption)
        if achievements:
            for ach in achievements: await msg.answer(f"🏅 {ach['icon']} {ach['name']}!")
        if levels > 0: await msg.answer(f"🎉 {new_level} уровень!")
    
    # ==================== КОЛЕСО ====================
    async def spin_fortune(msg):
        prizes = []
        for p in FORTUNE_PRIZES: prizes.extend([p] * p['weight'])
        prize = random.choice(prizes)
        card = None
        if prize['prize'] == 'roll': await upd_rolls(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'diamond': await upd_diamonds(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_regular_cards()
            if cards: card = random.choice(cards); await add_card_to_user(msg.from_user.id, card['id'], is_original=True)
            else: prize = {"prize": "nothing", "value": 0, "desc": "❌ Ничего"}
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] > 0: await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
        await add_xp(msg.from_user.id, 5)
        await update_task_progress(msg.from_user.id, 'fortune')
        await update_weekly_progress(msg.from_user.id, 'weekly_fortune')
        if card:
            caption = f"🎡 Колесо!\n🎴 {rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
            await send_card_with_break(msg, card, caption)
        else: await msg.answer(f"🎡 Колесо!\n\n{prize['desc']}")
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вр. - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вр. - 3💎", callback_data="fortune_buy_5")],
            ])
            await msg.answer("🎡 Нет вращений!\nКупить:", reply_markup=kb)
        else:
            await msg.answer(f"🎡 Вращений: {u['fortune_spins']}")
            await spin_fortune(msg)
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call: types.CallbackQuery):
        amount = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3}
        price = prices[amount]
        u = await get_user(call.from_user.id)
        if u['diamonds'] < price: await call.answer(f"❌ {price}💎!", show_alert=True); return
        await upd_diamonds(call.from_user.id, -price)
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + amount)
        await call.answer(f"✅ +{amount}!", show_alert=True)
        for _ in range(amount): await spin_fortune(call.message)
    
    # ==================== ПРОФИЛЬ ====================
    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u: return
        cards = await get_card_count(msg.from_user.id)
        xp_needed = u['level'] * 100 + 50
        progress_bar = "▓" * int(u['xp']/xp_needed*10) + "░" * (10 - int(u['xp']/xp_needed*10))
        text = (
            f"👤 {u['username']} | ⭐ Ур.{u['level']}\n"
            f"📊 XP: {u['xp']}/{xp_needed} [{progress_bar}]\n\n"
            f"💎 {u['diamonds']} | 🎲 {u['rolls']} | 🎪 {u['event_rolls']}\n"
            f"🎴 Карт: {cards} | 🎡 Колесо: {u['fortune_spins']}\n"
            f"📊 Гарант: {u['event_guarantor']}/50"
        )
        await update_task_progress(msg.from_user.id, 'profile')
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== СИСТЕМА УРОВНЕЙ ====================
    @dp.message(F.text == "⬆ Уровни")
    async def levels_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        xp_needed = u['level'] * 100 + 50
        rewards = await get_level_rewards(msg.from_user.id)
        
        text = (
            f"⬆ Система уровней\n\n"
            f"⭐ Уровень: {u['level']}\n"
            f"📊 XP: {u['xp']}/{xp_needed}\n\n"
            f"🎁 Как получать XP:\n"
            f"🎲 Крутка: +10 XP\n"
            f"💎 Премиум: +10 XP\n"
            f"🎪 Ивент: +20 XP\n"
            f"🔨 Разбитие: +2 XP\n"
            f"🎡 Колесо: +5 XP\n"
            f"⚔️ Дуэль: +15 XP\n\n"
            f"🏆 Награды за уровни:\n"
            f"2: +1🎲 | 3: +2💎 | 4: +1🎲 +1💎\n"
            f"5: +1🎪 | 6: +2🎲 | 7: +3💎\n"
            f"8: +1🎲 +1🎪 | 9: +5💎 | 10: +3🎲 +3💎 +1🎪\n"
        )
        
        if rewards:
            text += f"\n🎁 Доступно наград: {len(rewards)}!\nНажми кнопку чтобы получить:"
            buttons = []
            for r in rewards[:5]:
                buttons.append([InlineKeyboardButton(
                    text=f"🎁 Уровень {r['level']}",
                    callback_data=f"claim_level_{r['level']}"
                )])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("claim_level_"))
    async def claim_level(call: types.CallbackQuery):
        level = int(call.data.split("_")[2])
        reward = await claim_level_reward(call.from_user.id, level)
        if reward:
            desc = " ".join([f"+{v}{'🎲' if k=='rolls' else '💎' if k=='diamonds' else '🎪'}" for k,v in reward.items()])
            await call.answer(f"✅ Получено: {desc}!", show_alert=True)
        else:
            await call.answer("❌ Награда не найдена или уже получена", show_alert=True)
    
    # ==================== ИНВЕНТАРЬ ====================
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_btn(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        if not cards: await msg.answer("🎒 Пусто"); return
        text = "🎒 Карты:\n\n"; buttons = []
        for card in cards[:30]:
            orig = "🔒" if card['is_original'] else ""
            ev = "🎪" if card['is_event_card'] else ""
            text += f"{orig}{ev}{rarity_emoji(card['rarity'])} #{card['id']} {card['name']} x{card['quantity']}\n"
            buttons.append([InlineKeyboardButton(text=f"📋 #{card['id']} {card['name']}", callback_data=f"cardinfo_{card['id']}")])
        await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("cardinfo_"))
    async def card_info(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        card = await get_card_by_id(card_id)
        if not card: return
        uc = await get_user_card(call.from_user.id, card_id)
        qty = uc['quantity'] if uc else 0
        text = f"{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['is_event_card']: text += "🎪 ИВЕНТ\n"
        if card['description']: text += f"📝 {card['description']}\n"
        text += f"⭐ {card['rarity']}\n📎 #{card['id']}"
        if card['is_L_card']: text += "\n🌟 L-КАРТА!"
        if qty: text += f"\n📦 У вас: {qty}"
        kb_buttons = []
        if qty > 1:
            extra = qty - 1 if uc['is_original'] else qty
            kb_buttons.append([InlineKeyboardButton(text=f"🔨 +1💎", callback_data=f"breakone_{card_id}"),
                              InlineKeyboardButton(text=f"💥 +{extra}💎", callback_data=f"break_{card_id}")])
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
        s, _ = await remove_card(call.from_user.id, cid, 1)
        if s: await upd_diamonds(call.from_user.id, 1); await add_xp(call.from_user.id, 2); await update_task_progress(call.from_user.id, 'break'); await update_weekly_progress(call.from_user.id, 'weekly_break'); await call.answer("✅ +1💎!")
        else: await call.answer("❌")
    
    @dp.callback_query(F.data.startswith("break_"))
    async def ba(call):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1: return
        bq = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        async with aiosqlite.connect(DB_PATH) as db:
            if uc['is_original']: await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            else: await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
            await db.commit()
        await upd_diamonds(call.from_user.id, bq)
        for _ in range(bq): await add_xp(call.from_user.id, 2); await update_task_progress(call.from_user.id, 'break'); await update_weekly_progress(call.from_user.id, 'weekly_break')
        await call.answer(f"✅ +{bq}💎!")
    
    @dp.callback_query(F.data.startswith("breakcustom_"))
    async def bc(call, state: FSMContext):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1: return
        mx = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        await state.update_data(bcid=cid, mx=mx)
        await call.message.answer(f"🔢 Сколько? (1-{mx}):")
        await state.set_state(BreakCustomStates.waiting_for_quantity)
        await call.answer()
    
    @dp.message(StateFilter(BreakCustomStates.waiting_for_quantity))
    async def bcm(msg, state: FSMContext):
        try:
            q = int(msg.text.strip())
            d = await state.get_data()
            if q < 1 or q > d['mx']: await msg.answer(f"❌ 1-{d['mx']}!"); return
            s, _ = await remove_card(msg.from_user.id, d['bcid'], q)
            if s:
                await upd_diamonds(msg.from_user.id, q)
                for _ in range(q): await add_xp(msg.from_user.id, 2); await update_task_progress(msg.from_user.id, 'break'); await update_weekly_progress(msg.from_user.id, 'weekly_break')
                await msg.answer(f"✅ +{q}💎!")
            await state.clear()
        except: await msg.answer("❌ Число!")
    
    @dp.callback_query(F.data.startswith("sellcard_"))
    async def sc(call):
        cid = int(call.data.split("_")[1])
        await call.message.answer(f"💱 /sell {cid} ЦЕНА")
        await call.answer()
    
    # ==================== ЗАДАНИЯ ====================
    @dp.message(F.text == "📋 Задания")
    async def tasks_btn(msg: types.Message):
        tasks = await get_daily_tasks(msg.from_user.id)
        text = "📋 Ежедневные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            ti = next((x for x in TASK_TYPES if x['type'] == t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id): text += "\n🎉 +1🎲!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "📅 Неделя")
    async def weekly_btn(msg: types.Message):
        tasks = await get_weekly_tasks(msg.from_user.id)
        text = "📅 Еженедельные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            ti = next((x for x in WEEKLY_TASK_TYPES if x['type'] == t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        completed_all = all(t['completed'] for t in tasks)
        if completed_all and not any(t['reward_claimed'] for t in tasks):
            text += "\n🎁 Награда: +3💎 +2🎲 +1🎪\nНажми /claim_weekly чтобы получить!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("claim_weekly"))
    async def claim_weekly(msg: types.Message):
        tasks = await get_weekly_tasks(msg.from_user.id)
        if not tasks: return
        if all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            today = datetime.now()
            ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE weekly_tasks SET reward_claimed=1 WHERE user_id=? AND week_start=?", (msg.from_user.id, ws))
                await db.commit()
            await upd_diamonds(msg.from_user.id, 3)
            await upd_rolls(msg.from_user.id, 2)
            await upd_event_rolls(msg.from_user.id, 1)
            await add_xp(msg.from_user.id, 50)
            await msg.answer("✅ Награда получена! +3💎 +2🎲 +1🎪 +50XP")
        else:
            await msg.answer("❌ Не все задания выполнены или награда уже получена!")
    
    # ==================== БИРЖА, АУКЦИОН, ОБМЕН ====================
    @dp.message(F.text == "💱 Биржа")
    async def market_btn(msg: types.Message):
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
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data == "msi"): await call.message.answer("/find НОМЕР"); await call.answer()
    @dp.callback_query(F.data == "msi2"): await call.message.answer("/sell НОМЕР ЦЕНА"); await call.answer()
    
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
            if pr < 1: await msg.answer("❌ >0!"); return
            uc = await get_user_card(msg.from_user.id, cid)
            if not uc: await msg.answer(f"❌ Нет #{cid}!"); return
            if uc['is_original'] and uc['quantity'] <= 1: await msg.answer("❌ Оригинал!"); return
            await remove_card(msg.from_user.id, cid, 1)
            await create_market_listing(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ #{cid} за {pr}💎!")
        except: await msg.answer("❌ /sell НОМЕР ЦЕНА")
    
    @dp.callback_query(F.data.startswith("mbuy_"))
    async def mb(call):
        lid = int(call.data.split("_")[1])
        s, m = await buy_listing(lid, call.from_user.id)
        await call.answer(f"{'✅' if s else '❌'} {m}", show_alert=True)
    
    @dp.message(F.text == "🏪 Аукцион")
    async def auc_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Активные", callback_data="auction_view")],
            [InlineKeyboardButton(text="📊 Создать /auction", callback_data="auction_info")],
        ])
        await msg.answer("🏪 Аукцион:", reply_markup=kb)
    
    @dp.callback_query(F.data == "auction_view")
    async def av(call):
        auctions = await get_active_auctions()
        if not auctions: await call.message.answer("📋 Нет активных"); await call.answer(); return
        text = "📋 Аукционы:\n\n"; buttons = []
        for a in auctions[:10]:
            text += f"#{a['id']} {rarity_emoji(a['rarity'])} {a['name']} | {a['current_price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f"Ставка >{a['current_price']}💎", callback_data=f"abid_{a['id']}")])
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data == "auction_info")
    async def ai(call): await call.message.answer("📊 /auction ID_карты СТАРТ_ЦЕНА\nПример: /auction 5 10"); await call.answer()
    
    @dp.message(Command("auction"))
    async def acmd(msg):
        try:
            p = msg.text.split(); cid, pr = int(p[1]), int(p[2])
            uc = await get_user_card(msg.from_user.id, cid)
            if not uc: await msg.answer(f"❌ Нет #{cid}!"); return
            await remove_card(msg.from_user.id, cid, 1)
            await create_auction(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ Аукцион создан! #{cid} от {pr}💎")
        except: await msg.answer("❌ /auction НОМЕР ЦЕНА")
    
    @dp.callback_query(F.data.startswith("abid_"))
    async def abid(call, state: FSMContext):
        aid = int(call.data.split("_")[1])
        await state.update_data(aid=aid)
        await call.message.answer(f"💰 Введи сумму ставки:")
        await state.set_state(AuctionStates.waiting_for_bid)
        await call.answer()
    
    @dp.message(StateFilter(AuctionStates.waiting_for_bid))
    async def bid_msg(msg, state: FSMContext):
        try:
            amount = int(msg.text.strip())
            data = await state.get_data()
            s, m = await bid_auction(data['aid'], msg.from_user.id, amount)
            await msg.answer(f"{'✅' if s else '❌'} {m}")
            await state.clear()
        except: await msg.answer("❌ Введи число!")
    
    @dp.message(F.text == "🔄 Обмен")
    async def trade_btn(msg): await msg.answer("🔄 /trade @user ID_моей ID_его")
    
    @dp.message(Command("trade"))
    async def tcmd(msg):
        try:
            p = msg.text.split()
            if len(p) != 4: await msg.answer("❌ /trade @user ID ID"); return
            tun = p[1].replace("@",""); fc, tc = int(p[2]), int(p[3])
            mc = await get_user_card(msg.from_user.id, fc)
            if not mc: await msg.answer(f"❌ Нет #{fc}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (tun,)) as c:
                    tu = await c.fetchone()
            if not tu: await msg.answer(f"❌ @{tun}!"); return
            tuid = tu[0]
            hc = await get_user_card(tuid, tc)
            if not hc: await msg.answer(f"❌ У @{tun} нет #{tc}!"); return
            fcard = await get_card_by_id(fc); tcard = await get_card_by_id(tc)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"tac_{msg.from_user.id}_{fc}_{tc}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"tdc_{msg.from_user.id}")],
            ])
            await bot.send_message(tuid, f"🔄 ОБМЕН!\nОт: @{msg.from_user.username}\n"
                f"Предлагает: {rarity_emoji(fcard['rarity'])} {fcard['name']} (#{fc})\n"
                f"Хочет: {rarity_emoji(tcard['rarity'])} {tcard['name']} (#{tc})\n\nПринять?", reply_markup=kb)
            await msg.answer(f"✅ @{tun}!")
        except: await msg.answer("❌")
    
    @dp.callback_query(F.data.startswith("tac_"))
    async def tac(call):
        p = call.data.split("_"); fu, fc, tc = int(p[1]), int(p[2]), int(p[3])
        if not await get_user_card(fu, fc) or not await get_user_card(call.from_user.id, tc):
            await call.message.edit_text("❌"); return
        await remove_card(fu, fc); await remove_card(call.from_user.id, tc)
        await add_card_to_user(call.from_user.id, fc); await add_card_to_user(fu, tc)
        await call.message.edit_text("✅!"); await call.answer()
    
    @dp.callback_query(F.data.startswith("tdc_"))
    async def tdc(call):
        await call.message.edit_text("❌"); await call.answer()
    
    # ==================== ДУЭЛИ ====================
    @dp.message(F.text == "⚔️ Дуэль")
    async def duel_btn(msg): await msg.answer("⚔️ /duel @user")
    
    @dp.message(Command("duel"))
    async def dcmd(msg):
        try:
            p = msg.text.split()
            if len(p) < 2: await msg.answer("❌ /duel @user"); return
            oun = p[1].replace("@","")
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (oun,)) as c:
                    ou = await c.fetchone()
            if not ou: await msg.answer(f"❌ @{oun}!"); return
            oid = ou[0]
            if oid == msg.from_user.id: await msg.answer("❌ Нельзя себя!"); return
            u = await get_user(msg.from_user.id)
            if u['diamonds'] < 1: await msg.answer("❌ 1💎!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT INTO duels (challenger_id, opponent_id) VALUES (?,?)", (msg.from_user.id, oid))
                await db.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"aduel_{msg.from_user.id}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"dduel_{msg.from_user.id}")],
            ])
            await bot.send_message(oid, f"⚔️ @{msg.from_user.username}\nСтавка: 1💎\nПринять?", reply_markup=kb)
            await msg.answer(f"✅ @{oun}!")
        except: await msg.answer("❌")
    
    @dp.callback_query(F.data.startswith("aduel_"))
    async def ad(call):
        cid = int(call.data.split("_")[1])
        await call.message.answer("⚔️ Выбери карту: /pick ID")
        try: await bot.send_message(cid, "⚔️ Выбери карту: /pick ID")
        except: pass
        await call.answer()
    
    @dp.callback_query(F.data.startswith("dduel_"))
    async def dd(call):
        await call.message.edit_text("❌ Отклонен"); await call.answer()
    
    @dp.message(Command("pick"))
    async def pcmd(msg):
        try:
            cid = int(msg.text.replace("/pick","").strip())
            if not await get_user_card(msg.from_user.id, cid): await msg.answer(f"❌ Нет #{cid}!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE (challenger_id=? OR opponent_id=?) AND status='pending'",
                                      (msg.from_user.id, msg.from_user.id)) as c:
                    duel = await c.fetchone()
            if not duel: await msg.answer("❌ Нет дуэли!"); return
            if msg.from_user.id == duel['challenger_id']:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE duels SET challenger_card_id=? WHERE id=?", (cid, duel['id'])); await db.commit()
            else:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE duels SET opponent_card_id=? WHERE id=?", (cid, duel['id'])); await db.commit()
            await msg.answer(f"✅ #{cid} выбрана!")
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM duels WHERE id=?", (duel['id'],)) as c:
                    ud = await c.fetchone()
            if ud['challenger_card_id'] and ud['opponent_card_id']:
                await resolve_duel(ud)
        except: await msg.answer("❌ /pick ID")
    
    async def resolve_duel(duel):
        cc = await get_card_by_id(duel['challenger_card_id'])
        oc = await get_card_by_id(duel['opponent_card_id'])
        rp = {'R':1,'SR':2,'SSR':3,'L':4}
        cp, op = rp.get(cc['rarity'],0), rp.get(oc['rarity'],0)
        wid = duel['challenger_id'] if cp > op else (duel['opponent_id'] if op > cp else (duel['challenger_id'] if cc['id'] > oc['id'] else duel['opponent_id']))
        lid = duel['opponent_id'] if wid == duel['challenger_id'] else duel['challenger_id']
        await upd_diamonds(wid, 2); await upd_diamonds(lid, -1)
        await add_xp(wid, 15); await add_xp(lid, 5)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=?", (wid, duel['id'])); await db.commit()
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try: await bot.send_message(uid, f"⚔️ Победитель: {wid}!")
            except: pass
    
    # ==================== ДРУЗЬЯ ====================
    @dp.message(F.text == "👥 Друзья")
    async def friends_btn(msg: types.Message):
        friends = await get_friends(msg.from_user.id)
        text = "👥 Друзья:\n\n"
        if friends:
            for f in friends: text += f"• @{f['username']}\n"
        else: text += "Пока нет друзей\n"
        text += "\n/friend add @user - добавить\n/friend accept @user - принять\n/friend remove @user - удалить"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("friend"))
    async def fcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) < 3: await msg.answer("❌ /friend add/accept/remove @user"); return
            action = p[1]; un = p[2].replace("@","")
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c:
                    fu = await c.fetchone()
            if not fu: await msg.answer(f"❌ @{un}!"); return
            fid = fu[0]
            if action == "add":
                await send_friend_request(msg.from_user.id, fid)
                await msg.answer(f"✅ Заявка @{un}!"); await bot.send_message(fid, f"👥 @{msg.from_user.username} хочет в друзья!\n/friend accept @{msg.from_user.username}")
            elif action == "accept":
                await accept_friend(msg.from_user.id, fid)
                await msg.answer(f"✅ @{un} в друзьях!")
            elif action == "remove":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (msg.from_user.id, fid, fid, msg.from_user.id))
                    await db.commit()
                await msg.answer(f"✅ @{un} удален")
        except: await msg.answer("❌")
    
    # ==================== ГИЛЬДИИ ====================
    @dp.message(F.text == "🏰 Гильдия")
    async def guild_btn(msg: types.Message):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT g.* FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=?
            """, (msg.from_user.id,)) as c:
                guild = await c.fetchone()
        if guild:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id=?", (guild['id'],)) as c:
                    count = (await c.fetchone())[0]
            await msg.answer(
                f"🏰 {guild['name']}\n👥 {count} участников\n\n"
                "/guild info - инфо\n/guild members - список\n/guild leave - покинуть\n"
                "/guild invite @user - пригласить\n/guild kick @user - выгнать"
            )
        else:
            await msg.answer(
                "🏰 Гильдии\n\n"
                "/guild create НАЗВАНИЕ - создать (10💎)\n"
                "/guild join НАЗВАНИЕ - подать заявку\n"
                "/guild list - список гильдий"
            )
    
    @dp.message(Command("guild"))
    async def gcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) < 2: await msg.answer("❌ /guild create/join/leave/list/info/members/invite/kick"); return
            action = p[1]
            
            if action == "create":
                if len(p) < 3: await msg.answer("❌ /guild create НАЗВАНИЕ"); return
                name = " ".join(p[2:])
                u = await get_user(msg.from_user.id)
                if u['diamonds'] < 10: await msg.answer("❌ 10💎!"); return
                await upd_diamonds(msg.from_user.id, -10)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT INTO guilds (name, owner_id) VALUES (?,?)", (name, msg.from_user.id))
                    await db.commit()
                    async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c:
                        gid = (await c.fetchone())[0]
                    await db.execute("INSERT INTO guild_members (guild_id, user_id, role) VALUES (?,?,'owner')", (gid, msg.from_user.id))
                    await db.commit()
                await msg.answer(f"✅ Гильдия '{name}' создана!")
            
            elif action == "join":
                if len(p) < 3: await msg.answer("❌ /guild join НАЗВАНИЕ"); return
                name = " ".join(p[2:])
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c:
                        g = await c.fetchone()
                if not g: await msg.answer(f"❌ '{name}' нет!"); return
                gid = g[0]
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("INSERT OR IGNORE INTO guild_join_requests (guild_id, user_id) VALUES (?,?)", (gid, msg.from_user.id))
                    await db.commit()
                    async with db.execute("SELECT owner_id FROM guilds WHERE id=?", (gid,)) as c:
                        oid = (await c.fetchone())[0]
                await msg.answer("✅ Заявка отправлена!")
                try: await bot.send_message(oid, f"📩 @{msg.from_user.username} хочет в '{name}'\n/guild accept @{msg.from_user.username}")
                except: pass
            
            elif action == "accept":
                if len(p) < 3: await msg.answer("❌ /guild accept @user"); return
                un = p[2].replace("@","")
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c:
                        uid = await c.fetchone()
                    if not uid: await msg.answer("❌"); return
                    uid = uid[0]
                    async with db.execute("SELECT g.id FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=? AND gm.role='owner'", (msg.from_user.id,)) as c:
                        g = await c.fetchone()
                    if not g: await msg.answer("❌ Вы не глава!"); return
                    await db.execute("DELETE FROM guild_join_requests WHERE guild_id=? AND user_id=?", (g[0], uid))
                    await db.execute("INSERT OR IGNORE INTO guild_members (guild_id, user_id) VALUES (?,?)", (g[0], uid))
                    await db.commit()
                await msg.answer(f"✅ @{un} принят!")
                try: await bot.send_message(uid, "✅ Вы приняты в гильдию!")
                except: pass
            
            elif action == "leave":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("DELETE FROM guild_members WHERE user_id=?", (msg.from_user.id,))
                    await db.commit()
                await msg.answer("✅ Вы покинули гильдию")
            
            elif action == "invite":
                if len(p) < 3: await msg.answer("❌ /guild invite @user"); return
                un = p[2].replace("@","")
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c:
                        uid = await c.fetchone()
                    if not uid: await msg.answer("❌"); return
                    uid = uid[0]
                await msg.answer(f"✅ Приглашение @{un}!")
                try: await bot.send_message(uid, f"🏰 @{msg.from_user.username} приглашает в гильдию!\n/guild join НАЗВАНИЕ")
                except: pass
            
            elif action == "kick":
                if len(p) < 3: await msg.answer("❌ /guild kick @user"); return
                un = p[2].replace("@","")
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c:
                        uid = await c.fetchone()
                    if not uid: await msg.answer("❌"); return
                    uid = uid[0]
                    async with db.execute("SELECT g.id FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=? AND gm.role='owner'", (msg.from_user.id,)) as c:
                        g = await c.fetchone()
                    if not g: await msg.answer("❌ Не глава!"); return
                    await db.execute("DELETE FROM guild_members WHERE guild_id=? AND user_id=?", (g[0], uid))
                    await db.commit()
                await msg.answer(f"✅ @{un} исключен")
            
            elif action == "list":
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute("SELECT g.name, COUNT(gm.user_id) as cnt FROM guilds g LEFT JOIN guild_members gm ON g.id=gm.guild_id GROUP BY g.id") as c:
                        guilds = await c.fetchall()
                if not guilds: await msg.answer("📋 Нет гильдий"); return
                text = "📋 Гильдии:\n\n"
                for g in guilds: text += f"• {g['name']} ({g['cnt']}👥)\n"
                await msg.answer(text)
            
            elif action == "members":
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute("""
                        SELECT u.username, gm.role FROM guild_members gm
                        JOIN users u ON gm.user_id=u.user_id
                        JOIN guilds g ON gm.guild_id=g.id
                        WHERE gm.user_id IN (SELECT user_id FROM guild_members WHERE user_id=?)
                    """, (msg.from_user.id,)) as c:
                        members = await c.fetchall()
                if not members: await msg.answer("❌ Вы не в гильдии"); return
                text = "👥 Участники:\n\n"
                for m in members: text += f"{'👑' if m['role']=='owner' else '👤'} @{m['username']}\n"
                await msg.answer(text)
            
            elif action == "info":
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute("""
                        SELECT g.* FROM guilds g JOIN guild_members gm ON g.id=gm.guild_id WHERE gm.user_id=?
                    """, (msg.from_user.id,)) as c:
                        g = await c.fetchone()
                if not g: await msg.answer("❌ Вы не в гильдии"); return
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id=?", (g['id'],)) as c:
                        cnt = (await c.fetchone())[0]
                await msg.answer(f"🏰 {g['name']}\n👑 Глава: {g['owner_id']}\n👥 {cnt} участников")
            
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    
    # ==================== ПРОМОКОДЫ ====================
    @dp.message(F.text == "🎫 Промокод")
    async def promo_btn(msg: types.Message, state: FSMContext):
        await msg.answer("🎫 Введи промокод:")
        await state.set_state(PromoStates.waiting_for_code)
    
    @dp.message(StateFilter(PromoStates.waiting_for_code))
    async def promo_code(msg: types.Message, state: FSMContext):
        code = msg.text.strip().upper()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM promocodes WHERE code=? AND uses_left>0", (code,)) as c:
                promo = await c.fetchone()
        if not promo:
            await msg.answer("❌ Промокод недействителен!")
        else:
            if promo['type'] == 'diamonds': await upd_diamonds(msg.from_user.id, promo['value'])
            elif promo['type'] == 'rolls': await upd_rolls(msg.from_user.id, promo['value'])
            elif promo['type'] == 'event_rolls': await upd_event_rolls(msg.from_user.id, promo['value'])
            elif promo['type'] == 'card':
                card = await get_card_by_id(promo['value'])
                if card: await add_card_to_user(msg.from_user.id, promo['value'], is_original=True)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE promocodes SET uses_left=uses_left-1 WHERE code=?", (code,))
                await db.commit()
            await msg.answer(f"✅ Промокод активирован! +{promo['value']} {promo['type']}")
        await state.clear()
    
    # ==================== ЛИДЕРЫ, ДОСТИЖЕНИЯ, КАРТЫ, ПОМОЩЬ ====================
    @dp.message(F.text == "🏆 Лидеры")
    async def lead_btn(msg):
        top = await get_leaders(10)
        if not top: await msg.answer("🏆 Пусто"); return
        text = "🏆 Топ-10 по картам:\n\n"
        for i,u in enumerate(top): text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} @{u['username']} - {u['total']} карт\n"
        ltop = await get_level_leaders(5)
        if ltop:
            text += "\n⭐ Топ-5 по уровням:\n"
            for i,u in enumerate(ltop): text += f"{['🥇','🥈','🥉'][i] if i<3 else f'{i+1}.'} @{u['username']} - Ур.{u['level']}\n"
        await msg.answer(text)
    
    @dp.message(F.text == "🏅 Достижения")
    async def ach_btn(msg):
        u = await get_user(msg.from_user.id)
        cards = await get_user_cards(msg.from_user.id)
        tc = sum(c['quantity'] for c in cards)
        lc = sum(c['quantity'] for c in cards if c['is_L_card'])
        text = "🏅 Достижения:\n\n"
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute("SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                    row = await c.fetchone()
                    text += f"{'✅' if row and row[0] else '🔒'} {ach['icon']} {ach['name']}\n"
        text += f"\n📊 Карт: {tc} | L: {lc} | Круток: {u['total_rolls']} | Уровень: {u['level']}"
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
        await msg.answer("📚 Обычные:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
    @dp.message(F.text == "❓ Помощь")
    async def help_btn(msg):
        await msg.answer(
            "🎲 Крутить | 💎 Премиум 5💎 | 🎪 Ивент\n🎡 Колесо | 🏪 Аукцион | ⚔️ Дуэли\n"
            "👥 Друзья | 🏰 Гильдии | 🎫 Промокоды\n📋 Ежедневные | 📅 Еженедельные\n"
            "⬆ Уровни - получай XP и награды!\n🕐 Выдачи 7:00 и 17:00 МСК"
        )
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg): await msg.answer("🎮 Меню:", reply_markup=permanent_keyboard())
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Обычная", callback_data="admin_add")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="admin_add_event")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="admin_edit")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🎫 Промокод", callback_data="admin_promo")],
            [InlineKeyboardButton(text="⛔ Бан/Разбан", callback_data="admin_ban")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        ])
        await msg.answer(
            "👑 Админ\n\n"
            "/addcard /addeventcard /editcard /cards /delcard\n"
            "/givediamonds @user кол-во\n/giverolls @user кол-во\n/giveevent @user кол-во\n/givecards @user кол-во\n/givecard @user ID\n"
            "/user @user - инфо\n/ban @user\n/unban @user\n/broadcast\n/stats\n/promo КОД ТИП ЗНАЧЕНИЕ ИСПОЛЬЗОВАНИЙ\n"
            "/force_morning\n/force_evening\n/reset @user\n/logs [кол-во]",
            reply_markup=kb
        )
    
    # Добавление карт
    @dp.callback_query(F.data == "admin_add")
    async def aas(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(is_event=False)
        await call.message.answer("📝 Обычная\nШаг 1/4\nВведи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name); await call.answer()
    
    @dp.callback_query(F.data == "admin_add_event")
    async def aae(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        await state.update_data(is_event=True)
        await call.message.answer("🎪 Ивент\nШаг 1/4\nВведи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name); await call.answer()
    
    @dp.message(Command("addcard"))
    async def ac(msg, state): await state.update_data(is_event=False); await msg.answer("📝 Обычная\nШаг 1/4"); await state.set_state(AddCardStates.waiting_for_name)
    @dp.message(Command("addeventcard"))
    async def aec(msg, state): await state.update_data(is_event=True); await msg.answer("🎪 Ивент\nШаг 1/4"); await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def an(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(name=msg.text.strip()); await msg.answer("📝 Шаг 2/4\nОписание:")
        await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def ad(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nРедкость:", reply_markup=rarity_keyboard())
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def ar(call, state):
        if call.from_user.id not in ADMIN_IDS: return
        rarity = call.data.split("_")[1]; await state.update_data(rarity=rarity)
        await call.message.answer(f"📝 Шаг 4/4\n{rarity}\nОтправь фото или 'нет'")
        await state.set_state(AddCardStates.waiting_for_photo); await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def ap(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data()
        file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity'] == 'L'; is_event = data.get('is_event', False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO cards (name, description, file_id, rarity, is_L_card, is_event_card) VALUES (?,?,?,?,?,?)",
                           (data['name'], data['description'], file_id, data['rarity'], is_L, is_event))
            await db.commit()
        await msg.answer(f"✅ {'🎪' if is_event else ''} {data['name']} добавлена!"); await state.clear()
    
    # Изменение карт
    @dp.callback_query(F.data == "admin_edit")
    async def ae(call): await call.message.answer("✏️ /editcard ID"); await call.answer()
    
    @dp.message(Command("editcard"))
    async def ec(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            cid = int(msg.text.replace("/editcard","").strip())
            card = await get_card_by_id(cid)
            if not card: await msg.answer(f"❌ #{cid}"); return
            await state.update_data(edit_card_id=cid)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📛 Имя", callback_data="ed_name")],
                [InlineKeyboardButton(text="📝 Описание", callback_data="ed_desc")],
                [InlineKeyboardButton(text="⭐ Редкость", callback_data="ed_rarity")],
                [InlineKeyboardButton(text="🖼 Фото", callback_data="ed_photo")],
                [InlineKeyboardButton(text="🎪 Ивент?", callback_data="ed_event")],
            ])
            await msg.answer(f"✏️ #{cid} '{card['name']}'", reply_markup=kb)
        except: await msg.answer("❌ /editcard ID")
    
    @dp.callback_query(F.data == "ed_name")
    async def en(call, state): await state.set_state(EditCardStates.waiting_for_value); await state.update_data(edit_field='name'); await call.message.answer("📛 Имя:"); await call.answer()
    @dp.callback_query(F.data == "ed_desc")
    async def ed(call, state): await state.set_state(EditCardStates.waiting_for_value); await state.update_data(edit_field='description'); await call.message.answer("📝 Описание:"); await call.answer()
    @dp.callback_query(F.data == "ed_rarity")
    async def er(call, state): await state.set_state(EditCardStates.waiting_for_value); await state.update_data(edit_field='rarity'); await call.message.answer("⭐ Редкость:", reply_markup=rarity_keyboard()); await call.answer()
    @dp.callback_query(F.data == "ed_photo")
    async def ep(call, state): await state.set_state(EditCardStates.waiting_for_value); await state.update_data(edit_field='photo'); await call.message.answer("🖼 Фото:"); await call.answer()
    
    @dp.callback_query(F.data == "ed_event")
    async def ee(call):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("Используй /toggleevent ID"); await call.answer()
    
    @dp.message(Command("toggleevent"))
    async def te(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            cid = int(msg.text.replace("/toggleevent","").strip())
            card = await get_card_by_id(cid)
            if not card: return
            new = not card['is_event_card']
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE cards SET is_event_card=? WHERE id=?", (new, cid)); await db.commit()
            await msg.answer(f"✅ #{cid}: {'🎪 ИВЕНТ' if new else 'Обычная'}")
        except: pass
    
    @dp.callback_query(StateFilter(EditCardStates.waiting_for_value), F.data.startswith("rarity_"))
    async def erc(call, state):
        rarity = call.data.split("_")[1]; data = await state.get_data(); is_L = rarity == 'L'
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE cards SET rarity=?, is_L_card=? WHERE id=?", (rarity, is_L, data['edit_card_id'])); await db.commit()
        await call.message.answer(f"✅ → {rarity}!"); await state.clear(); await call.answer()
    
    @dp.message(StateFilter(EditCardStates.waiting_for_value))
    async def ev(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data(); cid, field = data['edit_card_id'], data['edit_field']
        async with aiosqlite.connect(DB_PATH) as db:
            if field == 'name': await db.execute("UPDATE cards SET name=? WHERE id=?", (msg.text.strip(), cid))
            elif field == 'description': await db.execute("UPDATE cards SET description=? WHERE id=?", (msg.text.strip(), cid))
            elif field == 'photo' and msg.photo: await db.execute("UPDATE cards SET file_id=? WHERE id=?", (msg.photo[-1].file_id, cid))
            else: await msg.answer("❌"); return
            await db.commit()
        await msg.answer(f"✅ #{cid} обновлена!"); await state.clear()
    
    # Список карт
    async def show_cards_list(target):
        cards = await get_all_cards()
        if not cards: await target.answer("📋 Нет"); return
        ro = {'L':'🌟L','SSR':'🟣SSR','SR':'🔵SR','R':'⚪R'}; g = {}
        for c in cards: g.setdefault(c['rarity'], []).append(c)
        text = "📋 Карты:\n\n"
        for r,t in ro.items():
            if r in g:
                text += f"{t} ({len(g[r])}):\n"
                for c in g[r]: text += f"  #{c['id']} {'🎪' if c['is_event_card'] else ''}{c['name']}\n"
                text += "\n"
        for i in range(0, len(text), 4000): await target.answer(text[i:i+4000])
    
    @dp.callback_query(F.data == "admin_list")
    async def alc(call): await show_cards_list(call.message); await call.answer()
    @dp.message(Command("cards"))
    async def cc(msg): await show_cards_list(msg)
    
    @dp.message(Command("delcard"))
    async def dc(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            cid = int(msg.text.replace("/delcard","").strip())
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (cid,))
                await db.execute("DELETE FROM user_cards WHERE card_id=?", (cid,))
                await db.execute("DELETE FROM market WHERE card_id=?", (cid,))
                await db.commit()
            await msg.answer(f"✅ #{cid} удалена!")
        except: pass
    
    # Выдача ресурсов (по username)
    async def resolve_user(username):
        username = username.replace("@", "")
        if username.isdigit(): return int(username)
        user = await get_user_by_username(username)
        return user['user_id'] if user else None
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def agm(call):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="gd")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="gr")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="ge")],
            [InlineKeyboardButton(text="🎴 Случ.карты", callback_data="gc")],
            [InlineKeyboardButton(text="🎯 Конкр.карта", callback_data="gs")],
        ])
        await call.message.edit_text("🎁 Выдача:", reply_markup=kb); await call.answer()
    
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
    
    @dp.message(Command("givediamonds"))
    async def gd_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); uid = await resolve_user(p[1]); am = int(p[2])
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            await upd_diamonds(uid, am); await msg.answer(f"✅ +{am}💎 пользователю {p[1]}")
        except: await msg.answer("❌ /givediamonds @user кол-во")
    
    @dp.message(Command("giverolls"))
    async def gr_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); uid = await resolve_user(p[1]); am = int(p[2])
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            await upd_rolls(uid, am); await msg.answer(f"✅ +{am}🎲 пользователю {p[1]}")
        except: await msg.answer("❌ /giverolls @user кол-во")
    
    @dp.message(Command("giveevent"))
    async def ge_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); uid = await resolve_user(p[1]); am = int(p[2])
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            await upd_event_rolls(uid, am); await msg.answer(f"✅ +{am}🎪 пользователю {p[1]}")
        except: await msg.answer("❌ /giveevent @user кол-во")
    
    @dp.message(Command("givecards"))
    async def gc_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); uid = await resolve_user(p[1]); am = int(p[2])
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            cards = await get_all_cards()
            if not cards: await msg.answer("❌ Нет карт!"); return
            for _ in range(am): await add_card_to_user(uid, random.choice(cards)['id'], is_original=True)
            await msg.answer(f"✅ +{am} карт пользователю {p[1]}")
        except: await msg.answer("❌ /givecards @user кол-во")
    
    @dp.message(Command("givecard"))
    async def gs_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); uid = await resolve_user(p[1]); cid = int(p[2])
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            card = await get_card_by_id(cid)
            if not card: await msg.answer(f"❌ Карта #{cid} не найдена!"); return
            await add_card_to_user(uid, cid, is_original=True)
            await msg.answer(f"✅ Карта #{cid} '{card['name']}' выдана {p[1]}")
        except: await msg.answer("❌ /givecard @user ID")
    
    # Просмотр профиля игрока
    @dp.message(Command("user"))
    async def user_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            un = msg.text.replace("/user","").strip()
            uid = await resolve_user(un)
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            u = await get_user(uid); cards = await get_card_count(uid)
            text = (
                f"👤 @{u['username']} (ID: {uid})\n"
                f"⭐ Ур.{u['level']} | XP: {u['xp']}/{u['level']*100+50}\n"
                f"💎 {u['diamonds']} | 🎲 {u['rolls']} | 🎪 {u['event_rolls']}\n"
                f"🎴 Карт: {cards} | 🎡 Колесо: {u['fortune_spins']}\n"
                f"🔄 Круток: {u['total_rolls']} | Гарант: {u['event_guarantor']}/50\n"
                f"⛔ Забанен: {'Да' if u['banned'] else 'Нет'}"
            )
            await msg.answer(text)
        except: await msg.answer("❌ /user @user")
    
    # Бан/разбан
    @dp.callback_query(F.data == "admin_ban")
    async def ab(call): await call.message.answer("/ban @user | /unban @user"); await call.answer()
    
    @dp.message(Command("ban"))
    async def ban_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            un = msg.text.replace("/ban","").strip()
            uid = await resolve_user(un)
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,)); await db.commit()
            await msg.answer(f"⛔ @{un} забанен!")
        except: await msg.answer("❌ /ban @user")
    
    @dp.message(Command("unban"))
    async def unban_cmd(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            un = msg.text.replace("/unban","").strip()
            uid = await resolve_user(un)
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,)); await db.commit()
            await msg.answer(f"✅ @{un} разбанен!")
        except: await msg.answer("❌ /unban @user")
    
    # Промокоды
    @dp.callback_query(F.data == "admin_promo")
    async def apromo(call): await call.message.answer("🎫 /promo КОД ТИП ЗНАЧЕНИЕ ИСП\nПример: /promo HELLO diamonds 100 50\nТипы: diamonds, rolls, event_rolls, card"); await call.answer()
    
    @dp.message(Command("promo"))
    async def promo_create(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split()
            if len(p) < 4: await msg.answer("❌ /promo КОД ТИП ЗНАЧЕНИЕ [ИСП]"); return
            code = p[1].upper(); ptype = p[2]; value = int(p[3]); uses = int(p[4]) if len(p) > 4 else 1
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR REPLACE INTO promocodes (code, type, value, uses_left, created_by) VALUES (?,?,?,?,?)",
                               (code, ptype, value, uses, msg.from_user.id))
                await db.commit()
            await msg.answer(f"✅ Промокод {code} создан! {value} {ptype}, {uses} исп.")
        except: await msg.answer("❌")
    
    # Рассылка
    @dp.callback_query(F.data == "admin_broadcast")
    async def abr(call, state): await call.message.answer("📢 Сообщение:"); await state.set_state(BroadcastStates.waiting_for_broadcast); await call.answer()
    
    @dp.message(Command("broadcast"))
    async def bcmd(msg, state): await msg.answer("📢 Сообщение:"); await state.set_state(BroadcastStates.waiting_for_broadcast)
    
    @dp.message(StateFilter(BroadcastStates.waiting_for_broadcast))
    async def bsend(msg, state):
        if msg.from_user.id not in ADMIN_IDS: return
        users = await get_all_users(); sent = 0
        for u in users:
            try: await bot.send_message(u['user_id'], msg.text or "📢"); sent += 1; await asyncio.sleep(0.05)
            except: pass
        await msg.answer(f"✅ {sent}/{len(users)}"); await state.clear()
    
    # Статистика
    @dp.callback_query(F.data == "admin_stats")
    @dp.message(Command("stats"))
    async def astats(msg_or_call):
        if isinstance(msg_or_call, types.Message):
            if msg_or_call.from_user.id not in ADMIN_IDS: return
            target = msg_or_call
        else:
            if msg_or_call.from_user.id not in ADMIN_IDS: return
            target = msg_or_call.message
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c: users = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM cards") as c: cards = (await c.fetchone())[0]
            async with db.execute("SELECT SUM(rolls) FROM users") as c: rolls = (await c.fetchone())[0] or 0
            async with db.execute("SELECT SUM(diamonds) FROM users") as c: diamonds = (await c.fetchone())[0] or 0
            async with db.execute("SELECT AVG(level) FROM users") as c: avg_level = (await c.fetchone())[0] or 0
        
        text = (
            f"📊 Статистика:\n"
            f"👥 Игроков: {users}\n"
            f"🎴 Карт в базе: {cards}\n"
            f"🎲 Круток в обороте: {rolls}\n"
            f"💎 Алмазов: {diamonds}\n"
            f"⭐ Средний уровень: {avg_level:.1f}"
        )
        await target.answer(text)
        if isinstance(msg_or_call, types.CallbackQuery): await msg_or_call.answer()
    
    # Логи
    @dp.message(Command("logs"))
    async def logs_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            limit = int(msg.text.replace("/logs","").strip() or "20")
        except: limit = 20
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)) as c:
                logs = await c.fetchall()
        if not logs: await msg.answer("📋 Логи пусты"); return
        text = "📋 Последние действия:\n\n"
        for l in logs: text += f"[{l['timestamp']}] ID{l['user_id']}: {l['action']} - {l['details'][:50]}\n"
        await msg.answer(text[:4000])
    
    # Ручной запуск выдач
    @dp.message(Command("force_morning"))
    async def fm(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await morning_bonus()
        await msg.answer("✅ Утренняя выдача запущена")
    
    @dp.message(Command("force_evening"))
    async def fe(msg):
        if msg.from_user.id not in ADMIN_IDS: return
        await evening_bonus()
        await msg.answer("✅ Вечерняя выдача запущена")
    
    # Сброс игрока
    @dp.message(Command("reset"))
    async def reset_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            un = msg.text.replace("/reset","").strip()
            uid = await resolve_user(un)
            if not uid: await msg.answer("❌ Пользователь не найден!"); return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=0, diamonds=0, event_rolls=0, fortune_spins=0, total_rolls=0, xp=0, level=1 WHERE user_id=?", (uid,))
                await db.execute("DELETE FROM user_cards WHERE user_id=?", (uid,))
                await db.commit()
            await msg.answer(f"✅ Игрок {un} сброшен!")
        except: await msg.answer("❌ /reset @user")
    
    # ==================== ВЫДАЧИ ====================
    async def morning_bonus():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2, fortune_spins=1, event_rolls=event_rolls+1, bonus_roll_received=0")
                await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),))
                await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
                    users = await c.fetchall()
            sent = 0
            for u in users:
                try:
                    await bot.send_message(u['user_id'],
                        "🌅 Доброе утро! Вот твои утренние награды:\n\n"
                        "🎲 +2 обычные крутки\n🎡 +1 вращение колеса\n🎪 +1 ивентовая\n💎 +2 алмаза\n\n"
                        "🕐 В 17:00 МСК жди ещё!")
                    sent += 1; await asyncio.sleep(0.05)
                except: pass
            logger.info(f"☀️ Утро: {sent}/{len(users)}")
        except Exception as e: logger.error(f"Утро: {e}")
    
    async def evening_bonus():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2, fortune_spins=1, event_rolls=event_rolls+1")
                await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
                    users = await c.fetchall()
            sent = 0
            for u in users:
                try:
                    await bot.send_message(u['user_id'],
                        "🌆 Добрый вечер! Вот твои обещанные награды:\n\n"
                        "🎲 +2 обычные крутки\n🎡 +1 вращение колеса\n🎪 +1 ивентовая\n💎 +2 алмаза\n\n"
                        "😊 Хорошего вечера!")
                    sent += 1; await asyncio.sleep(0.05)
                except: pass
            logger.info(f"🌆 Вечер: {sent}/{len(users)}")
        except Exception as e: logger.error(f"Вечер: {e}")
    
    # ==================== ЗАПУСК ====================
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
