import os
import re
import sqlite3
from collections import defaultdict
from dotenv import load_dotenv
import telebot
from google import genai
from google.genai.types import GenerateContentConfig
from mistralai import Mistral
from datetime import datetime

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден!")

bot = telebot.TeleBot(TOKEN)
bot.delete_webhook(drop_pending_updates=True)

BOT_USERNAME = bot.get_me().username
print(f"🤖 Бот запущен как: @{BOT_USERNAME}")

# ====================== ИИ ======================
client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
client_mistral = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None

CURRENT_AI = "mistral"
CURRENT_MODEL = "mistral-large-latest"  # По умолчанию

# История чата: {user_id: [{"role": "user/assistant", "content": "..."}]}
history = defaultdict(list)

# ====================== База данных ======================
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS bad_words (word TEXT PRIMARY KEY)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS bans (id INTEGER PRIMARY KEY, user_id INTEGER, username TEXT, reason TEXT, date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT)''')

ADMINS = [1009623720, 6296059302, 1001908351016]
warnings = defaultdict(int)

# ====================== Функции ======================
def save_to_history(user_id, role, content):
    history[user_id].append({"role": role, "content": content})
    # Ограничиваем историю (чтобы не было слишком длинно)
    if len(history[user_id]) > 20:
        history[user_id] = history[user_id][-20:]
    
    cursor.execute("INSERT INTO chat_history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                   (user_id, role, content, datetime.now().isoformat()))
    conn.commit()

def get_ai_response(user_message: str, user_id: int, photo=None):
    global CURRENT_AI, CURRENT_MODEL

    if CURRENT_AI == "mistral" and client_mistral:
        messages = [{"role": "system", "content": "Ты — дружелюбный, остроумный и полезный ИИ-помощник. Отвечай на русском."}]
        messages.extend(history[user_id])
        
        if photo:
            # Mistral Pixtral поддерживает изображения
            messages.append({"role": "user", "content": [
                {"type": "text", "text": user_message or "Опиши это изображение"},
                {"type": "image_url", "image_url": photo}
            ]})
        else:
            messages.append({"role": "user", "content": user_message})

        try:
            response = client_mistral.chat.complete(
                model=CURRENT_MODEL,
                messages=messages,
                temperature=0.75,
                max_tokens=1500
            )
            answer = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Mistral Error: {e}")
            answer = "😔 Mistral временно недоступен."
    else:
        # Gemini (упрощённо)
        try:
            response = client_gemini.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_message,
                config=GenerateContentConfig(system_instruction="Ты — дружелюбный ИИ-помощник.")
            )
            answer = response.text or "Не понял 😅"
        except Exception as e:
            print(f"Gemini Error: {e}")
            answer = "😔 Gemini недоступен."

    save_to_history(user_id, "assistant", answer)
    return answer


def is_spam(message):
    if not message.text:
        return False
    text = message.text.lower()
    spam_keywords = ['подработка', 'зарплата', 'выплаты', 'студентам']
    return any(kw in text for kw in spam_keywords) or len(text) > 200


# ====================== Команды ======================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, f"Привет! Я ИИ-бот (@{BOT_USERNAME})\n"
                         f"Текущий ИИ: **{CURRENT_AI.upper()}** ({CURRENT_MODEL})\n\n"
                         f"Команды:\n"
                         f"/ai gemini — Gemini\n"
                         f"/ai mistral — Mistral\n"
                         f"/model large /model small — выбор модели Mistral")

@bot.message_handler(commands=['ai'])
def switch_ai(message):
    global CURRENT_AI
    if message.from_user.id not in ADMINS:
        return bot.reply_to(message, "Только для админов.")
    
    if "gemini" in message.text.lower():
        CURRENT_AI = "gemini"
        bot.reply_to(message, "✅ Переключено на **Gemini**")
    else:
        if client_mistral:
            CURRENT_AI = "mistral"
            bot.reply_to(message, f"✅ Переключено на **Mistral** ({CURRENT_MODEL})")
        else:
            bot.reply_to(message, "❌ Mistral ключ не настроен!")

@bot.message_handler(commands=['model'])
def switch_model(message):
    global CURRENT_MODEL
    if message.from_user.id not in ADMINS:
        return
    text = message.text.lower()
    if "large" in text:
        CURRENT_MODEL = "mistral-large-latest"
    elif "small" in text:
        CURRENT_MODEL = "mistral-small-latest"
    elif "pixtral" in text:
        CURRENT_MODEL = "pixtral-large"
    else:
        bot.reply_to(message, f"Текущая модель: {CURRENT_MODEL}")
        return
    bot.reply_to(message, f"✅ Модель изменена на **{CURRENT_MODEL}**")


# ====================== Обработка сообщений ======================
@bot.message_handler(content_types=['text', 'photo'])
def handle_all(message):
    user_id = message.from_user.id
    
    if is_spam(message):
        return bot.reply_to(message, "🚫 Спам-детект.")

    # Сохраняем сообщение пользователя
    text = message.text or (message.caption or "Изображение")
    save_to_history(user_id, "user", text)

    # Если есть фото
    photo_url = None
    if message.photo:
        # Получаем file_id самой большой версии
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        photo_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    response = get_ai_response(text, user_id, photo=photo_url)
    bot.reply_to(message, response)


print("🚀 Бот с Mistral + история + изображения запущен!")
bot.infinity_polling()
