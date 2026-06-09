import asyncio
import aiosqlite
import random
import logging
import sys
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
                guarantor_progress INTEGER DEFAULT 0
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
        await db.commit()
        logger.info("✅ База данных готова")

# ==================== СОСТОЯНИЯ ДЛЯ FSM ====================
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

# ==================== КЛАВИАТУРЫ ====================
def permanent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎲 Крутить"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="💎 Премиум крутка"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        persistent=True
    )

def rarity_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="R - Обычная", callback_data="rarity_R")],
        [InlineKeyboardButton(text="SR - Редкая", callback_data="rarity_SR")],
        [InlineKeyboardButton(text="SSR - Эпическая", callback_data="rarity_SSR")],
        [InlineKeyboardButton(text="🌟 L - Легендарная", callback_data="rarity_L")],
    ])

def profile_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить крутки", callback_data="buy_rolls")],
    ])

def buy_rolls_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 крутка - 5💎", callback_data="buy_1")],
        [InlineKeyboardButton(text="5 круток - 20💎", callback_data="buy_5")],
        [InlineKeyboardButton(text="10 круток - 35💎", callback_data="buy_10")],
    ])

def rarity_emoji(rarity):
    emojis = {
        'R': '⚪',
        'SR': '🔵',
        'SSR': '🟣',
        'L': '🌟'
    }
    return emojis.get(rarity, '⚪')

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
            "• +2 алмаза 💎\n\n"
            "🎴 Собирай коллекцию!\n"
            "🌟 L-гарант: каждые 90 круток без L\n"
            "🏆 Соревнуйся с другими\n\n"
            "Используй кнопки меню внизу 👇"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ПОСТОЯННЫЕ КНОПКИ ====================
    
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
        cards = await get_all_cards()
        
        if not cards:
            await msg.answer("❌ В базе нет карт", reply_markup=permanent_keyboard())
            return
        
        # Получаем прогресс гаранта
        progress = u['guarantor_progress']
        
        # Проверяем гарант (90 круток без L)
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        
        is_guaranteed = progress >= 90
        
        if is_guaranteed and L_cards:
            # Гарантированная L-карта
            card = random.choice(L_cards)
            await upd_guarantor(msg.from_user.id, 0)  # Сбрасываем гарант
            guarantee_text = "🎉 ГАРАНТИРОВАННАЯ L-КАРТА!\n"
            progress = 0
        else:
            # Обычная крутка
            if L_cards and random.random() < 0.01:  # 1% шанс
                card = random.choice(L_cards)
                await upd_guarantor(msg.from_user.id, 0)  # Сброс при выпадении L
                guarantee_text = "🌟 ВЫПАЛА L-КАРТА!\n"
                progress = 0
            else:
                card = random.choice(normal if normal else cards)
                new_progress = progress + 1
                await upd_guarantor(msg.from_user.id, new_progress)
                guarantee_text = ""
                progress = new_progress
        
        await add_card_to_user(msg.from_user.id, card['id'])
        
        # Формируем сообщение
        rarity_symbol = rarity_emoji(card['rarity'])
        caption = f"{guarantee_text}"
        caption += f"{rarity_symbol} {card['name']}\n"
        if card['description']:
            caption += f"📝 {card['description']}\n"
        caption += f"⭐ Редкость: {card['rarity']}\n"
        caption += f"📎 ID: #{card['id']}\n"
        caption += f"📊 Прогресс L-гаранта: {progress}/90 ({int(progress/90*100)}%)"
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=permanent_keyboard())
            else:
                await msg.answer(caption, reply_markup=permanent_keyboard())
        except Exception as e:
            await msg.answer(caption, reply_markup=permanent_keyboard())
    
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
            f"📊 L-гарант: {progress}/90 ({int(progress/90*100)}%)"
        )
        
        await msg.answer(text, reply_markup=profile_inline())
    
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_button(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        
        if not cards:
            await msg.answer("🎒 Инвентарь пуст\n\nИспользуй 🎲 Крутить!", reply_markup=permanent_keyboard())
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:20]:
            rarity_symbol = rarity_emoji(card['rarity'])
            desc = f" - {card['description'][:30]}..." if card['description'] else ""
            text += f"{rarity_symbol} #{card['id']} {card['name']}{desc} x{card['quantity']}\n"
            
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} {card['name']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        if buttons:
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
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
    
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5:
            await msg.answer("❌ Нужно 5 алмазов!", reply_markup=permanent_keyboard())
            return
        
        await upd_diamonds(msg.from_user.id, -5)
        cards = await get_all_cards()
        
        if not cards:
            await msg.answer("❌ Нет карт в базе!", reply_markup=permanent_keyboard())
            return
        
        card = random.choice(cards)
        await add_card_to_user(msg.from_user.id, card['id'])
        
        # Прогресс гаранта не меняется при премиум крутках
        progress = u['guarantor_progress']
        rarity_symbol = rarity_emoji(card['rarity'])
        
        caption = f"💎 Премиум крутка!\n"
        caption += f"{rarity_symbol} {card['name']}\n"
        if card['description']:
            caption += f"📝 {card['description']}\n"
        caption += f"⭐ Редкость: {card['rarity']}\n"
        caption += f"📎 #{card['id']}\n"
        caption += f"📊 L-гарант: {progress}/90"
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=permanent_keyboard())
            else:
                await msg.answer(caption, reply_markup=permanent_keyboard())
        except:
            await msg.answer(caption, reply_markup=permanent_keyboard())
    
    @dp.message(F.text == "❓ Помощь")
    async def help_button(msg: types.Message):
        text = (
            "❓ Как играть:\n\n"
            "🎲 Крутить - бесплатная крутка (2 в день)\n"
            "💎 Премиум крутка - крутка за 5 алмазов\n"
            "👤 Профиль - твои ресурсы и гарант\n"
            "🎒 Инвентарь - твои карты\n"
            "🏆 Лидеры - топ игроков\n\n"
            "🌟 Система гаранта:\n"
            "• Каждые 90 круток без L-карты\n"
            "• Ты получаешь гарантированную L!\n"
            "• Прогресс виден в профиле\n\n"
            "💡 Советы:\n"
            "• 5 одинаковых карт = 1💎\n"
            "• Покупай крутки в профиле\n"
            "• Редкости: R → SR → SSR → L\n\n"
            "📢 По вопросам: @your_support"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== CALLBACK ОБРАБОТЧИКИ ====================
    
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
            await call.answer("✅ 5 карт → 1💎!", show_alert=True)
        else:
            await call.answer("❌ Ошибка!", show_alert=True)
    
    @dp.callback_query(F.data == "buy_rolls")
    async def buy_rolls(call: types.CallbackQuery):
        await call.message.answer("💎 Выбери количество:", reply_markup=buy_rolls_inline())
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
    
    # ==================== КОМАНДЫ ====================
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg: types.Message):
        await msg.answer("🎮 Используй кнопки внизу экрана 👇", reply_markup=permanent_keyboard())
    
    @dp.message(Command("card"))
    async def card_info(msg: types.Message):
        try:
            card_id = int(msg.text.replace("/card", "").strip())
            card = await get_card_by_id(card_id)
            
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена")
                return
            
            rarity_symbol = rarity_emoji(card['rarity'])
            text = f"{rarity_symbol} {card['name']}\n"
            if card['description']:
                text += f"📝 {card['description']}\n"
            text += f"⭐ Редкость: {card['rarity']}\n"
            text += f"📎 ID: #{card['id']}\n"
            if card['is_L_card']:
                text += "🌟 L-КАРТА!\n"
            
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=text, reply_markup=permanent_keyboard())
            else:
                await msg.answer(text, reply_markup=permanent_keyboard())
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
            [InlineKeyboardButton(text="🗑 Удалить карту", callback_data="admin_del")],
        ])
        
        await msg.answer("👑 Админ-панель:", reply_markup=kb)
    
    # Начало добавления карты
    @dp.callback_query(F.data == "admin_add")
    async def admin_add_start(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ Нет доступа!", show_alert=True)
            return
        
        await call.message.answer(
            "📝 Шаг 1/4\n\n"
            "Введи номер и имя персонажа:\n"
            "Формат: #НОМЕР ИМЯ\n\n"
            "Пример: #6 Дима"
        )
        await state.set_state(AddCardStates.waiting_for_name)
        await call.answer()
    
    # Шаг 1: Имя
    @dp.message(StateFilter(AddCardStates.waiting_for_name))
    async def add_card_name(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        text = msg.text.strip()
        await state.update_data(name=text)
        
        await msg.answer(
            "📝 Шаг 2/4\n\n"
            "Введи описание персонажа:\n\n"
            "Пример: Какой-то там вампир"
        )
        await state.set_state(AddCardStates.waiting_for_description)
    
    # Шаг 2: Описание
    @dp.message(StateFilter(AddCardStates.waiting_for_description))
    async def add_card_desc(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        description = msg.text.strip()
        await state.update_data(description=description)
        
        await msg.answer(
            "📝 Шаг 3/4\n\n"
            "Выбери редкость карты:",
            reply_markup=rarity_keyboard()
        )
        await state.set_state(AddCardStates.waiting_for_rarity)
    
    # Шаг 3: Редкость (через callback)
    @dp.callback_query(StateFilter(AddCardStates.waiting_for_rarity), F.data.startswith("rarity_"))
    async def add_card_rarity(call: types.CallbackQuery, state: FSMContext):
        if call.from_user.id not in ADMIN_IDS:
            return
        
        rarity = call.data.split("_")[1]  # R, SR, SSR, L
        await state.update_data(rarity=rarity)
        
        await call.message.answer(
            "📝 Шаг 4/4\n\n"
            "Отправь фото карты\n"
            "Или напиши 'нет' если без фото"
        )
        await state.set_state(AddCardStates.waiting_for_photo)
        await call.answer()
    
    # Шаг 4: Фото
    @dp.message(StateFilter(AddCardStates.waiting_for_photo))
    async def add_card_photo(msg: types.Message, state: FSMContext):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        data = await state.get_data()
        name = data['name']
        description = data['description']
        rarity = data['rarity']
        
        # Проверяем фото
        file_id = None
        if msg.photo:
            file_id = msg.photo[-1].file_id
        elif msg.text and msg.text.lower() == 'нет':
            file_id = None
        else:
            await msg.answer("❌ Отправь фото или напиши 'нет'")
            return
        
        is_L = rarity == 'L'
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?, ?, ?, ?, ?)",
                (name, description, file_id, rarity, is_L)
            )
            await db.commit()
        
        rarity_names = {'R': 'Обычная', 'SR': 'Редкая', 'SSR': 'Эпическая', 'L': '🌟 Легендарная'}
        
        response = (
            f"✅ Карта добавлена!\n\n"
            f"📛 {name}\n"
            f"📝 {description}\n"
            f"⭐ Редкость: {rarity} - {rarity_names.get(rarity, rarity)}\n"
            f"{'🖼 С фото' if file_id else '❌ Без фото'}"
        )
        
        await msg.answer(response, reply_markup=permanent_keyboard())
        await state.clear()
    
    # Список карт
    @dp.callback_query(F.data == "admin_list")
    async def admin_list(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ Нет доступа!", show_alert=True)
            return
        
        cards = await get_all_cards()
        if not cards:
            await call.message.answer("Нет карт в базе")
            await call.answer()
            return
        
        text = "📋 Все карты:\n\n"
        for c in cards:
            rarity_symbol = rarity_emoji(c['rarity'])
            photo = "🖼" if c['file_id'] else "❌"
            desc = f" - {c['description'][:30]}" if c['description'] else ""
            text += f"{rarity_symbol} #{c['id']} {c['name']}{desc} ({c['rarity']}) {photo}\n"
        
        # Разбиваем на части
        for i in range(0, len(text), 4000):
            await call.message.answer(text[i:i+4000])
        await call.answer()
    
    # Удаление карты
    @dp.callback_query(F.data == "admin_del")
    async def admin_del_start(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ Нет доступа!", show_alert=True)
            return
        
        await call.message.answer(
            "🗑 Для удаления отправь:\n"
            "/delcard ID_карты\n\n"
            "Пример: /delcard 5"
        )
        await call.answer()
    
    @dp.message(Command("delcard"))
    async def delcard(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        try:
            card_id = int(msg.text.replace("/delcard", "").strip())
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cards WHERE id=?", (card_id,))
                await db.execute("DELETE FROM user_cards WHERE card_id=?", (card_id,))
                await db.commit()
            
            await msg.answer(f"✅ Карта #{card_id} удалена")
        except:
            await msg.answer("❌ Формат: /delcard ID")
    
    @dp.message(Command("give"))
    async def give_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        try:
            parts = msg.text.split()
            if len(parts) != 4:
                await msg.answer("❌ Формат: /give ID тип количество")
                return
            
            target_id = int(parts[1])
            give_type = parts[2].lower()
            value = int(parts[3])
            
            if give_type == 'diamonds':
                await upd_diamonds(target_id, value)
                await msg.answer(f"✅ +{value}💎 пользователю {target_id}")
            elif give_type == 'rolls':
                await upd_rolls(target_id, value)
                await msg.answer(f"✅ +{value}🎲 пользователю {target_id}")
            else:
                await msg.answer("❌ Типы: diamonds, rolls")
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    
    # ==================== ЕЖЕДНЕВНЫЙ БОНУС ====================
    async def daily_bonus():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2")
                await db.commit()
            logger.info("✅ Ежедневные бонусы начислены!")
        except Exception as e:
            logger.error(f"Ошибка бонусов: {e}")
    
    # ==================== ЗАПУСК ====================
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_bonus, 'cron', hour=8, minute=0)
    scheduler.start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
