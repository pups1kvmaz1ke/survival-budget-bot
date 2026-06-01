import os
import re
from datetime import datetime
import threading
from flask import Flask, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import firebase_admin
from firebase_admin import credentials, firestore

# Токен бота
BOT_TOKEN = "8738075651:AAFw0UW_2hLhaMYpYROfGYhVq2WyKoAcYsc"
DEFAULT_BACKUP_NAME = "survival_budget_backup.json"
MAX_BACKUPS = 5  # Храним максимум 5 файлов для каждого юзера

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Идентификатор вашего приложения для структуры папок в Firestore
APP_ID = os.environ.get("__app_id", "survival-budget-backup")

# Инициализация Firebase
db = None
try:
    if "FIREBASE_KEY_JSON" in os.environ:
        import json
        cred_dict = json.loads(os.environ["FIREBASE_KEY_JSON"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Успешное подключение к Firebase Firestore через Environment Variable!")
    elif os.path.exists("firebase_key.json"):
        cred = credentials.Certificate("firebase_key.json")
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Успешное подключение к Firebase Firestore через локальный файл!")
    else:
        print("Предупреждение: Ключ Firebase не обнаружен. Бот запущен в режиме локального фолбека.")
except Exception as e:
    print(f"Ошибка при инициализации Firebase: {e}")
    print("Бот продолжит работу в режиме локального фолбека (данные сотрутся при перезапуске).")

# Локальный фолбек на случай, если Firebase не подключен
local_db_fallback = {}

def get_user_backups_ref(user_id):
    """Возвращает ссылку на коллекцию бэкапов пользователя в Firestore."""
    if db:
        return db.collection('artifacts').document(APP_ID).collection('public_data').document(f'user_{user_id}').collection('backups')
    return None

def get_user_backups(user_id):
    """Возвращает отсортированный по времени список бэкапов пользователя."""
    if db:
        try:
            backups_ref = get_user_backups_ref(user_id)
            docs = backups_ref.stream()
            
            backup_list = []
            for doc in docs:
                data = doc.to_dict()
                backup_list.append({
                    "id": doc.id,
                    "file_id": data.get("file_id"),
                    "filename": data.get("filename"),
                    "timestamp": data.get("timestamp", 0)
                })
            # Сортируем: новые сверху
            backup_list.sort(key=lambda x: x["timestamp"], reverse=True)
            return backup_list
        except Exception as e:
            print(f"Ошибка при получении бэкапов из Firestore: {e}")
            return []
    else:
        return local_db_fallback.get(str(user_id), [])

def clean_old_backups(user_id):
    """Удаляет старые бэкапы, оставляя только MAX_BACKUPS штук."""
    backups = get_user_backups(user_id)
    if len(backups) > MAX_BACKUPS:
        old_backups = backups[MAX_BACKUPS:]
        for old_item in old_backups:
            if db:
                try:
                    backups_ref = get_user_backups_ref(user_id)
                    backups_ref.document(old_item["id"]).delete()
                except Exception as e:
                    print(f"Ошибка удаления старого бэкапа из Firestore: {e}")
            else:
                if str(user_id) in local_db_fallback:
                    local_db_fallback[str(user_id)] = local_db_fallback[str(user_id)][:MAX_BACKUPS]

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
    status = "Active with Firestore" if db else "Active with Local Fallback"
    return f"Survival Budget Cloud Backup Bot is running! Status: {status}", 200

@app.route('/upload', methods=['POST'])
def upload_file_from_app():
    """Прием бэкапа напрямую из Android-приложения с учетом времени клиента."""
    if 'file' not in request.files or 'user_id' not in request.form:
        return jsonify({"error": "Missing file or user_id"}), 400
        
    file = request.files['file']
    user_id = str(request.form['user_id'])
    
    if file.filename != DEFAULT_BACKUP_NAME:
        return jsonify({"error": f"Invalid file name. Expected {DEFAULT_BACKUP_NAME}"}), 400

    # 1. Принимаем поле 'client_time' из запроса приложения
    client_time = request.form.get('client_time')
    
    if client_time:
        try:
            # Парсим полученное время телефона обратно в объект datetime
            now_dt = datetime.strptime(client_time, "%Y%m%d_%H%M%S")
        except ValueError:
            # Фолбек на случай непредвиденных проблем с форматом строки
            now_dt = datetime.utcnow()
            client_time = now_dt.strftime("%Y%m%d_%H%M%S")
    else:
        # Если клиент старой версии или не передал время устройства, используем UTC
        now_dt = datetime.utcnow()
        client_time = now_dt.strftime("%Y%m%d_%H%M%S")

    # Формируем имя файла с использованием времени клиента
    new_file_name = f"survival_budget_backup_{client_time}.json"

    try:
        file_content = file.read()
        pretty_time = now_dt.strftime("%d.%m.%Y %H:%M")
        
        # Отправляем файл в чат, чтобы сгенерировать стабильный Telegram file_id
        sent_doc = bot.send_document(
            chat_id=user_id,
            document=file_content,
            visible_file_name=DEFAULT_BACKUP_NAME,
            caption=f"🔒 Системный лог загрузки: {pretty_time}"
        )
        telegram_file_id = sent_doc.document.file_id
        
        # Сразу удаляем системный документ из чата пользователя для чистоты интерфейса
        try:
            bot.delete_message(chat_id=user_id, message_id=sent_doc.message_id)
        except Exception as delete_err:
            print(f"Не удалось удалить технический файл (не критично): {delete_err}")
            
        firebase_timestamp = int(now_dt.timestamp())
        
        # Сохраняем метаданные в Firestore
        if db:
            backups_ref = get_user_backups_ref(user_id)
            doc_id = f"backup_{client_time}"
            backups_ref.document(doc_id).set({
                "file_id": telegram_file_id,
                "filename": new_file_name,
                "timestamp": firebase_timestamp
            })
        else:
            if user_id not in local_db_fallback:
                local_db_fallback[user_id] = []
            local_db_fallback[user_id].insert(0, {
                "id": f"backup_{client_time}",
                "file_id": telegram_file_id,
                "filename": new_file_name,
                "timestamp": firebase_timestamp
            })

        clean_old_backups(user_id)
        
        # Оставляем только чистое текстовое уведомление (время подстроится под пояс юзера)
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
        "Отправь команду /clear, чтобы очистить ваш список бэкапов в базе данных."
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
    for item in backups:
        filename = item["filename"]
        pretty_date = parse_datetime_from_filename(filename)
        button = InlineKeyboardButton(
            text=f"📅 {pretty_date}", 
            callback_data=f"download_db:{item['id']}"
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
    """Полное удаление всех бэкапов пользователя из базы данных."""
    user_id = str(message.from_user.id)
    backups = get_user_backups(user_id)
    
    if not backups:
        bot.reply_to(message, "У вас и так нет сохранённых копий в облаке.")
        return

    try:
        if db:
            backups_ref = get_user_backups_ref(user_id)
            for item in backups:
                backups_ref.document(item["id"]).delete()
        else:
            if user_id in local_db_fallback:
                del local_db_fallback[user_id]
        
        bot.reply_to(
            message, 
            "🗑️ *Облако очищено:* Все ваши записи резервных копий были удалены!", 
            parse_mode='Markdown'
        )
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при очистке облака: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('download_db:'))
def handle_backup_download(call):
    """Обработка нажатия на кнопку бэкапа."""
    user_id = str(call.from_user.id)
    backup_id = call.data.split('download_db:')[1]
    
    backups = get_user_backups(user_id)
    target_backup = next((b for b in backups if b["id"] == backup_id), None)

    if not target_backup:
        bot.answer_callback_query(call.id, text="Ошибка: запись не найдена в базе данных!", show_alert=True)
        return

    try:
        bot.answer_callback_query(call.id, text="Файл успешно извлечен!")
        
        # Отправляем файл резервной копии пользователю в чат
        bot.send_document(
            call.message.chat.id, 
            target_backup["file_id"], 
            visible_file_name=DEFAULT_BACKUP_NAME,
            caption=f"📦 Восстановление от {parse_datetime_from_filename(target_backup['filename'])}."
        )
        
        # Удаляем само меню выбора, чтобы не засорять историю сообщений
        try:
            bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception as delete_err:
            print(f"Ошибка удаления сообщения выбора: {delete_err}")
            
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Ошибка при отправке файла: {str(e)}")

def run_bot():
    print("Бот Survival Budget успешно запущен...")
    bot.infinity_polling()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
