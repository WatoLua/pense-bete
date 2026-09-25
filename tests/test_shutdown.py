import os
import signal

import pytest

from conftest import posix_only
from pensebete.app import save_on_shutdown


class FakeWindow:
    def __init__(self):
        self.calls = []

    def save_all(self):
        self.calls.append("save_all")

    def save_session(self):
        self.calls.append("save_session")

    def quit_app(self):
        self.calls.append("quit_app")


@pytest.fixture
def restore_signals():
    handlers = {getattr(signal, name): signal.getsignal(getattr(signal, name))
                for name in ("SIGTERM", "SIGINT", "SIGHUP") if hasattr(signal, name)}
    yield
    for number, handler in handlers.items():
        signal.signal(number, handler)
    signal.set_wakeup_fd(-1)


# On Windows, os.kill with these signals terminates the process outright: nothing to test.
@posix_only
@pytest.mark.parametrize("name", ["SIGTERM", "SIGINT", "SIGHUP"])
def test_a_stop_signal_quits_the_usual_way(qtbot, qapp, restore_signals, name):
    window = FakeWindow()
    keep_alive = save_on_shutdown(qapp, window)

    os.kill(os.getpid(), getattr(signal, name))

    qtbot.waitUntil(lambda: window.calls == ["quit_app"], timeout=2000)
    del keep_alive

