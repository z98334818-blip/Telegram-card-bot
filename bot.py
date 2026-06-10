import asyncio
import aiosqlite
import random
import logging
import sys
from datetime import datetime
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

# Конфиг
from config import BOT_TOKEN, ADMIN_IDS, DB_PATH

# Логирование
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                rolls INTEGER DEFAULT 2,
                diamonds INTEGER DEFAULT 0,
                total_rolls INTEGER DEFAULT 0,
                guarantor_progress INTEGER DEFAULT 0,
                fortune_spins INTEGER DEFAULT 1,
                bonus_roll_received BOOLEAN DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT DEFAULT '',
                file_id TEXT,
                rarity TEXT DEFAULT 'R',
                is_L_card BOOLEAN DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id INTEGER,
                card_id INTEGER,
                quantity INTEGER DEFAULT 1,
                is_original BOOLEAN DEFAULT 1,
                PRIMARY KEY (user_id, card_id)
            )
        """)
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                achievement_id TEXT,
                completed BOOLEAN DEFAULT 0,
                PRIMARY KEY (user_id, achievement_id)
            )
        """)
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
        await db.commit()
        logger.info("✅ База данных готова")

# ==================== СОСТОЯНИЯ FSM ====================
class AddCardStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_rarity = State()
    waiting_for_photo = State()

# ==================== ФУНКЦИИ БД ====================
async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as c:
            return await c.fetchone()

async def create_user(uid, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id,username) VALUES (?,?)", (uid, name))
        await db.commit()

async def get_all_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards ORDER BY id") as c:
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

async def upd_guarantor(uid, progress):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET guarantor_progress=? WHERE user_id=?", (progress, uid))
        await db.commit()

async def upd_fortune_spins(uid, spins):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET fortune_spins=? WHERE user_id=?", (spins, uid))
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
        if not row:
            return False, "Карта не найдена"
        current_qty, is_original = row[0], row[1]
        if is_original and current_qty <= qty:
            return False, "❌ Нельзя удалить оригинал карты!"
        if current_qty >= qty:
            new_qty = current_qty - qty
            if new_qty <= 0:
                await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
            else:
                await db.execute("UPDATE user_cards SET quantity=? WHERE user_id=? AND card_id=?", (new_qty, uid, cid))
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

# ==================== ЗАДАНИЯ ====================
TASK_TYPES = [
    {"type": "roll", "desc": "🎲 Прокрутить один раз", "target": 1},
    {"type": "profile", "desc": "👤 Зайти в профиль", "target": 1},
    {"type": "break", "desc": "🔨 Разбить повторку", "target": 1},
    {"type": "fortune", "desc": "🎡 Крутануть колесо", "target": 1},
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
                        (uid, i, task['type'], task['target'], today)
                    )
                await db.commit()

async def get_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    await ensure_daily_tasks(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_tasks WHERE user_id=? AND date=?", (uid, today)) as c:
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

async def check_all_tasks_completed(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) as total, SUM(completed) as done FROM daily_tasks WHERE user_id=? AND date=?",
            (uid, today)
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
]

async def check_achievements(uid):
    user = await get_user(uid)
    cards = await get_user_cards(uid)
    total_cards = sum(c['quantity'] for c in cards)
    l_cards = sum(c['quantity'] for c in cards if c['is_L_card'])
    new_achievements = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            if ach['id'] == 'cards_10' and total_cards >= 10: completed = True
            elif ach['id'] == 'cards_50' and total_cards >= 50: completed = True
            elif ach['id'] == 'cards_100' and total_cards >= 100: completed = True
            elif ach['id'] == 'rolls_100' and user['total_rolls'] >= 100: completed = True
            elif ach['id'] == 'l_cards_1' and l_cards >= 1: completed = True
            else: continue
            async with db.execute(
                "SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (uid, ach['id'])
            ) as c:
                row = await c.fetchone()
                if not row or not row[0]:
                    await db.execute(
                        "INSERT OR REPLACE INTO achievements (user_id, achievement_id, completed) VALUES (?,?,1)",
                        (uid, ach['id'])
                    )
                    await db.commit()
                    new_achievements.append(ach)
    return new_achievements

