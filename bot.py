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
    @dp.message(Command("admin"))
    async def admin_cmd(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            await msg.answer("❌ У вас нет доступа к админ-панели")
            return
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add")],
            [InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
            [InlineKeyboardButton(text="👤 Выдать ресурсы", callback_data="admin_give")],
        ])
        
        await msg.answer("👑 Админ-панель:", reply_markup=kb)
    
    @dp.callback_query(F.data == "admin_add")
    async def admin_add(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ Нет доступа!", show_alert=True)
            return
        
        await call.message.answer(
            "📸 Отправь фото карты с подписью (имя)\n"
            "Для L-карты: 'L:Имя карты'\n"
            "Для обычной: 'Имя карты'"
        )
        await call.answer()
    
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
        
        text = "📋 Все карты:\n\n"
        for card in cards[:50]:
            prefix = "🌟 " if card['is_L_card'] else ""
            text += f"{prefix}#{card['id']} {card['name']}\n"
        
        await call.message.answer(text[:4000])
        await call.answer()
    
    @dp.callback_query(F.data == "admin_give")
    async def admin_give(call: types.CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("❌ Нет доступа!", show_alert=True)
            return
        
        await call.message.answer(
            "📝 Формат выдачи:\n"
            "ID_пользователя тип количество\n\n"
            "Типы:\n"
            "• diamonds - алмазы\n"
            "• rolls - крутки\n"
            "• card_id - ID карты\n\n"
            "Пример: 123456789 diamonds 100"
        )
        await call.answer()
    
    # Обработка текстовых команд админа для выдачи
    @dp.message()
    async def handle_admin_give(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        # Проверяем формат команды выдачи
        parts = msg.text.split()
        if len(parts) == 3 and parts[0].isdigit():
            try:
                target_id = int(parts[0])
                give_type = parts[1]
                value = int(parts[2])
                
                if give_type == 'diamonds':
                    await upd_diamonds(target_id, value)
                    await msg.answer(f"✅ Выдано {value}💎 пользователю {target_id}")
                elif give_type == 'rolls':
                    await upd_rolls(target_id, value)
                    await msg.answer(f"✅ Выдано {value}🎲 пользователю {target_id}")
                elif give_type.isdigit():
                    card_id = int(give_type)
                    for _ in range(value):
                        await add_card_to_user(target_id, card_id)
                    await msg.answer(f"✅ Выдано {value} карт #{card_id} пользователю {target_id}")
                else:
                    await msg.answer("❌ Неверный тип ресурса")
            except Exception as e:
                await msg.answer(f"❌ Ошибка: {e}")
    
    # Прием фото карт от админа
    @dp.message(F.photo)
    async def handle_photo(msg: types.Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        
        caption = msg.caption or "Без имени"
        is_L = caption.startswith("L:")
        name = caption[2:].strip() if is_L else caption
        file_id = msg.photo[-1].file_id
        
        await add_card_to_db(name, file_id, is_L)
        await msg.answer(f"✅ Карта '{name}' добавлена! {'🌟 L-карта' if is_L else ''}")
    
    # Ежедневный бонус
    async def daily_bonus():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET rolls=rolls+2, diamonds=diamonds+2")
                await db.commit()
            logger.info("✅ Ежедневные бонусы начислены!")
        except Exception as e:
            logger.error(f"Ошибка бонусов: {e}")
    
    # Планировщик
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_bonus, 'cron', hour=8, minute=0)
    scheduler.start()
    
    # Запуск
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🚀 Бот запущен!")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
