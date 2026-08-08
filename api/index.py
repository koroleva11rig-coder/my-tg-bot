import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
)

TELEGRAM_ANSWER_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
)

ANYMODEL_API_URL = "https://anymodel.org/v1/chat/completions"
DEEP_MODEL = "gpt-5.6-terra"

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


def send_telegram_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if keyboard:
        payload["reply_markup"] = {
            "inline_keyboard": keyboard
        }

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


def ask_fast(user_text):
    headers = {
        "Content-Type": "application/json"
    }

    params = {
        "key": GEMINI_API_KEY
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": user_text
                    }
                ]
            }
        ]
    }

    try:
        resp = requests.post(
            GEMINI_API_URL,
            headers=headers,
            params=params,
            json=payload,
            timeout=30,
        )

        if not resp.ok:
            return (
                f"Ошибка быстрой модели.\n\n"
                f"HTTP {resp.status_code}\n\n"
                f"{resp.text}"
            )

        data = resp.json()

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return f"Ошибка подключения:\n\n{e}"


def ask_deep(user_text):
    headers = {
        "Authorization": f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEEP_MODEL,
        "messages": [
            {
                "role": "user",
                "content": user_text,
            }
        ],
    }

    try:
        resp = requests.post(
            ANYMODEL_API_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if not resp.ok:
            return (
                f"Ошибка глубокой модели.\n\n"
                f"HTTP {resp.status_code}\n\n"
                f"{resp.text}"
            )

        data = resp.json()

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        return f"Ошибка подключения:\n\n{e}"


def main_menu():
    return [
        [
            {
                "text": "⚡ Быстрый ответ",
                "callback_data": "fast"
            },
            {
                "text": "🧠 Подумать глубже",
                "callback_data": "deep"
            }
        ]
    ]


@app.route("/", methods=["GET"])
def home():
    return "Telegram AI bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


@app.route("/api/index", methods=["GET", "POST"])
def webhook():

    update = request.get_json(silent=True) or {}

    # Нажатие кнопки
    callback = update.get("callback_query")

    if callback:
        callback_id = callback.get("id")
        data = callback.get("data")
        message = callback.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        answer_callback(callback_id)

        if data == "fast":
            send_telegram_message(
                chat_id,
                "⚡ Быстрый режим включён.\n\n"
                "Пиши вопрос."
            )

        elif data == "deep":
            send_telegram_message(
                chat_id,
                "🧠 Глубокий режим включён.\n\n"
                "Пиши вопрос."
            )

        return jsonify({"ok": True})


    # Обычное сообщение
    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not chat_id:
        return jsonify({"ok": True})

    text = message.get("text", "").strip()

    if not text:
        return jsonify({"ok": True})


    # Главное меню
    if text == "/start":
        send_telegram_message(
            chat_id,
            "Привет! Я Света 👋\n\n"
            "Выбери режим:",
            main_menu()
        )

        return jsonify({"ok": True})


    # По умолчанию быстрый режим
    answer = ask_fast(text)

    send_telegram_message(
        chat_id,
        answer,
        main_menu()
    )

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
