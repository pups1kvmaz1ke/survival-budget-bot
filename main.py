```python
import os
import re
from datetime import datetime
import threading
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pytz

# Токен бота
BOT_TOKEN = "8738075651:AAFlih0KCqso9re1_40N0jPq7AgCveOZXUE"
DEFAULT_BACKUP_NAME = "survival_budget_backup.json"
BACKUPS_DIR = "backups"
MAX_BACKUPS = 5  # Храним максимум 5 файлов для каждого юзера

# Настройка часового пояса (по умолчанию Екатеринбург, UTC+5)
BOT_TIMEZONE = pytz.timezone('Asia/Yekaterinburg')

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

def ensure_backups_dir():
    """Гарантирует существование базовой папки для бэкапов."""
    if not os.path.exists(BACKUPS_DIR):
        os.makedirs(BACKUPS_DIR)

def get_user_backups(user_id):
    """Возвращает отсортированный по времени список бэкапов пользователя."""
    user_dir = os.path.join(BACKUPS_DIR, str(user_id))
    if not os.path.exists(user_dir):
        return []
    
    files = os.listdir(user_dir)
    backup_files = [
        f for f in files 
        if re.match(r"survival_budget_backup_\d{8}_\d{6}\.json", f)
    ]
    # Сортируем файлы по дате/времени в их имени, а не по времени файловой системы,
    # чтобы избежать путаницы при изменении метаданных файлов на сервере
    backup_files.sort(key=lambda x: re.search(r"(\d{8})_(\d{6})", x).group(0), reverse=True)
    return backup_files

def clean_old_backups(user_id):
    """Удаляет старые бэкапы, оставляя только MAX_BACKUPS штук."""
    user_dir = os.path.join(BACKUPS_DIR, str(user_id))
    backups = get_user_backups(user_id)
    
    if len(backups) > MAX_BACKUPS:
        old_backups = backups[MAX_BACKUPS:]
        for old_file in old_backups:
            try:
                os.remove(os.path.join(user_dir, old_file))
            except Exception as e:
                print(f"Ошибка удаления старого файла {old_file}: {e}")

def parse_datetime_from_filename(filename):
    """Вытаскивает красивую дату и время из имени файла и возвращает её в локальном формате."""
    match = re.search(r"(\d{8})_(\d{6})", filename)
    if match:
        date_part, time_part = match.groups()
        # Время в названии файла сохранено в часовом поясе BOT_TIMEZONE
        dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
        return dt.strftime("%d.%m.%Y %H:%M")
    return "Неизвестная дата"

@app.route('/')
def home():
    return "Survival Budget Backup Bot is running!", 200

@app.route('/upload', methods=['POST'])
def upload_file_from_app():
    """Прием бэкапа напрямую из Android-приложения."""
    if 'file' not in request.files or 'user_id' not in request.form:
        return jsonify({"error": "Missing file or user_id"}), 400
        
    file = request.files['file']
    user_id = request.form['user_id']
    
    if file.filename != DEFAULT_BACKUP_NAME:
        return jsonify({"error": f"Invalid file name. Expected {DEFAULT_BACKUP_NAME}"}), 400

    ensure_backups_dir()
    user_dir = os.path.join(BACKUPS_DIR, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)

    # Получаем текущее время в локальной временной зоне бота
    now_local = datetime.now(BOT_TIMEZONE)
    now_str = now_local.strftime("%Y%m%d_%H%M%S")
    new_file_name = f"survival_budget_backup_{now_str}.json"
    file_path = os.path.join(user_dir, new_file_name)

    try:
        file.save(file_path)
        clean_old_backups(user_id)
        
        # Форматируем локальное время для отправки пользователю в чат
        pretty_time = now_local.strftime("%d.%m.%Y %H:%M")
        bot.send_message(
            chat_id=user_id, 
            text=f"🔄 *Облако:* Резервная копия успешно создана и сохранена в архив сервера!\n📅 Время сохранения: *{pretty_time}*",
            parse_mode='Markdown'
        )
        return jsonify({"status": "success", "message": f"Backup saved successfully at {pretty_time}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Привет! Я официальный бот архива резервных копий *Survival Budget*.\n\n"
        "💾 *Сохранение:*\n"
        "Просто нажми кнопку «Сохранить бэкап в облако TG» в приложении.\n\n"
        "📥 *Восстановление:*\n"
        "Отправь команду /load, и я выведу список доступных точек восстановления.\n\n"
        "🗑️ *Очистка:*\n"
        "Отправь команду /clear, чтобы навсегда удалить все свои бэкапы с сервера."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['load'])
def load_backup_list(message):
    """Вывод списка кнопок с доступными бэкапами."""
    user_id = str(message.from_user.id)
    backups = get_user_backups(user_id)
    
    if not backups:
        bot.reply_to(message, "У вас ещё нет сохранённых копий в облаке.")
        return

    markup = InlineKeyboardMarkup()
    for filename in backups:
        pretty_date = parse_datetime_from_filename(filename)
        button = InlineKeyboardButton(
            text=f"📅 {pretty_date}", 
            callback_data=f"download:{filename}"
        )
        markup.add(button)

    bot.send_message(
        message.chat.id, 
        "📋 *Выберите точку восстановления из архива:*", 
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['clear'])
def clear_backups(message):
    """Полное удаление всех бэкапов пользователя с сервера."""
    user_id = str(message.from_user.id)
    user_dir = os.path.join(BACKUPS_DIR, user_id)
    
    if not os.path.exists(user_dir) or not os.listdir(user_dir):
        bot.reply_to(message, "У вас и так нет сохранённых копий в облаке.")
        return

    try:
        for filename in os.listdir(user_dir):
            os.remove(os.path.join(user_dir, filename))
        os.rmdir(user_dir)
        
        bot.reply_to(
            message, 
            "🗑️ *Облако очищено:* Все ваши резервные копии были навсегда удалены с сервера!", 
            parse_mode='Markdown'
        )
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при очистке облака: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('download:'))
def handle_backup_download(call):
    """Обработка нажатия на кнопку с датой бэкапа."""
    user_id = str(call.from_user.id)
    filename = call.data.split('download:')[1]
    file_path = os.path.join(BACKUPS_DIR, user_id, filename)

    if not os.path.exists(file_path):
        bot.answer_callback_query(call.id, text="Ошибка: файл не найден на сервере!", show_alert=True)
        return

    try:
        bot.answer_callback_query(call.id, text="Отправляю файл...")
        with open(file_path, 'rb') as backup_file:
            bot.send_document(
                call.message.chat.id, 
                backup_file, 
                visible_file_name=DEFAULT_BACKUP_NAME,
                caption=f"📦 Восстановление от {parse_datetime_from_filename(filename)}."
            )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Ошибка при отправке файла: {str(e)}")

def run_bot():
    ensure_backups_dir()
    print("Бот Survival Budget успешно запущен...")
    bot.infinity_polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

```
def clean_old_backups(user_id):
    """Удаляет старые бэкапы, оставляя только MAX_BACKUPS штук."""
    user_dir = os.path.join(BACKUPS_DIR, str(user_id))
    backups = get_user_backups(user_id)
    
    if len(backups) > MAX_BACKUPS:
        old_backups = backups[MAX_BACKUPS:]
        for old_file in old_backups:
            try:
                os.remove(os.path.join(user_dir, old_file))
            except Exception as e:
                print(f"Ошибка удаления старого файла {old_file}: {e}")

