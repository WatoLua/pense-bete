"""install.ps1, run from this repository into a throwaway profile: Windows only."""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_DIR, windows_only

pytestmark = windows_only


@pytest.fixture
def profile(tmp_path):
    """Where install.ps1 puts things: %APPDATA%, %LOCALAPPDATA% and the Start menu."""
    places = {"APPDATA": tmp_path / "Roaming", "LOCALAPPDATA": tmp_path / "Local",
              "PENSE_BETE_SHORTCUT_DIR": tmp_path / "Start Menu"}
    for path in places.values():
        path.mkdir()
    return places


def install_ps1(profile, *args, repo=None, piped=False, path=None, api=None):
    """Run install.ps1 from this repository, or as `irm ... | iex` does when piped."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PENSE_BETE_")}
    env.update({key: str(path) for key, path in profile.items()})
    if repo is not None:
        env["PENSE_BETE_REPO"] = str(repo)
    if path is not None:
        env["PATH"] = path
    if api is not None:
        env["PENSE_BETE_API"] = api
    script = REPO_DIR / "install.ps1"
    if piped:
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   f"Get-Content -Raw -LiteralPath '{script}' | Invoke-Expression"]
    else:
        command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(script), "-Yes", *args]
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def shortcut(profile, name="Pense-bête"):
    return profile["PENSE_BETE_SHORTCUT_DIR"] / f"{name}.lnk"


def read_shortcut(path: Path) -> dict:
    """The shortcut's target, arguments, icon and AppUserModelID, as Windows reads them."""
    script = (
        f"$link = (New-Object -ComObject WScript.Shell).CreateShortcut('{path}');"
        f"$folder = (New-Object -ComObject Shell.Application).Namespace('{path.parent}');"
        f"$item = $folder.ParseName('{path.name}');"
        "$link.TargetPath; $link.Arguments; $link.IconLocation;"
        "$item.ExtendedProperty('System.AppUserModel.ID')"
    )
    output = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, check=True).stdout.splitlines()
    return dict(zip(("target", "arguments", "icon", "app_id"), output + [""] * 4))


def make_note(data_dir: Path, note_id="a"):
    (data_dir / note_id).mkdir(parents=True)
    (data_dir / note_id / "note.json").write_text("{}")


