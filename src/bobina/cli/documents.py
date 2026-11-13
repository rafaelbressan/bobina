"""Commands that render documents: print, check, preview, view, edit."""

from __future__ import annotations

from pathlib import Path

from .. import config, config_keys, editor, preview, state, view
from .. import profile as profiles
from ..export import is_pattern as export_pattern
from . import common, steps
from .common import (
    CONFIRM,
    LEFT_OUT,
    OK,
    STRICT,
    USAGE,
    Fail,
    ask,
    build,
    confirm_loop,
    do_send,
    err,
    export_labels,
    guard_outputs,
    job_code,
    job_json,
    load_job,
    paper_printer,
    print_json,
    printer_name,
    report_nudges,
    save_image,
    screen,
    summary,
)
from .common import IMAGE_FORMATS as PREVIEW_FORMATS
from .library import starter


def editable(origin: str) -> bool:
    """[e] edit again only for a document file: not stdin/inline text, a multi-part job, a saved @label (the copy
    lives in the library) or an image/PDF target."""
    if origin in ("stdin", "inline", "(chain)") or origin.startswith("@"):
        return False
    p = Path(origin)
    return p.is_file() and p.name.lower().endswith((".bob.md", ".md", ".txt"))


def cmd_print(args):
    """Prints, and records the job in the history whatever happens (bobina history)."""
    from .. import history
    from ..nudges import SecurityError

    rec = history.Recorder(getattr(args, "argv", []))
    try:
        common.refuse_json_on_stdout_output(args)
        code = _print(args, rec)
    except Fail as e:
        rec.finish("failed", e.code, _warned(rec) + e.problems())  # the job's warnings too, as the JSON lists
        _json_failed(args, rec, e.code, e.problems())
        raise
    except SecurityError as e:
        rec.finish("failed", common.SECURITY, _warned(rec) + [e.nudge])
        _json_failed(args, rec, common.SECURITY, [e.nudge])
        raise
    except KeyboardInterrupt:
        rec.finish("interrupted", 130)
        raise
    except Exception as e:  # damaged state or a lock timeout (E209, exit 1 as main gives it), or a bug
        from ..fileio import LockTimeout, StateError
        from ..nudges import Nudge

        known = [Nudge("E209", str(e), severity="error")] if isinstance(e, (StateError, LockTimeout)) else []
        # a bug has no problem code: failed, exit 1, its traceback on stderr
        rec.finish("failed", USAGE, _warned(rec) + known)
        _json_failed(args, rec, USAGE, known)
        raise
    if code == STRICT:  # --last/--again -o set "saved" before the stop: nothing was written
        rec.outcome, rec.saved_to = "", ""
    outcome = {OK: "printed", LEFT_OUT: "printed", CONFIRM: "cancelled", STRICT: "nothing printed (--strict)"}.get(
        code, "failed"
    )
    rec.finish(outcome, code, rec.problems if rec.res is None else None)  # --last: the stored job's problems
    if args.json:
        print_json(_print_json(rec, outcome, code), indent=2, ensure_ascii=False, default=str)
    return code


def _warned(rec) -> list:
    """The warnings of the job a failure interrupted: the built job's, or those kept with a --last job."""
    return list(rec.res.visible_nudges()) if rec.res is not None else list(rec.problems)


def _json_failed(args, rec, code: int, problems: list) -> None:
    """print --json when the job failed: the same object, outcome failed, the error among the problems (the
    prose goes to stderr as always)."""
    if getattr(args, "json", False):
        out = _print_json(rec, "failed", code)  # the job's figures and warnings when it was built, then the error
        out["problems"] = out["problems"] + [n.as_dict() for n in problems]
        print_json(out, indent=2, ensure_ascii=False, default=str)


def _print_json(rec, outcome: str, code: int) -> dict:
    """print --json: what happened to the job, its figures and its problems (docs/schemas/print.schema.json)."""
    out = {
        "schema": "bobina.print/1",
        "outcome": rec.outcome_for(outcome),  # the same word as the history
        "exit": code,
        "printer": rec.printer or None,
        "saved_to": rec.saved_to or None,
    }
    if rec.res is not None:
        return out | job_json(rec.res)
    problems = [n.as_dict() for n in rec.problems]  # --last: the stored job (identical bytes), or the error
    return out | {"stats": rec.summary or {}, "problems": problems}


