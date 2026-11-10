"""Last print and drafts (~/.local/state/bobina)."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from . import paths


def last_dir() -> Path:
    return paths.state_dir() / "last"


def _pointer() -> Path:
    return paths.state_dir() / "last.json"


def save_last(source: str, base_dir: str, origin: str, data: bytes, image, stats: dict):
    """The last print, for --last/--again. Each job gets its own folder (last/<id>/) and last.json names the
    current one, replaced atomically: --last never mixes the files of two jobs printed at the same time."""
    from . import fileio

    root = last_dir()
    root.mkdir(parents=True, exist_ok=True)
    meta = {"base_dir": base_dir, "origin": origin, "stats": stats, "printed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with fileio.locked(_pointer()):  # the whole save: the newest folder is always the one last.json names
        job = Path(tempfile.mkdtemp(prefix=f"{time.time_ns():020d}-", dir=root))  # names sort by time
        (job / "source.bob.md").write_text(source, encoding="utf-8")
        (job / "job.bin").write_bytes(data)
        image.save(job / "preview.png")  # 1-bit: the dots are black or white
        (job / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        fileio.write_json(_pointer(), {"job": job.name})
        _prune(root, keep={job.name})


def _prune(root: Path, keep: set[str]) -> None:
    """Old job folders go; the two newest stay, so a --last reading the previous one still finds its files.
    Files of the layout before per-job folders (last/meta.json …) go too."""
    for f in ("source.bob.md", "job.bin", "preview.png", "meta.json"):
        (root / f).unlink(missing_ok=True)
    jobs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    for d in jobs[:-2]:
        if d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def load_last() -> dict | None:
    from . import fileio

    root = last_dir()
    ptr = fileio.read_json(_pointer(), {})
    d = root / str(ptr.get("job", "")) if ptr.get("job") else root  # root: a job saved by an older bobina
    if not (d / "meta.json").exists():
        return None
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    meta["source"] = (d / "source.bob.md").read_text(encoding="utf-8")
    meta["data"] = (d / "job.bin").read_bytes()
    meta["preview"] = d / "preview.png"
    return meta


def new_draft(text: str = "") -> Path:
    d = paths.state_dir() / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / time.strftime("draft-%Y%m%d-%H%M%S.bob.md")
    p.write_text(text)
    return p
