"""The keyboard shortcuts and mouse gestures, which the user can change or turn off.

Every action has default keys; the user's changes are kept in the session, on top of
them, so that an action left alone follows the defaults. Mouse gestures are turned on
or off, not rebound. Widgets ask here rather than hard-coding their keys, and bind
their shortcuts through Binding, which follows the changes.
"""

from dataclasses import dataclass

from PySide6.QtCore import QKeyCombination, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut


@dataclass(frozen=True)
class Action:
    id: str
    section: str  # translation keys
    description: str
    defaults: tuple[str, ...] = ()  # key sequences, in Qt's portable text
    gesture: str = ""  # the translation key naming a mouse gesture, for gestures only
    # Where the keys work: "list", "note" or "both". Two actions of overlapping scopes
    # cannot share a key.
    scope: str = "note"


ACTIONS = (
    Action("search", "sc_section_list", "sc_search", ("Ctrl+F",), scope="list"),
    Action("open_first", "sc_section_list", "sc_open_first", ("Return",), scope="list"),
    Action("clear_search", "sc_section_list", "sc_clear_search", ("Esc",), scope="list"),
    Action("close_list", "sc_section_list", "sc_close_list", ("Ctrl+W",), scope="list"),
    Action("shortcuts", "sc_section_list", "sc_shortcuts", ("F1",), scope="both"),
    Action("save", "sc_section_note", "sc_save", ("Ctrl+S",)),
    Action("close_note", "sc_section_note", "sc_close_note", ("Ctrl+W",)),
    Action("undo", "sc_section_note", "sc_undo", ("Ctrl+Z",)),
    Action("redo", "sc_section_note", "sc_redo", ("Ctrl+Y", "Ctrl+Shift+Z")),
    Action("copy_all", "sc_section_note", "sc_copy_all", ("Ctrl+Shift+C",)),
    Action("clear_all", "sc_section_note", "sc_clear_all", ("Ctrl+Del",)),
    Action("zoom_in", "sc_section_note", "sc_zoom_in", ("Ctrl++", "Ctrl+=")),
    Action("zoom_out", "sc_section_note", "sc_zoom_out", ("Ctrl+-",)),
    Action("zoom_reset", "sc_section_note", "sc_zoom_reset", ("Ctrl+0",)),
    Action("zoom_wheel", "sc_section_note", "sc_zoom", gesture="sc_ctrl_wheel"),
    Action("move", "sc_section_note", "sc_move", gesture="sc_alt_left_drag"),
    Action("resize", "sc_section_note", "sc_resize", gesture="sc_alt_right_drag"),
    Action("history_older", "sc_section_note", "sc_history_older", ("Alt+Left",)),
    Action("history_newer", "sc_section_note", "sc_history_newer", ("Alt+Right",)),
    Action("insert_task", "sc_section_markdown", "sc_insert_task", ("Ctrl+L",)),
    Action("insert_table", "sc_section_markdown", "sc_insert_table", ("Ctrl+T",)),
    Action("toggle_task", "sc_section_markdown", "sc_toggle_task", ("Ctrl+Space",)),
    Action("click_box", "sc_section_markdown", "sc_toggle_task", gesture="sc_click_box"),
    Action("continue_list", "sc_section_markdown", "sc_continue_list", ("Return",)),
    Action("table_next", "sc_section_table", "sc_next_cell", ("Tab",)),
    Action("table_previous", "sc_section_table", "sc_previous_cell", ("Shift+Tab",)),
    Action("table_add_row", "sc_section_table", "sc_add_row", ("Ctrl+Return",)),
    Action("table_add_column", "sc_section_table", "sc_add_column", ("Ctrl+Shift+Return",)),
    Action("table_delete_row", "sc_section_table", "sc_delete_row", ("Ctrl+Backspace",)),
    Action("table_delete_column", "sc_section_table", "sc_delete_column",
           ("Ctrl+Shift+Backspace",)),
)
BY_ID = {action.id: action for action in ACTIONS}


def normalized(sequence: QKeySequence | str) -> str:
    """A key sequence as portable text, Shift+Tab and the keypad's Enter written as the
    keys users think of: Qt reports them as Backtab and Enter."""
    text = QKeySequence(sequence).toString(QKeySequence.PortableText)
    return text.replace("Backtab", "Tab").replace("Enter", "Return")


