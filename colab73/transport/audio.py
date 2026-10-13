"""Discord PCM transport and first-packet measurement."""
import asyncio
import io
import time

import discord


class MeasuredVoiceClient(discord.VoiceClient):
    first_packet_callback = None

    def send_audio_packet(self, data, *, encode=True):
        super().send_audio_packet(data, encode=encode)
        callback = self.first_packet_callback
        if callback is not None:
            self.first_packet_callback = None
            self.loop.call_soon_threadsafe(callback, time.monotonic())


class PCMSource(discord.AudioSource):
    def __init__(self, pcm: bytes):
        self.buffer = io.BytesIO(pcm)

    def read(self):
        frame = self.buffer.read(3840)  # Discord: 20 ms at 48 kHz stereo int16
        return frame.ljust(3840, b"\0") if frame else b""

    def cleanup(self):
        self.buffer.close()


class DiscordPlayer:
    def __init__(self, voice: MeasuredVoiceClient, volume: float):
        self.voice, self.volume = voice, volume

    async def play(self, audio, on_first_packet):
        if not self.voice.is_connected():
            raise RuntimeError("VC接続が切れました。/join で再接続してください。")
        loop = asyncio.get_running_loop()
        finished = loop.create_future()

        def finish(error):
            if not finished.done():
                if error:
                    finished.set_exception(error)
                else:
                    finished.set_result(None)

        source = discord.PCMVolumeTransformer(PCMSource(audio.pcm), volume=self.volume)
        self.voice.first_packet_callback = on_first_packet
        started = False
        try:
            self.voice.play(source, after=lambda error: loop.call_soon_threadsafe(finish, error))
            started = True
            await asyncio.shield(finished)
        finally:
            self.voice.first_packet_callback = None
            if started and not finished.done():
                self.voice.stop()
                # Wait for the sender thread before allowing a new player to
                # claim its callback or cleaning up the old PCM buffer.
                try:
                    await asyncio.wait_for(asyncio.shield(finished), timeout=2)
                except Exception:
                    pass
            source.cleanup()

    def stop(self):
        self.voice.first_packet_callback = None
        self.voice.stop()