def _print(args, rec):
    if args.last or args.again:
        if args.target or getattr(args, "chain", None):
            flag = "--last" if args.last else "--again"
            raise Fail(USAGE, f"{flag} reprints the last job; it does not take documents or --then", problem="E105")
        if args.output:  # saved, never printed (also with --dry-run, like print -o): the history says so
            rec.outcome, rec.saved_to = "saved", args.output
        elif args.dry_run:
            rec.outcome = "dry run"
        else:
            rec.outcome = "reprinted" if args.last else ""
        return print_last(args, rec)
    args.reserve_counters = not (args.dry_run or args.output)  # a print takes its seq numbers now
    res, source, base, origin = load_job(args)
    rec.res = res
    try:
        return _print_job(args, rec, res, base, origin)
    finally:
        rec.res.release()  # not printed: the numbers go back (nothing happens after commit)


def _print_job(args, rec, res, base, origin):
    if common.strict_hits(res, args):
        return report_nudges(res, args)
    if args.output and export_pattern(args.output):
        code = report_nudges(res, args)
        if code == STRICT:
            return code
        paths = export_labels(res, args.output, "bytes", args)
        rec.outcome, rec.saved_to = "saved", args.output
        if not args.quiet:
            err(f"wrote {len(paths)} files: {paths[0]} … {paths[-1]} (one per label, nothing printed)")
        return code
    if args.output:
        guard_outputs([args.output], args, explicit=True)
        code = report_nudges(res, args)
        _save_bytes(args, res.data)
        rec.outcome, rec.saved_to = "saved", args.output
        return code
    steps.plan_job(args, res)  # its notes (P105 glued labels, P106 no terminal) are shown with the others
    if args.yes:
        name = paper_printer(args)
        if name:
            from .. import paper

            line = paper.check(name, res.length_mm, res.first.nudges)
            if not args.quiet and not args.dry_run:  # a dry run shows it on its screen
                err(line.strip())
        report_nudges(res, args)
    title = f"preview · {res.profile.id} · {res.profile.get('paper_mm', 58)} mm"
    if args.dry_run:
        if not args.json:  # stdout is the JSON result
            print(screen(res, title, view.use_color() and not args.no_color, args))
        rec.outcome = "dry run"
        return job_code(res)
    rebuild = None
    if editable(origin):

        def rebuild():
            # the whole job again, the same way (load_job: --compact, joins, export names); --ask answers kept
            common.open_editor(origin, args.editor, config.load())
            job, *_ = load_job(args)
            return job

    go, res = confirm_loop(args, res, title, rebuild, note=lambda r: _step_line(args, r))
    rec.res = res
    if not go:
        err("not printed")
        return CONFIRM
    rec.printer = printer_name(args) or ""
    rec.counters = res.stats().get("counters", {})
    name, st = _send_job(args, res, rec)
    rec.printer = name
    _keep_last(res, base, origin, st)
    if not args.quiet:
        err(_printed_line(args, res, name, st))
    return job_code(res)


def _step_line(args, res) -> str:
    every = steps.plan_job(args, res)
    return steps.screen_line(len(steps.labels_of(res)), every) if every else ""


def _send_job(args, res, rec=None):
    """Sends a confirmed job: all at once, or label by label (steps). -> (printer name, steps.Run or None)."""
    every = steps.plan_job(args, res)
    if not every:
        return _send_and_commit(args, res), None
    labels = steps.labels_of(res)
    try:
        names, st = steps.send_labels(args, labels, every, res.profile, do_send)
    except BaseException as e:
        st = e.step_run
        _keep_printed(res, st, rec)
        if isinstance(e, Fail):
            steps.add_summary(e, st, getattr(args, "argv", None), res)
        raise
    _keep_printed(res, st, rec)
    return (names[-1] if names else printer_name(args) or ""), st


def _keep_printed(res, st, rec=None) -> None:
    """The seq numbers of the labels that printed are spent; those after the last printed one go back. A job that
    did not print every label is recorded with what it printed (and only those numbers)."""
    try:
        if hasattr(res, "keep"):
            res.keep(st.printed)
        elif st.printed:
            res.commit()
    except Exception as e:  # noqa: BLE001 - what printed must not turn into an error (it would be printed again)
        err(f"note: the seq numbers of this job could not be updated ({e})")
    if rec is not None and not st.complete:
        if rec.outcome in ("", "printed"):
            rec.outcome = "stopped"
        _record_printed(rec, steps.labels_of(res), st)
        rec.counters = getattr(res, "kept_counters", rec.counters)


