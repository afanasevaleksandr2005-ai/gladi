import os
import time
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
import telebot
from telebot import types
import a2s

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("Проверь .env — TOKEN обязателен!")

# ====================== НАСТРОЙКИ ======================
ARMA_SERVER_IP = os.getenv("ARMA_SERVER_IP", "46.174.48.58")      # Gladius
ARMA_SERVER_QUERY_PORT = int(os.getenv("ARMA_SERVER_QUERY_PORT", "2503"))

# VPN
VPN_LINK = "https://t.me/Strelka_vpn_bot?start=1009623720"
VPN_MESSAGE = "🔑 <b>Нужен VPN для комфортной игры?</b>\n\nПереходи по ссылке ниже 👇"

AUTO_VPN_INTERVAL = 7200  # 2 часа

bot = telebot.TeleBot(TOKEN)

print(f"🤖 Бот запущен как: @{bot.get_me().username}")

# ====================== АНТИСПАМ ======================
REPEAT_THRESHOLD = 3
REPEAT_WINDOW_SECONDS = 60
MUTE_DURATION_SECONDS = 3600

user_messages = defaultdict(lambda: defaultdict(list))

# ====================== БД ======================
conn = sqlite3.connect('bot_data.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    chat_id INTEGER,
                    content TEXT,
                    timestamp TEXT)''')
conn.commit()

def save_history(user_id, chat_id, content):
    cursor.execute(
        "INSERT INTO chat_history (user_id, chat_id, content, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, chat_id, content[:500], datetime.now().isoformat())
    )
    conn.commit()

def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())

def is_admin(chat_id, user_id) -> bool:
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

def is_spam(user_id, chat_id, text) -> bool:
    now = time.time()
    normalized = normalize_text(text)
    if not normalized:
        return False

    records = user_messages[user_id][chat_id]
    records[:] = [r for r in records if now - r[1] <= REPEAT_WINDOW_SECONDS]
    records.append((normalized, now))

    same_count = sum(1 for r in records if r[0] == normalized)
    return same_count >= REPEAT_THRESHOLD

def mute_user(chat_id, user_id, first_name):
    until = int(time.time() + MUTE_DURATION_SECONDS)
    try:
        bot.restrict_chat_member(
            chat_id, user_id, until_date=until,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        minutes = MUTE_DURATION_SECONDS // 60
        bot.send_message(chat_id, f"🚫 {first_name} заглушен на {minutes} мин. за спам.")
        return True
    except Exception as e:
        print(f"Ошибка мута: {e}")
        return False

def get_arma_server_info():
    try:
        address = (ARMA_SERVER_IP, ARMA_SERVER_QUERY_PORT)
        info = a2s.info(address, timeout=5)
        return info
    except:
        return None

# ====================== ХЕНДЛЕРЫ ======================
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Привет! Я бот-модератор чата.")

@bot.message_handler(commands=['online'])
def online(msg):
    try:
        info = get_arma_server_info()
        if info:
            text = (
                f"🎮 <b>{info.server_name}</b>\n"
                f"🗺 Карта: <code>{info.map_name}</code>\n"
                f"👥 Онлайн: <b>{info.player_count}/{info.max_players}</b>"
            )
            bot.send_message(msg.chat.id, text, parse_mode='HTML')
        else:
            bot.reply_to(msg, "😔 Не удалось получить данные с сервера.")
    except Exception as e:
        print(f"Arma error: {e}")
        bot.reply_to(msg, "😔 Не удалось получить данные с сервера.")

@bot.message_handler(commands=['vpn'])
def vpn(msg):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Получить VPN", url=VPN_LINK))
    
    bot.send_message(
        msg.chat.id,
        VPN_MESSAGE,
        parse_mode='HTML',
        reply_markup=markup,
        disable_web_page_preview=True
    )

@bot.message_handler(commands=['id'])
def get_chat_id(msg):
    chat_id = msg.chat.id
    print(f"📌 Chat ID: {chat_id}")
    bot.reply_to(msg, f"🆔 ID этого чата:\n`{chat_id}`", parse_mode='Markdown')

@bot.message_handler(content_types=['text', 'photo', 'video', 'document'])
def all_messages(msg):
    user_id = msg.from_user.id
    chat_id = msg.chat.id
    text = msg.text or msg.caption or "[media]"

    save_history(user_id, chat_id, text)

    if msg.chat.type in ("group", "supergroup"):
        if is_admin(chat_id, user_id):
            return
        if is_spam(user_id, chat_id, text):
            try:
                bot.delete_message(chat_id, msg.message_id)
            except:
                pass
            mute_user(chat_id, user_id, msg.from_user.first_name)

# ====================== АВТООТПРАВКА VPN ======================
def auto_send_vpn():
    while True:
        try:
            GROUP_CHAT_ID = -1001908351016   # GladiusGORN
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚀 Получить VPN", url=VPN_LINK))
            
            bot.send_message(
                GROUP_CHAT_ID,
                VPN_MESSAGE,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=True
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Авто-VPN отправлен в группу")
        except Exception as e:
            print(f"❌ Ошибка авто-VPN: {e}")
        
        time.sleep(AUTO_VPN_INTERVAL)

# ====================== ЗАПУСК ======================
if __name__ == "__main__":
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)

    # Запуск автоотправки в фоне
    threading.Thread(target=auto_send_vpn, daemon=True).start()

    print("🚀 Бот запущен...")
    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            print(f"Бот упал: {e}. Перезапуск...")
            time.sleep(5)
