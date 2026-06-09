import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8606776997:AAElzO6hH5KGT7dQYa-XM8egnNfc3wRrAY8")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "6486215227").split(",")]
DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")
