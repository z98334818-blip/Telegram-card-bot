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
    ReplyKeyboardMarkup, KeyboardButton
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

async def add_card_to_user(uid, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_cards VALUES (?,?,1)
            ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=quantity+1
        """, (uid, cid))
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
            SELECT c.*, uc.quantity FROM user_cards uc
            JOIN cards c ON uc.card_id=c.id
            WHERE uc.user_id=?
            ORDER BY c.id
        """, (uid,)) as c:
            return await c.fetchall()

async def remove_card(uid, cid, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute("SELECT quantity FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
        row = await c.fetchone()
        if row and row[0] >= qty:
            if row[0] == qty:
                await db.execute("DELETE FROM user_cards WHERE user_id=? AND card_id=?", (uid, cid))
            else:
                await db.execute("UPDATE user_cards SET quantity=quantity-? WHERE user_id=? AND card_id=?", 
                               (qty, uid, cid))
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
    {"type": "break", "desc": "🔨 Разбить 1 повторку", "target": 1},
    {"type": "fortune", "desc": "🎡 Прокрутить колесо фортуны", "target": 1},
]

async def get_daily_tasks(uid):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_tasks WHERE user_id=? AND date=?",
            (uid, today)
        ) as c:
            tasks = await c.fetchall()
            if not tasks:
                selected = random.sample(TASK_TYPES, 2)
                for i, task in enumerate(selected):
                    await db.execute(
                        "INSERT INTO daily_tasks (user_id, task_id, task_type, task_target, date) VALUES (?,?,?,?,?)",
                        (uid, i, task['type'], task['target'], today)
                    )
                await db.commit()
                async with db.execute(
                    "SELECT * FROM daily_tasks WHERE user_id=? AND date=?",
                    (uid, today)
                ) as c2:
                    return await c2.fetchall()
            return tasks

async def update_task_progress(uid, task_type, date=None):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE daily_tasks SET progress=progress+1 
            WHERE user_id=? AND task_type=? AND date=? AND completed=0
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
            return row[0] == 2 and row[1] == 2

