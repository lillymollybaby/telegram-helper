from __future__ import annotations

from types import SimpleNamespace


class FakeJob:
    def __init__(self) -> None:
        self.removed = False

    def schedule_removal(self) -> None:
        self.removed = True


class FakeJobQueue:
    def __init__(self) -> None:
        self.once_calls = []
        self.repeating_calls = []
        self.named_jobs: dict[str, list[FakeJob]] = {}

    def run_once(self, callback, when=0, data=None, name=None):
        self.once_calls.append({"callback": callback, "when": when, "data": data, "name": name})
        job = FakeJob()
        if name:
            self.named_jobs.setdefault(name, []).append(job)
        return job

    def run_repeating(self, callback, interval=0, first=0, name=None):
        self.repeating_calls.append({"callback": callback, "interval": interval, "first": first, "name": name})
        job = FakeJob()
        if name:
            self.named_jobs.setdefault(name, []).append(job)
        return job

    def get_jobs_by_name(self, name: str):
        return self.named_jobs.get(name, [])


class FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def download_as_bytearray(self):
        return bytearray(self._data)


class FakeBot:
    def __init__(self) -> None:
        self.deleted_messages = []
        self.sent_messages = []
        self.files: dict[str, bytes] = {}

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted_messages.append((chat_id, message_id))

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        self.sent_messages.append((chat_id, text, reply_markup))
        return SimpleNamespace(chat_id=chat_id, message_id=len(self.sent_messages))

    async def get_file(self, file_id: str) -> FakeFile:
        return FakeFile(self.files.get(file_id, b""))


class FakeMessage:
    _counter = 1000

    def __init__(self, text: str = "", chat_id: int = 1, caption: str = "", photo=None) -> None:
        self.text = text
        self.caption = caption
        self.chat_id = chat_id
        self.photo = photo or []
        self.message_id = FakeMessage._counter
        FakeMessage._counter += 1
        self.replies = []

    async def reply_text(self, text: str, reply_markup=None):
        self.replies.append({"text": text, "reply_markup": reply_markup})
        sent_id = FakeMessage._counter
        FakeMessage._counter += 1
        return SimpleNamespace(chat_id=self.chat_id, message_id=sent_id)

    async def delete(self):
        return None


class FakeUpdate:
    def __init__(self, user_id: int = 1, chat_id: int = 1, text: str = "", caption: str = "", photo=None) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=chat_id)
        msg = FakeMessage(text=text, chat_id=chat_id, caption=caption, photo=photo)
        self.effective_message = msg
        self.message = msg


class FakeApplication:
    def __init__(self) -> None:
        self.job_queue = FakeJobQueue()
        self.user_data = {}


class FakeContext:
    def __init__(self, bot: FakeBot | None = None, app: FakeApplication | None = None, args=None) -> None:
        self.bot = bot or FakeBot()
        self.application = app or FakeApplication()
        self.job_queue = self.application.job_queue
        self.user_data = {}
        self.args = args or []

