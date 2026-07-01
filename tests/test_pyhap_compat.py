import asyncio

from hap_daikin_ac.pyhap_compat import install_child_watcher_compat


def test_install_child_watcher_compat_adds_missing_asyncio_api(
    monkeypatch,
) -> None:
    monkeypatch.delattr(asyncio, "SafeChildWatcher", raising=False)
    monkeypatch.delattr(asyncio, "set_child_watcher", raising=False)

    install_child_watcher_compat()

    watcher = asyncio.SafeChildWatcher()
    watcher.attach_loop(None)
    asyncio.set_child_watcher(watcher)
