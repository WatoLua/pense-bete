import io
import json
import subprocess
import zipfile

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
    assert updates.latest_release(lambda *args: completed(TAGS), use_git=True) == (
        "v1.2.10", "bbb", "")


def test_an_annotated_tag_stands_for_the_commit_it_points_to():
    listing = "tagobj\trefs/tags/v1.0.0\ncommit\trefs/tags/v1.0.0^{}\n"
    release = updates.latest_release(lambda *args: completed(listing), use_git=True)
    assert release[:2] == ("v1.0.0", "commit")


def test_a_repository_without_releases_has_no_update(installed):
    assert updates.latest_release(lambda *args: completed("ddd\trefs/tags/latest\n"),
                                  use_git=True) is None
    assert updates.update_available(lambda *args: completed("")) is None


def test_an_update_is_available_when_a_newer_release_exists(installed):
    assert updates.update_available(lambda *args: completed(TAGS)).tag == "v1.2.10"


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

    release = updates.Release("v1.2.10", "bbb")
    updates.install_release(release, runner)

    clone, install = calls
    assert clone[:2] == ("git", "clone")
    assert clone[clone.index("--branch") + 1] == "v1.2.10"
    assert clone[-2] == updates.REPO_URL
    source = updates.Path(clone[-1])
    assert list(install) == updates.installer(source, "yes", target=installed, release=release)


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
        updates.install_release(updates.Release("v1.0.0", "abc"), runner)
    assert len(calls) == 1


def test_releases_are_read_from_a_real_repository(tagged_repo, monkeypatch):
    repo, commits = tagged_repo
    monkeypatch.setattr(updates, "REPO_URL", str(repo))

    assert updates.latest_release()[:2] == ("v1.10.0", commits["v1.10.0"])


def test_a_clone_is_not_updated(installed):
    assert updates.can_update()
    (installed / ".git").mkdir()
    assert not updates.can_update()


def test_release_notes_are_the_message_of_an_annotated_tag(tagged_repo, monkeypatch):
    repo, _ = tagged_repo
    monkeypatch.setattr(updates, "REPO_URL", str(repo))

    assert updates.release_notes(updates.Release("v1.10.0", "")) == "Release"
    # Lightweight: no message of its own. Missing: no notes, no failure.
    assert updates.release_notes(updates.Release("v1.9.0", "")) == ""
    assert updates.release_notes(updates.Release("v9.9.9", "")) == ""


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


# Without git: the GitHub API, served here by a dictionary of URL -> response.
API = "https://api.github.com/repos/someone/pense-bete"


def fake_github(responses):
    def fetcher(url):
        if url not in responses:
            raise RuntimeError(f"{url}: 404")
        value = responses[url]
        return value if isinstance(value, bytes) else json.dumps(value).encode()
    return fetcher


def test_the_api_address_comes_from_a_github_url(monkeypatch):
    monkeypatch.delenv("PENSE_BETE_API", raising=False)
    for url in ("https://github.com/someone/pense-bete.git", "https://github.com/someone/pense-bete"):
        monkeypatch.setattr(updates, "REPO_URL", url)
        assert updates.github_api() == API
    monkeypatch.setattr(updates, "REPO_URL", "https://gitlab.com/someone/pense-bete.git")
    assert updates.github_api() == ""


def test_without_git_the_newest_release_comes_from_the_api(monkeypatch):
    monkeypatch.setattr(updates, "REPO_URL", "https://github.com/someone/pense-bete.git")
    fetcher = fake_github({f"{API}/tags?per_page=100": [
        {"name": "v1.9.0", "commit": {"sha": "old"}, "zipball_url": "zip/v1.9.0"},
        {"name": "v1.10.0", "commit": {"sha": "new"}, "zipball_url": "zip/v1.10.0"},
        {"name": "v2.0.0-rc1", "commit": {"sha": "rc"}, "zipball_url": "zip/rc"},
    ]})

    assert updates.latest_release(fetcher=fetcher, use_git=False) == (
        "v1.10.0", "new", "zip/v1.10.0")


def test_without_git_a_repository_off_github_cannot_update(monkeypatch):
    monkeypatch.setattr(updates, "REPO_URL", "/srv/git/pense-bete.git")
    with pytest.raises(RuntimeError, match="git"):
        updates.latest_release(use_git=False)