# ==================== БИРЖА ====================
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
        if buyer['diamonds'] < listing['price']: return False, f"Недостаточно алмазов! Нужно {listing['price']}💎"
        await upd_diamonds(buyer_id, -listing['price'])
        await upd_diamonds(listing['seller_id'], listing['price'])
        await add_card_to_user(buyer_id, listing['card_id'])
        if listing['quantity'] > 1:
            await db.execute("UPDATE market SET quantity=quantity-1 WHERE id=?", (listing_id,))
        else:
            await db.execute("DELETE FROM market WHERE id=?", (listing_id,))
        await db.commit()
        return True, "Покупка успешна"

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
            [KeyboardButton(text="🎡 Колесо фортуны"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="📋 Задания")],
            [KeyboardButton(text="💱 Биржа"), KeyboardButton(text="🔄 Обмен")],
            [KeyboardButton(text="🏆 Лидеры"), KeyboardButton(text="🏅 Достижения")],
            [KeyboardButton(text="❓ Помощь")],
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
    
    # ==================== /start ====================
    @dp.message(CommandStart())
    async def start(msg: types.Message):
        await create_user(msg.from_user.id, msg.from_user.username or "Аноним")
        text = (
            "✨ Приветствую тебя путник в великолепном боте с женщинами визуальных новелл! ✨\n\n"
            "🎲 Каждый день в 8:00 МСК:\n"
            "• +2 крутки и +2💎\n"
            "• +1 вращение колеса 🎡\n"
            "• +2 новых задания 📋\n\n"
            "💱 Обменивайся и торгуй с другими игроками!"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== КРУТКА ====================
    async def perform_roll(uid, is_premium=False):
        u = await get_user(uid)
        cards = await get_all_cards()
        if not cards:
            return None, "В базе нет карт"
        progress = u['guarantor_progress']
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        is_guaranteed = progress >= 90
        guarantee_text = ""
        if is_guaranteed and L_cards:
            card = random.choice(L_cards)
            await upd_guarantor(uid, 0)
            guarantee_text = "🎉 ГАРАНТ! "
            progress = 0
        else:
            if L_cards and random.random() < 0.01:
                card = random.choice(L_cards)
                await upd_guarantor(uid, 0)
                guarantee_text = "🌟 L-КАРТА! "
                progress = 0
            else:
                card = random.choice(normal if normal else cards)
                if not is_premium:
                    progress += 1
                    await upd_guarantor(uid, progress)
        await add_card_to_user(uid, card['id'], is_original=True)
        caption = f"{guarantee_text}{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']: caption += f"📝 {card['description']}\n"
        caption += f"⭐ {card['rarity']}\n📎 #{card['id']}\n📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        return card, caption
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u: return
        if u['rolls'] <= 0:
            await msg.answer("❌ Нет круток!", reply_markup=permanent_keyboard())
            return
        await upd_rolls(msg.from_user.id, -1)
        card, caption = await perform_roll(msg.from_user.id)
        if card is None:
            await msg.answer(caption, reply_markup=permanent_keyboard())
            return
        await update_task_progress(msg.from_user.id, 'roll')
        achievements = await check_achievements(msg.from_user.id)
        try:
            if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption=caption)
            else: await msg.answer(caption)
        except: await msg.answer(caption)
        if achievements:
            for ach in achievements: await msg.answer(f"🏅 ДОСТИЖЕНИЕ!\n{ach['icon']} {ach['name']}: {ach['desc']}")
        if await check_all_tasks_completed(msg.from_user.id):
            bonus = await give_bonus_roll(msg.from_user.id)
            if bonus: await msg.answer("🎉 Все задания выполнены! +1 бонусная крутка! Забери в 📋 Заданиях")
    
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5:
            await msg.answer("❌ Нужно 5💎!", reply_markup=permanent_keyboard())
            return
        await upd_diamonds(msg.from_user.id, -5)
        card, caption = await perform_roll(msg.from_user.id, is_premium=True)
        if card is None: return
        try:
            if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption="💎 Премиум!\n" + caption)
            else: await msg.answer("💎 Премиум!\n" + caption)
        except: await msg.answer("💎 Премиум!\n" + caption)
    
    # ==================== КОЛЕСО ФОРТУНЫ ====================
    async def spin_fortune(msg):
        prizes = []
        for p in FORTUNE_PRIZES: prizes.extend([p] * p['weight'])
        prize = random.choice(prizes)
        card = None
        if prize['prize'] == 'roll': await upd_rolls(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'diamond': await upd_diamonds(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_all_cards()
            if cards:
                card = random.choice(cards)
                await add_card_to_user(msg.from_user.id, card['id'], is_original=True)
            else: prize = {"prize": "nothing", "value": 0, "desc": "❌ Ничего (нет карт)"}
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] > 0: await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
        await update_task_progress(msg.from_user.id, 'fortune')
        if card and prize['prize'] == 'random_card':
            caption = f"🎡 Колесо фортуны!\n\n🎴 Выпала карта!\n{rarity_emoji(card['rarity'])} {card['name']}\n"
            if card['description']: caption += f"📝 {card['description']}\n"
            caption += f"⭐ {card['rarity']}\n📎 #{card['id']}"
            try:
                if card['file_id']: await msg.answer_photo(photo=card['file_id'], caption=caption)
                else: await msg.answer(caption)
            except: await msg.answer(caption)
        else: await msg.answer(f"🎡 Колесо фортуны!\n\n{prize['desc']}")
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вращение - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вращений - 3💎", callback_data="fortune_buy_5")],
                [InlineKeyboardButton(text="🎡 10 вращений - 5💎", callback_data="fortune_buy_10")],
            ])
            await msg.answer("🎡 Бесплатные вращения закончились!\nМожно купить:", reply_markup=kb)
        else:
            await msg.answer(f"🎡 Крутим колесо! Бесплатных вращений: {u['fortune_spins']}")
            await spin_fortune(msg)
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call: types.CallbackQuery):
        amount = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3, 10: 5}
        price = prices[amount]
        u = await get_user(call.from_user.id)
        if u['diamonds'] < price:
            await call.answer(f"❌ Нужно {price}💎!", show_alert=True)
            return
        await upd_diamonds(call.from_user.id, -price)
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + amount)
        await call.answer(f"✅ +{amount} вращений!", show_alert=True)
        for i in range(amount): await spin_fortune(call.message)
    
    # ==================== ПРОФИЛЬ ====================
    @dp.message(F.text == "👤 Профиль")
    async def profile_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u: return
        cards = await get_card_count(msg.from_user.id)
        progress = u['guarantor_progress']
        text = (
            f"👤 Профиль\n\n📛 {u['username']}\n💎 Алмазы: {u['diamonds']}\n🎲 Крутки: {u['rolls']}\n"
            f"🎴 Карт: {cards}\n🔄 Круток: {u['total_rolls']}\n🎡 Колесо: {u['fortune_spins']}\n"
            f"📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        )
        await update_task_progress(msg.from_user.id, 'profile')
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить крутки", callback_data="buy_rolls_menu")],
        ])
        await msg.answer(text, reply_markup=kb)
    
    @dp.callback_query(F.data == "buy_rolls_menu")
    async def buy_rolls(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 крутка - 5💎", callback_data="buy_1")],
            [InlineKeyboardButton(text="5 круток - 20💎", callback_data="buy_5")],
            [InlineKeyboardButton(text="10 круток - 35💎", callback_data="buy_10")],
        ])
        await call.message.answer("💎 Покупка круток:", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data.startswith("buy_"))
    async def process_buy(call: types.CallbackQuery):
        amount = int(call.data.split("_")[1])
        prices = {1: 5, 5: 20, 10: 35}
        price = prices[amount]
        u = await get_user(call.from_user.id)
        if u['diamonds'] < price:
            await call.answer(f"❌ Нужно {price}💎!", show_alert=True)
            return
        await upd_diamonds(call.from_user.id, -price)
        await upd_rolls(call.from_user.id, amount)
        await call.answer(f"✅ +{amount} круток!", show_alert=True)
    
    # ==================== ИНВЕНТАРЬ ====================
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_button(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        if not cards:
            await msg.answer("🎒 Инвентарь пуст", reply_markup=permanent_keyboard())
            return
        text = "🎒 Карты:\n\n"
        buttons = []
        for card in cards[:30]:
            original = "🔒" if card['is_original'] else ""
            desc = f" - {card['description'][:30]}..." if card['description'] else ""
            text += f"{original}{rarity_emoji(card['rarity'])} #{card['id']} {card['name']}{desc} x{card['quantity']}\n"
            if card['quantity'] > 1:
                extra = card['quantity'] - 1 if card['is_original'] else card['quantity']
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} (+{extra}💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        if buttons:
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("break_"))
    async def break_card(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        user_card = await get_user_card(call.from_user.id, card_id)
        if not user_card or user_card['quantity'] <= 1:
            await call.answer("❌ Нечего разбивать!", show_alert=True)
            return
        break_qty = user_card['quantity'] - 1 if user_card['is_original'] else user_card['quantity']
        if break_qty <= 0:
            await call.answer("❌ Нечего разбивать!", show_alert=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            if user_card['is_original']:
                await db.execute("UPDATE user_cards SET quantity=1 WHERE user_id=? AND card_id=?", 
                               (call.from_user.id, card_id))
            else:
                await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", 
                               (call.from_user.id, card_id))
            await db.commit()
        await upd_diamonds(call.from_user.id, break_qty)
        await update_task_progress(call.from_user.id, 'break')
        await call.answer(f"✅ Разбито {break_qty} карт → +{break_qty}💎!", show_alert=True)
    
    # ==================== ЗАДАНИЯ ====================
    @dp.message(F.text == "📋 Задания")
    async def tasks_button(msg: types.Message):
        tasks = await get_daily_tasks(msg.from_user.id)
        text = "📋 Ежедневные задания:\n\n"
        for task in tasks:
            status = "✅" if task['completed'] else "⬜"
            progress = f"{task['progress']}/{task['task_target']}"
            task_info = next((t for t in TASK_TYPES if t['type'] == task['task_type']), None)
            task_desc = task_info['desc'] if task_info else task['task_type']
            text += f"{status} {task_desc} ({progress})\n"
        all_done = await check_all_tasks_completed(msg.from_user.id)
        bonus_given = await give_bonus_roll(msg.from_user.id)
        if all_done and bonus_given: text += "\n🎉 ВСЕ ЗАДАНИЯ ВЫПОЛНЕНЫ!\n+1 бонусная крутка начислена!"
        elif all_done and not bonus_given: text += "\n✅ Бонус уже получен!\nЖди обновления в 8:00 МСК"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== БИРЖА ====================
    @dp.message(F.text == "💱 Биржа")
    async def market_button(msg: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все лоты", callback_data="market_view")],
            [InlineKeyboardButton(text="🔍 Найти по номеру", callback_data="market_search_info")],
            [InlineKeyboardButton(text="📊 Выставить на продажу", callback_data="market_sell_info")],
        ])
        await msg.answer("💱 Биржа карт\n\nЗдесь можно купить/продать карты за алмазы.\nВыбери действие:", reply_markup=kb)
    
    @dp.callback_query(F.data == "market_view")
    async def market_view(call: types.CallbackQuery):
        listings = await get_market_listings()
        if not listings:
            await call.message.answer("📋 На бирже пока нет лотов")
            await call.answer()
            return
        text = "📋 Лоты:\n\n"
        buttons = []
        for lot in listings[:10]:
            text += f"#{lot['id']} {rarity_emoji(lot['rarity'])} {lot['name']} | {lot['price']}💎\n"
            buttons.append([InlineKeyboardButton(text=f"Купить за {lot['price']}💎", callback_data=f"mbuy_{lot['id']}")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await call.message.answer(text, reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "market_search_info")
    async def market_search_info(call: types.CallbackQuery):
        await call.message.answer("🔍 Используй: /find НОМЕР\nПример: /find 5")
        await call.answer()
    
    @dp.message(Command("find"))
    async def find_card(msg: types.Message):
        try:
            card_id = int(msg.text.replace("/find", "").strip())
            listings = await get_market_listings(card_id=card_id)
            if not listings:
                await msg.answer(f"📋 Нет лотов с картой #{card_id}")
                return
            text = f"📋 Лоты с картой #{card_id}:\n\n"
            buttons = []
            for lot in listings[:10]:
                text += f"#{lot['id']} | {lot['price']}💎\n"
                buttons.append([InlineKeyboardButton(text=f"Купить за {lot['price']}💎", callback_data=f"mbuy_{lot['id']}")])
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except:
            await msg.answer("❌ Формат: /find НОМЕР")
    
    @dp.callback_query(F.data == "market_sell_info")
    async def market_sell_info(call: types.CallbackQuery):
        await call.message.answer("📊 Для продажи: /sell НОМЕР ЦЕНА\nПример: /sell 5 10")
        await call.answer()
    
    @dp.message(Command("sell"))
    async def sell_card(msg: types.Message):
        try:
            parts = msg.text.split()
            card_id, price = int(parts[1]), int(parts[2])
            if price < 1:
                await msg.answer("❌ Цена > 0!")
                return
            user_card = await get_user_card(msg.from_user.id, card_id)
            if not user_card:
                await msg.answer(f"❌ У вас нет карты #{card_id}!")
                return
            if user_card['is_original'] and user_card['quantity'] <= 1:
                await msg.answer("❌ Нельзя продать оригинал!")
                return
            await remove_card(msg.from_user.id, card_id, 1)
            await create_market_listing(msg.from_user.id, card_id, price)
            await msg.answer(f"✅ Карта #{card_id} продается за {price}💎!")
        except:
            await msg.answer("❌ /sell НОМЕР ЦЕНА")
    
    @dp.callback_query(F.data.startswith("mbuy_"))
    async def market_buy(call: types.CallbackQuery):
        listing_id = int(call.data.split("_")[1])
        success, message = await buy_listing(listing_id, call.from_user.id)
        await call.answer(f"{'✅' if success else '❌'} {message}", show_alert=True)
    
    # ==================== ОБМЕН ====================
    @dp.message(F.text == "🔄 Обмен")
    async def trade_button(msg: types.Message):
        await msg.answer(
            "🔄 Обмен картами\n\n"
            "/trade @юзер ID_моей_карты ID_его_карты\n\n"
            "Пример: /trade @username 5 10\n\n"
            "Предложит обменять вашу #5 на #10 игрока @username"
        )
    
    @dp.message(Command("trade"))
    async def trade_cmd(msg: types.Message):
        try:
            parts = msg.text.split()
            if len(parts) != 4:
                await msg.answer("❌ /trade @юзер ID_моей ID_его")
                return
            to_username = parts[1].replace("@", "")
            from_card_id, to_card_id = int(parts[2]), int(parts[3])
            my_card = await get_user_card(msg.from_user.id, from_card_id)
            if not my_card:
                await msg.answer(f"❌ У вас нет карты #{from_card_id}!")
                return
            if my_card['is_original'] and my_card['quantity'] <= 1:
                await msg.answer("❌ Нельзя обменять оригинал!")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM users WHERE username=?", (to_username,)) as c:
                    to_user = await c.fetchone()
            if not to_user:
                await msg.answer(f"❌ @{to_username} не найден!")
                return
            to_uid = to_user[0]
            his_card = await get_user_card(to_uid, to_card_id)
            if not his_card:
                await msg.answer(f"❌ У @{to_username} нет карты #{to_card_id}!")
                return
            from_card = await get_card_by_id(from_card_id)
            to_card = await get_card_by_id(to_card_id)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да", callback_data=f"trade_accept_{msg.from_user.id}_{from_card_id}_{to_card_id}")],
                [InlineKeyboardButton(text="❌ Нет", callback_data=f"trade_decline_{msg.from_user.id}")],
            ])
            trade_text = (
                f"🔄 ПРЕДЛОЖЕНИЕ ОБМЕНА!\n\n"
                f"От: @{msg.from_user.username}\n\n"
                f"Предлагает: {rarity_emoji(from_card['rarity'])} {from_card['name']} (#{from_card_id})\n"
                f"Хочет: {rarity_emoji(to_card['rarity'])} {to_card['name']} (#{to_card_id})\n\n"
                f"Принять обмен?"
            )
            try:
                await bot.send_message(to_uid, trade_text, reply_markup=kb)
                await msg.answer(f"✅ Предложение отправлено @{to_username}!")
            except:
                await msg.answer("❌ Не удалось отправить")
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    
    @dp.callback_query(F.data.startswith("trade_accept_"))
    async def trade_accept(call: types.CallbackQuery):
        parts = call.data.split("_")
        from_uid, from_cid, to_cid = int(parts[2]), int(parts[3]), int(parts[4])
        from_card = await get_user_card(from_uid, from_cid)
        to_card = await get_user_card(call.from_user.id, to_cid)
        if not from_card or not to_card:
            await call.message.edit_text("❌ Карта больше недоступна")
            return
        await remove_card(from_uid, from_cid, 1)
        await remove_card(call.from_user.id, to_cid, 1)
        await add_card_to_user(call.from_user.id, from_cid)
        await add_card_to_user(from_uid, to_cid)
        await call.message.edit_text("✅ Обмен выполнен!")
        try: await bot.send_message(from_uid, f"✅ @{call.from_user.username} принял обмен!")
        except: pass
        await call.answer()
    
    @dp.callback_query(F.data.startswith("trade_decline_"))
    async def trade_decline(call: types.CallbackQuery):
        from_uid = int(call.data.split("_")[2])
        await call.message.edit_text("❌ Обмен отклонен")
        try: await bot.send_message(from_uid, f"❌ @{call.from_user.username} отклонил обмен")
        except: pass
        await call.answer()
    
    # ==================== ЛИДЕРЫ И ДОСТИЖЕНИЯ ====================
    @dp.message(F.text == "🏆 Лидеры")
    async def leaders_button(msg: types.Message):
        top = await get_leaders(10)
        if not top:
            await msg.answer("🏆 Пока никого", reply_markup=permanent_keyboard())
            return
        text = "🏆 Топ-10:\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(top):
            text += f"{medals[i] if i<3 else f'{i+1}.'} {u['username']} - {u['total']} карт\n"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "🏅 Достижения")
    async def achievements_button(msg: types.Message):
        user = await get_user(msg.from_user.id)
        cards = await get_user_cards(msg.from_user.id)
        total_cards = sum(c['quantity'] for c in cards)
        l_cards = sum(c['quantity'] for c in cards if c['is_L_card'])
        text = "🏅 Достижения:\n\n"
        async with aiosqlite.connect(DB_PATH) as db:
            for ach in ACHIEVEMENTS:
                async with db.execute(
                    "SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?", (msg.from_user.id, ach['id'])
                ) as c:
                    row = await c.fetchone()
                    completed = row and row[0]
                text += f"{'✅' if completed else '🔒'} {ach['icon']} {ach['name']}\n   {ach['desc']}\n\n"
        text += f"📊 Статистика:\n🎴 Карт: {total_cards}\n🌟 L-карт: {l_cards}\n🔄 Круток: {user['total_rolls']}"
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "❓ Помощь")
    async def help_button(msg: types.Message):
        text = (
            "❓ Помощь\n\n"
            "🎲 Крутить - бесплатно\n💎 Премиум - за 5💎\n🎡 Колесо - 1/день\n"
            "💱 Биржа - купить/продать\n🔄 Обмен - /trade @юзер ID ID\n📋 Задания - авто\n\n"
            "🌟 Гарант: 90 круток = L\n💰 Повторы → 💎"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg: types.Message):
        await msg.answer("🎮 Меню:", reply_markup=permanent_keyboard())
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать ресурсы", callback_data="admin_give_menu")],
        ])
        await msg.answer(
            "👑 Админ-панель\n\n"
            "/addcard - добавить\n/cards - список\n/delcard ID - удалить\n"
            "/givediamonds ID кол-во\n/giverolls ID кол-во\n/givecards ID кол-во\n/givecard ID карта_ID",
            reply_markup=kb
        )
    
    @dp.callback_query(F.data == "admin_add")
    async def admin_add_start(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS: return
        await call.message.answer("📝 Шаг 1/4\nВведи номер и имя:\nПример: #6 Дима")
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    @dp.message(Command("addcard"))
    async def addcard_cmd(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        await msg.answer("📝 Шаг 1/4\nВведи номер и имя:\nПример: #6 Дима")
        await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def add_name(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(name=msg.text.strip())
        await msg.answer("📝 Шаг 2/4\nВведи описание:")
        await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def add_desc(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nВыбери редкость:", reply_markup=rarity_keyboard())
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def add_rarity(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS: return
        rarity = call.data.split("_")[1]
        await state.update_data(rarity=rarity)
        rn = {'R':'R-Обычная','SR':'SR-Редкая','SSR':'SSR-Эпическая','L':'L-Легендарная'}
        await call.message.answer(f"📝 Шаг 4/4\n{rn.get(rarity,rarity)}\nОтправь фото или 'нет'")
        await state.set_state(AddCardStates.waiting_for_photo)
        await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def add_photo(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS: return
        data = await state.get_data()
        file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity'] == 'L'
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?,?,?,?,?)",
                (data['name'], data['description'], file_id, data['rarity'], is_L)
            )
            await db.commit()
        rn = {'R':'R','SR':'SR','SSR':'SSR','L':'🌟L'}
        await msg.answer(f"✅ Карта добавлена!\n📛 {data['name']}\n📝 {data['description']}\n⭐ {rn.get(data['rarity'],data['rarity'])}\n{'🖼' if file_id else '❌'}")
        await state.clear()
    
    async def show_cards_list(target):
        cards = await get_all_cards()
        if not cards:
            await target.answer("📋 Нет карт")
            return
        ro = {'L':'🌟L','SSR':'🟣SSR','SR':'🔵SR','R':'⚪R'}
        g = {}
        for c in cards:
            r = c['rarity']
            if r not in g: g[r] = []
            g[r].append(c)
        text = "📋 Все карты:\n\n"
        for r, t in ro.items():
            if r in g:
                text += f"{t} ({len(g[r])}):\n"
                for c in g[r]:
                    d = f" - {c['description'][:30]}" if c['description'] else ""
                    p = "🖼" if c['file_id'] else "❌"
                    text += f"  #{c['id']} {c['name']}{d} {p}\n"
                text += "\n"
        text += f"Всего: {len(cards)}"
        for i in range(0, len(text), 4000): await target.answer(text[i:i+4000])
    
    @dp.callback_query(F.data == "admin_list")
    async def admin_list_callback(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS: return
        await show_cards_list(call.message)
        await call.answer()
    
    @dp.message(Command("cards"))
    async def cards_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        await show_cards_list(msg)
    
    @dp.message(Command("delcard"))
    async def delcard(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            card_id = int(msg.text.replace("/delcard","").strip())
            card = await get_card_by_id(card_id)
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена!")
                return
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (card_id,))
                await db.execute("DELETE FROM user_cards WHERE card_id=?", (card_id,))
                await db.execute("DELETE FROM market WHERE card_id=?", (card_id,))
                await db.commit()
            await msg.answer(f"✅ Карта #{card_id} удалена!")
        except: await msg.answer("❌ /delcard ID")
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def admin_give_menu(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS: return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Алмазы", callback_data="give_diamonds")],
            [InlineKeyboardButton(text="🎲 Крутки", callback_data="give_rolls")],
            [InlineKeyboardButton(text="🎴 Случайные карты", callback_data="give_random_cards")],
            [InlineKeyboardButton(text="🎯 Конкретная карта", callback_data="give_specific_card")],
        ])
        await call.message.edit_text("🎁 Выдача ресурсов\nИли команды:\n/givediamonds /giverolls /givecards /givecard", reply_markup=kb)
        await call.answer()
    
    @dp.callback_query(F.data == "give_diamonds")
    async def gi(call: types.CallbackQuery): await call.message.answer("/givediamonds ID кол-во"); await call.answer()
    @dp.callback_query(F.data == "give_rolls")
    async def gr(call: types.CallbackQuery): await call.message.answer("/giverolls ID кол-во"); await call.answer()
    @dp.callback_query(F.data == "give_random_cards")
    async def gc(call: types.CallbackQuery): await call.message.answer("/givecards ID кол-во"); await call.answer()
    @dp.callback_query(F.data == "give_specific_card")
    async def gs(call: types.CallbackQuery): await call.message.answer("/givecard ID карта_ID"); await call.answer()
    
    @dp.message(Command("givediamonds"))
    async def gd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); tid, am = int(p[1]), int(p[2])
            await upd_diamonds(tid, am)
            await msg.answer(f"✅ +{am}💎 пользователю {tid}")
        except: await msg.answer("❌ /givediamonds ID кол-во")
    
    @dp.message(Command("giverolls"))
    async def gr2(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); tid, am = int(p[1]), int(p[2])
            await upd_rolls(tid, am)
            await msg.answer(f"✅ +{am}🎲 пользователю {tid}")
        except: await msg.answer("❌ /giverolls ID кол-во")
    
    @dp.message(Command("givecards"))
    async def gc2(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); tid, am = int(p[1]), int(p[2])
            cards = await get_all_cards()
            if not cards: await msg.answer("❌ Нет карт!"); return
            for _ in range(am):
                await add_card_to_user(tid, random.choice(cards)['id'], is_original=True)
            await msg.answer(f"✅ +{am} карт пользователю {tid}")
        except: await msg.answer("❌ /givecards ID кол-во")
    
    @dp.message(Command("givecard"))
    async def gs2(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS: return
        try:
            p = msg.text.split(); tid, cid = int(p[1]), int(p[2])
            card = await get_card_by_id(cid)
            if not card: await msg.answer(f"❌ Карта #{cid} не найдена!"); return
            await add_card_to_user(tid, cid, is_original=True)
            await msg.answer(f"✅ Карта #{cid} '{card['name']}' выдана {tid}")
        except: await msg.answer("❌ /givecard ID карта_ID")
    
    # ==================== УВЕДОМЛЕНИЯ В 8:00 ====================
    async def daily_reset_with_bot():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2, fortune_spins=1, bonus_roll_received=0")
                await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),))
                await db.commit()
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT user_id FROM users") as c:
                    users = await c.fetchall()
            tasks = random.sample(TASK_TYPES, 2)
            sent = 0
            for user in users:
                try:
                    message = (
                        "🌅 Доброе утро! Ежедневные бонусы начислены!\n\n"
                        "🎁 Получено:\n"
                        "🎲 +2 крутки\n💎 +2 алмаза\n🎡 +1 колесо фортуны\n\n"
                        f"📋 Сегодняшние задания:\n"
                        f"1️⃣ {tasks[0]['desc']}\n"
                        f"2️⃣ {tasks[1]['desc']}\n\n"
                        "🏅 Выполни оба → +1 бонусная крутка!\n\nУдачи! 🍀"
                    )
                    await bot.send_message(user['user_id'], message)
                    sent += 1
                    await asyncio.sleep(0.05)
                except: pass
            logger.info(f"✅ Бонусы начислены! Уведомления: {sent}/{len(users)}")
        except Exception as e:
            logger.error(f"Ошибка сброса: {e}")
    
    # ==================== ЗАПУСК ====================
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_reset_with_bot, 'cron', hour=8, minute=0)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
