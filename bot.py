import os
import time
import sqlite3
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
import telebot
import a2s
 
load_dotenv()
 
TOKEN = os.getenv("TELEGRAM_TOKEN")
 
if not TOKEN:
    raise ValueError("Проверь .env — TOKEN обязателен!")
 
# ====================== НАСТРОЙКИ ARMA 3 СЕРВЕРА ======================
# Query-порт обычно = игровой порт + 1 (например, игровой 2302 -> query 2303)
ARMA_SERVER_IP = os.getenv("ARMA_SERVER_IP", "")
ARMA_SERVER_QUERY_PORT = int(os.getenv("ARMA_SERVER_QUERY_PORT", "2303"))
 
bot = telebot.TeleBot(TOKEN)
 
print(f"🤖 Бот запущен как: @{bot.get_me().username}")
 
# ====================== НАСТРОЙКИ АНТИСПАМА ======================
REPEAT_THRESHOLD = 3          # сколько одинаковых сообщений подряд считать спамом
REPEAT_WINDOW_SECONDS = 60    # за какой период времени считаем повторы
MUTE_DURATION_SECONDS = 3600  # на сколько глушить нарушителя (1 час)
 
# user_id -> chat_id -> list of (normalized_text, timestamp)
user_messages = defaultdict(lambda: defaultdict(list))
 
# ====================== БД (лог истории, без ИИ) ======================
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
    except Exception as e:
        print(f"Ошибка проверки прав: {e}")
        return False
 
 
def is_spam(user_id, chat_id, text) -> bool:
    now = time.time()
    normalized = normalize_text(text)
    if not normalized:
        return False
 
    records = user_messages[user_id][chat_id]
    # оставляем только записи в пределах окна
    records[:] = [r for r in records if now - r[1] <= REPEAT_WINDOW_SECONDS]
    records.append((normalized, now))
 
    same_count = sum(1 for r in records if r[0] == normalized)
    return same_count >= REPEAT_THRESHOLD
 
 
def mute_user(chat_id, user_id):
    until = int(time.time() + MUTE_DURATION_SECONDS)
    try:
        bot.restrict_chat_member(
            chat_id,
            user_id,
            until_date=until,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        return True
    except Exception as e:
        print(f"Ошибка мута пользователя: {e}")
        return False
 
 
def get_arma_server_info():
    address = (ARMA_SERVER_IP, ARMA_SERVER_QUERY_PORT)
    info = a2s.info(address, timeout=5)
    return info
 
 
# ====================== ХЕНДЛЕРЫ ======================
@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Привет! Я бот-модератор чата.")
 
 
@bot.message_handler(commands=['online'])
def online(msg):
    if not ARMA_SERVER_IP:
        bot.reply_to(msg, "⚠️ IP сервера не настроен (ARMA_SERVER_IP в .env).")
        return
 
    try:
        info = get_arma_server_info()
        text = (
            f"🎮 {info.server_name}\n"
            f"🗺 Карта: {info.map_name}\n"
            f"👥 Онлайн: {info.player_count}/{info.max_players}"
        )
        bot.reply_to(msg, text)
    except Exception as e:
        print(f"Ошибка запроса к серверу Arma: {e}")
        bot.reply_to(msg, "😔 Не удалось получить данные с сервера. Возможно, он offline или неверно указан IP/порт.")
 
 
@bot.message_handler(commands=['vpn'])
def vpn(msg):
    if msg.chat.type != "private":
        # Если команду вызвали в группе — вежливо перенаправляем в ЛС
        bot.reply_to(msg, "🔒 Команда /vpn работает только в личных сообщениях.\nНапиши мне в личку 👇")
        return
    
    # Красивый ответ с кнопкой
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🚀 Перейти по ссылке", url="https://t.me/Gladiuzbot?start=1009623720"))
    
    bot.send_message(
        msg.chat.id,
        "✅ <b>Ссылка на VPN</b>\n\n"
        "Нажми кнопку ниже, чтобы перейти:",
        parse_mode='HTML',
        reply_markup=markup
    )
 
 
@bot.message_handler(content_types=['text', 'photo'])
def all_messages(msg):
    user_id = msg.from_user.id
    chat_id = msg.chat.id
    text = msg.text or msg.caption or ""
 
    save_history(user_id, chat_id, text)
 
    # В группах/супергруппах проверяем на спам, в личке — нет
    if msg.chat.type in ("group", "supergroup"):
        if is_admin(chat_id, user_id):
            return  # админов не проверяем
 
        if is_spam(user_id, chat_id, text):
            try:
                bot.delete_message(chat_id, msg.message_id)
            except Exception as e:
                print(f"Ошибка удаления сообщения: {e}")
 
            muted = mute_user(chat_id, user_id)
            if muted:
                minutes = MUTE_DURATION_SECONDS // 60
                bot.send_message(
                    chat_id,
                    f"🚫 {msg.from_user.first_name} заглушен на {minutes} мин. за спам/рекламу."
                )
            # очищаем историю сообщений пользователя, чтобы не мутить повторно
            user_messages[user_id][chat_id].clear()
 
 
# ====================== ЗАПУСК ======================
if __name__ == "__main__":
    print("🛑 Останавливаем старые процессы...")
    bot.remove_webhook()
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(3)  # даём время старому инстансу (если есть) полностью остановиться
 
    print("🚀 Запуск бота...")
    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=1, timeout=30)
        except Exception as e:
            print(f"Бот упал с ошибкой, перезапуск через 5 секунд: {e}")
            time.sleep(5)
