"""bobina update: is there a newer bobina, and the command of what installed it (shown, run only after asking)."""

from __future__ import annotations

import subprocess

from .. import __version__, update
from .common import OK, UNREACHABLE, USAGE, Fail, ask, err, open_tty, print_json

NEWER = 10  # bobina update --check: a newer release exists (docs/CLI.md exit codes)
SCHEMA = "bobina.update/1"


def cmd_update(args):
    try:
        latest = update.fetch()
    except update.UpdateError as e:
        raise Fail.with_hint(UNREACHABLE, f"could not check for a new bobina: {e}",
                             f"try again when online, or look at {update.RELEASES}", "E701") from None  # fmt: skip
    how = update.detect(latest)
    is_newer = update.newer(latest)
    dev = update.parse(__version__) is None
    if args.json:
        print_json({"schema": SCHEMA, "version": __version__, "latest": latest, "newer": is_newer,
                    "development": dev, **how.as_dict(), "note": how.note}, indent=2)  # fmt: skip
        return NEWER if args.check and is_newer else OK
    if dev:
        print(f"bobina {__version__} is a development version; the latest release is {latest}")
    elif not is_newer:
        print(f"bobina {__version__} is the latest release")
        return OK
    else:
        print(f"bobina {latest} is available (you have {__version__})")
    if args.check:
        return NEWER if is_newer else OK
    print(f"installed by {how.what}: {how.shown}")
    if how.note:
        print(f"  {how.note}")
    if not how.command:  # sudo, a download or a source checkout: said, never run
        return OK
    tty = open_tty()
    if tty is None:  # a script or an agent: the command is shown, never run
        return OK
    with tty:
        a = ask(tty, " run it? [y/n] ")
    if a not in ("y", "yes"):
        err("not run")
        return OK
    try:
        code = subprocess.call(how.command)
    except OSError as e:
        raise Fail(USAGE, f"cannot run {how.command[0]}: {e.strerror or e}\n→ run it yourself: {how.shown}",
                   problem="E101") from None  # fmt: skip
    if code:
        raise Fail(USAGE, f"{how.shown} exited with {code}\n→ its message is above", problem="E101")
    return OK