def _record_printed(rec, labels: list, st) -> None:
    import hashlib

    rec.labels_printed = len(st.printed)
    rec.printed_mm = round(st.length_mm, 1)
    rec.printed_sha256 = hashlib.sha256(b"".join(labels[i].data for i in sorted(st.printed))).hexdigest()


def _printed_line(args, res, name: str, st) -> str:
    where = common.where(name)
    if st is None:
        return f"printed on {where}: ~{res.length_mm / 10:.1f} cm"
    return steps.summary(st, getattr(args, "argv", None), res, where)


def _send_and_commit(args, res) -> str:
    """Sends; the seq numbers are spent when the job printed, also when only part of it did (decided 07/11:
    rather skip a number than print it twice). When nothing reached the printer they go back (release)."""
    progress: dict = {}
    try:
        name = do_send(args, res.data, res.profile, length_mm=res.length_mm, progress=progress)
    except Fail as e:
        if getattr(e, "partial", False):
            res.commit()
            if res.stats().get("counters"):
                e.args = (e.args[0] + "\n  the seq numbers of this job were used, so they will not repeat",)
        raise
    except BaseException:  # Ctrl-C or a crash
        if progress.get("started"):  # bytes were going out: the job may be on paper, its numbers are spent
            try:
                res.commit()
            except Exception as e:  # noqa: BLE001 - the interruption is what the user must see
                err(f"note: the seq numbers of this job could not be marked as used ({e})")
        raise  # before any byte: the finally of the caller gives the numbers back
    res.commit()
    return name


def _keep_last(res, base: str, origin: str, st=None) -> None:
    """After a print: saving it for --last must not turn the finished print into an error. A job stopped part
    way (steps) keeps only the labels that printed: --last must never print one whose number went back."""
    from .. import fileio

    if not config_keys.read(config.load(), "keep_last", say=err):
        return
    try:
        emulator = res.first.emulator if hasattr(res, "first") else res.emulator
        labels = steps.labels_of(res)
        kept = sorted(st.printed) if st is not None and not st.complete else list(range(len(labels)))
        stats = res.stats()
        if len(kept) == len(labels):
            data, rows = res.data, res.rows
        else:
            data = b"".join(labels[i].data for i in kept)
            rows = [row for i in kept[: res.SHOW] for row in labels[i].rows]
            stats |= {"renders": len(kept), "copies": 1, "bytes": len(data),
                      "length_mm": round(sum(labels[i].length_mm for i in kept), 1)}  # fmt: skip
        if len(kept) > 1 and not getattr(res, "stripped", False):  # where each label ends: --last stops there too
            stats["label_bytes"] = [len(labels[i].data) for i in kept]
            stats["label_mm"] = [round(labels[i].length_mm, 2) for i in kept]
            stats["label_titles"] = [steps.title(labels[i]) for i in kept]  # the pause of --last names them
        # the preview of what the terminal showed (up to SHOW labels), not the whole job: drawing a 1000-label
        # strip after every print doubled its time and memory
        shown = preview.render(rows, res.profile, emulator)
        # what the document allowed stays allowed; a command line --allow belongs to its run (--last brings its own)
        stats["problems"] = [n.as_dict() for n in res.visible_nudges(doc_only=True)]
        state.save_last(res.source_text, base, origin, data, shown, stats)
    except (OSError, fileio.StateError, fileio.LockTimeout) as e:
        err(f"note: this print was not kept for --last ({e})")


def _save_bytes(args, data: bytes, note: str = "") -> None:
    from .. import fileio

    try:
        fileio.write_output(Path(args.output), data)
    except OSError as e:
        raise Fail(USAGE, f"{args.output}: {e.strerror or e} (nothing written)", problem="E208") from None
    if not args.quiet:
        err(f"wrote {len(data)} bytes to {args.output} ({note + ', ' if note else ''}nothing printed)")


def _origin_file(last: dict) -> list[Path]:
    """The document behind the last job, when it was a file: -o must never replace it."""
    origin = last.get("origin") or ""
    if origin in ("stdin", "inline", "(chain)") or origin.startswith("@"):
        return []
    p = Path(origin) if Path(origin).is_absolute() else Path(last.get("base_dir") or ".") / Path(origin).name
    return [p] if p.is_file() else []


