"""Session-scoped temporary directories that are swept after a crash.

Decrypted database copies, recovered images, extracted voice clips, and
rendered pages are private chat data. They only ever live inside temporary
directories created here. Every directory records the process that owns it
(process id plus start time, so a recycled id is not mistaken for the owner),
so leftovers from a crashed or killed session can be removed the next time
the application starts instead of lingering in the system temp folder.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

WORKSPACE_PREFIX = "wce-"
OWNER_FILE = ".wce-owner"
# Directories without an owner marker come from releases before 0.3.8 (or were
# re-created after their session ended). They are only removed once nothing
# inside them has changed for this long, so a still-running older instance
# keeps its working files.
UNMARKED_GRACE_SECONDS = 6 * 60 * 60
# Name patterns used by releases before the owner marker existed.
_LEGACY_PATTERNS = ("wechat-memory-voice-*",)


class TemporaryWorkspace:
    """A temporary directory tagged with the identity of the process that owns it."""

    def __init__(self, prefix: str = WORKSPACE_PREFIX) -> None:
        if not prefix.startswith(WORKSPACE_PREFIX):
            raise ValueError(f"Workspace prefix must start with {WORKSPACE_PREFIX!r}")
        self._temp = tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True)
        self.path = Path(self._temp.name)
        (self.path / OWNER_FILE).write_text(_owner_marker(), encoding="ascii")

    def cleanup(self) -> None:
        self._temp.cleanup()

    def __enter__(self) -> "TemporaryWorkspace":
        return self

    def __exit__(self, *_args: object) -> None:
        self.cleanup()


def remove_stale_workspaces(root: Path | None = None) -> list[Path]:
    """Delete workspaces whose owning process is no longer running.

    Marked directories are removed as soon as their owner is gone. Unmarked
    directories are removed after ``UNMARKED_GRACE_SECONDS`` of inactivity.
    """
    base = root or Path(tempfile.gettempdir())
    removed: list[Path] = []
    try:
        candidates = list(base.glob(f"{WORKSPACE_PREFIX}*"))
        for pattern in _LEGACY_PATTERNS:
            candidates.extend(base.glob(pattern))
    except OSError:
        return removed
    now = time.time()
    for candidate in sorted(set(candidates)):
        if not candidate.is_dir() or not _is_stale(candidate, now):
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            removed.append(candidate)
    return removed


def _owner_marker() -> str:
    pid = os.getpid()
    start = _process_start_time(pid)
    return f"{pid} {start}" if start is not None else str(pid)


def _is_stale(directory: Path, now: float) -> bool:
    owner = _read_owner(directory)
    if owner is None:
        return now - _newest_mtime(directory) >= UNMARKED_GRACE_SECONDS
    return _is_stale_marker(*owner)


def _is_stale_marker(pid: int, start: int | None) -> bool:
    if start is not None:
        actual = _process_start_time(pid)
        if actual is not None and actual != start:
            return True  # The id was recycled by an unrelated process.
    if pid == os.getpid():
        return False
    return not _process_alive(pid)


def _read_owner(directory: Path) -> tuple[int, int | None] | None:
    try:
        fields = (directory / OWNER_FILE).read_text(encoding="ascii").split()
    except (OSError, UnicodeDecodeError):
        return None
    if not fields or not fields[0].isdigit():
        return None
    start = int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None
    return int(fields[0]), start


def _newest_mtime(directory: Path) -> float:
    newest = 0.0
    try:
        newest = directory.stat().st_mtime
        for path in directory.rglob("*"):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def _process_start_time(pid: int) -> int | None:
    """Return an opaque start-time token for ``pid``, or None when unavailable."""
    if pid <= 0 or os.name != "nt":
        return None
    return _windows_process_start_time(pid)


def _windows_kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


def _windows_open_process(kernel32, pid: int):
    import ctypes

    process_query_limited_information = 0x1000
    if not 0 < pid <= 0xFFFFFFFF:
        return None
    ctypes.set_last_error(0)
    return kernel32.OpenProcess(process_query_limited_information, False, pid) or None


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    error_access_denied = 5
    still_active = 259
    if not 0 < pid <= 0xFFFFFFFF:
        return False
    kernel32 = _windows_kernel32()
    handle = _windows_open_process(kernel32, pid)
    if handle is None:
        # A live process owned by another user cannot be opened at all.
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == still_active
        return True
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_start_time(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    handle = _windows_open_process(kernel32, pid)
    if handle is None:
        return None
    try:
        creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)
