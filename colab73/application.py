"""Notebook operations independent of widgets and display functions."""
from dataclasses import dataclass, field
import asyncio
import json
import zipfile

from .contracts import RunMode, validate_mode
from .session import session_voice


@dataclass(frozen=True)
class LaunchOptions:
    start: float
    end: float
    transcript: str
    volume: float
    dictionary: str
    text: str


@dataclass(frozen=True)
class PreparedLaunch:
    mode: RunMode
    preset: dict
    token: str | None = field(repr=False)
    text: str


def colab_token() -> str:
    from google.colab import userdata
    try:
        return userdata.get("DISCORD_BOT_TOKEN")
    except Exception:
        raise ValueError("左の鍵アイコンからDISCORD_BOT_TOKENを登録し、ノートブックへのアクセスを許可してください。") from None


class NotebookApplication:
    def __init__(self, controller, token_provider=colab_token):
        self.controller = controller
        self.voice = session_voice(controller)
        self.token_provider = token_provider

    async def prepare_launch(self, mode: RunMode, options: LaunchOptions) -> PreparedLaunch:
        validate_mode(mode)
        self.controller.require_stopped()
        dictionary = json.loads(options.dictionary)
        self.controller.store.validate_settings({"volume": options.volume, "dictionary": dictionary})
        # Colab's secret request uses the notebook message channel. Keep it on
        # the notebook thread; only filesystem/FFmpeg/process work is offloaded.
        token = self.token_provider() if mode == "bot" else None
        preset = await asyncio.to_thread(self.voice.apply, options.start, options.end,
                                         options.transcript, options.volume, dictionary)
        return PreparedLaunch(mode, preset, token, options.text)

    async def start(self, prepared: PreparedLaunch) -> None:
        await asyncio.to_thread(self.controller.start, prepared.mode,
                                token=prepared.token, text=prepared.text)

    def reports_archive(self):
        self.controller.require_stopped()
        source = self.controller.store.root / "reports"
        reports = [path for path in source.glob("**/*") if path.is_file()]
        if not reports:
            raise ValueError("測定結果がありません。試聴・測定・BOTを終了してからダウンロードしてください。")
        target = self.controller.paths.reports_archive
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in reports:
                archive.write(path, path.relative_to(source))
        return target
