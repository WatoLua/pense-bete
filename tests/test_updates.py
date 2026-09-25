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
    monkeypatch.setattr(updates, "RELEASE_FILE", tmp_path / ".release")
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
    source = updates.Path(clone[-1])
    assert list(install) == updates.installer(source, "yes", target=installed)


def test_the_installer_command_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "WINDOWS", False)

    assert updates.installer(tmp_path, "uninstall", "yes", "purge") == [
        "bash", str(tmp_path / "install.sh"), "--uninstall", "--yes", "--purge"]
    assert updates.installer(tmp_path, "yes", target=tmp_path / "app") == [
        "bash", str(tmp_path / "install.sh"), "--yes", str(tmp_path / "app")]


def test_the_installer_command_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "WINDOWS", True)

    command = updates.installer(tmp_path, "uninstall", "yes", "dev")
    assert command[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert command[5:] == [str(tmp_path / "install.ps1"), "-Uninstall", "-Yes", "-Dev"]
    assert updates.installer(tmp_path, "yes", target=tmp_path / "app")[-3:] == [
        "-Yes", "-Target", str(tmp_path / "app")]


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


def test_release_notes_are_the_message_of_an_annotated_tag(tagged_repo, monkeypatch):
    repo, _ = tagged_repo
    monkeypatch.setattr(updates, "REPO_URL", str(repo))

    assert updates.release_notes("v1.10.0") == "Release"
    assert updates.release_notes("v1.9.0") == ""  # lightweight: no message of its own
    assert updates.release_notes("v9.9.9") == ""  # missing: no notes, no failure


def test_the_installed_release_and_its_date(installed):
    (installed / ".release").write_text("v1.2.3\n")
    (installed / ".version").write_text("0123456789abcdef\n")

    version = updates.installed_version()

    assert (version.release, version.commit) == ("v1.2.3", "0123456")
    assert version.installed is not None and not version.branch


def test_a_clone_reports_its_branch_commit_and_changes(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "--quiet", "--initial-branch", "work")
    (tmp_path / "file").write_text("x")
    git("add", "file")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "c")
    monkeypatch.setattr(updates, "APP_DIR", tmp_path)

    version = updates.installed_version()
    assert (version.branch, len(version.commit), version.modified) == ("work", 7, False)

    (tmp_path / "file").write_text("changed")
    assert updates.installed_version().modified
