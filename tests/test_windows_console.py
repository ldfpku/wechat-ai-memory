from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from wechat_context_exporter.sources import wechat4_crypto, wechat4_key_capture
from wechat_context_exporter.sources.base import SourceError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows console helpers")


def test_helper_processes_never_open_console_windows(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert wechat4_key_capture._main_wechat_pid() is None
    wechat4_key_capture._stop_wechat()
    try:
        wechat4_key_capture.find_wechat_executable()
    except SourceError:
        pass  # WeChat is not installed on the test machine.
    assert wechat4_crypto._process_candidates("Weixin.exe") == []

    launched = {command[0].lower() for command, _ in calls}
    assert {"powershell", "taskkill", "tasklist"} <= launched
    for command, kwargs in calls:
        flags = int(kwargs.get("creationflags", 0))
        assert flags & subprocess.CREATE_NO_WINDOW, f"{command[0]} would flash a console window"
