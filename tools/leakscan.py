#!/usr/bin/env python3
"""Scan files for personal data before they are published.

Generic patterns live here (MAC addresses, e-mails, CPF numbers, phone numbers, home paths, tailnet
addresses). Literal personal values (and private tracker ids) belong in a private patterns file
(one regex per line), passed with --patterns, found at local/leak-patterns.txt (gitignored), or given in the
LEAK_PATTERNS environment variable (CI: a repository secret): publishing that list would itself be the leak.

Test data and docs: known fake values and fake-data folders go in tools/leak-allow.txt (public, each with a
reason); one line can be excused with a `leak-ok: <reason>` marker. Neither excuses a private (real) value.

Usage: tools/leakscan.py [--patterns FILE] [PATH ...]   (default: the public allowlist)
Exit code 1 when something is found."""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ttf", ".otf", ".woff", ".woff2", ".whl", ".bin", ".zip"}

GENERIC = {
    "mac address": re.compile(r"(?<![0-9A-Fa-f:])(?!AA:BB:CC:DD:EE:FF)[0-9A-F]{2}(?::[0-9A-F]{2}){5}(?![0-9A-Fa-f:])"),
    "e-mail": re.compile(  # reserved for examples (RFC 2606/6761): example.com/.org/.net, *.test, *.invalid, *.example
        r"[\w.+-]+@(?!example\.(?:com|org|net)\b)(?!anthropic\.com\b)(?![\w.-]+\.(?:test|invalid|example)\b)"
        r"[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b",
        re.I,
    ),
    "cpf": re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d])"),
    "phone": re.compile(r"\+\d{2}[\s-]?\(?\d{2}\)?[\s-]?9\d{4}[\s-]?\d{4}"),
    "home path": re.compile(r"/(?:home|Users)/(?!user\b|runner\b|you\b|me\b)[a-z][\w.-]+"),
    "tailnet": re.compile(r"\b[\w-]+\.ts\.net\b|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
}

HELP = """These look like personal data (a real e-mail, phone, CPF, MAC address, home folder or private network).
If they are real, remove them. If they are made up for a test or an example: use reserved values (example.com,
AA:BB:CC:DD:EE:FF, /home/user), list them in tools/leak-allow.txt with a reason, or end the line with a
`leak-ok: <reason>` comment. A "private pattern" finding comes from the maintainer's own list (CI secret)."""


def public_files() -> list[Path]:
    globs = [
        ln.strip()
        for ln in (ROOT / "tools/public-files.txt").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    # tracked files and new ones not yet added (a scan run before `git add` must not miss a new test file);
    # ignored files are never public
    tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()  # fmt: skip
    return [ROOT / f for f in tracked if any(fnmatch.fnmatch(f, g) or f == g for g in globs)]


def load_private(path: Path | None) -> tuple[dict[str, re.Pattern], set[str]]:
    """Private regexes, plus `!path` lines: files where they are intended (e.g. the LICENSE copyright)."""
    import os

    p = path or ROOT / "local/leak-patterns.txt"
    if p.exists():
        text = p.read_text()
    elif os.environ.get("LEAK_PATTERNS"):
        text = os.environ["LEAK_PATTERNS"]
    else:
        return {}, set()
    out, exempt = {}, set()
    for i, ln in enumerate(text.splitlines(), 1):
        ln = ln.strip()
        if ln.startswith("!"):
            exempt.add(ln[1:].strip())
        elif ln and not ln.startswith("#"):
            out[f"private pattern #{i}"] = re.compile(ln, re.I)
    return out, exempt


LEAK_OK = re.compile(r"leak-ok:\s*\S.{2,}")  # a line marker with a reason, like noqa: `leak-ok: fake key for tests`


def load_allow(path: Path | None = None) -> tuple[set[str], list[str]]:
    """Public allowlist (tools/leak-allow.txt): known fake values allowed anywhere, and paths of files that hold
    only fake data. Every entry needs a reason after '#'; an entry without one is an error."""
    p = path or ROOT / "tools/leak-allow.txt"
    values, paths = set(), []
    if not p.exists():
        return values, paths
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        entry, sep, reason = ln.partition(" #")
        if not sep or not reason.strip():
            raise SystemExit(f"{p.name}:{i}: an allowlist entry needs a reason: '{ln}  # why it is fake'")
        kind, _, value = entry.strip().partition(":")
        if kind == "value" and value.strip():
            values.add(value.strip())
        elif kind == "path" and value.strip():
            paths.append(value.strip())
        else:
            raise SystemExit(f"{p.name}:{i}: use 'value: TEXT  # reason' or 'path: GLOB  # reason'")
    return values, paths


def scan(
    files: list[Path],
    patterns: dict[str, re.Pattern],
    private: dict | None = None,
    exempt: set[str] = frozenset(),
    allow: tuple[set[str], list[str]] = (set(), []),
) -> list[str]:
    hits = []
    allowed_values, allowed_paths = allow
    for f in files:
        rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else f.name
        if any(fnmatch.fnmatch(rel, g) for g in allowed_paths):
            active = dict(private or {})  # fake-data files: generic patterns off, the private (real) values still on
        else:
            active = {**patterns, **(private or {})}
        if rel in exempt or f.name in exempt:
            active = {k: v for k, v in active.items() if k in patterns}
        if f.suffix.lower() in BINARY or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            marked = LEAK_OK.search(line) is not None
            for name, rx in active.items():
                if marked and name in patterns:
                    continue  # the line says why its generic match is fake; real (private) values are never excused
                m = next((x for x in rx.finditer(line) if x.group(0) not in allowed_values), None)
                if m:
                    shown = m.group(0)
                    masked = shown[:2] + "…" + shown[-2:] if len(shown) > 6 else "…"
                    hits.append(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}:{n}: {name} ({masked})")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--patterns", type=Path, help="private patterns file (one regex per line)")
    a = ap.parse_args()
    files = []
    for p in a.paths:
        files += [x for x in p.rglob("*") if x.is_file()] if p.is_dir() else [p]
    if not files:
        files = public_files()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
        if dirty:
            print("note: uncommitted changes — CI scans the committed files, which may differ", file=sys.stderr)
    private, exempt = load_private(a.patterns)
    hits = scan(files, GENERIC, private, exempt, load_allow())
    for h in hits:
        print(h)
    if hits:
        print("\n" + HELP, file=sys.stderr)
    print(f"{len(files)} files scanned, {len(hits)} finding(s)", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
