import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
import telebot
from mistralai import Mistral

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден!")
if not MISTRAL_API_KEY:
    raise ValueError("MISTRAL_API_KEY не найден! Добавь его в .env")

bot = telebot.TeleBot(TOKEN)

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
print(f"🤖 Бот запущен как: @{bot.get_me().username}")

client_mistral = Mistral(api_key=MISTRAL_API_KEY)

CURRENT_MODEL = "mistral-large-latest"   # mistral-large-latest / mistral-small-latest / pixtral-large

# История чата
history = defaultdict(list)

# ====================== БАЗА ДАННЫХ ======================
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS bad_words (word TEXT PRIMARY KEY)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT)''')
conn.commit()

ADMINS = [1009623720, 6296059302, 1001908351016]
warnings = defaultdict(int)

# ====================== ФУНКЦИИ ======================
def save_to_history(user_id, role, content):
    history[user_id].append({"role": role, "content": content})
    if len(history[user_id]) > 20:
        history[user_id] = history[user_id][-20:]
    
    cursor.execute("INSERT INTO chat_history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, role, content[:500], datetime.now().isoformat()))
    conn.commit()

def get_mistral_response(user_message: str, user_id: int, photo_url=None):
    messages = [{"role": "system", "content": "Ты — дружелюбный, остроумный и полезный ИИ-помощник. Отвечай на русском языке."}]
    messages.extend(history[user_id])
    
    user_content = [{"type": "text", "text": user_message or "Опиши изображение"}]
    if photo_url:
        user_content.append({"type": "image_url", "image_url": photo_url})
    
    messages.append({"role": "user", "content": user_content})

    try:
        response = client_mistral.chat.complete(
            model=CURRENT_MODEL,
            messages=messages,
            temperature=0.75,
            max_tokens=1500
        )
        answer = response.choices[0].message.content.strip()
        save_to_history(user_id, "assistant", answer)
        return answer
    except Exception as e:
        print(f"Mistral Error: {e}")
        return "😔 Mistral сейчас недоступен. Попробуй позже."

def is_spam(message):
    if not message.text:
        return False
    text = message.text.lower()
    spam_keywords = ['подработка', 'зарплата', 'выплаты', 'студентам', 'найму']
    return any(kw in text for kw in spam_keywords) or len(text) > 200


# ====================== КОМАНДЫ ======================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, f"Привет! Я бот на **Mistral** ({CURRENT_MODEL})\n\n"
                         f"/model large — большая модель\n"
                         f"/model small — быстрая модель\n"
                         f"/clear — очистить историю")

@bot.message_handler(commands=['model'])
def switch_model(message):
    global CURRENT_MODEL
    if message.from_user.id not in ADMINS:
        return bot.reply_to(message, "Только для админов.")
    
    text = message.text.lower()
    if "large" in text:
        CURRENT_MODEL = "mistral-large-latest"
    elif "small" in text:
        CURRENT_MODEL = "mistral-small-latest"
    elif "pixtral" in text:
        CURRENT_MODEL = "pixtral-large"
    bot.reply_to(message, f"✅ Модель изменена на **{CURRENT_MODEL}**")

@bot.message_handler(commands=['clear'])
def clear_history(message):
    history[message.from_user.id].clear()
    bot.reply_to(message, "✅ История чата очищена.")

# ====================== ОБРАБОТКА СООБЩЕНИЙ ======================
@bot.message_handler(content_types=['text', 'photo'])
def handle_message(message):
    user_id = message.from_user.id
    text = message.text or (message.caption or "")

    if is_spam(message):
        return bot.reply_to(message, "🚫 Спам-детект.")

    # Сохраняем сообщение пользователя
    save_to_history(user_id, "user", text)

    # Обработка фото
    photo_url = None
    if message.photo:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    response = get_mistral_response(text, user_id, photo_url)
    bot.reply_to(message, response)


# ====================== ЗАПУСК ======================
if __name__ == "__main__":
    print("🚀 Запуск бота...")
    bot.remove_webhook()                    # Удаляем старый webhook
    bot.delete_webhook(drop_pending_updates=True)  # Очищаем очередь
    
    print("✅ Бот запущен в режиме polling")
    bot.infinity_polling(none_stop=True, interval=1)
