import asyncio
import aiosqlite
import random
import logging
import sys
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
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
                total_rolls INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT DEFAULT '',
                file_id TEXT,
                rarity TEXT DEFAULT 'common',
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
# Постоянная клавиатура (всегда видна внизу)
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

# Инлайн клавиатура для профиля
def profile_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить крутки", callback_data="buy_rolls")],
        [InlineKeyboardButton(text="📋 Подробнее о карте", callback_data="card_info")],
    ])

# Инлайн клавиатура покупки круток
def buy_rolls_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 крутка - 5💎", callback_data="buy_1")],
        [InlineKeyboardButton(text="5 круток - 20💎", callback_data="buy_5")],
        [InlineKeyboardButton(text="10 круток - 35💎", callback_data="buy_10")],
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
            "• +2 алмаза 💎\n\n"
            "🎴 Собирай коллекцию!\n"
            "🏆 Соревнуйся с другими\n\n"
            "Используй кнопки меню внизу 👇"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== ПОСТОЯННЫЕ КНОПКИ ====================
    
    # 🎲 Крутить
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
            await msg.answer("❌ В базе нет карт. Админ еще не добавил", reply_markup=permanent_keyboard())
            return
        
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        
        if L_cards and random.random() < 0.01:
            card = random.choice(L_cards)
            prefix = "🌟 L-КАРТА! "
        else:
            card = random.choice(normal if normal else cards)
            prefix = ""
        
        await add_card_to_user(msg.from_user.id, card['id'])
        
        # Формируем описание
        caption = f"{prefix}🎴 {card['name']}\n"
        if card['description']:
            caption += f"📝 {card['description']}\n"
        caption += f"⭐ Редкость: {card['rarity']}\n📎 ID: #{card['id']}"
        
        try:
            if card['file_id']:
                await msg.answer_photo(photo=card['file_id'], caption=caption, reply_markup=permanent_keyboard())
            else:
                await msg.answer(caption, reply_markup=permanent_keyboard())
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            await msg.answer(caption, reply_markup=permanent_keyboard())
    
    # 👤 Профиль
    @dp.message(F.text == "👤 Профиль")
    async def profile_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if not u:
            await msg.answer("Нажми /start сначала!", reply_markup=permanent_keyboard())
            return
        
        cards = await get_card_count(msg.from_user.id)
        text = (
            f"👤 Профиль\n\n"
            f"📛 {u['username']}\n"
            f"💎 Алмазы: {u['diamonds']}\n"
            f"🎲 Крутки: {u['rolls']}\n"
            f"🎴 Карт собрано: {cards}\n"
            f"🔄 Всего круток: {u['total_rolls']}"
        )
        
        await msg.answer(text, reply_markup=profile_inline())
    
    # 🎒 Инвентарь
    @dp.message(F.text == "🎒 Инвентарь")
    async def inv_button(msg: types.Message):
        cards = await get_user_cards(msg.from_user.id)
        
        if not cards:
            await msg.answer("🎒 Инвентарь пуст\n\nИспользуй 🎲 Крутить чтобы получить карты!", reply_markup=permanent_keyboard())
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:20]:
            prefix = "🌟" if card['is_L_card'] else ""
            desc = f" - {card['description'][:30]}..." if card['description'] else ""
            text += f"{prefix}#{card['id']} {card['name']}{desc} x{card['quantity']}\n"
            
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} {card['name']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        if buttons:
            buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_inv")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.answer(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=permanent_keyboard())
    
    # 🏆 Лидеры
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
    
    # 💎 Премиум крутка
    @dp.message(F.text == "💎 Премиум крутка")
    async def prem_button(msg: types.Message):
        u = await get_user(msg.from_user.id)
        if u['diamonds'] < 5:
            await msg.answer("❌ Нужно 5 алмазов! Используй разбитие карт в инвентаре", reply_markup=permanent_keyboard())
            return
        
        await upd_diamonds(msg.from_user.id, -5)
        cards = await get_all_cards()
        
        if not cards:
            await msg.answer("❌ Нет карт в базе!", reply_markup=permanent_keyboard())
            return
        
        card = random.choice(cards)
        await add_card_to_user(msg.from_user.id, card['id'])
        
        caption = f"💎 Премиум крутка!\n🎴 {card['name']}\n"
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
    
    # ❓ Помощь
    @dp.message(F.text == "❓ Помощь")
    async def help_button(msg: types.Message):
        text = (
            "❓ Как играть:\n\n"
            "🎲 Крутить - бесплатная крутка (2 в день)\n"
            "💎 Премиум крутка - крутка за 5 алмазов\n"
            "👤 Профиль - твои ресурсы\n"
            "🎒 Инвентарь - твои карты\n"
            "🏆 Лидеры - топ игроков\n\n"
            "💡 Советы:\n"
            "• Собирай 5 одинаковых карт чтобы разбить в 1💎\n"
            "• Покупай крутки за алмазы в профиле\n"
            "• L-карты самые редкие (шанс 1%)\n"
            "• Бонусы каждый день в 8:00 МСК\n\n"
            "📢 По вопросам: @your_support"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    # ==================== CALLBACK ОБРАБОТЧИКИ ====================
    
    # Разбить карты
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
    
    # Обновить инвентарь
    @dp.callback_query(F.data == "refresh_inv")
    async def refresh_inv(call: types.CallbackQuery):
        cards = await get_user_cards(call.from_user.id)
        
        if not cards:
            await call.message.edit_text("🎒 Инвентарь пуст")
            await call.answer()
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:20]:
            prefix = "🌟" if card['is_L_card'] else ""
            desc = f" - {card['description'][:30]}..." if card['description'] else ""
            text += f"{prefix}#{card['id']} {card['name']}{desc} x{card['quantity']}\n"
            
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить #{card['id']} {card['name']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        if buttons:
            buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_inv")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await call.message.edit_text(text, reply_markup=kb)
        else:
            await call.message.edit_text(text)
        
        await call.answer("Обновлено!")
    
    # Покупка круток
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
    
    # Информация о карте
    @dp.callback_query(F.data == "card_info")
    async def card_info_help(call: types.CallbackQuery):
        await call.message.answer(
            "📋 Чтобы посмотреть информацию о карте, отправь её ID:\n"
            "Например: /card 5\n\n"
            "ID карты можно найти в инвентаре.",
            reply_markup=permanent_keyboard()
        )
        await call.answer()
    
    # ==================== КОМАНДЫ ====================
    
    @dp.message(Command("card"))
    async def card_info(msg: types.Message):
        try:
            card_id = int(msg.text.replace("/card", "").strip())
            card = await get_card_by_id(card_id)
            
            if not card:
                await msg.answer(f"❌ Карта #{card_id} не найдена")
                return
            
            text = f"🎴 {card['name']}\n"
            if card['description']:
                text += f"📝 Описание: {card['description']}\n"
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
    
    @dp.message(Command("menu"))
    async def menu_cmd(msg: types.Message):
        await msg.answer("🎮 Используй кнопки внизу экрана 👇", reply_markup=permanent_keyboard())
    
    # ==================== АДМИНКА ====================
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        text = (
            "👑 Админ-панель\n\n"
            "📝 Добавить карту:\n"
            "/addcard Имя | Описание | Редкость\n"
            "(можно прикрепить фото)\n\n"
            "📋 Команды:\n"
            "/cards - список карт\n"
            "/card ID - инфо о карте\n"
            "/editcard ID | Имя | Описание | Редкость\n"
            "/delcard ID - удалить карту\n"
            "/give ID тип кол-во - выдать\n\n"
            "🌟 Редкости: common, rare, epic, legendary"
        )
        await msg.answer(text, reply_markup=permanent_keyboard())
    
    @dp.message(Command("addcard"))
    async def addcard(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        try:
            text = msg.text.replace("/addcard", "").strip()
            
            if not text:
                await msg.answer(
                    "❌ Формат:\n"
                    "/addcard Имя | Описание | Редкость\n\n"
                    "Примеры:\n"
                    "/addcard Сакура | Девушка из Наруто | rare\n"
                    "/addcard Хината | Наследница клана Хьюга | common\n\n"
                    "Можно прикрепить фото к сообщению!"
                )
                return
            
            # Разбираем параметры
            parts = [p.strip() for p in text.split("|")]
            
            name = parts[0] if len(parts) > 0 else "Без имени"
            description = parts[1] if len(parts) > 1 else ""
            rarity = parts[2].lower() if len(parts) > 2 else "common"
            
            # Проверка редкости
            if rarity not in ['common', 'rare', 'epic', 'legendary']:
                rarity = 'common'
            
            is_L = rarity == 'legendary'
            
            # Фото
            file_id = msg.photo[-1].file_id if msg.photo else None
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO cards (name, description, file_id, rarity, is_L_card) VALUES (?, ?, ?, ?, ?)",
                    (name, description, file_id, rarity, is_L)
                )
                await db.commit()
            
            resp = f"✅ Карта добавлена!\n\n📛 {name}"
            if description:
                resp += f"\n📝 {description}"
            resp += f"\n⭐ Редкость: {rarity}"
            if is_L:
                resp += "\n🌟 L-карта!"
            if file_id:
                resp += "\n🖼 С фото"
            
            await msg.answer(resp, reply_markup=permanent_keyboard())
            
        except Exception as e:
            logger.error(f"Ошибка добавления: {e}")
            await msg.answer(f"❌ Ошибка: {e}")
    
    @dp.message(Command("editcard"))
    async def editcard(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        try:
            text = msg.text.replace("/editcard", "").strip()
            parts = [p.strip() for p in text.split("|")]
            
            if len(parts) < 2:
                await msg.answer("❌ Формат: /editcard ID | Имя | Описание | Редкость")
                return
            
            card_id = int(parts[0])
            name = parts[1] if len(parts) > 1 else None
            description = parts[2] if len(parts) > 2 else None
            rarity = parts[3].lower() if len(parts) > 3 else None
            
            if rarity and rarity not in ['common', 'rare', 'epic', 'legendary']:
                await msg.answer("❌ Неверная редкость!")
                return
            
            is_L = rarity == 'legendary' if rarity else None
            file_id = msg.photo[-1].file_id if msg.photo else None
            
            async with aiosqlite.connect(DB_PATH) as db:
                if name:
                    await db.execute("UPDATE cards SET name=? WHERE id=?", (name, card_id))
                if description is not None:
                    await db.execute("UPDATE cards SET description=? WHERE id=?", (description, card_id))
                if rarity:
                    await db.execute("UPDATE cards SET rarity=?, is_L_card=? WHERE id=?", (rarity, is_L, card_id))
                if file_id:
                    await db.execute("UPDATE cards SET file_id=? WHERE id=?", (file_id, card_id))
                await db.commit()
            
            await msg.answer(f"✅ Карта #{card_id} обновлена!")
            
        except Exception as e:
            await msg.answer(f"❌ Ошибка: {e}")
    
    @dp.message(Command("cards"))
    async def list_cards(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        cards = await get_all_cards()
        if not cards:
            await msg.answer("Нет карт в базе")
            return
        
        text = "📋 Все карты:\n\n"
        for c in cards[:30]:
            prefix = "🌟" if c['is_L_card'] else "  "
            photo = "🖼" if c['file_id'] else "❌"
            desc = f" - {c['description'][:20]}" if c['description'] else ""
            text += f"{prefix} #{c['id']} {c['name']}{desc} ({c['rarity']}) {photo}\n"
        
        await msg.answer(text[:4000])
    
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