def parse_datetime_from_filename(filename):
    """Вытаскивает красивую дату и время из имени файла."""
    match = re.search(r"(\d{8})_(\d{6})", filename)
    if match:
        date_part, time_part = match.groups()
        dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
        return dt.strftime("%d.%m.%Y %H:%M")
    return "Неизвестная дата"

@app.route('/')
def home():
    return "Survival Budget Backup Bot is running!", 200

@app.route('/upload', methods=['POST'])
def upload_file_from_app():
    """Прием бэкапа напрямую из Android-приложения."""
    if 'file' not in request.files or 'user_id' not in request.form:
        return jsonify({"error": "Missing file or user_id"}), 400
        
    file = request.files['file']
    user_id = request.form['user_id']
    
    if file.filename != DEFAULT_BACKUP_NAME:
        return jsonify({"error": f"Invalid file name. Expected {DEFAULT_BACKUP_NAME}"}), 400

    ensure_backups_dir()
    user_dir = os.path.join(BACKUPS_DIR, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)

    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_file_name = f"survival_budget_backup_{now_str}.json"
    file_path = os.path.join(user_dir, new_file_name)

    try:
        file.save(file_path)
        clean_old_backups(user_id)
        
        bot.send_message(
            chat_id=user_id, 
            text="🔄 *Облако:* Резервная копия успешно создана и сохранена в архив сервера!",
            parse_mode='Markdown'
        )
        return jsonify({"status": "success", "message": "Backup saved successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Привет! Я официальный бот архива резервных копий *Survival Budget*.\n\n"
        "💾 *Сохранение:*\n"
        "Просто нажми кнопку «Сохранить бэкап в облако TG» в приложении.\n\n"
        "📥 *Восстановление:*\n"
        "Отправь команду /load, и я выведу список доступных точек восстановления.\n\n"
        "🗑️ *Очистка:*\n"
        "Отправь команду /clear, чтобы навсегда удалить все свои бэкапы с сервера."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['load'])
def load_backup_list(message):
    """Вывод списка кнопок с доступными бэкапами."""
    user_id = str(message.from_user.id)
    backups = get_user_backups(user_id)
    
    if not backups:
        bot.reply_to(message, "У вас ещё нет сохранённых копий в облаке.")
        return

    markup = InlineKeyboardMarkup()
    for filename in backups:
        pretty_date = parse_datetime_from_filename(filename)
        button = InlineKeyboardButton(
            text=f"📅 {pretty_date}", 
            callback_data=f"download:{filename}"
        )
        markup.add(button)

    bot.send_message(
        message.chat.id, 
        "📋 *Выберите точку восстановления из архива:*", 
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['clear'])
def clear_backups(message):
    """Полное удаление всех бэкапов пользователя с сервера."""
    user_id = str(message.from_user.id)
    user_dir = os.path.join(BACKUPS_DIR, user_id)
    
    if not os.path.exists(user_dir) or not os.listdir(user_dir):
        bot.reply_to(message, "У вас и так нет сохранённых копий в облаке.")
        return

    try:
        for filename in os.listdir(user_dir):
            os.remove(os.path.join(user_dir, filename))
        os.rmdir(user_dir)
        
        bot.reply_to(
            message, 
            "🗑️ *Облако очищено:* Все ваши резервные копии были навсегда удалены с сервера!", 
            parse_mode='Markdown'
        )
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при очистке облака: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('download:'))
def handle_backup_download(call):
    """Обработка нажатия на кнопку с датой бэкапа."""
    user_id = str(call.from_user.id)
    filename = call.data.split('download:')[1]
    file_path = os.path.join(BACKUPS_DIR, user_id, filename)

    if not os.path.exists(file_path):
        bot.answer_callback_query(call.id, text="Ошибка: файл не найден на сервере!", show_alert=True)
        return

    try:
        bot.answer_callback_query(call.id, text="Отправляю файл...")
        with open(file_path, 'rb') as backup_file:
            bot.send_document(
                call.message.chat.id, 
                backup_file, 
                visible_file_name=DEFAULT_BACKUP_NAME,
                caption=f"📦 Восстановление от {parse_datetime_from_filename(filename)}."
            )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Ошибка при отправке файла: {str(e)}")

def run_bot():
    ensure_backups_dir()
    print("Бот Survival Budget успешно запущен...")
    bot.infinity_polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
