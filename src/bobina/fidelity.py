"""How close is the preview to the paper? Compares a photo of a printed ticket with its preview.

The photo should show the ticket flat, upright, on a darker background. The paper is found by its straight edges
and its never-inked margins (find_paper), scaled to the paper width, and compared row by row (ink profile) with the
exact bitmap. Output: length error, row-profile correlation, a score, and a side-by-side image."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass
class Report:
    expected_mm: float
    measured_mm: float
    length_error_pct: float
    correlation: float
    score: float

    def lines(self) -> list[str]:
        return [
            f"length: preview {self.expected_mm:.1f} mm · photo {self.measured_mm:.1f} mm "
            f"({self.length_error_pct:+.1f}%)",
            f"row ink profile correlation: {self.correlation:.3f}",
            f"fidelity score: {self.score:.0f}/100",
        ]


def find_paper(photo: Image.Image, exact: Image.Image | None = None, profile=None, paper_mm: float = 58.0):
    """The paper in a photo of a ticket on a darker table.

    Candidates come from the paper's straight edges: x positions where a dark run (the table, or the photo's border
    when the paper touches it) meets a bright run in many rows; a reflection's edge is curved and ink runs are short,
    so they pile up few votes. Each pair of edges gives a box (the rows that show both edges, or a bright margin just
    inside an edge something bright hides; rows across a shadow stay one ticket). With the exact preview the box
    whose print looks most like it (a small 2D grid of the ink) wins: a lamp's reflection or a white strip has no
    print. The length is not used to choose: it is what compare measures. Without a preview, the pair most rows
    agree on, nearest the middle, the narrower of two.
    Before, the box around every bright pixel took the whole photo when the table reflected the lamp (score 0)."""
    g = ImageOps.autocontrast(ImageOps.exif_transpose(photo).convert("L"), cutoff=2)
    boxes = paper_candidates(g)
    if not boxes:
        return g
    if exact is None or profile is None:
        return g.crop(boxes[0])

    grid = (32, min(200, exact.height))  # the print in 2D, small: rows and columns must both look like the preview
    want = list(exact.convert("L").resize(grid, Image.BOX).tobytes())  # once: the same for every box

    def fit(box):
        content, _, _ = _content(g.crop(box), exact, profile, paper_mm)
        return corr(want, list(ImageOps.autocontrast(content).resize(grid, Image.BOX).tobytes()))

    return g.crop(max(boxes, key=fit))


def paper_candidates(g: Image.Image) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1) that may be the paper, the most likely first (see find_paper)."""
    k = max(1, max(g.width, g.height) // 600)  # ~600 px finds a ticket, fast
    small = g.resize((max(1, g.width // k), max(1, g.height // k)))
    w, h = small.size
    thr = _otsu(small.histogram())
    bits = small.point(lambda v: 255 if v > thr else 0).tobytes()
    edges = [_row_edges(bits[y * w : (y + 1) * w], w) for y in range(h)]
    r, tol = max(1, w // 100), max(2, w // 25)
    votes_l, votes_r = [0] * (w + 1), [0] * (w + 1)
    for lefts, rights in edges:
        for x in lefts:
            votes_l[x] += 1
        for x in rights:
            votes_r[x] += 1
    lefts_x, rights_x = _peaks(votes_l, r), _peaks(votes_r, r)

    def side_ok(x: int, inner: int, which: int) -> list[bool]:
        a, b = sorted((x + inner // 2, x + inner * 3 // 2))  # 2–6 % in: inside the never-inked margin
        a, b = max(0, a), min(w, b)
        out = []
        for y, row_edges in enumerate(edges):
            if any(abs(e - x) <= tol for e in row_edges[which]):
                out.append(True)  # the edge itself
            else:  # an edge hidden by something bright beside it: the margin just inside must be bright
                out.append(b > a and bits[y * w + a : y * w + b].count(255) == b - a)
        return out

    pairs = []
    for xl in lefts_x:
        for xr in rights_x:
            if xr - xl < w // 12:
                continue
            m = max(2, (xr - xl) // 25)
            rows = [a and b for a, b in zip(side_ok(xl, m, 0), side_ok(xr, -m, 1), strict=True)]
            strict = [any(abs(e - xl) <= tol for e in L) and any(abs(e - xr) <= tol for e in R) for L, R in edges]
            pairs.append((sum(rows), xl, xr, rows, strict))
    if not pairs:
        return []
    top = max(p[0] for p in pairs)
    # first the pair a photo without a preview would pick: most rows, nearest the middle, the narrower of two; the
    # preview scores every pair (a ticket shorter than a bright strip has fewer rows, and must still be scored)
    pairs.sort(key=lambda p: (p[0] < 0.8 * top, abs((p[1] + p[2]) / 2 - w / 2), p[2] - p[1]))
    boxes = []
    for _, xl, xr, rows, strict in pairs:
        for flags in (rows, strict):  # a bright patch above or below can pass the margin test: try edges only too
            y0, y1 = _one_object(flags, max(1, h // 12))
            if y1 > y0:
                box = (xl * k, y0 * k, xr * k, y1 * k)
                if box not in boxes:
                    boxes.append(box)
    return boxes


def _row_edges(row: bytes, w: int) -> tuple[list[int], list[int]]:
    """(left edges, right edges) of one row: a bright run of w/60 or more next to a dark run of w/40, or to the
    photo's border (the paper may touch it in a tight crop)."""
    dark, bright = max(2, w // 40), max(2, w // 60)
    lefts, rights = [], []
    for s, e in _runs([b == 255 for b in row]):
        if e - s < bright:
            continue
        if s == 0 or (s >= dark and row.count(b"\x00", s - dark, s) == dark):
            lefts.append(s)
        if e == w or (w - e >= dark and row.count(b"\x00", e, e + dark) == dark):
            rights.append(e)
    return lefts, rights


def _peaks(votes: list[int], r: int, n: int = 8) -> list[int]:
    """Up to n edge positions: the strongest smoothed peaks, each at least 3r from the others (one straight edge
    gives a plateau of tied positions; it must not take every slot), placed at the centre of their votes (a tilted
    edge spreads them)."""
    smooth = [sum(votes[max(0, i - r) : i + r + 1]) for i in range(len(votes))]
    taken: list[int] = []
    out: list[int] = []
    for x in sorted(range(len(votes)), key=lambda i: -smooth[i]):
        if not smooth[x] or len(out) == n:
            break
        if all(abs(x - t) > 3 * r for t in taken):
            taken.append(x)
            lo, hi = max(0, x - 3 * r), min(len(votes), x + 3 * r + 1)
            total = sum(votes[lo:hi])
            out.append(round(sum(i * votes[i] for i in range(lo, hi)) / total))
    return sorted(set(out))


def _content(paper: Image.Image, exact: Image.Image, profile, paper_mm: float):
    """(printable area of the paper scaled to the preview, measured mm, expected mm)."""
    W = exact.width
    printable = W / (profile.dpi / 25.4)
    px_per_mm = paper.width / paper_mm
    measured_mm = paper.height / px_per_mm
    expected_mm = exact.height / (profile.dpi / 25.4)
    side = (paper.width - printable * px_per_mm) / 2  # the printable area is centred on the paper
    content = paper.crop((int(side), 0, int(paper.width - side), paper.height)).resize((W, exact.height))
    return content, measured_mm, expected_mm


def _otsu(hist: list[int]) -> int:
    """The grey level that best splits the photo in two (paper and table)."""
    total, everything, below, below_sum, best = sum(hist), sum(i * c for i, c in enumerate(hist)), 0, 0, (0.0, 128)
    for t in range(256):
        below += hist[t]
        if not below or below == total:
            continue
        below_sum += t * hist[t]
        m0, m1 = below_sum / below, (everything - below_sum) / (total - below)
        spread = below * (total - below) * (m0 - m1) ** 2
        if spread > best[0]:
            best = (spread, t)
    return best[1]


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate([*flags, False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i))
            start = None
    return out


def _one_object(flags: list[bool], max_gap: int) -> tuple[int, int]:
    """The longest run of True, joined with the runs around it that are at most max_gap away (a shadow across
    the ticket, a crease)."""
    runs = _runs(flags)
    if not runs:
        return 0, 0
    i = max(range(len(runs)), key=lambda j: runs[j][1] - runs[j][0])
    lo, hi = i, i
    while lo > 0 and runs[lo][0] - runs[lo - 1][1] <= max_gap:
        lo -= 1
    while hi < len(runs) - 1 and runs[hi + 1][0] - runs[hi][1] <= max_gap:
        hi += 1
    return runs[lo][0], runs[hi][1]


def ink_profile(im: Image.Image, rows: int) -> list[float]:
    g = im.convert("L").resize((im.width, rows), Image.BOX)
    data = g.tobytes()
    w = g.width
    return [1 - sum(data[y * w : (y + 1) * w]) / (255 * w) for y in range(rows)]


def corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    if not va or not vb:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (va * vb)


def compare(
    photo: Image.Image, exact: Image.Image, profile, paper_mm: float | None = None
) -> tuple[Report, Image.Image]:
    W = exact.width
    paper_mm = paper_mm or float(profile.get("paper_mm", 58))
    paper = find_paper(photo, exact, profile, paper_mm)
    content, measured_mm, expected_mm = _content(paper, exact, profile, paper_mm)
    rows = min(400, exact.height)
    c = corr(ink_profile(exact, rows), ink_profile(ImageOps.autocontrast(content), rows))
    err = (measured_mm - expected_mm) / expected_mm * 100
    score = max(0.0, min(100.0, 100 * max(0.0, c) - 2 * abs(err)))
    from . import realistic

    real = realistic.render(exact, profile).resize((W, exact.height))
    sheet = Image.new("RGB", (W * 3 + 40, exact.height), (160, 160, 160))
    sheet.paste(exact.convert("RGB"), (0, 0))
    sheet.paste(real, (W + 20, 0))
    sheet.paste(content.convert("RGB"), (2 * W + 40, 0))
    return Report(expected_mm, measured_mm, err, c, score), sheet
