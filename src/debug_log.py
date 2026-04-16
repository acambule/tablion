from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import traceback

_log_path: Path | None = None
_lock = threading.Lock()


def initialize_debug_log(path: Path) -> None:
    global _log_path
    _log_path = path
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    _write_line("--- Debug logging started ---")


def debug_log(message: str) -> None:
    _write_line(message)


def debug_exception(prefix: str, exc: BaseException) -> None:
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _write_line(f"{prefix}: {details}")


def debug_mime_data(prefix: str, mime_data) -> None:
    if mime_data is None:
        _write_line(f"{prefix}: mime_data=None")
        return

    try:
        formats = list(mime_data.formats())
    except Exception as exc:
        _write_line(f"{prefix}: failed to list formats: {exc}")
        return

    parts: list[str] = [f"formats={formats}"]
    try:
        if mime_data.hasUrls():
            urls = [url.toString() for url in mime_data.urls()[:10]]
            parts.append(f"urls={urls}")
    except Exception as exc:
        parts.append(f"urls_error={exc}")

    for mime_name in formats:
        try:
            payload = bytes(mime_data.data(mime_name))
            preview = payload[:160]
            try:
                preview_text = preview.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    preview_text = preview.decode("utf-16le")
                except UnicodeDecodeError:
                    preview_text = preview.hex()
            parts.append(
                f"{mime_name}=len:{len(payload)} preview:{preview_text!r}"
            )
        except Exception as exc:
            parts.append(f"{mime_name}=error:{exc}")

    _write_line(f"{prefix}: {' | '.join(parts)}")


def _write_line(message: str) -> None:
    if _log_path is None:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {message}\n"

    with _lock:
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
