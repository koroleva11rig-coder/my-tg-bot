import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# ENV
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

# ИМЕНА ИЗ ТВОЕГО VERCEL
REDIS_URL = os.environ.get("KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("KV_REST_API_TOKEN")

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SEND_MESSAGE_URL = f"{TELEGRAM_BASE}/sendMessage"
ANSWER_CALLBACK_URL = f"{TELEGRAM_BASE}/answerCallbackQuery"

# =========================================================
# ANYMODEL
# =========================================================

AI_URL = "https://anymodel.org/v1/chat/completions"

FAST_MODEL = "cx/gpt-5.6-luna"
DEEP_MODEL = "cx/gpt-5.6-terra"

# =========================================================
# SETTINGS
# =========================================================

MAX_MESSAGES = 100
CONTEXT_TTL = 2592000

SYSTEM_PROMPT = """
Ты — постоянный AI-помощник пользователя.

Ты ведёшь ОДИН непрерывный разговор.

Все предыдущие сообщения в истории являются частью текущего
разговора. Всегда используй их, когда они относятся к текущему
вопросу.

Luna и Terra — это две модели одного и того же помощника.

Переключение между Luna и Terra НЕ создаёт новый разговор.
Обе модели получают одну и ту же историю.

Если пользователь пишет:
"этот вопрос", "а теперь", "а что насчёт этого",
"как ты говорил выше" и тому подобное,
обязательно используй предыдущие сообщения для определения,
о чём именно идёт речь.

Не проси пользователя повторять вопрос, если он есть в истории.

Сегодняшняя дата передаётся отдельно в каждом запросе.
Используй её для вопросов про сегодня, завтра, вчера и дни недели.

Отвечай на русском языке, если пользователь не просит другой язык.

Luna:
быстрые, короткие и практичные ответы.

Terra:
более глубокий анализ и рассуждение.

Обе модели обязаны сохранять одинаковый контекст.
"""

# =========================================================
# REDIS
# =========================================================

def redis_headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json"
    }


def redis_get(key):

    if not REDIS_URL or not REDIS_TOKEN:
        return None

    try:
        response = requests.get(
            f"{REDIS_URL}/get/{key}",
            headers=redis_headers(),
            timeout=10
        )

        if not response.ok:
            return None

        return response.json().get("result")

    except Exception:
        return None


def redis_set(key, value):

    if not REDIS_URL or not REDIS_TOKEN:
        return False

    try:
        response = requests.post(
            f"{REDIS_URL}/set/{key}?EX={CONTEXT_TTL}",
            headers=redis_headers(),
            data=json.dumps(
                value,
                ensure_ascii=False
            ),
            timeout=10
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

        if data.get("mode") not in ["luna", "terra"]:
            data["mode"] = "luna"

        if not isinstance(data.get("messages"), list):
            data["messages"] = []

        return data

    except Exception:

        return {
            "mode": "luna",
            "messages": []
        }


def save_chat_data(chat_id, data):

    data["messages"] = data.get(
        "messages",
        []
    )[-MAX_MESSAGES:]

    redis_set(
        f"telegram_chat:{chat_id}",
        data
    )


# =========================================================
# TELEGRAM
# =========================================================

def send_message(chat_id, text, keyboard=None):

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:

        payload["reply_markup"] = json.dumps({
            "inline_keyboard": keyboard
        })

    try:

        requests.post(
            SEND_MESSAGE_URL,
            json=payload,
            timeout=15
        )

    except Exception:
        pass


def answer_callback(callback_id):

    try:

        requests.post(
            ANSWER_CALLBACK_URL,
            json={
                "callback_query_id": callback_id
            },
            timeout=10
        )

    except Exception:
        pass


# =========================================================
# MENU
# =========================================================

def start_menu(chat_id):

    keyboard = [
        [
            {
                "text": "⚡ Быстрый ответ",
                "callback_data": "luna"
            },
            {
                "text": "🧠 Подумать глубже",
                "callback_data": "terra"
            }
        ],
        [
            {
                "text": "🗑 Очистить контекст",
                "callback_data": "reset"
            }
        ]
    ]

    send_message(
        chat_id,
        "Выбери режим:",
        keyboard
    )


# =========================================================
# AI
# =========================================================

def ask_ai(chat_data):

    if chat_data["mode"] == "terra":
        model = DEEP_MODEL
    else:
        model = FAST_MODEL

    # Текущая дата передаётся модели.
    from datetime import datetime

    today = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    system_message = (
        SYSTEM_PROMPT
        + "\n\nТекущая дата и время сервера: "
        + today
    )

    messages = [
        {
            "role": "system",
            "content": system_message
        }
    ]

    messages.extend(
        chat_data["messages"]
    )

    headers = {
        "Authorization": f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages
    }

    try:

        response = requests.post(
            AI_URL,
            headers=headers,
            json=payload,
            timeout=180
        )

        if not response.ok:

            return (
                f"Ошибка AI: HTTP "
                f"{response.status_code}\n\n"
                f"{response.text[:2000]}"
            )

        data = response.json()

        return (
            data["choices"][0]
            ["message"]
            ["content"]
        )

    except Exception as e:

        return (
            "Ошибка соединения с AI:\n\n"
            + str(e)
        )


# =========================================================
# WEBHOOK
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "Telegram AI bot is running.", 200


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "redis": bool(
            REDIS_URL and REDIS_TOKEN
        ),
        "telegram": bool(
            TELEGRAM_TOKEN
        ),
        "anymodel": bool(
            ANYMODEL_API_KEY
        )
    })


