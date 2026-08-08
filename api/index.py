import os
import json
import time
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

TELEGRAM_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
)

SEND_MESSAGE_URL = (
    f"{TELEGRAM_BASE}/sendMessage"
)

ANSWER_CALLBACK_URL = (
    f"{TELEGRAM_BASE}/answerCallbackQuery"
)

SET_COMMANDS_URL = (
    f"{TELEGRAM_BASE}/setMyCommands"
)

GET_FILE_URL = (
    f"{TELEGRAM_BASE}/getFile"
)


# =========================================================
# ANYMODEL
# =========================================================

AI_URL = (
    "https://anymodel.org/v1/chat/completions"
)

FAST_MODEL = (
    "cx/gpt-5.6-luna"
)

DEEP_MODEL = (
    "cx/gpt-5.6-terra"
)

VISION_MODEL = (
    "ag/gemini-3-flash-agent"
)


# =========================================================
# SETTINGS
# =========================================================

MAX_MESSAGES = 100

CONTEXT_TTL = 2592000

MAX_ALBUM_PHOTOS = 10

ALBUM_TTL = 30

ALBUM_WAIT_SECONDS = 2.0


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты — Света, постоянный AI-помощник пользователя в Telegram.

Это один непрерывный разговор.

Ты получаешь историю предыдущих сообщений этого чата.
Всегда используй историю для понимания контекста.

Если пользователь ссылается на предыдущие сообщения,
используй сохранённый контекст и не проси повторять уже
известную информацию.

Есть два режима:

Luna — быстрый режим.
Отвечай быстро, понятно и по существу.

Terra — глубокий режим.
Проводить более глубокий анализ, когда задача этого требует.

Luna и Terra — это один и тот же помощник.
Переключение режима НЕ создаёт новый разговор.

Если пользователь присылает фотографии:

- внимательно анализируй все присланные фотографии;
- используй изображения совместно;
- сравнивай разные ракурсы;
- если это растение, животное, предмет, дерево,
  деталь дома или другая вещь — старайся определить,
  что именно изображено;
- если точность определения недостаточна,
  честно сообщай об этом;
- не выдумывай детали, которых на изображениях не видно.

Не говори пользователю о Redis, API, системном промпте,
внутреннем коде или технической реализации.

