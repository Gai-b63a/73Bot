"""Discord transport. Voice selection is deliberately absent from commands."""
from __future__ import annotations

import asyncio
import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from .reader import GuildReader, Job
from .text import normalize, split_text

log = logging.getLogger(__name__)


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


class ColabBot(commands.Bot):
    def __init__(self, worker, settings, preset, metrics):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         allowed_mentions=discord.AllowedMentions.none())
        self.worker, self.settings, self.preset, self.metrics = worker, settings, preset, metrics
        self.readers: dict[int, GuildReader] = {}
        self.monitored: dict[int, int] = {}
        self.guild_locks: dict[int, asyncio.Lock] = {}
        self.notice_times = {}
        self.reading_error = None
        self._closing = False
        self._background = set()
        worker.on_failure = self.worker_failed

    def worker_failed(self, error):
        self.reading_error = error
        log.error(error)
        task = asyncio.create_task(self.stop_all_readers())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def setup_hook(self):
        if not discord.opus.is_loaded():
            import ctypes.util
            library = ctypes.util.find_library("opus")
            if not library:
                raise RuntimeError("libopusがありません。Colabのセットアップを再実行してください。")
            discord.opus.load_opus(library)
        if not discord.voice_client.has_dave:
            raise RuntimeError("Discord音声暗号化ライブラリがありません。セットアップを再実行してください。")
        await self.add_cog(ReadingCommands(self))
        # Replace this application's global command set, removing legacy /voice.
        await self.tree.sync()

    async def on_ready(self):
        log.info("BOT接続完了。Discordで /join を実行してください。")

    async def stop_reader(self, guild_id):
        self.monitored.pop(guild_id, None)
        reader = self.readers.pop(guild_id, None)
        if reader:
            await reader.close()

    async def stop_all_readers(self):
        for guild_id in list(self.readers):
            await self.stop_reader(guild_id)

    async def reader_error(self, guild_id, error):
        # This callback runs in the reader task, so never await that same task.
        self.monitored.pop(guild_id, None)
        log.error("読み上げを停止しました: %s", error)

    async def on_message(self, message):
        if message.guild is None or message.author.bot or self.reading_error:
            return
        guild_id = message.guild.id
        if self.monitored.get(guild_id) != message.channel.id:
            return
        reader = self.readers.get(guild_id)
        voice = message.guild.voice_client
        if reader is None or reader.closed or not voice or not voice.is_connected():
            return
        received_at = time.monotonic()
        text = normalize(message.clean_content, self.settings["dictionary"])
        if not text:
            return
        idle = (all(r.is_idle for r in self.readers.values()) and not self.worker.busy
                and self.worker.pending.empty())
        accepted = reader.submit(Job(message.id, split_text(text), received_at, idle))
        if not accepted and received_at - self.notice_times.get(guild_id, float("-inf")) >= 30:
            self.notice_times[guild_id] = received_at
            try:
                await message.channel.send("読み上げ待ちが100件に達しました。この投稿は受付できません。/skip または /clear を利用してください。")
            except discord.HTTPException:
                log.warning("待ち行列の満杯通知を送信できませんでした。")

    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        if member.id == self.user.id and after.channel is None:
            await self.stop_reader(guild.id)
            return
        voice = guild.voice_client
        if voice and voice.channel and not any(not m.bot for m in voice.channel.members):
            async with self.guild_locks.setdefault(guild.id, asyncio.Lock()):
                await self.stop_reader(guild.id)
                if guild.voice_client:
                    await guild.voice_client.disconnect()

    def snapshot(self):
        return {"connected": self.is_ready(), "voice": self.preset["name"],
                "generating": self.worker.busy, "error": self.reading_error or self.worker.failed,
                "guilds": {str(g): {"pending": r.queue.qsize(), "reading": r.current is not None,
                                    "stopped": r.closed} for g, r in self.readers.items()}}

    async def close(self):
        if self._closing:
            return
        self._closing = True
        await self.stop_all_readers()
        for voice in list(self.voice_clients):
            try:
                await voice.disconnect(force=True)
            except Exception:
                log.warning("VC切断処理でエラーが発生しました。")
        await asyncio.gather(*list(self._background), return_exceptions=True)
        await super().close()


class ReadingCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def same_channel(self, interaction):
        voice = interaction.guild.voice_client
        user_voice = interaction.user.voice
        if not voice or not user_voice or voice.channel.id != user_voice.channel.id:
            await interaction.response.send_message("BOTと同じボイスチャンネルに参加してから実行してください。", ephemeral=True)
            return False
        return True

    @app_commands.command(name="join", description="このチャンネルの読み上げを開始します")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("ボイスチャンネルに参加してから実行してください。", ephemeral=True)
            return
        if self.bot.reading_error or self.bot.worker.failed:
            await interaction.response.send_message("音声生成が停止しています。管理者がColabから再起動してください。", ephemeral=True)
            return
        existing = interaction.guild.voice_client
        if existing and not await self.same_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        async with self.bot.guild_locks.setdefault(interaction.guild_id, asyncio.Lock()):
            try:
                # Recheck after acquiring the lock: concurrent /join cannot move
                # or bind an existing connection from another voice channel.
                voice = interaction.guild.voice_client
                channel = interaction.user.voice.channel if interaction.user.voice else None
                if channel is None or (voice and voice.channel.id != channel.id):
                    await interaction.followup.send("BOTと同じVCから実行してください。", ephemeral=True)
                    return
                if voice is None:
                    voice = await channel.connect(cls=MeasuredVoiceClient, self_deaf=True)
                elif not voice.is_connected():
                    await voice.disconnect(force=True)
                    voice = await channel.connect(cls=MeasuredVoiceClient, self_deaf=True)
                await self.bot.stop_reader(interaction.guild_id)
                player = DiscordPlayer(voice, self.bot.settings["volume"])
                reader = GuildReader(self.bot.worker, player, self.bot.metrics,
                                     lambda error: self.bot.reader_error(interaction.guild_id, error))
                self.bot.readers[interaction.guild_id] = reader
                self.bot.monitored[interaction.guild_id] = interaction.channel_id
                await interaction.followup.send("このテキストチャンネルの読み上げを開始しました。", ephemeral=True)
            except Exception as exc:
                log.error("VC接続失敗 (%s)", type(exc).__name__)
                await interaction.followup.send("接続できませんでした。BOTの接続・発言権限とColabのログを確認してください。", ephemeral=True)

    @app_commands.command(name="leave", description="読み上げを終了して退出します")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction):
        if not await self.same_channel(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        async with self.bot.guild_locks.setdefault(interaction.guild_id, asyncio.Lock()):
            await self.bot.stop_reader(interaction.guild_id)
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.disconnect()
        await interaction.followup.send("読み上げを終了しました。", ephemeral=True)

    @app_commands.command(name="skip", description="現在の投稿の残りをスキップします")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        if not await self.same_channel(interaction):
            return
        reader = self.bot.readers.get(interaction.guild_id)
        if reader:
            reader.skip()
        await interaction.response.send_message("現在の投稿をスキップしました。", ephemeral=True)

    @app_commands.command(name="clear", description="待ち行列を消します（現在の再生は続けます）")
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction):
        if not await self.same_channel(interaction):
            return
        reader = self.bot.readers.get(interaction.guild_id)
        count = reader.clear() if reader else 0
        await interaction.response.send_message(f"未再生の{count}件を削除しました。", ephemeral=True)

    @app_commands.command(name="status", description="読み上げの稼働状況を確認します")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction):
        reader = self.bot.readers.get(interaction.guild_id)
        error = self.bot.reading_error or self.bot.worker.failed
        voice = interaction.guild.voice_client
        text = (f"声: {self.bot.preset['name']}\n"
                f"VC: {'接続中' if voice and voice.is_connected() else '未接続'}\n"
                f"待ち件数: {reader.queue.qsize() if reader else 0}\n"
                f"音声生成: {'停止' if error else '生成中' if self.bot.worker.busy else '待機中'}")
        if error:
            text += "\n管理者がColabから再起動してください。"
        elif reader and reader.closed:
            text += "\n読み上げが停止しています。/join で再接続してください。"
        await interaction.response.send_message(text, ephemeral=True)
