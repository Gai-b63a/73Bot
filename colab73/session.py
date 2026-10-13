"""One uploaded reference per Colab session, independent of widget instances."""
from pathlib import Path
import shutil
import tempfile

from .controller import Controller


class SessionVoice:
    def __init__(self, controller: Controller):
        self.controller = controller
        self.source = None
        self.filename = None
        self.signature = None
        self.preset = None
        self.start = 0.0
        self.end = 10.0
        self.transcript = ""

    def upload(self, name, content):
        self.controller.require_stopped()
        suffix = Path(name).suffix.lower()
        if suffix not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
            raise ValueError("WAV・MP3・FLAC・OGG・M4Aの音声を選んでください。")
        if not content:
            raise ValueError("音声ファイルが空です。別の録音を選んでください。")
        # Keep even an invalid reference so its crop can be corrected in details.
        folder = self.controller.local_root / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as file:
            file.write(bytes(content))
            source = Path(file.name)
        previous = self.source
        self.source, self.filename = source, Path(name).name
        self.signature = self.preset = None
        self.start, self.end, self.transcript = 0.0, 10.0, ""
        if previous:
            previous.unlink(missing_ok=True)
        self.controller.save_settings({"preset_id": None, **self.options()})
        return self.prepare()

    def options(self):
        settings = self.controller.store.settings()
        return {"volume": settings["volume"], "dictionary": settings["dictionary"]}

    def prepare(self, start=None, end=None, transcript=None):
        self.controller.require_stopped()
        if self.source is None or not self.source.is_file():
            raise ValueError("このセッションで音声をアップロードしてください。")
        start = self.start if start is None else start
        end = self.end if end is None else end
        transcript = self.transcript if transcript is None else transcript
        signature = (float(start), float(end), transcript.strip())
        if signature != self.signature:
            preset = self.controller.register(self.source, "アップロードした音声", transcript, start, end)
            old = self.preset
            self.controller.save_settings({"preset_id": preset["id"], **self.options()})
            self.preset, self.signature = preset, signature
            self.start, self.end, self.transcript = signature
            if old:
                base = (self.controller.store.root / "presets").resolve()
                target = (base / old["id"]).resolve()
                if target != base and target.is_relative_to(base):
                    shutil.rmtree(target, ignore_errors=True)
        return self.preset

    def apply(self, start, end, transcript, volume, dictionary):
        preset = self.prepare(start, end, transcript)
        self.controller.save_settings({"preset_id": preset["id"], "volume": volume,
                                       "dictionary": dictionary})
        return preset


def session_voice(controller):
    if not hasattr(controller, "session_voice"):
        controller.session_voice = SessionVoice(controller)
    return controller.session_voice
