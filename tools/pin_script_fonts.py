"""Checks the pinned fonts of src/bobina/scriptfonts.py against the network: downloads every font and license
(about 30 MB) and compares size and sha256 with the table. Run it after changing a commit or adding a pack:

    python tools/pin_script_fonts.py            # exit 1 and the right values when a pin is wrong
    python tools/pin_script_fonts.py thai lao   # only these packs

Not run by the tests (no network there): tests/test_scriptfonts.py checks the table offline."""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bobina import scriptfonts  # noqa: E402


def main(names: list[str]) -> int:
    bad = 0
    seen: dict[str, tuple[int, str]] = {}
    for p in scriptfonts.PACKS.values():
        if names and p.id not in names:
            continue
        for what, url, size, sha in (
            ("font", p.url, p.size, p.sha256),
            ("license", p.license_url, p.license_size, p.license_sha256),
        ):
            if url not in seen:
                data = scriptfonts.fetch(url, scriptfonts.MAX_BYTES)
                seen[url] = (len(data), hashlib.sha256(data).hexdigest())
            got = seen[url]
            ok = got == (size, sha)
            bad += not ok
            print(f"{'ok ' if ok else 'BAD'} {p.id:20s} {what:8s} {got[0]:>9d} {got[1]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
