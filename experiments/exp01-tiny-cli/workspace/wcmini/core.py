from pathlib import Path

def count_file(path: str | Path) -> tuple[int, int, int]:
    data = Path(path).read_bytes()
    lines = data.count(b"\n")
    # words: whitespace-separated tokens in text
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    words = len(text.split())
    bytes_ = len(data)
    return lines, words, bytes_
