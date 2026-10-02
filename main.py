import json
import os
import queue
import threading
import time
from urllib.request import Request, urlopen

from dotenv import load_dotenv


# ============================================================
# ENV
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

DATA_FILE = "anonymous_business_bot_data.json"


# ============================================================
# TELEGRAM API
# ============================================================

class TelegramAPI:

    def __init__(self, token):

        self.token = token

        self.base_url = (
            f"https://api.telegram.org/bot{token}"
        )

    # --------------------------------------------------------

    def call(
        self,
        method,
        data=None
    ):

        payload = json.dumps(
            data or {},
            ensure_ascii=False
        ).encode("utf-8")

        request = Request(
            f"{self.base_url}/{method}",
            data=payload,
            headers={
                "Content-Type": "application/json"
            },
            method="POST"
        )

        with urlopen(
            request,
            timeout=40
        ) as response:

            result = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        if not result.get("ok"):

            raise RuntimeError(
                result.get(
                    "description",
                    "Telegram API error"
                )
            )

        return result.get(
            "result"
        )


# ============================================================
# STORAGE
# ============================================================

class Storage:

    def __init__(
        self,
        filename
    ):

        self.filename = filename

        self.lock = threading.RLock()

        self.data = {
            "connections": {},
            "chats": {},
            "users": {},
            "active_chats": {}
        }

        self.load()

    # --------------------------------------------------------

    def load(self):

        if not os.path.exists(
            self.filename
        ):

            return

        try:

            with open(
                self.filename,
                "r",
                encoding="utf-8"
            ) as file:

                loaded = json.load(
                    file
                )

            if isinstance(
                loaded,
                dict
            ):

                self.data.update(
                    loaded
                )

        except Exception:

            pass

    # --------------------------------------------------------

    def save(self):

        with self.lock:

            temp_file = (
                self.filename + ".tmp"
            )

            with open(
                temp_file,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    self.data,
                    file,
                    ensure_ascii=False,
                    indent=2
                )

            os.replace(
                temp_file,
                self.filename
            )

    # ========================================================
    # USERS
    # ========================================================

    def save_user(
        self,
        user
    ):

        if not user:

            return

        user_id = str(
            user.get("id")
        )

        self.data[
            "users"
        ][user_id] = user

        self.save()

    # ========================================================
    # CONNECTIONS
    # ========================================================

    def save_connection(
        self,
        connection
    ):

        connection_id = (
            connection.get("id")
        )

        if not connection_id:

            return

        self.data[
            "connections"
        ][connection_id] = connection

        self.save()

    # --------------------------------------------------------

    def get_connection(
        self,
        connection_id
    ):

        return self.data[
            "connections"
        ].get(
            connection_id
        )

    # ========================================================
    # CHATS
    # ========================================================

    def save_chat(
        self,
        connection_id,
        chat
    ):

        if not chat:

            return

        chat_id = str(
            chat.get("id")
        )

        if chat_id == "None":

            return

        title = (
            chat.get("title")
            or " ".join(
                value
                for value in [
                    chat.get(
                        "first_name"
                    ) or "",
                    chat.get(
                        "last_name"
                    ) or ""
                ]
                if value
            )
            or chat.get(
                "username"
            )
            or f"Chat {chat_id}"
        )

        self.data[
            "chats"
        ][chat_id] = {

            "id": chat.get(
                "id"
            ),

            "type": chat.get(
                "type"
            ),

            "title": title,

            "username": chat.get(
                "username"
            ),

            "connection_id": connection_id,

            "updated_at": int(
                time.time()
            )
        }

        self.save()

    # --------------------------------------------------------

    def get_chats(
        self
    ):

        return list(
            self.data[
                "chats"
            ].values()
        )

    # --------------------------------------------------------

    def get_chat(
        self,
        chat_id
    ):

        return self.data[
            "chats"
        ].get(
            str(chat_id)
        )

    # ========================================================
    # ACTIVE CHAT
    # ========================================================

    def set_active_chat(
        self,
        telegram_user_id,
        chat_id
    ):

        self.data[
            "active_chats"
        ][
            str(telegram_user_id)
        ] = str(chat_id)

        self.save()

    # --------------------------------------------------------

    def get_active_chat(
        self,
        telegram_user_id
    ):

        return self.data[
            "active_chats"
        ].get(
            str(telegram_user_id)
        )

    # --------------------------------------------------------

    def clear_active_chat(
        self,
        telegram_user_id
    ):

        self.data[
            "active_chats"
        ].pop(
            str(telegram_user_id),
            None
        )

        self.save()


