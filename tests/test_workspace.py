from __future__ import annotations

import os
import subprocess
import sys

import pytest

from wechat_context_exporter import workspace
from wechat_context_exporter.workspace import OWNER_FILE, TemporaryWorkspace, remove_stale_workspaces


def test_workspace_records_owner_and_is_removed_on_cleanup() -> None:
    with TemporaryWorkspace("wce-test-") as active:
        assert active.path.is_dir()
        assert (active.path / OWNER_FILE).read_text(encoding="ascii") == str(os.getpid())
        (active.path / "message.db").write_bytes(b"decrypted")
    assert not active.path.exists()


def test_workspace_prefix_must_be_recognisable() -> None:
    with pytest.raises(ValueError):
        TemporaryWorkspace("other-")


def test_stale_sweep_keeps_live_sessions_and_removes_leftovers(tmp_path) -> None:
    live = tmp_path / "wce-db-live0001"
    live.mkdir()
    (live / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    (live / "message.db").write_bytes(b"in use")
    dead = tmp_path / "wce-image-dead0001"
    dead.mkdir()
    (dead / OWNER_FILE).write_text("4000000000", encoding="ascii")
    (dead / "photo.jpg").write_bytes(b"leftover")
    unmarked = tmp_path / "wce-wechat4-abcd1234"
    unmarked.mkdir()
    (unmarked / "contact.db").write_bytes(b"leftover")
    legacy_wav = tmp_path / "wechat-memory-voice-abcd1234"
    legacy_wav.mkdir()
    corrupt = tmp_path / "wce-voice-corrupt01"
    corrupt.mkdir()
    (corrupt / OWNER_FILE).write_text("not a pid", encoding="ascii")
    other = tmp_path / "other-abcd1234"
    other.mkdir()
    stray_file = tmp_path / "wce-file"
    stray_file.write_text("x", encoding="ascii")

    removed = remove_stale_workspaces(tmp_path)

    assert set(removed) == {dead, unmarked, legacy_wav, corrupt}
    assert live.is_dir() and (live / "message.db").is_file()
    assert other.is_dir()
    assert stray_file.is_file()


def test_stale_sweep_defaults_to_the_system_temp_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workspace.tempfile, "gettempdir", lambda: str(tmp_path))
    leftover = tmp_path / "wce-render-zzzz0000"
    leftover.mkdir()

    assert remove_stale_workspaces() == [leftover]
    assert not leftover.exists()


def test_process_liveness_is_checked_against_real_processes() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert workspace._process_alive(child.pid)
    finally:
        child.kill()
        child.wait()
    assert not workspace._process_alive(child.pid)
    assert not workspace._process_alive(4_000_000_000)
    assert not workspace._process_alive(0)
