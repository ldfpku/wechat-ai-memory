from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from wechat_context_exporter import workspace
from wechat_context_exporter.workspace import (
    OWNER_FILE,
    UNMARKED_GRACE_SECONDS,
    TemporaryWorkspace,
    remove_stale_workspaces,
)


def _age(path, seconds: float) -> None:
    stamp = time.time() - seconds
    for item in [path, *path.rglob("*")]:
        os.utime(item, (stamp, stamp))


def test_workspace_records_owner_and_is_removed_on_cleanup() -> None:
    with TemporaryWorkspace("wce-test-") as active:
        assert active.path.is_dir()
        marker = (active.path / OWNER_FILE).read_text(encoding="ascii").split()
        assert marker[0] == str(os.getpid())
        if os.name == "nt":
            assert marker[1] == str(workspace._process_start_time(os.getpid()))
        (active.path / "message.db").write_bytes(b"decrypted")
    assert not active.path.exists()


def test_workspace_prefix_must_be_recognisable() -> None:
    with pytest.raises(ValueError):
        TemporaryWorkspace("other-")


def test_stale_sweep_keeps_live_sessions_and_removes_leftovers(tmp_path) -> None:
    live = tmp_path / "wce-db-live0001"
    live.mkdir()
    (live / OWNER_FILE).write_text(workspace._owner_marker(), encoding="ascii")
    (live / "message.db").write_bytes(b"in use")
    live_pid_only = tmp_path / "wce-image-live0002"
    live_pid_only.mkdir()
    (live_pid_only / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    dead = tmp_path / "wce-image-dead0001"
    dead.mkdir()
    (dead / OWNER_FILE).write_text("4000000000", encoding="ascii")
    (dead / "photo.jpg").write_bytes(b"leftover")
    recycled = tmp_path / "wce-voice-recycled1"
    recycled.mkdir()
    (recycled / OWNER_FILE).write_text(f"{os.getpid()} 1", encoding="ascii")
    unmarked_recent = tmp_path / "wce-wechat4-abcd1234"
    unmarked_recent.mkdir()
    (unmarked_recent / "contact.db").write_bytes(b"older release, still running")
    unmarked_old = tmp_path / "wce-images-abcd1234"
    unmarked_old.mkdir()
    (unmarked_old / "photo.jpg").write_bytes(b"older release, crashed")
    _age(unmarked_old, UNMARKED_GRACE_SECONDS + 60)
    legacy_wav = tmp_path / "wechat-memory-voice-abcd1234"
    legacy_wav.mkdir()
    _age(legacy_wav, UNMARKED_GRACE_SECONDS + 60)
    corrupt = tmp_path / "wce-render-corrupt01"
    corrupt.mkdir()
    (corrupt / OWNER_FILE).write_text("not a pid", encoding="ascii")
    _age(corrupt, UNMARKED_GRACE_SECONDS + 60)
    other = tmp_path / "other-abcd1234"
    other.mkdir()
    _age(other, UNMARKED_GRACE_SECONDS + 60)
    stray_file = tmp_path / "wce-file"
    stray_file.write_text("x", encoding="ascii")

    removed = remove_stale_workspaces(tmp_path)

    if os.name == "nt":
        assert set(removed) == {dead, unmarked_old, legacy_wav, corrupt, recycled}
    else:
        assert set(removed) == {dead, unmarked_old, legacy_wav, corrupt}
    assert live.is_dir() and (live / "message.db").is_file()
    assert live_pid_only.is_dir()
    assert unmarked_recent.is_dir() and (unmarked_recent / "contact.db").is_file()
    assert other.is_dir()
    assert stray_file.is_file()


def test_unmarked_workspace_stays_while_files_inside_are_still_changing(tmp_path) -> None:
    active = tmp_path / "wce-wechat4-zzzz0000"
    active.mkdir()
    (active / "decrypted").mkdir()
    _age(active, UNMARKED_GRACE_SECONDS + 60)
    (active / "decrypted" / "message_0.db").write_bytes(b"fresh")

    assert remove_stale_workspaces(tmp_path) == []
    assert active.is_dir()


def test_stale_sweep_defaults_to_the_system_temp_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workspace.tempfile, "gettempdir", lambda: str(tmp_path))
    leftover = tmp_path / "wce-render-zzzz0000"
    leftover.mkdir()
    (leftover / OWNER_FILE).write_text("4000000000", encoding="ascii")

    assert remove_stale_workspaces() == [leftover]
    assert not leftover.exists()


def test_process_identity_is_checked_against_real_processes() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert workspace._process_alive(child.pid)
        start = workspace._process_start_time(child.pid)
        if os.name == "nt":
            assert start is not None
            assert workspace._process_start_time(child.pid) == start
            assert not workspace._is_stale_marker(child.pid, start)
            assert workspace._is_stale_marker(child.pid, start + 1)
    finally:
        child.kill()
        child.wait()
    assert not workspace._process_alive(child.pid)
    assert workspace._is_stale_marker(child.pid, start)
    assert not workspace._process_alive(4_000_000_000)
    assert not workspace._process_alive(2**40)
    assert workspace._process_start_time(2**40) is None
    assert not workspace._process_alive(0)
