import subprocess

import pytest

from pensebete import updates


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """An installation whose recorded commit is "abc"."""
    version = tmp_path / ".version"
    version.write_text("abc\n")
    monkeypatch.setattr(updates, "VERSION_FILE", version)
    monkeypatch.setattr(updates, "APP_DIR", tmp_path)
    return tmp_path


def test_an_update_is_available_when_the_repository_moved_on(installed):
    assert updates.update_available(lambda *args: completed("def\tHEAD\n"))


def test_no_update_for_the_installed_commit(installed):
    assert not updates.update_available(lambda *args: completed("abc\tHEAD\n"))


def test_an_unreachable_repository_raises(installed):
    with pytest.raises(RuntimeError, match="offline"):
        updates.update_available(lambda *args: completed(returncode=128, stderr="offline"))


def test_install_latest_runs_the_downloaded_installer(installed):
    calls = []

    def runner(*args):
        calls.append(args)
        return completed()

    updates.install_latest(runner)

    clone, install = calls
    assert clone[:2] == ("git", "clone") and clone[-2] == updates.REPO_URL
    assert install[0] == "bash" and install[1].endswith("install.sh")
    assert install[2:] == ("--yes", str(installed))


def test_a_failed_download_stops_the_update(installed):
    calls = []

    def runner(*args):
        calls.append(args)
        return completed(returncode=1, stderr="no network")

    with pytest.raises(RuntimeError, match="no network"):
        updates.install_latest(runner)
    assert len(calls) == 1


def test_a_clone_is_not_updated(installed):
    assert updates.can_update()
    (installed / ".git").mkdir()
    assert not updates.can_update()
