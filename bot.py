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
                bonus_roll_received BOOLEAN DEFAULT 0,
                last_daily_reset TEXT DEFAULT '2000-01-01'
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
# (Все предыдущие функции БД остаются те же, добавляем новые)

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

# ==================== ЗАДАНИЯ И КОЛЕСО ====================

TASK_TYPES = [
    {"type": "roll", "desc": "Прокрутить один раз", "target": 1},
    {"type": "profile", "desc": "Зайти в профиль один раз", "target": 1},
    {"type": "break", "desc": "Разбить 1 повторку", "target": 1},
    {"type": "fortune", "desc": "Прокрутить колесо фортуны", "target": 1},
]

FORTUNE_PRIZES = [
    {"prize": "roll", "value": 1, "desc": "🎲 +1 крутка", "weight": 30},
    {"prize": "diamond", "value": 1, "desc": "💎 +1 алмаз", "weight": 25},
    {"prize": "diamond", "value": 2, "desc": "💎 +2 алмаза", "weight": 15},
    {"prize": "random_card", "value": 1, "desc": "🎴 Случайная карта", "weight": 15},
    {"prize": "nothing", "value": 0, "desc": "❌ Ничего", "weight": 15},
]

ACHIEVEMENTS = [
    {"id": "cards_10", "name": "Начинающий коллекционер", "desc": "Собрать 10 карт", "check": lambda u: u['total_cards'] >= 10},
    {"id": "cards_50", "name": "Опытный коллекционер", "desc": "Собрать 50 карт", "check": lambda u: u['total_cards'] >= 50},
    {"id": "cards_100", "name": "Мастер коллекционирования", "desc": "Собрать 100 карт", "check": lambda u: u['total_cards'] >= 100},
    {"id": "rolls_100", "name": "Крутой крутильщик", "desc": "Сделать 100 круток", "check": lambda u: u['total_rolls'] >= 100},
    {"id": "l_cards_1", "name": "Первая L-карта", "desc": "Получить L-карту", "check": lambda u: u['l_cards'] >= 1},
    {"id": "all_common", "name": "Коллекционер R", "desc": "Собрать все R карты", "check": lambda u: False},  # Будет проверяться отдельно
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
                # Генерируем новые задания
                selected = random.sample(TASK_TYPES, 2)
                for i, task in enumerate(selected):
                    await db.execute(
                        "INSERT INTO daily_tasks (user_id, task_id, task_type, task_target, date) VALUES (?,?,?,?,?)",
                        (uid, i, task['type'], task['target'], today)
                    )
                await db.commit()
                # Получаем заново
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
        
        # Проверяем выполнение
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
            return row[0] == 2 and row[1] == 2  # 2 задания и оба выполнены

async def give_bonus_roll(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bonus_roll_received=1 WHERE user_id=?", (uid,))
        await db.execute("UPDATE users SET rolls=rolls+1 WHERE user_id=?", (uid,))
        await db.commit()

async def check_achievements(uid):
    user = await get_user(uid)
    cards = await get_user_cards(uid)
    total_cards = sum(c['quantity'] for c in cards)
    l_cards = sum(c['quantity'] for c in cards if c['is_L_card'])
    
    user_data = {
        'total_cards': total_cards,
        'total_rolls': user['total_rolls'],
        'l_cards': l_cards,
    }
    
    new_achievements = []
    async with aiosqlite.connect(DB_PATH) as db:
        for ach in ACHIEVEMENTS:
            if ach['check'](user_data):
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

# ==================== КЛАВИАТУРЫ ====================
def permanent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="💎 Премиум крутка"), KeyboardButton(text="🎡 Колесо фортуны")],
            [KeyboardButton(text="📋 Задания"), KeyboardButton(text="🏅 Достижения")],
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
            "✨ Приветствую тебя путник! ✨\n\n"
            "🎲 Ежедневно в 8:00 МСК:\n"
            "• +2 крутки и +2💎\n"
            "• +2 новых задания\n"
            "• +1 вращение колеса фортуны\n\n"
            "🌟 Собирай коллекцию, выполняй задания, получай награды!"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== КНОПКИ МЕНЮ ====================
    
    @dp.message(F.text == "🎲 Крутить")
    async def roll_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['rolls'] <= 0:
            await msg.answer("❌ Нет круток!", reply_markup=permanent_keyboard())
            return
        
        await upd_rolls(msg.from_user.id, -1)
        cards = await get_all_cards()
        
        if not cards:
            await msg.answer("❌ Нет карт в базе", reply_markup=permanent_keyboard())
            return
        
        progress = u['guarantor_progress']
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        
        is_guaranteed = progress >= 90
        
        if is_guaranteed and L_cards:
            card = random.choice(L_cards)
            await upd_guarantor(msg.from_user.id, 0)
            guarantee_text = "🎉 ГАРАНТ! "
            progress = 0
        else:
            if L_cards and random.random() < 0.01:
                card = random.choice(L_cards)
                await upd_guarantor(msg.from_user.id, 0)
                guarantee_text = "🌟 L-КАРТА! "
                progress = 0
            else:
                card = random.choice(normal if normal else cards)
                progress += 1
                await upd_guarantor(msg.from_user.id, progress)
                guarantee_text = ""
        
        await add_card_to_user(msg.from_user.id, card['id'])
        
        # Обновляем прогресс заданий
        await update_task_progress(msg.from_user.id, 'roll')
        
        # Проверяем достижения
        achievements = await check_achievements(msg.from_user.id)
        
        caption = f"{guarantee_text}{rarity_emoji(card['rarity'])} {card['name']}\n"
        if card['description']:
            caption += f"📝 {card['description']}\n"
        caption += f"⭐ {card['rarity']}\n📎 #{card['id']}\n"
        caption += f"📊 Гарант: {progress}/90 ({int(progress/90*100)}%)"
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption)
            else:
                await msg.answer(caption)
        except:
            await msg.answer(caption)
        
        # Уведомление о новых достижениях
        if achievements:
            for ach in achievements:
                await msg.answer(f"🏅 ДОСТИЖЕНИЕ РАЗБЛОКИРОВАНО!\n{ach['name']}: {ach['desc']}")
        
        # Проверяем все ли задания выполнены
        if await check_all_tasks_completed(msg.from_user.id):
            u2 = await get_user(msg.from_user.id)
            if not u2['bonus_roll_received']:
                await give_bonus_roll(msg.from_user.id)
                await msg.answer("🎉 Все задания выполнены! +1 бонусная крутка!")
    
    @dp.message(F.text == "👤 Профиль")
    async def profile_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        cards = await get_card_count(msg.from_user.id)
        progress = u['guarantor_progress']
        
        text = (
            f"👤 Профиль\n\n"
            f"📛 {u['username']}\n"
            f"💎 Алмазы: {u['diamonds']}\n"
            f"🎲 Крутки: {u['rolls']}\n"
            f"🎴 Карт: {cards}\n"
            f"🔄 Всего круток: {u['total_rolls']}\n"
            f"🎡 Колесо: {u['fortune_spins']} вращений\n"
            f"📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        )
        
        # Обновляем задание "зайти в профиль"
        await update_task_progress(msg.from_user.id, 'profile')
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_button(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        
        if not cards:
            await msg.answer("🎒 Инвентарь пуст", reply_markup=permanent_keyboard())
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:20]:
            text += f"{rarity_emoji(card['rarity'])} #{card['id']} {card['name']} x{card['quantity']}\n"
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        if buttons:
            await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "🏆 Лидеры")
    async def leaders_button(msg: types.Message):
        top = await get_leaders(10)
        if not top:
            await msg.answer("🏆 Пока никто не собрал карты!", reply_markup=permanent_keyboard())
            return
        
        text = "🏆 Топ-10:\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {u['username']} - {u['total']} карт\n"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5:
            await msg.answer("❌ Нужно 5💎!", reply_markup=permanent_keyboard())
            return
        
        await upd_diamonds(msg.from_user.id, -5)
        cards = await get_all_cards()
        card = random.choice(cards)
        await add_card_to_user(msg.from_user.id, card['id'])
        
        caption = f"💎 Премиум!\n{rarity_emoji(card['rarity'])} {card['name']}\n⭐ {card['rarity']}"
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption)
            else:
                await msg.answer(caption)
        except:
            await msg.answer(caption)
    
    # ==================== КОЛЕСО ФОРТУНЫ ====================
    @dp.message(F.text == "🎡 Колесо фортуны")
    async def fortune_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        
        if u['fortune_spins'] <= 0:
            # Платное вращение
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1 вращение - 1💎", callback_data="fortune_buy_1")],
                [InlineKeyboardButton(text="5 вращений - 3💎", callback_data="fortune_buy_5")],
            ])
            await msg.answer("🎡 Колесо фортуны\n\nБесплатные вращения закончились!\nМожно купить за алмазы:", reply_markup=kb)
        else:
            await spin_fortune(msg)
    
    async def spin_fortune(msg):
        # Выбираем приз
        prizes = []
        for p in FORTUNE_PRIZES:
            prizes.extend([p] * p['weight'])
        
        prize = random.choice(prizes)
        
        # Выдаем приз
        if prize['prize'] == 'roll':
            await upd_rolls(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'diamond':
            await upd_diamonds(msg.from_user.id, prize['value'])
        elif prize['prize'] == 'random_card':
            cards = await get_all_cards()
            if cards:
                card = random.choice(cards)
                await add_card_to_user(msg.from_user.id, card['id'])
        
        # Уменьшаем счетчик
        u = await get_user(msg.from_user.id)
        if u['fortune_spins'] > 0:
            await upd_fortune_spins(msg.from_user.id, u['fortune_spins'] - 1)
        
        # Обновляем задание
        await update_task_progress(msg.from_user.id, 'fortune')
        
        await msg.answer(f"🎡 Колесо фортуны!\n\n{prize['desc']}", reply_markup=permanent_keyboard())
    
    @dp.callback_query(F.data.startswith("fortune_buy_"))
    async def fortune_buy(call: types.CallbackQuery):
        amount = int(call.data.split("_")[2])
        prices = {1: 1, 5: 3}
        price = prices[amount]
        
        u = await get_user(call.from_user.id)
        if u['diamonds'] < price:
            await call.answer(f"❌ Нужно {price}💎!", show_alert=True)
            return
        
        await upd_diamonds(call.from_user.id, -price)
        await upd_fortune_spins(call.from_user.id, u['fortune_spins'] + amount)
        await call.answer(f"✅ Куплено {amount} вращений!", show_alert=True)
    
    # ==================== ЗАДАНИЯ ====================
    @dp.message(F.text == "📋 Задания")
    async def tasks_button(msg: types.Message):
        tasks = await get_daily_tasks(msg.from_user.id)
        u = await get_user(msg.from_user.id)
        
        text = "📋 Ежедневные задания:\n\n"
        task_descs = {t['type']: t['desc'] for t in TASK_TYPES}
        
        for task in tasks:
            status = "✅" if task['completed'] else "⬜"
            progress = f"{task['progress']}/{task['task_target']}"
            text += f"{status} {task_descs.get(task['task_type'], 'Задание')} ({progress})\n"
        
        if await check_all_tasks_completed(msg.from_user.id):
            if not u['bonus_roll_received']:
                await give_bonus_roll(msg.from_user.id)
                text += "\n🎉 Все задания выполнены!\nПолучена +1 бонусная крутка!"
            else:
                text += "\n✅ Бонус уже получен!"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ДОСТИЖЕНИЯ ====================
    @dp.message(F.text == "🏅 Достижения")
    async def achievements_button(msg: types.Message):
        achievements = await check_achievements(msg.from_user.id)
        u = await get_user(msg.from_user.id)
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
                text += f"{status} {ach['name']}\n   {ach['desc']}\n\n"
        
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== CALLBACK ОБРАБОТЧИКИ ====================
    @dp.callback_query(F.data.startswith("break_"))
    async def break_card(call: types.CallbackQuery):
        card_id = int(call.data.split("_")[1])
        cards = await get_user_cards(call.from_user.id)
        card = next((c for c in cards if c['id'] == card_id), None)
        
        if not card or card['quantity'] < 5:
            await call.answer("❌ Нужно 5 одинаковых!", show_alert=True)
            return
        
        if await remove_card(call.from_user.id, card_id, 5):
            await upd_diamonds(call.from_user.id, 1)
            await update_task_progress(call.from_user.id, 'break')
            await call.answer("✅ 5 карт → 1💎!", show_alert=True)
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
        ])
        await msg.answer("👑 Админ-панель:", reply_markup=kb)
    
    @dp.callback_query(F.data == "admin_add")
    async def admin_add_start(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        await call.message.answer("📝 Шаг 1/4\nВведи номер и имя:\nПример: #6 Дима")
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def add_name(msg: types.Message, state: FSMContext):
        await state.update_data(name=msg.text.strip())
        await msg.answer("📝 Шаг 2/4\nВведи описание:")
        await state.set_state(AddCardStates.waiting_for_description)
    
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def add_desc(msg: types.Message, state: FSMContext):
        await state.update_data(description=msg.text.strip())
        await msg.answer("📝 Шаг 3/4\nВыбери редкость:", reply_markup=rarity_keyboard())
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def add_rarity(call: types.CallbackQuery, state: FSMContext):
        rarity = call.data.split("_")[1]
        await state.update_data(rarity=rarity)
        await call.message.answer("📝 Шаг 4/4\nОтправь фото или напиши 'нет'")
        await state.set_state(AddCardStates.waiting_for_photo)
        await call.answer()
    
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def add_photo(msg: types.Message, state: FSMContext):
        data = await state.get_data()
        file_id = msg.photo[-1].file_id if msg.photo else None
        is_L = data['rarity'] == 'L'
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?,?,?,?,?)",
                (data['name'], data['description'], file_id, data['rarity'], is_L)
            )
            await db.commit()
        
        await msg.answer(f"✅ Карта '{data['name']}' добавлена!\n⭐ {data['rarity']}")
        await state.clear()
    
    @dp.callback_query(F.data == "admin_list")
    async def admin_list(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            return
        
        cards = await get_all_cards()
        text = "📋 Карты:\n\n"
        for c in cards:
            text += f"{rarity_emoji(c['rarity'])} #{c['id']} {c['name']} ({c['rarity']})\n"
        
        await call.message.answer(text[:4000])
        await call.answer()
    
    @dp.message(Command("give"))
    async def give_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        parts = msg.text.split()
        if len(parts) != 4:
            await msg.answer("/give ID тип количество")
            return
        
        target_id = int(parts[1])
        give_type = parts[2].lower()
        value = int(parts[3])
        
        if give_type == 'diamonds':
            await upd_diamonds(target_id, value)
        elif give_type == 'rolls':
            await upd_rolls(target_id, value)
        
        await msg.answer(f"✅ Выдано {value} {give_type}")
    
    # ==================== ЕЖЕДНЕВНЫЙ СБРОС ====================
    async def daily_reset():
        """Сброс заданий и начисление бонусов в 8:00 МСК"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Начисляем бонусы
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2, fortune_spins=1, bonus_roll_received=0")
                # Удаляем старые задания
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