async def give_bonus_roll(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bonus_roll_received=1 WHERE user_id=?", (uid,))
        await db.execute("UPDATE users SET rolls=rolls+1 WHERE user_id=?", (uid,))
        await db.commit()

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
            # Проверяем условие
            if ach['id'] == 'cards_10' and total_cards >= 10:
                completed = True
            elif ach['id'] == 'cards_50' and total_cards >= 50:
                completed = True
            elif ach['id'] == 'cards_100' and total_cards >= 100:
                completed = True
            elif ach['id'] == 'rolls_100' and user['total_rolls'] >= 100:
                completed = True
            elif ach['id'] == 'l_cards_1' and l_cards >= 1:
                completed = True
            else:
                continue
            
            async with db.execute(
                "SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?",
                (uid, ach['id'])
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
            [KeyboardButton(text="🏆 Лидеры"), KeyboardButton(text="🏅 Достижения")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        persistent=True
    )

def rarity_emoji(rarity):
    emojis = {'R': '⚪', 'SR': '🔵', 'SSR': '🟣', 'L': '🌟'}
    return emojis.get(rarity, '⚪')

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
            "• +2 бесплатные крутки\n"
            "• +2 алмаза 💎\n"
            "• +1 вращение колеса 🎡\n"
            "• +2 новых задания 📋\n\n"
            "🌟 Собирай коллекцию!\n"
            "🏆 Выполняй задания и получай награды!\n\n"
            "Используй кнопки меню внизу 👇"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== КРУТКА ====================
    async def perform_roll(uid, is_premium=False):
        """Выполняет крутку и возвращает результат"""
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
            guarantee_text = "🎉 ГАРАНТИРОВАННАЯ L-КАРТА!\n"
            progress = 0
        else:
            if L_cards and random.random() < 0.01:
                card = random.choice(L_cards)
                await upd_guarantor(uid, 0)
                guarantee_text = "🌟 ВЫПАЛА L-КАРТА!\n"
                progress = 0
            else:
                card = random.choice(normal if normal else cards)
                if not is_premium:  # Прогресс гаранта только для обычных круток
                    progress += 1
                    await upd_guarantor(uid, progress)
                guarantee_text = ""
        
        await add_card_to_user(uid, card['id'])
        
        caption = guarantee_text
        caption += f"{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']:
            caption += f"📝 {card['description']}\n"
        caption += f"⭐ Редкость: {card['rarity']}\n"
        caption += f"📎 ID: #{card['id']}\n"
        caption += f"📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        
        return card, caption
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u:
            await msg.answer("Нажми /start сначала!", reply_markup=permanent_keyboard())
            return
        
        if u['rolls'] <= 0:
            await msg.answer("❌ Нет круток! Жди 8:00 МСК или купи за алмазы", reply_markup=permanent_keyboard())
            return
        
        await upd_rolls(msg.from_user.id, -1)
        card, caption = await perform_roll(msg.from_user.id)
        
        if card is None:
            await msg.answer(caption, reply_markup=permanent_keyboard())
            return
        
        # Обновляем задание
        await update_task_progress(msg.from_user.id, 'roll')
        
        # Проверяем достижения
        achievements = await check_achievements(msg.from_user.id)
        
        # Отправляем карту
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption)
            else:
                await msg.answer(caption)
        except:
            await msg.answer(caption)
        
        # Уведомления о достижениях
        if achievements:
            for ach in achievements:
                await msg.answer(f"🏅 ДОСТИЖЕНИЕ!\n{ach['icon']} {ach['name']}: {ach['desc']}")
        
        # Проверяем бонус за задания
        if await check_all_tasks_completed(msg.from_user.id):
            u2 = await get_user(msg.from_user.id)
            if not u2['bonus_roll_received']:
                await give_bonus_roll(msg.from_user.id)
                await msg.answer("🎉 Все задания выполнены! +1 бонусная крутка!")
    
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5:
            await msg.answer("❌ Нужно 5 алмазов!", reply_markup=permanent_keyboard())
            return
        
        await upd_diamonds(msg.from_user.id, -5)
        card, caption = await perform_roll(msg.from_user.id, is_premium=True)
        
        if card is None:
            await msg.answer(caption, reply_markup=permanent_keyboard())
            return
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption="💎 Премиум крутка!\n" + caption)
            else:
                await msg.answer("💎 Премиум крутка!\n" + caption)
        except:
            await msg.answer("💎 Премиум крутка!\n" + caption)
    
    # ==================== КОЛЕСО ФОРТУНЫ ====================
    async def spin_fortune(msg):
        prizes = []
        for p in FORTUNE_PRIZES:
            prizes.extend([p] * p['weight'])
        
        prize = random.choice(prizes)
        card = None
        
        if prize['prize'] == 'roll':
            await upd_rolls(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'diamond':
            await upd_diamonds(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_all_cards()
            if cards:
                card = random.choice(cards)
                await add_card_to_user(msg.from_user.id, card['id'])
            else:
                prize = {"prize": "nothing", "value": 0, "desc": "❌ Ничего (нет карт в базе)"}
        
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] > 0:
            await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
        
        await update_task_progress(msg.from_user.id, 'fortune')
        
        if card and prize['prize'] == 'random_card':
            caption = f"🎡 Колесо фортуны!\n\n🎴 Выпала карта!\n{rarity_emoji(card['rarity'])} {card['name']}\n"
            if card['description']:
                caption += f"📝 {card['description']}\n"
            caption += f"⭐ {card['rarity']}\n📎 #{card['id']}"
            
            try:
                if card['file_id']:
                    await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=permanent_keyboard())
                else:
                    await msg.answer(caption, reply_markup=permanent_keyboard())
            except:
                await msg.answer(caption, reply_markup=permanent_keyboard())
        else:
            await msg.answer(f"🎡 Колесо фортуны!\n\n{prize['desc']}", reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        
        if u['fortune_spins'] <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎡 1 вращение - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="🎡 5 вращений - 3💎 (скидка)", callback_data="fortune_buy_5")],
                [InlineKeyboardButton(text="🎡 10 вращений - 5💎 (скидка)", callback_data="fortune_buy_10")],
            ])
            await msg.answer(
                "🎡 Колесо фортуны\n\n"
                "🎁 Возможные призы:\n"
                "🎲 +1 крутка (30%)\n"
                "💎 +1 алмаз (25%)\n"
                "💎 +2 алмаза (15%)\n"
                "🎴 Случайная карта (15%)\n"
                "❌ Ничего (15%)\n\n"
                "Бесплатные вращения закончились!\n"
                "Можно купить за алмазы:",
                reply_markup=kb
            )
        else:
            await msg.answer(f"🎡 Крутим колесо фортуны!\nОсталось бесплатных вращений: {u['fortune_spins']}")
            await spin_fortune(msg)
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call: types.CallbackQuery):
        amount = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3, 10: 5}
        price = prices[amount]
        
        u = await get_user(call.from_user.id)
        if u['diamonds'] < price:
            await call.answer(f"❌ Нужно {price}💎! У тебя {u['diamonds']}💎", show_alert=True)
            return
        
        await upd_diamonds(call.from_user.id, -price)
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + amount)
        await call.answer(f"✅ +{amount} вращений за {price}💎!", show_alert=True)
        
        # Запускаем вращения
        for i in range(amount):
            await spin_fortune(call.message)
    
    # ==================== ПРОФИЛЬ ====================
    @dp.message(F.text == "👤 Профиль")
    async def profile_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u:
            await msg.answer("Нажми /start сначала!", reply_markup=permanent_keyboard())
            return
        
        cards = await get_card_count(msg.from_user.id)
        progress = u['guarantor_progress']
        
        text = (
            f"👤 Профиль\n\n"
            f"📛 {u['username']}\n"
            f"💎 Алмазы: {u['diamonds']}\n"
            f"🎲 Крутки: {u['rolls']}\n"
            f"🎴 Карт собрано: {cards}\n"
            f"🔄 Всего круток: {u['total_rolls']}\n"
            f"🎡 Вращений колеса: {u['fortune_spins']}\n"
            f"📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        )
        
        # Обновляем задание
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
            await call.answer(f"❌ Нужно {price}💎! У тебя {u['diamonds']}💎", show_alert=True)
            return
        
        await upd_diamonds(call.from_user.id, -price)
        await upd_rolls(call.from_user.id, amount)
        await call.answer(f"✅ +{amount} круток за {price}💎!", show_alert=True)
    
    # ==================== ИНВЕНТАРЬ ====================
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_button(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        
        if not cards:
            await msg.answer("🎒 Инвентарь пуст\n\nИспользуй 🎲 Крутить!", reply_markup=permanent_keyboard())
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:30]:
            desc = f" - {card['description'][:30]}..." if card['description'] else ""
            text += f"{rarity_emoji(card['rarity'])} #{card['id']} {card['name']}{desc} x{card['quantity']}\n"
            
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        if buttons:
            buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_inv")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("break_"))
    async def break_card(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        cards = await get_user_cards(call.from_user.id)
        card = next((c for c in cards if c['id'] == card_id), None)
        
        if not card or card['quantity'] < 5:
            await call.answer("❌ Нужно 5 одинаковых карт!", show_alert=True)
            return
        
        if await remove_card(call.from_user.id, card_id, 5):
            await upd_diamonds(call.from_user.id, 1)
            await update_task_progress(call.from_user.id, 'break')
            await call.answer("✅ 5 карт → 1💎!", show_alert=True)
        else:
            await call.answer("❌ Ошибка!", show_alert=True)
    
    @dp.callback_query(F.data == "refresh_inv")
    async def refresh_inv(call: types.CallbackQuery):
        await inv_button(call.message)
        await call.answer("Обновлено!")
    
    # ==================== ЗАДАНИЯ ====================
    @dp.message(F.text == "📋 Задания")
    async def tasks_button(msg: types.Message):
        tasks = await get_daily_tasks(msg.from_user.id)
        u = await get_user(msg.from_user.id)
        
        text = "📋 Ежедневные задания:\n\n"
        
        for task in tasks:
            status = "✅" if task['completed'] else "⬜"
            progress = f"{task['progress']}/{task['task_target']}"
            task_info = next((t for t in TASK_TYPES if t['type'] == task['task_type']), None)
            task_desc = task_info['desc'] if task_info else task['task_type']
            text += f"{status} {task_desc} ({progress})\n"
        
        if await check_all_tasks_completed(msg.from_user.id):
            if not u['bonus_roll_received']:
                await give_bonus_roll(msg.from_user.id)
                text += "\n🎉 Все задания выполнены!\n+1 бонусная крутка!"
            else:
                text += "\n✅ Бонус уже получен!\nЖди обновления в 8:00 МСК"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ЛИДЕРЫ ====================
    @dp.message(F.text == "🏆 Лидеры")
    async def leaders_button(msg: types.Message):
        top = await get_leaders(10)
        
        if not top:
            await msg.answer("🏆 Пока никто не собрал карты!", reply_markup=permanent_keyboard())
            return
        
        text = "🏆 Топ-10 коллекционеров:\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {u['username']} - {u['total']} карт\n"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ДОСТИЖЕНИЯ ====================
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
                    "SELECT completed FROM achievements WHERE user_id=? AND achievement_id=?",
                    (msg.from_user.id, ach['id'])
                ) as c:
                    row = await c.fetchone()
                    completed = row and row[0]
                
                status = "✅" if completed else "🔒"
                text += f"{status} {ach['icon']} {ach['name']}\n   {ach['desc']}\n\n"
        
        text += f"📊 Твоя статистика:\n"
        text += f"🎴 Всего карт: {total_cards}\n"
        text += f"🌟 L-карт: {l_cards}\n"
        text += f"🔄 Круток: {user['total_rolls']}\n"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ПОМОЩЬ ====================
    @dp.message(F.text == "❓ Помощь")
    async def help_button(msg: types.Message):
        text = (
            "❓ Как играть:\n\n"
            "🎲 Крутить - бесплатная крутка\n"
            "💎 Премиум крутка - за 5 алмазов\n"
            "🎡 Колесо фортуны - 1 бесплатно в день\n"
            "👤 Профиль - статистика\n"
            "🎒 Инвентарь - твои карты\n"
            "📋 Задания - ежедневные задачи\n"
            "🏆 Лидеры - топ игроков\n"
            "🏅 Достижения - награды за прогресс\n\n"
            "🌟 Система L-гаранта:\n"
            "• Каждые 90 круток без L → гарант L\n"
            "• Прогресс виден при крутке и в профиле\n\n"
            "💡 Советы:\n"
            "• 5 одинаковых карт = 1💎\n"
            "• Выполняй задания для бонусов\n"
            "• Крути колесо фортуны\n"
            "• Собирай достижения\n\n"
            "📢 По вопросам: @your_support"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== КОМАНДЫ ====================
    @dp.message(Command("menu"))
    async def menu_cmd(msg: types.Message):
        await msg.answer("🎮 Используй кнопки внизу 👇", reply_markup=permanent_keyboard())
    
    @dp.message(Command("card"))
    async def card_info(msg: types.Message):
        try:
            card_id = int(msg.text.replace("/card", "").strip())
            card = await get_card_by_id(card_id)
            
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена")
                return
            
            text = f"{rarity_emoji(card['rarity'])} {card['name']}\n"
            if card['description']:
                text += f"📝 {card['description']}\n"
            text += f"⭐ Редкость: {card['rarity']}\n📎 #{card['id']}"
            if card['is_L_card']:
                text += "\n🌟 L-КАРТА!"
            
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=text)
            else:
                await msg.answer(text)
        except:
            await msg.answer("❌ Формат: /card ID\nПример: /card 5")
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
            [InlineKeyboardButton(text="🎁 Выдать игроку", callback_data="admin_give_menu")],
        ])
        
        text = (
            "👑 Админ-панель\n\n"
            "📝 Быстрые команды:\n"
            "/addcard - добавить карту (пошагово)\n"
            "/cards - список всех карт\n"
            "/delcard ID - удалить карту\n"
            "/givediamonds ID кол-во\n"
            "/giverolls ID кол-во\n"
            "/givecards ID кол-во\n"
            "/givecard ID карта_ID\n\n"
            "Или используй кнопки 👇"
        )
        await msg.answer(text, reply_markup=kb)
    
    @dp.callback_query(F.data == "admin_add")
    async def admin_add_start(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("📝 Шаг 1/4\n\nВведи номер и имя:\nФормат: #НОМЕР ИМЯ\nПример: #6 Дима")
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    @dp.message(Command("addcard"))
    async def addcard_cmd(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await msg.answer("📝 Шаг 1/4\n\nВведи номер и имя:\nФормат: #НОМЕР ИМЯ\nПример: #6 Дима")
        await state.set_state(AddCardStates.waiting_for_name)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def add_name(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(name=msg.text.strip())
        await msg.answer("📝 Шаг 2/4\n\nВведи описание:\nПример: Какой-то там вампир")
        await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def add_desc(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\n\nВыбери редкость:", reply_markup=rarity_keyboard())
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def add_rarity(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        rarity = call.data.split("_")[1]
        await state.update_data(rarity=rarity)
        
        rarity_names = {'R': 'R - Обычная', 'SR': 'SR - Редкая', 'SSR': 'SSR - Эпическая', 'L': 'L - Легендарная'}
        await call.message.answer(
            f"📝 Шаг 4/4\n\n"
            f"Редкость: {rarity_names.get(rarity, rarity)}\n\n"
            f"Отправь фото или напиши 'нет'"
        )
        await state.set_state(AddCardStates.waiting_for_photo)
        await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def add_photo(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        data = await state.get_data()
        file_id = None
        
        if msg.photo:
            file_id = msg.photo[-1].file_id
        elif msg.text and msg.text.lower() != 'нет':
            await msg.answer("❌ Отправь фото или напиши 'нет'")
            return
        
        is_L = data['rarity'] == 'L'
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?,?,?,?,?)",
                (data['name'], data['description'], file_id, data['rarity'], is_L)
            )
            await db.commit()
        
        rarity_names = {'R': 'R - Обычная', 'SR': 'SR - Редкая', 'SSR': 'SSR - Эпическая', 'L': '🌟 L - Легендарная'}
        
        await msg.answer(
            f"✅ Карта добавлена!\n\n"
            f"📛 {data['name']}\n"
            f"📝 {data['description']}\n"
            f"⭐ {rarity_names.get(data['rarity'], data['rarity'])}\n"
            f"{'🖼 С фото' if file_id else '❌ Без фото'}"
        )
        await state.clear()
    
    @dp.callback_query(F.data == "admin_list")
    async def admin_list(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        
        cards = await get_all_cards()
        if not cards:
            await call.message.answer("📋 Нет карт в базе")
            await call.answer()
            return
        
        # Группируем по редкости
        rarity_order = {'L': '🌟 L', 'SSR': '🟣 SSR', 'SR': '🔵 SR', 'R': '⚪ R'}
        grouped = {}
        for card in cards:
            r = card['rarity']
            if r not in grouped:
                grouped[r] = []
            grouped[r].append(card)
        
        text = "📋 Все карты:\n\n"
        for rarity, title in rarity_order.items():
            if rarity in grouped:
                text += f"{title} ({len(grouped[rarity])}):\n"
                for c in grouped[rarity]:
                    desc = f" - {c['description'][:30]}" if c['description'] else ""
                    text += f"  #{c['id']} {c['name']}{desc}\n"
                text += "\n"
        
        text += f"Всего: {len(cards)} карт"
        
        # Разбиваем если длинное
        for i in range(0, len(text), 4000):
            await call.message.answer(text[i:i+4000])
        await call.answer()
    
    @dp.message(Command("cards"))
    async def cards_list(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        await admin_list(msg)
    
    @dp.message(Command("delcard"))
    async def delcard(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            card_id = int(msg.text.replace("/delcard", "").strip())
            card = await get_card_by_id(card_id)
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена!")
                return
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (card_id,))
                await db.execute("DELETE FROM user_cards WHERE card_id=?", (card_id,))
                await db.commit()
            
            await msg.answer(f"✅ Карта #{card_id} '{card['name']}' удалена!")
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}\nФормат: /delcard ID")
    
    @dp.callback_query(F.data == "admin_give_menu")
    async def admin_give_menu(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
        ])
        
        await call.message.edit_text(
            "🎁 Выдача ресурсов\n\n"
            "Команды:\n"
            "/givediamonds ID кол-во - алмазы\n"
            "/giverolls ID кол-во - крутки\n"
            "/givecards ID кол-во - случайные карты\n"
            "/givecard ID карта_ID - конкретная карта\n\n"
            "Пример: /givediamonds 123456789 100",
            reply_markup=kb
        )
        await call.answer()
    
    @dp.callback_query(F.data == "admin_back")
    async def admin_back(call: types.CallbackQuery):
        await admin_cmd(call.message)
        await call.answer()
    
    @dp.message(Command("givediamonds"))
    async def give_diamonds(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            parts = msg.text.split()
            target_id = int(parts[1])
            amount = int(parts[2])
            await upd_diamonds(target_id, amount)
            await msg.answer(f"✅ Выдано {amount}💎 пользователю {target_id}")
            try:
                await bot.send_message(target_id, f"🎁 Админ выдал вам {amount}💎!")
            except:
                pass
        except:
            await msg.answer("❌ Формат: /givediamonds ID кол-во")
    
    @dp.message(Command("giverolls"))
    async def give_rolls(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            parts = msg.text.split()
            target_id = int(parts[1])
            amount = int(parts[2])
            await upd_rolls(target_id, amount)
            await msg.answer(f"✅ Выдано {amount}🎲 пользователю {target_id}")
            try:
                await bot.send_message(target_id, f"🎁 Админ выдал вам {amount}🎲!")
            except:
                pass
        except:
            await msg.answer("❌ Формат: /giverolls ID кол-во")
    
    @dp.message(Command("givecards"))
    async def give_cards(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            parts = msg.text.split()
            target_id = int(parts[1])
            amount = int(parts[2])
            cards = await get_all_cards()
            if not cards:
                await msg.answer("❌ Нет карт в базе!")
                return
            for _ in range(amount):
                card = random.choice(cards)
                await add_card_to_user(target_id, card['id'])
            await msg.answer(f"✅ Выдано {amount} случайных карт пользователю {target_id}")
            try:
                await bot.send_message(target_id, f"🎁 Админ выдал вам {amount} случайных карт!")
            except:
                pass
        except:
            await msg.answer("❌ Формат: /givecards ID кол-во")
    
    @dp.message(Command("givecard"))
    async def give_specific_card(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        try:
            parts = msg.text.split()
            target_id = int(parts[1])
            card_id = int(parts[2])
            card = await get_card_by_id(card_id)
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена!")
                return
            await add_card_to_user(target_id, card_id)
            await msg.answer(f"✅ Карта #{card_id} '{card['name']}' выдана пользователю {target_id}")
            try:
                if card['file_id']:
                    await bot.send_photo(target_id, photo=card['file_id'],
                        caption=f"🎁 Админ выдал вам карту!\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}")
                else:
                    await bot.send_message(target_id,
                        f"🎁 Админ выдал вам карту!\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}")
            except:
                pass
        except:
            await msg.answer("❌ Формат: /givecard ID карта_ID")
    
    # ==================== ЕЖЕДНЕВНЫЙ СБРОС ====================
    async def daily_reset():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2, fortune_spins=1, bonus_roll_received=0")
                await db.execute("DELETE FROM daily_tasks WHERE date < ?", (datetime.now().strftime("%Y-%m-%d"),))
                await db.commit()
            logger.info("✅ Ежедневный сброс выполнен!")
        except Exception as e:
            logger.error(f"Ошибка сброса: {e}")
    
    # ==================== ЗАПУСК ====================
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_reset, 'cron', hour=8, minute=0)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
