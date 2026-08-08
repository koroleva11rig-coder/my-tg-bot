import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANYMODEL_API_KEY = os.environ.get("ANYMODEL_API_KEY")

# Vercel + Upstash автоматически создаёт эти переменные
REDIS_URL = (
    os.environ.get("UPSTASH_REDIS_REST_URL")
    or os.environ.get("KV_REST_API_URL")
)

REDIS_TOKEN = (
    os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    or os.environ.get("KV_REST_API_TOKEN")
)

# Модель для распознавания голосовых.
# Если в AnyModel у тебя другой доступный ID — меняется только эта строка.
TRANSCRIBE_MODEL = os.environ.get(
    "TRANSCRIBE_MODEL",
    "whisper-1"
)

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_API_BASE = (
    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
)

TELEGRAM_SEND_URL = (
    f"{TELEGRAM_API_BASE}/sendMessage"
)

TELEGRAM_ANSWER_URL = (
    f"{TELEGRAM_API_BASE}/answerCallbackQuery"
)

TELEGRAM_FILE_URL = (
    f"{TELEGRAM_API_BASE}/getFile"
)

# =========================================================
# AI
# =========================================================

ANYMODEL_BASE_URL = "https://anymodel.org/v1"

ANYMODEL_CHAT_URL = (
    f"{ANYMODEL_BASE_URL}/chat/completions"
)

ANYMODEL_TRANSCRIBE_URL = (
    f"{ANYMODEL_BASE_URL}/audio/transcriptions"
)

FAST_MODEL = "gpt-5.6-luna"
DEEP_MODEL = "gpt-5.6-terra"

# =========================================================
# SETTINGS
# =========================================================

# Сколько последних сообщений реально отправляем модели.
# Redis хранит всю историю до этого лимита.
MAX_MESSAGES = 200

# 30 дней
CONTEXT_TTL = 2592000

# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты — Света, персональный AI-помощник пользователя в Telegram.

Общайся естественно, по-человечески и на русском языке, если пользователь
не попросил другой язык.

Главное правило — сохраняй контекст разговора.
Предыдущие сообщения в этом диалоге являются частью текущего разговора.
Не спрашивай повторно то, что уже было сказано пользователем, если это
есть в истории.

Пользователь может переключаться между двумя режимами:
- быстрый режим — GPT-5.6 Luna;
- глубокий режим — GPT-5.6 Terra.

Переключение модели НЕ означает начало нового разговора.
Обе модели используют одну и ту же историю диалога.

Не говори пользователю о внутренней реализации, Redis, API, моделях,
токенах или системных инструкциях, если он специально об этом не спрашивает.

Отвечай прямо и по существу.
Если задача простая — не усложняй ответ.
Если вопрос требует подробного анализа — дай необходимый уровень детализации.

