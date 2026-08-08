import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# ENVIRONMENT VARIABLES
# =========================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

# =========================
# TELEGRAM
# =========================

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
)

TELEGRAM_ANSWER_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
)

# =========================
# AI
# =========================

ANYMODEL_API_URL = "https://anymodel.org/v1/chat/completions"

FAST_MODEL = "gpt-5.6-luna"
DEEP_MODEL = "gpt-5.6-terra"

# =========================
# SETTINGS
# =========================

MAX_MESSAGES = 100
CONTEXT_TTL = 2592000  # 30 дней


# =========================
# REDIS
# =========================

def redis_headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}"
    }


def redis_get(key):
    if not REDIS_URL or not REDIS_TOKEN:
        return None

    try:
        response = requests.get(
            f"{REDIS_URL}/get/{key}",
            headers=redis_headers(),
            timeout=10,
        )

        if not response.ok:
            return None

        data = response.json()

        return data.get("result")

    except Exception:
        return None


def redis_set(key, value):
    if not REDIS_URL or not REDIS_TOKEN:
        return False

    try:
        response = requests.post(
            f"{REDIS_URL}/set/{key}?EX={CONTEXT_TTL}",
            headers={
                **redis_headers(),
                "Content-Type": "application/json",
            },
            data=json.dumps(value, ensure_ascii=False),
            timeout=10,
        )

        return response.ok

    except Exception:
        return False


def get_chat_data(chat_id):
    key = f"telegram_chat:{chat_id}"

    raw = redis_get(key)

    if not raw:
        return {
            "mode": "luna",
            "messages": []
        }

    try:
        data = json.loads(raw)

        if not isinstance(data, dict):
            raise ValueError

        if "mode" not in data:
            data["mode"] = "luna"

        if "messages" not in data:
            data["messages"] = []

        return data

    except Exception:
        return {
            "mode": "luna",
            "messages": []
        }


def save_chat_data(chat_id, data):
    key = f"telegram_chat:{chat_id}"

    # Ограничиваем историю, чтобы она не разрасталась бесконечно.
    data["messages"] = data.get("messages", [])[-MAX_MESSAGES:]

    redis_set(key, data)


# =========================
# TELEGRAM FUNCTIONS
# =========================

def send_telegram_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if keyboard:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": keyboard
        }, ensure_ascii=False)

    try:
        requests.post(
            TELEGRAM_API_URL,
            json=payload,
            timeout=15,
        )

    except Exception:
        pass


def answer_callback(callback_id):
    try:
        requests.post(
            TELEGRAM_ANSWER_URL,
            json={
                "callback_query_id": callback_id
            },
            timeout=10,
        )

    except Exception:
        pass


# =========================
# START MENU
# =========================

def send_start_menu(chat_id):
    keyboard = [
        [
            {
                "text": "⚡ Быстрый ответ",
                "callback_data": "mode_luna"
            },
            {
                "text": "🧠 Подумать глубже",
                "callback_data": "mode_terra"
            }
        ]
    ]

    send_telegram_message(
        chat_id,
        "Привет! 👋\n\nВыбери режим:",
        keyboard,
    )


# =========================
# AI
# =========================

def ask_ai(chat_data):

    mode = chat_data.get("mode", "luna")

    if mode == "terra":
        model = DEEP_MODEL
    else:
        model = FAST_MODEL

    messages = chat_data.get("messages", [])

    headers = {
        "Authorization": f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    try:
        response = requests.post(
            ANYMODEL_API_URL,
            headers=headers,
            json=payload,
            timeout=120,
        )

        if not response.ok:
            return (
                f"Ошибка AI: HTTP {response.status_code}\n\n"
                f"{response.text[:2000]}"
            )

        data = response.json()

        answer = (
            data["choices"][0]
            ["message"]
            ["content"]
        )

        return answer

    except Exception as e:
        return f"Ошибка соединения с AI:\n\n{e}"


# =========================
# WEBHOOK
# =========================

@app.route("/", methods=["GET"])
def home():
    return "Telegram AI bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "redis": bool(REDIS_URL and REDIS_TOKEN),
        "telegram": bool(TELEGRAM_TOKEN),
        "anymodel": bool(ANYMODEL_API_KEY),
    }), 200


@app.route("/api/index", methods=["GET", "POST"])
def webhook():

    update = request.get_json(silent=True) or {}

    # =========================
    # BUTTON PRESS
    # =========================

    callback = update.get("callback_query")

    if callback:

        callback_id = callback.get("id")

        answer_callback(callback_id)

        data = callback.get("data")

        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if not chat_id:
            return jsonify({"ok": True})

        chat_data = get_chat_data(chat_id)

        if data == "mode_luna":

            chat_data["mode"] = "luna"

            save_chat_data(chat_id, chat_data)

            send_telegram_message(
                chat_id,
                "⚡ Быстрый режим включён.\n\nПиши вопрос."
            )

            return jsonify({"ok": True})

        if data == "mode_terra":

            chat_data["mode"] = "terra"

            save_chat_data(chat_id, chat_data)

            send_telegram_message(
                chat_id,
                "🧠 Глубокий режим включён.\n\nПиши вопрос."
            )

            return jsonify({"ok": True})

        return jsonify({"ok": True})

    # =========================
    # NORMAL MESSAGE
    # =========================

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return jsonify({"ok": True})

    text = message.get("text", "").strip()

    if not text:
        return jsonify({"ok": True})

    # =========================
    # START
    # =========================

    if text == "/start":
        send_start_menu(chat_id)
        return jsonify({"ok": True})

    # =========================
    # LOAD CONTEXT
    # =========================

    chat_data = get_chat_data(chat_id)

    # =========================
    # ADD USER MESSAGE
    # =========================

    chat_data["messages"].append({
        "role": "user",
        "content": text
    })

    # =========================
    # ASK AI
    # =========================

    answer = ask_ai(chat_data)

    # =========================
    # SAVE AI ANSWER
    # =========================

    chat_data["messages"].append({
        "role": "assistant",
        "content": answer
    })

    save_chat_data(chat_id, chat_data)

    # =========================
    # SEND ANSWER
    # =========================

    send_telegram_message(
        chat_id,
        answer
    )

    return jsonify({"ok": True})


# =========================
# LOCAL
# =========================

if __name__ == "__main__":
    app.run()
