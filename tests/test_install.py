"""install.sh, run from this repository into a throwaway HOME."""

import os
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_DIR


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def install_sh(home, *args, script=REPO_DIR / "install.sh"):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XDG_", "PENSE_BETE_"))}
    env["HOME"] = str(home)
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