def event_sequence(event: QKeyEvent) -> str:
    """The key sequence a key press makes, in the form normalized() gives."""
    modifiers = event.modifiers() & ~Qt.KeypadModifier
    key = event.key()
    if key == Qt.Key_Backtab:
        key, modifiers = Qt.Key_Tab, modifiers | Qt.ShiftModifier
    if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_unknown):
        return ""
    return normalized(QKeySequence(QKeyCombination(modifiers, Qt.Key(key))))


class Shortcuts(QObject):
    """The keys of every action, and whether each gesture is on."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.session = None
        self.keys_changed: dict[str, list[str]] = {}
        self.gestures_changed: dict[str, bool] = {}

    def attach(self, session) -> None:
        """Take the user's changes from the session, and keep them there."""
        self.session = session
        saved = session.get("shortcuts", {})
        self.keys_changed = {id: list(keys) for id, keys in saved.get("keys", {}).items()
                             if id in BY_ID and not BY_ID[id].gesture}
        self.gestures_changed = {id: bool(on) for id, on in saved.get("gestures", {}).items()
                                 if id in BY_ID and BY_ID[id].gesture}
        self.changed.emit()

    def detach(self) -> None:
        """Back to the defaults, kept nowhere."""
        self.session = None
        self.keys_changed, self.gestures_changed = {}, {}
        self.changed.emit()

    def keys(self, action_id: str) -> list[str]:
        if action_id in self.keys_changed:
            return list(self.keys_changed[action_id])
        return list(BY_ID[action_id].defaults)

    def enabled(self, action_id: str) -> bool:
        """Whether a gesture is on, or whether an action has any key."""
        action = BY_ID[action_id]
        if action.gesture:
            return self.gestures_changed.get(action_id, True)
        return bool(self.keys(action_id))

    def is_default(self, action_id: str) -> bool:
        return action_id not in self.keys_changed and action_id not in self.gestures_changed

    def matches(self, action_id: str, event: QKeyEvent) -> bool:
        sequence = event_sequence(event)
        return bool(sequence) and sequence in map(normalized, self.keys(action_id))

    def conflict(self, action_id: str, sequence: str) -> str | None:
        """Another action that has this key where the given one would work, if any."""
        scope = BY_ID[action_id].scope
        sequence = normalized(sequence)
        for other in ACTIONS:
            if other.id == action_id or other.gesture:
                continue
            if "both" not in (scope, other.scope) and scope != other.scope:
                continue
            if sequence in map(normalized, self.keys(other.id)):
                return other.id
        return None

    def set_keys(self, action_id: str, keys: list[str]) -> None:
        keys = [normalized(key) for key in keys if key]
        if keys == [normalized(key) for key in BY_ID[action_id].defaults]:
            self.keys_changed.pop(action_id, None)
        else:
            self.keys_changed[action_id] = keys
        self._save()

    def set_enabled(self, action_id: str, enabled: bool) -> None:
        """Turn a gesture on or off."""
        if enabled:
            self.gestures_changed.pop(action_id, None)
        else:
            self.gestures_changed[action_id] = False
        self._save()

    def reset(self, action_id: str | None = None) -> None:
        """Back to the defaults, for one action or, without one, for all."""
        if action_id is None:
            self.keys_changed, self.gestures_changed = {}, {}
        else:
            self.keys_changed.pop(action_id, None)
            self.gestures_changed.pop(action_id, None)
        self._save()

    def _save(self) -> None:
        if self.session is not None:
            self.session.set("shortcuts", {"keys": self.keys_changed,
                                           "gestures": self.gestures_changed})
            self.session.write()
        self.changed.emit()


# The application's shortcuts, which MainWindow attaches to the session.
settings = Shortcuts()


class Binding(QObject):
    """QShortcuts on a widget for an action's keys, rebuilt when they change."""

    def __init__(self, widget, action_id: str, callback, context=Qt.WindowShortcut):
        super().__init__(widget)
        self.widget, self.action_id, self.callback, self.context = (
            widget, action_id, callback, context)
        self.shortcuts: list[QShortcut] = []
        settings.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        for key in settings.keys(self.action_id):
            shortcut = QShortcut(QKeySequence(key), self.widget)
            shortcut.setContext(self.context)
            shortcut.activated.connect(self.callback)
            self.shortcuts.append(shortcut)


def first_key(action_id: str) -> QKeySequence:
    """The key to show beside an action in a menu, none when it has no key."""
    keys = settings.keys(action_id)
    return QKeySequence(keys[0]) if keys else QKeySequence()