# ============================================================
# BOT WORKER
# ============================================================

class BotWorker(
    threading.Thread
):

    def __init__(
        self,
        token,
        storage,
        events
    ):

        super().__init__(
            daemon=True
        )

        self.api = TelegramAPI(
            token
        )

        self.storage = storage

        self.events = events

        self.offset = None

        self.running = True

        self.bot_username = ""

        self.bot_id = None

    # --------------------------------------------------------

    def emit(
        self,
        event,
        data=None
    ):

        self.events.put(
            (
                event,
                data
            )
        )

    # ========================================================
    # RUN
    # ========================================================

    def run(self):

        try:

            me = self.api.call(
                "getMe"
            )

            self.bot_username = (
                me.get(
                    "username",
                    ""
                )
            )

            self.bot_id = me.get(
                "id"
            )

            self.emit(
                "bot_ready",
                me
            )

            while self.running:

                try:

                    updates = (
                        self.api.call(
                            "getUpdates",
                            {
                                "timeout": 25,

                                "offset": (
                                    self.offset
                                    if self.offset is not None
                                    else None
                                ),

                                "allowed_updates": [
                                    "message",
                                    "business_connection",
                                    "business_message",
                                    "edited_business_message",
                                    "deleted_business_messages",
                                    "callback_query"
                                ]
                            }
                        )
                    )

                    for update in updates:

                        self.offset = (
                            update[
                                "update_id"
                            ] + 1
                        )

                        self.handle_update(
                            update
                        )

                except Exception as exc:

                    self.emit(
                        "error",
                        str(exc)
                    )

                    time.sleep(
                        3
                    )

        except Exception as exc:

            self.emit(
                "fatal",
                str(exc)
            )

    # ========================================================
    # UPDATE ROUTER
    # ========================================================

    def handle_update(
        self,
        update
    ):

        # ----------------------------------------------------
        # BUSINESS CONNECTION
        # ----------------------------------------------------

        if (
            "business_connection"
            in update
        ):

            connection = update[
                "business_connection"
            ]

            self.storage.save_connection(
                connection
            )

            self.emit(
                "business_connection",
                connection
            )

            return

        # ----------------------------------------------------
        # BUSINESS MESSAGE
        # ----------------------------------------------------

        if (
            "business_message"
            in update
        ):

            message = update[
                "business_message"
            ]

            self.process_business_message(
                message
            )

            return

        # ----------------------------------------------------
        # EDITED BUSINESS MESSAGE
        # ----------------------------------------------------

        if (
            "edited_business_message"
            in update
        ):

            message = update[
                "edited_business_message"
            ]

            self.process_business_message(
                message,
                edited=True
            )

            return

        # ----------------------------------------------------
        # CALLBACK
        # ----------------------------------------------------

        if (
            "callback_query"
            in update
        ):

            self.handle_callback(
                update[
                    "callback_query"
                ]
            )

            return

        # ----------------------------------------------------
        # NORMAL MESSAGE
        # ----------------------------------------------------

        if (
            "message"
            in update
        ):

            message = update[
                "message"
            ]

            self.handle_normal_message(
                message
            )

    # ========================================================
    # NORMAL MESSAGE
    # ========================================================

    def handle_normal_message(
        self,
        message
    ):

        user = (
            message.get(
                "from"
            )
            or {}
        )

        self.storage.save_user(
            user
        )

        user_id = user.get(
            "id"
        )

        chat = (
            message.get(
                "chat"
            )
            or {}
        )

        chat_id = chat.get(
            "id"
        )

        text = (
            message.get(
                "text"
            )
            or ""
        ).strip()

        # ----------------------------------------------------
        # COMMANDS
        # ----------------------------------------------------

        if text == "/start":

            self.send_start(
                message
            )

            return

        if text == "/chats":

            self.send_chats(
                message
            )

            return

        if text == "/help":

            self.send_help(
                message
            )

            return

        if text == "/stopchat":

            if user_id is not None:

                self.storage.clear_active_chat(
                    user_id
                )

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "🛑 Поточний чат відключено.\n\n"
                        "Напиши /chats, щоб вибрати інший."
                    )
                }
            )

            return

        # ----------------------------------------------------
        # EMPTY
        # ----------------------------------------------------

        if not text:

            return

        # ----------------------------------------------------
        # SEND TO ACTIVE BUSINESS CHAT
        # ----------------------------------------------------

        if user_id is None:

            return

        active_chat_id = (
            self.storage.get_active_chat(
                user_id
            )
        )

        if not active_chat_id:

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "📭 Чат ще не вибраний.\n\n"
                        "Напиши /chats і вибери Business-чат."
                    )
                }
            )

            return

        selected_chat = (
            self.storage.get_chat(
                active_chat_id
            )
        )

        if not selected_chat:

            self.storage.clear_active_chat(
                user_id
            )

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "❌ Обраний чат більше не доступний.\n\n"
                        "Напиши /chats і вибери чат заново."
                    )
                }
            )

            return

        connection_id = (
            selected_chat.get(
                "connection_id"
            )
        )

        target_chat_id = (
            selected_chat.get(
                "id"
            )
        )

        if not connection_id:

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "❌ У цього чату немає Business Connection."
                    )
                }
            )

            return

        try:

            self.send_to_business_chat(
                connection_id,
                target_chat_id,
                text
            )

            title = (
                selected_chat.get(
                    "title"
                )
                or "чат"
            )

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        f"✅ Надіслано в: {title}"
                    )
                }
            )

        except Exception as exc:

            self.api.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": (
                        "❌ Не вдалося відправити повідомлення.\n\n"
                        f"Telegram: {exc}\n\n"
                        "Перевір права Business Connection, "
                        "зокрема право can_reply."
                    )
                }
            )

            self.emit(
                "error",
                str(exc)
            )

    # ========================================================
    # START
    # ========================================================

    def send_start(
        self,
        message
    ):

        chat = (
            message.get(
                "chat"
            )
            or {}
        )

        user = (
            message.get(
                "from"
            )
            or {}
        )

        chat_id = chat.get(
            "id"
        )

        first_name = (
            user.get(
                "first_name"
            )
            or "користувач"
        )

        text = (
            f"Привіт, {first_name}! 👋\n\n"
            f"🤖 Бот запущений.\n\n"
            f"Команди:\n\n"
            f"/chats — вибрати Business-чат.\n"
            f"/stopchat — завершити поточну переписку.\n"
            f"/help — допомога.\n\n"
            f"Після вибору чату просто пиши повідомлення "
            f"сюди — вони будуть відправлятися в обраний "
            f"Business-чат."
        )

        self.api.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text
            }
        )

    # ========================================================
    # HELP
    # ========================================================

    def send_help(
        self,
        message
    ):

        chat_id = (
            message[
                "chat"
            ][
                "id"
            ]
        )

        text = (
            "🤖 Допомога\n\n"
            "/start — запуск.\n"
            "/chats — вибір Business-чату.\n"
            "/stopchat — завершити поточну переписку.\n"
            "/help — ця допомога.\n\n"
            "Після вибору чату просто пиши мені.\n"
            "Твої повідомлення будуть відправлятися "
            "в обраний Business-чат.\n\n"
            "Відповіді з Business-чату я автоматично "
            "надсилатиму тобі сюди."
        )

        self.api.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text
            }
        )

    # ========================================================
    # BUSINESS MESSAGE
    # ========================================================

    def process_business_message(
        self,
        message,
        edited=False
    ):

        connection_id = (
            message.get(
                "business_connection_id"
            )
        )

        chat = (
            message.get(
                "chat"
            )
        )

        if not connection_id:

            return

        if not chat:

            return

        self.storage.save_chat(
            connection_id,
            chat
        )

        self.emit(
            "business_message",
            message
        )

        # ----------------------------------------------------
        # FIND BUSINESS OWNER
        # ----------------------------------------------------

        connection = (
            self.storage.get_connection(
                connection_id
            )
        )

        if not connection:

            return

        business_owner_chat_id = (
            connection.get(
                "user_chat_id"
            )
        )

        if not business_owner_chat_id:

            return

        # ----------------------------------------------------
        # MESSAGE TEXT
        # ----------------------------------------------------

        text = (
            message.get(
                "text"
            )
            or message.get(
                "caption"
            )
            or ""
        ).strip()

        if not text:

            text = (
                "📎 Отримано повідомлення "
                "без тексту."
            )

        # ----------------------------------------------------
        # CHAT NAME
        # ----------------------------------------------------

        title = (
            chat.get(
                "title"
            )
            or " ".join(
                value
                for value in [
                    chat.get(
                        "first_name"
                    ) or "",
                    chat.get(
                        "last_name"
                    ) or ""
                ]
                if value
            )
            or chat.get(
                "username"
            )
            or "Business-чат"
        )

        # ----------------------------------------------------
        # SENDER
        # ----------------------------------------------------

        sender = (
            message.get(
                "from"
            )
            or {}
        )

        sender_name = (
            sender.get(
                "first_name"
            )
            or "Користувач"
        )

        if sender.get(
            "last_name"
        ):

            sender_name += (
                " "
                + sender.get(
                    "last_name"
                )
            )

        if edited:

            prefix = "✏️ Відредаговано"

        else:

            prefix = "📩 Нове повідомлення"

        outgoing_text = (
            f"{prefix}\n\n"
            f"💬 Чат: {title}\n"
            f"👤 {sender_name}\n\n"
            f"{text}"
        )

        # ----------------------------------------------------
        # SEND TO BOT OWNER
        # ----------------------------------------------------

        try:

            self.api.call(
                "sendMessage",
                {
                    "chat_id": business_owner_chat_id,
                    "text": outgoing_text
                }
            )

        except Exception as exc:

            self.emit(
                "error",
                (
                    "Не вдалося переслати "
                    f"Business-повідомлення: {exc}"
                )
            )

    # ========================================================
    # CHATS
    # ========================================================

    def send_chats(
        self,
        message
    ):

        telegram_chat_id = (
            message[
                "chat"
            ][
                "id"
            ]
        )

        chats = (
            self.storage.get_chats()
        )

        valid_chats = []

        # ----------------------------------------------------
        # ONLY ENABLED BUSINESS CONNECTIONS
        # ----------------------------------------------------

        for chat in chats:

            connection_id = (
                chat.get(
                    "connection_id"
                )
            )

            if not connection_id:

                continue

            connection = (
                self.storage.get_connection(
                    connection_id
                )
            )

            if not connection:

                continue

            if not connection.get(
                "is_enabled",
                False
            ):

                continue

            valid_chats.append(
                chat
            )

        # ----------------------------------------------------
        # SORT
        # ----------------------------------------------------

        valid_chats.sort(
            key=lambda item:
                item.get(
                    "updated_at",
                    0
                ),
            reverse=True
        )

        # ----------------------------------------------------
        # NOTHING
        # ----------------------------------------------------

        if not valid_chats:

            self.api.call(
                "sendMessage",
                {
                    "chat_id": telegram_chat_id,
                    "text": (
                        "📭 Доступних Business-чатів поки немає.\n\n"
                        "Переконайся, що бот підключений "
                        "до Telegram Business."
                    )
                }
            )

            return

        # ----------------------------------------------------
        # BUTTONS
        # ----------------------------------------------------

        buttons = []

        for chat in valid_chats:

            title = (
                chat.get(
                    "title"
                )
                or "Без назви"
            )

            chat_id = str(
                chat.get(
                    "id"
                )
            )

            buttons.append(
                [
                    {
                        "text": (
                            f"💬 {title}"
                        ),
                        "callback_data": (
                            f"chat:{chat_id}"
                        )
                    }
                ]
            )

        buttons.append(
            [
                {
                    "text": "🔄 Оновити список",
                    "callback_data": "refresh_chats"
                }
            ]
        )

        self.api.call(
            "sendMessage",
            {
                "chat_id": telegram_chat_id,
                "text": (
                    "💬 Доступні Business-чати\n\n"
                    "Вибери чат.\n\n"
                    "Після вибору можеш одразу "
                    "писати повідомлення."
                ),
                "reply_markup": {
                    "inline_keyboard": buttons
                }
            }
        )

    # ========================================================
    # CALLBACK
    # ========================================================

    def handle_callback(
        self,
        callback
    ):

        callback_id = callback.get(
            "id"
        )

        data = (
            callback.get(
                "data"
            )
            or ""
        )

        callback_message = (
            callback.get(
                "message"
            )
            or {}
        )

        telegram_chat_id = (
            callback_message.get(
                "chat",
                {}
            ).get(
                "id"
            )
        )

        # ----------------------------------------------------
        # ANSWER
        # ----------------------------------------------------

        try:

            self.api.call(
                "answerCallbackQuery",
                {
                    "callback_query_id":
                        callback_id
                }
            )

        except Exception:

            pass

        # ----------------------------------------------------
        # REFRESH
        # ----------------------------------------------------

        if data == "refresh_chats":

            if telegram_chat_id:

                self.send_chats(
                    callback_message
                )

            return

        # ----------------------------------------------------
        # SELECT CHAT
        # ----------------------------------------------------

        if data.startswith(
            "chat:"
        ):

            selected_id = (
                data.split(
                    ":",
                    1
                )[1]
            )

            chat = (
                self.storage.get_chat(
                    selected_id
                )
            )

            if not chat:

                if telegram_chat_id:

                    self.api.call(
                        "sendMessage",
                        {
                            "chat_id":
                                telegram_chat_id,

                            "text": (
                                "❌ Чат не знайдено.\n\n"
                                "Напиши /chats і вибери його заново."
                            )
                        }
                    )

                return

            title = (
                chat.get(
                    "title"
                )
                or "Без назви"
            )

            connection_id = (
                chat.get(
                    "connection_id"
                )
            )

            # ------------------------------------------------
            # SAVE ACTIVE CHAT
            # ------------------------------------------------

            if telegram_chat_id:

                self.storage.set_active_chat(
                    telegram_chat_id,
                    selected_id
                )

            # ------------------------------------------------
            # CONFIRM
            # ------------------------------------------------

            self.api.call(
                "sendMessage",
                {
                    "chat_id":
                        telegram_chat_id,

                    "text": (
                        f"✅ Чат вибрано!\n\n"
                        f"💬 {title}\n\n"
                        f"🟢 Тепер ти можеш одразу "
                        f"писати мені повідомлення.\n\n"
                        f"Я відправлятиму їх у цей "
                        f"Business-чат.\n\n"
                        f"📩 Відповіді з цього чату "
                        f"я автоматично надсилатиму тобі.\n\n"
                        f"Щоб вибрати інший чат:\n"
                        f"/chats\n\n"
                        f"Щоб завершити переписку:\n"
                        f"/stopchat"
                    )
                }
            )

            return

    # ========================================================
    # SEND TO BUSINESS CHAT
    # ========================================================

    def send_to_business_chat(
        self,
        connection_id,
        chat_id,
        text
    ):

        return self.api.call(
            "sendMessage",
            {
                "business_connection_id":
                    connection_id,

                "chat_id":
                    chat_id,

                "text":
                    text
            }
        )

    # ========================================================

    def stop(
        self
    ):

        self.running = False


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        print(
            "ПОМИЛКА: TELEGRAM_BOT_TOKEN "
            "не знайдено в .env"
        )

        print()

        print(
            "Створи файл .env поруч із main.py:"
        )

        print()

        print(
            "TELEGRAM_BOT_TOKEN=ТВІЙ_ТОКЕН"
        )

        return

    storage = Storage(
        DATA_FILE
    )

    events = queue.Queue()

    worker = BotWorker(
        BOT_TOKEN,
        storage,
        events
    )

    worker.start()

    print(
        "========================================"
    )

    print(
        "       АНОНІМНИЙ БОТ-НЕВИДИМКА"
    )

    print(
        "========================================"
    )

    print()

    print(
        "Бот запущено."
    )

    print(
        "Відкрий Telegram і напиши боту:"
    )

    print(
        "/start"
    )

    print()

    try:

        while True:

            try:

                event, data = (
                    events.get(
                        timeout=1
                    )
                )

                # --------------------------------------------
                # BOT READY
                # --------------------------------------------

                if event == "bot_ready":

                    username = (
                        data.get(
                            "username"
                        )
                        or ""
                    )

                    print(
                        f"Бот: @{username}"
                    )

                # --------------------------------------------
                # BUSINESS CONNECTION
                # --------------------------------------------

                elif event == "business_connection":

                    connection = data

                    print(
                        "Business connection:"
                    )

                    print(
                        json.dumps(
                            connection,
                            ensure_ascii=False,
                            indent=2
                        )
                    )

                # --------------------------------------------
                # BUSINESS MESSAGE
                # --------------------------------------------

                elif event == "business_message":

                    message = data

                    chat = (
                        message.get(
                            "chat"
                        )
                        or {}
                    )

                    title = (
                        chat.get(
                            "title"
                        )
                        or chat.get(
                            "first_name"
                        )
                        or "Chat"
                    )

                    text = (
                        message.get(
                            "text"
                        )
                        or message.get(
                            "caption"
                        )
                        or "[не текст]"
                    )

                    print(
                        f"[BUSINESS] {title}: {text}"
                    )

                # --------------------------------------------
                # ERROR
                # --------------------------------------------

                elif event == "error":

                    print(
                        f"[ERROR] {data}"
                    )

                # --------------------------------------------
                # FATAL
                # --------------------------------------------

                elif event == "fatal":

                    print(
                        f"[FATAL] {data}"
                    )

            except queue.Empty:

                pass

    except KeyboardInterrupt:

        print()

        print(
            "Зупинка бота..."
        )

        worker.stop()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()