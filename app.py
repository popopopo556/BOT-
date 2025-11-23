import logging
import os
from flask import Flask, jsonify, request
import sqlite3

# Отключаем логирование httpx (дублируются с telegram)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Настройка логирования только для нашего бота
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import datetime
from datetime import timezone, timedelta
import json
from collections import defaultdict

# Создаем Flask приложение для управления статусом
app = Flask(__name__)

# Безопасность - использование переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN', "8402596513:AAGEkanjGOrWgi-hOyEif348-yQ9LYAg5wM")
CHANNEL_ID = os.getenv('CHANNEL_ID', "-1002965624279")
YOUMONEY_CARD = os.getenv('YOUMONEY_CARD', "5599002123754949")
DEVELOPER_IDS = [int(id.strip()) for id in os.getenv('DEVELOPER_IDS', '8442930104').split(',')]

# Файл для статистики
STATS_FILE = "bot_statistics.json"

# Кэш для клавиатур
_main_keyboard = None
_dev_keyboard = None

# Словарь для переименования действий в статистике
ACTION_NAMES = {
    "start": "🚀 Запуск бота",
    "donate_button": "💝 Поддержать разработчика",
    "rules_button": "📜 Правила канала",
    "contact_admin_button": "💌 Связь с админом",
    "help_button": "🆘 Помощь",
    "write_post_button": "📝 Написать пост",
    "new_post": "📝 Отправлен текст",
    "photo_post": "📸 Отправлено фото",
    "video_post": "🎥 Отправлено видео",
    "document_post": "📎 Отправлен файл",
    "animation_post": "🎭 Отправлена GIF",
    "voice_post": "🎵 Отправлено голосовое",
    "sticker_post": "🖼️ Отправлен стикер",
    "message_to_admin": "💌 Сообщение админу"
}

# Система управления статусом бота для мобильного приложения
class BotManager:
    def __init__(self):
        self.status = "active"
    
    def get_status(self):
        return self.status
    
    def set_status(self, status):
        self.status = status

# Инициализация менеджера статуса
status_manager = BotManager()

