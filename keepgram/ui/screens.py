"""The screens: the home menu, your chats, settings, and a chat picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, OptionList
from textual.widgets.option_list import Option

from keepgram import config, plugins
from keepgram.ui import flows, look
from keepgram.ui.dialogs import Ask, Choice
from keepgram.ui.widgets import KeyBar, SafeOptionList, SafeTable, TopBar

HOME = [
    ("chats", "My channels and groups", "every chat you created - pick one to work on it"),
    ("folders", "Sort them into folders", 'Keepgram 1, Keepgram 2, ... - a new one when one is full'),
    ("secure", "Make every file my own", "re-upload files that depend on someone else's post"),
    ("tidy", "Delete forwards I have copies of", "each forward goes once its own copy is checked"),
    ("upload", "Upload a folder", "every file in a folder from this computer, big ones in parts"),
    ("watch", "Keep working while I use Telegram", "new chats into folders, new forwards copied - until you stop it"),
    ("join", "Join downloaded parts", "name.mkv.001, .002, ... back into the file"),
    ("bot", "Run the bot", "let anyone add keepgram to their channels and groups"),
    ("settings", "Settings", "limits, folder names, what to copy, the look"),
    ("account", "Log in / log out", "your Telegram account"),
]


class HomeScreen(Screen):
    BINDINGS = [Binding("q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield TopBar(["keepgram"], "not logged in")
        yield SafeOptionList(*[Option(f"{label}\n[dim]   {hint}[/dim]", id=key) for key, label, hint in HOME],
                             id="home")
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one("#home").focus()
        self.app.start_flow(flows.quiet_connect(self.app))

    def on_screen_resume(self) -> None:
        self.refresh_info()

    def refresh_info(self) -> None:
        me = getattr(self.app, "me", None)
        if me:
            name = " ".join(x for x in (me.first_name, me.last_name) if x)
            watching = " · watching" if getattr(self.app, "watching", False) else ""
            self.query_one(TopBar).set_info(f"{name}{' · @' + me.username if me.username else ''}{watching}")
        else:
            self.query_one(TopBar).set_info("not logged in")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id
        app = self.app
        if key == "chats":
            app.push_screen(ChatsScreen())
        elif key == "settings":
            app.push_screen(SettingsScreen())
        elif key == "folders":
            app.start_flow(flows.folders_flow(app))
        elif key == "secure":
            app.start_flow(flows.secure_flow(app))
        elif key == "tidy":
            app.start_flow(flows.tidy_flow(app))
        elif key == "upload":
            app.start_flow(flows.upload_flow(app))
        elif key == "join":
            app.start_flow(flows.join_flow(app))
        elif key == "watch":
            app.start_flow(flows.watch_flow(app))
        elif key == "bot":
            app.start_flow(flows.bot_flow(app))
        elif key == "account":
            app.start_flow(flows.account_flow(app))


class ChatsScreen(Screen):
    """Your chats; Enter on one: make its files your own, or upload into it."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back"), Binding("r", "reload", "Reload")]

    def compose(self) -> ComposeResult:
        yield TopBar(["keepgram", "My channels and groups"], "loading …")
        yield SafeTable(id="chats")
        yield KeyBar()

    def on_mount(self) -> None:
        table = self.query_one(SafeTable)
        table.add_column("Kind", width=8)
        table.add_column("Title")
        table.focus()
        self.action_reload()

    def action_reload(self) -> None:
        self.app.start_flow(flows.load_chats(self.app, self))

    def show(self, owned) -> None:
        self.owned = owned
        table = self.query_one(SafeTable)
        table.clear()
        for c in owned:
            table.add_row("channel" if c.kind == "channel" else "group", c.title, key=str(c.id))
        channels = sum(c.kind == "channel" for c in owned)
        self.query_one(TopBar).set_info(f"{len(owned)} chats: {channels} channels, {len(owned) - channels} groups")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        chat = next(c for c in self.owned if str(c.id) == event.row_key.value)
        self.app.start_flow(flows.chat_flow(self.app, chat))


class PickChat(Screen):
    """Pick one of `owned`; Esc gives None."""

    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, path: list[str], owned) -> None:
        super().__init__()
        self.path, self.owned = path, owned

    def compose(self) -> ComposeResult:
        yield TopBar(self.path, "double click or Enter to choose")
        yield SafeTable()
        yield KeyBar()

    def on_mount(self) -> None:
        table = self.query_one(SafeTable)
        table.add_column("Kind", width=8)
        table.add_column("Title")
        for c in self.owned:
            table.add_row(c.kind, c.title, key=str(c.id))
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(next(c for c in self.owned if str(c.id) == event.row_key.value))

    def action_cancel(self) -> None:
        self.dismiss(None)


THUMB_MODES = [("logo", "keepgram pictures - a picture of each file's kind"),
               ("own", "Their own first - keep a copied file's own thumbnail, a picture otherwise"),
               ("none", "None - Telegram's plain file icon")]

