"""Compatibility shims for HAP-python runtime issues."""

from __future__ import annotations

import asyncio


class _NoopChildWatcher:
    def attach_loop(self, loop) -> None:
        return None


def install_child_watcher_compat() -> None:
    """Provide Python 3.14+ child-watcher names expected by HAP-python 5.

    HAP-python still calls the Unix child-watcher API during startup. That API
    was removed from asyncio in Python 3.14. This app does not launch
    subprocesses from the HAP loop, so a no-op watcher is enough.
    """

    if not hasattr(asyncio, "SafeChildWatcher"):
        asyncio.SafeChildWatcher = _NoopChildWatcher  # type: ignore[attr-defined]

    if not hasattr(asyncio, "set_child_watcher"):
        asyncio.set_child_watcher = lambda watcher: None  # type: ignore[attr-defined]

