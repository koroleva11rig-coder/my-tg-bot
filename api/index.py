import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
TELEGRAM_WEBHOOK_URL = "https://my-tg-bot-tau.vercel.app/api/index"

ANYMODEL_API_URL = "https://anymodel.org/v1/chat/completions"
MODEL = "gpt-5.6-terra"


def ask_ai(user_text):
    try:
        response = requests.post(
            ANYMODEL_API_URL,
            headers={
                "Authorization": f"Bearer {ANYMODEL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": user_text
                    }
                ]
            },
            timeout=60
        )

        if not response.ok:
            return f"AI ERROR\n\nHTTP {response.status_code}\n\n{response.text}"

        data = response.json()
        return data["choices"][0]["message"]["content"]

    except Exception as e:
        return f"AI CONNECTION ERROR\n\n{e}"


def send_telegram_message(chat_id, text):
    try:
        requests.post(
            TELEGRAM_API_URL,
            json={
                "chat_id": chat_id,
                "text": text
            },
            timeout=15
        )
    except Exception:
        pass


@app.route("/", methods=["GET"])
def home():
    return "Telegram AI bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={
                "url": TELEGRAM_WEBHOOK_URL
            },
            timeout=15
        )

        return response.text, response.status_code

    except Exception as e:
        return str(e), 500


@app.route("/api/index", methods=["GET", "POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return jsonify({"ok": True})

    text = message.get("text", "").strip()

    if not text:
        send_telegram_message(chat_id, "Отправь текст.")
        return jsonify({"ok": True})

    answer = ask_ai(text)
    send_telegram_message(chat_id, answer)

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
