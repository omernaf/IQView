"""Open a ``.py`` file in the user's preferred application.

The preferred application is whatever the operating system uses for ``.py``
files. When nothing is registered, or the registration is the Python
interpreter (so opening the file would run it), the system Open With dialog
is shown instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class OpenPyResult:
    """Outcome of trying to open a ``.py`` file."""

    cancelled: bool = False
    message: str = ""

    @property
    def ok(self) -> bool:
        return not self.message and not self.cancelled


def command_opens_in_editor(command: str) -> bool:
    """Return True when *command* launches an editor rather than the interpreter.

    A bare ``python file.py`` or ``py.exe "%1"`` runs the script. A command
    whose program is any other application, or a Python process that launches
    an editor script such as ``idle.pyw``, opens an editor.
    """
    tokens = _strip_env(_split_command(command or ""))
    tokens = [token for token in tokens if token and not token.startswith("%")]
    if not tokens:
        return False
    stem = _exe_stem(tokens[0])
    if not _stem_is_interpreter(stem):
        return True
    # Interpreter plus another program or script (IDLE, python -m idlelib, …)
    # still opens an editor. A bare interpreter command only runs the file.
    for arg in tokens[1:]:
        if arg.startswith("-") or arg.startswith("%"):
            continue
        return True
    return False


def open_py_file(path: str, parent_hwnd: int = 0) -> OpenPyResult:
    """Open *path* in the preferred editor, or show the system app chooser."""
    if not path or not os.path.isfile(path):
        return OpenPyResult(message="The plugin file is not on disk.")
    path = os.path.abspath(path)
    if sys.platform == "win32":
        return _open_windows(path, parent_hwnd)
    if sys.platform == "darwin":
        return _spawn_or_error(["open", path], "Could not open the file.")
    return _open_linux(path)


def _open_windows(path: str, parent_hwnd: int) -> OpenPyResult:
    command = _windows_open_command()
    if command_opens_in_editor(command):
        try:
            os.startfile(path)  # noqa: S606 - user asked to open the file in their editor
            return OpenPyResult()
        except OSError:
            pass
    return _windows_open_with_dialog(path, parent_hwnd)


def _windows_open_command() -> str:
    command = _assoc_query(".py", "open", 1)  # ASSOCSTR_COMMAND
    if command:
        return command
    return _assoc_query(".py", None, 1) or _assoc_query(".py", "open", 2) or ""


def _assoc_query(extension: str, verb: Optional[str], kind: int) -> str:
    import ctypes
    from ctypes import wintypes

    shlwapi = ctypes.WinDLL("shlwapi", use_last_error=True)
    query = shlwapi.AssocQueryStringW
    query.argtypes = [
        wintypes.DWORD,
        ctypes.c_int,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query.restype = ctypes.c_long
    buf = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buf))
    hr = query(0, kind, extension, verb, buf, ctypes.byref(size))
    if hr != 0:
        return ""
    return buf.value.strip()


def _windows_open_with_dialog(path: str, parent_hwnd: int) -> OpenPyResult:
    import ctypes
    from ctypes import wintypes

    class OPENASINFO(ctypes.Structure):
        _fields_ = [
            ("pcszFile", ctypes.c_wchar_p),
            ("pcszClass", ctypes.c_wchar_p),
            ("oaifInFlags", wintypes.DWORD),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    dialog = shell32.SHOpenWithDialog
    dialog.argtypes = [wintypes.HWND, ctypes.POINTER(OPENASINFO)]
    dialog.restype = ctypes.c_long

    info = OPENASINFO()
    info.pcszFile = path
    info.pcszClass = None
    info.oaifInFlags = 0x4  # OAIF_EXEC: open the file with the chosen app
    hwnd = wintypes.HWND(int(parent_hwnd or 0))
    hr = dialog(hwnd, ctypes.byref(info))
    if hr == 0:
        return OpenPyResult()
    # ERROR_CANCELLED (1223) packed as an HRESULT.
    if (hr & 0xFFFFFFFF) in (0x800704C7, 1223):
        return OpenPyResult(cancelled=True)
    return OpenPyResult(message="The Open With dialog could not be shown.")


def _open_linux(path: str) -> OpenPyResult:
    desktop_id, command = _linux_default_command(path)
    if command_opens_in_editor(command) or (
        desktop_id and not _desktop_id_is_interpreter(desktop_id) and not command
    ):
        opened = _spawn_or_error(_linux_open_argv(path), "Could not open the file.")
        if opened.ok:
            return opened
    return _linux_open_with_dialog(path)


def _linux_open_argv(path: str) -> List[str]:
    if shutil.which("xdg-open"):
        return ["xdg-open", path]
    if shutil.which("gio"):
        return ["gio", "open", path]
    return []


def _linux_default_command(path: str) -> tuple:
    mime = _query_mime(path) or "text/x-python"
    desktop_id = _query_default_desktop(mime)
    if not desktop_id:
        for fallback in ("text/x-python", "text/x-python3", "application/x-python-code"):
            desktop_id = _query_default_desktop(fallback)
            if desktop_id:
                break
    if not desktop_id:
        return "", ""
    desktop_path = _find_desktop_file(desktop_id)
    if not desktop_path:
        return desktop_id, ""
    return desktop_id, _desktop_exec(desktop_path)


def _query_mime(path: str) -> str:
    if not shutil.which("xdg-mime"):
        return ""
    try:
        result = subprocess.run(
            ["xdg-mime", "query", "filetype", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip()


def _query_default_desktop(mime: str) -> str:
    if not mime or not shutil.which("xdg-mime"):
        return ""
    try:
        result = subprocess.run(
            ["xdg-mime", "query", "default", mime],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip()


def _data_dirs() -> List[str]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    extra = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [home] + [part for part in extra.split(":") if part]


def _find_desktop_file(desktop_id: str) -> str:
    name = desktop_id.strip().replace("\\", "/")
    if not name:
        return ""
    rel = name if "/" in name else os.path.join("applications", name)
    for root in _data_dirs():
        candidate = os.path.join(root, rel)
        if os.path.isfile(candidate):
            return candidate
    return ""


def _desktop_exec(path: str) -> str:
    in_entry = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    if in_entry:
                        break
                    in_entry = line.lower() == "[desktop entry]"
                    continue
                if in_entry and line.startswith("Exec="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def _desktop_id_is_interpreter(desktop_id: str) -> bool:
    name = os.path.basename(desktop_id.strip()).lower()
    if name.endswith(".desktop"):
        name = name[: -len(".desktop")]
    return _stem_is_interpreter(name)


def _linux_open_with_dialog(path: str) -> OpenPyResult:
    interpreters = []
    for candidate in ("/usr/bin/python3", "/usr/bin/python", shutil.which("python3"), sys.executable):
        if candidate and candidate not in interpreters and os.path.isfile(candidate):
            interpreters.append(candidate)
    if not interpreters:
        return OpenPyResult(message="No application is registered for .py files, and the app chooser could not be opened.")

    last_message = "The app chooser could not be opened."
    for interpreter in interpreters:
        try:
            result = subprocess.run(
                [interpreter, "-c", _GTK_APP_CHOOSER, path],
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_message = str(exc)
            continue
        if result.returncode == 0:
            return OpenPyResult()
        if result.returncode == 1:
            return OpenPyResult(cancelled=True)
        if result.returncode == 2:
            continue
        detail = (result.stderr or result.stdout or "").strip()
        last_message = detail or last_message
    return OpenPyResult(message=last_message)


def _spawn_or_error(argv: List[str], message: str) -> OpenPyResult:
    if not argv:
        return OpenPyResult(message=message)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return OpenPyResult(message=str(exc))
    if result.returncode == 0:
        return OpenPyResult()
    detail = (result.stderr or result.stdout or "").strip()
    return OpenPyResult(message=detail or message)


def _split_command(command: str) -> List[str]:
    tokens: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    for ch in (command or "").strip():
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _strip_env(tokens: List[str]) -> List[str]:
    if not tokens:
        return tokens
    if _exe_stem(tokens[0]) != "env":
        return tokens
    tokens = tokens[1:]
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    return tokens


def _exe_stem(token: str) -> str:
    return os.path.splitext(os.path.basename(token.strip().strip("\"'")))[0].lower()


def _stem_is_interpreter(stem: str) -> bool:
    if stem in {"py", "pyw", "python", "pythonw"}:
        return True
    if stem.startswith("python"):
        rest = stem[len("python"):]
        return rest == "" or rest[0] in "w0123456789."
    return False


_GTK_APP_CHOOSER = r"""
import sys
path = sys.argv[1]
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gio
except Exception:
    sys.exit(2)

Gtk.init([])
dialog = Gtk.AppChooserDialog.new_for_content_type(None, Gtk.DialogFlags.MODAL, "text/x-python")
dialog.set_title("Open with")
response = dialog.run()
try:
    if response != Gtk.ResponseType.OK:
        sys.exit(1)
    app = dialog.get_app_info()
    if app is None:
        sys.exit(3)
    launched = app.launch([Gio.File.new_for_path(path)], None)
    sys.exit(0 if launched else 3)
finally:
    dialog.destroy()
"""