def print_last(args, rec=None):
    last = state.load_last()
    if not last:
        raise Fail(USAGE, "nothing printed yet", problem="E105")
    if args.output and export_pattern(args.output):
        flag = "--last" if args.last else "--again"
        raise Fail(USAGE, f"{flag} -o saves the whole job to one file: give a file name, not a {{n}} pattern",
                   problem="E105")  # fmt: skip
    if args.output:
        guard_outputs([args.output], args, explicit=True, extra_inputs=_origin_file(last))
    if args.again:
        if last.get("origin") == "(chain)":
            raise Fail(
                USAGE,
                "--again re-renders one document; a --then job can be reprinted as is with --last",
                problem="E105",
            )
        args.target = None
        args.reserve_counters = not (args.dry_run or args.output)  # saving a file spends no seq numbers
        res = build(args, last["source"], last["base_dir"])
        if rec is not None:
            rec.res = res
        if common.strict_hits(res, args):
            res.release()
            return report_nudges(res, args)  # --strict stops every --again path, as it stops print
        if args.output:  # before --dry-run, as print -o does
            try:
                code = report_nudges(res, args)
                if code == STRICT:
                    return code
                _save_bytes(args, res.data, "re-rendered")
            finally:
                res.release()
            return code
        if args.dry_run:  # re-rendered and shown, never sent
            if not args.json:
                print(screen(res, "again · re-rendered (new now/seq)", view.use_color() and not args.no_color, args))
            return job_code(res)
        steps.plan_job(args, res)  # its notes (P105, P106) are shown with the others
        if args.yes:  # no confirmation screen to show the warnings on (and the reason of exit 9)
            report_nudges(res, args)
        try:
            go, res = confirm_loop(args, res, "again · re-rendered (new now/seq)", note=lambda r: _step_line(args, r))
            if not go:
                err("not printed")
                return CONFIRM
            if rec is not None:
                rec.res = res
            name, st = _send_job(args, res, rec)
            if rec is not None:
                rec.printer = name
        finally:
            res.release()
        _keep_last(res, last["base_dir"], last["origin"], st)
        if not args.quiet:
            err(_printed_line(args, res, name, st) + " (re-rendered)")
        return job_code(res)
    from PIL import Image

    prof = profiles.load(last["stats"].get("profile"))
    st = last["stats"]
    msg = (
        view.image_box(Image.open(last["preview"]), prof, f"last print · {last['printed_at']}")
        + f"\n ~{st['length_mm'] / 10:.1f} cm · identical bytes, counters not consumed again"
        + (
            f" · the preview shows the first 12 of {st['renders'] * st.get('copies', 1)} labels"
            if st.get("renders", 1) * st.get("copies", 1) > 12
            else ""
        )  # fmt: skip
    )
    if rec is not None:  # no render to read it from: the stored job says what it was
        rec.summary = {
            "profile": prof.id,
            "labels": int(st.get("renders", 1)) * int(st.get("copies", 1)),
            "length_mm": round(float(st.get("length_mm", 0)), 1),
            "counters": {},  # identical bytes: no seq numbers were used again
            "bytes_sha256": __import__("hashlib").sha256(last["data"]).hexdigest(),
        }
    from ..nudges import Nudges

    kept = Nudges(_stored_nudge(p) for p in st.get("problems", []) if isinstance(p, dict))  # older jobs kept none
    stored = kept.filtered(common.allow_set(args))  # this run's --allow, as every other print path applies it
    if rec is not None:
        rec.problems = stored
    if common.strict_hits(stored, args):
        if not args.json:
            err("\n".join(common.render_problems(stored, f"{common.stopped() or 'stopped'} (--strict)")))
        return STRICT  # identical bytes with the same warnings: --strict stops them as it did the first time
    left_out = [n for n in stored if n.code in common.LEFT_OUT_CODES]
    code = LEFT_OUT if left_out else OK  # identical bytes: still without the payment code the first print lacked
    if left_out and not args.json:
        err("\n".join(common.render_problems(left_out, "identical bytes, the same as before")))
    if args.output:  # before --dry-run, as print -o does
        _save_bytes(args, last["data"], "identical bytes")
        return code
    if args.dry_run:
        if not args.json:
            print(msg)
        return code
    pieces = _last_labels(last["data"], st)

    def note(code):
        from ..nudges import Nudge

        msg, hint = steps.message(code)
        err("\n".join(common.render_problems([Nudge(code, msg, None, hint)], "")))

    every = steps.plan(args, len(pieces), note=note)
    if not args.yes:
        tty = common.open_tty()
        if tty is None:
            err(msg)
            raise Fail(CONFIRM, "confirmation required: no terminal attached. Re-run with --yes.", problem="E107")
        with tty:
            tty.write(msg + "\n" + (steps.screen_line(len(pieces), every) + "\n" if every else "") + "\n")
            if ask(tty, " [p] print   [q] quit\n> ") not in ("p", "print"):
                err("not printed")
                return CONFIRM
    if every:
        try:
            names, run = steps.send_labels(args, pieces, every, prof, do_send)
        except BaseException as e:
            if rec is not None and not e.step_run.complete:
                _record_printed(rec, pieces, e.step_run)
            if isinstance(e, Fail):
                steps.add_summary(e, e.step_run)
            raise
        name = names[-1]
        if rec is not None:
            rec.printer = name
            if not run.complete:  # still "reprinted": only how many labels went out is said
                _record_printed(rec, pieces, run)
        if not args.quiet:
            err(steps.summary(run, where=common.where(name)) + " (identical bytes)")
        return code
    name = do_send(args, last["data"], prof, length_mm=float(st.get("length_mm", 0)))
    if rec is not None:
        rec.printer = name
    if not args.quiet:
        err(f"reprinted on {common.where(name)}: ~{st.get('length_mm', 0) / 10:.1f} cm (identical bytes)")
    return code


