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


def install_ps1(profile, *args, repo=None, piped=False):
    """Run install.ps1 from this repository, or as `irm ... | iex` does when piped."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PENSE_BETE_")}
    env.update({key: str(path) for key, path in profile.items()})
    if repo is not None:
        env["PENSE_BETE_REPO"] = str(repo)
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
