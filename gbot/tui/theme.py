from textual.theme import Theme

GBOT_THEME = Theme(
    name="gbot",
    primary="#d97757",
    accent="#d97757",
    secondary="#929292",
    foreground="#dedede",
    background="#181818",
    surface="#181818",
    panel="#222222",
    success="#78b878",
    warning="#d2b45f",
    error="#d16969",
    dark=True,
)

STYLES = """
Screen { background: $background; color: $foreground; padding: 1 2; }
#header { height: 1; layout: horizontal; }
#heading { width: 1fr; }
#connection { width: auto; color: $success; }
#body { height: 1fr; padding-top: 1; }
#footer { height: 3; color: $text-muted; border-top: solid $secondary; }
*:focus { border: solid $accent; }
HelpScreen { align: center middle; background: $background 80%; }
#help { width: 76; height: 90%; border: solid $accent; padding: 1 2; }
#help-title { height: 2; color: $accent; }
#help-bindings { height: 1fr; }
"""