def test_install_copies_the_application_and_adds_it_to_the_start_menu(profile, tmp_path):
    target = tmp_path / "apps" / "pense-bete"

    install_ps1(profile, "-Target", str(target))

    assert (target / "pense_bete.py").is_file()
    assert (target / "pensebete" / "app.py").is_file()
    assert (target / "icon.ico").is_file() and (target / "LICENSE").is_file()
    head = subprocess.run(["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert (target / ".version").read_text().strip() == head
    link = read_shortcut(shortcut(profile))
    assert link["target"].lower().endswith("pythonw.exe")
    assert link["arguments"] == f'"{target}\\pense_bete.py"'
    assert link["icon"].startswith(f"{target}\\icon.ico")
    assert link["app_id"] == "pense-bete"


def test_install_uses_the_default_directory(profile):
    install_ps1(profile)

    assert (profile["LOCALAPPDATA"] / "Programs" / "pense-bete" / "pense_bete.py").is_file()


def test_reinstalling_drops_modules_the_repository_no_longer_has(profile, tmp_path):
    target = tmp_path / "app"
    install_ps1(profile, "-Target", str(target))
    (target / "pensebete" / "stale.py").write_text("")

    install_ps1(profile, "-Target", str(target))

    assert not (target / "pensebete" / "stale.py").exists()


def test_uninstall_keeps_the_notes_by_default(profile):
    install_ps1(profile)
    data_dir = profile["APPDATA"] / "pense-bete" / "notes"
    make_note(data_dir)

    install_ps1(profile, "-Uninstall")

    assert not (profile["LOCALAPPDATA"] / "Programs" / "pense-bete").exists()
    assert not shortcut(profile).exists()
    assert (data_dir / "a" / "note.json").exists()


def test_purge_deletes_only_what_the_application_wrote(profile):
    install_ps1(profile)
    app_data = profile["APPDATA"] / "pense-bete"
    make_note(app_data / "notes")
    (app_data / "notes" / "unrelated.txt").write_text("keep me")
    (app_data / "session.json").write_text("{}")

    install_ps1(profile, "-Uninstall", "-Purge")

    assert not (app_data / "notes" / "a").exists()
    assert (app_data / "notes" / "unrelated.txt").read_text() == "keep me"
    assert not (app_data / "session.json").exists()


def test_the_development_entry_runs_the_clone_and_uninstalling_keeps_it(profile):
    install_ps1(profile, "-Dev")

    link = read_shortcut(shortcut(profile, "Pense-bête (dev)"))
    assert link["arguments"] == f'"{REPO_DIR}\\pense_bete.py"'
    assert link["icon"].startswith(f"{REPO_DIR}\\icon-dev.ico")
    assert link["app_id"] == "pense-bete-dev"
    assert not shortcut(profile).exists()

    install_ps1(profile, "-Uninstall", "-Dev")

    assert not shortcut(profile, "Pense-bête (dev)").exists()
    assert (REPO_DIR / "pense_bete.py").exists()


def test_the_standalone_installer_installs_the_newest_release(profile, tagged_repo):
    repo, commits = tagged_repo

    result = install_ps1(profile, repo=repo, piped=True)

    target = profile["LOCALAPPDATA"] / "Programs" / "pense-bete"
    assert "v1.10.0" in result.stdout
    assert (target / ".version").read_text().strip() == commits["v1.10.0"]
    assert (target / ".release").read_text().strip() == "v1.10.0"
    assert shortcut(profile).exists()


def test_the_commit_and_release_given_are_recorded(profile, tmp_path):
    target = tmp_path / "app"

    install_ps1(profile, "-Target", str(target), "-Commit", "abc123", "-Release", "v9.9.9")

    assert (target / ".version").read_text().strip() == "abc123"
    assert (target / ".release").read_text().strip() == "v9.9.9"


def test_without_git_the_standalone_installer_downloads_the_newest_release(
        profile, no_git_path, fake_github):
    api, commit = fake_github

    result = install_ps1(profile, piped=True, path=no_git_path, api=api)

    target = profile["LOCALAPPDATA"] / "Programs" / "pense-bete"
    assert "git" in result.stdout  # warned that notes will have no history
    assert "v1.10.0" in result.stdout
    assert (target / "pensebete" / "app.py").is_file()
    assert (target / ".version").read_text().strip() == commit
    assert (target / ".release").read_text().strip() == "v1.10.0"
    assert shortcut(profile).exists()


@pytest.fixture
def bundle(tmp_path):
    """A standalone build unpacked, as an update hands it over to its installer."""
    from conftest import fake_bundle_files
    directory = tmp_path / "staged" / "Pense-bete"
    for name, data in fake_bundle_files().items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    return directory


def run_ps1(profile, script, *args, path=None, api=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("PENSE_BETE_")}
    env.update({key: str(value) for key, value in profile.items()})
    if path is not None:
        env["PATH"] = path
    if api is not None:
        env["PENSE_BETE_API"] = api
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                             "Bypass", "-File", str(script), "-Yes", *args],
                            env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_a_standalone_build_is_installed_with_a_shortcut_to_its_executable(profile, tmp_path,
                                                                            bundle):
    target = tmp_path / "app"

    run_ps1(profile, bundle / "install.ps1", "-Target", str(target),
            "-Commit", "abc", "-Release", "v1.2.3")

    assert (target / "Pense-bete.exe").is_file()
    assert (target / "_internal" / "python312.dll").is_file()
    assert (target / ".release").read_text().strip() == "v1.2.3"
    link = read_shortcut(shortcut(profile))
    assert link["target"] == str(target / "Pense-bete.exe")
    assert link["arguments"] == ""
    assert link["app_id"] == "pense-bete"


def test_a_standalone_build_replaces_an_installation_with_python(profile, tmp_path, bundle):
    target = tmp_path / "app"
    install_ps1(profile, "-Target", str(target))
    assert (target / "pense_bete.py").exists()

    run_ps1(profile, bundle / "install.ps1", "-Target", str(target))

    assert not (target / "pense_bete.py").exists() and not (target / "pensebete").exists()
    assert (target / "Pense-bete.exe").is_file()


def test_an_update_waits_for_the_application_then_cleans_up_and_relaunches(profile, tmp_path,
                                                                           bundle):
    import sys
    import time
    target = tmp_path / "app"
    running = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    started = time.monotonic()

    run_ps1(profile, bundle / "install.ps1", "-Target", str(target),
            "-WaitPid", str(running.pid), "-Launch", "-RemoveSource")

    assert time.monotonic() - started >= 3  # it waited for the process to end
    assert running.poll() is not None
    assert (target / "Pense-bete.exe").is_file()
    assert not bundle.exists()  # the unpacked download is gone


def test_standalone_downloads_the_build_of_the_newest_release(profile, tmp_path, fake_github):
    api, commit = fake_github
    alone = tmp_path / "script"  # install.ps1 on its own: nothing to install beside it
    alone.mkdir()
    (alone / "install.ps1").write_bytes((REPO_DIR / "install.ps1").read_bytes())
    target = tmp_path / "app"

    result = run_ps1(profile, alone / "install.ps1", "-Standalone", "-Target", str(target),
                     api=api)

    assert "v1.10.0" in result.stdout
    assert (target / "Pense-bete.exe").is_file()
    assert (target / ".version").read_text().strip() == commit
    assert read_shortcut(shortcut(profile))["target"] == str(target / "Pense-bete.exe")


def test_a_standalone_installation_is_uninstalled(profile, tmp_path, bundle):
    target = tmp_path / "app"
    run_ps1(profile, bundle / "install.ps1", "-Target", str(target))

    run_ps1(profile, target / "install.ps1", "-Uninstall")

    assert not target.exists()
    assert not shortcut(profile).exists()
