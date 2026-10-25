"""iqview/utils/log_manager.py

Application Log Manager and Stream Interceptor for IQView.

Captures all console/terminal messages (stdout, stderr, debug_print, plugin logs)
into a thread-safe in-memory ring buffer so they can be inspected, searched,
copied, or saved directly from within the IQView application GUI.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
import io
import sys
import threading
import time
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class LogEntry:
    timestamp: float
    time_str: str
    message: str
    stream: str   # "stdout", "stderr", "debug", "app"
    level: str    # "INFO", "WARNING", "ERROR", "DEBUG"

    def format_line(self) -> str:
        """Formatted text line with timestamp and level."""
        return f"[{self.time_str}] [{self.level:<5}] {self.message}"


class _LogEmitter(QObject):
    """PyQt signal emitter for cross-thread log notifications."""
    entry_added = pyqtSignal(object)  # Emits LogEntry
    cleared = pyqtSignal()


class StreamTee:
    """
    Tee stream that forwards writes to the original stream (terminal)
    and buffers lines into the application LogManager.
    """

    def __init__(self, original_stream, stream_name: str, manager: "LogManager"):
        self._orig = original_stream
        self._name = stream_name
        self._mgr = manager
        self._buf = ""
        self._lock = threading.RLock()
        self._local = threading.local()

    def write(self, text: str) -> int:
        if getattr(self._local, "writing", False):
            if self._orig is not None:
                try:
                    return self._orig.write(text)
                except Exception:
                    return len(text)
            return len(text)

        self._local.writing = True
        try:
            # 1. Forward to original console stream if present
            if self._orig is not None:
                try:
                    self._orig.write(text)
                except Exception:
                    pass

            # 2. Buffer into completed lines
            if not isinstance(text, str):
                try:
                    text = str(text)
                except Exception:
                    text = "<unprintable>"

            with self._lock:
                self._buf += text
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    line = line.rstrip("\r")
                    if line:
                        self._mgr.add_log(line, stream=self._name)
            return len(text)
        finally:
            self._local.writing = False

    def flush(self) -> None:
        if getattr(self._local, "flushing", False):
            if self._orig is not None:
                try:
                    self._orig.flush()
                except Exception:
                    pass
            return

        self._local.flushing = True
        try:
            with self._lock:
                if self._buf:
                    line = self._buf.rstrip("\r")
                    self._buf = ""
                    if line:
                        self._mgr.add_log(line, stream=self._name)
            if self._orig is not None:
                try:
                    self._orig.flush()
                except Exception:
                    pass
        finally:
            self._local.flushing = False

    def isatty(self) -> bool:
        if self._orig is not None and hasattr(self._orig, "isatty"):
            try:
                return self._orig.isatty()
            except Exception:
                return False
        return False

    def fileno(self) -> int:
        if self._orig is not None and hasattr(self._orig, "fileno"):
            return self._orig.fileno()
        raise io.UnsupportedOperation("fileno not supported")

    @property
    def encoding(self) -> str:
        return getattr(self._orig, "encoding", "utf-8") or "utf-8"

    @property
    def errors(self) -> str:
        return getattr(self._orig, "errors", "replace") or "replace"


class LogManager:
    """
    Central thread-safe in-memory log buffer for IQView.
    """

    _instance: Optional["LogManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, max_entries: int = 10000):
        self._max_entries = max_entries
        self._entries: collections.deque[LogEntry] = collections.deque(maxlen=max_entries)
        self._lock = threading.RLock()
        self._emitter = _LogEmitter()
        self._installed = False
        self._stdout_tee: Optional[StreamTee] = None
        self._stderr_tee: Optional[StreamTee] = None

    @classmethod
    def get_instance(cls) -> "LogManager":
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def install(cls) -> "LogManager":
        """Install stdout and stderr interception."""
        mgr = cls.get_instance()
        with mgr._lock:
            if not mgr._installed:
                mgr._stdout_tee = StreamTee(sys.stdout, "stdout", mgr)
                mgr._stderr_tee = StreamTee(sys.stderr, "stderr", mgr)
                sys.stdout = mgr._stdout_tee
                sys.stderr = mgr._stderr_tee
                mgr._installed = True
        return mgr

    @property
    def emitter(self) -> _LogEmitter:
        return self._emitter

    def add_log(
        self,
        message: str,
        stream: str = "stdout",
        level: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> LogEntry:
        """Add a log entry thread-safely."""
        now = time.time() if timestamp is None else float(timestamp)
        time_str = time.strftime("%H:%M:%S", time.localtime(now))

        if level is None:
            level = self._detect_level(message, stream)

        entry = LogEntry(
            timestamp=now,
            time_str=time_str,
            message=message,
            stream=stream,
            level=level,
        )

        with self._lock:
            self._entries.append(entry)

        try:
            self._emitter.entry_added.emit(entry)
        except Exception:
            pass

        return entry

    def clear(self) -> None:
        """Clear the in-memory log buffer."""
        with self._lock:
            self._entries.clear()
        try:
            self._emitter.cleared.emit()
        except Exception:
            pass

    def get_entries(self) -> List[LogEntry]:
        """Return a snapshot copy of all buffered entries."""
        with self._lock:
            return list(self._entries)

    def get_text(self, entries: Optional[List[LogEntry]] = None) -> str:
        """Return formatted plain text for all or filtered entries."""
        items = self.get_entries() if entries is None else entries
        return "\n".join(e.format_line() for e in items)

    @staticmethod
    def _detect_level(message: str, stream: str) -> str:
        """Infer log level based on stream and content."""
        if stream == "stderr":
            return "ERROR"
        if stream == "debug":
            return "DEBUG"

        low = message.lower()
        if (
            low.startswith("error:")
            or "error:" in low
            or "traceback (most recent call last):" in low
            or low.startswith("exception:")
            or " exception:" in low
            or "[x]" in message
            or "failed to " in low
        ):
            return "ERROR"

        if (
            low.startswith("warning:")
            or "warning:" in low
            or "[!]" in message
            or "[warn]" in low
        ):
            return "WARNING"

        if "[iqview]" in message or "[debug]" in low or "debug:" in low:
            return "DEBUG"

        return "INFO"


def log_message(message: str, stream: str = "app", level: str = "INFO") -> None:
    """Global helper to record a message in the in-app LogManager."""
    LogManager.get_instance().add_log(message, stream=stream, level=level)
