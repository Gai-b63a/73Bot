"""Discord slash commands and access checks."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..reader import GuildReader
from .audio import DiscordPlayer, MeasuredVoiceClient
from ..runtime.activity import log as activity

log = logging.getLogger(__name__)


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
                activity.info("VC接続完了。対象チャンネルの読み上げを開始しました。")
                await interaction.followup.send("このテキストチャンネルの読み上げを開始しました。", ephemeral=True)
            except Exception as exc:
                log.error("VC接続失敗 (%s)", type(exc).__name__)
                activity.error("VC接続に失敗しました。権限と詳細ログを確認してください。")
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
