import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


def ask_gemini(user_text: str) -> str:
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
            timeout=15,
        )

        if resp.status_code != 200:
            return (
                f"HTTP {resp.status_code}\n\n"
                f"{resp.text}"
            )

        data = resp.json()

        if "candidates" not in data:
            return str(data)

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return str(e)


def send_telegram_message(chat_id, text):
    requests.post(
        TELEGRAM_API_URL,
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=15,
    )


@app.route("/api/index", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not text:
        send_telegram_message(chat_id, "Отправь текст.")
        return jsonify({"ok": True})

    answer = ask_gemini(text)

    send_telegram_message(chat_id, answer)

    return jsonify({"ok": True})


@app.route("/api/index", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True)