def test_without_git_the_release_notes_come_from_the_api(monkeypatch):
    monkeypatch.setattr(updates, "REPO_URL", "https://github.com/someone/pense-bete.git")
    fetcher = fake_github({
        f"{API}/git/refs/tags/v1.0.0": {"object": {"type": "tag", "sha": "t1"}},
        f"{API}/git/tags/t1": {"message": "Search and sort\n"},
        f"{API}/git/refs/tags/v0.9.0": {"object": {"type": "commit", "sha": "c1"}},
    })

    assert updates.release_notes(updates.Release("v1.0.0", "c", "zip"), fetcher=fetcher) == \
        "Search and sort"
    assert updates.release_notes(updates.Release("v0.9.0", "c", "zip"), fetcher=fetcher) == ""
    assert updates.release_notes(updates.Release("v9.9.9", "c", "zip"), fetcher=fetcher) == ""


def zip_of(files: dict[str, str], top="someone-pense-bete-1a2b3c4") -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, text in files.items():
            archive.writestr(f"{top}/{name}", text)
    return data.getvalue()


def test_without_git_a_release_is_downloaded_and_installed_with_its_commit(installed):
    calls = []

    def runner(*args):
        calls.append(args)
        script = next(arg for arg in args if arg.endswith(("install.sh", "install.ps1")))
        assert (updates.Path(script).parent / "pensebete" / "app.py").read_text() == "app"
        return completed()
    release = updates.Release("v1.10.0", "new", "https://example.com/zip")
    fetcher = fake_github({release.archive: zip_of({"install.sh": "", "pensebete/app.py": "app"})})

    updates.install_release(release, runner, fetcher)

    [install] = calls
    script = next(arg for arg in install if arg.endswith(("install.sh", "install.ps1")))
    assert list(install) == updates.installer(updates.Path(script).parent, "yes",
                                              target=installed, release=release)


def test_an_archive_that_climbs_out_is_refused(installed):
    release = updates.Release("v1.0.0", "c", "https://example.com/zip")
    fetcher = fake_github({release.archive: zip_of({"../evil": "x"})})

    with pytest.raises(RuntimeError):
        updates.install_release(release, lambda *args: completed(), fetcher)


def test_the_standalone_build_is_found_among_the_release_assets(monkeypatch):
    monkeypatch.setattr(updates, "REPO_URL", "https://github.com/someone/pense-bete.git")
    release = updates.Release("v1.0.0", "c")
    fetcher = fake_github({f"{API}/releases/tags/v1.0.0": {"assets": [
        {"name": "other.zip", "browser_download_url": "other"},
        {"name": "pense-bete-windows.zip", "browser_download_url": "the-build"}]}})

    assert updates.bundle_url(release, fetcher) == "the-build"
    with pytest.raises(RuntimeError, match="v2.0.0"):  # not built yet
        updates.bundle_url(updates.Release("v2.0.0", "c"), fetcher)


def test_an_update_of_the_standalone_build_is_unpacked_for_the_installer(monkeypatch):
    monkeypatch.setattr(updates, "REPO_URL", "https://github.com/someone/pense-bete.git")
    release = updates.Release("v1.0.0", "c")
    fetcher = fake_github({
        f"{API}/releases/tags/v1.0.0": {"assets": [
            {"name": "pense-bete-windows.zip", "browser_download_url": "the-build"}]},
        "the-build": zip_of({"Pense-bete.exe": "exe", "install.ps1": ""}, top="Pense-bete"),
    })

    staged = updates.stage_update(release, fetcher)

    assert (staged / "Pense-bete.exe").read_text() == "exe"
    updates.remove_tree(staged.parent)


def test_the_installer_can_wait_for_the_application_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "WINDOWS", True)

    command = updates.installer(tmp_path, "yes", "launch", target=tmp_path / "app", wait_pid=42)

    assert command[-5:] == ["-Launch", "-Waitpid", "42", "-Target", str(tmp_path / "app")]


def test_the_hand_over_runs_on_without_a_window(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(updates, "HANDOVER_LOG", tmp_path / "install.log")
    monkeypatch.setattr(updates.subprocess, "Popen", lambda command, **options: started.append(
        (command, options)))

    updates.hand_over(["powershell", "-File", "install.ps1"])

    [(command, options)] = started
    assert command == ["powershell", "-File", "install.ps1"]
    assert options["stdin"] == updates.subprocess.DEVNULL
