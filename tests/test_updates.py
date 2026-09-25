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


TAGS = (
    "aaa\trefs/tags/v1.2.9\n"
    "bbb\trefs/tags/v1.2.10\n"
    "ccc\trefs/tags/v1.3.0-beta\n"
    "ddd\trefs/tags/latest\n"
)


def test_the_newest_release_is_compared_by_number():
    assert updates.latest_release(lambda *args: completed(TAGS)) == ("v1.2.10", "bbb")


def test_an_annotated_tag_stands_for_the_commit_it_points_to():
    listing = "tagobj\trefs/tags/v1.0.0\ncommit\trefs/tags/v1.0.0^{}\n"
    assert updates.latest_release(lambda *args: completed(listing)) == ("v1.0.0", "commit")


def test_a_repository_without_releases_has_no_update(installed):
    assert updates.latest_release(lambda *args: completed("ddd\trefs/tags/latest\n")) is None
    assert updates.update_available(lambda *args: completed("")) is None


def test_an_update_is_available_when_a_newer_release_exists(installed):
    assert updates.update_available(lambda *args: completed(TAGS)) == "v1.2.10"


def test_no_update_when_the_newest_release_is_installed(installed):
    (installed / ".version").write_text("bbb\n")
    assert updates.update_available(lambda *args: completed(TAGS)) is None


def test_an_unreachable_repository_raises(installed):
    with pytest.raises(RuntimeError, match="offline"):
        updates.update_available(lambda *args: completed(returncode=128, stderr="offline"))


def test_install_release_installs_that_tag(installed):
    calls = []

    def runner(*args):
        calls.append(args)
        return completed()

    updates.install_release("v1.2.10", runner)

    clone, install = calls
    assert clone[:2] == ("git", "clone")
    assert clone[clone.index("--branch") + 1] == "v1.2.10"
    assert clone[-2] == updates.REPO_URL
    assert install[0] == "bash" and install[1].endswith("install.sh")
    assert install[2:] == ("--yes", str(installed))


def test_a_failed_download_stops_the_update(installed):
    calls = []

    def runner(*args):
        calls.append(args)
        return completed(returncode=1, stderr="no network")

    with pytest.raises(RuntimeError, match="no network"):
        updates.install_release("v1.0.0", runner)
    assert len(calls) == 1


def test_releases_are_read_from_a_real_repository(tagged_repo, monkeypatch):
    repo, commits = tagged_repo
    monkeypatch.setattr(updates, "REPO_URL", str(repo))

    assert updates.latest_release() == ("v1.10.0", commits["v1.10.0"])


def test_a_clone_is_not_updated(installed):
    assert updates.can_update()
    (installed / ".git").mkdir()
    assert not updates.can_update()
