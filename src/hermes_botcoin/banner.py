"""ASCII banner for the BOTCOIN plugin.

Two pre-rendered variants are exported as module constants — no pyfiglet
runtime dependency, no surprise Unicode width issues. The font (`ansi_shadow`)
is picked to match the chunky 3D block style of Hermes' own logo.

Usage::

    from hermes_botcoin.banner import BANNER_ONE_LINE, BANNER_STACKED, render
    print(render())
"""

from __future__ import annotations

# 6 lines × ~111 cols. Use in README headers and TUI splash screens.
BANNER_ONE_LINE = (
    "██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗    ██████╗  ██████╗ ████████╗ ██████╗ ██████╗ ██╗███╗   ██╗\n"
    "██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝    ██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝██╔═══██╗██║████╗  ██║\n"
    "███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗    ██████╔╝██║   ██║   ██║   ██║     ██║   ██║██║██╔██╗ ██║\n"
    "██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║    ██╔══██╗██║   ██║   ██║   ██║     ██║   ██║██║██║╚██╗██║\n"
    "██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║    ██████╔╝╚██████╔╝   ██║   ╚██████╗╚██████╔╝██║██║ ╚████║\n"
    "╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝    ╚═════╝  ╚═════╝    ╚═╝    ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝"
)

# 12 lines × ~57 cols (HERMES on top, BOTCOIN below). For installers and
# narrower terminals.
BANNER_STACKED = (
    "██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗\n"
    "██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝\n"
    "███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗\n"
    "██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║\n"
    "██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║\n"
    "╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝\n"
    "██████╗  ██████╗ ████████╗ ██████╗ ██████╗ ██╗███╗   ██╗\n"
    "██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝██╔═══██╗██║████╗  ██║\n"
    "██████╔╝██║   ██║   ██║   ██║     ██║   ██║██║██╔██╗ ██║\n"
    "██╔══██╗██║   ██║   ██║   ██║     ██║   ██║██║██║╚██╗██║\n"
    "██████╔╝╚██████╔╝   ██║   ╚██████╗╚██████╔╝██║██║ ╚████║\n"
    "╚═════╝  ╚═════╝    ╚═╝    ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝"
)

TAGLINE = "  Mine BOTCOIN. Native to Hermes Agent. Privacy-first via Venice."


def render(*, stacked: bool | None = None, width: int | None = None) -> str:
    """Return the banner. Auto-stack on terminals narrower than the one-line
    width unless caller pins ``stacked``."""
    import shutil
    cols = width or shutil.get_terminal_size((100, 24)).columns
    if stacked is None:
        stacked = cols < 115
    body = BANNER_STACKED if stacked else BANNER_ONE_LINE
    return body + "\n" + TAGLINE
