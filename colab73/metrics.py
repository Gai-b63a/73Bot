"""Durations only for Discord; benchmark text is intentionally public test data."""
import json
import math
from pathlib import Path
import statistics
from .storage.json import write_json


def summarize(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "p95": None, "max": None, "all_within_5s": None}
    ordered = sorted(values)
    return {"count": len(values), "mean": statistics.mean(values),
            "p95": ordered[math.ceil(len(values) * .95) - 1], "max": ordered[-1],
            "all_within_5s": ordered[-1] <= 5}


class Metrics:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.records = []

    def add(self, **record):
        self.records.append(record)
        with (self.folder / "events.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def finish(self, info: dict) -> dict:
        summary = {"environment": info,
                   "generation_seconds": summarize([r["generation_seconds"] for r in self.records if "generation_seconds" in r]),
                   "idle_first_packet_seconds": summarize([r["latency_seconds"] for r in self.records
                                                            if r.get("idle") and "latency_seconds" in r]),
                   "queued_first_packet_seconds": summarize([r["latency_seconds"] for r in self.records
                                                              if not r.get("idle") and "latency_seconds" in r]),
                   "peak_gpu_memory_mb": max((r.get("peak_memory_mb", 0) for r in self.records), default=0)}
        write_json(self.folder / "summary.json", summary)
        return summary
