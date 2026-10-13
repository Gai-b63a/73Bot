"""Discord connection and guild reading lifecycle."""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from ..reader import GuildReader, Job
from ..text import normalize, split_text
from .commands import ReadingCommands
from ..runtime.activity import log as activity

log = logging.getLogger(__name__)


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
        activity.error("音声生成が停止しました。状態欄を確認し、停止後に再起動してください。")
        task = asyncio.create_task(self.stop_all_readers(clear_monitoring=False))
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
        activity.info("Discord接続完了。読むチャンネルで /join を実行してください。")

    async def on_disconnect(self):
        activity.info("Discordとの接続が切れました。")

    async def stop_reader(self, guild_id, clear_monitoring=True):
        if clear_monitoring:
            self.monitored.pop(guild_id, None)
        reader = self.readers.pop(guild_id, None)
        if reader:
            await reader.close()
            activity.info("読み上げを終了しました。")

    async def stop_all_readers(self, clear_monitoring=True):
        for guild_id in list(self.readers):
            await self.stop_reader(guild_id, clear_monitoring=clear_monitoring)

    async def reader_error(self, guild_id, error):
        # This callback runs in the reader task, so never await that same task.
        log.error("読み上げを停止しました: %s", error)
        activity.error("読み上げが停止しました。状態欄と詳細ログを確認してください。")

    async def on_message(self, message):
        if message.guild is None or message.author.bot:
            return
        guild_id = message.guild.id
        if self.monitored.get(guild_id) != message.channel.id:
            return
        reader = self.readers.get(guild_id)
        voice = message.guild.voice_client
        if self.reading_error or self.worker.failed or reader is None or reader.closed:
            activity.info("メッセージ受信：受付不可（読み上げ停止中）。")
            return
        if not voice or not voice.is_connected():
            activity.info("メッセージ受信：受付不可（VC未接続）。")
            return
        received_at = time.monotonic()
        text = normalize(message.clean_content, self.settings["dictionary"])
        if not text:
            activity.info("メッセージ受信：読み上げ対象の本文なし。")
            return
        idle = (all(r.is_idle for r in self.readers.values()) and not self.worker.busy
                and self.worker.pending.empty())
        accepted = reader.submit(Job(message.id, split_text(text), received_at, idle))
        activity.info("メッセージ受信：%s", "読み上げ受付。" if accepted else "受付不可（待ち行列が満杯）。")
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


