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


def _write_line(message: str) -> None:
    if _log_path is None:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {message}\n"

    with _lock:
        with _log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