@app.route("/api/index", methods=["GET", "POST"])
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    # =====================================================
    # BUTTON
    # =====================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

        answer_callback(
            callback.get("id")
        )

        chat_id = (
            callback
            .get("message", {})
            .get("chat", {})
            .get("id")
        )

        if not chat_id:
            return jsonify({
                "ok": True
            })

        data = callback.get("data")

        chat_data = get_chat_data(
            chat_id
        )

        if data == "luna":

            chat_data["mode"] = "luna"

            save_chat_data(
                chat_id,
                chat_data
            )

            send_message(
                chat_id,
                "⚡ Быстрый режим Luna включён.\n\n"
                "Контекст сохранён."
            )

            return jsonify({
                "ok": True
            })

        if data == "terra":

            chat_data["mode"] = "terra"

            save_chat_data(
                chat_id,
                chat_data
            )

            send_message(
                chat_id,
                "🧠 Глубокий режим Terra включён.\n\n"
                "Контекст сохранён."
            )

            return jsonify({
                "ok": True
            })

        if data == "reset":

            save_chat_data(
                chat_id,
                {
                    "mode": "luna",
                    "messages": []
                }
            )

            start_menu(
                chat_id
            )

            return jsonify({
                "ok": True
            })

        return jsonify({
            "ok": True
        })

    # =====================================================
    # MESSAGE
    # =====================================================

    message = update.get(
        "message"
    )

    if not message:

        return jsonify({
            "ok": True
        })

    chat_id = (
        message
        .get("chat", {})
        .get("id")
    )

    if not chat_id:

        return jsonify({
            "ok": True
        })

    text = (
        message
        .get("text", "")
        .strip()
    )

    # =====================================================
    # START
    # =====================================================

    if text == "/start":

        start_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    # =====================================================
    # RESET
    # =====================================================

    if text == "/reset":

        save_chat_data(
            chat_id,
            {
                "mode": "luna",
                "messages": []
            }
        )

        start_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    # =====================================================
    # LOAD HISTORY
    # =====================================================

    chat_data = get_chat_data(
        chat_id
    )

    # =====================================================
    # ADD USER MESSAGE
    # =====================================================

    if not text:

        return jsonify({
            "ok": True
        })

    chat_data["messages"].append({
        "role": "user",
        "content": text
    })

    # =====================================================
    # AI
    # =====================================================

    answer = ask_ai(
        chat_data
    )

    # =====================================================
    # SAVE ANSWER
    # =====================================================

    chat_data["messages"].append({
        "role": "assistant",
        "content": answer
    })

    save_chat_data(
        chat_id,
        chat_data
    )

    # =====================================================
    # SEND
    # =====================================================

    send_message(
        chat_id,
        answer
    )

    return jsonify({
        "ok": True
    })


if __name__ == "__main__":
    app.run()
