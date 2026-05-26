import os
import re
from datetime import datetime
import threading
from flask import Flask, request, jsonify
import telebot

# Токен бота
BOT_TOKEN = "8738075651:AAFlih0KCqso9re1_40N0jPq7AgCveOZXUE"
DEFAULT_BACKUP_NAME = "survival_budget_backup.json"
BACKUPS_DIR = "backups"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

def ensure_backups_dir():
    """Гарантирует существование базовой папки для бэкапов."""
    if not os.path.exists(BACKUPS_DIR):
        os.makedirs(BACKUPS_DIR)

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

    # Формируем имя файла с датой
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_file_name = f"survival_budget_backup_{now_str}.json"
    file_path = os.path.join(user_dir, new_file_name)

    try:
        # Сохраняем файл на сервере
        file.save(file_path)
        
        # Отправляем пользователю уведомление в Telegram, что бэкап долетел до сервера
        bot.send_message(
            chat_id=user_id, 
            text=f"🔄 *Облако:* Новая резервная копия из приложения успешно сохранена на сервере!",
            parse_mode='Markdown'
        )
        return jsonify({"status": "success", "message": "Backup saved successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Привет! Я бот для управления резервными копиями приложения Survival Budget.\n\n"
        "💾 *Как сохранить бэкап:*\n"
        "Просто нажми кнопку «Сохранить бэкап в облако TG» внутри приложения.\n\n"
        "📥 *Как восстановить бэкап:*\n"
        "Отправь команду /load, и я пришлю тебе самый свежий файл."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['load'])
def load_backup(message):
    """Выдача пользователю самой последней версии бэкапа."""
    user_id = str(message.from_user.id)
    user_dir = os.path.join(BACKUPS_DIR, user_id)
    
    if not os.path.exists(user_dir) or not os.listdir(user_dir):
        bot.reply_to(message, "У вас ещё нет сохранённых копий.")
        return

    try:
        files = os.listdir(user_dir)
        backup_files = [
            f for f in files 
            if re.match(r"survival_budget_backup_\d{8}_\d{6}\.json", f)
        ]
        
        if not backup_files:
            bot.reply_to(message, "У вас ещё нет сохранённых копий.")
            return
            
        backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(user_dir, x)), reverse=True)
        latest_file_name = backup_files[0]
        latest_file_path = os.path.join(user_dir, latest_file_name)
        
        with open(latest_file_path, 'rb') as backup_file:
            bot.send_document(
                message.chat.id, 
                backup_file, 
                visible_file_name=DEFAULT_BACKUP_NAME,
                caption="Ваша последняя резервная копия из облака."
            )
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при отправке файла: {str(e)}")

def run_bot():
    ensure_backups_dir()
    print("Бот Survival Budget запущен...")
    bot.infinity_polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