def _last_labels(data: bytes, st: dict) -> list:
    """The labels of the stored job (where each one ends, kept by _keep_last); one piece when it does not say."""
    from types import SimpleNamespace

    sizes, mm = st.get("label_bytes"), st.get("label_mm")
    if not (isinstance(sizes, list) and isinstance(mm, list) and len(sizes) == len(mm) and sum(sizes) == len(data)):
        return [SimpleNamespace(data=data, length_mm=float(st.get("length_mm", 0)), rows=[])]
    titles = st.get("label_titles")
    titles = titles if isinstance(titles, list) and len(titles) == len(sizes) else [""] * len(sizes)
    out, at = [], 0
    for n, length, name in zip(sizes, mm, titles, strict=True):
        out.append(SimpleNamespace(data=data[at : at + n], length_mm=float(length), rows=[], title=str(name)))
        at += n
    return out


def _stored_nudge(p: dict):
    from ..nudges import Nudge

    keys = ("code", "message", "line", "suggestion", "evidence", "severity", "source", "part", "file")
    return Nudge(**{k: p[k] for k in keys if p.get(k) is not None})


def cmd_check(args):
    res, source, base, _ = load_job(args)
    sources = getattr(res, "data_sources", [])  # what {{ }} can use, per part with --data (agents asked for it)
    if args.json:
        out = job_json(res) | ({"data_columns": sources} if sources else {})
        print_json(out, indent=2, ensure_ascii=False)  # problems as --problems json
    else:
        for line in summary(res):
            print(line.strip())
        many = len({d["part"] for d in sources}) > 1 or any(d["part"] > 1 for d in sources)
        for d in sources:
            files = ", ".join(_file_name(s) for s in d["data"])
            where = f", part {d['part']} ({d['document']}: {files})" if many else f" ({files})"
            print(f"data columns{where}: {', '.join(d['columns'])}")
    return report_nudges(res, args)


