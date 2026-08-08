import os
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# ENVIRONMENT
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

# Реальные переменные, которые создал Vercel + Upstash
REDIS_URL = os.environ.get("KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("KV_REST_API_TOKEN")

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SEND_MESSAGE_URL = f"{TELEGRAM_BASE}/sendMessage"
ANSWER_CALLBACK_URL = f"{TELEGRAM_BASE}/answerCallbackQuery"
SET_COMMANDS_URL = f"{TELEGRAM_BASE}/setMyCommands"
GET_FILE_URL = f"{TELEGRAM_BASE}/getFile"

# =========================================================
# ANYMODEL
# =========================================================

AI_URL = "https://anymodel.org/v1/chat/completions"
TRANSCRIBE_URL = "https://anymodel.org/v1/audio/transcriptions"

FAST_MODEL = "cx/gpt-5.6-luna"
DEEP_MODEL = "cx/gpt-5.6-terra"

# =========================================================
# SETTINGS
# =========================================================

MAX_MESSAGES = 100
CONTEXT_TTL = 2592000  # 30 дней

SYSTEM_PROMPT = """
Ты — постоянный AI-помощник пользователя в Telegram.

Это один непрерывный разговор.

Ты получаешь историю предыдущих сообщений этого чата.
Всегда используй эту историю для понимания контекста.

Если пользователь пишет:
"этот вопрос",
"а теперь",
"а что насчёт этого",
"как ты говорил выше",
"продолжим",
"а если",
или другую фразу, которая зависит от предыдущего разговора,
используй историю и не проси пользователя повторить уже известную
информацию.

Есть два режима работы:

Luna — быстрый режим.
Отвечай быстро, понятно и без лишнего усложнения.

Terra — глубокий режим.
Проводить более глубокий анализ, проверять логику и рассматривать
несколько вариантов, когда это действительно необходимо.

Luna и Terra являются двумя режимами ОДНОГО помощника.
Переключение между ними никогда не означает новый разговор.

Не говори пользователю о Redis, API, системных инструкциях,
внутреннем коде или технической реализации, если он специально
не спрашивает об этом.

Отвечай на русском языке, если пользователь не попросил другой язык.
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


def get_chat_key(chat_id):
    return f"telegram_chat:{chat_id}"


def get_chat_data(chat_id):

    raw = redis_get(
        get_chat_key(chat_id)
    )

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

    data["messages"] = (
        data.get("messages", [])
        [-MAX_MESSAGES:]
    )

    redis_set(
        get_chat_key(chat_id),
        data
    )


# =========================================================
# TELEGRAM UI
# =========================================================

def persistent_menu_keyboard():

    return {
        "keyboard": [
            [
                {
                    "text": "☰ Меню"
                }
            ]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def mode_menu_keyboard():

    return [
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


def send_message(
    chat_id,
    text,
    inline_keyboard=None,
    persistent_menu=False
):

    if not text:
        return

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if inline_keyboard:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": inline_keyboard
        }, ensure_ascii=False)

    elif persistent_menu:
        payload["reply_markup"] = json.dumps(
            persistent_menu_keyboard(),
            ensure_ascii=False
        )

    try:
        requests.post(
            SEND_MESSAGE_URL,
            json=payload,
            timeout=15
        )

    except Exception:
        pass


def show_menu(chat_id):

    send_message(
        chat_id,
        "Выбери режим:",
        inline_keyboard=mode_menu_keyboard()
    )


def answer_callback(callback_id):

    if not callback_id:
        return

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
# TELEGRAM COMMANDS
# =========================================================

def set_bot_commands():

    if not TELEGRAM_TOKEN:
        return

    commands = [
        {
            "command": "start",
            "description": "Запустить Свету"
        },
        {
            "command": "menu",
            "description": "Открыть меню"
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
        }
    ]

    try:
        requests.post(
            SET_COMMANDS_URL,
            json={
                "commands": commands
            },
            timeout=10
        )

    except Exception:
        pass


# =========================================================
# AI
# =========================================================

def ask_ai(chat_data):

    if chat_data.get("mode") == "terra":
        model = DEEP_MODEL
    else:
        model = FAST_MODEL

    current_date = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    system_message = (
        SYSTEM_PROMPT
        + "\n\n"
        + "Текущая дата и время: "
        + current_date
    )

    messages = [
        {
            "role": "system",
            "content": system_message
        }
    ]

    messages.extend(
        chat_data.get("messages", [])
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

        choices = data.get("choices", [])

        if not choices:
            return "AI не вернул ответ."

        content = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not content:
            return "AI вернул пустой ответ."

        return str(content).strip()

    except requests.Timeout:

        return (
            "Модель слишком долго отвечает. "
            "Попробуй ещё раз."
        )

    except Exception as e:

        return (
            "Ошибка соединения с AI:\n\n"
            + str(e)
        )


# =========================================================
# VOICE
# =========================================================

def download_telegram_file(file_id):

    try:

        response = requests.get(
            GET_FILE_URL,
            params={
                "file_id": file_id
            },
            timeout=15
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

        audio = requests.get(
            file_url,
            timeout=60
        )

        if not audio.ok:
            return None

        return audio.content

    except Exception:
        return None


def transcribe_voice(audio_bytes):

    models = [
        "gpt-4o-mini-transcribe",
        "gpt-4o-transcribe",
        "whisper-1"
    ]

    last_error = ""

    for model in models:

        try:

            response = requests.post(
                TRANSCRIBE_URL,
                headers={
                    "Authorization":
                    f"Bearer {ANYMODEL_API_KEY}"
                },
                files={
                    "file": (
                        "voice.ogg",
                        audio_bytes,
                        "audio/ogg"
                    )
                },
                data={
                    "model": model
                },
                timeout=120
            )

            if response.ok:

                data = response.json()

                text = data.get("text")

                if text:
                    return text.strip()

            last_error = (
                f"{model}: "
                f"HTTP {response.status_code}"
            )

        except Exception as e:

            last_error = str(e)

    return (
        "Не удалось распознать голосовое.\n\n"
        + last_error
    )


# =========================================================
# HEALTH
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
        ),
        "luna": FAST_MODEL,
        "terra": DEEP_MODEL
    })


# =========================================================
# WEBHOOK
# =========================================================

@app.route(
    "/api/index",
    methods=["GET", "POST"]
)
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    # =====================================================
    # INLINE BUTTON
    # =====================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

        answer_callback(
            callback.get("id")
        )

        message = (
            callback.get("message")
            or {}
        )

        chat_id = (
            message
            .get("chat", {})
            .get("id")
        )

        if not chat_id:
            return jsonify({
                "ok": True
            })

        action = callback.get("data")

        chat_data = get_chat_data(
            chat_id
        )

        # -----------------------------------------------
        # LUNA
        # -----------------------------------------------

        if action == "mode_luna":

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

        # -----------------------------------------------
        # TERRA
        # -----------------------------------------------

        if action == "mode_terra":

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

        # -----------------------------------------------
        # RESET
        # -----------------------------------------------

        if action == "reset_context":

            save_chat_data(
                chat_id,
                {
                    "mode": "luna",
                    "messages": []
                }
            )

            send_message(
                chat_id,
                "🗑 Контекст очищен."
            )

            show_menu(
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

        set_bot_commands()

        send_message(
            chat_id,
            "Готово. Выбери режим работы.",
            persistent_menu=True
        )

        show_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    # =====================================================
    # MENU
    # =====================================================

    if text == "☰ Меню" or text == "/menu":

        show_menu(
            chat_id
        )

        return jsonify({
            "ok": True
        })

    # =====================================================
    # LUNA COMMAND
    # =====================================================

    if text == "/luna":

        chat_data = get_chat_data(
            chat_id
        )

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

    # =====================================================
    # TERRA COMMAND
    # =====================================================

    if text == "/terra":

        chat_data = get_chat_data(
            chat_id
        )

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

    # =====================================================
    # RESET COMMAND
    # =====================================================

    if text == "/reset":

        save_chat_data(
            chat_id,
            {
                "mode": "luna",
                "messages": []
            }
        )

        send_message(
            chat_id,
            "🗑 Контекст очищен."
        )

        return jsonify({
            "ok": True
        })

    # =====================================================
    # VOICE
    # =====================================================

    voice = message.get("voice")

    if voice:

        file_id = voice.get(
            "file_id"
        )

        if not file_id:

            send_message(
                chat_id,
                "Не удалось получить голосовое."
            )

            return jsonify({
                "ok": True
            })

        audio = download_telegram_file(
            file_id
        )

        if not audio:

            send_message(
                chat_id,
                "Не удалось скачать голосовое."
            )

            return jsonify({
                "ok": True
            })

        text = transcribe_voice(
            audio
        )

        if text.startswith(
            "Не удалось распознать"
        ):

            send_message(
                chat_id,
                text
            )

            return jsonify({
                "ok": True
            })

    # =====================================================
    # EMPTY
    # =====================================================

    if not text:

        return jsonify({
            "ok": True
        })

    # =====================================================
    # LOAD CONTEXT
    # =====================================================

    chat_data = get_chat_data(
        chat_id
    )

    # =====================================================
    # USER MESSAGE
    # =====================================================

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
    # SAVE AI ANSWER
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
    # SEND ANSWER
    # =====================================================

    send_message(
        chat_id,
        answer
    )

    return jsonify({
        "ok": True
    })


# =========================================================
# LOCAL
# =========================================================

if __name__ == "__main__":

    set_bot_commands()

    app.run()
