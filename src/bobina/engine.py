"""One engine for check, preview, view and print: source text -> rows (+ nudges)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from importlib import resources

from . import escpos, locales, preview, templating
from . import profile as profiles
from .emulator import Emulator
from .layout import Layout
from .model import Document, Paragraph, Run
from .nudges import Nudges
from .parser import parse
from .rows import BitmapRow, FeedRow, QRRow, TextRow

COMMENT = re.compile(r"<!--.*?-->", re.S)


@dataclass
class Result:
    doc: Document
    rows: list
    nudges: Nudges
    profile: profiles.Profile
    rendered: templating.Rendered | None
    allow: set[str] = field(default_factory=set)
    doc_allow: set[str] = field(default_factory=set)  # only what the document says (front matter allow:)

    @cached_property
    def emulator(self) -> Emulator:
        return Emulator(self.profile)

    @cached_property
    def image(self):
        return preview.render(self.rows, self.profile, self.emulator)

    @property
    def all_rows(self) -> list:
        return self.rows

    def page_rows(self, max_h: int | None = None) -> list[list]:
        """The rows split into preview pages (heights only); draw each with preview.render."""
        return preview.split_pages(self.all_rows, self.profile, self.emulator, max_h)

    @cached_property
    def data(self) -> bytes:
        return escpos.encode(self.rows, self.profile, self.emulator)

    @property
    def length_mm(self) -> float:
        return preview.heights(self.rows, self.profile, self.emulator) / (self.profile.dpi / 25.4)

    def stats(self) -> dict:
        native = sum(1 for r in self.rows if isinstance(r, (TextRow, QRRow)) and getattr(r, "native", True))
        raster = sum(1 for r in self.rows if isinstance(r, BitmapRow) or (isinstance(r, TextRow) and not r.native))
        return {
            "length_mm": round(self.length_mm, 1),
            "native_rows": native,
            "raster_rows": raster,
            "bytes": len(self.data),
            "profile": self.profile.id,
            "counters": self.rendered.counters.reserved() if self.rendered else {},
        }

    def visible_nudges(self, doc_only: bool = False):
        """The problems not allowed. doc_only: only the document's own allow: counts (what print --last keeps:
        a command line --allow belongs to its run)."""
        return self.nudges.filtered(self.doc_allow if doc_only else self.allow)

    def commit(self):
        """Call only after the print was confirmed and sent: consumes counter values."""
        if self.rendered:
            self.rendered.counters.commit()

    def release(self):
        """The job will not be printed: reserved counter values go back when nobody took later ones."""
        if self.rendered:
            self.rendered.counters.release()


def template_dirs(base_dir: str):
    from pathlib import Path

    from . import paths

    return [Path(base_dir).resolve(), (paths.config_dir() / "templates").resolve()]


def load_template(name: str, base_dir: str) -> str:
    """A template by name (user folder ~/.config/bobina/templates, then built-in) or a .bob.md path
    inside the document's folder. Paths elsewhere are refused: a shared document cannot pull in
    arbitrary files from the machine that prints it."""
    from pathlib import Path

    from . import paths
    from .nudges import SecurityError

    if name.endswith(".md") or "/" in name or "\\" in name:
        p = Path(name).expanduser()
        p = (p if p.is_absolute() else Path(base_dir) / p).resolve()
        if not any(p.is_relative_to(d) for d in template_dirs(base_dir)):
            raise SecurityError(
                "M315", f"template '{name}' is outside the document folder and ~/.config/bobina/templates"
            )
        if not p.is_file():
            raise ValueError(f"template file not found: {name}")
        return p.read_text(encoding="utf-8")
    user = paths.config_dir() / "templates" / f"{name}.bob.md"
    if user.is_file():
        return user.read_text(encoding="utf-8")
    f = resources.files("bobina") / "templates" / f"{name}.bob.md"
    if not f.is_file():
        raise ValueError(f"unknown template '{name}' (see: bobina template list)")
    return f.read_text(encoding="utf-8")


def template_fields(tmeta: dict) -> dict:
    f = tmeta.get("fields") or {}
    return {k: (v if isinstance(v, dict) else {}) for k, v in f.items()} if isinstance(f, dict) else {}


ASK_SKIP = {"now", "today", "seq", "range", "namespace", "label", "loop", "true", "false", "none"}


def template_names(source: str, base_dir: str = ".") -> set[str] | None:
    """The bare {{ names }} the document (or its template) reads; None when it cannot be parsed (the build
    reports why). Only parses."""
    from jinja2 import meta as jmeta

    try:
        meta, body, _ = templating.split_front_matter(source)
        if meta.get("template"):
            _, body, _ = templating.split_front_matter(load_template(str(meta["template"]), base_dir))
        env = templating.ImmutableSandboxedEnvironment(comment_start_string="<#", comment_end_string="#>")
        return set(jmeta.find_undeclared_variables(env.parse(body)))
    except Exception:  # noqa: BLE001
        return None


def fields_to_ask(source: str, base_dir: str = ".") -> list[tuple[str, dict]]:
    """The fields a document still needs, in order: the template's declared fields (or the document's own
    `fields:`) that the front matter does not set; without a schema, the undeclared {{ variables }}.
    Only parses - nothing is rendered or evaluated."""
    from jinja2 import meta as jmeta

    meta, body, _ = templating.split_front_matter(source)
    schema = template_fields(meta)
    if meta.get("template"):
        tmeta, tbody, _ = templating.split_front_matter(load_template(str(meta["template"]), base_dir))
        schema, body = template_fields(tmeta), tbody
    given = {k for k in meta if k not in templating.RESERVED and k not in ("fields", "template")}
    if schema:
        return [(k, v) for k, v in schema.items() if k not in given]
    env = templating.ImmutableSandboxedEnvironment(comment_start_string="<#", comment_end_string="#>")
    try:
        names = jmeta.find_undeclared_variables(env.parse(body))
    except Exception:  # noqa: BLE001 - a template error is reported by the real build
        return []
    order = {n: body.find(n) for n in names}
    return [(n, {}) for n in sorted(names, key=order.get) if n not in given and n not in ASK_SKIP]


class JobError(ValueError):
    """A job that cannot be built, with its problem code (the CLI reads the code, not the message)."""

    code = "E304"


class JobTooLarge(JobError):
    code = "E305"


class NothingToPrint(JobError):
    code = "E304"


def _note_untested(prof, rows, nudges) -> None:
    """P301 once per label when it uses a feature nobody has seen on paper yet (features.py)."""
    from . import features
    from .profile import plain_ascii
    from .rows import BarcodeRow

    on = set(features.of_profile(prof))
    used = []
    if "codepage" in on and any(isinstance(r, TextRow) and r.native and not all(plain_ascii(c.ch) for c in r.cells)
                                for r in rows):  # fmt: skip
        used.append("codepage")
    if "cutter" in on:
        used.append("cutter")
    if "native-barcode-imported" in on and any(isinstance(r, BarcodeRow) for r in rows):
        used.append("native-barcode-imported")
    if used:
        names = "; ".join(features.FEATURES[u]["title"] for u in used)
        nudges.add("P301", f"not tested on paper yet: {names}", None, "look at the result (docs/TESTED.md)")


def apply_overrides(prof, overrides: dict | None):
    """Per-printer measured values (config) on top of the model profile, e.g. margins.feed_after_dots.
    margins.tear_mm (+ margins.tear_margin_mm) become dots with this profile's dpi: a 180 dpi printer measured with
    calibrate tear must not get 203 dpi dots."""
    over = dict(overrides or {})
    tear_mm = over.pop("margins.tear_mm", None)
    margin_mm = over.pop("margins.tear_margin_mm", None)
    if tear_mm is not None:
        over.setdefault("margins.tear_dots", prof.mm_to_dots(float(tear_mm)))
        if margin_mm is not None:
            over.setdefault("margins.feed_after_dots", prof.mm_to_dots(float(tear_mm) + float(margin_mm)))
    for dotted, v in over.items():
        cur = prof.data
        parts = dotted.split(".")
        for k in parts[:-1]:
            cur = cur.setdefault(k, {})
        cur[parts[-1]] = v
    return prof


def build(
    source: str,
    *,
    base_dir: str = ".",
    profile_name: str | None = None,
    fields: dict | None = None,
    plain: bool = False,
    allow: set[str] | None = None,
    config_profile: str | None = None,
    counters: templating.CounterStore | None = None,
    overrides: dict | None = None,
    net: bool = False,
    row: int | None = None,
    locale=None,
) -> Result:
    """locale: the machine's locale for a document without locale: (a tag, or the CLI's locales.Machine, which
    infers and saves it on first use); None: such a document is English."""
    nudges = Nudges()
    meta, body, fm_lines = templating.split_front_matter(source)
    defaults, labels, schema = {}, None, {}
    if not meta.get("template") and not plain:  # a document that declares its own fields (no template)
        schema = template_fields(meta)
        defaults = {k: v["default"] for k, v in schema.items() if "default" in v}
    doc_keys = set(meta)  # what the document itself set, before the template's front matter joins in
    if meta.get("template") and not plain:
        tmeta, body, fm_lines = templating.split_front_matter(load_template(str(meta["template"]), base_dir))
        schema = template_fields(tmeta)
        labels = tmeta.get("labels")
        defaults = {k: v["default"] for k, v in schema.items() if "default" in v}
        merged = {k: v for k, v in tmeta.items() if k not in ("fields", "labels")}
        merged.update({k: v for k, v in meta.items() if k != "template"})
        meta = merged
    prof = apply_overrides(profiles.load(profile_name or meta.get("profile") or config_profile), overrides)
    rendered, choice = None, None
    if plain:
        doc = Document(meta=meta, base_dir=base_dir, blocks=[Paragraph(line=1, runs=[Run(body.rstrip("\n"))])])
    else:
        body = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), body)  # HTML comments: ignored
        if counters is None:
            counters = templating.CounterStore(meta.get("counters"), nudges)
        else:
            counters.nudges = nudges
            counters.declare(meta.get("counters"))  # this part's own counters: start, format, stop …
        given = {**{k: v for k, v in meta.items() if k not in templating.RESERVED}, **(fields or {})}
        empty_required = set()
        for k, spec in schema.items():
            if spec.get("required") and given.get(k) in (None, "", []):
                empty_required.add(k)
                nudges.add(
                    "M131",
                    (f"data row {row}: " if row else "") + f"required field '{k}' is empty",
                    None,
                    f"set it in front matter or --set {k}=…"
                    + (f" (e.g. {spec['example']})" if spec.get("example") else ""),
                )
        renamed = {old: k for k, spec in schema.items() for old in (spec.get("was") or [])}
        for old in sorted((doc_keys | set(fields or {})) & set(renamed) - set(schema)):
            new = renamed[old]
            nudges.add("M101", f"template field '{old}' was renamed to '{new}': it is ignored", None, f"write {new}:")
        choice = locales.choose(meta, locale)  # plain text has no dates or prices: it never needs one
        for code, msg, hint in choice.notes:
            nudges.add(code, msg, None, hint)
        rendered = templating.render(
            body, meta, nudges, fields=fields, line_offset=fm_lines, counters=counters, defaults=defaults,
            labels=labels, quiet_names=frozenset(empty_required), locale=choice,
        )  # fmt: skip
        doc = parse(rendered.text, nudges, line_offset=fm_lines, base_dir=base_dir, meta=meta)
    rows = Layout(prof, doc, rendered, nudges, net=net, locale=choice).run()
    if doc.blocks and not any(not isinstance(r, FeedRow) for r in rows):
        nudges.add("L105", "nothing printable: every block was skipped", None, "see the warnings above")
    _note_untested(prof, rows, nudges)
    own = meta.get("allow") or []
    if isinstance(own, str):  # allow: L102 or allow: F301,L101, as on the command line
        own = re.split(r"[,\s]+", own)
    own = {str(a).strip() for a in own if str(a).strip()}
    res = Result(doc, rows, nudges, prof, rendered, set(allow or set()) | own, own)
    res.fields = dict(fields or {})  # the values this label was filled with (export names: {column})
    mm = res.length_mm
    if mm > 300:
        nudges.add("L102", f"about {mm / 10:.0f} cm of paper", None, "check the preview first")
    return res


@dataclass
class Batch:
    """Several renders printed as one job (--data rows, --repeat) or identical copies (--copies)."""

    results: list[Result]
    copies: int = 1
    compact: bool = False  # one strip: top margin once, cut lines between labels, tear feed once
    groups: list[int] | None = None  # --then/files: the part of each label (labels = results * copies)
    group_compact: list[bool] | None = None  # per part: are its labels glued with cut lines?

    @property
    def first(self) -> Result:
        return self.results[0]

    @property
    def profile(self):
        return self.first.profile

    SHOW = 12  # labels drawn on the terminal preview of a long job (the PNG preview has them all)

    @property
    def rows(self):
        """Rows for the terminal preview: the whole job, up to SHOW labels, with its cut/tear joins."""
        if len(self.labels) == 1:
            return self.first.rows
        return self._compose(min(len(self.labels), self.SHOW))

    @cached_property
    def labels(self) -> list:
        return self.results * self.copies

    @cached_property
    def joins(self) -> list[str]:
        """What separates label i from label i+1: "cut" (glued, dashed ✂ line) or "tear" (feed to the tear
        bar, then the next label's top margin). Inside a part: its compact flag. Between parts: cut only
        if both parts are compact."""
        n = len(self.labels)
        groups = self.groups or [0] * n
        flags = self.group_compact or [self.compact]
        return ["cut" if flags[groups[i]] and flags[groups[i + 1]] else "tear" for i in range(n - 1)]

    @property
    def stripped(self) -> bool:
        return "cut" in self.joins

    @cached_property
    def strip_rows(self) -> list:
        return self._compose(len(self.labels))

    def _compose(self, n: int) -> list:
        """The first n labels as one strip: each join is a ✂ line (cut) or the tear feed + next top margin."""
        from . import imaging
        from .rows import BitmapRow

        labels = self.labels[:n]
        gap = FeedRow(int(self.profile.get("margins.cut_gap_dots", 6)))  # around the cut line: ~0.75 mm
        rows = [labels[0].rows[0]]
        for i, r in enumerate(labels):
            if i and self.joins[i - 1] == "cut":  # printed only with --marks cut|both; the screen always shows ✂
                if self.profile.get("marks", "none") in ("cut", "both"):
                    line = BitmapRow(imaging.mark_line(self.profile.width_dots), 0, "cut")
                else:
                    line = FeedRow(1, mark="cut")
                rows += [gap, line, gap]
            elif i:
                rows += [labels[i - 1].rows[-1], r.rows[0]]
            rows += r.rows[1:-1]
        rows.append(labels[-1].rows[-1])
        return rows

    @cached_property
    def data(self) -> bytes:
        if self.stripped:
            return escpos.encode(self.strip_rows, self.profile, self.first.emulator)
        return b"".join(r.data for r in self.labels)

    @property
    def all_rows(self) -> list:
        """Every row of the job in paper order (labels one after the other, or the composed strip)."""
        if self.stripped:
            return self.strip_rows
        return [row for r in self.labels for row in r.rows]

    @property
    def image(self):
        """The whole job as one image. Not cached and no per-label copies (one image per label used ~3x the memory
        of the strip): for long jobs use page_rows() + preview.render, one page at a time."""
        return preview.render(self.all_rows, self.profile, self.first.emulator)

    def page_rows(self, max_h: int | None = None) -> list[list]:
        return preview.split_pages(self.all_rows, self.profile, self.first.emulator, max_h)

    @property
    def length_mm(self) -> float:
        if self.stripped:
            return preview.heights(self.strip_rows, self.profile, self.first.emulator) / (self.profile.dpi / 25.4)
        return sum(r.length_mm for r in self.labels)

    def visible_nudges(self, doc_only: bool = False):
        seen, out = set(), []
        for r in self.results:
            for n in r.visible_nudges(doc_only):
                key = (n.code, n.line, n.message, n.source)  # the same warning in two parts is two warnings
                if key not in seen:
                    seen.add(key)
                    out.append(n)
        return out

    def stats(self) -> dict:
        st = dict(self.first.stats())
        st["length_mm"] = round(self.length_mm, 1)
        st["bytes"] = len(self.data)
        st["renders"] = len(self.results)
        st["copies"] = self.copies
        st["counters"] = self.first.rendered.counters.reserved() if self.first.rendered else {}
        return st

    def commit(self):
        seen = set()
        for r in self.results:  # joined parts may have their own counter stores; copies repeat a result
            if id(r) not in seen:
                seen.add(id(r))
                r.commit()

    def release(self):
        for r in {id(r): r for r in self.results}.values():
            r.release()


def join(parts: list[tuple[Batch, int, bool]]) -> Batch:
    """Several documents/batches as one job (bobina print A B --then C): one preview, one confirmation,
    one paper count. parts = (batch, part number, is that part compact); copies are expanded; the first
    profile wins."""
    results, groups, flags = [], [], {}
    for b, g, compact in parts:
        for r in b.results * b.copies:
            results.append(r)
            groups.append(g)
        flags[g] = compact
    if len(results) > 1000:
        raise JobTooLarge("job too large (max 1000 labels)")
    order = sorted(flags)
    remap = {g: i for i, g in enumerate(order)}
    return Batch(results, 1, False, [remap[g] for g in groups], [flags[g] for g in order])


def build_batch(
    source: str,
    *,
    rows_data: list[dict] | None = None,
    repeat: int = 1,
    copies: int = 1,
    row_copies: list[int] | None = None,
    **kw,
) -> Batch:
    """row_copies: identical copies of each data row (0 skips the row); counters advance once per row."""
    if row_copies is not None and rows_data:
        keep = [(r, n) for r, n in zip(rows_data, row_copies, strict=True) if n > 0]
        if not keep:
            raise NothingToPrint("every data row asks 0 copies (--copies-from): nothing to print")
        rows_data, row_copies = [r for r, _ in keep], [n for _, n in keep]
    total = sum(row_copies) if row_copies else len(rows_data or [])
    labels = (total if rows_data else repeat) * copies
    if labels > 1000 or copies > 100:
        raise JobTooLarge(f"job too large: {labels} labels (max 1000, and 100 copies); split it with --rows")
    base_fields = kw.pop("fields", None) or {}  # --set/--ask: they win over a data column (decided 07/11)
    rows = rows_data or [{}]
    from .datasource import LINE

    first = build(source, fields={**rows[0], **base_fields}, row=rows[0].get(LINE, 1) if rows_data else None, **kw)
    kw.pop("counters", None)
    results = [first]
    store = first.rendered.counters if first.rendered else None
    extra = [(i, dict(r)) for i, r in enumerate(rows[1:], 2)] if rows_data else [(None, {}) for _ in range(repeat - 1)]
    for i, r in extra:
        results.append(build(source, fields={**r, **base_fields}, counters=store, row=r.get(LINE, i), **kw))
    if row_copies:
        results = [r for r, n in zip(results, row_copies, strict=True) for _ in range(n)]
    return Batch(results, copies)