def default_preview_name(origin: str, args) -> str:
    """DOCUMENT.preview.png in the current folder (preview photo.png -> photo.preview.png)."""
    if origin in ("stdin", "inline", "(chain)"):
        return "preview.png"
    name = Path(origin.lstrip("@")).name
    for ext in (".bob.md", ".md"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    else:
        name = Path(name).stem
    return f"{name}.preview.png"  # never someone's logo.png: only a previous preview of bobina is replaced


def cmd_preview(args):
    common.refuse_json_on_stdout_output(args)
    res, source, base, origin = load_job(args)
    code, files = _preview(args, res, origin)
    if args.json:  # docs/schemas/preview.schema.json
        out = {"schema": "bobina.preview/1", "exit": code, "files": files} | job_json(res)
        print_json(out, indent=2, ensure_ascii=False, default=str)
    return code


def _preview(args, res, origin) -> tuple[int, list[str]]:
    """Writes the preview; (exit code, files written)."""
    if common.strict_hits(res, args):
        return report_nudges(res, args), []  # --strict: nothing is written, like print and check
    if args.output and export_pattern(args.output):
        paths = export_labels(res, args.output, "image", args)
        code = report_nudges(res, args)
        if not args.quiet:
            err(f"wrote {len(paths)} images: {paths[0]} … {paths[-1]} (one per label)")
        return code, [str(x) for x in paths]
    out = args.output or default_preview_name(origin, args)
    if getattr(args, "pages", False):
        guard_outputs([out], args, explicit=bool(args.output))
        if Path(out).suffix.lower() != ".pdf":
            raise Fail(USAGE, "--pages makes a PDF with one page per label: -o FILE.pdf", problem="E208")
        from .. import pdfout

        n = pdfout.write(Path(out), res.labels, res.profile.dpi)  # one page in memory at a time, 1:1 on paper
        code = report_nudges(res, args)
        if not args.quiet:
            err(f"wrote {out} ({n} pages, one per label)")
        return code, [out]
    fmt = Path(out).suffix.lower()
    if fmt not in PREVIEW_FORMATS:
        raise Fail(USAGE, f"cannot save a preview as '{fmt or out}': use {', '.join(PREVIEW_FORMATS)}", problem="E208")
    split = res.page_rows()  # heights once; each page is drawn, saved and dropped
    count = len(split)
    outs = [out] if count == 1 else [part_name(out, k) for k in range(1, count + 1)]
    guard_outputs(outs, args, explicit=bool(args.output))
    if args.realistic:
        from .. import realistic

        draw = lambda im: realistic.render(im, res.profile)  # noqa: E731
    else:
        draw = lambda im: im  # noqa: E731
    width, height = res.profile.width_dots, 0
    em = getattr(res, "first", res).emulator
    for dest, rows in zip(outs, split, strict=True):  # one page in memory at a time
        im = preview.render(rows, res.profile, em)
        height += im.height
        save_image(draw(im), dest)
    code = report_nudges(res, args)
    if args.realistic and not res.profile.get("preview.calibrated", False):
        err("note: realistic preview is an estimate until the profile is calibrated (photo of the R6 ramps)")
    if args.quiet:
        return code, outs
    if count == 1:
        err(f"wrote {out} ({width}x{height} dots, ~{res.length_mm / 10:.1f} cm)")
    else:
        err(
            f"note: the strip is ~{res.length_mm / 1000:.1f} m long, too tall for one image (most viewers stop near "
            f"{preview.MAX_PAGE_DOTS} dots): wrote {count} files of up to "
            f"~{preview.MAX_PAGE_DOTS / res.profile.dpi * 25.4 / 1000:.1f} m, {outs[0]} … {outs[-1]}"
        )
    return code, outs


def part_name(out: str, k: int) -> str:
    """x.preview.png -> x.preview-1.png; strip.png -> strip-1.png."""
    p = Path(out)
    return str(p.with_name(f"{p.stem}-{k}{p.suffix}"))


def cmd_view(args):
    res, source, base, _ = load_job(args)
    print(view.render(res.rows, res.profile, f"view · {res.profile.id}", view.use_color() and not args.no_color))
    for line in summary(res):
        print(line)
    return report_nudges(res, args)


def cmd_edit(args):
    cfg = config.load()
    if args.target:
        path = Path(args.target).expanduser()
        if not path.exists():
            path.write_text(editor.RULER + "\n")
        if args.template and not path.read_text().strip(editor.RULER).strip():
            path.write_text(starter(args.template) + editor.RULER)
    else:
        path = state.new_draft((starter(args.template) if args.template else "") + editor.RULER + "\n")
    while True:
        common.open_editor(path, args.editor, cfg)
        src = path.read_text(encoding="utf-8")
        body = src.replace(editor.RULER, "").strip()
        if not body:
            err(f"empty document, nothing to print ({path})")
            return CONFIRM
        args.reserve_counters = True
        res = build(args, src, str(path.resolve().parent))

        def rebuild():
            common.open_editor(path, args.editor, cfg)
            return build(args, path.read_text(encoding="utf-8"), str(path.resolve().parent))

        # --strict stops before the screen, as print does; --yes has no screen to show the warnings on
        if (common.strict_hits(res, args) or args.yes) and report_nudges(res, args) == STRICT:
            res.release()
            err(f"not printed (kept: {path})")  # a draft lives where the user never named it
            return STRICT
        try:
            go, res = confirm_loop(args, res, f"edit · {path.name}", rebuild)
            if not go:
                err(f"not printed (kept: {path})")
                return CONFIRM
            _send_and_commit(args, res)
        finally:
            res.release()
        _keep_last(res, str(path.resolve().parent), str(path))
        err(f"printed: ~{res.length_mm / 10:.1f} cm")
        return job_code(res)


def _file_name(spec: str) -> str:
    """--data a=/long/path/prices.csv -> a=prices.csv (the name the source is used by, then its file)."""
    name, eq, path = spec.rpartition("=") if "=" in spec else ("", "", spec)
    return f"{name}{eq}{Path(path).name}"
