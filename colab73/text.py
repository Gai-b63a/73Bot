"""Predictable preprocessing; no LLM rewriting or automatic voice switching."""
import re


def normalize(text: str, dictionary: dict[str, str]) -> str:
    text = re.sub(r"```.*?(?:```|$)", " ", text, flags=re.S)
    text = re.sub(r"https?://[^\s<>]+", " URL ", text)
    text = re.sub(r"<a?:([A-Za-z0-9_]+):\d+>", r" \1 ", text)
    text = re.sub(r"<[@#][!&]?\d+>", " ", text)  # unresolved mentions
    text = re.sub(r"<\|[^>]*\|>", " ", text)  # do not pass model control tokens
    text = re.sub(r"[*_~`|]", "", text)
    if dictionary:
        pattern = "|".join(re.escape(k) for k in sorted(dictionary, key=len, reverse=True))
        text = re.sub(pattern, lambda m: dictionary[m.group()], text)
    return re.sub(r"\s+", " ", text).strip()


def split_text(text: str, limit: int = 40) -> list[str]:
    if limit < 1:
        raise ValueError("limit must be positive")
    parts = []
    while text:
        end = min(limit, len(text))
        if len(text) > limit:
            boundary = [m.end() for m in re.finditer(r"[。！？!?、，,；;\s]", text[:limit])]
            if boundary:
                end = boundary[-1]
        chunk, text = text[:end].strip(), text[end:].lstrip()
        if chunk:
            parts.append(chunk)
    return parts
