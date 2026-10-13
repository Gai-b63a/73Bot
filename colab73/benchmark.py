"""Twenty fixed Japanese cases, three runs each, with retained audio."""
import asyncio
from pathlib import Path
import time
import wave

from .storage.json import write_json
from .metrics import summarize
from .text import split_text

CASES = [
    "了解です。", "今そっちに行くね。", "ちょっと待って、まだ準備できてない。", "ありがとう、助かったよ！",
    "次はどこに集合する？", "今日は九月三十日、水曜日です。", "午後八時三十分に開始します。",
    "残りは三人、回復薬は二個です。", "合計1,280円で、割引率は15％です。", "バージョン2.7.1に更新しました。",
    "東京から大阪へ新幹線で移動します。", "日本橋と日本海では、同じ漢字でも読み方が違います。",
    "七十三番の部屋で待っています。", "敵が右側にいるから、先に回復して。", "セーブしてから、もう一度挑戦しよう。",
    "Discordのボイスチャンネルに参加してください。", "Google ColabでBOTを起動しました。",
    "HPが半分だから、ボスの攻撃に気をつけて。", "OK、次のステージに進もう！",
    "今日の作戦は、入口で合流してから奥の部屋を調べることです。準備ができた人から声をかけてください。",
]


def save_pcm(path: Path, pcm: bytes):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(pcm)


async def benchmark(worker, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for repeat in range(3):
        for index, text in enumerate(CASES):
            started = time.monotonic()
            first = None
            pcm = []
            peak = 0
            generation = 0
            for segment in split_text(text):
                audio = await worker.synthesize(segment)
                if first is None:
                    first = time.monotonic() - started
                pcm.append(audio.pcm)
                peak = max(peak, audio.peak_memory_mb)
                generation += audio.generation_seconds
            filename = f"case-{index + 1:02d}-run-{repeat + 1}.wav"
            save_pcm(folder / filename, b"".join(pcm))
            results.append({"case": index + 1, "run": repeat + 1, "text": text,
                            "first_segment_seconds": first, "total_generation_seconds": generation,
                            "peak_memory_mb": peak, "audio": filename})
            write_json(folder / "results.json", {"environment": worker.info, "results": results})
            print(f"試聴テスト {len(results)}/60: 最初の区間 {first:.2f}秒", flush=True)
    summary = {"environment": worker.info, "first_segment_seconds": summarize([r["first_segment_seconds"] for r in results]),
               "total_generation_seconds": summarize([r["total_generation_seconds"] for r in results]),
               "peak_memory_mb": max(r["peak_memory_mb"] for r in results),
               "note": "Discord通信を含まない試聴測定。VCでの送信開始はBOT実行時に別途記録。"}
    write_json(folder / "summary.json", summary)
    return summary
