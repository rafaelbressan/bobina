"""One file per label: an output name with {placeholders} (like ffmpeg's frame%04d.png).

    -o 'jar-{n}.png'      {n}  label number in the whole job (1, 2, 3 …); {n:03} pads with zeros
    -o '{file}-{i}.bin'   {i}  number inside its document (restarts per file); {file} document name
    -o 'tag-{item}.jpg'   {part} the --then part; {column} a data value ({b.column} from a joined source)

Data values come from spreadsheets: they are cleaned so a cell can never become a path ('../x', '/', ':')."""

from __future__ import annotations

import re
from pathlib import Path

PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.]*)(?:\|(\w+))?(?::(\d{1,2}))?\}")
CASES = ("lower", "upper", "slug", "snake", "kebab", "camel", "pascal", "deaccent", "titlecase")
UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


class ExportError(ValueError):
    pass


def is_pattern(name: str | None) -> bool:
    return bool(name and PLACEHOLDER.search(name))


def clean(value: str) -> str:
    v = UNSAFE.sub("_", str(value)).strip().strip(".")
    v = re.sub(r"\.{2,}", "_", v)
    return (v or "_")[:80]


def names(pattern: str, metas: list[dict]) -> list[Path]:
    """metas: per label {n, i, part, file, fields}. -> one path per label; errors for unknown placeholders and
    for two labels that would get the same name (one would overwrite the other)."""
    out = []
    for m in metas:

        def fill(match, m=m):
            key, case, width = match.group(1), match.group(2), match.group(3)
            if key in ("n", "i", "part"):
                return str(m[key]).zfill(int(width or 0))
            val = m["file"] if key == "file" else _field(m["fields"], key)
            if val is None:
                avail = ", ".join(["n", "i", "part", "file", *sorted(_keys(m["fields"]))])
                raise ExportError(f"-o {pattern}: no value for {{{key}}} (available: {avail})")
            return clean(_case(str(val), case, pattern))

        out.append(Path(PLACEHOLDER.sub(fill, pattern)).expanduser())
    seen: dict[Path, int] = {}
    for k, p in enumerate(out, 1):
        if p in seen:
            raise ExportError(
                f"-o {pattern}: labels {seen[p]} and {k} would both be saved as {p.name}; add {{n}} or {{i}}"
            )
        seen[p] = k
    return out


def _case(value: str, case: str | None, pattern: str) -> str:
    """{item|slug}: the text filters of templates (docs/FORMAT.md), for file names."""
    if not case:
        return value
    if case not in CASES:
        raise ExportError(f"-o {pattern}: unknown case '|{case}' (use: {', '.join(CASES)})")
    from babel import Locale

    from .templating import text_filters

    if case in ("lower", "upper"):
        return value.lower() if case == "lower" else value.upper()
    return text_filters(Locale("en"))[case](value)


def _field(fields: dict, key: str):
    cur = fields
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return None if isinstance(cur, (dict, list)) else cur


def _keys(fields: dict, prefix: str = "") -> list[str]:
    out = []
    for k, v in fields.items():
        from .datasource import internal

        if internal(k):
            continue
        if k == "row" and not prefix and isinstance(v, dict):  # the exact headers: only those not usable as they are
            out += [f"row.{c}" for c in v if c not in fields]
            continue
        if isinstance(v, dict):
            out += _keys(v, f"{prefix}{k}.")
        elif not isinstance(v, list):
            out.append(prefix + k)
    return out
