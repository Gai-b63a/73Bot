"""Small application-only activity log, separate from dependency diagnostics."""
from collections import deque
import logging
import logging.handlers
from pathlib import Path

log = logging.getLogger("colab73.activity")


def configure(path: Path):
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=128_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def read(path: Path) -> str:
    if not path.exists():
        return "まだ稼働ログはありません。"
    with path.open(encoding="utf-8") as source:
        return "".join(deque(source, maxlen=100)).rstrip()
