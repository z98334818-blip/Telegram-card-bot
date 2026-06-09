import asyncio
import aiosqlite
import random
import logging
import sys
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

# ==================== ФУНКЦИИ ====================
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
        async with db.execute("SELECT * FROM cards") as c:
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

async def get_user_cards(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*, uc.quantity FROM user_cards uc
            JOIN cards c ON uc.card_id=c.id
            WHERE uc.user_id=?
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

async def add_card_to_db(name, file_id, is_L=False):
    async with aiosqlite.connect(DB_PATH) as db:
        rarity = 'legendary' if is_L else 'common'
        await db.execute("INSERT INTO cards (name,file_id,rarity,is_L_card) VALUES (?,?,?,?)",
                        (name, file_id, rarity, is_L))
        await db.commit()

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Крутить (бесплатно)", callback_data="roll")],
        [InlineKeyboardButton(text="💎 Крутить за алмазы (5💎)", callback_data="prem_roll")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inv")],
        [InlineKeyboardButton(text="🏆 Лидеры", callback_data="leaders")],
        [InlineKeyboardButton(text="📢 Поддержка", url="https://t.me/your_support")],
    ])

def back_to_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_menu")]
    ])

# ==================== БОТ ====================
async def main():
    await init_db()
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # /start
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
            "Снизу есть кнопочки, нажми и начни свой путь!"
        )
        await msg.answer(text, reply_markup=main_menu())
    
    # Кнопка "Назад в меню"
    @dp.callback_query(F.data == "back_menu")
    async def back_menu(call: types.CallbackQuery):
        await call.message.edit_text("🎮 Главное меню:", reply_markup=main_menu())
        await call.answer()
    
    # Профиль
    @dp.callback_query(F.data == "profile")
    async def profile(call: types.CallbackQuery):
        u = await get_user(call.from_user.id)
        if not u:
            await call.answer("Нажми /start сначала!", show_alert=True)
            return
        
        cards = await get_card_count(call.from_user.id)
        text = (
            f"👤 Профиль\n\n"
            f"📛 {u['username']}\n"
            f"💎 Алмазы: {u['diamonds']}\n"
            f"🎲 Крутки: {u['rolls']}\n"
            f"🎴 Карт: {cards}\n"
            f"🔄 Всего круток: {u['total_rolls']}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить крутки", callback_data="buy_rolls")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_menu")]
        ])
        
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
    # Бесплатная крутка
    @dp.callback_query(F.data == "roll")
    async def roll(call: types.CallbackQuery):
        u = await get_user(call.from_user.id)
        if not u:
            await call.answer("Нажми /start!", show_alert=True)
            return
        
        if u['rolls'] <= 0:
            await call.answer("❌ Нет круток! Жди 8:00 МСК или купи за алмазы", show_alert=True)
            return
        
        await upd_rolls(call.from_user.id, -1)
        cards = await get_all_cards()
        
        if not cards:
            await call.answer("❌ В базе нет карт. Админ еще не добавил", show_alert=True)
            return
        
        # Выбираем карту
        L_cards = [c for c in cards if c['is_L_card']]
        normal = [c for c in cards if not c['is_L_card']]
        
        if L_cards and random.random() < 0.01:  # 1% шанс L
            card = random.choice(L_cards)
            prefix = "🌟 L-КАРТА! "
        else:
            card = random.choice(normal if normal else cards)
            prefix = ""
        
        await add_card_to_user(call.from_user.id, card['id'])
        
        caption = f"{prefix}🎴 {card['name']}\n⭐ Редкость: {card['rarity']}\n📎 #{card['id']}"
        
        try:
            if card['file_id']:
                await call.message.answer_photo(photo=card['file_id'], caption=caption)
            else:
                await call.message.answer(caption)
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            await call.message.answer(caption)
        
        await call.message.answer("🎮 Меню:", reply_markup=main_menu())
        await call.answer()
    
    # Премиум крутка
    @dp.callback_query(F.data == "prem_roll")
    async def prem_roll(call: types.CallbackQuery):
        u = await get_user(call.from_user.id)
        if u['diamonds'] < 5:
            await call.answer("❌ Нужно 5 алмазов!", show_alert=True)
            return
        
        await upd_diamonds(call.from_user.id, -5)
        cards = await get_all_cards()
        
        if not cards:
            await call.answer("❌ Нет карт в базе!", show_alert=True)
            return
        
        card = random.choice(cards)
        await add_card_to_user(call.from_user.id, card['id'])
        
        caption = f"💎 Премиум крутка!\n🎴 {card['name']}\n⭐ {card['rarity']}\n📎 #{card['id']}"
        
        try:
            if card['file_id']:
                await call.message.answer_photo(photo=card['file_id'], caption=caption)
            else:
                await call.message.answer(caption)
        except:
            await call.message.answer(caption)
        
        await call.answer("✅ Премиум крутка использована!", show_alert=True)
    
    # Инвентарь
    @dp.callback_query(F.data == "inv")
    async def inv(call: types.CallbackQuery):
        cards = await get_user_cards(call.from_user.id)
        
        if not cards:
            await call.message.edit_text(
                "🎒 Инвентарь пуст\n\nИспользуй крутки чтобы получить карты!",
                reply_markup=back_to_menu()
            )
            await call.answer()
            return
        
        text = "🎒 Твои карты:\n\n"
        buttons = []
        
        for card in cards[:20]:
            prefix = "🌟" if card['is_L_card'] else ""
            text += f"{prefix}#{card['id']} {card['name']} x{card['quantity']}\n"
            
            if card['quantity'] >= 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔨 Разбить {card['name']} (5→1💎)",
                        callback_data=f"break_{card['id']}"
                    )
                ])
        
        buttons.append([InlineKeyboardButton(text="🔙 В меню", callback_data="back_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    
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
            await inv(call)
        else:
            await call.answer("❌ Ошибка!", show_alert=True)
    
    # Покупка круток
    @dp.callback_query(F.data == "buy_rolls")
    async def buy_rolls(call: types.CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 крутка - 5💎", callback_data="buy_1")],
            [InlineKeyboardButton(text="5 круток - 20💎", callback_data="buy_5")],
            [InlineKeyboardButton(text="10 круток - 35💎", callback_data="buy_10")],
            [InlineKeyboardButton(text="🔙 В профиль", callback_data="profile")]
        ])
        
        await call.message.edit_text("💎 Покупка круток:", reply_markup=kb)
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
        await call.answer(f"✅ +{amount} круток за {price}💎!", show_alert=True)
        await profile(call)
    
    # Лидеры
    @dp.callback_query(F.data == "leaders")
    async def leaders(call: types.CallbackQuery):
        top = await get_leaders(10)
        
        if not top:
            await call.message.edit_text("🏆 Пока никто не собрал карты!", reply_markup=back_to_menu())
            await call.answer()
            return
        
        text = "🏆 Топ-10 коллекционеров:\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, u in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {u['username']} - {u['total']} карт\n"
        
        await call.message.edit_text(text, reply_markup=back_to_menu())
        await call.answer()
    
    # ==================== АДМИНКА ====================
# Формат добавления карты:
# /addcard Номер | Имя | Редкость
# И прикрепить фото
# Пример: /addcard 1 | Сакура | rare

# Или без фото:
# /addcard Номер | Имя | Редкость
# Пример: /addcard 1 | Сакура | common

@dp.message(Command("admin"))
async def admin_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ У вас нет доступа к админ-панели")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_help")],
        [InlineKeyboardButton(text="📋 Все карты", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить карту", callback_data="admin_del_help")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="admin_edit_help")],
        [InlineKeyboardButton(text="👤 Выдать ресурсы", callback_data="admin_give")],
    ])
    
    text = (
        "👑 Админ-панель\n\n"
        "📝 Команды:\n"
        "• /addcard # | Имя | Редкость - добавить карту\n"
        "• /delcard # - удалить карту\n"
        "• /editcard # | Имя | Редкость - изменить карту\n"
        "• /give ID тип кол-во - выдать ресурсы\n\n"
        "🌟 Редкости: common, rare, epic, legendary, L\n"
        "📸 Можно прикрепить фото к /addcard"
    )
    
    await msg.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "admin_help")
