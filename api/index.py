import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# ENV
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
)

TELEGRAM_SEND_URL = f"{TELEGRAM_BASE}/sendMessage"
TELEGRAM_ANSWER_URL = f"{TELEGRAM_BASE}/answerCallbackQuery"
TELEGRAM_GET_FILE_URL = f"{TELEGRAM_BASE}/getFile"

# ============================================================
# ANYMODEL
# ============================================================

ANYMODEL_CHAT_URL = "https://anymodel.org/v1/chat/completions"
ANYMODEL_TRANSCRIBE_URL = "https://anymodel.org/v1/audio/transcriptions"

# ВАЖНО:
# Это точные ID из твоего каталога AnyModel.
FAST_MODEL = "cx/gpt-5.6-luna"
DEEP_MODEL = "cx/gpt-5.6-terra"

# Whisper у тебя сейчас недоступен.
# Пробуем несколько OpenAI-compatible STT ID.
TRANSCRIBE_MODELS = [
    "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe",
    "whisper-1",
]

# ============================================================
# SETTINGS
# ============================================================

MAX_MESSAGES = 100

# 30 дней
CONTEXT_TTL = 2592000

# Общая системная инструкция для ОБЕИХ моделей.
# Модели отличаются только глубиной ответа.
SYSTEM_PROMPT = """
Ты — постоянный AI-ассистент пользователя.

Главное правило: сохраняй непрерывность разговора.

У тебя есть история предыдущих сообщений этого чата.
Всегда используй её, если она относится к текущему вопросу.

Не заставляй пользователя повторять информацию, которую он уже
сообщал в этом разговоре.

Если пользователь возвращается к теме после паузы, сначала проверь
историю разговора и восстанови контекст.

Luna и Terra — это ДВА РЕЖИМА ОДНОГО И ТОГО ЖЕ ассистента.
Переключение между ними НЕ должно создавать новый разговор.

Режим Luna:
- отвечай быстро;
- не усложняй простые задачи;
- сохраняй контекст так же строго, как Terra.

Режим Terra:
- трать больше времени на сложные рассуждения;
- проверяй логику;
- разбирай неоднозначности;
- сохраняй тот же самый контекст разговора.

Никогда не сообщай пользователю, что ты "забыл" контекст,
если нужная информация присутствует в истории.

Если информации действительно нет в истории — прямо скажи об этом.
"""

# ============================================================
# REDIS
# ============================================================

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
            data=json.dumps(
                value,
                ensure_ascii=False
            ),
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

        if data.get("mode") not in ("luna", "terra"):
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

    key = f"telegram_chat:{chat_id}"

    messages = data.get("messages", [])

    # Оставляем последние 100 сообщений.
    data["messages"] = messages[-MAX_MESSAGES:]

    redis_set(key, data)


# ============================================================
# TELEGRAM HELPERS
# ============================================================

def send_telegram_message(chat_id, text, keyboard=None):

    if not text:
        return

    # Telegram ограничивает сообщение примерно 4096 символами.
    chunks = [
        text[i:i + 4000]
        for i in range(0, len(text), 4000)
    ]

    for chunk in chunks:

        payload = {
            "chat_id": chat_id,
            "text": chunk,
        }

        if keyboard:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": keyboard
            }, ensure_ascii=False)

        try:
            requests.post(
                TELEGRAM_SEND_URL,
                json=payload,
                timeout=15,
            )

        except Exception:
            pass


def answer_callback(callback_id):

    if not callback_id:
        return

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


# ============================================================
# TELEGRAM COMMAND MENU
# ============================================================

def setup_bot_commands():

    if not TELEGRAM_TOKEN:
        return

    commands = [
        {
            "command": "start",
            "description": "Запустить бота"
        },
        {
            "command": "luna",
            "description": "⚡ Быстрый режим"
        },
        {
            "command": "terra",
            "description": "🧠 Глубокий режим"
        },
        {
            "command": "reset",
            "description": "🗑 Очистить контекст"
        },
    ]

    try:

        requests.post(
            f"{TELEGRAM_BASE}/setMyCommands",
            json={
                "commands": commands
            },
            timeout=10,
        )

    except Exception:
        pass


# ============================================================
# START MENU
# ============================================================

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
        ],
        [
            {
                "text": "🗑 Очистить контекст",
                "callback_data": "reset_context"
            }
        ]
    ]

    send_telegram_message(
        chat_id,
        "Выбери режим:",
        keyboard,
    )


# ============================================================
# AI
# ============================================================

def ask_ai(chat_data):

    mode = chat_data.get("mode", "luna")

    if mode == "terra":
        model = DEEP_MODEL
    else:
        model = FAST_MODEL

    history = chat_data.get("messages", [])

    # SYSTEM PROMPT добавляется на каждый запрос.
    # Он НЕ сохраняется как сообщение пользователя.
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history)

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
            ANYMODEL_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=180,
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

        return (
            "Ошибка соединения с AI:\n\n"
            f"{e}"
        )


# ============================================================
# TELEGRAM FILE DOWNLOAD
# ============================================================

def download_telegram_file(file_id):

    try:

        response = requests.get(
            f"{TELEGRAM_BASE}/getFile",
            params={
                "file_id": file_id
            },
            timeout=15,
        )

        if not response.ok:
            return None

        data = response.json()

        file_path = (
            data.get("result", {})
            .get("file_path")
        )

        if not file_path:
            return None

        file_url = (
            f"https://api.telegram.org/file/"
            f"bot{TELEGRAM_TOKEN}/{file_path}"
        )

        audio_response = requests.get(
            file_url,
            timeout=30,
        )

        if not audio_response.ok:
            return None

        return audio_response.content

    except Exception:
        return None


