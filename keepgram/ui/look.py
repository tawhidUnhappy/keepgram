"""The Android 17 look (Material 3 Expressive), like remanga's menus, in
keepgram's own colours - the indigo and coral of its logo (assets/). A terminal
draws no curves or shadows, so it shows as tonal surfaces: a tonal top bar and
key bar, the highlighted row on a container fill, dialogs as tonal cards."""

from __future__ import annotations

from textual.theme import Theme

LOOKS = (("keepgram-dark", "Android, dark"), ("keepgram-light", "Android, light"))

DARK = Theme(
    name="keepgram-dark",
    primary="#B9C3FF", secondary="#C3C5DD", accent="#FFB59E",
    foreground="#E4E1E9", background="#121318", surface="#1E1F25", panel="#292A2F", boost="#33343A",
    success="#9ED383", warning="#F6BD58", error="#FFB4AB",
    dark=True,
    variables={
        "block-cursor-background": "#3A4590", "block-cursor-foreground": "#DEE0FF",
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": "#33343A", "block-cursor-blurred-foreground": "#E4E1E9",
        "block-hover-background": "#33343A",
        "footer-background": "#1E1F25", "footer-key-foreground": "#B9C3FF",
        "footer-description-foreground": "#C6C5D0",
        "input-selection-background": "#3A4590",
        "scrollbar": "#46464F", "scrollbar-hover": "#90909A", "scrollbar-active": "#B9C3FF",
        "scrollbar-background": "#1E1F25", "scrollbar-background-hover": "#1E1F25",
        "scrollbar-background-active": "#1E1F25", "scrollbar-corner-color": "#1E1F25",
        "border": "#B9C3FF", "border-blurred": "#46464F",
        "text-muted": "#C6C5D0",
    },
)

LIGHT = Theme(
    name="keepgram-light",
    primary="#2F3DBF", secondary="#5A5D72", accent="#A33F20",
    foreground="#1B1B21", background="#FBF8FF", surface="#F0EDF4", panel="#EAE7EF", boost="#E4E1E9",
    success="#386A20", warning="#7D5700", error="#BA1A1A",
    dark=False,
    variables={
        "block-cursor-background": "#DEE0FF", "block-cursor-foreground": "#00105C",
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": "#E4E1E9", "block-cursor-blurred-foreground": "#1B1B21",
        "block-hover-background": "#E4E1E9",
        "footer-background": "#F0EDF4", "footer-key-foreground": "#2F3DBF",
        "footer-description-foreground": "#46464F",
        "input-selection-background": "#DEE0FF",
        "scrollbar": "#C6C5D0", "scrollbar-hover": "#767680", "scrollbar-active": "#2F3DBF",
        "scrollbar-background": "#F0EDF4", "scrollbar-background-hover": "#F0EDF4",
        "scrollbar-background-active": "#F0EDF4", "scrollbar-corner-color": "#F0EDF4",
        "border": "#2F3DBF", "border-blurred": "#C6C5D0",
        "text-muted": "#46464F",
    },
)


def register(app) -> None:
    app.register_theme(DARK)
    app.register_theme(LIGHT)
