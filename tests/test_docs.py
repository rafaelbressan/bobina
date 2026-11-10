"""The docs list every nudge, so a new code cannot ship undocumented."""

from pathlib import Path

from bobina.nudges import CATALOG

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_every_nudge_is_in_the_flow_doc_and_the_format_appendix():
    flow = (DOCS / "diagrams" / "nudges-flow.md").read_text(encoding="utf-8")
    fmt = (DOCS / "FORMAT.md").read_text(encoding="utf-8")
    missing_flow = [c for c in CATALOG if f"`{c}`" not in flow]
    missing_fmt = [c for c in CATALOG if f"`{c}`" not in fmt]
    assert not missing_flow, f"add to docs/diagrams/nudges-flow.md: {missing_flow}"
    assert not missing_fmt, f"add to docs/FORMAT.md appendix: {missing_fmt}"


def test_every_error_raised_by_the_cli_has_a_catalog_code():
    """An error without a code cannot be read by other programs or logged consistently."""
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "bobina"
    missing, unknown = [], []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Fail":
                kw = {k.arg: k.value for k in node.keywords}
                if "problem" not in kw:
                    missing.append(f"{path.name}:{node.lineno}")
                elif isinstance(kw["problem"], ast.Constant) and kw["problem"].value not in (*CATALOG, "MULTI"):
                    unknown.append(f"{path.name}:{node.lineno} {kw['problem'].value}")
    assert not missing, f"Fail(...) without problem=: {missing}"
    assert not unknown, f"problem codes not in nudges.CATALOG: {unknown}"


def test_every_problem_code_written_in_the_source_is_in_the_catalog():
    """Not only Fail(problem=): nudges.add("X"), ImageError("X", …), DataError(…, "X"), SecurityError("X", …) and
    notes tuples ("X", …) too. A code that is not in the catalog has no severity, no docs and no flow entry."""
    import ast
    import re

    code_re = re.compile(r"^[EFILMPQBS]\d{3}$")
    src = Path(__file__).resolve().parents[1] / "src" / "bobina"
    unknown = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            consts = []
            if isinstance(node, ast.Call):
                consts = [a for a in node.args[:2] if isinstance(a, ast.Constant)]
                consts += [k.value for k in node.keywords if k.arg in ("code", "problem")]
            elif isinstance(node, ast.Tuple) and node.elts and isinstance(node.elts[0], ast.Constant):
                consts = [node.elts[0]]
            for c in consts:
                v = getattr(c, "value", None)
                if isinstance(v, str) and code_re.match(v) and v not in CATALOG:
                    unknown.append(f"{path.name}:{node.lineno} {v}")
    assert not unknown, f"problem codes used in the source but not in nudges.CATALOG: {unknown}"