# ============================================================
# VOICE TRANSCRIPTION
# ============================================================

def transcribe_audio(audio_bytes):

    if not audio_bytes:
        return None

    headers = {
        "Authorization": f"Bearer {ANYMODEL_API_KEY}",
    }

    last_error = None

    for model in TRANSCRIBE_MODELS:

        try:

            files = {
                "file": (
                    "voice.ogg",
                    audio_bytes,
                    "audio/ogg"
                )
            }

            data = {
                "model": model
            }

            response = requests.post(
                ANYMODEL_TRANSCRIBE_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=120,
            )

            if response.ok:

                result = response.json()

                text = result.get("text")

                if text:
                    return text.strip()

            last_error = (
                f"{model}: HTTP "
                f"{response.status_code}: "
                f"{response.text[:1000]}"
            )

        except Exception as e:

            last_error = (
                f"{model}: {e}"
            )

    return (
        "Ошибка распознавания голоса.\n\n"
        f"{last_error}"
    )


# ============================================================
# RESET
# ============================================================

def reset_context(chat_id):

    data = {
        "mode": "luna",
        "messages": []
    }

    save_chat_data(chat_id, data)


# ============================================================
# WEBHOOK
# ============================================================

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
        ),
    }), 200


@app.route("/api/index", methods=["GET", "POST"])
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    # ========================================================
    # CALLBACK BUTTON
    # ========================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

        callback_id = callback.get("id")

        answer_callback(
            callback_id
        )

        data = callback.get("data")

        message = (
            callback.get("message")
            or {}
        )

        chat = (
            message.get("chat")
            or {}
        )

        chat_id = chat.get("id")

        if not chat_id:
            return jsonify({
                "ok": True
            })

        chat_data = get_chat_data(
            chat_id
        )

        # FAST
        if data == "mode_luna":

            chat_data["mode"] = "luna"

            save_chat_data(
                chat_id,
                chat_data
            )

            send_telegram_message(
                chat_id,
                "⚡ Быстрый режим Luna включён.\n\n"
                "Контекст разговора сохранён."
            )

            return jsonify({
                "ok": True
            })

        # DEEP
        if data == "mode_terra":

            chat_data["mode"] = "terra"

            save_chat_data(
                chat_id,
                chat_data
            )

            send_telegram_message(
                chat_id,
                "🧠 Глубокий режим Terra включён.\n\n"
                "Контекст разговора сохранён."
            )

            return jsonify({
                "ok": True
            })

        # RESET
        if data == "reset_context":

            reset_context(
                chat_id
            )

            send_start_menu(
                chat_id
            )

            return jsonify({
                "ok": True
            })

        return jsonify({
            "ok": True
        })

    # ========================================================
    # NORMAL MESSAGE
    # ========================================================

    message = update.get(
        "message"
    )

    if not message:
        return jsonify({
            "ok": True
        })

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get("id")

    if not chat_id:
        return jsonify({
            "ok": True
        })

    # ========================================================
    # COMMANDS
    # ========================================================

    text = (
        message.get("text")
        or ""
    ).strip()

    if text == "/start":

        send_start_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    if text == "/luna":

        chat_data = get_chat_data(
            chat_id
        )

        chat_data["mode"] = "luna"

        save_chat_data(
            chat_id,
            chat_data
        )

        send_telegram_message(
            chat_id,
            "⚡ Luna включена.\n\n"
            "Общий контекст сохранён."
        )

        return jsonify({
            "ok": True
        })

    if text == "/terra":

        chat_data = get_chat_data(
            chat_id
        )

        chat_data["mode"] = "terra"

        save_chat_data(
            chat_id,
            chat_data
        )

        send_telegram_message(
            chat_id,
            "🧠 Terra включена.\n\n"
            "Общий контекст сохранён."
        )

        return jsonify({
            "ok": True
        })

    if text == "/reset":

        reset_context(
            chat_id
        )

        send_start_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    # ========================================================
    # VOICE MESSAGE
    # ========================================================

    voice = message.get("voice")

    if voice:

        file_id = voice.get(
            "file_id"
        )

        audio = download_telegram_file(
            file_id
        )

        if not audio:

            send_telegram_message(
                chat_id,
                "Не удалось получить голосовое сообщение."
            )

            return jsonify({
                "ok": True
            })

        text = transcribe_audio(
            audio
        )

        if not text:

            send_telegram_message(
                chat_id,
                "Не удалось распознать голос."
            )

            return jsonify({
                "ok": True
            })

        # Если транскрибация вернула нашу ошибку
        if text.startswith(
            "Ошибка распознавания голоса."
        ):

            send_telegram_message(
                chat_id,
                text
            )

            return jsonify({
                "ok": True
            })

    # ========================================================
    # IGNORE EMPTY MESSAGE
    # ========================================================

    if not text:

        return jsonify({
            "ok": True
        })

    # ========================================================
    # LOAD SHARED CONTEXT
    # ========================================================

    chat_data = get_chat_data(
        chat_id
    )

    # ========================================================
    # USER MESSAGE
    # ========================================================

    chat_data["messages"].append({
        "role": "user",
        "content": text
    })

    # ========================================================
    # AI
    # ========================================================

    answer = ask_ai(
        chat_data
    )

    # ========================================================
    # SAVE AI ANSWER
    # ========================================================

    chat_data["messages"].append({
        "role": "assistant",
        "content": answer
    })

    save_chat_data(
        chat_id,
        chat_data
    )

    # ========================================================
    # SEND
    # ========================================================

    send_telegram_message(
        chat_id,
        answer
    )

    return jsonify({
        "ok": True
    })


# ============================================================
# LOCAL
# ============================================================

if __name__ == "__main__":

    setup_bot_commands()

    app.run()