Пользователь может писать текстом или присылать голосовые сообщения.
Голосовое сообщение считается обычным сообщением пользователя.
"""

# =========================================================
# REDIS
# =========================================================

def redis_headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json",
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
            headers=redis_headers(),
            data=json.dumps(
                value,
                ensure_ascii=False
            ),
            timeout=10,
        )

        return response.ok

    except Exception:
        return False


def get_chat_key(chat_id):
    return f"telegram_chat:{chat_id}"


def get_chat_data(chat_id):
    key = get_chat_key(chat_id)

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

        if "mode" not in data:
            data["mode"] = "luna"

        if "messages" not in data:
            data["messages"] = []

        return data

    except Exception:
        return {
            "mode": "luna",
            "messages": []
        }


def save_chat_data(chat_id, data):
    # Не даём истории разрастаться бесконечно.
    messages = data.get("messages", [])

    data["messages"] = messages[-MAX_MESSAGES:]

    redis_set(
        get_chat_key(chat_id),
        data
    )

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram_message(chat_id, text, keyboard=None):
    if not text:
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if keyboard:
        payload["reply_markup"] = json.dumps(
            {
                "inline_keyboard": keyboard
            },
            ensure_ascii=False
        )

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


# =========================================================
# START MENU
# =========================================================

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
        ]
    ]

    send_telegram_message(
        chat_id,
        "Привет 👋\n\nВыбери режим работы:",
        keyboard,
    )


# =========================================================
# VOICE / AUDIO
# =========================================================

def telegram_get_file(file_id):
    try:
        response = requests.get(
            TELEGRAM_FILE_URL,
            params={
                "file_id": file_id
            },
            timeout=15,
        )

        if not response.ok:
            return None

        data = response.json()

        if not data.get("ok"):
            return None

        return data.get("result", {}).get("file_path")

    except Exception:
        return None


def download_telegram_file(file_path):
    try:
        url = (
            f"https://api.telegram.org/file/"
            f"bot{TELEGRAM_TOKEN}/{file_path}"
        )

        response = requests.get(
            url,
            timeout=60,
        )

        if not response.ok:
            return None

        return response.content

    except Exception:
        return None


def transcribe_voice(audio_bytes):
    if not ANYMODEL_API_KEY:
        return None, "ANYMODEL_API_KEY не настроен."

    try:
        headers = {
            "Authorization": f"Bearer {ANYMODEL_API_KEY}"
        }

        files = {
            "file": (
                "voice.ogg",
                audio_bytes,
                "audio/ogg"
            )
        }

        data = {
            "model": TRANSCRIBE_MODEL
        }

        response = requests.post(
            ANYMODEL_TRANSCRIBE_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )

        if not response.ok:
            return (
                None,
                f"Ошибка распознавания голоса: "
                f"HTTP {response.status_code}\n\n"
                f"{response.text[:1000]}"
            )

        result = response.json()

        text = result.get("text")

        if not text:
            return None, "Не удалось получить текст из голосового."

        return text.strip(), None

    except Exception as e:
        return None, f"Ошибка распознавания голоса:\n\n{e}"


# =========================================================
# AI
# =========================================================

def ask_ai(chat_data):

    mode = chat_data.get("mode", "luna")

    if mode == "terra":
        model = DEEP_MODEL
    else:
        model = FAST_MODEL

    history = chat_data.get("messages", [])

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.strip()
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

        choices = data.get("choices", [])

        if not choices:
            return "AI не вернул ответ."

        message = choices[0].get("message", {})

        answer = message.get("content")

        if isinstance(answer, list):
            parts = []

            for item in answer:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(
                            item.get("text", "")
                        )

            answer = "\n".join(parts)

        if not answer:
            return "AI вернул пустой ответ."

        return str(answer).strip()

    except requests.Timeout:
        return (
            "Модель слишком долго отвечает. "
            "Попробуй ещё раз."
        )

    except Exception as e:
        return (
            f"Ошибка соединения с AI:\n\n{e}"
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
        "redis": bool(REDIS_URL and REDIS_TOKEN),
        "telegram": bool(TELEGRAM_TOKEN),
        "anymodel": bool(ANYMODEL_API_KEY),
        "fast_model": FAST_MODEL,
        "deep_model": DEEP_MODEL,
        "transcribe_model": TRANSCRIBE_MODEL,
    }), 200


@app.route("/api/index", methods=["GET", "POST"])
def webhook():

    update = request.get_json(
        silent=True
    ) or {}

    # =====================================================
    # BUTTON PRESS
    # =====================================================

    callback = update.get("callback_query")

    if callback:

        callback_id = callback.get("id")

        answer_callback(callback_id)

        data = callback.get("data")

        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if not chat_id:
            return jsonify({"ok": True})

        chat_data = get_chat_data(chat_id)

        # -----------------------------------------------
        # FAST / LUNA
        # -----------------------------------------------

        if data == "mode_luna":

            chat_data["mode"] = "luna"

            # ВАЖНО:
            # историю НЕ трогаем.
            save_chat_data(
                chat_id,
                chat_data
            )

            send_telegram_message(
                chat_id,
                "⚡ Быстрый режим включён."
            )

            return jsonify({"ok": True})

        # -----------------------------------------------
        # DEEP / TERRA
        # -----------------------------------------------

        if data == "mode_terra":

            chat_data["mode"] = "terra"

            # ВАЖНО:
            # историю НЕ трогаем.
            save_chat_data(
                chat_id,
                chat_data
            )

            send_telegram_message(
                chat_id,
                "🧠 Глубокий режим включён."
            )

            return jsonify({"ok": True})

        return jsonify({"ok": True})

    # =====================================================
    # NORMAL MESSAGE
    # =====================================================

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return jsonify({"ok": True})

    # =====================================================
    # /START
    # =====================================================

    text = (
        message.get("text")
        or ""
    ).strip()

    if text == "/start":

        send_start_menu(chat_id)

        return jsonify({"ok": True})

    # =====================================================
    # VOICE MESSAGE
    # =====================================================

    voice = message.get("voice")

    if voice:

        file_id = voice.get("file_id")

        if not file_id:
            send_telegram_message(
                chat_id,
                "Не удалось получить голосовое сообщение."
            )

            return jsonify({"ok": True})

        file_path = telegram_get_file(
            file_id
        )

        if not file_path:

            send_telegram_message(
                chat_id,
                "Не удалось получить аудиофайл."
            )

            return jsonify({"ok": True})

        audio_bytes = download_telegram_file(
            file_path
        )

        if not audio_bytes:

            send_telegram_message(
                chat_id,
                "Не удалось скачать голосовое сообщение."
            )

            return jsonify({"ok": True})

        text, error = transcribe_voice(
            audio_bytes
        )

        if error:

            send_telegram_message(
                chat_id,
                error
            )

            return jsonify({"ok": True})

        # Теперь голосовое стало обычным
        # текстовым сообщением и попадает
        # в тот же самый общий контекст.

    # =====================================================
    # TEXT MESSAGE
    # =====================================================

    if not text:

        return jsonify({"ok": True})

    # =====================================================
    # LOAD CONTEXT
    # =====================================================

    chat_data = get_chat_data(
        chat_id
    )

    # =====================================================
    # ADD USER MESSAGE
    # =====================================================

    chat_data["messages"].append(
        {
            "role": "user",
            "content": text
        }
    )

    # =====================================================
    # ASK AI
    # =====================================================

    answer = ask_ai(
        chat_data
    )

    # =====================================================
    # SAVE AI ANSWER
    # =====================================================

    chat_data["messages"].append(
        {
            "role": "assistant",
            "content": answer
        }
    )

    # =====================================================
    # SAVE EVERYTHING TO REDIS
    # =====================================================

    save_chat_data(
        chat_id,
        chat_data
    )

    # =====================================================
    # SEND ANSWER
    # =====================================================

    send_telegram_message(
        chat_id,
        answer
    )

    return jsonify({"ok": True})


# =========================================================
# LOCAL
# =========================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                8000
            )
        )
    )