async def admin_help(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа!", show_alert=True)
        return
    
    text = (
        "📝 Как добавить карту:\n\n"
        "Отправь сообщение в формате:\n"
        "/addcard НОМЕР | ИМЯ | РЕДКОСТЬ\n\n"
        "Пример с фото:\n"
        "/addcard 1 | Сакура Харуно | rare\n"
        "(прикрепи фото к этому сообщению)\n\n"
        "Пример без фото:\n"
        "/addcard 2 | Хината | common\n\n"
        "🌟 Доступные редкости:\n"
        "• common - обычная\n"
        "• rare - редкая\n"
        "• epic - эпическая\n"
        "• legendary - легендарная (L-карта)"
    )
    
    await call.message.answer(text)
    await call.answer()

@dp.callback_query(F.data == "admin_del_help")
async def admin_del_help(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await call.message.answer(
        "🗑 Для удаления карты:\n"
        "/delcard НОМЕР\n\n"
        "Пример: /delcard 5"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_edit_help")
async def admin_edit_help(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await call.message.answer(
        "✏️ Для редактирования карты:\n"
        "/editcard НОМЕР | НОВОЕ_ИМЯ | НОВАЯ_РЕДКОСТЬ\n\n"
        "Пример: /editcard 5 | Сакура v2 | epic\n\n"
        "Чтобы изменить только фото - просто отправь\n"
        "/editcard НОМЕР с новым фото"
    )
    await call.answer()

# Добавление карты
@dp.message(Command("addcard"))
async def add_card_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа!")
        return
    
    try:
        # Убираем команду и разбираем параметры
        text = msg.text.replace("/addcard", "").strip()
        
        if not text:
            await msg.answer(
                "❌ Неверный формат!\n"
                "Используй: /addcard НОМЕР | ИМЯ | РЕДКОСТЬ\n"
                "Пример: /addcard 1 | Сакура | rare"
            )
            return
        
        # Разделяем по |
        parts = [p.strip() for p in text.split("|")]
        
        if len(parts) != 3:
            await msg.answer(
                "❌ Нужно 3 параметра через |\n"
                "Формат: НОМЕР | ИМЯ | РЕДКОСТЬ"
            )
            return
        
        card_num = parts[0]
        card_name = parts[1]
        rarity = parts[2].lower()
        
        # Проверяем редкость
        valid_rarities = ['common', 'rare', 'epic', 'legendary', 'l']
        if rarity not in valid_rarities:
            await msg.answer(f"❌ Неверная редкость! Доступны: {', '.join(valid_rarities)}")
            return
        
        # Определяем L-карту
        is_L = rarity in ['legendary', 'l']
        if is_L:
            rarity = 'legendary'
        
        # Получаем file_id из фото если есть
        file_id = None
        if msg.photo:
            file_id = msg.photo[-1].file_id
        
        # Добавляем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cards (name, file_id, rarity, is_L_card) VALUES (?, ?, ?, ?)",
                (f"#{card_num} {card_name}", file_id, rarity, is_L)
            )
            await db.commit()
        
        response = (
            f"✅ Карта успешно добавлена!\n\n"
            f"📎 #{card_num}\n"
            f"📛 {card_name}\n"
            f"⭐ Редкость: {rarity}\n"
            f"{'🌟 Это L-карта!' if is_L else ''}\n"
            f"{'🖼 С фото' if file_id else '❌ Без фото'}"
        )
        
        await msg.answer(response)
        
    except Exception as e:
        logger.error(f"Ошибка добавления карты: {e}")
        await msg.answer(f"❌ Ошибка: {e}")

# Удаление карты
@dp.message(Command("delcard"))
async def del_card_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа!")
        return
    
    try:
        card_num = msg.text.replace("/delcard", "").strip()
        
        if not card_num:
            await msg.answer("❌ Укажи номер карты!\nПример: /delcard 5")
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Ищем карту
            async with db.execute(
                "SELECT id, name FROM cards WHERE name LIKE ?",
                (f"#{card_num} %",)
            ) as c:
                card = await c.fetchone()
            
            if not card:
                await msg.answer(f"❌ Карта #{card_num} не найдена!")
                return
            
            # Удаляем
            await db.execute("DELETE FROM cards WHERE id=?", (card[0],))
            await db.execute("DELETE FROM user_cards WHERE card_id=?", (card[0],))
            await db.commit()
        
        await msg.answer(f"✅ Карта #{card_num} '{card[1]}' удалена!")
        
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await msg.answer(f"❌ Ошибка: {e}")

# Редактирование карты
@dp.message(Command("editcard"))
async def edit_card_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа!")
        return
    
    try:
        text = msg.text.replace("/editcard", "").strip()
        
        if not text:
            await msg.answer("❌ Укажи номер карты!\nПример: /editcard 5 | Новое имя | rare")
            return
        
        parts = [p.strip() for p in text.split("|")]
        card_num = parts[0]
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Ищем карту
            async with db.execute(
                "SELECT id, name, file_id, rarity FROM cards WHERE name LIKE ?",
                (f"#{card_num} %",)
            ) as c:
                card = await c.fetchone()
            
            if not card:
                await msg.answer(f"❌ Карта #{card_num} не найдена!")
                return
            
            # Если только фото
            if len(parts) == 1 and msg.photo:
                file_id = msg.photo[-1].file_id
                await db.execute("UPDATE cards SET file_id=? WHERE id=?", (file_id, card[0]))
                await db.commit()
                await msg.answer(f"✅ Фото карты #{card_num} обновлено!")
                return
            
            # Если имя и редкость
            if len(parts) == 3:
                new_name = parts[1]
                new_rarity = parts[2].lower()
                
                valid_rarities = ['common', 'rare', 'epic', 'legendary', 'l']
                if new_rarity not in valid_rarities:
                    await msg.answer(f"❌ Неверная редкость! Доступны: {', '.join(valid_rarities)}")
                    return
                
                is_L = new_rarity in ['legendary', 'l']
                if is_L:
                    new_rarity = 'legendary'
                
                await db.execute(
                    "UPDATE cards SET name=?, rarity=?, is_L_card=? WHERE id=?",
                    (f"#{card_num} {new_name}", new_rarity, is_L, card[0])
                )
                
                # Если еще и фото обновляем
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    await db.execute("UPDATE cards SET file_id=? WHERE id=?", (file_id, card[0]))
                
                await db.commit()
                
                await msg.answer(
                    f"✅ Карта #{card_num} обновлена!\n"
                    f"📛 {new_name}\n"
                    f"⭐ {new_rarity}\n"
                    f"{'🌟 L-карта!' if is_L else ''}"
                )
            else:
                await msg.answer("❌ Неверный формат!\n/editcard НОМЕР | ИМЯ | РЕДКОСТЬ")
                
    except Exception as e:
        logger.error(f"Ошибка редактирования: {e}")
        await msg.answer(f"❌ Ошибка: {e}")

# Список карт
@dp.callback_query(F.data == "admin_list")
async def admin_list(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа!", show_alert=True)
        return
    
    cards = await get_all_cards()
    if not cards:
        await call.message.answer("📋 В базе нет карт")
        await call.answer()
        return
    
    # Группируем по редкости
    rarity_order = {'legendary': '🌟 L-карты', 'epic': '🟣 Эпические', 'rare': '🔵 Редкие', 'common': '⚪ Обычные'}
    grouped = {}
    
    for card in cards:
        rarity = card['rarity']
        if rarity not in grouped:
            grouped[rarity] = []
        grouped[rarity].append(card)
    
    text = "📋 Все карты:\n\n"
    
    for rarity, title in rarity_order.items():
        if rarity in grouped:
            text += f"{title}:\n"
            for card in grouped[rarity][:10]:
                has_photo = "🖼" if card['file_id'] else "❌"
                text += f"  #{card['name'].split()[0]} {card['name'].split(' ', 1)[1] if ' ' in card['name'] else card['name']} {has_photo}\n"
            text += "\n"
    
    text += f"Всего карт: {len(cards)}"
    
    # Разбиваем на части если слишком длинное
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await call.message.answer(text[i:i+4000])
    else:
        await call.message.answer(text)
    
    await call.answer()

# Выдача ресурсов
@dp.callback_query(F.data == "admin_give")
async def admin_give(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("❌ Нет доступа!", show_alert=True)
        return
    
    await call.message.answer(
        "📝 Используй команду:\n"
        "/give ID ТИП КОЛИЧЕСТВО\n\n"
        "Типы:\n"
        "• diamonds - алмазы\n"
        "• rolls - крутки\n\n"
        "Пример: /give 123456789 diamonds 100"
    )
    await call.answer()

@dp.message(Command("give"))
async def give_cmd(msg: types.Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer("❌ Нет доступа!")
        return
    
    try:
        parts = msg.text.split()
        if len(parts) != 4:
            await msg.answer("❌ Формат: /give ID ТИП КОЛИЧЕСТВО")
            return
        
        target_id = int(parts[1])
        give_type = parts[2].lower()
        value = int(parts[3])
        
        if give_type == 'diamonds':
            await upd_diamonds(target_id, value)
            await msg.answer(f"✅ Выдано {value}💎 пользователю {target_id}")
        elif give_type == 'rolls':
            await upd_rolls(target_id, value)
            await msg.answer(f"✅ Выдано {value}🎲 пользователю {target_id}")
        else:
            await msg.answer("❌ Неверный тип! Используй diamonds или rolls")
            
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}")
