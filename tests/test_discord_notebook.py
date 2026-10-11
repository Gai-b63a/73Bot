import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import nbformat
import pytest

from colab73.discord_bot import ColabBot, DiscordPlayer, MeasuredVoiceClient, PCMSource, ReadingCommands
from colab73.engine import AudioChunk, QwenEngine
from colab73.metrics import Metrics


def test_pcm_frames_are_exactly_20ms():
    source = PCMSource(b"\x01\x00" * 2000)
    assert len(source.read()) == 3840
    tail = source.read()
    assert len(tail) == 3840
    assert tail[160:] == bytes(3680)
    assert source.read() == b""
    source.cleanup()


@pytest.mark.asyncio
async def test_commands_have_no_voice_selection_and_require_same_vc(tmp_path):
    worker = SimpleNamespace(on_failure=None, busy=False, pending=asyncio.Queue(), failed=None)
    bot = ColabBot(worker, {"volume": 1, "dictionary": {}}, {"name": "自分"}, Metrics(tmp_path))
    try:
        cog = ReadingCommands(bot)
        await bot.add_cog(cog)
        assert {c.name for c in bot.tree.get_commands()} == {"join", "leave", "skip", "clear", "status"}
        interaction = SimpleNamespace(guild=SimpleNamespace(voice_client=SimpleNamespace(channel=SimpleNamespace(id=1))),
                                      user=SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(id=2))),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        assert not await cog.same_channel(interaction)
        interaction.response.send_message.assert_awaited_once()
        interaction.user.voice.channel.id = 1
        assert await cog.same_channel(interaction)
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_dm_bot_and_empty_posts_are_ignored(tmp_path):
    worker = SimpleNamespace(on_failure=None, busy=False, pending=asyncio.Queue(), failed=None)
    bot = ColabBot(worker, {"volume": 1, "dictionary": {}}, {"name": "自分"}, Metrics(tmp_path))
    try:
        await bot.on_message(SimpleNamespace(guild=None))
        await bot.on_message(SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(bot=True)))
        reader = SimpleNamespace(closed=False, is_idle=True, submit=Mock(), close=AsyncMock())
        bot.readers[1] = reader
        bot.monitored[1] = 2
        message = SimpleNamespace(guild=SimpleNamespace(id=1, voice_client=SimpleNamespace(is_connected=lambda: True)),
                                  author=SimpleNamespace(bot=False), channel=SimpleNamespace(id=2), clean_content="```code```", id=3)
        await bot.on_message(message)
        reader.submit.assert_not_called()
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_join_reconnect_empty_channel_and_leave(tmp_path):
    worker = SimpleNamespace(on_failure=None, busy=False, pending=asyncio.Queue(), failed=None)
    bot = ColabBot(worker, {"volume": 1, "dictionary": {}}, {"name": "自分"}, Metrics(tmp_path))
    bot._connection.user = SimpleNamespace(id=99)
    guild = SimpleNamespace(id=1, voice_client=None)
    channel = SimpleNamespace(id=10, members=[SimpleNamespace(bot=False)])
    connections = []

    async def connect(**kwargs):
        voice = SimpleNamespace(channel=channel, connected=True, stop=Mock())
        voice.is_connected = lambda: voice.connected

        async def disconnect(**kwargs):
            voice.connected = False
            guild.voice_client = None

        voice.disconnect = AsyncMock(side_effect=disconnect)
        guild.voice_client = voice
        connections.append(voice)
        return voice

    channel.connect = AsyncMock(side_effect=connect)
    interaction = SimpleNamespace(
        guild=guild, guild_id=1, channel_id=20,
        user=SimpleNamespace(voice=SimpleNamespace(channel=channel)),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    cog = ReadingCommands(bot)
    try:
        await cog.join.callback(cog, interaction)
        first_reader = bot.readers[1]
        assert bot.monitored[1] == 20
        assert len(connections) == 1

        interaction.channel_id = 21
        await cog.join.callback(cog, interaction)
        assert first_reader.closed
        assert bot.monitored[1] == 21
        assert len(connections) == 1

        connections[0].connected = False
        await cog.join.callback(cog, interaction)
        assert len(connections) == 2
        connections[0].disconnect.assert_awaited_once_with(force=True)

        channel.members = [SimpleNamespace(bot=True)]
        reader = bot.readers[1]
        await bot.on_voice_state_update(SimpleNamespace(id=4, guild=guild),
                                        SimpleNamespace(channel=channel), SimpleNamespace(channel=None))
        assert reader.closed and 1 not in bot.monitored and 1 not in bot.readers
        assert guild.voice_client is None

        channel.members = [SimpleNamespace(bot=False)]
        await cog.join.callback(cog, interaction)
        reader = bot.readers[1]
        await cog.leave.callback(cog, interaction)
        assert reader.closed and guild.voice_client is None
        assert 1 not in bot.monitored
    finally:
        await bot.close()


def test_notebook_schema_code_and_no_secrets():
    path = Path(__file__).resolve().parents[1] / "notebooks" / "73Bot_Colab.ipynb"
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec")
            assert cell.outputs == []
            assert cell.execution_count is None
    contents = path.read_text(encoding="utf-8")
    assert "userdata" not in contents or "userdata.get" in contents
    assert "colab73" in contents


@pytest.mark.asyncio
async def test_packet_metric_is_after_successful_send_and_only_once(monkeypatch):
    import discord
    voice = object.__new__(MeasuredVoiceClient)
    voice.loop = asyncio.get_running_loop()
    callback = Mock()
    voice.first_packet_callback = callback
    send = Mock(side_effect=RuntimeError("network"))
    monkeypatch.setattr(discord.VoiceClient, "send_audio_packet", send)
    with pytest.raises(RuntimeError):
        voice.send_audio_packet(b"audio")
    callback.assert_not_called()
    send.side_effect = None
    voice.send_audio_packet(b"audio")
    voice.send_audio_packet(b"audio")
    await asyncio.sleep(0)
    callback.assert_called_once()
    assert voice.first_packet_callback is None


@pytest.mark.asyncio
async def test_play_cancellation_waits_for_sender_cleanup():
    callbacks = []
    loop = asyncio.get_running_loop()
    voice = SimpleNamespace(is_connected=lambda: True, first_packet_callback=None)
    voice.play = lambda source, after: callbacks.append(after)
    voice.stop = lambda: loop.call_later(.02, callbacks[0], None)
    player = DiscordPlayer(voice, 1)
    task = asyncio.create_task(player.play(AudioChunk(bytes(3840), .02, .1), Mock()))
    await asyncio.sleep(.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert voice.first_packet_callback is None


def test_missing_gpu_is_reported_before_loading_model(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    with pytest.raises(RuntimeError, match="GPU"):
        QwenEngine().load("no-model-needed")


def test_portable_bundle_contains_code_and_no_private_files(tmp_path):
    import subprocess
    import sys
    import zipfile
    repo = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(repo / "tools" / "build_colab_notebook.py"),
                    "--output-dir", str(tmp_path)], check=True)
    generated = tmp_path / "notebooks" / "73Bot_Colab.ipynb"
    published = repo / "notebooks" / "73Bot_Colab.ipynb"
    assert json.loads(generated.read_text(encoding="utf-8")) == json.loads(published.read_text(encoding="utf-8"))
    with zipfile.ZipFile(tmp_path / "dist" / "73Bot_Colab.zip") as archive:
        from tools.check_public_files import check_content
        names = archive.namelist()
        assert "colab73/runner.py" in names
        assert "notebooks/73Bot_Colab.ipynb" in names
        assert not any(".env" in n or ".cache" in n or n.endswith(".wav") for n in names)
        assert archive.read("LICENSE") == (repo / "LICENSE").read_bytes()
        assert b"Copyright (c) 2026 guy7cc" in archive.read("LICENSE")
        assert "THIRD_PARTY.md" in names
        for name in names:
            assert not check_content(name, archive.read(name)), name
