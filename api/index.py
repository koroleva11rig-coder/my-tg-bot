import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent"
)

def ask_gemini(user_text: str) -> str:
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": user_text}
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
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Ошибка при обращении к Gemini: {e}"

def send_telegram_message(chat_id, text: str):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(TELEGRAM_API_URL, json=payload, timeout=8)

@app.route("/api/index", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    user_text = message.get("text", "")

    if not user_text:
        send_telegram_message(chat_id, "Пришли текстовое сообщение, я обрабатываю только текст.")
        return jsonify({"ok": True})

    gemini_reply = ask_gemini(user_text)
    send_telegram_message(chat_id, gemini_reply)

    return jsonify({"ok": True})

@app.route("/api/index", methods=["GET"])
def health_check():
    return "Bot is alive", 200

if __name__ == "__main__":
    app.run(debug=True)
