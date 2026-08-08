import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
)

TELEGRAM_ANSWER_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
)

ANYMODEL_API_URL = "https://anymodel.org/v1/chat/completions"

FAST_MODEL = "gpt-5.6-luna"
DEEP_MODEL = "gpt-5.6-terra"

# Режим каждого пользователя
user_modes = {}


def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        payload["reply_markup"] = {
            "inline_keyboard": keyboard
        }

    try:
        requests.post(
            TELEGRAM_API_URL,
            json=payload,
            timeout=15
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
            timeout=10
        )
    except Exception:
        pass


def menu():
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


def ask_ai(user_text, model):
    headers = {
        "Authorization": f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": user_text
            }
        ]
    }

    try:
        response = requests.post(
            ANYMODEL_API_URL,
            headers=headers,
            json=payload,
            timeout=60
        )

        if not response.ok:
            return (
                "Не получилось получить ответ. "
                "Попробуй ещё раз через несколько секунд."
            )

        data = response.json()

        return data["choices"][0]["message"]["content"]

    except Exception:
        return (
            "Не получилось получить ответ. "
            "Попробуй ещё раз."
        )


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
            user_modes[chat_id] = FAST_MODEL

            send_message(
                chat_id,
                "⚡ Быстрый режим включён.\n\n"
                "Пиши вопрос."
            )

        elif data == "deep":
            user_modes[chat_id] = DEEP_MODEL

            send_message(
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


    # Старт
    if text == "/start":

        user_modes[chat_id] = FAST_MODEL

        send_message(
            chat_id,
            "Привет! 👋\n\n"
            "Выбери режим:",
            menu()
        )

        return jsonify({"ok": True})


    # Если режим ещё не выбран
    if chat_id not in user_modes:

        user_modes[chat_id] = FAST_MODEL

        send_message(
            chat_id,
            "Выбери режим:",
            menu()
        )

        return jsonify({"ok": True})


    # Отправляем вопрос в выбранную модель
    model = user_modes[chat_id]

    answer = ask_ai(text, model)

    send_message(
        chat_id,
        answer,
        menu()
    )

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