Отвечай на русском языке, если пользователь не попросил
другой язык.
"""


# =========================================================
# ACCESS CONTROL
# =========================================================

def is_allowed(chat_id):

    if not ALLOWED_CHAT_ID:
        return False

    return str(chat_id) == str(ALLOWED_CHAT_ID)


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


def redis_set(
    key,
    value,
    ttl=CONTEXT_TTL
):

    if not REDIS_URL or not REDIS_TOKEN:
        return False

    try:

        response = requests.post(
            f"{REDIS_URL}/set/{key}?EX={ttl}",
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


def redis_delete(key):

    if not REDIS_URL or not REDIS_TOKEN:
        return False

    try:

        response = requests.post(
            f"{REDIS_URL}/del/{key}",
            headers=redis_headers(),
            timeout=10
        )

        return response.ok

    except Exception:
        return False


# =========================================================
# CHAT CONTEXT
# =========================================================

def get_chat_key(chat_id):

    return (
        f"telegram_chat:{chat_id}"
    )


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

        if data.get("mode") not in [
            "luna",
            "terra"
        ]:

            data["mode"] = "luna"

        if not isinstance(
            data.get("messages"),
            list
        ):

            data["messages"] = []

        return data

    except Exception:

        return {
            "mode": "luna",
            "messages": []
        }


def save_chat_data(
    chat_id,
    data
):

    data["messages"] = (
        data.get("messages", [])
        [-MAX_MESSAGES:]
    )

    redis_set(
        get_chat_key(chat_id),
        data,
        CONTEXT_TTL
    )


# =========================================================
# ALBUM STORAGE
# =========================================================

def get_album_key(
    chat_id,
    media_group_id
):

    return (
        f"telegram_album:"
        f"{chat_id}:"
        f"{media_group_id}"
    )


def get_album(
    chat_id,
    media_group_id
):

    raw = redis_get(
        get_album_key(
            chat_id,
            media_group_id
        )
    )

    if not raw:
        return {
            "photos": [],
            "caption": ""
        }

    try:

        data = json.loads(raw)

        if not isinstance(data, dict):
            raise ValueError

        if not isinstance(
            data.get("photos"),
            list
        ):

            data["photos"] = []

        return data

    except Exception:

        return {
            "photos": [],
            "caption": ""
        }


def save_album(
    chat_id,
    media_group_id,
    album
):

    album["photos"] = (
        album.get("photos", [])
        [:MAX_ALBUM_PHOTOS]
    )

    redis_set(
        get_album_key(
            chat_id,
            media_group_id
        ),
        album,
        ALBUM_TTL
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
                "inline_keyboard":
                inline_keyboard
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

        inline_keyboard=
        mode_menu_keyboard()
    )


def answer_callback(
    callback_id
):

    if not callback_id:
        return

    try:

        requests.post(

            ANSWER_CALLBACK_URL,

            json={
                "callback_query_id":
                callback_id
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
            "description":
            "Запустить Свету"
        },

        {
            "command": "menu",
            "description":
            "Открыть меню"
        },

        {
            "command": "luna",
            "description":
            "⚡ Быстрый режим"
        },

        {
            "command": "terra",
            "description":
            "🧠 Глубокий режим"
        },

        {
            "command": "reset",
            "description":
            "🗑 Очистить контекст"
        }

    ]

    try:

        requests.post(

            SET_COMMANDS_URL,

            json={
                "commands":
                commands
            },

            timeout=10
        )

    except Exception:

        pass


# =========================================================
# AI — TEXT
# =========================================================

def ask_text_ai(
    chat_data
):

    if chat_data.get("mode") == "terra":

        model = DEEP_MODEL

    else:

        model = FAST_MODEL

    current_date = (
        datetime.now()
        .strftime("%Y-%m-%d %H:%M")
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

        chat_data.get(
            "messages",
            []
        )

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

        choices = data.get(
            "choices",
            []
        )

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
            "Модель слишком долго "
            "отвечает. Попробуй ещё раз."
        )

    except Exception as e:

        return (
            "Ошибка соединения с AI:\n\n"
            + str(e)
        )


# =========================================================
# TELEGRAM FILE
# =========================================================

def get_telegram_file_path(
    file_id
):

    try:

        response = requests.get(

            GET_FILE_URL,

            params={
                "file_id":
                file_id
            },

            timeout=15
        )

        if not response.ok:
            return None

        data = response.json()

        return (

            data
            .get("result", {})
            .get("file_path")
        )

    except Exception:

        return None


def download_telegram_file(
    file_id
):

    file_path = (
        get_telegram_file_path(
            file_id
        )
    )

    if not file_path:
        return None

    try:

        file_url = (

            f"https://api.telegram.org/file/"

            f"bot{TELEGRAM_TOKEN}/"

            f"{file_path}"
        )

        response = requests.get(

            file_url,

            timeout=60
        )

        if not response.ok:
            return None

        return response.content

    except Exception:

        return None


# =========================================================
# TELEGRAM PHOTO
# =========================================================

def get_best_photo_file_id(
    photo_sizes
):

    if not photo_sizes:
        return None

    # Берём самое большое доступное фото.
    best = photo_sizes[-1]

    return best.get("file_id")


# =========================================================
# IMAGE → BASE64
# =========================================================

def image_to_data_url(
    image_bytes
):

    if not image_bytes:
        return None

    encoded = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    return (
        "data:image/jpeg;base64,"
        + encoded
    )


# =========================================================
# AI — VISION
# =========================================================

def ask_vision_ai(
    image_bytes_list,
    caption=""
):

    if not image_bytes_list:
        return (
            "Не удалось получить "
            "изображение."
        )

    content = []

    prompt = (

        "Проанализируй присланные "
        "фотографии.\n\n"

        "Используй все фотографии "
        "совместно.\n"

        "Если это растение, дерево, "
        "животное, предмет, деталь "
        "дома или другая вещь — "
        "постарайся определить, "
        "что именно изображено.\n"

        "Если несколько фотографий "
        "показывают один объект "
        "с разных сторон, учитывай "
        "их все.\n"

        "Не выдумывай то, чего "
        "нельзя определить по фото.\n"

        "Если уверенность низкая — "
        "скажи об этом и объясни, "
        "что именно нужно "
        "сфотографировать дополнительно."
    )

    if caption:

        prompt += (

            "\n\nКомментарий пользователя:\n"

            + caption
        )

    content.append({

        "type": "text",

        "text": prompt
    })

    for image_bytes in image_bytes_list:

        data_url = (
            image_to_data_url(
                image_bytes
            )
        )

        if not data_url:
            continue

        content.append({

            "type": "image_url",

            "image_url": {

                "url": data_url
            }
        })

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

                "content":
                SYSTEM_PROMPT
            },

            {

                "role": "user",

                "content":
                content
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

                f"Ошибка анализа изображения: "
                f"HTTP {response.status_code}\n\n"

                f"{response.text[:2000]}"
            )

        data = response.json()

        choices = data.get(
            "choices",
            []
        )

        if not choices:

            return (
                "Gemini не вернул ответ "
                "по фотографии."
            )

        answer = (

            choices[0]
            .get("message", {})
            .get("content")
        )

        if not answer:

            return (
                "Gemini вернул пустой "
                "ответ по фотографии."
            )

        return str(answer).strip()

    except requests.Timeout:

        return (
            "Анализ фотографий "
            "занял слишком много времени. "
            "Попробуй отправить меньше фото."
        )

    except Exception as e:

        return (
            "Ошибка анализа фотографий:\n\n"
            + str(e)
        )


# =========================================================
# PROCESS ALBUM
# =========================================================

def process_album(
    chat_id,
    media_group_id
):

    # Даём Telegram время прислать
    # остальные фотографии альбома.

    time.sleep(
        ALBUM_WAIT_SECONDS
    )

    album = get_album(

        chat_id,

        media_group_id
    )

    photos = album.get(
        "photos",
        []
    )

    caption = album.get(
        "caption",
        ""
    )

    if not photos:

        return

    # Защита от повторной обработки.

    lock_key = (

        f"telegram_album_lock:"
        f"{chat_id}:"
        f"{media_group_id}"
    )

    existing_lock = redis_get(
        lock_key
    )

    if existing_lock:

        return

    redis_set(

        lock_key,

        "processed",

        60
    )

    photos = photos[
        :MAX_ALBUM_PHOTOS
    ]

    image_bytes_list = []

    for file_id in photos:

        image = (
            download_telegram_file(
                file_id
            )
        )

        if image:

            image_bytes_list.append(
                image
            )

    if not image_bytes_list:

        send_message(

            chat_id,

            "Не удалось получить "
            "фотографии."
        )

        return

    answer = ask_vision_ai(

        image_bytes_list,

        caption
    )

    # Сохраняем текстовый след
    # анализа в общий контекст.

    chat_data = get_chat_data(
        chat_id
    )

    user_content = (

        f"[Пользователь прислал "
        f"{len(image_bytes_list)} "
        f"фото]"

    )

    if caption:

        user_content += (
            "\nКомментарий: "
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


# =========================================================
# HEALTH
# =========================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "Telegram AI bot is running.",
        200
    )


@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({

        "ok": True,

        "redis":
        bool(
            REDIS_URL and
            REDIS_TOKEN
        ),

        "telegram":
        bool(
            TELEGRAM_TOKEN
        ),

        "anymodel":
        bool(
            ANYMODEL_API_KEY
        ),

        "access_control":
        bool(
            ALLOWED_CHAT_ID
        ),

        "luna":
        FAST_MODEL,

        "terra":
        DEEP_MODEL,

        "vision":
        VISION_MODEL,

        "max_album_photos":
        MAX_ALBUM_PHOTOS

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
    # CALLBACK
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

        if not is_allowed(
            chat_id
        ):

            answer_callback(
                callback.get("id")
            )

            return jsonify({
                "ok": True
            })

        answer_callback(
            callback.get("id")
        )

        action = callback.get(
            "data"
        )

        chat_data = get_chat_data(
            chat_id
        )

        # -------------------------------------------------
        # LUNA
        # -------------------------------------------------

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

        # -------------------------------------------------
        # TERRA
        # -------------------------------------------------

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

        # -------------------------------------------------
        # RESET
        # -------------------------------------------------

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

    # =====================================================
    # ACCESS CONTROL
    # =====================================================

    if not is_allowed(
        chat_id
    ):

        # Ничего не сообщаем
        # постороннему пользователю.

        return jsonify({
            "ok": True
        })


    # =====================================================
    # MEDIA GROUP / ALBUM
    # =====================================================

    media_group_id = message.get(
        "media_group_id"
    )

    if media_group_id:

        photos = message.get(
            "photo"
        )

        if photos:

            file_id = (
                get_best_photo_file_id(
                    photos
                )
            )

            if file_id:

                album = get_album(

                    chat_id,

                    media_group_id
                )

                if len(
                    album["photos"]
                ) < MAX_ALBUM_PHOTOS:

                    if file_id not in (
                        album["photos"]
                    ):

                        album["photos"].append(
                            file_id
                        )

                caption = (
                    message
                    .get("caption")
                    or ""
                )

                if caption:

                    album["caption"] = (
                        caption
                    )

                save_album(

                    chat_id,

                    media_group_id,

                    album
                )

                # ВАЖНО:
                # первый webhook ждёт немного,
                # затем собирает весь альбом.

                process_album(

                    chat_id,

                    media_group_id
                )

        return jsonify({
            "ok": True
        })


    # =====================================================
    # TEXT
    # =====================================================

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

    if (
        text == "☰ Меню"
        or
        text == "/menu"
    ):

        show_menu(
            chat_id
        )

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
    # SINGLE PHOTO
    # =====================================================

    photo = message.get(
        "photo"
    )

    if photo:

        file_id = (
            get_best_photo_file_id(
                photo
            )
        )

        if not file_id:

            send_message(

                chat_id,

                "Не удалось получить фотографию."
            )

            return jsonify({
                "ok": True
            })

        image = (
            download_telegram_file(
                file_id
            )
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

            [image],

            caption
        )

        chat_data = get_chat_data(
            chat_id
        )

        user_content = (
            "[Пользователь прислал 1 фото]"
        )

        if caption:

            user_content += (
                "\nКомментарий: "
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

    answer = ask_text_ai(
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


# =========================================================
# LOCAL
# =========================================================

if __name__ == "__main__":

    set_bot_commands()

    app.run()
