import logging
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import datetime
from datetime import timezone, timedelta
import json
from collections import defaultdict

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.getenv('BOT_TOKEN', "8402596513:AAGEkanjGOrWgi-hOyEif348-yQ9LYAg5wM")
CHANNEL_ID = os.getenv('CHANNEL_ID', "-1002965624279")

def get_moscow_time():
    moscow_offset = timedelta(hours=3)
    moscow_tz = timezone(moscow_offset)
    return datetime.datetime.now(moscow_tz).strftime("%H:%M %d.%m.%Y")

def start_command(update: Update, context: CallbackContext):
    welcome_text = """
🎊 Добро пожаловать! 🎊

🏫 Твой анонимный голос в школьном канале

📝 Напиши сообщение - оно отправится на модерацию!
    """
    update.message.reply_text(welcome_text)

def handle_message(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_info = f"👤 ID: {user.id}\n📛 Имя: {user.first_name}\n🔗 Username: @{user.username if user.username else 'нет'}"
    
    context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"📝 Новый пост\n\n{user_info}\n💬 Текст: {update.message.text}\n⏰ {get_moscow_time()}"
    )
    
    update.message.reply_text("✅ Пост отправлен на модерацию!")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    print("🤖 Бот запущен!")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
