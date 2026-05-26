import os
import re
from datetime import datetime
import threading
from flask import Flask
import telebot

# Токен бота, предоставленный в ТЗ
BOT_TOKEN = "8738075651:AAFlih0KCqso9re1_40N0jPq7AgCveOZXUE"
DEFAULT_BACKUP_NAME = "survival_budget_backup.json"
BACKUPS_DIR = "backups"

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# Инициализация Flask-приложения для прохождения проверок (Port Binding) на Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Survival Budget Backup Bot is running!", 200

def ensure_backups_dir():
    """Гарантирует существование базовой папки для бэкапов."""
    if not os.path.exists(BACKUPS_DIR):
        os.makedirs(BACKUPS_DIR)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Приветственное сообщение."""
    welcome_text = (
        "Привет! Я бот для управления резервными копиями приложения Survival Budget.\n\n"
        "💾 *Как сохранить бэкап:*\n"
        f"Просто отправь мне файл с именем `{DEFAULT_BACKUP_NAME}`.\n\n"
        "📥 *Как восстановить бэкап:*\n"
        "Отправь команду /load, и я пришлю тебе самый свежий файл."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def handle_document(message):
    """Прием файла бэкапа от пользователя."""
    document = message.document
    file_name = document.file_name

    # Проверяем, совпадает ли имя файла с требуемым по умолчанию
    if file_name == DEFAULT_BACKUP_NAME:
        user_id = str(message.from_user.id)
        user_dir = os.path.join(BACKUPS_DIR, user_id)
        
        # Создаем папку для пользователя, если её еще нет
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            
        # Формируем новое имя файла с текущей датой и временем
        # Формат: survival_budget_backup_YYYYMMDD_HHMMSS.json
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_file_name = f"survival_budget_backup_{now_str}.json"
        file_path = os.path.join(user_dir, new_file_name)
        
        try:
            # Скачиваем файл через Telegram API
            file_info = bot.get_file(document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Сохраняем файл локально
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
                
            bot.reply_to(message, "Резервная копия успешно сохранена в облаке!")
        except Exception as e:
            bot.reply_to(message, f"Произошла ошибка при сохранении файла: {str(e)}")
    else:
        bot.reply_to(
            message, 
            f"Неверное имя файла. Ожидался файл с именем `{DEFAULT_BACKUP_NAME}`.",
            parse_mode='Markdown'
        )

@bot.message_handler(commands=['load'])
def load_backup(message):
    """Выдача пользователю самой последней версии бэкапа."""
    user_id = str(message.from_user.id)
    user_dir = os.path.join(BACKUPS_DIR, user_id)
    
    # Проверяем наличие папки пользователя и файлов в ней
    if not os.path.exists(user_dir) or not os.listdir(user_dir):
        bot.reply_to(message, "У вас ещё нет сохранённых копий.")
        return

    try:
        # Получаем список всех файлов в папке пользователя
        files = os.listdir(user_dir)
        
        # Фильтруем файлы по паттерну, чтобы случайно не отправить посторонний файл
        backup_files = [
            f for f in files 
            if re.match(r"survival_budget_backup_\d{8}_\d{6}\.json", f)
        ]
        
        if not backup_files:
            bot.reply_to(message, "У вас ещё нет сохранённых копий.")
            return
            
        # Находим самый последний файл по времени изменения/добавления
        backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(user_dir, x)), reverse=True)
        latest_file_name = backup_files[0]
        latest_file_path = os.path.join(user_dir, latest_file_name)
        
        # Отправляем файл пользователю, переименовав его в стандартное имя
        with open(latest_file_path, 'rb') as backup_file:
            bot.send_document(
                message.chat.id, 
                backup_file, 
                visible_file_name=DEFAULT_BACKUP_NAME,
                caption="Ваша последняя резервная копия."
            )
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при отправке файла: {str(e)}")

def run_bot():
    """Запуск бота в бесконечном цикле пуллинга."""
    ensure_backups_dir()
    print("Бот Survival Budget запущен и готов к работе...")
    bot.infinity_polling()

if __name__ == '__main__':
    # Запуск бота в отдельном потоке, чтобы Flask-сервер мог параллельно отвечать на запросы Render
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Render передает порт в переменную окружения PORT
    port = int(os.environ.get("PORT", 5000))
    # Запуск веб-сервера на хосте 0.0.0.0
    app.run(host='0.0.0.0', port=port)