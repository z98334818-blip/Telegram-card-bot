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
from aiohttp import web

from config import BOT_TOKEN, ADMIN_IDS, DB_PATH

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Глобальные переменные
db_conn = None
bot = None

async def get_db():
    global db_conn
    if db_conn is None:
        db_conn = await aiosqlite.connect(DB_PATH)
        db_conn.row_factory = aiosqlite.Row
    return db_conn

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    global db_conn
    db_conn = await aiosqlite.connect(DB_PATH)
    db_conn.row_factory = aiosqlite.Row
    
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, rolls INTEGER DEFAULT 2, diamonds INTEGER DEFAULT 0, total_rolls INTEGER DEFAULT 0, fortune_spins INTEGER DEFAULT 1, event_rolls INTEGER DEFAULT 0, event_guarantor INTEGER DEFAULT 0, bonus_roll_received BOOLEAN DEFAULT 0, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1, banned BOOLEAN DEFAULT 0, login_streak INTEGER DEFAULT 0, last_login TEXT, favorite_card INTEGER DEFAULT 0)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT DEFAULT '', file_id TEXT, rarity TEXT DEFAULT 'R', is_L_card BOOLEAN DEFAULT 0, is_event_card BOOLEAN DEFAULT 0)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER, quantity INTEGER DEFAULT 1, is_original BOOLEAN DEFAULT 1, PRIMARY KEY (user_id, card_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (user_id INTEGER, task_id INTEGER, task_type TEXT, task_target INTEGER DEFAULT 1, progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT 0, date TEXT, PRIMARY KEY (user_id, task_id, date))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS weekly_tasks (user_id INTEGER, task_id INTEGER, task_type TEXT, task_target INTEGER DEFAULT 1, progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT 0, reward_claimed BOOLEAN DEFAULT 0, week_start TEXT, PRIMARY KEY (user_id, task_id, week_start))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS achievements (user_id INTEGER, achievement_id TEXT, completed BOOLEAN DEFAULT 0, reward_claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, achievement_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS market (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, card_id INTEGER, price INTEGER, quantity INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS auctions (id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, card_id INTEGER, start_price INTEGER, current_price INTEGER, current_bidder_id INTEGER, end_time TIMESTAMP, status TEXT DEFAULT 'active')""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guilds (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, owner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_members (guild_id INTEGER, user_id INTEGER, role TEXT DEFAULT 'member', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guild_id, user_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_join_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, status TEXT DEFAULT 'pending')""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_war_seasons (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'pending', started_at TIMESTAMP, ended_at TIMESTAMP)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_war_points (guild_id INTEGER, user_id INTEGER, points INTEGER DEFAULT 0, season_id INTEGER, PRIMARY KEY (guild_id, user_id, season_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_war_cards (season_id INTEGER, guild_id INTEGER, user_id INTEGER, card_id INTEGER, PRIMARY KEY (season_id, guild_id, user_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS duels (id INTEGER PRIMARY KEY AUTOINCREMENT, challenger_id INTEGER, opponent_id INTEGER, challenger_card_id INTEGER, opponent_card_id INTEGER, bet_amount INTEGER DEFAULT 1, status TEXT DEFAULT 'pending', winner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, duel_type TEXT DEFAULT 'card')""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS duel_stats (user_id INTEGER PRIMARY KEY, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS friends (user_id INTEGER, friend_id INTEGER, status TEXT DEFAULT 'pending', PRIMARY KEY (user_id, friend_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, type TEXT, value INTEGER, uses_left INTEGER, created_by INTEGER)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS level_rewards (user_id INTEGER, level INTEGER, claimed BOOLEAN DEFAULT 0, PRIMARY KEY (user_id, level))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS card_decks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS deck_cards (deck_id INTEGER, card_id INTEGER, PRIMARY KEY (deck_id, card_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS active_events (id INTEGER PRIMARY KEY AUTOINCREMENT, deck_id INTEGER, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP, status TEXT DEFAULT 'active')""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS daily_login (user_id INTEGER, date TEXT, PRIMARY KEY (user_id, date))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS boosters (user_id INTEGER, type TEXT, multiplier REAL, ends_at TIMESTAMP, PRIMARY KEY (user_id, type))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS rps_rounds (duel_id INTEGER, round_number INTEGER, challenger_choice TEXT, opponent_choice TEXT, winner_id INTEGER, PRIMARY KEY (duel_id, round_number))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, task_type TEXT, task_target INTEGER DEFAULT 1, progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT 0, week_start TEXT)""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_task_contributions (guild_task_id INTEGER, user_id INTEGER, progress INTEGER DEFAULT 0, PRIMARY KEY (guild_task_id, user_id))""")
    await db_conn.execute("""CREATE TABLE IF NOT EXISTS guild_reward_claims (guild_id INTEGER, user_id INTEGER, week_start TEXT, claimed BOOLEAN DEFAULT 0, PRIMARY KEY (guild_id, user_id, week_start))""")
    
    defaults = {'morning_rolls':'2','morning_diamonds':'3','morning_fortune':'1','morning_event':'1','evening_rolls':'2','evening_diamonds':'3','evening_fortune':'1','evening_event':'1','break_R':'1','break_SR':'5','break_SSR':'10','break_L':'20','guarantor_limit':'50','event_rate_L':'2'}
    for key, value in defaults.items():
        await db_conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    try:
        await db_conn.execute("ALTER TABLE duels ADD COLUMN duel_type TEXT DEFAULT 'card'")
    except:
        pass
    
    try:
        await db_conn.execute("ALTER TABLE users ADD COLUMN favorite_card INTEGER DEFAULT 0")
    except:
        pass
    
    await db_conn.commit()
    logger.info("✅ БД готова")

# ==================== НАСТРОЙКИ ====================
async def get_setting(key, default=None):
    db = await get_db()
    async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
        row = await c.fetchone()
        return row[0] if row else default

async def set_setting(key, value):
    db = await get_db()
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
    db = await get_db()
    async with db.execute("SELECT * FROM boosters WHERE user_id=? AND type=? AND ends_at > datetime('now')", (uid, btype)) as c:
        return await c.fetchone()

async def buy_booster(uid, btype, hours, cost):
    u = await get_user(uid)
    if u['diamonds'] < cost:
        return False
    await upd_diamonds(uid, -cost)
    ends = datetime.now() + timedelta(hours=hours)
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO boosters VALUES (?,?,?,?)", (uid, btype, 1.5, ends))
    await db.commit()
    return True

# ==================== ЕЖЕДНЕВНЫЙ ВХОД ====================
async def check_daily_login(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    db = await get_db()
    
    async with db.execute("SELECT * FROM daily_login WHERE user_id=? AND date=?", (uid, today)) as c:
        if await c.fetchone():
            user = await get_user(uid)
            return False, user['login_streak'] if user else 0
    
    await db.execute("INSERT INTO daily_login VALUES (?,?)", (uid, today))
    
    user = await get_user(uid)
    if not user:
        return False, 0
    
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    async with db.execute("SELECT * FROM daily_login WHERE user_id=? AND date=?", (uid, yesterday)) as c:
        was_yesterday = await c.fetchone()
    
    if was_yesterday:
        streak = user['login_streak'] + 1
    else:
        streak = 1
    
    await db.execute("UPDATE users SET login_streak=?, last_login=? WHERE user_id=?", (streak, today, uid))
    await db.commit()
    
    return True, streak

# ==================== СОСТОЯНИЯ FSM ====================
class AddCardStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_rarity = State()
    waiting_for_photo = State()

class EditCardStates(StatesGroup):
    waiting_for_new_value = State()

class DeleteCardStates(StatesGroup):
    waiting_for_confirm = State()

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

class GiveCardStates(StatesGroup):
    waiting_for_user = State()
    waiting_for_card = State()

# ==================== ФУНКЦИИ БД ====================
async def get_user(uid):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as c:
        return await c.fetchone()

async def get_user_by_username(username):
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE username=?", (username,)) as c:
        return await c.fetchone()

async def create_user(uid, name):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO users (user_id,username) VALUES (?,?)", (uid, name))
    await db.commit()

async def add_xp(uid, amount):
    db = await get_db()
    await db.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (amount, uid))
    await db.commit()
    user = await get_user(uid)
    xp, level = user['xp'], user['level']
    xp_needed = level * 100 + 50
    levels_gained = 0
    while xp >= xp_needed:
        xp -= xp_needed
        level += 1
        levels_gained += 1
        xp_needed = level * 100 + 50
    if levels_gained > 0:
        await db.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (xp, level, uid))
        await db.commit()
        for l in range(level - levels_gained + 1, level + 1):
            await db.execute("INSERT OR IGNORE INTO level_rewards VALUES (?,?,0)", (uid, l))
        await db.commit()
    if amount > 0:
        guild = await get_user_guild(uid)
        if guild:
            await update_guild_task_progress(guild['id'], uid, 'guild_xp', amount)
    return levels_gained, level

async def get_level_rewards(uid):
    db = await get_db()
    async with db.execute("SELECT * FROM level_rewards WHERE user_id=? AND claimed=0 ORDER BY level", (uid,)) as c:
        return await c.fetchall()

async def claim_level_reward(uid, level):
    rewards = {2:{'rolls':1},3:{'diamonds':2},4:{'rolls':1,'diamonds':1},5:{'event_rolls':1},6:{'rolls':2},7:{'diamonds':3},8:{'rolls':1,'event_rolls':1},9:{'diamonds':5},10:{'rolls':3,'diamonds':3,'event_rolls':1}}
    if level > 10 and level % 5 == 0:
        rewards[level] = {'rolls':level//2,'diamonds':level,'event_rolls':level//5}
    if level not in rewards:
        return None
    r = rewards[level]
    db = await get_db()
    async with db.execute("SELECT claimed FROM level_rewards WHERE user_id=? AND level=?", (uid, level)) as c:
        row = await c.fetchone()
        if row and row[0]:
            return None
    if 'rolls' in r:
        await upd_rolls(uid, r['rolls'])
    if 'diamonds' in r:
        await upd_diamonds(uid, r['diamonds'])
    if 'event_rolls' in r:
        await upd_event_rolls(uid, r['event_rolls'])
    await db.execute("UPDATE level_rewards SET claimed=1 WHERE user_id=? AND level=?", (uid, level))
    await db.commit()
    return r

async def get_all_cards():
    db = await get_db()
    async with db.execute("SELECT * FROM cards ORDER BY id") as c:
        return await c.fetchall()

async def get_total_cards_count():
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM cards") as c:
        row = await c.fetchone()
        return row[0] if row else 0

async def get_regular_cards():
    db = await get_db()
    async with db.execute("SELECT * FROM cards WHERE is_event_card=0 ORDER BY id") as c:
        cards = await c.fetchall()
        if cards:
            return cards
    async with db.execute("SELECT * FROM cards ORDER BY id") as c:
        return await c.fetchall()

async def get_event_cards():
    cards = await get_event_cards_active()
    if cards:
        return cards
    db = await get_db()
    async with db.execute("SELECT * FROM cards WHERE is_event_card=1 ORDER BY id") as c:
        return await c.fetchall()

async def get_card_by_id(card_id):
    db = await get_db()
    async with db.execute("SELECT * FROM cards WHERE id=?", (card_id,)) as c:
        return await c.fetchone()

async def add_card_to_user(uid, cid, is_original=False):
    db = await get_db()
    async with db.execute("SELECT is_original FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid)) as c:
        ex = await c.fetchone()
    if ex:
        await db.execute("UPDATE user_cards SET quantity=quantity+1 WHERE user_id=? AND card_id=?", (uid, cid))
    else:
        await db.execute("INSERT INTO user_cards VALUES (?,?,1,?)", (uid, cid, is_original))
    await db.commit()

async def upd_rolls(uid, d):
    db = await get_db()
    await db.execute("UPDATE users SET rolls=rolls+?, total_rolls=total_rolls+? WHERE user_id=?", (d, abs(d), uid))
    await db.commit()

async def upd_diamonds(uid, d):
    db = await get_db()
    await db.execute("UPDATE users SET diamonds=diamonds+? WHERE user_id=?", (d, uid))
    await db.commit()

async def upd_fortune_spins(uid, s):
    db = await get_db()
    await db.execute("UPDATE users SET fortune_spins=? WHERE user_id=?", (s, uid))
    await db.commit()

async def upd_event_rolls(uid, d):
    db = await get_db()
    await db.execute("UPDATE users SET event_rolls=event_rolls+? WHERE user_id=?", (d, uid))
    await db.commit()

async def get_user_cards(uid):
    db = await get_db()
    async with db.execute("""SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc JOIN cards c ON uc.card_id=c.id WHERE uc.user_id=? AND uc.quantity>0 ORDER BY c.id""", (uid,)) as c:
        return await c.fetchall()

async def get_user_card(uid, cid):
    db = await get_db()
    async with db.execute("""SELECT c.*, uc.quantity, uc.is_original FROM user_cards uc JOIN cards c ON uc.card_id=c.id WHERE uc.user_id=? AND uc.card_id=?""", (uid, cid)) as c:
        return await c.fetchone()

async def remove_card(uid, cid, qty=1):
    db = await get_db()
    async with db.execute("SELECT quantity, is_original FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid)) as c:
        row = await c.fetchone()
    if not row:
        return False
    cq, io = row[0], row[1]
    if io and cq <= qty:
        return False
    if cq >= qty:
        nq = cq - qty
        if nq <= 0:
            await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
        else:
            await db.execute("UPDATE user_cards SET quantity=? WHERE user_id=? AND card_id=?", (nq, uid, cid))
        await db.commit()
        return True
    return False

async def get_card_count(uid):
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=? AND is_original=1", (uid,)) as c:
        row = await c.fetchone()
        return row[0] if row else 0

async def get_leaders(limit=10):
    db = await get_db()
    async with db.execute("""SELECT u.username, COUNT(uc.card_id) as total FROM users u LEFT JOIN user_cards uc ON u.user_id=uc.user_id WHERE uc.is_original=1 GROUP BY u.user_id HAVING total>0 ORDER BY total DESC LIMIT ?""", (limit,)) as c:
        return await c.fetchall()

async def get_level_leaders(limit=10):
    db = await get_db()
    async with db.execute("SELECT username, level FROM users ORDER BY level DESC LIMIT ?", (limit,)) as c:
        return await c.fetchall()

async def get_duel_leaders(limit=10):
    db = await get_db()
    async with db.execute("""SELECT u.username, ds.wins, ds.losses FROM duel_stats ds JOIN users u ON ds.user_id=u.user_id ORDER BY ds.wins DESC LIMIT ?""", (limit,)) as c:
        return await c.fetchall()

async def get_all_users():
    db = await get_db()
    async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
        return await c.fetchall()

async def update_card_field(card_id, field, value):
    db = await get_db()
    allowed_fields = ['name', 'description', 'rarity', 'file_id', 'is_L_card', 'is_event_card']
    if field not in allowed_fields:
        return False
    await db.execute(f"UPDATE cards SET {field}=? WHERE id=?", (value, card_id))
    await db.commit()
    return True

async def delete_card_completely(card_id):
    db = await get_db()
    await db.execute("DELETE FROM user_cards WHERE card_id=?", (card_id,))
    await db.execute("DELETE FROM market WHERE card_id=?", (card_id,))
    await db.execute("DELETE FROM auctions WHERE card_id=?", (card_id,))
    await db.execute("DELETE FROM deck_cards WHERE card_id=?", (card_id,))
    await db.execute("DELETE FROM guild_war_cards WHERE card_id=?", (card_id,))
    await db.execute("UPDATE users SET favorite_card=0 WHERE favorite_card=?", (card_id,))
    await db.execute("DELETE FROM cards WHERE id=?", (card_id,))
    await db.commit()
    return True

def get_card_info_text(card):
    text = (
        f"📋 Карта #{card['id']}\n\n"
        f"📝 Название: {card['name']}\n"
        f"📄 Описание: {card['description'] or 'Нет'}\n"
        f"⭐ Редкость: {card['rarity']}\n"
        f"🌟 L-карта: {'Да' if card['is_L_card'] else 'Нет'}\n"
        f"🎪 Ивент-карта: {'Да' if card['is_event_card'] else 'Нет'}\n"
        f"🖼 Фото: {'Есть' if card['file_id'] else 'Нет'}\n"
    )
    return text

# ==================== ЛЮБИМАЯ КАРТА ====================
async def set_favorite_card(uid, card_id):
    db = await get_db()
    card = await get_user_card(uid, card_id)
    if not card:
        return False
    await db.execute("UPDATE users SET favorite_card=? WHERE user_id=?", (card_id, uid))
    await db.commit()
    return True

async def remove_favorite_card(uid):
    db = await get_db()
    await db.execute("UPDATE users SET favorite_card=0 WHERE user_id=?", (uid,))
    await db.commit()

async def get_favorite_card(uid):
    user = await get_user(uid)
    if not user or not user['favorite_card']:
        return None
    return await get_user_card(uid, user['favorite_card'])

# ==================== ДУЭЛИ ====================
async def update_duel_stats(uid, is_win):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO duel_stats VALUES (?,0,0)", (uid,))
    if is_win:
        await db.execute("UPDATE duel_stats SET wins=wins+1 WHERE user_id=?", (uid,))
    else:
        await db.execute("UPDATE duel_stats SET losses=losses+1 WHERE user_id=?", (uid,))
    await db.commit()

async def get_duel_stats(uid):
    db = await get_db()
    async with db.execute("SELECT * FROM duel_stats WHERE user_id=?", (uid,)) as c:
        return await c.fetchone()

# ==================== ДУЭЛИ КНБ ====================
RPS_CHOICES = {'камень': '🗿', 'ножницы': '✂️', 'бумага': '📄'}
RPS_WINS = {'камень': 'ножницы', 'ножницы': 'бумага', 'бумага': 'камень'}

def get_rps_winner(choice1, choice2):
    if choice1 == choice2:
        return None
    if RPS_WINS[choice1] == choice2:
        return 1
    return 2

async def create_rps_duel(challenger_id, opponent_id, bet):
    db = await get_db()
    await db.execute("INSERT INTO duels (challenger_id, opponent_id, bet_amount, duel_type) VALUES (?,?,?, 'rps')", (challenger_id, opponent_id, bet))
    await db.commit()
    async with db.execute("SELECT last_insert_rowid()") as c:
        row = await c.fetchone()
        return row[0] if row else None

async def get_rps_duel(duel_id):
    db = await get_db()
    async with db.execute("SELECT * FROM duels WHERE id=? AND duel_type='rps' AND status='pending'", (duel_id,)) as c:
        return await c.fetchone()

async def submit_rps_choice(duel_id, user_id, round_num, choice):
    db = await get_db()
    async with db.execute("SELECT challenger_id, opponent_id FROM duels WHERE id=?", (duel_id,)) as c:
        duel = await c.fetchone()
    if not duel:
        return False
    if user_id == duel['challenger_id']:
        await db.execute("INSERT OR REPLACE INTO rps_rounds (duel_id, round_number, challenger_choice, opponent_choice) VALUES (?,?,?, COALESCE((SELECT opponent_choice FROM rps_rounds WHERE duel_id=? AND round_number=?), NULL))", (duel_id, round_num, choice, duel_id, round_num))
    elif user_id == duel['opponent_id']:
        await db.execute("INSERT OR REPLACE INTO rps_rounds (duel_id, round_number, challenger_choice, opponent_choice) VALUES (?,?,COALESCE((SELECT challenger_choice FROM rps_rounds WHERE duel_id=? AND round_number=?), NULL),?)", (duel_id, round_num, duel_id, round_num, choice))
    else:
        return False
    await db.commit()
    return True

async def get_rps_round(duel_id, round_num):
    db = await get_db()
    async with db.execute("SELECT * FROM rps_rounds WHERE duel_id=? AND round_number=?", (duel_id, round_num)) as c:
        return await c.fetchone()

async def get_rps_rounds(duel_id):
    db = await get_db()
    async with db.execute("SELECT * FROM rps_rounds WHERE duel_id=? ORDER BY round_number", (duel_id,)) as c:
        return await c.fetchall()

async def resolve_rps_duel(duel_id):
    rounds = await get_rps_rounds(duel_id)
    if len(rounds) < 3:
        return None, None
    db = await get_db()
    async with db.execute("SELECT * FROM duels WHERE id=? AND status='pending'", (duel_id,)) as c:
        duel = await c.fetchone()
    if not duel:
        return None, None
    challenger_wins = 0
    opponent_wins = 0
    for round_data in rounds:
        if round_data['challenger_choice'] and round_data['opponent_choice']:
            winner = get_rps_winner(round_data['challenger_choice'], round_data['opponent_choice'])
            if winner == 1:
                challenger_wins += 1
                await db.execute("UPDATE rps_rounds SET winner_id=? WHERE duel_id=? AND round_number=?", (duel['challenger_id'], duel_id, round_data['round_number']))
            elif winner == 2:
                opponent_wins += 1
                await db.execute("UPDATE rps_rounds SET winner_id=? WHERE duel_id=? AND round_number=?", (duel['opponent_id'], duel_id, round_data['round_number']))
    winner_id = None
    if challenger_wins >= 2:
        winner_id = duel['challenger_id']
    elif opponent_wins >= 2:
        winner_id = duel['opponent_id']
    if winner_id:
        loser_id = duel['opponent_id'] if winner_id == duel['challenger_id'] else duel['challenger_id']
        await upd_diamonds(winner_id, duel['bet_amount'])
        await upd_diamonds(loser_id, -duel['bet_amount'])
        await add_xp(winner_id, 20)
        await add_xp(loser_id, 5)
        await update_duel_stats(winner_id, True)
        await update_duel_stats(loser_id, False)
        await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=?", (winner_id, duel_id))
        await db.commit()
        guild = await get_user_guild(winner_id)
        if guild:
            await update_guild_task_progress(guild['id'], winner_id, 'guild_duels')
    return winner_id, rounds

async def get_active_rps_duels_for_user(user_id):
    db = await get_db()
    async with db.execute("""SELECT d.*, c.username as challenger_name, o.username as opponent_name FROM duels d JOIN users c ON d.challenger_id = c.user_id JOIN users o ON d.opponent_id = o.user_id WHERE d.duel_type='rps' AND d.status='pending' AND (d.challenger_id=? OR d.opponent_id=?) ORDER BY d.created_at DESC""", (user_id, user_id)) as c:
        return await c.fetchall()

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

GUILD_TASK_TYPES = [
    {"type":"guild_rolls","desc":"🎲 Сделать 100 круток всей гильдией","target":100},
    {"type":"guild_fortune","desc":"🎡 Колесо фортуны 30 раз","target":30},
    {"type":"guild_break","desc":"🔨 Разбить 50 повторов","target":50},
    {"type":"guild_ssr","desc":"🟣 Выбить 10 SSR","target":10},
    {"type":"guild_duels","desc":"⚔️ Выиграть 20 дуэлей","target":20},
    {"type":"guild_xp","desc":"⭐ Набрать 1000 XP","target":1000},
]

async def has_duplicates(uid):
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=? AND quantity>1", (uid,)) as c:
        row = await c.fetchone()
        return row[0] > 0 if row else False

async def is_event_active():
    return await get_active_event() is not None or len(await get_event_cards()) > 0

async def ensure_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
        row = await c.fetchone()
        if row and row[0] == 0:
            available = [t for t in TASK_TYPES if t['type'] != 'break' or await has_duplicates(uid)]
            if not await is_event_active():
                available = [t for t in available if t['type'] != 'event_roll']
            if len(available) < 2:
                available = [t for t in TASK_TYPES if t['type'] not in ('break','event_roll')]
            selected = random.sample(available, min(2, len(available)))
            for i, t in enumerate(selected):
                await db.execute("INSERT INTO daily_tasks VALUES (?,?,?,?,?,?,?)", (uid, i, t['type'], t['target'], 0, 0, today))
            await db.commit()

async def ensure_weekly_tasks(uid):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, ws)) as c:
        row = await c.fetchone()
        if row and row[0] == 0:
            available = [t for t in WEEKLY_TASK_TYPES if t['type'] != 'weekly_break' or await has_duplicates(uid)]
            if len(available) < 3:
                available = [t for t in WEEKLY_TASK_TYPES if t['type'] in ('weekly_rolls','weekly_fortune')]
            selected = random.sample(available, min(3, len(available)))
            for i, t in enumerate(selected):
                await db.execute("INSERT INTO weekly_tasks VALUES (?,?,?,?,?,?,?,?)", (uid, i, t['type'], t['target'], 0, 0, 0, ws))
            await db.commit()

async def get_daily_tasks(uid):
    await ensure_daily_tasks(uid)
    db = await get_db()
    async with db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=?", (uid, datetime.now().strftime("%Y-%m-%d"))) as c:
        return await c.fetchall()

async def get_weekly_tasks(uid):
    await ensure_weekly_tasks(uid)
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT * FROM weekly_tasks WHERE user_id=? AND week_start=?", (uid, ws)) as c:
        return await c.fetchall()

async def update_task_progress(uid, tt):
    date = datetime.now().strftime("%Y-%m-%d")
    await ensure_daily_tasks(uid)
    db = await get_db()
    await db.execute("UPDATE daily_tasks SET progress=progress+1 WHERE user_id=? AND task_type=? AND date=? AND completed=0 AND progress<task_target", (uid, tt, date))
    await db.execute("UPDATE daily_tasks SET completed=1 WHERE user_id=? AND task_type=? AND date=? AND progress>=task_target", (uid, tt, date))
    await db.commit()

async def update_weekly_progress(uid, tt):
    await ensure_weekly_tasks(uid)
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    await db.execute("UPDATE weekly_tasks SET progress=progress+1 WHERE user_id=? AND task_type=? AND week_start=? AND completed=0 AND progress<task_target", (uid, tt, ws))
    await db.execute("UPDATE weekly_tasks SET completed=1 WHERE user_id=? AND task_type=? AND week_start=? AND progress>=task_target", (uid, tt, ws))
    await db.commit()

async def check_all_tasks_completed(uid):
    db = await get_db()
    async with db.execute("SELECT COUNT(*) as t, SUM(completed) as d FROM daily_tasks WHERE user_id=? AND date=?", (uid, datetime.now().strftime("%Y-%m-%d"))) as c:
        row = await c.fetchone()
        return row and row[0] >= 2 and row[1] == row[0]

async def give_bonus_roll(uid):
    db = await get_db()
    u = await get_user(uid)
    if u and not u['bonus_roll_received']:
        await db.execute("UPDATE users SET bonus_roll_received=1, rolls=rolls+1 WHERE user_id=?", (uid,))
        await db.commit()
        return True
    return False

# ==================== ГИЛЬДЕЙСКИЕ ЗАДАНИЯ ====================
async def ensure_guild_tasks(guild_id):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM guild_tasks WHERE guild_id=? AND week_start=?", (guild_id, ws)) as c:
        row = await c.fetchone()
        if row and row[0] == 0:
            selected = random.sample(GUILD_TASK_TYPES, min(3, len(GUILD_TASK_TYPES)))
            for t in selected:
                await db.execute("INSERT INTO guild_tasks (guild_id, task_type, task_target, week_start) VALUES (?,?,?,?)", (guild_id, t['type'], t['target'], ws))
            await db.commit()

async def get_guild_tasks(guild_id):
    await ensure_guild_tasks(guild_id)
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT * FROM guild_tasks WHERE guild_id=? AND week_start=? ORDER BY id", (guild_id, ws)) as c:
        return await c.fetchall()

async def update_guild_task_progress(guild_id, user_id, task_type, amount=1):
    global bot
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT id, task_target FROM guild_tasks WHERE guild_id=? AND task_type=? AND week_start=? AND completed=0", (guild_id, task_type, ws)) as c:
        task = await c.fetchone()
    if not task:
        return
    await db.execute("UPDATE guild_tasks SET progress = progress + ? WHERE id = ? AND progress < task_target", (amount, task['id']))
    await db.execute("INSERT INTO guild_task_contributions (guild_task_id, user_id, progress) VALUES (?,?,?) ON CONFLICT(guild_task_id, user_id) DO UPDATE SET progress = progress + ?", (task['id'], user_id, amount, amount))
    await db.execute("UPDATE guild_tasks SET completed = 1 WHERE id = ? AND progress >= task_target", (task['id'],))
    await db.commit()
    async with db.execute("SELECT COUNT(*) as total, SUM(completed) as done FROM guild_tasks WHERE guild_id=? AND week_start=?", (guild_id, ws)) as c:
        row = await c.fetchone()
        if row and row['total'] > 0 and row['done'] == row['total']:
            async with db.execute("SELECT user_id FROM guild_members WHERE guild_id=?", (guild_id,)) as c:
                members = await c.fetchall()
            for member in members:
                try:
                    await bot.send_message(member['user_id'], "🎉 Гильдия выполнила все недельные задания!\n\nЗаберите свою награду: /claim_guild_reward\n\n🏆 Награда:\n💎 +7 алмазов\n🎪 +3 ивент-крутки")
                except:
                    pass

async def can_claim_guild_reward(guild_id, user_id):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT COUNT(*) as total, SUM(completed) as done FROM guild_tasks WHERE guild_id=? AND week_start=?", (guild_id, ws)) as c:
        row = await c.fetchone()
        if not row or row['total'] == 0 or row['done'] != row['total']:
            return False, "Задания ещё не выполнены"
    async with db.execute("SELECT claimed FROM guild_reward_claims WHERE guild_id=? AND user_id=? AND week_start=?", (guild_id, user_id, ws)) as c:
        claim = await c.fetchone()
        if claim and claim['claimed']:
            return False, "Вы уже получили награду"
    async with db.execute("SELECT SUM(gtc.progress) as total_contribution FROM guild_task_contributions gtc JOIN guild_tasks gt ON gtc.guild_task_id = gt.id WHERE gt.guild_id = ? AND gt.week_start = ? AND gtc.user_id = ?", (guild_id, ws, user_id)) as c:
        row = await c.fetchone()
        if not row or not row['total_contribution'] or row['total_contribution'] == 0:
            return False, "Вы не внесли вклад в задания"
    return True, "Можно забрать награду!"

async def claim_guild_reward(guild_id, user_id):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    can_claim, status = await can_claim_guild_reward(guild_id, user_id)
    if not can_claim:
        return False, status
    await db.execute("INSERT OR REPLACE INTO guild_reward_claims VALUES (?,?,?,1)", (guild_id, user_id, ws))
    await db.commit()
    await upd_diamonds(user_id, 7)
    await upd_event_rolls(user_id, 3)
    return True, "success"

async def get_guild_claim_stats(guild_id):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT COUNT(*) as total_members, (SELECT COUNT(*) FROM guild_reward_claims WHERE guild_id=? AND week_start=? AND claimed=1) as claimed FROM guild_members WHERE guild_id=?", (guild_id, ws, guild_id)) as c:
        row = await c.fetchone()
        return row['total_members'] if row else 0, row['claimed'] if row else 0

async def get_guild_task_contributions(guild_id):
    today = datetime.now()
    ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    db = await get_db()
    async with db.execute("SELECT u.username, SUM(gtc.progress) as total_progress FROM guild_task_contributions gtc JOIN guild_tasks gt ON gtc.guild_task_id = gt.id JOIN users u ON gtc.user_id = u.user_id WHERE gt.guild_id = ? AND gt.week_start = ? GROUP BY gtc.user_id ORDER BY total_progress DESC LIMIT 10", (guild_id, ws)) as c:
        return await c.fetchall()

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
    if not u:
        return []
    cards = await get_user_cards(uid)
    tc = sum(1 for c in cards if c['is_original'])
    lc = sum(c['quantity'] for c in cards if c['is_L_card'])
    new_ach = []
    db = await get_db()
    for ach in ACHIEVEMENTS:
        completed = (ach['id']=='cards_10' and tc>=10) or (ach['id']=='cards_50' and tc>=50) or (ach['id']=='cards_100' and tc>=100) or (ach['id']=='rolls_100' and u['total_rolls']>=100) or (ach['id']=='l_cards_1' and lc>=1) or (ach['id']=='level_5' and u['level']>=5) or (ach['id']=='level_10' and u['level']>=10)
        if not completed:
            continue
        async with db.execute("SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach['id'])) as c:
            row = await c.fetchone()
            if not row or not row[0]:
                await db.execute("INSERT OR REPLACE INTO achievements VALUES (?,?,1,0)", (uid, ach['id']))
                await db.commit()
                new_ach.append(ach)
    return new_ach

async def claim_achievement_reward(uid, ach_id):
    db = await get_db()
    async with db.execute("SELECT reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach_id)) as c:
        row = await c.fetchone()
        if row and row[0]:
            return None
    ach = next((a for a in ACHIEVEMENTS if a['id']==ach_id), None)
    if not ach:
        return None
    r = ach['reward']
    if 'diamonds' in r:
        await upd_diamonds(uid, r['diamonds'])
    if 'rolls' in r:
        await upd_rolls(uid, r['rolls'])
    if 'event_rolls' in r:
        await upd_event_rolls(uid, r['event_rolls'])
    await db.execute("UPDATE achievements SET reward_claimed=1 WHERE user_id=? AND achievement_id=?", (uid, ach_id))
    await db.commit()
    return r

# ==================== БИРЖА ====================
async def create_market_listing(sid, cid, price, qty=1):
    db = await get_db()
    await db.execute("INSERT INTO market (seller_id,card_id,price,quantity) VALUES (?,?,?,?)", (sid, cid, price, qty))
    await db.commit()

async def get_market_listings(card_id=None, page=0, limit=10):
    db = await get_db()
    if card_id:
        async with db.execute("SELECT m.*, c.name, c.rarity FROM market m JOIN cards c ON m.card_id=c.id WHERE m.card_id=? ORDER BY m.price ASC LIMIT ? OFFSET ?", (card_id, limit, page*limit)) as c:
            return await c.fetchall()
    async with db.execute("SELECT m.*, c.name, c.rarity FROM market m JOIN cards c ON m.card_id=c.id ORDER BY m.created_at DESC LIMIT ? OFFSET ?", (limit, page*limit)) as c:
        return await c.fetchall()

async def buy_listing(lid, bid):
    db = await get_db()
    async with db.execute("SELECT * FROM market WHERE id=?", (lid,)) as c:
        l = await c.fetchone()
    if not l or l['seller_id']==bid:
        return False
    buyer = await get_user(bid)
    if buyer['diamonds'] < l['price']:
        return False
    await upd_diamonds(bid, -l['price'])
    await upd_diamonds(l['seller_id'], l['price'])
    await add_card_to_user(bid, l['card_id'])
    if l['quantity']>1:
        await db.execute("UPDATE market SET quantity=quantity-1 WHERE id=?", (lid,))
    else:
        await db.execute("DELETE FROM market WHERE id=?", (lid,))
    await db.commit()
    return True

# ==================== АУКЦИОНЫ ====================
async def create_auction(sid, cid, sp, dh=24):
    et = datetime.now() + timedelta(hours=dh)
    db = await get_db()
    await db.execute("INSERT INTO auctions (seller_id,card_id,start_price,current_price,end_time) VALUES (?,?,?,?,?)", (sid, cid, sp, sp, et))
    await db.commit()

async def get_active_auctions():
    db = await get_db()
    async with db.execute("SELECT a.*, c.name, c.rarity FROM auctions a JOIN cards c ON a.card_id=c.id WHERE a.status='active' AND a.end_time > datetime('now') ORDER BY a.end_time ASC") as c:
        return await c.fetchall()

async def bid_auction(aid, bid, amt):
    db = await get_db()
    async with db.execute("SELECT * FROM auctions WHERE id=? AND status='active'", (aid,)) as c:
        a = await c.fetchone()
    if not a or amt <= a['current_price'] or (await get_user(bid))['diamonds'] < amt:
        return False
    await db.execute("UPDATE auctions SET current_price=?, current_bidder_id=? WHERE id=?", (amt, bid, aid))
    await db.commit()
    return True

async def finish_auctions():
    db = await get_db()
    async with db.execute("SELECT * FROM auctions WHERE status='active' AND end_time <= datetime('now')") as c:
        for a in await c.fetchall():
            if a['current_bidder_id']:
                await upd_diamonds(a['seller_id'], a['current_price'])
                await add_card_to_user(a['current_bidder_id'], a['card_id'])
                await db.execute("UPDATE auctions SET status='sold' WHERE id=?", (a['id'],))
            else:
                await db.execute("UPDATE auctions SET status='expired' WHERE id=?", (a['id'],))
    await db.commit()

# ==================== ДРУЗЬЯ ====================
async def send_friend_request(uid, fid):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO friends VALUES (?,?,'pending')", (uid, fid))
    await db.commit()

async def accept_friend(uid, fid):
    db = await get_db()
    await db.execute("UPDATE friends SET status='accepted' WHERE user_id=? AND friend_id=?", (fid, uid))
    await db.execute("INSERT OR IGNORE INTO friends VALUES (?,?,'accepted')", (uid, fid))
    await db.commit()

async def get_friends(uid):
    db = await get_db()
    async with db.execute("SELECT u.user_id, u.username FROM friends f JOIN users u ON f.friend_id=u.user_id WHERE f.user_id=? AND f.status='accepted'", (uid,)) as c:
        sent = await c.fetchall()
    async with db.execute("SELECT u.user_id, u.username FROM friends f JOIN users u ON f.user_id=u.user_id WHERE f.friend_id=? AND f.status='accepted'", (uid,)) as c:
        received = await c.fetchall()
    friends = []
    seen = set()
    for f in sent + received:
        if f['user_id']!=uid and f['user_id'] not in seen:
            friends.append(f)
            seen.add(f['user_id'])
    return friends

# ==================== КОЛОДЫ И ИВЕНТЫ ====================
async def create_deck(name):
    db = await get_db()
    await db.execute("INSERT INTO card_decks (name) VALUES (?)", (name,))
    await db.commit()
    async with db.execute("SELECT last_insert_rowid()") as c:
        row = await c.fetchone()
        return row[0] if row else None

async def get_all_decks():
    db = await get_db()
    async with db.execute("SELECT * FROM card_decks ORDER BY id") as c:
        return await c.fetchall()

async def add_card_to_deck(did, cid):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO deck_cards VALUES (?,?)", (did, cid))
    await db.commit()

async def get_deck_cards(did):
    db = await get_db()
    async with db.execute("SELECT c.* FROM cards c JOIN deck_cards dc ON c.id=dc.card_id WHERE dc.deck_id=?", (did,)) as c:
        return await c.fetchall()

async def start_event(did):
    db = await get_db()
    await db.execute("UPDATE active_events SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status='active'")
    await db.execute("INSERT INTO active_events (deck_id, status) VALUES (?, 'active')", (did,))
    await db.commit()

async def end_current_event():
    db = await get_db()
    await db.execute("UPDATE active_events SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status='active'")
    await db.commit()

async def get_active_event():
    db = await get_db()
    async with db.execute("SELECT * FROM active_events WHERE status='active'") as c:
        return await c.fetchone()

async def get_event_cards_active():
    event = await get_active_event()
    return await get_deck_cards(event['deck_id']) if event else []

# ==================== ГИЛЬДЕЙСКИЕ ВОЙНЫ ====================
async def get_active_war_season():
    db = await get_db()
    async with db.execute("SELECT * FROM guild_war_seasons WHERE status IN ('active','selection')") as c:
        return await c.fetchone()

async def start_war_season():
    await end_current_war()
    db = await get_db()
    await db.execute("INSERT INTO guild_war_seasons (status, started_at) VALUES ('selection', CURRENT_TIMESTAMP)")
    await db.commit()
    async with db.execute("SELECT last_insert_rowid()") as c:
        row = await c.fetchone()
        return row[0] if row else None

async def start_war_battles(season_id):
    db = await get_db()
    await db.execute("UPDATE guild_war_seasons SET status='active' WHERE id=?", (season_id,))
    await db.commit()

async def end_current_war():
    db = await get_db()
    await db.execute("UPDATE guild_war_seasons SET status='ended', ended_at=CURRENT_TIMESTAMP WHERE status IN ('active','selection')")
    await db.commit()

async def add_war_points(guild_id, user_id, season_id, points):
    db = await get_db()
    await db.execute("INSERT INTO guild_war_points VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,season_id) DO UPDATE SET points=points+?", (guild_id, user_id, points, season_id, points))
    await db.commit()

async def set_war_card(season_id, guild_id, user_id, card_id):
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO guild_war_cards VALUES (?,?,?,?)", (season_id, guild_id, user_id, card_id))
    await db.commit()

async def get_guild_war_ranking(season_id):
    db = await get_db()
    async with db.execute("SELECT g.id, g.name, SUM(gwp.points) as total FROM guilds g JOIN guild_war_points gwp ON g.id=gwp.guild_id WHERE gwp.season_id=? GROUP BY g.id ORDER BY total DESC", (season_id,)) as c:
        return await c.fetchall()

async def get_user_guild(uid):
    db = await get_db()
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

# ==================== ВЫДАЧИ ====================
async def morning_bonus():
    global bot
    try:
        mr = await get_setting_int('morning_rolls', 2)
        md = await get_setting_int('morning_diamonds', 3)
        mf = await get_setting_int('morning_fortune', 1)
        me = await get_setting_int('morning_event', 1)
        db = await get_db()
        await db.execute(f"UPDATE users SET rolls=rolls+{mr}, diamonds=diamonds+{md}, fortune_spins={mf}, event_rolls=event_rolls+{me}, bonus_roll_received=0")
        await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),))
        await db.commit()
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            users = await c.fetchall()
        for i, u in enumerate(users):
            try:
                await bot.send_message(u['user_id'], f"🌅 Доброе утро!\n\n🎲+{mr} 🎡+{mf} 🎪+{me} 💎+{md}")
                if i % 10 == 0:
                    await asyncio.sleep(0.1)
            except:
                pass
        try:
            shutil.copy2(DB_PATH, DB_PATH + ".backup")
        except:
            pass
        logger.info("☀️ Утро")
    except Exception as e:
        logger.error(f"Утро: {e}")

async def evening_bonus():
    global bot
    try:
        er = await get_setting_int('evening_rolls', 2)
        ed = await get_setting_int('evening_diamonds', 3)
        ef = await get_setting_int('evening_fortune', 1)
        ee = await get_setting_int('evening_event', 1)
        db = await get_db()
        await db.execute(f"UPDATE users SET rolls=rolls+{er}, diamonds=diamonds+{ed}, fortune_spins={ef}, event_rolls=event_rolls+{ee}")
        await db.commit()
        async with db.execute("SELECT user_id FROM users WHERE banned=0") as c:
            users = await c.fetchall()
        for i, u in enumerate(users):
            try:
                await bot.send_message(u['user_id'], f"🌆 Добрый вечер!\n\n🎲+{er} 🎡+{ef} 🎪+{ee} 💎+{ed}")
                if i % 10 == 0:
                    await asyncio.sleep(0.1)
            except:
                pass
        logger.info("🌆 Вечер")
    except Exception as e:
        logger.error(f"Вечер: {e}")

async def resolve_user(username):
    username = username.replace("@","")
    if username.isdigit():
        return int(username)
    user = await get_user_by_username(username)
    return user['user_id'] if user else None

# ==================== БОТ ====================
async def main():
    global db_conn, bot
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    db = await get_db()
    await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
    await db.commit()
    
    # ==================== КОМАНДЫ ====================
    @dp.message(CommandStart())
    async def start(msg: types.Message):
        user = await get_user(msg.from_user.id)
        if user and user['banned']:
            await msg.answer("⛔ Вы заблокированы.")
            return
        await create_user(msg.from_user.id, msg.from_user.username or "Аноним")
        login_bonus, streak = await check_daily_login(msg.from_user.id)
        text = "✨ Приветствую тебя путник! ✨\n\n🎲 Выдачи 7:00 и 17:00 МСК\n🌟 L-карты в ивентах\n💎 R=1 SR=5 SSR=10 L=20\n⚔️ /duel @user ID [ставка]\n✂️ /rps_duel @user [ставка]"
        if login_bonus:
            bonus = min(streak, 7)
            await upd_rolls(msg.from_user.id, bonus)
            text += f"\n\n🔥 Серия: {streak} дн!\n🎁 +{bonus}🎲 за вход!"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg: types.Message):
        await msg.answer("🎮 Меню:", reply_markup=permanent_keyboard())
    
    @dp.message(Command("duel"))
    async def dcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) < 3:
                await msg.answer("❌ /duel @user ID [ставка]")
                return
            oun, cid = p[1].replace("@",""), int(p[2])
            bet = int(p[3]) if len(p) > 3 else 1
            if bet < 1:
                await msg.answer("❌ Ставка > 0!")
                return
            if not await get_user_card(msg.from_user.id, cid):
                await msg.answer(f"❌ Нет карты #{cid}!")
                return
            u = await get_user(msg.from_user.id)
            if u['diamonds'] < bet:
                await msg.answer(f"❌ Нужно {bet}💎!")
                return
            db = await get_db()
            async with db.execute("SELECT user_id FROM users WHERE username=?", (oun,)) as c:
                row = await c.fetchone()
            if not row:
                await msg.answer(f"❌ @{oun} не найден!")
                return
            oid = row[0]
            if oid == msg.from_user.id:
                await msg.answer("❌ Нельзя себя!")
                return
            if (await get_user(oid))['diamonds'] < bet:
                await msg.answer(f"❌ У @{oun} нет {bet}💎!")
                return
            await db.execute("INSERT INTO duels (challenger_id, opponent_id, challenger_card_id, bet_amount, duel_type) VALUES (?,?,?,?, 'card')", (msg.from_user.id, oid, cid, bet))
            await db.commit()
            async with db.execute("SELECT last_insert_rowid()") as c:
                row = await c.fetchone()
                duel_id = row[0] if row else None
            if not duel_id:
                await msg.answer("❌ Ошибка создания дуэли!")
                return
            card = await get_card_by_id(cid)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"aduel_{duel_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dduel_{duel_id}")],
            ])
            await bot.send_message(oid, f"⚔️ ВЫЗОВ!\nОт: @{msg.from_user.username}\n{rarity_emoji(card['rarity'])} {card['name']} (#{cid})\nСтавка: {bet}💎\nВыбери карту: /pick ID", reply_markup=kb)
            await msg.answer(f"✅ Вызов @{oun}!\nСтавка: {bet}💎")
        except Exception as e:
            logger.error(f"Ошибка в /duel: {e}")
            await msg.answer("❌ /duel @user ID [ставка]")
    
    @dp.message(Command("rps_duel"))
    async def rps_duel_cmd(msg: types.Message):
        try:
            parts = msg.text.split()
            if len(parts) < 2:
                await msg.answer("❌ Использование: /rps_duel @username [ставка]")
                return
            opponent_name = parts[1].replace("@", "")
            bet = int(parts[2]) if len(parts) > 2 else 1
            if bet < 1:
                await msg.answer("❌ Ставка должна быть больше 0!")
                return
            db = await get_db()
            async with db.execute("SELECT user_id FROM users WHERE username=?", (opponent_name,)) as c:
                row = await c.fetchone()
            if not row:
                await msg.answer(f"❌ Пользователь @{opponent_name} не найден!")
                return
            opponent_id = row[0]
            if opponent_id == msg.from_user.id:
                await msg.answer("❌ Нельзя играть против себя!")
                return
            user = await get_user(msg.from_user.id)
            opp_user = await get_user(opponent_id)
            if not user or not opp_user:
                await msg.answer("❌ Ошибка получения данных!")
                return
            if user['diamonds'] < bet:
                await msg.answer(f"❌ У вас недостаточно алмазов! Нужно {bet}💎")
                return
            if opp_user['diamonds'] < bet:
                await msg.answer(f"❌ У @{opponent_name} недостаточно алмазов!")
                return
            duel_id = await create_rps_duel(msg.from_user.id, opponent_id, bet)
            if not duel_id:
                await msg.answer("❌ Ошибка создания дуэли!")
                return
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✂️ Принять вызов", callback_data=f"accept_rps_{duel_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_rps_{duel_id}")],
            ])
            await bot.send_message(opponent_id, f"✂️ ВЫЗОВ НА КАМЕНЬ-НОЖНИЦЫ-БУМАГУ!\n\nОт: @{msg.from_user.username}\nСтавка: {bet}💎\nФормат: лучший из 3 раундов\n\nПримешь вызов?", reply_markup=kb)
            await msg.answer(f"✅ Вызов отправлен @{opponent_name}!\nСтавка: {bet}💎\nЖдём ответа...")
        except Exception as e:
            logger.error(f"Ошибка в /rps_duel: {e}")
            await msg.answer("❌ Ошибка! Проверьте формат: /rps_duel @username [ставка]")
    
    @dp.message(Command("rps"))
    async def rps_choice_cmd(msg: types.Message):
        try:
            choice = msg.text.replace("/rps", "").strip().lower()
            if choice not in ['камень', 'ножницы', 'бумага']:
                await msg.answer("❌ Используй: /rps камень\nДоступно: камень, ножницы, бумага")
                return
            active_duels = await get_active_rps_duels_for_user(msg.from_user.id)
            if not active_duels:
                await msg.answer("❌ У вас нет активных дуэлей КНБ!")
                return
            if len(active_duels) == 1:
                duel = active_duels[0]
            else:
                text = "Выберите дуэль:\n\n"
                for i, d in enumerate(active_duels, 1):
                    vs = d['opponent_name'] if d['challenger_id'] == msg.from_user.id else d['challenger_name']
                    text += f"{i}. Против @{vs} | Ставка: {d['bet_amount']}💎\n"
                text += "\nИспользуй: /rps [номер] [выбор]"
                await msg.answer(text)
                return
            await process_rps_round(msg, duel, choice)
        except Exception as e:
            logger.error(f"Ошибка в /rps: {e}")
            await msg.answer("❌ Ошибка!")
    
    async def process_rps_round(msg, duel, choice):
        try:
            rounds = await get_rps_rounds(duel['id'])
            round_num = len(rounds) + 1
            if round_num > 3:
                await msg.answer("❌ Все раунды уже сыграны!")
                return
            success = await submit_rps_choice(duel['id'], msg.from_user.id, round_num, choice)
            if not success:
                await msg.answer("❌ Ошибка сохранения выбора!")
                return
            choice_emoji = RPS_CHOICES.get(choice, '❓')
            await msg.answer(f"✅ Выбор сделан: {choice_emoji} {choice.capitalize()}\nОжидаем оппонента...")
            round_data = await get_rps_round(duel['id'], round_num)
            opponent_id = duel['opponent_id'] if msg.from_user.id == duel['challenger_id'] else duel['challenger_id']
            opponent_choice = None
            if round_data:
                if msg.from_user.id == duel['challenger_id']:
                    opponent_choice = round_data['opponent_choice']
                else:
                    opponent_choice = round_data['challenger_choice']
            if opponent_choice:
                await show_rps_round_result(duel, round_num)
                winner_id, _ = await resolve_rps_duel(duel['id'])
                if winner_id:
                    await finish_rps_duel(duel['id'])
            else:
                try:
                    await bot.send_message(opponent_id, f"🎯 Ваш оппонент сделал выбор в раунде {round_num}!\nИспользуй /rps [камень|ножницы|бумага]")
                except:
                    pass
        except Exception as e:
            logger.error(f"Ошибка в process_rps_round: {e}")
            await msg.answer("❌ Произошла ошибка!")
    
    async def show_rps_round_result(duel, round_num):
        round_data = await get_rps_round(duel['id'], round_num)
        if not round_data:
            return
        c_choice = round_data['challenger_choice']
        o_choice = round_data['opponent_choice']
        c_emoji = RPS_CHOICES.get(c_choice, '❓')
        o_emoji = RPS_CHOICES.get(o_choice, '❓')
        result_text = f"🎯 Раунд {round_num}:\n\nВызывающий: {c_emoji}\nОппонент: {o_emoji}\n\n"
        if round_data['winner_id']:
            winner = await get_user(round_data['winner_id'])
            result_text += f"Победитель: @{winner['username']}!"
        else:
            result_text += "Ничья! 🤝"
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try:
                all_rounds = await get_rps_rounds(duel['id'])
                c_wins = sum(1 for r in all_rounds if r['winner_id'] == duel['challenger_id'])
                o_wins = sum(1 for r in all_rounds if r['winner_id'] == duel['opponent_id'])
                score = f"\nСчёт: {c_wins}-{o_wins}"
                await bot.send_message(uid, result_text + score)
            except Exception as e:
                logger.error(f"Не удалось отправить результат раунда пользователю {uid}: {e}")
    
    async def finish_rps_duel(duel_id):
        db = await get_db()
        async with db.execute("SELECT * FROM duels WHERE id=?", (duel_id,)) as c:
            duel = await c.fetchone()
        if not duel or duel['winner_id'] is None:
            return
        winner = await get_user(duel['winner_id'])
        rounds = await get_rps_rounds(duel_id)
        c_wins = sum(1 for r in rounds if r['winner_id'] == duel['challenger_id'])
        o_wins = sum(1 for r in rounds if r['winner_id'] == duel['opponent_id'])
        result_text = f"🏆 ДУЭЛЬ ЗАВЕРШЕНА!\n\nПобедитель: @{winner['username']}\nСчёт: {c_wins}-{o_wins}\nПриз: {duel['bet_amount']}💎\n\nИстория раундов:\n"
        for r in rounds:
            c_choice = r['challenger_choice'] or '❓'
            o_choice = r['opponent_choice'] or '❓'
            c_emoji = RPS_CHOICES.get(c_choice, '❓')
            o_emoji = RPS_CHOICES.get(o_choice, '❓')
            round_winner = "🤝" if not r['winner_id'] else "✅" if r['winner_id'] == duel['challenger_id'] else "❌"
            result_text += f"Раунд {r['round_number']}: {c_emoji} vs {o_emoji} {round_winner}\n"
        for uid in [duel['challenger_id'], duel['opponent_id']]:
            try:
                await bot.send_message(uid, result_text)
            except Exception as e:
                logger.error(f"Не удалось отправить результат дуэли пользователю {uid}: {e}")
    
    @dp.message(Command("pick"))
    async def pcmd(msg: types.Message):
        try:
            cid = int(msg.text.replace("/pick","").strip())
            if not await get_user_card(msg.from_user.id, cid):
                await msg.answer(f"❌ Нет #{cid}!")
                return
            db = await get_db()
            async with db.execute("SELECT * FROM duels WHERE opponent_id=? AND status='pending'", (msg.from_user.id,)) as c:
                duel = await c.fetchone()
            if not duel:
                await msg.answer("❌ Нет дуэли!")
                return
            await db.execute("UPDATE duels SET opponent_card_id=? WHERE id=?", (cid, duel['id']))
            await db.commit()
            async with db.execute("SELECT * FROM duels WHERE id=?", (duel['id'],)) as c:
                updated = await c.fetchone()
            if updated and updated['challenger_card_id'] and updated['opponent_card_id']:
                await resolve_duel(updated)
            else:
                await msg.answer(f"✅ Карта #{cid} выбрана!")
        except:
            await msg.answer("❌ /pick ID")
    
    @dp.message(Command("find"))
    async def fc(msg: types.Message):
        try:
            cid = int(msg.text.replace("/find","").strip())
            listings = await get_market_listings(card_id=cid)
            if not listings:
                await msg.answer(f"📋 Нет #{cid}")
                return
            text = f"📋 #{cid}:\n\n"
            buttons = []
            for l in listings[:10]:
                text += f"#{l['id']} | {l['price']}💎\n"
                buttons.append([InlineKeyboardButton(text=f"{l['price']}💎", callback_data=f"mbuy_{l['id']}")])
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except:
            await msg.answer("❌ /find НОМЕР")
    
    @dp.message(Command("sell"))
    async def scmd(msg: types.Message):
        try:
            p = msg.text.split()
            cid, pr = int(p[1]), int(p[2])
            if not await get_user_card(msg.from_user.id, cid):
                await msg.answer(f"❌ Нет #{cid}!")
                return
            await remove_card(msg.from_user.id, cid, 1)
            await create_market_listing(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ #{cid} за {pr}💎!")
        except:
            await msg.answer("❌ /sell НОМЕР ЦЕНА")
    
    @dp.message(Command("auction"))
    async def acmd(msg: types.Message):
        try:
            p = msg.text.split()
            cid, pr = int(p[1]), int(p[2])
            await remove_card(msg.from_user.id, cid, 1)
            await create_auction(msg.from_user.id, cid, pr)
            await msg.answer(f"✅ Аукцион #{cid} от {pr}💎")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("trade"))
    async def tcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) != 4:
                await msg.answer("❌")
                return
            tun, fc, tc = p[1].replace("@",""), int(p[2]), int(p[3])
            if not await get_user_card(msg.from_user.id, fc):
                await msg.answer(f"❌ Нет #{fc}!")
                return
            db = await get_db()
            async with db.execute("SELECT user_id FROM users WHERE username=?", (tun,)) as c:
                row = await c.fetchone()
            if not row:
                await msg.answer(f"❌ @{tun}!")
                return
            if not await get_user_card(row[0], tc):
                await msg.answer(f"❌ У @{tun} нет #{tc}!")
                return
            fcard, tcard = await get_card_by_id(fc), await get_card_by_id(tc)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"tac_{msg.from_user.id}_{fc}_{tc}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"tdc_{msg.from_user.id}")],
            ])
            await bot.send_message(row[0], f"🔄 ОБМЕН!\nОт: @{msg.from_user.username}\n{rarity_emoji(fcard['rarity'])} {fcard['name']} (#{fc})\n→ {rarity_emoji(tcard['rarity'])} {tcard['name']} (#{tc})", reply_markup=kb)
            await msg.answer(f"✅ @{tun}!")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("friend"))
    async def fcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) < 3:
                return
            action, un = p[1], p[2].replace("@","")
            db = await get_db()
            async with db.execute("SELECT user_id FROM users WHERE username=?", (un,)) as c:
                row = await c.fetchone()
            if not row or row[0] == msg.from_user.id:
                return
            fid = row[0]
            if action == "add":
                async with db.execute("SELECT * FROM friends WHERE ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)) AND status='accepted'", (msg.from_user.id, fid, fid, msg.from_user.id)) as c:
                    if await c.fetchone():
                        await msg.answer("❌ Уже друзья!")
                        return
                await send_friend_request(msg.from_user.id, fid)
                await msg.answer(f"✅ Заявка @{un}!")
                try:
                    await bot.send_message(fid, f"👥 @{msg.from_user.username} хочет в друзья!\n/friend accept @{msg.from_user.username}")
                except:
                    pass
            elif action == "accept":
                await accept_friend(msg.from_user.id, fid)
                await msg.answer(f"✅ @{un} друг!")
            elif action == "remove":
                await db.execute("DELETE FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)", (msg.from_user.id, fid, fid, msg.from_user.id))
                await db.commit()
                await msg.answer("✅ Удалён")
        except:
            pass
    
    @dp.message(Command("guild"))
    async def gcmd(msg: types.Message):
        try:
            p = msg.text.split()
            if len(p) < 2:
                return
            action = p[1]
            if action == "create":
                name = " ".join(p[2:])
                u = await get_user(msg.from_user.id)
                if u['diamonds'] < 10:
                    await msg.answer("❌ 10💎!")
                    return
                await upd_diamonds(msg.from_user.id, -10)
                db = await get_db()
                await db.execute("INSERT INTO guilds (name, owner_id) VALUES (?,?)", (name, msg.from_user.id))
                await db.commit()
                async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c:
                    row = await c.fetchone()
                    if row:
                        gid = row[0]
                        await db.execute("INSERT INTO guild_members VALUES (?,?,'owner',CURRENT_TIMESTAMP)", (gid, msg.from_user.id))
                        await db.commit()
                await msg.answer(f"✅ '{name}' создана!")
            elif action == "join":
                name = " ".join(p[2:])
                async with db.execute("SELECT id FROM guilds WHERE name=?", (name,)) as c:
                    row = await c.fetchone()
                if not row:
                    return
                await db.execute("INSERT OR IGNORE INTO guild_join_requests VALUES (?,?,?,'pending')", (row[0], msg.from_user.id))
                await db.commit()
                async with db.execute("SELECT owner_id FROM guilds WHERE id=?", (row[0],)) as c:
                    row2 = await c.fetchone()
                    if row2:
                        await msg.answer("✅ Заявка отправлена!")
                        try:
                            await bot.send_message(row2[0], f"📩 @{msg.from_user.username} хочет в '{name}'\n/guild accept @{msg.from_user.username}")
                        except:
                            pass
            elif action == "list":
                async with db.execute("SELECT g.name, COUNT(gm.user_id) as cnt FROM guilds g LEFT JOIN guild_members gm ON g.id=gm.guild_id GROUP BY g.id") as c:
                    guilds = await c.fetchall()
                if guilds:
                    await msg.answer("📋 Гильдии:\n\n" + "\n".join([f"• {g['name']} ({g['cnt']}👥)" for g in guilds]))
                else:
                    await msg.answer("Нет")
        except:
            pass
    
    @dp.message(Command("war_pick"))
    async def war_pick(msg: types.Message):
        season = await get_active_war_season()
        if not season or season['status'] != 'selection':
            return
        guild = await get_user_guild(msg.from_user.id)
        if not guild:
            return
        try:
            cid = int(msg.text.replace("/war_pick","").strip())
            if not await get_user_card(msg.from_user.id, cid):
                await msg.answer(f"❌ Нет #{cid}!")
                return
            await set_war_card(season['id'], guild['id'], msg.from_user.id, cid)
            await msg.answer(f"✅ #{cid} выбрана!")
        except:
            pass
    
    @dp.message(Command("claim_weekly"))
    async def claim_weekly(msg: types.Message):
        tasks = await get_weekly_tasks(msg.from_user.id)
        if tasks and all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            today = datetime.now()
            ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
            db = await get_db()
            await db.execute("UPDATE weekly_tasks SET reward_claimed=1 WHERE user_id=? AND week_start=?", (msg.from_user.id, ws))
            await db.commit()
            await upd_diamonds(msg.from_user.id, 3)
            await upd_rolls(msg.from_user.id, 2)
            await upd_event_rolls(msg.from_user.id, 1)
            await msg.answer("✅ +3💎 +2🎲 +1🎪")
        else:
            await msg.answer("❌ Не все задания выполнены или награда получена")
    
    @dp.message(Command("claim_guild_reward"))
    async def claim_guild_reward_cmd(msg: types.Message):
        guild = await get_user_guild(msg.from_user.id)
        if not guild:
            await msg.answer("❌ Вы не в гильдии!")
            return
        can_claim, message = await can_claim_guild_reward(guild['id'], msg.from_user.id)
        if not can_claim:
            await msg.answer(f"❌ {message}")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать награду", callback_data=f"confirm_guild_reward_{guild['id']}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_guild_reward")],
        ])
        await msg.answer("🎉 Гильдия выполнила все задания!\n\n🏆 Ваша награда:\n💎 +7 алмазов\n🎪 +3 ивент-крутки\n\nЗабрать?", reply_markup=kb)
    
    @dp.message(Command("levels"))
    async def levels_cmd(msg: types.Message):
        u = await get_user(msg.from_user.id)
        rewards = await get_level_rewards(msg.from_user.id)
        xp_need = u['level'] * 100 + 50
        progress = int(u['xp'] / xp_need * 10) if xp_need > 0 else 10
        bar = "▓" * progress + "░" * (10 - progress)
        text = (
            f"⬆ Ваш уровень: {u['level']}\n"
            f"📊 XP: {u['xp']}/{xp_need}\n"
            f"[{bar}] {int(u['xp']/xp_need*100) if xp_need > 0 else 100}%\n\n"
            "📈 Как получить XP:\n"
            "🎲 Крутка: 10 XP (15 с бустером)\n"
            "🎪 Ивент-крутка: 20 XP (30 с бустером)\n"
            "🎡 Колесо фортуны (карта): 10 XP (15 с бустером)\n"
            "🔨 Разбитие карты: 2 XP за каждую\n"
            "⚔️ Победа в дуэли: 15 XP\n"
            "⚔️ Поражение в дуэли: 5 XP\n"
            "✂️ Победа в КНБ: 20 XP\n"
            "✂️ Поражение в КНБ: 5 XP\n\n"
            "🎁 Награды за уровни:\n"
            "Ур.2: 🎲 +1 крутка\n"
            "Ур.3: 💎 +2 алмаза\n"
            "Ур.4: 🎲 +1 крутка, 💎 +1 алмаз\n"
            "Ур.5: 🎪 +1 ивент-крутка\n"
            "Ур.6: 🎲 +2 крутки\n"
            "Ур.7: 💎 +3 алмаза\n"
            "Ур.8: 🎲 +1 крутка, 🎪 +1 ивент-крутка\n"
            "Ур.9: 💎 +5 алмазов\n"
            "Ур.10: 🎲 +3 крутки, 💎 +3 алмаза, 🎪 +1 ивент-крутка\n"
            "Каждые 5 уровней после 10: крутки (ур/2), алмазы (ур), ивент-крутки (ур/5)\n\n"
        )
        if rewards:
            text += f"🎁 Доступно наград: {len(rewards)}\n"
            text += "Нажмите кнопку ⬆ Уровни чтобы забрать!"
        await msg.answer(text)
    
    @dp.message(Command("fav"))
    async def fav_cmd(msg: types.Message):
        try:
            cid = int(msg.text.replace("/fav","").strip())
            if await set_favorite_card(msg.from_user.id, cid):
                card = await get_card_by_id(cid)
                await msg.answer(f"❤️ {rarity_emoji(card['rarity'])} {card['name']} теперь любимая!")
            else:
                await msg.answer(f"❌ У вас нет карты #{cid}!")
        except:
            await msg.answer("❌ /fav ID_карты")
    
    # Админ-команды
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Карта", callback_data="admin_add")],
            [InlineKeyboardButton(text="✏️ Изменить карту", callback_data="admin_edit_card")],
            [InlineKeyboardButton(text="🗑 Удалить карту", callback_data="admin_delete_card")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_take_menu")],
            [InlineKeyboardButton(text="🃏 Выдать карту", callback_data="admin_give_card_menu")],
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
    async def ac(msg: types.Message, state: FSMContext):
        await state.update_data(is_event=False)
        await msg.answer("📝 Шаг 1/4\nВведи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(Command("cards"))
    async def cc(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        cards = await get_all_cards()
        if not cards:
            await msg.answer("📋 Нет")
            return
        text = "📋 Карты:\n\n"
        for c in cards:
            text += f"#{c['id']} {rarity_emoji(c['rarity'])} {c['name']}\n"
        for i in range(0, len(text), 4000):
            await msg.answer(text[i:i+4000])
    
    @dp.message(Command("delcard"))
    async def dc(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            cid = int(msg.text.replace("/delcard","").strip())
            card = await get_card_by_id(cid)
            if not card:
                await msg.answer(f"❌ Карта #{cid} не найдена!")
                return
            text = f"⚠️ Вы уверены, что хотите удалить карту?\n\n"
            text += f"📋 #{card['id']} {rarity_emoji(card['rarity'])} {card['name']}\n"
            text += f"⭐ {card['rarity']}"
            if card['is_L_card']:
                text += " | 🌟 L-карта"
            if card['is_event_card']:
                text += " | 🎪 Ивент"
            text += f"\n\n❗ Это действие нельзя отменить!"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{cid}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")],
            ])
            await msg.answer(text, reply_markup=kb)
        except:
            await msg.answer("❌ /delcard ID_карты")
    
    @dp.message(Command("editcard"))
    async def edit_card_cmd(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            cid = int(msg.text.replace("/editcard","").strip())
            card = await get_card_by_id(cid)
            if not card:
                await msg.answer(f"❌ Карта #{cid} не найдена!")
                return
            text = get_card_info_text(card)
            text += "\nЧто хотите изменить?"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_name_{cid}")],
                [InlineKeyboardButton(text="📄 Описание", callback_data=f"edit_desc_{cid}")],
                [InlineKeyboardButton(text="⭐ Редкость", callback_data=f"edit_rarity_{cid}")],
                [InlineKeyboardButton(text="🌟 L-карта", callback_data=f"edit_isl_{cid}")],
                [InlineKeyboardButton(text="🎪 Ивент", callback_data=f"edit_event_{cid}")],
                [InlineKeyboardButton(text="🖼 Фото", callback_data=f"edit_photo_{cid}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="edit_cancel")],
            ])
            await msg.answer(text, reply_markup=kb)
        except:
            await msg.answer("❌ /editcard ID_карты")
    
    @dp.message(Command("givediamonds"))
    async def gd_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            await upd_diamonds(uid, int(p[2]))
            await msg.answer(f"✅ +{p[2]}💎")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("giverolls"))
    async def gr_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            await upd_rolls(uid, int(p[2]))
            await msg.answer(f"✅ +{p[2]}🎲")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("giveevent"))
    async def ge_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            await upd_event_rolls(uid, int(p[2]))
            await msg.answer(f"✅ +{p[2]}🎪")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("givecard"))
    async def givecard_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            cid = int(p[2])
            card = await get_card_by_id(cid)
            if not card:
                await msg.answer(f"❌ Карта #{cid} не найдена!")
                return
            await add_card_to_user(uid, cid, is_original=True)
            user = await get_user(uid)
            await msg.answer(f"✅ Карта #{cid} {rarity_emoji(card['rarity'])} {card['name']} выдана @{user['username']}!")
            if card['file_id']:
                try:
                    await bot.send_photo(uid, photo=card['file_id'], caption=f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
                except:
                    await bot.send_message(uid, f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
            else:
                await bot.send_message(uid, f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
        except:
            await msg.answer("❌ /givecard @user ID_карты")
    
    @dp.message(Command("takediamonds"))
    async def take_diamonds(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            amount = int(p[2])
            u = await get_user(uid)
            if u['diamonds'] < amount:
                await msg.answer(f"❌ У пользователя только {u['diamonds']}💎!")
                return
            await upd_diamonds(uid, -amount)
            await msg.answer(f"✅ -{amount}💎 у @{u['username']}!")
        except:
            await msg.answer("❌ /takediamonds @user кол-во")
    
    @dp.message(Command("takerolls"))
    async def take_rolls(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            amount = int(p[2])
            u = await get_user(uid)
            if u['rolls'] < amount:
                await msg.answer(f"❌ У пользователя только {u['rolls']}🎲!")
                return
            await upd_rolls(uid, -amount)
            await msg.answer(f"✅ -{amount}🎲 у @{u['username']}!")
        except:
            await msg.answer("❌ /takerolls @user кол-во")
    
    @dp.message(Command("takeevent"))
    async def take_event(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            amount = int(p[2])
            u = await get_user(uid)
            if u['event_rolls'] < amount:
                await msg.answer(f"❌ У пользователя только {u['event_rolls']}🎪!")
                return
            await upd_event_rolls(uid, -amount)
            await msg.answer(f"✅ -{amount}🎪 у @{u['username']}!")
        except:
            await msg.answer("❌ /takeevent @user кол-во")
    
    @dp.message(Command("takecard"))
    async def take_card(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            cid = int(p[2])
            qty = int(p[3]) if len(p) > 3 else 1
            card = await get_card_by_id(cid)
            uc = await get_user_card(uid, cid)
            if not uc:
                await msg.answer(f"❌ У пользователя нет карты #{cid}!")
                return
            if uc['quantity'] < qty:
                await msg.answer(f"❌ У пользователя только {uc['quantity']} шт. карты #{cid}!")
                return
            if await remove_card(uid, cid, qty):
                user = await get_user(uid)
                await msg.answer(f"✅ Забрано {qty} шт. карты #{cid} {rarity_emoji(card['rarity'])} {card['name']} у @{user['username']}!")
            else:
                await msg.answer("❌ Не удалось забрать карту!")
        except:
            await msg.answer("❌ /takecard @user ID_карты [кол-во]")
    
    @dp.message(Command("setlevel"))
    async def set_level(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            uid = await resolve_user(p[1])
            level = int(p[2])
            db = await get_db()
            xp_needed = (level - 1) * 100 + 50
            await db.execute("UPDATE users SET level=?, xp=? WHERE user_id=?", (level, xp_needed, uid))
            await db.commit()
            user = await get_user(uid)
            await msg.answer(f"✅ @{user['username']} теперь уровня {level}!")
        except:
            await msg.answer("❌ /setlevel @user уровень")
    
    @dp.message(Command("resettasks"))
    async def reset_tasks(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/resettasks","").strip())
            db = await get_db()
            await db.execute("DELETE FROM daily_tasks WHERE user_id=?", (uid,))
            await db.execute("DELETE FROM weekly_tasks WHERE user_id=?", (uid,))
            await db.commit()
            user = await get_user(uid)
            await msg.answer(f"✅ Задания сброшены для @{user['username']}!")
        except:
            await msg.answer("❌ /resettasks @user")
    
    @dp.message(Command("inv"))
    async def admin_inv(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/inv","").strip())
            user = await get_user(uid)
            cards = await get_user_cards(uid)
            if not cards:
                await msg.answer(f"🎒 Инвентарь @{user['username']} пуст")
                return
            text = f"🎒 Инвентарь @{user['username']}:\n\n"
            for card in cards[:50]:
                text += f"#{card['id']} {rarity_emoji(card['rarity'])} {card['name']} x{card['quantity']}\n"
            if len(cards) > 50:
                text += f"\n...и ещё {len(cards)-50} карт"
            await msg.answer(text[:4000])
        except:
            await msg.answer("❌ /inv @user")
    
    @dp.message(Command("userscount"))
    async def users_count(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        async with db.execute("SELECT COUNT(*) as total FROM users") as c:
            row = await c.fetchone()
            total = row['total'] if row else 0
        async with db.execute("SELECT COUNT(*) as active FROM users WHERE banned=0") as c:
            row = await c.fetchone()
            active = row['active'] if row else 0
        async with db.execute("SELECT COUNT(*) as banned FROM users WHERE banned=1") as c:
            row = await c.fetchone()
            banned = row['banned'] if row else 0
        await msg.answer(f"📊 Статистика пользователей:\n\n👥 Всего: {total}\n✅ Активных: {active}\n⛔ Забанено: {banned}")
    
    @dp.message(Command("giveall"))
    async def giveall_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            t, am = p[1], int(p[2])
            users = await get_all_users()
            for u in users:
                try:
                    if t == 'diamonds':
                        await upd_diamonds(u['user_id'], am)
                    elif t == 'rolls':
                        await upd_rolls(u['user_id'], am)
                    elif t == 'event':
                        await upd_event_rolls(u['user_id'], am)
                    elif t == 'fortune':
                        await upd_fortune_spins(u['user_id'], am)
                except:
                    pass
            await msg.answer(f"✅ {am} для всех!")
        except:
            await msg.answer("❌ /giveall ТИП КОЛ-ВО")
    
    @dp.message(Command("broadcast"))
    async def bcmd(msg: types.Message, state: FSMContext):
        await msg.answer("📢 Сообщение:")
        await state.set_state(BroadcastStates.waiting_for_broadcast)
    
    @dp.message(Command("ban"))
    async def ban_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/ban","").strip())
            db = await get_db()
            await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
            await db.commit()
            await msg.answer("⛔ Забанен!")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("unban"))
    async def unban_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/unban","").strip())
            db = await get_db()
            await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
            await db.commit()
            await msg.answer("✅ Разбанен!")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("promo"))
    async def promo_create(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            code = p[1].upper()
            ptype = p[2]
            value = int(p[3])
            uses = int(p[4]) if len(p) > 4 else 1
            db = await get_db()
            await db.execute("INSERT OR REPLACE INTO promocodes VALUES (?,?,?,?,?)", (code, ptype, value, uses, msg.from_user.id))
            await db.commit()
            await msg.answer(f"✅ {code}")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("user"))
    async def user_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/user","").strip())
            u = await get_user(uid)
            await msg.answer(f"👤 @{u['username']}\n⭐ Ур.{u['level']}\n💎{u['diamonds']} 🎲{u['rolls']} 🎪{u['event_rolls']}")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("reset"))
    async def reset_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.replace("/reset","").strip())
            db = await get_db()
            await db.execute("UPDATE users SET rolls=0,diamonds=0,event_rolls=0,fortune_spins=0,total_rolls=0,xp=0,level=1 WHERE user_id=?", (uid,))
            await db.execute("DELETE FROM user_cards WHERE user_id=?", (uid,))
            await db.commit()
            await msg.answer("✅ Сброшен!")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("stats"))
    async def stats_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            row = await c.fetchone()
            users = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM cards") as c:
            row = await c.fetchone()
            cards = row[0] if row else 0
        await msg.answer(f"📊 👥{users} 🎴{cards}")
    
    @dp.message(Command("force_morning"))
    async def fm(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await morning_bonus()
        await msg.answer("✅")
    
    @dp.message(Command("force_evening"))
    async def fe(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await evening_bonus()
        await msg.answer("✅")
    
    @dp.message(Command("backup"))
    async def backup_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            await msg.answer_document(FSInputFile(DB_PATH), caption="📦 Бекап базы данных")
        else:
            await msg.answer("❌ База пуста!")
    
    @dp.message(Command("restore"))
    async def restore_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not msg.document:
            await msg.answer("❌ Отправь файл .db")
            return
        try:
            file = await bot.get_file(msg.document.file_id)
            await bot.download_file(file.file_path, DB_PATH)
            await init_db()
            db = await get_db()
            await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
            await db.commit()
            await msg.answer("✅ База восстановлена!")
        except Exception as e:
            await msg.answer(f"❌ {e}")
    
    @dp.message(Command("check_db"))
    async def check_db(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM cards") as c:
            row = await c.fetchone()
            cards = row[0] if row else 0
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            row = await c.fetchone()
            users = row[0] if row else 0
        await msg.answer(f"📊 🎴{cards} 👥{users}")
    
    @dp.message(Command("fix_fortune"))
    async def fix_fortune(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        await db.execute("UPDATE users SET fortune_spins=1 WHERE fortune_spins=0")
        await db.commit()
        await msg.answer("✅ Всем выдано по 1 вращению колеса!")
    
    @dp.message(Command("set_rate"))
    async def set_rate(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            await set_setting(f'rate_{p[1]}', p[2])
            await msg.answer(f"✅ {p[1]}={p[2]}%")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("set_guarantor"))
    async def set_guar(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            p = msg.text.split()
            await set_setting('guarantor_limit', p[1])
            await msg.answer(f"✅ Гарант={p[1]}")
        except:
            await msg.answer("❌")
    
    @dp.message(Command("set_morning_rolls"))
    async def smr(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('morning_rolls', msg.text.split()[1])
            await msg.answer("✅")
        except:
            pass
    
    @dp.message(Command("set_morning_diamonds"))
    async def smd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('morning_diamonds', msg.text.split()[1])
            await msg.answer("✅")
        except:
            pass
    
    @dp.message(Command("set_evening_rolls"))
    async def ser(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('evening_rolls', msg.text.split()[1])
            await msg.answer("✅")
        except:
            pass
    
    @dp.message(Command("set_evening_diamonds"))
    async def sed(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('evening_diamonds', msg.text.split()[1])
            await msg.answer("✅")
        except:
            pass
    
    @dp.message(Command("set_break_R"))
    async def sbr(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('break_R', msg.text.split()[1])
            await msg.answer("✅ R: +"+msg.text.split()[1]+"💎")
        except:
            pass
    
    @dp.message(Command("set_break_SR"))
    async def sbsr(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('break_SR', msg.text.split()[1])
            await msg.answer("✅ SR: +"+msg.text.split()[1]+"💎")
        except:
            pass
    
    @dp.message(Command("set_break_SSR"))
    async def sbssr(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('break_SSR', msg.text.split()[1])
            await msg.answer("✅ SSR: +"+msg.text.split()[1]+"💎")
        except:
            pass
    
    @dp.message(Command("set_break_L"))
    async def sbl(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            await set_setting('break_L', msg.text.split()[1])
            await msg.answer("✅ L: +"+msg.text.split()[1]+"💎")
        except:
            pass
    
    @dp.message(Command("show_settings"))
    async def show_settings(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        async with db.execute("SELECT * FROM settings ORDER BY key") as c:
            rows = await c.fetchall()
        await msg.answer("⚙️:\n\n" + "\n".join([f"{r[0]}={r[1]}" for r in rows])[:4000])
    
    # ==================== ТЕКСТОВЫЕ КНОПКИ ====================
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
            if card['rarity'] == 'SSR':
                await update_weekly_progress(uid, 'weekly_ssr')
                guild = await get_user_guild(uid)
                if guild:
                    await update_guild_task_progress(guild['id'], uid, 'guild_ssr')
            caption = f"{rarity_emoji(card['rarity'])} {card['name']}\n"
            if card['description']:
                caption += f"📝 {card['description']}\n"
            caption += f"⭐ {card['rarity']}\n📎 #{card['id']}"
            if booster:
                caption += "\n⚡ Бустер удачи!"
            if levels_gained > 0:
                caption += f"\n⬆ Уровень {new_level}!"
            user = await get_user(uid)
            caption += f"\n\n📊 Осталось: 🎲{user['rolls']} | 💎{user['diamonds']} | 🎪{user['event_rolls']} | 🎡{user['fortune_spins']}"
            return card, caption
        except Exception as e:
            logger.error(f"Ошибка крутки: {e}")
            return None, f"Ошибка: {e}"
    
    async def perform_event_roll(uid):
        db = await get_db()
        u = await get_user(uid)
        cards = await get_event_cards_active() if await get_active_event() else await get_event_cards()
        if not cards:
            return None, "🎪 Нет ивента!"
        L = [c for c in cards if c['is_L_card']]
        N = [c for c in cards if not c['is_L_card']]
        lim = await get_setting_int('guarantor_limit', 50)
        event_rate_L = await get_setting_int('event_rate_L', 2)
        is_guaranteed = False
        async with db.execute("UPDATE users SET event_guarantor = 0 WHERE user_id = ? AND event_guarantor >= ?", (uid, lim)) as cursor:
            if cursor.rowcount > 0:
                is_guaranteed = True
            else:
                await db.execute("UPDATE users SET event_guarantor = event_guarantor + 1 WHERE user_id = ?", (uid,))
        await db.commit()
        if is_guaranteed and L:
            card = random.choice(L)
            g = "🎉 ГАРАНТ! "
        elif L and random.random() < event_rate_L / 100:
            card = random.choice(L)
            await db.execute("UPDATE users SET event_guarantor = 0 WHERE user_id = ?", (uid,))
            await db.commit()
            g = "🌟 L! "
        else:
            card = random.choice(N if N else cards)
            g = ""
        await add_card_to_user(uid, card['id'], is_original=True)
        booster = await get_booster(uid, 'event')
        lvl, nl = await add_xp(uid, int(20 * (1.5 if booster else 1)))
        if card['rarity'] in ('SSR', 'L'):
            await update_weekly_progress(uid, 'weekly_ssr')
            guild = await get_user_guild(uid)
            if guild:
                await update_guild_task_progress(guild['id'], uid, 'guild_ssr')
        cap = f"{g}{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']:
            cap += f"📝 {card['description']}\n"
        cap += f"⭐ {card['rarity']}\n📎 #{card['id']}"
        if booster:
            cap += "\n⚡ Бустер!"
        if lvl > 0:
            cap += f"\n⬆ Ур.{nl}!"
        user = await get_user(uid)
        cap += f"\n\n📊 Осталось: 🎲{user['rolls']} | 💎{user['diamonds']} | 🎪{user['event_rolls']} | 🎡{user['fortune_spins']}"
        return card, cap
    
    async def send_card(msg, card, caption):
        uid = msg.from_user.id
        uc = await get_user_card(uid, card['id'])
        kb = None
        if uc and uc['quantity'] > 1:
            extra = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
            price = await get_break_price(card['rarity'])
            if await get_booster(uid, 'break'):
                price = int(price * 1.5)
            if extra > 0:
                caption += f"\n\n🔄 Это повторка! У вас уже есть эта карта."
                caption += f"\n💎 При разбитии {'всех повторов' if extra > 1 else 'повтора'} вы получите +{extra * price}💎"
                if await get_booster(uid, 'break'):
                    caption += " (с бустером x1.5)"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔨 Разбить (+{extra * price}💎)", callback_data=f"break_{card['id']}")]
            ])
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=kb)
            else:
                await msg.answer(caption, reply_markup=kb)
        except Exception as e:
            logger.error(f"Не удалось отправить карту #{card['id']}: {e}")
            await msg.answer(caption, reply_markup=kb)
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u or u['rolls'] <= 0:
            await msg.answer("❌ Нет круток!")
            return
        await upd_rolls(msg.from_user.id, -1)
        card, caption = await perform_regular_roll(msg.from_user.id)
        if card is None:
            await msg.answer(f"❌ {caption}")
            return
        await update_task_progress(msg.from_user.id, 'roll')
        await update_weekly_progress(msg.from_user.id, 'weekly_rolls')
        guild = await get_user_guild(msg.from_user.id)
        if guild:
            await update_guild_task_progress(guild['id'], msg.from_user.id, 'guild_rolls')
        ach = await check_achievements(msg.from_user.id)
        await send_card(msg, card, caption)
        if ach:
            for a in ach:
                await msg.answer(f"🏅 {a['icon']} {a['name']}!")
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id):
                await msg.answer("🎉 +1 бонусная крутка!")
    
    @dp.message(F.text == "🎪 Ивент-крутка")
    async def event_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['event_rolls'] <= 0:
            await msg.answer("❌ Нет ивент-круток!")
            return
        await upd_event_rolls(msg.from_user.id, -1)
        card, caption = await perform_event_roll(msg.from_user.id)
        if card is None:
            await msg.answer(caption)
            return
        await update_task_progress(msg.from_user.id, 'event_roll')
        ach = await check_achievements(msg.from_user.id)
        await send_card(msg, card, caption)
        if ach:
            for a in ach:
                await msg.answer(f"🏅 {a['icon']} {a['name']}!")
    
    @dp.message(F.text == "💥 Разбить всё")
    async def break_all_btn(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        booster = await get_booster(msg.from_user.id, 'break')
        text = "⚠️ Разбить ВСЕ повторы?\n\n"
        total_qty = 0
        total_price = 0
        for card in cards:
            if card['quantity'] > 1:
                qty = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if qty > 0:
                    price = await get_break_price(card['rarity'])
                    if booster:
                        price = int(price * 1.5)
                    total_qty += qty
                    total_price += qty * price
                    text += f"{rarity_emoji(card['rarity'])} {card['name']}: {qty} шт × {price}💎 = {qty * price}💎\n"
        if total_qty == 0:
            await msg.answer("❌ Нет повторов!")
            return
        text += f"\n💰 Итого: {total_price}💎"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, разбить всё (+{total_price}💎)", callback_data="confirm_break_all")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_break_all")],
        ])
        await msg.answer(text, reply_markup=kb)
    
    @dp.message(F.text == "🛍 Магазин")
    async def shop_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Обычные крутки", callback_data="shop_regular")],
            [InlineKeyboardButton(text="🎪 Ивент-крутки", callback_data="shop_event")],
        ])
        await msg.answer("🛍 Магазин:", reply_markup=kb)
    
    @dp.message(F.text == "⚡ Бустеры")
    async def booster_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍀 Удача - 5💎/1ч", callback_data="buy_booster_luck")],
            [InlineKeyboardButton(text="🎪 Ивент - 10💎/1ч", callback_data="buy_booster_event")],
            [InlineKeyboardButton(text="💎 Разбитие - 3💎/1ч", callback_data="buy_booster_break")],
        ])
        await msg.answer("⚡ Бустеры (x1.5 на 1 час):", reply_markup=kb)
    
    # ==================== КОЛЕСО ФОРТУНЫ ====================
    async def spin_fortune(uid):
        prizes = FORTUNE_PRIZES
        weights = [p['weight'] for p in prizes]
        prize = random.choices(prizes, weights=weights)[0]
        if prize['prize'] == 'roll':
            await upd_rolls(uid, prize['value'])
        elif prize['prize'] == 'diamond':
            await upd_diamonds(uid, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_regular_cards()
            if cards:
                card = random.choice(cards)
                await add_card_to_user(uid, card['id'], is_original=True)
                booster = await get_booster(uid, 'luck')
                xp = int(10 * (1.5 if booster else 1.0))
                levels_gained, new_level = await add_xp(uid, xp)
                if card['rarity'] == 'SSR':
                    await update_weekly_progress(uid, 'weekly_ssr')
                    guild = await get_user_guild(uid)
                    if guild:
                        await update_guild_task_progress(guild['id'], uid, 'guild_ssr')
                caption = f"🎡 Колесо фортуны!\n\n🎴 {rarity_emoji(card['rarity'])} {card['name']}\n"
                if card['description']:
                    caption += f"📝 {card['description']}\n"
                caption += f"⭐ {card['rarity']}\n📎 #{card['id']}"
                if booster:
                    caption += "\n⚡ Бустер удачи!"
                if levels_gained > 0:
                    caption += f"\n⬆ Уровень {new_level}!"
                user = await get_user(uid)
                caption += f"\n\n📊 Осталось: 🎲{user['rolls']} | 💎{user['diamonds']} | 🎪{user['event_rolls']} | 🎡{user['fortune_spins']}"
                return card, caption
        user = await get_user(uid)
        result_text = f"🎡 Колесо фортуны!\n\n{prize['desc']}\n\n📊 Осталось: 🎲{user['rolls']} | 💎{user['diamonds']} | 🎪{user['event_rolls']} | 🎡{user['fortune_spins']}"
        return None, result_text
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вр. - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вр. - 3💎", callback_data="fortune_buy_5")],
            ])
            await msg.answer("🎡 Нет вращений!\nКупить за алмазы:", reply_markup=kb)
            return
        await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
        await update_task_progress(msg.from_user.id, 'fortune')
        await update_weekly_progress(msg.from_user.id, 'weekly_fortune')
        guild = await get_user_guild(msg.from_user.id)
        if guild:
            await update_guild_task_progress(guild['id'], msg.from_user.id, 'guild_fortune')
        card, caption = await spin_fortune(msg.from_user.id)
        ach = await check_achievements(msg.from_user.id)
        if card:
            await send_card(msg, card, caption)
            if ach:
                for a in ach:
                    await msg.answer(f"🏅 {a['icon']} {a['name']}!")
        else:
            await msg.answer(caption)
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id):
                await msg.answer("🎉 +1 бонусная крутка!")
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call: types.CallbackQuery):
        am = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[am]:
            await call.answer(f"❌ Нужно {prices[am]}💎!", show_alert=True)
            return
        await upd_diamonds(call.from_user.id, -prices[am])
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + am)
        await call.answer(f"✅ Куплено {am} вращений!", show_alert=True)
        user = await get_user(call.from_user.id)
        await call.message.answer(f"🎡 Куплено {am} вращений колеса фортуны за {prices[am]}💎\n📊 Осталось: 🎡{user['fortune_spins']} | 💎{user['diamonds']}")
    
    @dp.message(F.text == "👤 Профиль")
    async def profile_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u:
            return
        cards = await get_card_count(msg.from_user.id)
        total_cards = await get_total_cards_count()
        xp_need = u['level'] * 100 + 50
        progress = int(u['xp'] / xp_need * 10) if xp_need > 0 else 10
        bar = "▓" * progress + "░" * (10 - progress)
        ds = await get_duel_stats(msg.from_user.id)
        w, l = (ds['wins'], ds['losses']) if ds else (0, 0)
        await update_task_progress(msg.from_user.id, 'profile')
        text = (
            f"👤 {u['username']} | ⭐ Ур.{u['level']}\n"
            f"📊 XP: {u['xp']}/{xp_need} [{bar}] {int(u['xp']/xp_need*100) if xp_need > 0 else 100}%\n"
            f"💎 {u['diamonds']} | 🎲 {u['rolls']} | 🎪 {u['event_rolls']}\n"
            f"🎴 Карт: {cards}/{total_cards}\n"
            f"🎡 Колесо: {u['fortune_spins']} | ⚔️ Дуэли: {w}W/{l}L\n"
            f"🔥 Серия: {u['login_streak']} дн."
        )
        text += f"\n\n💡 /levels - посмотреть награды за уровни"
        fav = await get_favorite_card(msg.from_user.id)
        if fav and fav['file_id']:
            fav_text = f"❤️ Любимая карта:\n{rarity_emoji(fav['rarity'])} {fav['name']}\n⭐ {fav['rarity']} | 📎 #{fav['id']}"
            try:
                await msg.answer_photo(
                    photo=fav['file_id'],
                    caption=f"{text}\n\n{fav_text}",
                    reply_markup=permanent_keyboard()
                )
                return
            except:
                text += f"\n\n{fav_text}"
        elif fav:
            text += f"\n\n❤️ Любимая карта:\n{rarity_emoji(fav['rarity'])} {fav['name']} #{fav['id']}"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "⬆ Уровни")
    async def levels_btn(msg: types.Message):
        u = await get_user(msg.from_user.id)
        rewards = await get_level_rewards(msg.from_user.id)
        xp_need = u['level'] * 100 + 50
        progress = int(u['xp'] / xp_need * 10) if xp_need > 0 else 10
        bar = "▓" * progress + "░" * (10 - progress)
        text = (
            f"⬆ Ваш уровень: {u['level']}\n"
            f"📊 XP: {u['xp']}/{xp_need}\n"
            f"[{bar}] {int(u['xp']/xp_need*100) if xp_need > 0 else 100}%\n\n"
            "📈 Как получить XP:\n"
            "🎲 Крутка: 10 XP (15 с бустером)\n"
            "🎪 Ивент-крутка: 20 XP (30 с бустером)\n"
            "🎡 Колесо фортуны (карта): 10 XP (15 с бустером)\n"
            "🔨 Разбитие карты: 2 XP за каждую\n"
            "⚔️ Победа в дуэли: 15 XP\n"
            "⚔️ Поражение в дуэли: 5 XP\n"
            "✂️ Победа в КНБ: 20 XP\n"
            "✂️ Поражение в КНБ: 5 XP\n\n"
            "🎁 Награды за уровни:\n"
        )
        level_rewards_desc = {
            2: "🎲 +1 крутка", 3: "💎 +2 алмаза", 4: "🎲 +1 крутка, 💎 +1 алмаз",
            5: "🎪 +1 ивент-крутка", 6: "🎲 +2 крутки", 7: "💎 +3 алмаза",
            8: "🎲 +1 крутка, 🎪 +1 ивент-крутка", 9: "💎 +5 алмазов",
            10: "🎲 +3 крутки, 💎 +3 алмаза, 🎪 +1 ивент-крутка",
        }
        for lvl in range(2, 11):
            if lvl <= u['level']:
                db = await get_db()
                async with db.execute("SELECT claimed FROM level_rewards WHERE user_id=? AND level=?", (msg.from_user.id, lvl)) as c:
                    row = await c.fetchone()
                if row and row[0]:
                    text += f"✅ Ур.{lvl}: {level_rewards_desc.get(lvl, '')}\n"
                else:
                    text += f"🎁 Ур.{lvl}: {level_rewards_desc.get(lvl, '')}\n"
            else:
                text += f"🔒 Ур.{lvl}: {level_rewards_desc.get(lvl, '')}\n"
        text += "\n🎁 После 10 уровня:\nКаждые 5 уровней:\n🎲 Крутки = уровень ÷ 2\n💎 Алмазы = уровень\n🎪 Ивент-крутки = уровень ÷ 5\n"
        if rewards:
            text += f"\n🎁 Доступно наград: {len(rewards)}"
            buttons = []
            for r in rewards[:5]:
                lvl = r['level']
                buttons.append([InlineKeyboardButton(text=f"🎁 Ур.{lvl} - {level_rewards_desc.get(lvl, 'Награда')}", callback_data=f"claim_level_{lvl}")])
            if len(rewards) > 5:
                buttons.append([InlineKeyboardButton(text=f"🎁 И ещё {len(rewards)-5} наград...", callback_data="show_all_rewards")])
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            text += "\n✅ Все награды получены!"
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data == "show_all_rewards")
    async def show_all_rewards(call: types.CallbackQuery):
        rewards = await get_level_rewards(call.from_user.id)
        if not rewards:
            await call.answer("Нет доступных наград", show_alert=True)
            return
        text = "🎁 Все доступные награды:\n\n"
        level_rewards_desc = {
            2: "🎲 +1 крутка", 3: "💎 +2 алмаза", 4: "🎲 +1 крутка, 💎 +1 алмаз",
            5: "🎪 +1 ивент-крутка", 6: "🎲 +2 крутки", 7: "💎 +3 алмаза",
            8: "🎲 +1 крутка, 🎪 +1 ивент-крутка", 9: "💎 +5 алмазов",
            10: "🎲 +3 крутки, 💎 +3 алмаза, 🎪 +1 ивент-крутка",
        }
        buttons = []
        for r in rewards:
            lvl = r['level']
            desc = level_rewards_desc.get(lvl, f"🎲 {lvl//2} круток, 💎 {lvl} алмазов, 🎪 {lvl//5} ивент")
            text += f"🎁 Ур.{lvl}: {desc}\n"
            buttons.append([InlineKeyboardButton(text=f"🎁 Ур.{lvl}", callback_data=f"claim_level_{lvl}")])
        await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    async def show_inventory(msg, uid, page=0, edit=False):
        user = await get_user(uid)
        cards = await get_user_cards(uid)
        if not cards:
            text = "🎒 Инвентарь пуст"
            if edit:
                await msg.edit_text(text)
            else:
                await msg.answer(text, reply_markup=permanent_keyboard())
            return
        cards_per_page = 10
        total_pages = (len(cards) + cards_per_page - 1) // cards_per_page
        page = max(0, min(page, total_pages - 1))
        start = page * cards_per_page
        end = start + cards_per_page
        page_cards = cards[start:end]
        text = f"🎒 Инвентарь ({page + 1}/{total_pages}):\n\n"
        buttons = []
        for card in page_cards:
            fav_mark = "❤️" if user and user['favorite_card'] == card['id'] else ""
            orig = "🔒" if card['is_original'] else ""
            ev = "🎪" if card['is_event_card'] else ""
            text += f"{fav_mark}{orig}{ev}{rarity_emoji(card['rarity'])} #{card['id']} {card['name']} x{card['quantity']}\n"
            buttons.append([InlineKeyboardButton(text=f"📋 #{card['id']} {card['name']}", callback_data=f"cardinfo_{card['id']}")])
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"inv_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"inv_page_{page + 1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        if edit:
            await msg.edit_text(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=kb)
    
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_btn_msg(msg: types.Message):
        await show_inventory(msg, msg.from_user.id, 0)
    
    @dp.callback_query(F.data.startswith("inv_page_"))
    async def inv_btn_callback(call: types.CallbackQuery):
        page = int(call.data.split("_")[2])
        await show_inventory(call.message, call.from_user.id, page, edit=True)
        await call.answer()
    
    @dp.message(F.text == "📋 Задания")
    async def tasks_btn(msg: types.Message):
        tasks = await get_daily_tasks(msg.from_user.id)
        text = "📋 Ежедневные:\n\n"
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            ti = next((x for x in TASK_TYPES if x['type'] == t['task_type']), None)
            text += f"{st} {ti['desc'] if ti else t['task_type']} ({t['progress']}/{t['task_target']})\n"
        if await check_all_tasks_completed(msg.from_user.id):
            if await give_bonus_roll(msg.from_user.id):
                text += "\n🎉 +1🎲!"
        await msg.answer(text)
    
    @dp.message(F.text == "📅 Неделя")
    async def weekly_btn(msg: types.Message):
        await ensure_weekly_tasks(msg.from_user.id)
        tasks = await get_weekly_tasks(msg.from_user.id)
        text = "📅 Еженедельные:\n\n"
        names = {"weekly_rolls": "🎲 20 круток", "weekly_fortune": "🎡 Колесо 5 раз", "weekly_break": "🔨 Разбить 10", "weekly_ssr": "🟣 Выбить 3 SSR"}
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            text += f"{st} {names.get(t['task_type'], t['task_type'])} ({t['progress']}/{t['task_target']})\n"
        if all(t['completed'] for t in tasks) and not any(t['reward_claimed'] for t in tasks):
            text += "\n🎁 +3💎 +2🎲 +1🎪\n/claim_weekly"
        elif all(t['completed'] for t in tasks):
            text += "\n✅ Награда получена"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "💱 Биржа")
    async def market_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Лоты", callback_data="market_view")],
            [InlineKeyboardButton(text="🔍 /find", callback_data="msi")],
            [InlineKeyboardButton(text="📊 /sell", callback_data="msi2")],
        ])
        await msg.answer("💱 Биржа:", reply_markup=kb)
    
    @dp.message(F.text == "🏪 Аукцион")
    async def auc_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Активные", callback_data="auction_view")],
            [InlineKeyboardButton(text="📊 /auction", callback_data="auction_info")],
        ])
        await msg.answer("🏪 Аукцион:", reply_markup=kb)
    
    @dp.message(F.text == "🔄 Обмен")
    async def trade_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 /trade", callback_data="trade_info")],
            [InlineKeyboardButton(text="🔍 Недостающие карты", callback_data="missing_cards")],
            [InlineKeyboardButton(text="📦 Мои повторы", callback_data="my_duplicates")],
        ])
        await msg.answer("🔄 Обмен картами:", reply_markup=kb)
    
    @dp.callback_query(F.data == "trade_info")
    async def trade_info(call: types.CallbackQuery):
        await call.message.answer("🔄 Обмен картами:\n\n📋 /trade @user ID_моей ID_его\n\nГде:\n• @user - username игрока\n• ID_моей - номер вашей карты\n• ID_его - номер карты, которую хотите получить\n\n💡 Совет: используйте кнопки ниже\nчтобы узнать каких карт не хватает\nи какие есть повторы")
        await call.answer()
    
    @dp.callback_query(F.data == "missing_cards")
    async def show_missing_cards(call: types.CallbackQuery):
        all_cards = await get_all_cards()
        user_cards = await get_user_cards(call.from_user.id)
        user_card_ids = {c['id'] for c in user_cards}
        missing = [c for c in all_cards if c['id'] not in user_card_ids and not c['is_event_card']]
        if not missing:
            await call.message.answer("🎉 У вас есть все обычные карты!")
            await call.answer()
            return
        cards_per_page = 30
        total_pages = (len(missing) + cards_per_page - 1) // cards_per_page
        page_cards = missing[:cards_per_page]
        text = f"🔍 Недостающие карты (1/{total_pages}):\n\n"
        buttons = []
        row = []
        for card in page_cards:
            text += f"#{card['id']} {rarity_emoji(card['rarity'])} {card['name']}\n"
            row.append(InlineKeyboardButton(text=f"#{card['id']}", callback_data=f"cardinfo_{card['id']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        text += f"\n📊 Не хватает: {len(missing)}/{len(all_cards)} карт"
        nav = []
        if total_pages > 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"missing_page_1"))
        buttons.append(nav)
        nav2 = [InlineKeyboardButton(text="📦 Повторы", callback_data="my_duplicates"),
                InlineKeyboardButton(text="🔄 Обмен", callback_data="trade_info")]
        buttons.append(nav2)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("missing_page_"))
    async def missing_cards_page(call: types.CallbackQuery):
        page = int(call.data.split("_")[2])
        all_cards = await get_all_cards()
        user_cards = await get_user_cards(call.from_user.id)
        user_card_ids = {c['id'] for c in user_cards}
        missing = [c for c in all_cards if c['id'] not in user_card_ids and not c['is_event_card']]
        cards_per_page = 30
        total_pages = (len(missing) + cards_per_page - 1) // cards_per_page
        page = max(0, min(page, total_pages - 1))
        start = page * cards_per_page
        end = start + cards_per_page
        page_cards = missing[start:end]
        text = f"🔍 Недостающие карты ({page + 1}/{total_pages}):\n\n"
        buttons = []
        row = []
        for card in page_cards:
            text += f"#{card['id']} {rarity_emoji(card['rarity'])} {card['name']}\n"
            row.append(InlineKeyboardButton(text=f"#{card['id']}", callback_data=f"cardinfo_{card['id']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        text += f"\n📊 Не хватает: {len(missing)}/{len(all_cards)} карт"
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"missing_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"missing_page_{page+1}"))
        buttons.append(nav)
        nav2 = [InlineKeyboardButton(text="📦 Повторы", callback_data="my_duplicates"),
                InlineKeyboardButton(text="🔄 Обмен", callback_data="trade_info")]
        buttons.append(nav2)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "my_duplicates")
    async def show_my_duplicates(call: types.CallbackQuery):
        user_cards = await get_user_cards(call.from_user.id)
        duplicates = []
        for card in user_cards:
            if card['quantity'] > 1:
                extra = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if extra > 0:
                    duplicates.append({'card': card, 'extra': extra, 'price': await get_break_price(card['rarity'])})
        if not duplicates:
            await call.message.answer("📦 У вас нет повторяющихся карт!")
            await call.answer()
            return
        cards_per_page = 30
        total_pages = (len(duplicates) + cards_per_page - 1) // cards_per_page
        page_dupes = duplicates[:cards_per_page]
        text = f"📦 Ваши повторы (1/{total_pages}):\n\n"
        buttons = []
        row = []
        for item in page_dupes:
            card = item['card']
            text += f"#{card['id']} {rarity_emoji(card['rarity'])} {card['name']} x{item['extra']}\n"
            row.append(InlineKeyboardButton(text=f"#{card['id']}", callback_data=f"cardinfo_{card['id']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        text += f"\n📊 Всего повторов: {sum(d['extra'] for d in duplicates)} шт."
        nav = []
        if total_pages > 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"duplicates_page_1"))
        buttons.append(nav)
        nav2 = [InlineKeyboardButton(text="🔍 Недостающие", callback_data="missing_cards"),
                InlineKeyboardButton(text="🔄 Обмен", callback_data="trade_info")]
        buttons.append(nav2)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("duplicates_page_"))
    async def duplicates_page(call: types.CallbackQuery):
        page = int(call.data.split("_")[2])
        user_cards = await get_user_cards(call.from_user.id)
        duplicates = []
        for card in user_cards:
            if card['quantity'] > 1:
                extra = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if extra > 0:
                    duplicates.append({'card': card, 'extra': extra, 'price': await get_break_price(card['rarity'])})
        cards_per_page = 30
        total_pages = (len(duplicates) + cards_per_page - 1) // cards_per_page
        page = max(0, min(page, total_pages - 1))
        start = page * cards_per_page
        end = start + cards_per_page
        page_dupes = duplicates[start:end]
        text = f"📦 Ваши повторы ({page + 1}/{total_pages}):\n\n"
        buttons = []
        row = []
        for item in page_dupes:
            card = item['card']
            text += f"#{card['id']} {rarity_emoji(card['rarity'])} {card['name']} x{item['extra']}\n"
            row.append(InlineKeyboardButton(text=f"#{card['id']}", callback_data=f"cardinfo_{card['id']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        text += f"\n📊 Всего повторов: {sum(d['extra'] for d in duplicates)} шт."
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"duplicates_page_{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"duplicates_page_{page+1}"))
        buttons.append(nav)
        nav2 = [InlineKeyboardButton(text="🔍 Недостающие", callback_data="missing_cards"),
                InlineKeyboardButton(text="🔄 Обмен", callback_data="trade_info")]
        buttons.append(nav2)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "noop")
    async def noop(call: types.CallbackQuery):
        await call.answer()
    
    @dp.message(F.text == "⚔️ Дуэль")
    async def duel_menu(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🃏 Дуэль картами", callback_data="duel_cards_info")],
            [InlineKeyboardButton(text="✂️ КНБ (3 раунда)", callback_data="duel_rps_info")],
        ])
        await msg.answer("⚔️ Выберите тип дуэли:", reply_markup=kb)
    
    @dp.message(F.text == "👥 Друзья")
    async def friends_btn(msg: types.Message):
        friends = await get_friends(msg.from_user.id)
        text = "👥 Друзья:\n\n" + ("\n".join([f"• @{f['username']}" for f in friends]) if friends else "Пока нет") + "\n\n/friend add @user"
        await msg.answer(text)
    
    @dp.message(F.text == "🏰 Гильдия")
    async def guild_btn(msg: types.Message):
        guild = await get_user_guild(msg.from_user.id)
        if guild:
            db = await get_db()
            async with db.execute("SELECT COUNT(*) FROM guild_members WHERE guild_id=?", (guild['id'],)) as c:
                row = await c.fetchone()
                cnt = row[0] if row else 0
            tasks = await get_guild_tasks(guild['id'])
            completed = sum(1 for t in tasks if t['completed']) if tasks else 0
            total = len(tasks) if tasks else 3
            can_claim, _ = await can_claim_guild_reward(guild['id'], msg.from_user.id)
            reward_status = "🌟 Награда доступна!" if can_claim else ""
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📋 Задания гильдии ({completed}/{total})", callback_data=f"guild_tasks_{guild['id']}")],
                [InlineKeyboardButton(text="🏆 Топ участников", callback_data=f"guild_top_{guild['id']}")],
            ])
            text = f"🏰 {guild['name']}\n👥 Участников: {cnt}\n📋 Заданий: {completed}/{total}"
            if reward_status:
                text += f"\n{reward_status}"
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer("🏰 /guild create НАЗВАНИЕ | /guild join НАЗВАНИЕ")
    
    @dp.message(F.text == "⚔️ Война гильдий")
    async def war_btn(msg: types.Message):
        season = await get_active_war_season()
        guild = await get_user_guild(msg.from_user.id)
        if not season:
            await msg.answer("⚔️ Нет войны!")
            return
        if not guild:
            await msg.answer("❌ Не в гильдии!")
            return
        if season['status'] == 'selection':
            await msg.answer("⚔️ Выбор карт!\n/war_pick ID")
        else:
            ranking = await get_guild_war_ranking(season['id'])
            text = "⚔️ БИТВЫ!\n\n🏆:\n" + ("\n".join([f"{i+1}. {g['name']} - {g.get('total_points', 0)} очков" for i, g in enumerate(ranking[:10])]) if ranking else "Нет")
            await msg.answer(text)
    
    @dp.message(F.text == "📚 Все карты")
    async def allc_btn(msg: types.Message):
        cards = await get_all_cards()
        if not cards:
            return
        buttons = []
        row = []
        for c in cards:
            if not c['is_event_card']:
                row.append(InlineKeyboardButton(text=f"#{c['id']}", callback_data=f"cardinfo_{c['id']}"))
                if len(row) == 5:
                    buttons.append(row)
                    row = []
        if row:
            buttons.append(row)
        await msg.answer("📚 Обычные:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)
    
    # ==================== ЛИДЕРЫ ====================
    @dp.message(F.text == "🏆 Лидеры")
    async def lead_btn(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎴 По картам", callback_data="lead_cards")],
            [InlineKeyboardButton(text="⭐ По уровню", callback_data="lead_level")],
            [InlineKeyboardButton(text="⚔️ По дуэлям", callback_data="lead_duels")],
        ])
        await msg.answer("🏆 Лидеры:", reply_markup=kb)
    
    @dp.callback_query(F.data == "lead_cards")
    async def lead_cards(call: types.CallbackQuery):
        top = await get_leaders(10)
        total_cards = await get_total_cards_count()
        text = "🏆 Топ-10 коллекционеров:\n\n"
        if top:
            for i, u in enumerate(top):
                medal = ['🥇','🥈','🥉'][i] if i < 3 else f'{i+1}.'
                text += f"{medal} {u['username']} - {u['total']}/{total_cards} карт\n"
        else:
            text += "Пусто\n"
        text += f"\n📚 Всего карт в коллекции: {total_cards}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_cards")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "lead_level")
    async def lead_level(call: types.CallbackQuery):
        top = await get_level_leaders(10)
        text = "⭐ Топ-10 по уровню:\n\n"
        if top:
            for i, u in enumerate(top):
                text += f"{['🥇','🥈','🥉'][i] if i < 3 else f'{i+1}.'} {u['username']} - Ур.{u['level']}\n"
        else:
            text += "Пусто\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_level")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "lead_duels")
    async def lead_duels(call: types.CallbackQuery):
        top = await get_duel_leaders(10)
        text = "⚔️ Топ-10 дуэлянтов:\n\n"
        if top:
            for i, u in enumerate(top):
                text += f"{['🥇','🥈','🥉'][i] if i < 3 else f'{i+1}.'} {u['username']} - {u['wins']}W/{u['losses']}L\n"
        else:
            text += "Пусто\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="lead_duels")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="lead_back")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "lead_back")
    async def lead_back(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎴 По картам", callback_data="lead_cards")],
            [InlineKeyboardButton(text="⭐ По уровню", callback_data="lead_level")],
            [InlineKeyboardButton(text="⚔️ По дуэлям", callback_data="lead_duels")],
        ])
        await call.message.edit_text("🏆 Лидеры:", reply_markup=kb)
        await call.answer()
    
    @dp.message(F.text == "🏅 Достижения")
    async def ach_btn(msg: types.Message):
        db = await get_db()
        text = "🏅 Достижения:\n\n"
        for ach in ACHIEVEMENTS:
            async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                row = await c.fetchone()
            text += f"{'🎁' if row and row[0] and not row[1] else '✅' if row and row[0] else '🔒'} {ach['icon']} {ach['name']}\n"
        buttons = []
        for ach in ACHIEVEMENTS:
            async with db.execute("SELECT completed, reward_claimed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])) as c:
                row = await c.fetchone()
            if row and row[0] and not row[1]:
                buttons.append([InlineKeyboardButton(text=f"🎁 {ach['icon']} {ach['name']}", callback_data=f"claim_ach_{ach['id']}")])
        await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else permanent_keyboard())
    
    @dp.message(F.text == "🎫 Промокод")
    async def promo_btn(msg: types.Message, state: FSMContext):
        await msg.answer("🎫 Введи код:")
        await state.set_state(PromoStates.waiting_for_code)
    
    @dp.message(F.text == "❓ Помощь")
    async def help_btn(msg: types.Message):
        await msg.answer("🎲 Крутить | 🛍 Магазин\n🎪 Ивент | 🎡 Колесо\n📋 Задания | 📅 Неделя\n💱 Биржа | 🏪 Аукцион\n🔄 Обмен | ⚔️ Дуэль\n👥 Друзья | 🏰 Гильдии\n💥 Разбить всё | ⚡ Бустеры\n💎 R=1 SR=5 SSR=10 L=20\n🕐 7:00 и 17:00 МСК\n\n🃏 Дуэль картами: /duel @user ID [ставка]\n✂️ Дуэль КНБ: /rps_duel @user [ставка]\n🎮 Ход в КНБ: /rps камень/ножницы/бумага\n🏰 Гильдия: /claim_guild_reward\n⬆ Уровни: /levels\n❤️ Любимая карта: /fav ID")
    
    # ==================== FSM ====================
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def an(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(name=msg.text.strip())
        await msg.answer("📝 Шаг 2/4\nОписание:")
        await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def ad(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nРедкость:", reply_markup=rarity_keyboard())
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def ap(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        data = await state.get_data()
        file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity'] == 'L'
        db = await get_db()
        await db.execute("INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?,?,?,?,?)", (data['name'], data['description'], file_id, data['rarity'], is_L))
        await db.commit()
        await msg.answer(f"✅ {data['name']} добавлена!")
        await state.clear()
    
    @dp.message(StateFilter(EditCardStates.waiting_for_new_value))
    async def process_edit_value(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        data = await state.get_data()
        cid = data.get('edit_card_id')
        field = data.get('edit_field')
        if not cid or not field:
            await msg.answer("❌ Ошибка!")
            await state.clear()
            return
        value = msg.text.strip()
        if field == 'description' and value.lower() == 'удалить':
            value = ''
        elif field == 'file_id':
            if value.lower() == 'удалить':
                value = ''
            elif msg.photo:
                value = msg.photo[-1].file_id
            else:
                await msg.answer("❌ Отправьте фото или 'удалить'!")
                return
        success = await update_card_field(cid, field, value)
        if success:
            card = await get_card_by_id(cid)
            text = f"✅ Поле '{field}' карты #{cid} обновлено!\n\n{get_card_info_text(card)}"
            await msg.answer(text)
        else:
            await msg.answer("❌ Ошибка обновления!")
        await state.clear()
    
    @dp.message(StateFilter(DeleteCardStates.waiting_for_confirm))
    async def process_delete_card(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            cid = int(msg.text.strip())
            card = await get_card_by_id(cid)
            if not card:
                await msg.answer(f"❌ Карта #{cid} не найдена!")
                await state.clear()
                return
            text = f"⚠️ Вы уверены, что хотите удалить карту?\n\n"
            text += f"📋 #{card['id']} {rarity_emoji(card['rarity'])} {card['name']}\n"
            if card['description']:
                text += f"📝 {card['description']}\n"
            text += f"⭐ {card['rarity']}"
            if card['is_L_card']:
                text += " | 🌟 L-карта"
            if card['is_event_card']:
                text += " | 🎪 Ивент"
            text += f"\n🖼 Фото: {'Есть' if card['file_id'] else 'Нет'}"
            text += f"\n\n❗ Это действие нельзя отменить!\nВсе пользователи потеряют эту карту!"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{cid}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")],
            ])
            await msg.answer(text, reply_markup=kb)
            await state.clear()
        except:
            await msg.answer("❌ Введите корректный ID карты (только число)!")
    
    @dp.message(StateFilter(BreakCustomStates.waiting_for_quantity))
    async def bcm(msg: types.Message, state: FSMContext):
        try:
            q = int(msg.text.strip())
            d = await state.get_data()
            if q < 1 or q > d['mx']:
                await msg.answer(f"❌ 1-{d['mx']}!")
                return
            uc = await get_user_card(msg.from_user.id, d['bcid'])
            if not uc:
                await state.clear()
                return
            price = d.get('break_price', await get_break_price(uc['rarity']))
            total = q * price
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ Да, разбить {q} шт (+{total}💎)", callback_data=f"confirmcustom_{d['bcid']}_{q}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancelbreak_{d['bcid']}")],
            ])
            await msg.answer(f"⚠️ Подтверждение\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: {q} шт.\nЦена за шт: {price}💎\nИтого: {total}💎\n\nТочно разбить?", reply_markup=kb)
            await state.clear()
        except:
            await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(GiveAllStates.waiting_for_amount))
    async def process_giveall(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        data = await state.get_data()
        t = data.get('giveall_type')
        try:
            am = int(msg.text.strip())
            users = await get_all_users()
            for u in users:
                try:
                    if t == 'diamonds':
                        await upd_diamonds(u['user_id'], am)
                    elif t == 'rolls':
                        await upd_rolls(u['user_id'], am)
                    elif t == 'event':
                        await upd_event_rolls(u['user_id'], am)
                    elif t == 'fortune':
                        await upd_fortune_spins(u['user_id'], am)
                except:
                    pass
            await msg.answer(f"✅ {am} для всех!")
            await state.clear()
        except:
            await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(BroadcastStates.waiting_for_broadcast))
    async def process_broadcast(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        users = await get_all_users()
        sent = 0
        for i, u in enumerate(users):
            try:
                await bot.send_message(u['user_id'], msg.text or "📢")
                sent += 1
                if i % 10 == 0:
                    await asyncio.sleep(0.1)
            except:
                pass
        await msg.answer(f"✅ {sent}/{len(users)}")
        await state.clear()
    
    @dp.message(StateFilter(AuctionStates.waiting_for_bid))
    async def bid_msg(msg: types.Message, state: FSMContext):
        try:
            am = int(msg.text.strip())
            d = await state.get_data()
            if await bid_auction(d['aid'], msg.from_user.id, am):
                await msg.answer("✅ Ставка!")
            else:
                await msg.answer("❌")
            await state.clear()
        except:
            await msg.answer("❌ Число!")
    
    @dp.message(StateFilter(PromoStates.waiting_for_code))
    async def promo_code(msg: types.Message, state: FSMContext):
        code = msg.text.strip().upper()
        db = await get_db()
        async with db.execute("SELECT * FROM promocodes WHERE code=? AND uses_left>0", (code,)) as c:
            promo = await c.fetchone()
        if not promo:
            await msg.answer("❌ Недействителен!")
        else:
            if promo['type'] == 'diamonds':
                await upd_diamonds(msg.from_user.id, promo['value'])
            elif promo['type'] == 'rolls':
                await upd_rolls(msg.from_user.id, promo['value'])
            elif promo['type'] == 'event_rolls':
                await upd_event_rolls(msg.from_user.id, promo['value'])
            await db.execute("UPDATE promocodes SET uses_left=uses_left-1 WHERE code=?", (code,))
            await db.commit()
            await msg.answer(f"✅ +{promo['value']} {promo['type']}!")
        await state.clear()
    
    @dp.message(StateFilter(EventStates.waiting_for_deck_name))
    async def deck_name(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        did = await create_deck(msg.text.strip())
        await msg.answer(f"✅ ID:{did}")
        await state.clear()
    
    @dp.message(StateFilter(GiveCardStates.waiting_for_user))
    async def process_give_random_card(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            uid = await resolve_user(msg.text.strip())
            if not uid:
                await msg.answer("❌ Пользователь не найден!")
                return
            data = await state.get_data()
            card_type = data.get('give_card_random', 'any')
            if card_type == 'any':
                cards = await get_all_cards()
            elif card_type == 'SSR':
                all_cards = await get_all_cards()
                cards = [c for c in all_cards if c['rarity'] == 'SSR']
            elif card_type == 'L':
                all_cards = await get_all_cards()
                cards = [c for c in all_cards if c['is_L_card']]
            elif card_type == 'event':
                cards = await get_event_cards()
                if not cards:
                    all_cards = await get_all_cards()
                    cards = [c for c in all_cards if c['is_event_card']]
            else:
                cards = []
            if not cards:
                await msg.answer(f"❌ Нет доступных карт типа {card_type}!")
                await state.clear()
                return
            card = random.choice(cards)
            await add_card_to_user(uid, card['id'], is_original=True)
            user = await get_user(uid)
            type_names = {'any': 'случайная', 'SSR': 'SSR', 'L': 'L', 'event': 'ивент'}
            await msg.answer(f"✅ Выдана {type_names.get(card_type, 'случайная')} карта:\n#{card['id']} {rarity_emoji(card['rarity'])} {card['name']}\nКому: @{user['username']}")
            if card['file_id']:
                try:
                    await bot.send_photo(uid, photo=card['file_id'], caption=f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
                except:
                    await bot.send_message(uid, f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
            else:
                await bot.send_message(uid, f"🎁 Администратор выдал вам карту!\n\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}")
            await state.clear()
        except Exception as e:
            logger.error(f"Ошибка выдачи случайной карты: {e}")
            await msg.answer("❌ Ошибка! Проверьте username.")
            await state.clear()
    
    # ==================== CALLBACK-ОБРАБОТЧИКИ ====================
    @dp.callback_query(F.data == "shop_regular")
    async def shop_reg(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1🎲 - 2💎", callback_data="buy_reg_1")],
            [InlineKeyboardButton(text="5🎲 - 10💎", callback_data="buy_reg_5")],
            [InlineKeyboardButton(text="10🎲 - 50💎", callback_data="buy_reg_10")],
        ])
        await call.message.edit_text("🎲 Обычные:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "shop_event")
    async def shop_evt(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1🎪 - 10💎", callback_data="buy_evt_1")],
            [InlineKeyboardButton(text="5🎪 - 35💎", callback_data="buy_evt_5")],
            [InlineKeyboardButton(text="10🎪 - 70💎", callback_data="buy_evt_10")],
        ])
        await call.message.edit_text("🎪 Ивент:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("buy_reg_"))
    async def buy_reg(call: types.CallbackQuery):
        am = int(call.data.split("_")[2])
        prices = {1: 2, 5: 10, 10: 50}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[am]:
            await call.answer(f"❌ {prices[am]}💎!", show_alert=True)
            return
        await upd_diamonds(call.from_user.id, -prices[am])
        await upd_rolls(call.from_user.id, am)
        await call.answer(f"✅ +{am}🎲!", show_alert=True)
        user = await get_user(call.from_user.id)
        await call.message.answer(f"✅ Куплено {am}🎲 за {prices[am]}💎\n📊 Осталось: 🎲{user['rolls']} | 💎{user['diamonds']}")
    
    @dp.callback_query(F.data.startswith("buy_evt_"))
    async def buy_evt(call: types.CallbackQuery):
        am = int(call.data.split("_")[2])
        prices = {1: 10, 5: 35, 10: 70}
        u = await get_user(call.from_user.id)
        if u['diamonds'] < prices[am]:
            await call.answer(f"❌ {prices[am]}💎!", show_alert=True)
            return
        await upd_diamonds(call.from_user.id, -prices[am])
        await upd_event_rolls(call.from_user.id, am)
        await call.answer(f"✅ +{am}🎪!", show_alert=True)
        user = await get_user(call.from_user.id)
        await call.message.answer(f"✅ Куплено {am}🎪 за {prices[am]}💎\n📊 Осталось: 🎪{user['event_rolls']} | 💎{user['diamonds']}")
    
    @dp.callback_query(F.data == "buy_booster_luck")
    async def bbl(call: types.CallbackQuery):
        if await buy_booster(call.from_user.id, 'luck', 1, 5):
            await call.answer("✅ Активирован!")
        else:
            await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_event")
    async def bbe(call: types.CallbackQuery):
        if await buy_booster(call.from_user.id, 'event', 1, 10):
            await call.answer("✅ Активирован!")
        else:
            await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_booster_break")
    async def bbb(call: types.CallbackQuery):
        if await buy_booster(call.from_user.id, 'break', 1, 3):
            await call.answer("✅ Активирован!")
        else:
            await call.answer("❌ Недостаточно 💎!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("claim_level_"))
    async def claim_level(call: types.CallbackQuery):
        level = int(call.data.split("_")[2])
        reward = await claim_level_reward(call.from_user.id, level)
        if reward:
            desc = " ".join([f"+{v}{'🎲' if k == 'rolls' else '💎' if k == 'diamonds' else '🎪'}" for k, v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else:
            await call.answer("❌ Уже получена!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("cardinfo_"))
    async def card_info(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        card = await get_card_by_id(card_id)
        if not card:
            return
        user = await get_user(call.from_user.id)
        uc = await get_user_card(call.from_user.id, card_id)
        qty = uc['quantity'] if uc else 0
        price = await get_break_price(card['rarity'])
        text = f"{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']:
            text += f"📝 {card['description']}\n"
        text += f"⭐ {card['rarity']} ({price}💎)\n📎 #{card['id']}"
        if card['is_L_card']:
            text += "\n🌟 L-КАРТА!"
        if qty:
            text += f"\n📦 У вас: {qty}"
        kb_buttons = []
        if qty > 1:
            extra = qty - 1 if uc['is_original'] else qty
            kb_buttons.append([
                InlineKeyboardButton(text=f"🔨 +{price}💎 (1 шт)", callback_data=f"breakone_{card_id}"),
                InlineKeyboardButton(text=f"💥 +{extra * price}💎 (все)", callback_data=f"break_{card_id}")
            ])
            kb_buttons.append([InlineKeyboardButton(text="🔢 Своё число...", callback_data=f"breakcustom_{card_id}")])
        if qty:
            if user and user['favorite_card'] == card_id:
                kb_buttons.append([InlineKeyboardButton(text="❤️ Убрать из любимых", callback_data=f"unfav_{card_id}")])
            else:
                kb_buttons.append([InlineKeyboardButton(text="❤️ В любимые", callback_data=f"fav_{card_id}")])
            kb_buttons.append([InlineKeyboardButton(text="💱 Продать", callback_data=f"sellcard_{card_id}")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        try:
            if card['file_id']:
                await call.message.answer_photo(photo=card['file_id'], caption=text, reply_markup=kb)
            else:
                await call.message.answer(text, reply_markup=kb)
        except:
            await call.message.answer(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("fav_"))
    async def set_fav(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        if await set_favorite_card(call.from_user.id, card_id):
            card = await get_card_by_id(card_id)
            await call.answer(f"❤️ {card['name']} теперь любимая!", show_alert=True)
        else:
            await call.answer("❌ У вас нет этой карты!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("unfav_"))
    async def unset_fav(call: types.CallbackQuery):
        await remove_favorite_card(call.from_user.id)
        await call.answer("❤️ Любимая карта убрана", show_alert=True)
    
    @dp.callback_query(F.data.startswith("breakone_"))
    async def bo(call: types.CallbackQuery):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc:
            return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, разбить (+{price}💎)", callback_data=f"confirmbreakone_{cid}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancelbreak_{cid}")],
        ])
        await call.message.answer(f"⚠️ Подтверждение разбития\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: 1 шт.\nЦена: {price}💎\n\nТочно разбить?", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("confirmbreakone_"))
    async def confirm_break_one(call: types.CallbackQuery):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc:
            await call.answer("❌ Карта не найдена!", show_alert=True)
            return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        if await remove_card(call.from_user.id, cid, 1):
            await upd_diamonds(call.from_user.id, price)
            await add_xp(call.from_user.id, 2)
            await update_task_progress(call.from_user.id, 'break')
            await update_weekly_progress(call.from_user.id, 'weekly_break')
            if uc['rarity'] == 'SSR':
                await update_weekly_progress(call.from_user.id, 'weekly_ssr')
            guild = await get_user_guild(call.from_user.id)
            if guild:
                await update_guild_task_progress(guild['id'], call.from_user.id, 'guild_break')
            await call.message.edit_text(f"✅ Разбито!\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: 1 шт.\nПолучено: {price}💎")
            await call.answer(f"✅ +{price}💎!", show_alert=True)
        else:
            await call.answer("❌ Ошибка!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("break_"))
    async def ba(call: types.CallbackQuery):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1:
            return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        bq = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        total = bq * price
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Да, разбить (+{total}💎)", callback_data=f"confirmbreak_{cid}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancelbreak_{cid}")],
        ])
        await call.message.answer(f"⚠️ Подтверждение разбития\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: {bq} шт.\nЦена за шт: {price}💎\nИтого: {total}💎\n\nТочно разбить?", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("confirmbreak_"))
    async def confirm_break(call: types.CallbackQuery):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1:
            await call.answer("❌ Нечего разбивать!", show_alert=True)
            return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        bq = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        total = bq * price
        db = await get_db()
        if uc['is_original']:
            await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
        else:
            await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (call.from_user.id, cid))
        await db.commit()
        await upd_diamonds(call.from_user.id, total)
        for _ in range(bq):
            await add_xp(call.from_user.id, 2)
            await update_task_progress(call.from_user.id, 'break')
            await update_weekly_progress(call.from_user.id, 'weekly_break')
            if uc['rarity'] == 'SSR':
                await update_weekly_progress(call.from_user.id, 'weekly_ssr')
        guild = await get_user_guild(call.from_user.id)
        if guild:
            for _ in range(bq):
                await update_guild_task_progress(guild['id'], call.from_user.id, 'guild_break')
        await call.message.edit_text(f"✅ Разбито!\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: {bq} шт.\nПолучено: {total}💎")
        await call.answer(f"✅ +{total}💎!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("cancelbreak_"))
    async def cancel_break(call: types.CallbackQuery):
        await call.message.edit_text("❌ Разбитие отменено")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("breakcustom_"))
    async def bc(call: types.CallbackQuery, state: FSMContext):
        cid = int(call.data.split("_")[1])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc or uc['quantity'] <= 1:
            return
        mx = uc['quantity'] - 1 if uc['is_original'] else uc['quantity']
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        await state.update_data(bcid=cid, mx=mx, break_price=price)
        await call.message.answer(f"🔢 Сколько разбить? (1-{mx}):\nЦена за шт: {price}💎")
        await state.set_state(BreakCustomStates.waiting_for_quantity)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("confirmcustom_"))
    async def confirm_custom_break(call: types.CallbackQuery):
        parts = call.data.split("_")
        cid = int(parts[1])
        qty = int(parts[2])
        uc = await get_user_card(call.from_user.id, cid)
        if not uc:
            await call.answer("❌ Карта не найдена!", show_alert=True)
            return
        price = await get_break_price(uc['rarity'])
        if await get_booster(call.from_user.id, 'break'):
            price = int(price * 1.5)
        total = qty * price
        if await remove_card(call.from_user.id, cid, qty):
            await upd_diamonds(call.from_user.id, total)
            for _ in range(qty):
                await add_xp(call.from_user.id, 2)
                await update_task_progress(call.from_user.id, 'break')
                await update_weekly_progress(call.from_user.id, 'weekly_break')
                if uc['rarity'] == 'SSR':
                    await update_weekly_progress(call.from_user.id, 'weekly_ssr')
            guild = await get_user_guild(call.from_user.id)
            if guild:
                for _ in range(qty):
                    await update_guild_task_progress(guild['id'], call.from_user.id, 'guild_break')
            await call.message.edit_text(f"✅ Разбито!\n\nКарта: {rarity_emoji(uc['rarity'])} {uc['name']}\nКоличество: {qty} шт.\nПолучено: {total}💎")
            await call.answer(f"✅ +{total}💎!", show_alert=True)
        else:
            await call.answer("❌ Ошибка!", show_alert=True)
    
    @dp.callback_query(F.data == "confirm_break_all")
    async def confirm_break_all(call: types.CallbackQuery):
        cards = await get_user_cards(call.from_user.id)
        total = 0
        broken = 0
        booster = await get_booster(call.from_user.id, 'break')
        guild = await get_user_guild(call.from_user.id)
        for card in cards:
            if card['quantity'] > 1:
                qty = card['quantity'] - 1 if card['is_original'] else card['quantity']
                if qty > 0:
                    price = await get_break_price(card['rarity'])
                    if booster:
                        price = int(price * 1.5)
                    diamonds = qty * price
                    db = await get_db()
                    if card['is_original']:
                        await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", (call.from_user.id, card['id']))
                    else:
                        await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (call.from_user.id, card['id']))
                    await db.commit()
                    total += diamonds
                    broken += qty
                    for _ in range(qty):
                        await add_xp(call.from_user.id, 2)
                        await update_task_progress(call.from_user.id, 'break')
                        await update_weekly_progress(call.from_user.id, 'weekly_break')
                        if card['rarity'] == 'SSR':
                            await update_weekly_progress(call.from_user.id, 'weekly_ssr')
                        if guild:
                            await update_guild_task_progress(guild['id'], call.from_user.id, 'guild_break')
        if broken > 0:
            await upd_diamonds(call.from_user.id, total)
            await call.message.edit_text(f"💥 Разбито {broken} повторов!\n💎 +{total} алмазов!" + ("\n⚡ Бустер!" if booster else ""))
        else:
            await call.message.edit_text("❌ Нет повторов!")
        await call.answer(f"✅ +{total}💎!", show_alert=True)
    
    @dp.callback_query(F.data == "cancel_break_all")
    async def cancel_break_all(call: types.CallbackQuery):
        await call.message.edit_text("❌ Разбитие отменено")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("sellcard_"))
    async def sc(call: types.CallbackQuery):
        await call.message.answer(f"💱 /sell {call.data.split('_')[1]} ЦЕНА")
        await call.answer()
    
    @dp.callback_query(F.data == "market_view")
    async def mv(call: types.CallbackQuery):
        listings = await get_market_listings()
        if not listings:
            await call.message.answer("📋 Пусто")
            await call.answer()
            return
        text = "📋 Лоты:\n\n"
        buttons = []
        for l in listings[:10]:
            text += f"#{l['id']} {rarity_emoji(l['rarity'])} {l['name']} | {l['price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f"{l['price']}💎", callback_data=f"mbuy_{l['id']}")])
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data == "msi")
    async def msi(call: types.CallbackQuery):
        await call.message.answer("/find НОМЕР")
        await call.answer()
    
    @dp.callback_query(F.data == "msi2")
    async def msi2(call: types.CallbackQuery):
        await call.message.answer("/sell НОМЕР ЦЕНА")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("mbuy_"))
    async def mb(call: types.CallbackQuery):
        lid = int(call.data.split("_")[1])
        if await buy_listing(lid, call.from_user.id):
            await call.answer("✅ Куплено!", show_alert=True)
        else:
            await call.answer("❌", show_alert=True)
    
    @dp.callback_query(F.data == "auction_view")
    async def av(call: types.CallbackQuery):
        auctions = await get_active_auctions()
        if not auctions:
            await call.message.answer("📋 Нет")
            await call.answer()
            return
        text = "📋 Аукционы:\n\n"
        buttons = []
        for a in auctions[:10]:
            text += f"#{a['id']} {rarity_emoji(a['rarity'])} {a['name']} | {a['current_price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f">{a['current_price']}💎", callback_data=f"abid_{a['id']}")])
        await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data == "auction_info")
    async def ai(call: types.CallbackQuery):
        await call.message.answer("📊 /auction ID СТАРТ_ЦЕНА")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("abid_"))
    async def abid(call: types.CallbackQuery, state: FSMContext):
        await state.update_data(aid=int(call.data.split("_")[1]))
        await call.message.answer("💰 Сумма:")
        await state.set_state(AuctionStates.waiting_for_bid)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("aduel_"))
    async def ad(call: types.CallbackQuery):
        duel_id = int(call.data.split("_")[1])
        db = await get_db()
        async with db.execute("SELECT * FROM duels WHERE id=? AND status='pending'", (duel_id,)) as c:
            duel = await c.fetchone()
        if not duel:
            await call.answer("❌ Дуэль не найдена!", show_alert=True)
            return
        if duel['opponent_id'] != call.from_user.id:
            await call.answer("❌ Это не ваша дуэль!", show_alert=True)
            return
        await call.message.edit_text(f"⚔️ Дуэль принята! Выбери карту: /pick ID")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("dduel_"))
    async def dd(call: types.CallbackQuery):
        duel_id = int(call.data.split("_")[1])
        db = await get_db()
        await db.execute("UPDATE duels SET status='declined' WHERE id=?", (duel_id,))
        await db.commit()
        async with db.execute("SELECT challenger_id FROM duels WHERE id=?", (duel_id,)) as c:
            row = await c.fetchone()
        if row:
            try:
                await bot.send_message(row[0], f"❌ @{call.from_user.username} отклонил")
            except:
                pass
        await call.message.edit_text("❌ Отклонен")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("accept_rps_"))
    async def accept_rps(call: types.CallbackQuery):
        duel_id = int(call.data.split("_")[2])
        duel = await get_rps_duel(duel_id)
        if not duel:
            await call.answer("❌ Дуэль не найдена!", show_alert=True)
            return
        if duel['opponent_id'] != call.from_user.id:
            await call.answer("❌ Это не ваша дуэль!", show_alert=True)
            return
        challenger = await get_user(duel['challenger_id'])
        await call.message.edit_text(f"✂️ Дуэль КНБ началась!\n\nПротив: @{challenger['username']}\nСтавка: {duel['bet_amount']}💎\n\nИспользуй /rps камень\nДоступно: камень, ножницы, бумага\n\nФормат: лучший из 3 раундов")
        try:
            await bot.send_message(duel['challenger_id'], f"✂️ @{call.from_user.username} принял вызов КНБ!\nИспользуй /rps камень чтобы сделать ход!")
        except:
            pass
        await call.answer()
    
    @dp.callback_query(F.data.startswith("decline_rps_"))
    async def decline_rps(call: types.CallbackQuery):
        duel_id = int(call.data.split("_")[2])
        db = await get_db()
        await db.execute("UPDATE duels SET status='declined' WHERE id=? AND status='pending'", (duel_id,))
        await db.commit()
        async with db.execute("SELECT challenger_id FROM duels WHERE id=?", (duel_id,)) as c:
            row = await c.fetchone()
        if row:
            try:
                await bot.send_message(row[0], f"❌ @{call.from_user.username} отклонил вызов КНБ")
            except:
                pass
        await call.message.edit_text("❌ Вызов отклонён")
        await call.answer()
    
    @dp.callback_query(F.data == "duel_cards_info")
    async def duel_cards_info(call: types.CallbackQuery):
        await call.message.answer("🃏 Дуэль картами:\n\n⚔️ /duel @user ID [ставка]\n📋 Победитель определяется по редкости карты\n⭐ R < SR < SSR < L\n🎲 При равной редкости - по ID карты")
        await call.answer()
    
    @dp.callback_query(F.data == "duel_rps_info")
    async def duel_rps_info(call: types.CallbackQuery):
        await call.message.answer("✂️ Камень-Ножницы-Бумага:\n\n🎯 /rps_duel @user [ставка]\n🔄 Лучший из 3 раундов\n🎮 Ход: /rps камень\n\nДоступные выборы:\n🗿 Камень\n✂️ Ножницы\n📄 Бумага")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("tac_"))
    async def tac(call: types.CallbackQuery):
        p = call.data.split("_")
        fu, fc, tc = int(p[1]), int(p[2]), int(p[3])
        if not await get_user_card(fu, fc) or not await get_user_card(call.from_user.id, tc):
            await call.message.edit_text("❌")
            return
        await remove_card(fu, fc)
        await remove_card(call.from_user.id, tc)
        await add_card_to_user(call.from_user.id, fc)
        await add_card_to_user(fu, tc)
        await call.message.edit_text("✅!")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("tdc_"))
    async def tdc(call: types.CallbackQuery):
        await call.message.edit_text("❌")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("claim_ach_"))
    async def claim_ach(call: types.CallbackQuery):
        ach_id = call.data.split("_", 2)[2]
        reward = await claim_achievement_reward(call.from_user.id, ach_id)
        if reward:
            desc = " ".join([f"+{v}{'💎' if k == 'diamonds' else '🎲' if k == 'rolls' else '🎪'}" for k, v in reward.items()])
            await call.answer(f"✅ {desc}!", show_alert=True)
        else:
            await call.answer("❌ Уже получена!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("confirm_guild_reward_"))
    async def confirm_guild_reward(call: types.CallbackQuery):
        guild_id = int(call.data.split("_")[3])
        success, status = await claim_guild_reward(guild_id, call.from_user.id)
        if success:
            await call.message.edit_text("✅ Награда получена!\n\n🏆 Вы получили:\n💎 +7 алмазов\n🎪 +3 ивент-крутки")
            await call.answer("🎉 Награда получена!", show_alert=True)
        elif status == "already_claimed":
            await call.message.edit_text("❌ Вы уже получили награду!")
            await call.answer("Уже получено!", show_alert=True)
        elif status == "no_contribution":
            await call.message.edit_text("❌ Вы не внесли вклад в задания гильдии!")
            await call.answer("Нет вклада!", show_alert=True)
        else:
            await call.message.edit_text("❌ Задания ещё не выполнены!")
            await call.answer("Не выполнены!", show_alert=True)
    
    @dp.callback_query(F.data == "cancel_guild_reward")
    async def cancel_guild_reward(call: types.CallbackQuery):
        await call.message.edit_text("❌ Получение награды отменено")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("guild_tasks_"))
    async def show_guild_tasks(call: types.CallbackQuery):
        guild_id = int(call.data.split("_")[2])
        guild = await get_user_guild(call.from_user.id)
        if not guild or guild['id'] != guild_id:
            await call.answer("❌ Вы не в этой гильдии!", show_alert=True)
            return
        tasks = await get_guild_tasks(guild_id)
        if not tasks:
            await call.message.answer("📋 Нет заданий на эту неделю")
            await call.answer()
            return
        text = "📋 Задания гильдии:\n\n"
        names = {t['type']: t['desc'] for t in GUILD_TASK_TYPES}
        all_completed = True
        for t in tasks:
            st = "✅" if t['completed'] else "⬜"
            text += f"{st} {names.get(t['task_type'], t['task_type'])} ({t['progress']}/{t['task_target']})\n"
            if not t['completed']:
                all_completed = False
        total_members, claimed = await get_guild_claim_stats(guild_id)
        text += f"\n👥 Участников: {total_members}\n🎁 Забрали награду: {claimed}/{total_members}\n"
        if all_completed:
            can_claim, msg_text = await can_claim_guild_reward(guild_id, call.from_user.id)
            if can_claim:
                text += "\n🌟 Вы можете забрать награду!\n/claim_guild_reward"
            else:
                text += f"\n❌ {msg_text}"
        today = datetime.now()
        ws = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        db = await get_db()
        async with db.execute("SELECT SUM(gtc.progress) as my_progress FROM guild_task_contributions gtc JOIN guild_tasks gt ON gtc.guild_task_id = gt.id WHERE gt.guild_id = ? AND gt.week_start = ? AND gtc.user_id = ?", (guild_id, ws, call.from_user.id)) as c:
            row = await c.fetchone()
            my_progress = row['my_progress'] if row and row['my_progress'] else 0
        text += f"\n📊 Ваш вклад: {my_progress} очков"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"guild_tasks_{guild_id}")],
            [InlineKeyboardButton(text="🏆 Топ участников", callback_data=f"guild_top_{guild_id}")],
        ])
        await call.message.answer(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("guild_top_"))
    async def show_guild_top(call: types.CallbackQuery):
        guild_id = int(call.data.split("_")[2])
        guild = await get_user_guild(call.from_user.id)
        if not guild or guild['id'] != guild_id:
            await call.answer("❌ Вы не в этой гильдии!", show_alert=True)
            return
        top = await get_guild_task_contributions(guild_id)
        if not top:
            await call.message.answer("🏆 Нет данных о вкладе")
            await call.answer()
            return
        text = "🏆 Топ участников по вкладу:\n\n"
        for i, u in enumerate(top, 1):
            medal = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f'{i}.'
            text += f"{medal} @{u['username']} - {u['total_progress']} очков\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"guild_top_{guild_id}")],
        ])
        await call.message.answer(text, reply_markup=kb)
        await call.answer()
    
    # Админские callback
    @dp.callback_query(F.data == "admin_add")
    async def aas(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(is_event=False)
        await call.message.answer("📝 Шаг 1/4\nВведи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_edit_card")
    async def admin_edit_card(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("✏️ Введите ID карты для редактирования:\n/editcard ID")
        await call.answer()
    
    @dp.callback_query(F.data == "admin_delete_card")
    async def admin_delete_card(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(DeleteCardStates.waiting_for_confirm)
        await call.message.answer("🗑 Введите ID карты для удаления:")
        await call.answer()
    
    @dp.callback_query(F.data == "admin_list")
    async def alc(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        cards = await get_all_cards()
        if not cards:
            await call.message.answer("📋 Нет")
            await call.answer()
            return
        text = "📋 Карты:\n\n"
        for c in cards:
            text += f"#{c['id']} {rarity_emoji(c['rarity'])} {c['name']}\n"
        for i in range(0, len(text), 4000):
            await call.message.answer(text[i:i+4000])
        await call.answer()
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def agm(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="gd")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="gr")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="ge")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("🎁 Выдача:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_take_menu")
    async def admin_take_menu(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="take_diamonds")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="take_rolls")],
            [InlineKeyboardButton(text="🎪 Ивент", callback_data="take_event")],
            [InlineKeyboardButton(text="🃏 Карту", callback_data="take_card")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("➖ Забрать:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_give_card_menu")
    async def admin_give_card_menu(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎴 Конкретную карту", callback_data="give_specific_card")],
            [InlineKeyboardButton(text="🎲 Случайную карту", callback_data="give_random_card")],
            [InlineKeyboardButton(text="🌟 Случайную SSR", callback_data="give_random_ssr")],
            [InlineKeyboardButton(text="💫 Случайную L", callback_data="give_random_l")],
            [InlineKeyboardButton(text="🎪 Случайную ивент", callback_data="give_random_event")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("🃏 Выдать карту:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "give_specific_card")
    async def give_specific_card(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("🎴 Введите:\n/givecard @user ID_карты")
        await call.answer()
    
    @dp.callback_query(F.data == "give_random_card")
    async def give_random_card_btn(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveCardStates.waiting_for_user)
        await state.update_data(give_card_random='any')
        await call.message.answer("🎲 Введите @username кому выдать случайную карту:")
        await call.answer()
    
    @dp.callback_query(F.data == "give_random_ssr")
    async def give_random_ssr_btn(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveCardStates.waiting_for_user)
        await state.update_data(give_card_random='SSR')
        await call.message.answer("🌟 Введите @username кому выдать случайную SSR:")
        await call.answer()
    
    @dp.callback_query(F.data == "give_random_l")
    async def give_random_l_btn(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveCardStates.waiting_for_user)
        await state.update_data(give_card_random='L')
        await call.message.answer("💫 Введите @username кому выдать случайную L-карту:")
        await call.answer()
    
    @dp.callback_query(F.data == "give_random_event")
    async def give_random_event_btn(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveCardStates.waiting_for_user)
        await state.update_data(give_card_random='event')
        await call.message.answer("🎪 Введите @username кому выдать случайную ивент-карту:")
        await call.answer()
    
    @dp.callback_query(F.data == "take_diamonds")
    async def take_diamonds_btn(call: types.CallbackQuery):
        await call.message.answer("/takediamonds @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "take_rolls")
    async def take_rolls_btn(call: types.CallbackQuery):
        await call.message.answer("/takerolls @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "take_event")
    async def take_event_btn(call: types.CallbackQuery):
        await call.message.answer("/takeevent @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "take_card")
    async def take_card_btn(call: types.CallbackQuery):
        await call.message.answer("/takecard @user ID_карты [кол-во]")
        await call.answer()
    
    @dp.callback_query(F.data == "admin_give_all")
    async def admin_give_all(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Всем алмазы", callback_data="giveall_diamonds")],
            [InlineKeyboardButton(text="🎲 Всем крутки", callback_data="giveall_rolls")],
            [InlineKeyboardButton(text="🎪 Всем ивент", callback_data="giveall_event")],
            [InlineKeyboardButton(text="🎡 Всем колесо", callback_data="giveall_fortune")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("👥 Всем:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_broadcast")
    async def abr(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("📢 Сообщение:")
        await state.set_state(BroadcastStates.waiting_for_broadcast)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_ban")
    async def ab(call: types.CallbackQuery):
        await call.message.answer("/ban @user | /unban @user")
        await call.answer()
    
    @dp.callback_query(F.data == "admin_event_menu")
    async def admin_event_menu(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📁 Создать колоду", callback_data="event_create_deck")],
            [InlineKeyboardButton(text="➕ В колоду", callback_data="event_add_to_deck_menu")],
            [InlineKeyboardButton(text="▶️ Запустить", callback_data="event_start")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="event_end")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("🎪 Ивенты:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_war_menu")
    async def awm(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Начать", callback_data="war_start")],
            [InlineKeyboardButton(text="⚔️ Битвы", callback_data="war_battles")],
            [InlineKeyboardButton(text="⏹ Завершить", callback_data="war_end")],
            [InlineKeyboardButton(text="🏆 Награды", callback_data="war_reward")],
            [InlineKeyboardButton(text="🔙", callback_data="admin_back")],
        ])
        await call.message.edit_text("⚔️ Война:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "admin_settings")
    async def admin_settings(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.edit_text("⚙️ /set_rate R 70\n/set_guarantor 50\n/set_break_R 1\n/set_morning_rolls 2\n/show_settings", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="🔙", callback_data="admin_back")]]))
        await call.answer()
    
    @dp.callback_query(F.data == "admin_backup")
    async def admin_backup_info(call: types.CallbackQuery):
        await call.message.answer("💾 /backup - скачать\n/restore - восстановить\n/check_db - проверить\n/userscount - статистика")
        await call.answer()
    
    @dp.callback_query(F.data == "admin_back")
    async def admin_back(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Карта", callback_data="admin_add")],
            [InlineKeyboardButton(text="✏️ Изменить карту", callback_data="admin_edit_card")],
            [InlineKeyboardButton(text="🗑 Удалить карту", callback_data="admin_delete_card")],
            [InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать", callback_data="admin_give_menu")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_take_menu")],
            [InlineKeyboardButton(text="🃏 Выдать карту", callback_data="admin_give_card_menu")],
            [InlineKeyboardButton(text="👥 Всем", callback_data="admin_give_all")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="⛔ Бан", callback_data="admin_ban")],
            [InlineKeyboardButton(text="🎪 Ивенты", callback_data="admin_event_menu")],
            [InlineKeyboardButton(text="⚔️ Война", callback_data="admin_war_menu")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
            [InlineKeyboardButton(text="💾 Бекап", callback_data="admin_backup")],
        ])
        await call.message.edit_text("👑 Админ-панель", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "gd")
    async def gd(call: types.CallbackQuery):
        await call.message.answer("/givediamonds @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "gr")
    async def gr(call: types.CallbackQuery):
        await call.message.answer("/giverolls @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "ge")
    async def ge(call: types.CallbackQuery):
        await call.message.answer("/giveevent @user кол-во")
        await call.answer()
    
    @dp.callback_query(F.data == "giveall_diamonds")
    async def gald(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveAllStates.waiting_for_amount)
        await state.update_data(giveall_type='diamonds')
        await call.message.answer("💎 Сколько?")
        await call.answer()
    
    @dp.callback_query(F.data == "giveall_rolls")
    async def galr(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveAllStates.waiting_for_amount)
        await state.update_data(giveall_type='rolls')
        await call.message.answer("🎲 Сколько?")
        await call.answer()
    
    @dp.callback_query(F.data == "giveall_event")
    async def gale(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveAllStates.waiting_for_amount)
        await state.update_data(giveall_type='event')
        await call.message.answer("🎪 Сколько?")
        await call.answer()
    
    @dp.callback_query(F.data == "giveall_fortune")
    async def galf(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.set_state(GiveAllStates.waiting_for_amount)
        await state.update_data(giveall_type='fortune')
        await call.message.answer("🎡 Сколько?")
        await call.answer()
    
    @dp.callback_query(F.data == "event_create_deck")
    async def ecd(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("📁 Название:")
        await state.set_state(EventStates.waiting_for_deck_name)
        await call.answer()
    
    @dp.callback_query(F.data == "event_add_to_deck_menu")
    async def eatdm(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        decks = await get_all_decks()
        if not decks:
            await call.message.answer("❌ Нет колод!")
            await call.answer()
            return
        buttons = [[InlineKeyboardButton(text=f"📁 {d['name']}", callback_data=f"addtodeck_{d['id']}")] for d in decks]
        await call.message.answer("Выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data.startswith("addtodeck_"))
    async def atd(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(current_deck_id=int(call.data.split("_")[1]), is_event=True)
        await call.message.answer("📝 Введи #НОМЕР ИМЯ")
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    @dp.callback_query(F.data == "event_start")
    async def es(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        decks = await get_all_decks()
        if not decks:
            await call.message.answer("❌")
            await call.answer()
            return
        buttons = [[InlineKeyboardButton(text=f"📁 {d['name']}", callback_data=f"startev_{d['id']}")] for d in decks]
        await call.message.answer("▶️ Выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await call.answer()
    
    @dp.callback_query(F.data.startswith("startev_"))
    async def se(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        did = int(call.data.split("_")[1])
        await start_event(did)
        await call.message.answer("✅ Запущен!")
        await call.answer()
    
    @dp.callback_query(F.data == "event_end")
    async def ee(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="confirm_end_event")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="admin_event_menu")],
        ])
        await call.message.answer("⏹ Завершить?", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "confirm_end_event")
    async def cee(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        await end_current_event()
        await call.message.answer("✅ Завершён!")
        await call.answer()
    
    @dp.callback_query(F.data == "war_start")
    async def ws_btn(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        sid = await start_war_season()
        await call.message.answer(f"✅ Сезон #{sid}!")
        await call.answer()
    
    @dp.callback_query(F.data == "war_battles")
    async def wb_btn(call: types.CallbackQuery):
        season = await get_active_war_season()
        if season:
            await start_war_battles(season['id'])
            await call.message.answer("⚔️ Битвы!")
        await call.answer()
    
    @dp.callback_query(F.data == "war_end")
    async def we_btn(call: types.CallbackQuery):
        await end_current_war()
        await call.message.answer("⏹ Завершена!")
        await call.answer()
    
    @dp.callback_query(F.data == "war_reward")
    async def wr_btn(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        db = await get_db()
        async with db.execute("SELECT * FROM guild_war_seasons WHERE status='ended' ORDER BY id DESC LIMIT 1") as c:
            last = await c.fetchone()
        if not last:
            await call.message.answer("❌ Нет сезонов!")
            await call.answer()
            return
        ranking = await get_guild_war_ranking(last['id'])
        if not ranking:
            await call.message.answer("❌ Нет данных!")
            await call.answer()
            return
        text = "🏆 Награды:\n\n"
        rewards = [(100, 10, 5), (70, 7, 3), (50, 5, 2), (30, 3, 1), (15, 1, 0)]
        for i, g in enumerate(ranking[:5]):
            if i < len(rewards):
                r = rewards[i]
                text += f"{['🥇','🥈','🥉'][i] if i < 3 else f'{i+1}.'} {g['name']}: 💎{r[0]} 🎲{r[1]} 🎪{r[2]}\n"
                async with db.execute("SELECT user_id FROM guild_members WHERE guild_id=?", (g['id'],)) as c:
                    async for m in c:
                        await upd_diamonds(m[0], r[0])
                        await upd_rolls(m[0], r[1])
                        await upd_event_rolls(m[0], r[2])
        await call.message.answer(text)
        await call.answer()
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def ar(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(rarity=call.data.split("_")[1])
        await call.message.answer("📝 Шаг 4/4\nОтправь фото или 'нет'")
        await state.set_state(AddCardStates.waiting_for_photo)
        await call.answer()
    
    # Callback для редактирования карт
    @dp.callback_query(F.data.startswith("edit_name_"))
    async def edit_name(call: types.CallbackQuery, state: FSMContext):
        cid = int(call.data.split("_")[2])
        await state.update_data(edit_card_id=cid, edit_field='name')
        await call.message.answer("📝 Введите новое название карты:")
        await state.set_state(EditCardStates.waiting_for_new_value)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("edit_desc_"))
    async def edit_desc(call: types.CallbackQuery, state: FSMContext):
        cid = int(call.data.split("_")[2])
        await state.update_data(edit_card_id=cid, edit_field='description')
        await call.message.answer("📄 Введите новое описание карты (или 'удалить' чтобы очистить):")
        await state.set_state(EditCardStates.waiting_for_new_value)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("edit_rarity_"))
    async def edit_rarity(call: types.CallbackQuery):
        cid = int(call.data.split("_")[2])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="R - Обычная", callback_data=f"setrarity_{cid}_R")],
            [InlineKeyboardButton(text="SR - Редкая", callback_data=f"setrarity_{cid}_SR")],
            [InlineKeyboardButton(text="SSR - Эпическая", callback_data=f"setrarity_{cid}_SSR")],
            [InlineKeyboardButton(text="🌟 L - Легендарная", callback_data=f"setrarity_{cid}_L")],
        ])
        await call.message.answer("⭐ Выберите новую редкость:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("setrarity_"))
    async def set_rarity(call: types.CallbackQuery):
        parts = call.data.split("_")
        cid = int(parts[1])
        rarity = parts[2]
        await update_card_field(cid, 'rarity', rarity)
        if rarity == 'L':
            await update_card_field(cid, 'is_L_card', 1)
        card = await get_card_by_id(cid)
        text = f"✅ Редкость карты #{cid} изменена на {rarity_emoji(rarity)} {rarity}\n\n{get_card_info_text(card)}"
        await call.message.edit_text(text)
        await call.answer(f"✅ Редкость изменена!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("edit_isl_"))
    async def edit_isl(call: types.CallbackQuery):
        cid = int(call.data.split("_")[2])
        card = await get_card_by_id(cid)
        new_val = 0 if card['is_L_card'] else 1
        await update_card_field(cid, 'is_L_card', new_val)
        if new_val:
            await update_card_field(cid, 'rarity', 'L')
        card = await get_card_by_id(cid)
        text = f"✅ L-статус карты #{cid} изменён\n\n{get_card_info_text(card)}"
        await call.message.edit_text(text)
        await call.answer(f"✅ L-статус: {'Да' if new_val else 'Нет'}!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("edit_event_"))
    async def edit_event(call: types.CallbackQuery):
        cid = int(call.data.split("_")[2])
        card = await get_card_by_id(cid)
        new_val = 0 if card['is_event_card'] else 1
        await update_card_field(cid, 'is_event_card', new_val)
        card = await get_card_by_id(cid)
        text = f"✅ Статус ивент-карты #{cid} изменён\n\n{get_card_info_text(card)}"
        await call.message.edit_text(text)
        await call.answer(f"✅ Ивент-карта: {'Да' if new_val else 'Нет'}!", show_alert=True)
    
    @dp.callback_query(F.data.startswith("edit_photo_"))
    async def edit_photo(call: types.CallbackQuery, state: FSMContext):
        cid = int(call.data.split("_")[2])
        await state.update_data(edit_card_id=cid, edit_field='file_id')
        await call.message.answer("🖼 Отправьте новое фото для карты (или 'удалить' чтобы убрать):")
        await state.set_state(EditCardStates.waiting_for_new_value)
        await call.answer()
    
    @dp.callback_query(F.data == "edit_cancel")
    async def edit_cancel(call: types.CallbackQuery):
        await call.message.edit_text("❌ Редактирование отменено")
        await call.answer()
    
    @dp.callback_query(F.data.startswith("confirm_delete_"))
    async def confirm_delete_card(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        cid = int(call.data.split("_")[2])
        card = await get_card_by_id(cid)
        if not card:
            await call.message.edit_text("❌ Карта не найдена!")
            await call.answer()
            return
        await delete_card_completely(cid)
        await call.message.edit_text(f"✅ Карта #{cid} {rarity_emoji(card['rarity'])} {card['name']} успешно удалена!\n\nУдалена у всех пользователей, с биржи и аукционов.")
        await call.answer(f"✅ Карта #{cid} удалена!", show_alert=True)
    
    @dp.callback_query(F.data == "cancel_delete")
    async def cancel_delete_card(call: types.CallbackQuery):
        await call.message.edit_text("❌ Удаление отменено")
        await call.answer()
    
    # ==================== ДУЭЛИ ====================
    async def resolve_duel(duel):
        try:
            cc = await get_card_by_id(duel['challenger_card_id'])
            oc = await get_card_by_id(duel['opponent_card_id'])
            if not cc or not oc:
                logger.error(f"Дуэль #{duel['id']}: карты не найдены")
                return
            rp = {'R': 1, 'SR': 2, 'SSR': 3, 'L': 4}
            cp, op = rp.get(cc['rarity'], 0), rp.get(oc['rarity'], 0)
            if cp > op:
                wid = duel['challenger_id']
            elif op > cp:
                wid = duel['opponent_id']
            else:
                wid = duel['challenger_id'] if cc['id'] > oc['id'] else duel['opponent_id']
            lid = duel['opponent_id'] if wid == duel['challenger_id'] else duel['challenger_id']
            await upd_diamonds(wid, duel['bet_amount'])
            await upd_diamonds(lid, -duel['bet_amount'])
            await add_xp(wid, 15)
            await add_xp(lid, 5)
            await update_duel_stats(wid, True)
            await update_duel_stats(lid, False)
            db = await get_db()
            await db.execute("UPDATE duels SET status='done', winner_id=? WHERE id=? AND status='pending'", (wid, duel['id']))
            await db.commit()
            guild = await get_user_guild(wid)
            if guild:
                await update_guild_task_progress(guild['id'], wid, 'guild_duels')
            winner = await get_user(wid)
            for uid in [duel['challenger_id'], duel['opponent_id']]:
                try:
                    await bot.send_message(uid, f"⚔️ Дуэль завершена!\nПобедитель: @{winner['username']}\nПриз: {duel['bet_amount']}💎")
                except Exception as e:
                    logger.error(f"Не удалось отправить результат дуэли пользователю {uid}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при разрешении дуэли #{duel['id']}: {e}")
            db = await get_db()
            await db.execute("UPDATE duels SET status='error' WHERE id=?", (duel['id'],))
            await db.commit()
    
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(morning_bonus, 'cron', hour=7, minute=0)
    scheduler.add_job(evening_bonus, 'cron', hour=17, minute=0)
    scheduler.add_job(finish_auctions, 'interval', minutes=10)
    scheduler.start()
    
    # Веб-сервер для Railway
    async def health_check(request):
        return web.Response(text="OK")
    
    app_web = web.Application()
    app_web.router.add_get("/", health_check)
    runner = web.AppRunner(app_web)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        if db_conn:
            await db_conn.close()
            logger.info("📦 Соединение с БД закрыто")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
