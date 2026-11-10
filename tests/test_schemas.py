"""The published JSON schemas (docs/schemas) match what bobina really writes."""

import json
from pathlib import Path

from bobina import cli

SCHEMAS = Path(__file__).resolve().parents[1] / "docs" / "schemas"
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "null": type(None)}


def _check(value, schema, where="$"):
    """The subset these schemas use: type, required, properties, items, enum, const, $ref (local files)."""
    if "$ref" in schema:
        schema = json.loads((SCHEMAS / schema["$ref"]).read_text())
    if "const" in schema:
        assert value == schema["const"], where
    if "enum" in schema:
        assert value in schema["enum"], (where, value)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(isinstance(value, TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
                 for t in types)  # fmt: skip
        assert ok, (where, value, types)
    for key in schema.get("required", []):
        assert key in value, (where, key)
    for key, sub in schema.get("properties", {}).items():
        if isinstance(value, dict) and key in value:
            _check(value[key], sub, f"{where}.{key}")
    if "items" in schema and isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{where}[{i}]")


def _schema(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def test_check_json_matches_its_schema(capsys):
    assert cli.main(["check", "Olá {{ nome }}\n\n```qr {module=2}\nx\n```", "--json"]) == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["problems"]) >= 2
    _check(doc, _schema("check"))


def test_history_lines_match_their_schema(tmp_path):
    from bobina import history

    assert cli.main(["print", "Olá {{ nome }}", "-o", str(tmp_path / "a.bin"), "-q"]) == cli.OK
    for line in history.path().read_text().splitlines():
        _check(json.loads(line), _schema("history"))


def test_problems_json_matches_the_problem_schema(capsys):
    cli.main(["--problems", "json", "check", "Olá {{ nome }}"])
    doc = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    for p in doc["problems"]:
        _check(p, _schema("problem"))


def test_print_and_preview_json_match_their_schemas(tmp_path, capsys):
    doc = "Olá {{ nome }}"
    assert cli.main(["print", doc, "-o", str(tmp_path / "a.bin"), "--json"]) == cli.OK
    _check(json.loads(capsys.readouterr().out), _schema("print"))
    assert cli.main(["print", doc, "--dry-run", "--json"]) == cli.OK
    _check(json.loads(capsys.readouterr().out), _schema("print"))  # stdout is only the JSON, no screen
    assert cli.main(["preview", doc, "-o", str(tmp_path / "a.png"), "--json"]) == cli.OK
    _check(json.loads(capsys.readouterr().out), _schema("preview"))