# Система статистики с оптимизацией
class BotStatistics:
    def __init__(self):
        self.stats = self.load_stats()
        self.save_counter = 0
        self.MAX_SAVES = 10  # Сохранять каждые 10 действий

    def load_stats(self):
        """Загружает статистику из файла"""
        try:
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Конвертируем list обратно в set
                    if "unique_users" in data and isinstance(data["unique_users"], list):
                        data["unique_users"] = set(data["unique_users"])

                    # Восстанавливаем defaultdict для вложенных словарей
                    commands_usage = defaultdict(int)
                    commands_usage.update(data.get("commands_usage", {}))
                    data["commands_usage"] = commands_usage

                    buttons_usage = defaultdict(int)
                    buttons_usage.update(data.get("buttons_usage", {}))
                    data["buttons_usage"] = buttons_usage

                    daily_stats = defaultdict(lambda: defaultdict(int))
                    for date, stats_dict in data.get("daily_stats", {}).items():
                        daily_stats[date].update(stats_dict)
                    data["daily_stats"] = daily_stats

                    user_actions = defaultdict(lambda: defaultdict(int))
                    for user, actions_dict in data.get("user_actions", {}).items():
                        user_actions[user].update(actions_dict)
                    data["user_actions"] = user_actions

                    return data
            else:
                return {
                    "total_users": 0,
                    "unique_users": set(),
                    "commands_usage": defaultdict(int),
                    "buttons_usage": defaultdict(int),
                    "daily_stats": defaultdict(lambda: defaultdict(int)),
                    "user_actions": defaultdict(lambda: defaultdict(int)),
                    "start_time": datetime.datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"Ошибка загрузки статистики: {e}")
            return {
                "total_users": 0,
                "unique_users": set(),
                "commands_usage": defaultdict(int),
                "buttons_usage": defaultdict(int),
                "daily_stats": defaultdict(lambda: defaultdict(int)),
                "user_actions": defaultdict(lambda: defaultdict(int)),
                "start_time": datetime.datetime.now().isoformat()
            }

    def save_stats(self):
        """Сохраняет статистику в файл с созданием бэкапа"""
        try:
            # Создаем бэкап старого файла
            if os.path.exists(STATS_FILE):
                backup_file = f"{STATS_FILE}.backup"
                import shutil
                shutil.copy2(STATS_FILE, backup_file)

            # Конвертируем sets в lists для JSON
            stats_to_save = self.stats.copy()
            stats_to_save["unique_users"] = list(stats_to_save["unique_users"])

            # Конвертируем defaultdict в обычные dict
            stats_to_save["commands_usage"] = dict(stats_to_save["commands_usage"])
            stats_to_save["buttons_usage"] = dict(stats_to_save["buttons_usage"])
            stats_to_save["daily_stats"] = {k: dict(v) for k, v in stats_to_save["daily_stats"].items()}
            stats_to_save["user_actions"] = {k: dict(v) for k, v in stats_to_save["user_actions"].items()}

            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(stats_to_save, f, ensure_ascii=False, indent=2)

            logger.info("Статистика успешно сохранена")

        except Exception as e:
            logger.error(f"Ошибка сохранения статистики: {e}")

    def add_user_action(self, user_id, action_type, user_name=""):
        """Добавляет действие пользователя"""
        # Не записываем действия разработчика
        if user_id in DEVELOPER_IDS:
            return

        today = datetime.datetime.now().strftime("%Y-%m-%d")

        # Обновляем уникальных пользователей
        self.stats["unique_users"].add(str(user_id))

        # Общая статистика
        self.stats["total_users"] = len(self.stats["unique_users"])
        self.stats["commands_usage"][action_type] += 1

        # Дневная статистика
        self.stats["daily_stats"][today][action_type] += 1

        # Статистика по пользователям
        user_key = f"{user_id} ({user_name})" if user_name else str(user_id)
        self.stats["user_actions"][user_key][action_type] += 1

        # Оптимизированное сохранение - не при каждом действии
        self.save_counter += 1
        if self.save_counter >= self.MAX_SAVES:
            self.save_stats()
            self.save_counter = 0

    def get_stats_summary(self):
        """Возвращает сводную статистику"""
        today = datetime.datetime.now().strftime("%Y-%m-%d")

        # Фильтруем статистику - убираем действия разработчиков
        filtered_daily_stats = defaultdict(lambda: defaultdict(int))
        filtered_commands_usage = defaultdict(int)

        # Собираем статистику только от обычных пользователей
        for user, actions in self.stats["user_actions"].items():
            # Пропускаем разработчиков
            if any(str(dev_id) in user for dev_id in DEVELOPER_IDS):
                continue

            for action, count in actions.items():
                # Находим дату для этого действия
                for date, date_stats in self.stats["daily_stats"].items():
                    if action in date_stats:
                        filtered_daily_stats[date][action] += count
                filtered_commands_usage[action] += count

        total_days = len(filtered_daily_stats)
        total_users = len([user for user in self.stats["unique_users"]
                           if not any(str(dev_id) in user for dev_id in DEVELOPER_IDS)])

        summary = f"""
📊 *СТАТИСТИКА БОТА*

👥 *Пользователи:*
├ Уникальных пользователей: {total_users}
├ Всего запусков бота: {filtered_commands_usage.get('start', 0)}
└ Дней работы: {total_days}

📈 *Активность за сегодня ({today}):*
"""

        # Активность за сегодня
        today_stats = filtered_daily_stats.get(today, {})
        for action, count in today_stats.items():
            display_name = ACTION_NAMES.get(action, action)
            summary += f"├ {display_name}: {count}\n"

        summary += f"\n🔄 *Всего действий:*\n"
        for action, count in sorted(filtered_commands_usage.items(), key=lambda x: x[1], reverse=True):
            display_name = ACTION_NAMES.get(action, action)
            summary += f"├ {display_name}: {count}\n"

        # Топ пользователей (исключаем разработчиков)
        user_stats = {user: actions for user, actions in self.stats["user_actions"].items()
                      if not any(str(dev_id) in user for dev_id in DEVELOPER_IDS)}

        top_users = sorted(
            [(user, sum(actions.values())) for user, actions in user_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]

        summary += f"\n🏆 *Топ-5 активных пользователей:*\n"
        for i, (user, count) in enumerate(top_users, 1):
            summary += f"{i}. {user}: {count} действий\n"

        return summary

# Инициализация статистики
stats = BotStatistics()

# Московское время (+3 часа от UTC)
def get_moscow_time():
    moscow_offset = timedelta(hours=3)
    moscow_tz = timezone(moscow_offset)
    return datetime.datetime.now(moscow_tz).strftime("%H:%M %d.%m.%Y")

def get_user_info(update: Update):
    """Получает полную информацию о пользователе"""
    user = update.message.from_user

    user_info = {
        "id": user.id,
        "username": f"@{user.username}" if user.username else "❌ Нет username",
        "first_name": user.first_name or "❌ Не указано",
        "last_name": user.last_name or "❌ Не указано",
        "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or "❌ Не указано",
        "is_premium": "✅ Да" if user.is_premium else "❌ Нет",
        "language_code": user.language_code or "❌ Не указано"
    }

    return user_info

def get_user_details_text(user_info):
    """Формирует текст с информацией о пользователе"""
    return f"""
👤 *Информация об отправителе:*
├ ID: `{user_info['id']}`
├ Username: {user_info['username']}
├ Имя: {user_info['first_name']}
├ Фамилия: {user_info['last_name']}
├ Премиум: {user_info['is_premium']}
└ Язык: {user_info['language_code']}
"""

def main_menu_keyboard(user_id=None):
    """Создает клавиатуру меню с кэшированием"""
    global _main_keyboard, _dev_keyboard

    if user_id in DEVELOPER_IDS:
        if _dev_keyboard is None:
            keyboard = [
                [KeyboardButton("📝 Написать пост"), KeyboardButton("📜 Правила канала")],
                [KeyboardButton("🆘 Помощь"), KeyboardButton("💌 Связь с админом")],
                [KeyboardButton("💝 Поддержать разработчика")],
                [KeyboardButton("📈 Быстрая статистика"), KeyboardButton("📊 Детальная статистика")]
            ]
            _dev_keyboard = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        return _dev_keyboard
    else:
        if _main_keyboard is None:
            keyboard = [
                [KeyboardButton("📝 Написать пост"), KeyboardButton("📜 Правила канала")],
                [KeyboardButton("🆘 Помощь"), KeyboardButton("💌 Связь с админом")],
                [KeyboardButton("💝 Поддержать разработчика")]
            ]
            _main_keyboard = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        return _main_keyboard

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        user_name = user_info['username']
        user_id = update.message.from_user.id

        # Логируем действие
        stats.add_user_action(user_id, "start", user_name)

        welcome_text = """
🎊 *Добро пожаловать!* 🎊

🏫 *Твой анонимный голос в школьном канале*

✨ *Что умеет этот бот:*
• Анонимно отправлять посты в школьный канал
• Передавать фото, видео, голосовые и файлы
• Гарантировать полную конфиденциальность

📱 *Быстрые действия:*
Используй кнопки ниже для навигации!

⚡ *Просто нажми «📝 Написать пост» и поделись своим мнением!*
        """

        # Для разработчика добавляем приветствие
        if user_id in DEVELOPER_IDS:
            welcome_text += "\n\n👑 *Разработчик, вам доступны дополнительные функции статистики!*"

        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(user_id)
        )

    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при запуске бота. Попробуйте еще раз.",
            parse_mode='Markdown'
        )

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        stats.add_user_action(update.message.from_user.id, "donate_button", user_info['username'])

        donate_text = f"""
💝 *Поддержать разработчика*

🤖 Этот бот был создан с нуля одним человеком специально для нашей школы.

🌟 *Если тебе нравится бот и ты хочешь поддержать разработчика:*

💳 *Анонимный перевод на карту:*
`{YOUMONEY_CARD}`

📱 *Как перевести:*
1. Открой приложение своего банка
2. Выбери "Перевод по номеру карты"
3. Введи номер: `{YOUMONEY_CARD}`
4. Укажи любую сумму

🔒 *Полная анонимность:*
• При переводе не видно имя получателя
• Только номер карты
• Никаких личных данных

✨ *Спасибо за поддержку!*
Она помогает развивать бота дальше 🚀
        """

        await update.message.reply_text(
            donate_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

    except Exception as e:
        logger.error(f"Ошибка в donate_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        stats.add_user_action(update.message.from_user.id, "help_button", user_info['username'])

        help_text = """
🆘 *Центр помощи*

💡 *Как отправить пост:*
1. Нажми кнопку «📝 Написать пост»
2. Напиши сообщение или отправь медиа
3. Нажми отправить - всё!

⏰ *Время модерации:* до 24 часов

🕵️ *Анонимность гарантирована:*
• Никто не узнает отправителя
• Админ видит только содержание
• Данные не сохраняются

📞 *Нужна помощь?*
Нажми «💌 Связь с админом» для личного обращения
        """
        await update.message.reply_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

    except Exception as e:
        logger.error(f"Ошибка в help_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        stats.add_user_action(update.message.from_user.id, "rules_button", user_info['username'])

        rules_text = """
📜 *Правила школьного канала "В 1 школе любят":* 📜

✅ *Разрешено:*
• Обсуждать школьные вопросы и мероприятия
• Делиться мнением о учебном процессе
• Предлагать идеи для улучшения школы
• Поздравлять учителей и учеников
• Общаться на любые школьные темы
• Делиться позитивными моментами

❌ *Строго запрещено:*
• Оскорбления, унижение, буллинг
• Разжигание ненависти и конфликтов
• Политические и религиозные споры
• Распространение личной информации
• Нецензурная лексика
• Спам и реклама

⚖️ *Система модерации:*
• Запрещенные посты не публикуются
• В комментариях: 2 предупреждения → бан
• Решение админа окончательно

🌈 *Давайте создавать позитивную атмосферу вместе!*
        """
        await update.message.reply_text(
            rules_text,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

    except Exception as e:
        logger.error(f"Ошибка в rules_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def contact_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        stats.add_user_action(update.message.from_user.id, "contact_admin_button", user_info['username'])

        contact_text = """
💌 *Связь с администратором*

📬 *Хочешь сообщить о проблеме или задать вопрос?*

Просто напиши свое сообщение ниже - оно придет админу лично.

⚠️ *Важно:*
• Сообщения проверяются 1-2 раза в день
• По техническим вопросам отвечаем быстро
• По содержанию постов - решения окончательные

✨ *Напиши свой вопрос и нажми отправить:*
        """
        await update.message.reply_text(
            contact_text,
            parse_mode='Markdown'
        )
        context.user_data['waiting_for_admin_message'] = True

    except Exception as e:
        logger.error(f"Ошибка в contact_admin_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def quick_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая статистика по кнопке"""
    try:
        user_id = update.message.from_user.id

        if user_id not in DEVELOPER_IDS:
            await update.message.reply_text("❌ Эта функция только для разработчика")
            return

        # Показываем статистику
        summary = stats.get_stats_summary()
        await update.message.reply_text(summary, parse_mode='Markdown')

        logger.info("📊 Быстрая статистика запрошена разработчиком")

    except Exception as e:
        logger.error(f"Ошибка в quick_stats_command: {e}")
        await update.message.reply_text("❌ Ошибка при получении статистики")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Проверка на спам/флуд
        user_id = update.message.from_user.id
        current_time = datetime.datetime.now()

        if hasattr(context, 'user_last_message'):
            time_diff = (current_time - context.user_last_message).seconds
            if time_diff < 2:  # Не чаще 1 сообщения в 2 секунды
                await update.message.reply_text("⚠️ Слишком частые сообщения. Подождите немного.")
                return

        context.user_last_message = current_time

        # Проверка длины сообщения
        if len(update.message.text) > 4000:
            await update.message.reply_text("❌ Сообщение слишком длинное. Максимум 4000 символов.")
            return

        if context.user_data.get('waiting_for_admin_message'):
            user_message = update.message.text
            user_info = get_user_info(update)
            user_id = update.message.from_user.id

            stats.add_user_action(user_id, "message_to_admin", user_info['username'])

            user_details = get_user_details_text(user_info)

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=f"💌 *Сообщение для админа*\n\n{user_details}\n💬 *Текст сообщения:*\n{user_message}\n\n⏰ _{get_moscow_time()}_",
                parse_mode='Markdown'
            )

            await update.message.reply_text(
                "✅ *Сообщение отправлено админу!*\n\n"
                "📋 Ответим в течение 24 часов\n"
                "🔄 Возвращаю в главное меню...",
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard(user_id)
            )
            context.user_data['waiting_for_admin_message'] = False
            return

        user_message = update.message.text
        user_info = get_user_info(update)
        user_id = update.message.from_user.id
        stats.add_user_action(user_id, "new_post", user_info['username'])

        user_details = get_user_details_text(user_info)

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"📝 *Предложен новый пост*\n\n{user_details}\n💬 *Текст поста:*\n{user_message}\n\n⏰ _{get_moscow_time()}_",
            parse_mode='Markdown'
        )

        await update.message.reply_text(
            "✅ *Пост отправлен на модерацию!*\n\n"
            "📋 Админ проверит его в течение 24 часов\n"
            "👀 Следи за каналом «В 1 школе любят»!\n\n"
            "🔄 Возвращаю в главное меню...",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(user_id)
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке сообщения. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_info = get_user_info(update)
        user_id = update.message.from_user.id
        stats.add_user_action(user_id, "photo_post", user_info['username'])

        photo = update.message.photo[-1]
        caption = update.message.caption or "Без описания"
        user_details = get_user_details_text(user_info)

        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=photo.file_id,
            caption=f"📸 *Предложено новое фото*\n\n{user_details}\n💬 *Описание:* {caption}\n\n⏰ _{get_moscow_time()}_",
            parse_mode='Markdown'
        )

        await update.message.reply_text(
            "✅ *Фото отправлено на модерацию!*\n\n"
            "🔄 Возвращаю в главное меню...",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard(user_id)
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_photo: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при отправке. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        user_info = get_user_info(update)
        user_id = update.message.from_user.id

        if text == "📝 Написать пост":
            stats.add_user_action(user_id, "write_post_button", user_info['username'])
            await update.message.reply_text(
                "📝 *Режим написания поста*\n\n"
                "💬 Напиши свой пост или отправь медиа-файл\n"
                "✨ Он сразу отправится на модерацию\n\n"
                "⚡ *Просто пиши ниже:*",
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard(user_id)
            )
        elif text == "📜 Правила канала":
            await rules_command(update, context)
        elif text == "🆘 Помощь":
            await help_command(update, context)
        elif text == "💌 Связь с админом":
            await contact_admin_command(update, context)
        elif text == "💝 Поддержать разработчика":
            await donate_command(update, context)
        elif text == "📈 Быстрая статистика":
            await quick_stats_command(update, context)

    except Exception as e:
        logger.error(f"Ошибка в button_handler: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=main_menu_keyboard(update.message.from_user.id)
        )

# Flask endpoints для управления статусом
@app.route('/')
def home():
    return "🤖 Бот работает! Статус: " + status_manager.get_status()

@app.route('/api/status')
def get_status():
    return jsonify({'status': status_manager.get_status()})

@app.route('/api/toggle', methods=['POST'])
def toggle_bot():
    current = status_manager.get_status()
    new_status = 'inactive' if current == 'active' else 'active'
    status_manager.set_status(new_status)
    return jsonify({'status': new_status})

def run_telegram_bot():
    """Запускает Telegram бота в отдельном потоке"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        # Команды
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("rules", rules_command))
        application.add_handler(CommandHandler("contact", contact_admin_command))
        application.add_handler(CommandHandler("donate", donate_command))
        application.add_handler(CommandHandler("stats", quick_stats_command))

        # Обработчики кнопок
        application.add_handler(MessageHandler(filters.Text([
            "📝 Написать пост", "📜 Правила канала",
            "🆘 Помощь", "💌 Связь с админом",
            "💝 Поддержать разработчика",
            "📈 Быстрая статистика"
        ]), button_handler))

        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        print("🎊 Бот «В 1 школе любят» запущен и готов к работе!")
        print("📊 Система статистики активирована!")
        print("🌐 API управления статусом доступно!")

        # Запуск бота
        application.run_polling()

    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")

def main():
    """Запускает и Telegram бота и Flask сервер"""
    import threading
    
    # Запускаем Telegram бота в отдельном потоке
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    print("✅ Telegram бот запущен в фоновом режиме!")
    print("🚀 Flask сервер запускается...")

# Запускаем и бота и Flask сервер
if __name__ == "__main__":
    # Запускаем бота в фоне
    main()
    
    # Запускаем Flask сервер (для Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
