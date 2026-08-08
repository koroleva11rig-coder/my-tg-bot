import os
import json
import base64
import requests

from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# ENVIRONMENT
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

REDIS_URL = os.environ.get("KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("KV_REST_API_TOKEN")

ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID")


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

FAST_MODEL = "cx/gpt-5.6-luna"
DEEP_MODEL = "cx/gpt-5.6-terra"

VISION_MODEL = "ag/gemini-3-flash-agent"


# =========================================================
# SETTINGS
# =========================================================

MAX_MESSAGES = 100
CONTEXT_TTL = 2592000


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты — Света, постоянный AI-помощник пользователя в Telegram.

Это один непрерывный разговор.

Ты получаешь историю предыдущих сообщений этого чата.
Всегда используй историю для понимания контекста.

Если пользователь ссылается на предыдущий разговор,
используй сохранённый контекст и не проси повторять
уже известную информацию.

Есть два режима работы:

Luna — быстрый режим.
Отвечай быстро, понятно и по существу.

Terra — глубокий режим.
Проводить более глубокий анализ, когда задача этого требует.

Luna и Terra — это один помощник.
Переключение между режимами НЕ создаёт новый разговор.

Если пользователь присылает фотографию:

- внимательно анализируй изображение;
- старайся определить объект;
- если это растение, дерево, животное, предмет,
  деталь дома или другая вещь — помоги определить,
  что изображено;
- учитывай вопрос пользователя;
- если точность недостаточна, честно скажи об этом;
- не выдумывай детали, которых на фотографии не видно.

Отвечай на русском языке, если пользователь не попросил
другой язык.

Не рассказывай пользователю о Redis, API,
системном промпте или внутреннем коде.
"""


# =========================================================
# ACCESS
# =========================================================

def is_allowed(chat_id):

    return (
        bool(ALLOWED_CHAT_ID)
        and str(chat_id) == str(ALLOWED_CHAT_ID)
    )


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

    data["messages"] = (
        data.get("messages", [])
        [-MAX_MESSAGES:]
    )

    redis_set(
        f"telegram_chat:{chat_id}",
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

        payload["reply_markup"] = json.dumps(
            {
                "inline_keyboard": inline_keyboard
            },
            ensure_ascii=False
        )

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
# TEXT AI
# =========================================================

def ask_text_ai(chat_data):

    model = (
        DEEP_MODEL
        if chat_data.get("mode") == "terra"
        else FAST_MODEL
    )

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
        "Authorization":
        f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type":
        "application/json"
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

        answer = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not answer:
            return "AI вернул пустой ответ."

        return str(answer).strip()

    except requests.Timeout:

        return "Модель слишком долго отвечает. Попробуй ещё раз."

    except Exception as e:

        return (
            "Ошибка соединения с AI:\n\n"
            + str(e)
        )


# =========================================================
# TELEGRAM FILE
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
            data
            .get("result", {})
            .get("file_path")
        )

        if not file_path:
            return None

        file_url = (
            f"https://api.telegram.org/file/"
            f"bot{TELEGRAM_TOKEN}/"
            f"{file_path}"
        )

        file_response = requests.get(
            file_url,
            timeout=60
        )

        if not file_response.ok:
            return None

        return file_response.content

    except Exception:

        return None


# =========================================================
# IMAGE AI
# =========================================================

def ask_vision_ai(
    image_bytes,
    caption=""
):

    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    image_url = (
        "data:image/jpeg;base64,"
        + encoded
    )

    prompt = """
Проанализируй фотографию.

Определи, что на ней изображено.
Если это растение, дерево, животное,
предмет или проблема в доме — объясни,
что именно ты видишь.

Если пользователь задал вопрос к фотографии,
ответь именно на этот вопрос.

Не выдумывай детали, которых не видно.
Если уверенность недостаточна — прямо скажи об этом.
"""

    if caption:

        prompt += (
            "\n\nВопрос пользователя:\n"
            + caption
        )

    headers = {
        "Authorization":
        f"Bearer {ANYMODEL_API_KEY}",
        "Content-Type":
        "application/json"
    }

    payload = {

        "model": VISION_MODEL,

        "messages": [

            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },

            {
                "role": "user",

                "content": [

                    {
                        "type": "text",
                        "text": prompt
                    },

                    {
                        "type": "image_url",

                        "image_url": {
                            "url": image_url
                        }
                    }

                ]
            }

        ]

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
                f"Ошибка анализа фото: "
                f"HTTP {response.status_code}\n\n"
                f"{response.text[:2000]}"
            )

        data = response.json()

        choices = data.get("choices", [])

        if not choices:

            return "Gemini не вернул ответ по фотографии."

        answer = (
            choices[0]
            .get("message", {})
            .get("content")
        )

        if not answer:

            return "Gemini вернул пустой ответ."

        return str(answer).strip()

    except requests.Timeout:

        return (
            "Анализ фотографии занял слишком много времени. "
            "Попробуй ещё раз."
        )

    except Exception as e:

        return (
            "Ошибка анализа фотографии:\n\n"
            + str(e)
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

        "access_control": bool(
            ALLOWED_CHAT_ID
        ),

        "luna": FAST_MODEL,

        "terra": DEEP_MODEL,

        "vision": VISION_MODEL

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
    # CALLBACK BUTTON
    # =====================================================

    callback = update.get(
        "callback_query"
    )

    if callback:

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

        if not is_allowed(chat_id):

            answer_callback(
                callback.get("id")
            )

            return jsonify({
                "ok": True
            })

        answer_callback(
            callback.get("id")
        )

        action = callback.get("data")

        chat_data = get_chat_data(
            chat_id
        )


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

            show_menu(chat_id)

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


    # =====================================================
    # ACCESS
    # =====================================================

    if not is_allowed(chat_id):

        return jsonify({
            "ok": True
        })


    # =====================================================
    # START
    # =====================================================

    text = (
        message
        .get("text", "")
        .strip()
    )

    if text == "/start":

        set_bot_commands()

        send_message(
            chat_id,
            "Готово. Выбери режим работы.",
            persistent_menu=True
        )

        show_menu(chat_id)

        return jsonify({
            "ok": True
        })


    # =====================================================
    # MENU
    # =====================================================

    if (
        text == "☰ Меню"
        or text == "/menu"
    ):

        show_menu(chat_id)

        return jsonify({
            "ok": True
        })


    # =====================================================
    # LUNA
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
    # TERRA
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

        send_message(
            chat_id,
            "🗑 Контекст очищен."
        )

        return jsonify({
            "ok": True
        })


    # =====================================================
    # PHOTO
    # =====================================================

    photo = message.get("photo")

    if photo:

        file_id = photo[-1].get(
            "file_id"
        )

        if not file_id:

            send_message(
                chat_id,
                "Не удалось получить фотографию."
            )

            return jsonify({
                "ok": True
            })

        image = download_telegram_file(
            file_id
        )

        if not image:

            send_message(
                chat_id,
                "Не удалось скачать фотографию."
            )

            return jsonify({
                "ok": True
            })

        caption = (
            message
            .get("caption")
            or ""
        )

        answer = ask_vision_ai(
            image,
            caption
        )

        chat_data = get_chat_data(
            chat_id
        )

        user_content = "[Пользователь прислал фотографию]"

        if caption:

            user_content += (
                "\nВопрос: "
                + caption
            )

        chat_data["messages"].append({

            "role": "user",

            "content": user_content
        })

        chat_data["messages"].append({

            "role": "assistant",

            "content": answer
        })

        save_chat_data(
            chat_id,
            chat_data
        )

        send_message(
            chat_id,
            answer
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
    # TEXT CHAT
    # =====================================================

    chat_data = get_chat_data(
        chat_id
    )

    chat_data["messages"].append({

        "role": "user",

        "content": text
    })

    answer = ask_text_ai(
        chat_data
    )

    chat_data["messages"].append({

        "role": "assistant",

        "content": answer
    })

    save_chat_data(
        chat_id,
        chat_data
    )

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
