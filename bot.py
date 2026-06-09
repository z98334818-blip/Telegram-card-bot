import asyncio
import aiosqlite
import random
import logging
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Импорт конфига
try:
    from config import BOT_TOKEN, ADMIN_IDS, DB_PATH
except:
    BOT_TOKEN = "ТОКЕН"
    ADMIN_IDS = []
    DB_PATH = "bot.db"

# =================== БАЗА ДАННЫХ ===================
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                type TEXT,
                value INTEGER,
                uses_left INTEGER DEFAULT 1
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

# =================== ФУНКЦИИ БД ===================
async def create_user(user_id, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def add_card_to_db(name, file_id, is_L=False):
    async with aiosqlite.connect(DB_PATH) as db:
        rarity = 'legendary' if is_L else 'common'
        await db.execute(
            "INSERT INTO cards (name, file_id, rarity, is_L_card) VALUES (?, ?, ?, ?)",
            (name, file_id, rarity, is_L)
        )
        await db.commit()

async def get_all_cards():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards") as cursor:
            return await cursor.fetchall()

async def add_card_to_user(user_id, card_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO user_cards (user_id, card_id, quantity) VALUES (?, ?, 1)
            ON CONFLICT(user_id, card_id) DO UPDATE SET quantity = quantity + 1
        """, (user_id, card_id))
        await db.commit()

async def update_rolls(user_id, delta):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rolls = rolls + ?, total_rolls = total_rolls + ? WHERE user_id = ?", 
                        (delta, abs(delta), user_id))
        await db.commit()

async def update_diamonds(user_id, delta):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?", 
                        (delta, user_id))
        await db.commit()

async def get_user_cards(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*, uc.quantity 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.id 
            WHERE uc.user_id = ?
        """, (user_id,)) as cursor:
            return await cursor.fetchall()

async def remove_card(user_id, card_id, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT quantity FROM user_cards WHERE user_id = ? AND card_id = ?",
            (user_id, card_id)
        )
        row = await cursor.fetchone()
        if row and row[0] >= qty:
            if row[0] == qty:
                await db.execute("DELETE FROM user_cards WHERE user_id = ? AND card_id = ?",
                               (user_id, card_id))
            else:
                await db.execute(
                    "UPDATE user_cards SET quantity = quantity - ? WHERE user_id = ? AND card_id = ?",
                    (qty, user_id, card_id)
                )
            await db.commit()
            return True
        return False

async def get_card_count(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(quantity) FROM user_cards WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] or 0

async def get_leaders(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.user_id, u.username, SUM(uc.quantity) as total
            FROM users u
            LEFT JOIN user_cards uc ON u.user_id = uc.user_id
            GROUP BY u.user_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
        """, (limit,)) as cursor:
            return await cursor.fetchall()

# =================== КЛАВИАТУРЫ ===================
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Крутить (бесплатно)", callback_data="roll")],
        [InlineKeyboardButton(text="💎 Крутить за алмазы (5💎)", callback_data="prem_roll")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inv")],
        [InlineKeyboardButton(text="💱 Биржа", callback_data="market_menu")],
        [InlineKeyboardButton(text="🏆 Лидеры", callback_data="leaders")],
        [InlineKeyboardButton(text="🎫 Промокод", callback_data="promo")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

# =================== ОБРАБОТЧИКИ ===================
router = Router()

@router.message(CommandStart())
async def start(message: types.Message):
    await create_user(message.from_user.id, message.from_user.username or "Аноним")
    text = (
        "✨ Приветствую тебя в боте с картами! ✨\n\n"
        "🎲 Каждый день в 8:00 МСК:\n"
        "• +2 бесплатные крутки\n"
        "• +2 алмаза\n\n"
        "🎴 Собирай коллекцию!\n"
        "💱 Торгуй на бирже\n"
        "🏆 Соревнуйся с другими"
    )
    await message.answer(text, reply_markup=main_menu_kb())

@router.message(Command("menu"))
async def menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "main_menu")
async def show_menu(call: types.CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb())
    await call.answer()

@router.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    user = await get_user(call.from_user.id)
    if not user:
        await call.answer("Нажми /start сначала!")
        return
    
    cards = await get_card_count(call.from_user.id)
    
    text = (
        f"👤 {user['username']}\n"
        f"💎 Алмазы: {user['diamonds']}\n"
        f"🎲 Крутки: {user['rolls']}\n"
        f"🎴 Карт собрано: {cards}\n"
        f"🔄 Всего круток: {user['total_rolls']}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить крутки", callback_data="buy_rolls")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data == "roll")
async def roll(call: types.CallbackQuery):
    user = await get_user(call.from_user.id)
    
    if user['rolls'] <= 0:
        await call.answer("❌ Нет круток! Жди 8:00 МСК или купи за алмазы.", show_alert=True)
        return
    
    await update_rolls(call.from_user.id, -1)
    cards = await get_all_cards()
    
    if not cards:
        await call.answer("❌ В базе нет карт!", show_alert=True)
        return
    
    L_cards = [c for c in cards if c['is_L_card']]
    normal_cards = [c for c in cards if not c['is_L_card']]
    
    if L_cards and random.random() < 0.01:
        card = random.choice(L_cards)
        prefix = "🌟 L-КАРТА! "
    else:
        card = random.choice(normal_cards if normal_cards else cards)
        prefix = ""
    
    await add_card_to_user(call.from_user.id, card['id'])
    
    caption = f"{prefix}🎴 {card['name']}\n⭐ Редкость: {card['rarity']}\n📎 #{card['id']}"
    
    try:
        if card['file_id']:
            await call.message.answer_photo(photo=card['file_id'], caption=caption)
        else:
            await call.message.answer(caption)
    except Exception as e:
        await call.message.answer(caption)
    
    await call.message.answer("Меню:", reply_markup=main_menu_kb())
    await call.answer()

@router.callback_query(F.data == "prem_roll")
async def prem_roll(call: types.CallbackQuery):
    user = await get_user(call.from_user.id)
    
    if user['diamonds'] < 5:
        await call.answer("❌ Нужно 5 алмазов!", show_alert=True)
        return
    
    await update_diamonds(call.from_user.id, -5)
    cards = await get_all_cards()
    
    if not cards:
        await call.answer("❌ В базе нет карт!", show_alert=True)
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
    
    await call.answer()

@router.callback_query(F.data == "inv")
async def inventory(call: types.CallbackQuery):
    cards = await get_user_cards(call.from_user.id)
    
    if not cards:
        await call.message.edit_text("🎒 Инвентарь пуст", reply_markup=back_kb())
        await call.answer()
        return
    
    text = "🎒 Ваши карты:\n\n"
    buttons = []
    
    for card in cards[:20]:
        prefix = "🌟" if card['is_L_card'] else ""
        text += f"{prefix} #{card['id']} {card['name']} x{card['quantity']}\n"
        buttons.append([
            InlineKeyboardButton(
                text=f"🔨 Разбить {card['name']}",
                callback_data=f"break_{card['id']}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("break_"))
async def break_card(call: types.CallbackQuery):
    card_id = int(call.data.split("_")[1])
    cards = await get_user_cards(call.from_user.id)
    card = next((c for c in cards if c['id'] == card_id), None)
    
    if not card or card['quantity'] < 5:
        await call.answer("❌ Нужно 5 одинаковых карт!", show_alert=True)
        return
    
    if await remove_card(call.from_user.id, card_id, 5):
        await update_diamonds(call.from_user.id, 1)
        await call.answer("✅ 5 карт разбито в 1💎!", show_alert=True)
        await inventory(call)
    else:
        await call.answer("❌ Ошибка!", show_alert=True)

@router.callback_query(F.data == "buy_rolls")
async def buy_rolls(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 крутка - 5💎", callback_data="buy_1")],
        [InlineKeyboardButton(text="5 круток - 20💎", callback_data="buy_5")],
        [InlineKeyboardButton(text="10 круток - 35💎", callback_data="buy_10")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile")]
    ])
    
    await call.message.edit_text("💎 Покупка круток:", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(call: types.CallbackQuery):
    amount = int(call.data.split("_")[1])
    prices = {1: 5, 5: 20, 10: 35}
    price = prices[amount]
    
    user = await get_user(call.from_user.id)
    if user['diamonds'] < price:
        await call.answer(f"❌ Нужно {price}💎!", show_alert=True)
        return
    
    await update_diamonds(call.from_user.id, -price)
    await update_rolls(call.from_user.id, amount)
    await call.answer(f"✅ Куплено {amount} круток!", show_alert=True)
    await profile(call)

@router.callback_query(F.data == "leaders")
async def leaders(call: types.CallbackQuery):
    top = await get_leaders(10)
    
    if not top:
        await call.message.edit_text("🏆 Пока никто не собрал карты!", reply_markup=back_kb())
        await call.answer()
        return
    
    text = "🏆 Топ-10 коллекционеров:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    
    for i, user in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {user['username']} - {user['total']} карт\n"
    
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()

@router.callback_query(F.data == "market_menu")
async def market(call: types.CallbackQuery):
    await call.message.edit_text(
        "💱 Биржа\n\nЗдесь можно купить/продать карты.\nФункция в разработке",
        reply_markup=back_kb()
    )
    await call.answer()

@router.callback_query(F.data == "promo")
async def promo(call: types.CallbackQuery):
    await call.message.edit_text(
        "🎫 Промокоды\n\nДля активации отправьте код в чат.",
        reply_markup=back_kb()
    )
    await call.answer()

# Админка
@router.message(Command("admin"))
async def admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить карту (отправь фото)", callback_data="add_card")],
        [InlineKeyboardButton(text="📋 Список карт", callback_data="list_cards")],
    ])
    
    await message.answer("👑 Админ-панель:", reply_markup=kb)

@router.callback_query(F.data == "add_card")
async def add_card_info(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    await call.message.answer(
        "📸 Отправь фото карты с подписью (имя).\n"
        "Для L-карты добавь 'L:' перед именем.\n"
        "Пример: 'L:Редкая Карта'"
    )
    await call.answer()

@router.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    caption = message.caption or "Без имени"
    is_L = caption.startswith("L:")
    name = caption[2:].strip() if is_L else caption
    file_id = message.photo[-1].file_id
    
    await add_card_to_db(name, file_id, is_L)
    await message.answer(f"✅ Карта '{name}' добавлена! {'🌟 L-карта' if is_L else ''}")

@router.callback_query(F.data == "list_cards")
async def list_cards(call: types.CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    
    cards = await get_all_cards()
    if not cards:
        await call.message.answer("Нет карт в базе")
        return
    
    text = "📋 Карты:\n\n"
    for card in cards[:30]:
        prefix = "🌟" if card['is_L_card'] else ""
        text += f"{prefix} #{card['id']} {card['name']}\n"
    
    await call.message.answer(text[:4000])
    await call.answer()

# =================== ЗАПУСК ===================
async def daily_bonus():
    """Ежедневные бонусы в 8:00 МСК"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rolls = rolls + 2, diamonds = diamonds + 2")
        await db.commit()
    logging.info("✅ Ежедневные бонусы начислены!")

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Инициализация БД
    await init_db()
    
    # Бот
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    
    # Планировщик
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_bonus, 'cron', hour=8, minute=0)
    scheduler.start()
    
    logging.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
