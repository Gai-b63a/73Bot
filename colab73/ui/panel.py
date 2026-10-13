"""Simple session-only controls embedded in the Colab notebook."""
import asyncio
import html
import json
from pathlib import Path

from ..application import LaunchOptions, NotebookApplication
from .colab import attach_colab_refresh
from .uploads import release_upload, uploaded_file


class NotebookPanel:
    def __init__(self, controller):
        import ipywidgets as w
        self.controller = controller
        self.application = NotebookApplication(controller)
        self.voice = self.application.voice
        self.busy = False
        self.monitor = None
        self.operation = None
        self.last_audio = None
        self.colab_refresh = None
        self.message = w.HTML()
        self.state = w.HTML()
        self.reference = w.Output()
        self.preview_audio = w.Output()
        self.upload = w.FileUpload(accept=".wav,.mp3,.flac,.ogg,.m4a", multiple=False,
                                   description="音声をアップロード", layout=w.Layout(width="220px"))
        self.start = w.FloatText(value=self.voice.start, description="開始秒")
        self.end = w.FloatText(value=self.voice.end, description="終了秒")
        self.transcript = w.Textarea(description="書き起こし", value=self.voice.transcript,
                                     placeholder="任意：空欄なら録音だけで声を再現します。",
                                     layout=w.Layout(width="95%", height="80px"))
        saved = controller.store.settings()
        self.volume = w.FloatSlider(description="音量", value=saved["volume"], min=0, max=2, step=.05)
        self.dictionary = w.Textarea(description="読み辞書", value=json.dumps(saved["dictionary"], ensure_ascii=False, indent=2),
                                     layout=w.Layout(width="95%", height="90px"))
        self.sample = w.Textarea(description="試聴する文", value="こんにちは。今日は一緒にゲームを楽しみましょう。",
                                 layout=w.Layout(width="95%", height="60px"))
        self.logs = w.HTML()
        self.activity = w.HTML()
        self.preview = self.button("試聴", lambda: self.launch("preview"))
        self.launch_bot = self.button("BOTを起動", lambda: self.launch("bot"), "success")
        self.stop = self.button("停止", self.stop_process, "warning")
        self.benchmark = self.button("20例×3回の測定", lambda: self.launch("benchmark"))
        self.download = self.button("測定結果をダウンロード", self.download_reports)
        self.crop = self.button("見本の区間を確認", self.prepare_reference)
        self.editable = [self.upload, self.start, self.end, self.transcript, self.volume,
                         self.dictionary, self.sample, self.crop]
        self.details = w.Accordion(children=[w.VBox([
            w.HTML("<b>見本の切り出し</b><br>既定は先頭10秒。短い録音は全体を使います。受付は3〜30秒です。"),
            w.HBox([self.start, self.end]), self.transcript, self.crop,
            self.sample, self.volume, self.dictionary, self.benchmark, self.download,
            w.HTML("<b>詳細ログ</b>"), self.logs,
        ])], selected_index=None)
        self.details.set_title(0, "詳細設定・測定・ログ")
        self.widget = w.VBox([
            w.HTML("<h3>音声をアップロードして起動</h3>ノイズの少ない5〜15秒の録音をおすすめします。"
                   "<br>新しいColabセッションでは再アップロードしてください。同じセッションでは再利用できます。"),
            self.upload, self.message, self.reference,
            w.HBox([self.preview, self.launch_bot, self.stop]), self.state,
            w.HTML("<b>稼働ログ</b>"), self.activity, self.preview_audio, self.details,
        ])
        self.upload.observe(self.upload_changed, names="value")
        if self.voice.preset:
            self.show_reference(self.voice.preset)
        self.refresh()

    def button(self, label, callback, style=""):
        import ipywidgets as w
        button = w.Button(description=label, button_style=style, layout=w.Layout(width="220px"))
        button.on_click(lambda _: self.schedule(callback))
        return button

    def schedule(self, callback):
        if self.busy:
            return
        self.busy = True
        self.refresh()

        async def perform():
            try:
                await callback()
            except Exception as exc:
                self.message.value = f"<b>操作を完了できませんでした。</b> {html.escape(str(exc))}"
            finally:
                self.busy = False
                self.refresh()

        try:
            self.operation = asyncio.get_running_loop().create_task(perform())
        except RuntimeError:
            self.busy = False
            self.message.value = "Colabで準備セルを実行し直してください。"
            self.refresh()

    def upload_changed(self, change):
        value = change["new"]
        if not value:
            return
        item = uploaded_file(value)
        self.schedule(lambda: self.accept_upload(item))

    async def accept_upload(self, item):
        self.controller.require_stopped()
        self.reference.outputs = ()
        self.preview_audio.outputs = ()
        # An old preview belongs to the previous voice and must not reappear.
        self.last_audio = self.controller.status().get("audio")
        try:
            preset = await asyncio.to_thread(self.voice.upload, item["name"], item["content"])
            self.show_reference(preset)
            self.message.value = "音声の準備ができました。「試聴」または「BOTを起動」を押してください。"
        except Exception as exc:
            raise ValueError(f"{exc} 別の録音をアップロードするか、詳細設定で見本の区間を調整してください。") from None
        finally:
            self.start.value, self.end.value, self.transcript.value = 0, 10, ""
            release_upload(self.upload)

    def show_reference(self, preset):
        from IPython.display import Audio
        self.reference.outputs = ()
        self.reference.append_stdout(f"声の見本: {preset['duration_seconds']:.1f}秒\n")
        self.reference.append_display_data(Audio(filename=preset["audio_path"]))

    async def prepare_reference(self):
        preset = await asyncio.to_thread(self.voice.prepare, self.start.value, self.end.value, self.transcript.value)
        self.show_reference(preset)
        self.message.value = "この区間を見本に使います。"

    async def launch(self, mode):
        options = LaunchOptions(self.start.value, self.end.value, self.transcript.value,
                                self.volume.value, self.dictionary.value, self.sample.value)
        prepared = await self.application.prepare_launch(mode, options)
        self.show_reference(prepared.preset)
        self.preview_audio.outputs = ()
        await self.application.start(prepared)
        self.message.value = "準備中です。初回はモデルのダウンロードに時間がかかります。"

    async def stop_process(self):
        await asyncio.to_thread(self.controller.stop)
        self.message.value = "停止しました。同じ音声で再起動するか、別の音声をアップロードできます。"

    async def download_reports(self):
        from google.colab import files
        archive_path = await asyncio.to_thread(self.application.reports_archive)
        files.download(str(archive_path))
        self.message.value = "測定結果のダウンロードを開始しました。"

    def refresh(self):
        from IPython.display import Audio
        try:
            state = self.controller.status()
            running = state["process_running"]
            phase = state.get("phase", "未起動")
            if phase == "稼働中" and running:
                phase = "BOT稼働中。DiscordでVCに入り、読むチャンネルで /join を実行してください。"
            elif phase == "終了" and state.get("mode") == "preview":
                phase = "試聴が完了しました。下の音声を再生してください。"
            elif not running and state.get("exit_code") not in (None, 0) and phase not in {"停止", "エラー"}:
                phase = "処理が終了しました。詳細ログを確認して、停止後に再起動してください。"
            error = state.get("error")
            self.state.value = f"<b>状態：</b>{html.escape(phase)}" + (
                f"<br>{html.escape(error)}<br>詳細ログを確認し、停止してから再起動してください。" if error else "")
            for item in self.editable:
                item.disabled = running or self.busy
            for item in (self.preview, self.launch_bot, self.benchmark):
                item.disabled = running or self.busy or self.voice.source is None
            self.stop.disabled = self.busy or not running
            self.download.disabled = self.busy or running
            self.logs.value = "<pre style='white-space:pre-wrap;max-height:320px;overflow:auto'>" + html.escape(self.controller.logs()) + "</pre>"
            activity = "<pre style='white-space:pre-wrap;max-height:240px;overflow:auto'>" + html.escape(self.controller.activity_logs()) + "</pre>"
            if self.activity.value != activity:
                self.activity.value = activity
            audio = state.get("audio")
            if not running and audio and audio != self.last_audio and Path(audio).is_file():
                self.preview_audio.outputs = ()
                self.preview_audio.append_display_data(Audio(filename=audio))
                self.last_audio = audio
        except (OSError, ValueError):
            self.state.value = "状態を読み取り中です。"

    def start_monitor(self):
        if self.monitor and not self.monitor.done():
            return

        async def watch():
            while True:
                self.refresh()
                await asyncio.sleep(1)

        try:
            self.monitor = asyncio.get_running_loop().create_task(watch())
        except RuntimeError:
            pass


def show_panel(controller):
    from IPython.display import display
    if controller.panel is None:
        controller.panel = NotebookPanel(controller)
    controller.panel.start_monitor()
    display(controller.panel.widget)
    attach_colab_refresh(controller.panel)
    return controller.panel
