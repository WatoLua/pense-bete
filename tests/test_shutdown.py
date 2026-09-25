import os
import signal

import pytest

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
    handlers = {number: signal.getsignal(number)
                for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    yield
    for number, handler in handlers.items():
        signal.signal(number, handler)
    signal.set_wakeup_fd(-1)


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_a_stop_signal_quits_the_usual_way(qtbot, qapp, restore_signals, number):
    window = FakeWindow()
    keep_alive = save_on_shutdown(qapp, window)

    os.kill(os.getpid(), number)

    qtbot.waitUntil(lambda: window.calls == ["quit_app"], timeout=2000)
    del keep_alive

