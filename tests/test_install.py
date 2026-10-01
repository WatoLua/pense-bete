"""install.sh, run from this repository into a throwaway HOME."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_DIR, posix_only

pytestmark = posix_only


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def install_sh(home, *args, repo=None, piped=False, path=None, api=None):
    """Run install.sh from this repository, or as `curl ... | bash` does when piped."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XDG_", "PENSE_BETE_"))}
    env["HOME"] = str(home)
    if repo is not None:
        env["PENSE_BETE_REPO"] = str(repo)
    if path is not None:
        env["PATH"] = path
    if api is not None:
        env["PENSE_BETE_API"] = api
    script = REPO_DIR / "install.sh"
    if piped:
        result = subprocess.run(["bash", "-s", "--", "--yes", *args], env=env,
                                input=script.read_text(), capture_output=True, text=True)
    else:
        result = subprocess.run(["bash", str(script), "--yes", *args], env=env,
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stderr
    return result


def desktop_file(home, app_id="pense-bete"):
    return home / ".local" / "share" / "applications" / f"{app_id}.desktop"


def make_note(data_dir: Path, note_id="a"):
    (data_dir / note_id).mkdir(parents=True)
    (data_dir / note_id / "note.json").write_text("{}")


def test_install_copies_the_application_and_registers_it(home):
    target = home / "apps" / "pense-bete"

    install_sh(home, str(target))

    assert (target / "pense_bete.py").is_file()
    assert (target / "pensebete" / "app.py").is_file()
    assert os.access(target / "pense-bete", os.X_OK)
    head = subprocess.run(["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert (target / ".version").read_text().strip() == head
    entry = desktop_file(home).read_text()
    assert f"Exec={target}/pense-bete" in entry
    assert "Name=Pense-bête\n" in entry
    assert (home / ".local" / "bin" / "pense-bete").resolve() == target / "pense-bete"


def test_install_uses_the_default_directory(home):
    install_sh(home)

    assert (home / ".local" / "opt" / "pense-bete" / "pense_bete.py").is_file()


def test_reinstalling_drops_modules_the_repository_no_longer_has(home):
    target = home / "app"
    install_sh(home, str(target))
    (target / "pensebete" / "stale.py").write_text("")

    install_sh(home, str(target))

    assert not (target / "pensebete" / "stale.py").exists()


def test_uninstall_keeps_the_notes_by_default(home):
    install_sh(home)
    data_dir = home / ".local" / "share" / "pense-bete"
    make_note(data_dir)

    install_sh(home, "--uninstall")

    assert not (home / ".local" / "opt" / "pense-bete").exists()
    assert not desktop_file(home).exists()
    assert not (home / ".local" / "bin" / "pense-bete").is_symlink()
    assert (data_dir / "a" / "note.json").exists()


def test_purge_deletes_only_what_the_application_wrote(home):
    install_sh(home)
    data_dir = home / ".local" / "share" / "pense-bete"
    make_note(data_dir)
    (data_dir / "unrelated.txt").write_text("keep me")
    config_dir = home / ".config" / "pense-bete"
    config_dir.mkdir(parents=True)
    (config_dir / "session.json").write_text("{}")

    install_sh(home, "--uninstall", "--purge")

    assert not (data_dir / "a").exists()
    assert (data_dir / "unrelated.txt").read_text() == "keep me"
    assert not config_dir.exists()


def test_uninstall_stops_the_start_with_the_session(home):
    install_sh(home)
    autostart = home / ".config" / "autostart"
    autostart.mkdir(parents=True)
    (autostart / "pense-bete.desktop").write_text("[Desktop Entry]\n")
    (autostart / "other.desktop").write_text("[Desktop Entry]\n")

    install_sh(home, "--uninstall")

    assert not (autostart / "pense-bete.desktop").exists()
    assert (autostart / "other.desktop").exists()


def test_purge_deletes_the_notes_in_the_folder_chosen(home):
    install_sh(home)
    chosen = home / "Documents" / "my notes"
    make_note(chosen)
    (chosen / "unrelated.txt").write_text("keep me")
    config_dir = home / ".config" / "pense-bete"
    config_dir.mkdir(parents=True)
    (config_dir / "session.json").write_text(json.dumps({"data_dir": str(chosen)}))

    install_sh(home, "--uninstall", "--purge")

    assert not (chosen / "a").exists()
    assert (chosen / "unrelated.txt").exists()


def test_the_development_entry_runs_the_clone_and_uninstalling_keeps_it(home):
    install_sh(home, "--dev")

    entry = desktop_file(home, "pense-bete-dev").read_text()
    assert f"Exec={REPO_DIR}/pense-bete" in entry
    assert "Name=Pense-bête (dev)" in entry
    assert f"Icon={REPO_DIR}/icon-dev.svg" in entry
    assert not desktop_file(home).exists()

    install_sh(home, "--uninstall", "--dev")

    assert not desktop_file(home, "pense-bete-dev").exists()
    assert (REPO_DIR / "pense_bete.py").exists()


def test_the_standalone_installer_installs_the_newest_release(home, tagged_repo):
    repo, commits = tagged_repo
    target = home / "app"

    result = install_sh(home, str(target), "--with-python", repo=repo, piped=True)

    assert "v1.10.0" in result.stdout
    assert (target / ".version").read_text().strip() == commits["v1.10.0"]
    assert (target / ".release").read_text().strip() == "v1.10.0"
    assert (target / "LICENSE").is_file()
    assert (target / "pensebete" / "app.py").is_file()


def test_the_standalone_installer_falls_back_to_the_latest_commit(home, tmp_path):
    repo = tmp_path / "untagged.git"
    subprocess.run(["git", "clone", "--quiet", "--bare", "--no-local", str(REPO_DIR), str(repo)],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "tag", "-d", *subprocess.run(
        ["git", "-C", str(repo), "tag"], capture_output=True, text=True).stdout.split()],
        capture_output=True)
    target = home / "app"

    result = install_sh(home, str(target), "--with-python", repo=repo, piped=True)

    assert "no release" in result.stderr
    assert (target / "pense_bete.py").is_file()
    assert not (target / ".release").exists()  # not a release: no version to show


def test_the_commit_and_release_given_are_recorded(home):
    target = home / "app"

    install_sh(home, str(target), "--commit=abc123", "--release=v9.9.9")

    assert (target / ".version").read_text().strip() == "abc123"
    assert (target / ".release").read_text().strip() == "v9.9.9"


def test_without_git_the_standalone_installer_downloads_the_newest_release(
        home, no_git_path, fake_github):
    api, commit = fake_github
    target = home / "app"

    result = install_sh(home, str(target), "--with-python", piped=True, path=no_git_path,
                        api=api)

    assert "git" in result.stderr  # warned that notes will have no history
    assert "v1.10.0" in result.stdout
    assert (target / "pensebete" / "app.py").is_file()
    assert (target / ".version").read_text().strip() == commit
    assert (target / ".release").read_text().strip() == "v1.10.0"


def test_without_git_a_repository_off_github_cannot_be_downloaded(home, no_git_path):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XDG_", "PENSE_BETE_"))}
    env.update(HOME=str(home), PATH=no_git_path, PENSE_BETE_REPO="/srv/git/pense-bete.git")

    def piped(*args):
        return subprocess.run(["bash", "-s", "--", "--yes", *args, str(home / "app")], env=env,
                              input=(REPO_DIR / "install.sh").read_text(),
                              capture_output=True, text=True)

    result = piped("--with-python")
    assert result.returncode != 0
    assert "needs git" in result.stderr
    result = piped()  # the standalone version is only published on GitHub
    assert result.returncode != 0
    assert "--with-python" in result.stderr


def test_the_standalone_version_is_installed_by_default(home, fake_github):
    api, commit = fake_github
    target = home / "app"

    result = install_sh(home, str(target), piped=True, api=api)

    assert "v1.10.0" in result.stdout
    assert os.access(target / "pense-bete", os.X_OK)
    assert (target / "_internal" / "libpython3.12.so.1.0").is_file()
    assert not (target / "pense_bete.py").exists()
    assert (target / ".version").read_text().strip() == commit  # carried by the build
    assert (target / ".release").read_text().strip() == "v1.10.0"
    assert f"Exec={target}/pense-bete" in desktop_file(home).read_text()
    assert (home / ".local" / "bin" / "pense-bete").resolve() == target / "pense-bete"


@pytest.fixture
def linux_bundle(tmp_path):
    """A standalone build unpacked, as an update hands it over to its installer."""
    from conftest import fake_linux_bundle_files
    directory = tmp_path / "staged" / "Pense-bete"
    for name, (data, mode) in fake_linux_bundle_files().items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
        (directory / name).chmod(mode)
    return directory


def run_bundle_installer(home, bundle, *args):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XDG_", "PENSE_BETE_"))}
    env["HOME"] = str(home)
    result = subprocess.run(["bash", str(bundle / "install.sh"), "--yes", *args], env=env,
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stderr
    return result


def test_a_standalone_build_replaces_an_installation_with_python(home, linux_bundle):
    target = home / "app"
    install_sh(home, str(target))
    assert (target / "pense_bete.py").exists()

    run_bundle_installer(home, linux_bundle, "--commit=abc", "--release=v1.2.3", str(target))

    assert not (target / "pense_bete.py").exists() and not (target / "pensebete").exists()
    assert os.access(target / "pense-bete", os.X_OK)
    assert (target / ".version").read_text().strip() == "abc"  # what is given wins
    assert (target / ".release").read_text().strip() == "v1.2.3"


def test_an_update_waits_for_the_application_then_cleans_up_and_relaunches(home,
                                                                           linux_bundle):
    import sys
    import time
    target = home / "app"
    running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    started = time.monotonic()

    run_bundle_installer(home, linux_bundle, f"--waitpid={running.pid}", "--launch",
                         "--removesource", str(target))

    assert time.monotonic() - started >= 2  # it waited for the process to end
    running.wait()
    assert os.access(target / "pense-bete", os.X_OK)
    assert not linux_bundle.exists()  # the unpacked download is gone
    deadline = time.monotonic() + 5
    while not (home / "launched").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (home / "launched").exists()


def test_a_standalone_installation_is_uninstalled(home, linux_bundle):
    target = home / "app"
    run_bundle_installer(home, linux_bundle, str(target))

    run_bundle_installer(home, target, "--uninstall")

    assert not target.exists()
    assert not desktop_file(home).exists()
