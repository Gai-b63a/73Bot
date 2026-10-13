"""Deliver idle-time widget updates through Colab's output callback channel."""
import json
import uuid


class ColabRefresh:
    def __init__(self, panel, output):
        self.panel = panel
        self.output = output
        self.name = "73Bot.refresh." + uuid.uuid4().hex
        self.generation = 0
        self.sent_outputs = {}
        output.register_callback(self.name, self.refresh)

    def refresh(self, generation):
        from IPython.display import JSON
        # A redisplayed panel takes over; polling in an older output stops.
        if generation != self.generation:
            return JSON({"active": False})
        self.panel.refresh()
        for widget in (self.panel.message, self.panel.state, self.panel.logs):
            widget.send_state("value")
        for widget in (self.panel.reference, self.panel.preview_audio):
            # Audio is embedded in these outputs. Resend it only when changed,
            # rather than transferring the whole WAV every second.
            if self.sent_outputs.get(widget.model_id) != widget.outputs:
                widget.send_state("outputs")
                self.sent_outputs[widget.model_id] = widget.outputs
        for widget in self.panel.editable:
            keys = ["disabled"]
            if widget is self.panel.upload:
                # Do not resend an uploaded recording on every refresh.
                if "_counter" in widget.traits():
                    keys.append("_counter")
            elif "value" in widget.traits():
                keys.append("value")
            widget.send_state(keys)
        for widget in (self.panel.preview, self.panel.launch_bot, self.panel.stop,
                       self.panel.benchmark, self.panel.download):
            widget.send_state("disabled")
        return JSON({"active": True})

    def attach(self):
        self.generation += 1
        self.sent_outputs.clear()
        name, generation = json.dumps(self.name), self.generation
        # Requests never overlap. This updates an open control panel, without
        # keeping a Python cell running or bypassing Colab runtime limits.
        script = """
(() => {
  async function refresh() {
    try {
      const reply = await google.colab.kernel.invokeFunction(NAME, [GENERATION], {});
      if (reply.data['application/json'].active === false) return;
    } catch (error) {
      // A transient disconnect can recover when the runtime reconnects.
    }
    setTimeout(refresh, 1000);
  }
  setTimeout(refresh, 0);
})();
""".replace("NAME", name).replace("GENERATION", str(generation))
        self.output.eval_js(script, ignore_result=True)


def attach_colab_refresh(panel):
    try:
        from google.colab import output
    except ImportError:
        return
    if panel.colab_refresh is None:
        panel.colab_refresh = ColabRefresh(panel, output)
    panel.colab_refresh.attach()
