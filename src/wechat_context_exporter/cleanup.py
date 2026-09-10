"""Best-effort removal of private data left on disk by earlier sessions."""

from __future__ import annotations

from .voice import remove_legacy_audio_cache
from .workspace import remove_stale_workspaces


def remove_private_leftovers() -> None:
    """Remove decrypted data that a crashed session or an older release left behind."""
    try:
        remove_stale_workspaces()
        remove_legacy_audio_cache()
    except Exception:  # Cleanup must never prevent the application from starting.
        pass
