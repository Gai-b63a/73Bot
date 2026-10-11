"""Administrator-only widgets embedded in the Colab notebook."""
import json
from pathlib import Path
import tempfile

from .controller import Controller


def show_panel(controller: Controller):
    import ipywidgets as w
    from IPython.display import Audio, display

    out = w.Output()
    saved = controller.store.settings()
    voice = w.Dropdown(description="使用する声", options=[])
    volume = w.FloatSlider(description="音量", value=saved["volume"], min=0, max=2, step=.05)
    dictionary = w.Textarea(description="読み辞書", value=json.dumps(saved["dictionary"], ensure_ascii=False, indent=2),
                            layout=w.Layout(width="95%", height="100px"))
    source = w.Text(description="Driveの音声", placeholder="/content/drive/MyDrive/録音.wav", layout=w.Layout(width="95%"))
    upload = w.FileUpload(accept=".wav,.mp3,.flac,.ogg,.m4a", multiple=False, description="音声を選ぶ")
    start = w.FloatText(value=0, description="開始秒")
    end = w.FloatText(value=10, description="終了秒")
    name = w.Text(description="声の名前")
    transcript = w.Textarea(description="書き起こし", placeholder="任意：空欄なら録音だけで声を再現します。",
                            layout=w.Layout(width="95%", height="80px"))
    sample = w.Textarea(description="試聴する文", value="こんにちは。今日は一緒にゲームを楽しみましょう。",
                        layout=w.Layout(width="95%", height="60px"))

    def refresh_presets(select=None):
        options = [(p["name"] + " / " + p["id"][:6], p["id"]) for p in controller.store.presets()]
        voice.options = options
        ids = [item[1] for item in options]
        if select in ids:
            voice.value = select
        elif saved["preset_id"] in ids:
            voice.value = saved["preset_id"]

    refresh_presets()

    def button(label, callback, style=""):
        item = w.Button(description=label, button_style=style, layout=w.Layout(width="180px"))

        def clicked(_):
            with out:
                out.clear_output(wait=True)
                try:
                    callback()
                except Exception as exc:
                    print(str(exc))

        item.on_click(clicked)
        return item

    def register():
        controller.require_stopped()
        with tempfile.TemporaryDirectory(prefix="73bot-upload-") as directory:
            path = source.value.strip()
            if upload.value:
                item = list(upload.value.values())[0] if isinstance(upload.value, dict) else upload.value[0]
                path = Path(directory) / Path(item["name"]).name
                path.write_bytes(bytes(item["content"]))
            if not path:
                raise ValueError("Driveのファイルを指定するか、音声を選んでください。")
            preset = controller.register(path, name.value, transcript.value, start.value, end.value)
        refresh_presets(preset["id"])
        upload.value = ()
        print("Driveに声を登録しました。「設定を保存」してから試聴できます。")
        display(Audio(filename=preset["audio_path"]))

    def save():
        if not voice.value:
            raise ValueError("声を登録・選択してください。")
        controller.save_settings({"preset_id": voice.value, "volume": volume.value,
                                  "dictionary": json.loads(dictionary.value)})
        print("設定をDriveに保存しました。次回も復元されます。")

    def launch(mode):
        save()
        token = None
        if mode == "bot":
            from google.colab import userdata
            token = userdata.get("DISCORD_BOT_TOKEN")
        controller.start(mode, token=token, text=sample.value)
        print("処理を開始しました。「状態・ログを確認」で進み具合を確認してください。")

    def status():
        state = controller.status()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print(controller.logs())
        if not state["process_running"] and state.get("audio") and Path(state["audio"]).is_file():
            display(Audio(filename=state["audio"]))
        if not state["process_running"]:
            print(f"測定結果の保存先: {controller.store.root / 'reports'}")

    def stop():
        controller.stop()
        print("停止しました。声の選択・設定変更・再起動ができます。")

    registration = w.VBox([
        w.HTML("<b>初回・新しい声の登録</b><br>ノイズの少ない5〜15秒を推奨（3〜30秒）。"
               "書き起こしは任意です。空欄なら録音だけで声を再現します。"
               "入力する場合は、切り出した区間で話している文章と一致させてください。"),
        source, upload, w.HBox([start, end]), name, transcript,
        button("声をDriveに登録", register),
    ])
    display(w.VBox([
        registration, w.HTML("<hr><b>保存済み設定</b>（変更は停止中のみ）"),
        voice, volume, dictionary, button("設定を保存", save), sample,
        w.HBox([button("試聴", lambda: launch("preview")), button("20例×3回の測定", lambda: launch("benchmark"))]),
        w.HBox([button("BOTを起動", lambda: launch("bot"), "success"), button("停止", stop, "warning")]),
        button("状態・ログを確認", status), out,
    ]))
