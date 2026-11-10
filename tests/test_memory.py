"""Long jobs: the preview is drawn page by page (one page in memory) and split into several files when the strip
is too tall for image viewers; a print keeps only the preview of the labels the terminal showed (for --last).
Measured on 07/11 with 1000 labels: preview 422 MB -> 88 MB, print 425 MB -> 68 MB."""

import resource
import subprocess
import sys

from PIL import Image

from bobina import preview, state
from bobina.cli import main
from bobina.cli.documents import part_name

DOC = "# Pote {{ seq.t }}\nArroz\n"


def test_a_tall_strip_is_split_into_several_files_with_a_note(isolated, monkeypatch, capsys):
    monkeypatch.setattr(preview, "MAX_PAGE_DOTS", 400)
    doc = isolated / "pote.bob.md"
    doc.write_text(DOC)
    assert main(["preview", str(doc), "--repeat", "6", "-o", str(isolated / "tira.png")]) == 0
    files = sorted(isolated.glob("tira-*.png"))
    assert len(files) >= 2 and not (isolated / "tira.png").exists()
    assert "too tall for one image" in capsys.readouterr().err
    heights = [Image.open(f).height for f in files]
    assert all(h <= 400 for h in heights)
    one = isolated / "uma.png"
    monkeypatch.setattr(preview, "MAX_PAGE_DOTS", 10**6)
    assert main(["preview", str(doc), "--repeat", "6", "-o", str(one), "--quiet"]) == 0
    assert sum(heights) == Image.open(one).height  # the pages are the whole strip, nothing lost or repeated


def test_split_files_are_not_replaced_without_force(isolated, monkeypatch):
    monkeypatch.setattr(preview, "MAX_PAGE_DOTS", 400)
    doc = isolated / "pote.bob.md"
    doc.write_text(DOC)
    out = str(isolated / "tira.png")
    assert main(["preview", str(doc), "--repeat", "6", "-o", out, "--quiet"]) == 0
    assert main(["preview", str(doc), "--repeat", "6", "-o", out, "--quiet"]) != 0
    assert main(["preview", str(doc), "--repeat", "6", "-o", out, "--quiet", "--force"]) == 0


def test_previews_are_saved_as_1_bit(isolated):
    doc = isolated / "pote.bob.md"
    doc.write_text(DOC)
    assert main(["preview", str(doc), "-o", str(isolated / "p.png"), "--quiet"]) == 0
    assert Image.open(isolated / "p.png").mode == "1"
    assert main(["preview", str(doc), "-o", str(isolated / "p.jpg"), "--quiet"]) == 0
    assert Image.open(isolated / "p.jpg").mode == "L"  # JPEG has no 1-bit mode


def test_part_names():
    assert part_name("x.preview.png", 2) == "x.preview-2.png"
    assert part_name("out/strip.png", 1) == "out/strip-1.png"


def test_last_keeps_only_the_shown_labels_preview(isolated):
    doc = isolated / "pote.bob.md"
    doc.write_text(DOC)
    cfg = isolated / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "config.toml").write_text(
        f'default_printer = "f"\n[printers.f]\ntransport = "file"\npath = "{isolated / "out.bin"}"\n'
    )
    assert main(["print", "--yes", "--quiet", str(doc), "--repeat", "30"]) == 0
    last = state.load_last()
    shown = Image.open(last["preview"]).height
    assert main(["preview", str(doc), "--repeat", "12", "-o", str(isolated / "p12.png"), "--quiet"]) == 0
    assert shown == Image.open(isolated / "p12.png").height
    assert last["data"] == (isolated / "out.bin").read_bytes()  # --last reprints the whole job


def test_a_long_preview_stays_small_in_memory(isolated):
    """200 labels in a child process: the peak stays far from the old ~0.4 MB per label."""
    doc = isolated / "pote.bob.md"
    doc.write_text(DOC + "\n```qr\nhttps://exemplo.org/{{ seq.t }}\n```\n")
    code = "import sys; from bobina.cli import main; sys.exit(main(sys.argv[1:]))"
    r = subprocess.run(
        [sys.executable, "-c", code, "preview", str(doc), "--repeat", "200", "-o", str(isolated / "t.png"), "--quiet"]
    )
    assert r.returncode == 0
    peak_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    assert peak_mb < 150, f"peak {peak_mb:.0f} MB"
