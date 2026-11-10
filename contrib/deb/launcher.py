#!/usr/bin/python3 -I
"""/usr/bin/bobina of the .deb (tools/build_deb.py). The package carries its own dependencies, not Debian's
python3-* packages (too old, or missing): the pure-Python ones in /usr/lib/bobina/common, the compiled ones once
per Python version in /usr/lib/bobina/cpXY. This picks the directory of the Python running it, the distribution's
own python3 (the one with Bluetooth sockets)."""

import os
import re
import sys

LIB = "/usr/lib/bobina"
RELEASES = "https://github.com/rafaelbressan/bobina/releases"


def lib_dirs(lib=LIB, version=None):
    """The directories to put first on sys.path, or SystemExit saying which Pythons this package has."""
    major, minor = (version or sys.version_info)[:2]
    own = os.path.join(lib, f"cp{major}{minor}")
    if os.path.isdir(own):
        return [own, os.path.join(lib, "common")]
    have = sorted(int(d[3:]) for d in os.listdir(lib) if re.fullmatch(r"cp3\d+", d))  # cp311 -> 11
    pythons = ", ".join(f"3.{n}" for n in have) or "none"
    raise SystemExit(
        f"bobina: this .deb has no packages for Python {major}.{minor} ({sys.executable}); it has them for Python"
        f" {pythons}.\nInstall the .deb of a newer bobina ({RELEASES}), or: pipx install bobina"
    )


def main():
    sys.path[:0] = lib_dirs()
    sys.dont_write_bytecode = True  # the .pyc files are written once, by the package's postinst
    from bobina.cli import main as bobina

    sys.exit(bobina())


if __name__ == "__main__":
    main()
