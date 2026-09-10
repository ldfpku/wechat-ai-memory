"""Session-scoped temporary directories that are swept after a crash.

Decrypted database copies, recovered images, extracted voice clips, and
rendered pages are private chat data. They only ever live inside temporary
directories created here. Every directory records the process that owns it,
so leftovers from a crashed or killed session can be removed the next time
the application starts instead of lingering in the system temp folder.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

WORKSPACE_PREFIX = "wce-"
OWNER_FILE = ".wce-owner"
# Name patterns used by releases before the owner marker existed.
_LEGACY_PATTERNS = ("wechat-memory-voice-*",)


class TemporaryWorkspace:
    """A temporary directory tagged with the id of the process that owns it."""

    def __init__(self, prefix: str = WORKSPACE_PREFIX) -> None:
        if not prefix.startswith(WORKSPACE_PREFIX):
            raise ValueError(f"Workspace prefix must start with {WORKSPACE_PREFIX!r}")
        self._temp = tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True)
        self.path = Path(self._temp.name)
        (self.path / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")

    def cleanup(self) -> None:
        self._temp.cleanup()

    def __enter__(self) -> "TemporaryWorkspace":
        return self

    def __exit__(self, *_args: object) -> None:
        self.cleanup()


def remove_stale_workspaces(root: Path | None = None) -> list[Path]:
    """Delete workspaces whose owning process is no longer running.

    Directories without an owner marker were created by an older release or
    were re-created after their session ended; they are removed as well.
    """
    base = root or Path(tempfile.gettempdir())
    removed: list[Path] = []
    try:
        candidates = list(base.glob(f"{WORKSPACE_PREFIX}*"))
        for pattern in _LEGACY_PATTERNS:
            candidates.extend(base.glob(pattern))
    except OSError:
        return removed
    for candidate in sorted(set(candidates)):
        if not candidate.is_dir() or not _is_stale(candidate):
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            removed.append(candidate)
    return removed


def _is_stale(directory: Path) -> bool:
    owner = _owner_pid(directory)
    if owner is None:
        return True
    if owner == os.getpid():
        return False
    return not _process_alive(owner)


def _owner_pid(directory: Path) -> int | None:
    try:
        value = (directory / OWNER_FILE).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(value) if value.isdigit() else None


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


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    if pid > 0xFFFFFFFF:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # A live process owned by another user cannot be opened at all.
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == still_active
        return True
    finally:
        kernel32.CloseHandle(handle)
