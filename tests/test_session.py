from PySide6.QtCore import QByteArray

from pensebete.session import Session


def test_values_survive_a_write_and_reload(session):
    session.set("background", True)
    session.set("open_notes", ["a", "b"])
    session.write()

    reloaded = Session(session.path)

    assert reloaded.get("background", False) is True
    assert reloaded.get("open_notes", []) == ["a", "b"]
    assert reloaded.get("missing", 42) == 42


def test_geometry_round_trip(session):
    geometry = QByteArray(b"\x01\x02binary\xff")
    session.set_geometry("main", geometry)
    session.write()

    assert Session(session.path).geometry("main") == geometry
    assert session.geometry("other") is None


def test_forget_removes_a_note_everywhere(session):
    session.set("open_notes", ["a", "b"])
    session.set("recent", ["b", "a"])
    session.set("on_top", ["a"])
    session.set_geometry("a", QByteArray(b"x"))
    session.set_geometry("b", QByteArray(b"y"))

    session.forget("a")

    assert session.get("open_notes", None) == ["b"]
    assert session.get("recent", None) == ["b"]
    assert session.get("on_top", None) == []
    assert session.geometry("a") is None
    assert session.geometry("b") == QByteArray(b"y")


def test_an_unreadable_file_starts_an_empty_session(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("{broken")

    assert Session(path).data == {}
    assert Session(tmp_path / "absent.json").data == {}
