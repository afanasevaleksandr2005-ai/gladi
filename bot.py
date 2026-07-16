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

if not TOKEN or not MISTRAL_API_KEY:
    raise ValueError("Проверь .env — TOKEN и MISTRAL_API_KEY обязательны!")

bot = telebot.TeleBot(TOKEN)

print(f"🤖 Бот запущен как: @{bot.get_me().username}")

client = Mistral(api_key=MISTRAL_API_KEY)
CURRENT_MODEL = "mistral-large-latest"

history = defaultdict(list)

# ====================== БД ======================
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT)''')
conn.commit()

ADMINS = [1009623720, 6296059302, 1001908351016]

def save_history(user_id, role, content):
    history[user_id].append({"role": role, "content": content})
    if len(history[user_id]) > 20:
        history[user_id] = history[user_id][-20:]
    cursor.execute("INSERT INTO chat_history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, role, content[:500], datetime.now().isoformat()))
    conn.commit()

def get_response(text: str, user_id: int, photo_url=None):
    messages = [{"role": "system", "content": "Ты — дружелюбный и полезный ИИ-помощник. Отвечай на русском."}]
    messages += history[user_id]

    if photo_url:
        content = [
            {"type": "text", "text": text or "Опиши это изображение"},
            {"type": "image_url", "image_url": photo_url}
        ]
    else:
        content = text

    messages.append({"role": "user", "content": content})

    try:
        resp = client.chat.complete(
            model=CURRENT_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1200
        )
        answer = resp.choices[0].message.content.strip()
        save_history(user_id, "assistant", answer)
        return answer
    except Exception as e:
        print(f"Ошибка Mistral: {e}")
        return "😔 Ошибка соединения с Mistral. Попробуй позже."

# ====================== ХЕНДЛЕРЫ ======================
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Привет! Я бот на Mistral AI.\n/model large | small — смена модели")

@bot.message_handler(commands=['model'])
def change_model(msg):
    global CURRENT_MODEL
    if msg.from_user.id not in ADMINS:
        return
    if "small" in msg.text.lower():
        CURRENT_MODEL = "mistral-small-latest"
    else:
        CURRENT_MODEL = "mistral-large-latest"
    bot.reply_to(msg, f"Модель изменена: {CURRENT_MODEL}")

@bot.message_handler(commands=['clear'])
def clear(msg):
    history[msg.from_user.id].clear()
    bot.reply_to(msg, "История очищена ✅")

@bot.message_handler(content_types=['text', 'photo'])
def all_messages(msg):
    user_id = msg.from_user.id
    text = msg.text or msg.caption or ""

    # Сохраняем запрос
    save_history(user_id, "user", text)

    photo_url = None
    if msg.photo:
        file_info = bot.get_file(msg.photo[-1].file_id)
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    answer = get_response(text, user_id, photo_url)
    bot.reply_to(msg, answer)


# ====================== ЗАПУСК (самое важное) ======================
if __name__ == "__main__":
    print("🛑 Останавливаем старые процессы...")
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    
    print("🚀 Запуск бота...")
    bot.infinity_polling(none_stop=True, interval=1, timeout=30)