# key, label, kind, what it does
SETTINGS = [
    ("premium", "Telegram Premium", "premium", "auto follows your account - its limits come from Telegram"),
    ("thumbnails", "File pictures", "thumbs", "the picture beside files sent as files; photos and videos "
     "sent as media always show as normal"),
    ("include_admin_chats", "Chats I only admin", "bool", "also chats you are an admin of, not just ones you made"),
    ("folders.name", "Folder name", "text", "folders are <name> 1, <name> 2 ... (12 characters with the number)"),
    ("folders.sorter", "Split folders", "sorter", "one series for everything, or channels and groups apart"),
    ("folders.size", "Chats per folder", "int", "0 = Telegram's limit"),
    ("secure.replace", "Delete forwards", "bool", "delete each forward once its own copy is posted and checked"),
    ("secure.source_note", "Note the source", "bool", 'add "kept from <where> · <date>" under the caption'),
    ("secure.skip_own_sources", "Skip my own forwards", "bool", "a forward from one of your own chats isn't copied"),
    ("secure.local_copy_dir", "Also keep on disk", "text", "a folder to keep every copied file in too (empty = no)"),
    ("upload.as_files", "Upload as files", "bool", "byte for byte; off = photos/videos as media, like the apps"),
    ("upload.skip_hidden", "Skip hidden files", "bool", 'names starting with "."'),
    ("upload.part_mb", "Part size (MB)", "int", "for files over the limit; 0 = the limit"),
    ("bot.max_jobs", "Bot: jobs at once", "int", "chats the bot copies at the same time"),
    ("bot.allowed_users", "Bot: allowed users", "ids", "Telegram user ids, comma separated; empty = anyone"),
    ("menus.look", "Look", "look", "Android dark or light"),
]


def _get(cfg, key):
    node = cfg
    for part in key.split("."):
        node = node[part]
    return node


def _set(cfg, key, value):
    *head, last = key.split(".")
    node = cfg
    for part in head:
        node = node[part]
    node[last] = value


def _show(value, kind: str = "") -> str:
    if kind == "sorter":
        plugins.load()
        return next((s.label for s in plugins.items("sorter") if s.name == value), str(value))
    if kind == "look":
        return dict(look.LOOKS).get(value, str(value))
    if kind == "premium":
        return {True: "on", False: "off"}.get(value, "auto")
    if kind == "thumbs":
        return dict(THUMB_MODES).get(value, str(value)).split(" -")[0]
    if kind == "int" and value == 0:
        return "auto"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "anyone"
    return str(value) if value not in ("", None) else "-"


class SettingsScreen(Screen):
    """One flat list; Enter changes the highlighted row, saved at once."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield TopBar(["keepgram", "Settings"], "saved in config.json as you change them")
        yield SafeTable()
        yield KeyBar()

    def on_mount(self) -> None:
        table = self.query_one(SafeTable)
        table.add_column("Setting", width=22)
        table.add_column("Value", width=16)
        table.add_column("What it does")
        self._fill()
        table.focus()

    def _fill(self) -> None:
        table = self.query_one(SafeTable)
        row = table.cursor_row
        table.clear()
        for key, label, kind, what in SETTINGS:
            table.add_row(label, _show(_get(self.app.cfg, key), kind), what, key=key)
        table.move_cursor(row=row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.app.start_flow(self._change(event.row_key.value))

    async def _change(self, key: str) -> None:
        _key, label, kind, what = next(s for s in SETTINGS if s[0] == key)
        cfg, value = self.app.cfg, _get(self.app.cfg, key)
        if kind == "bool":
            new = not value
        elif kind == "sorter":
            plugins.load()
            new = await self.app.push_screen_wait(Choice(label, what, [(s.name, f"{s.label} - {s.description}")
                                                                       for s in plugins.items("sorter")], value))
        elif kind == "thumbs":
            new = await self.app.push_screen_wait(Choice(label, what, THUMB_MODES, value))
        elif kind == "premium":
            picked = await self.app.push_screen_wait(Choice(label, what, [
                ("auto", "Auto - follow my account (recommended)"), ("on", "On"), ("off", "Off")],
                {True: "on", False: "off"}.get(value, "auto")))
            new = {"auto": "auto", "on": True, "off": False}.get(picked)
        elif kind == "look":
            new = await self.app.push_screen_wait(Choice(label, what, [("keepgram-dark", "Android, dark"),
                                                                       ("keepgram-light", "Android, light")], value))
        else:
            shown = ", ".join(map(str, value)) if kind == "ids" else str(value)
            typed = await self.app.push_screen_wait(Ask(label, what, shown))
            if typed is None:
                return
            typed = typed.strip()
            try:
                if kind == "int":
                    new = max(0, int(typed or 0))
                elif kind == "ids":
                    new = [int(x) for x in typed.replace(" ", "").split(",") if x]
                else:
                    new = typed
            except ValueError:
                self.app.notify("That isn't a number.", severity="error")
                return
        if new is None:
            return
        _set(cfg, key, new)
        config.save(cfg)
        if key == "menus.look":
            self.app.theme = new
        self._fill()
