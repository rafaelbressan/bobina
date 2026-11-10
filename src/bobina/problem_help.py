"""What to do about each problem code: `bobina help CODE`, docs/problems/CODE.md and `bobina help --json`.
Every code in nudges.CATALOG has an entry (tests/test_problem_help.py)."""

from __future__ import annotations

FIX = {
    # B drawing
    "B101": "Draw lines at least 2 dots thick (thickness=2), or keep it and silence it with --allow B101.",
    "B102": "Rotate by 90, 180 or 270 degrees for sharp text; other angles are drawn and look jagged.",
    # F fonts
    "F301": "Nothing to fix: the line prints as an image (a little slower). Remove that character to keep it native.",
    "F302": "Pick a font that has the character (bobina fonts list) or replace the character.",
    "F303": "Use a size the printer has natively (small, normal, large, title, huge), or a font size in px (raster).",
    "F201": "Use the font at or above its tested size (bobina fonts list shows tested fonts and their minimum sizes).",
    "F202": "Use a tested font (bobina fonts list), a bigger size or bold.",
    "F203": "Check the font name (bobina fonts list); install the font or use a bundled one.",
    "F204": "Inverted text needs bold and at least 20 px to stay readable.",
    "F205": "Use a font size between 6 and 400 px.",
    # Q codes
    "Q101": "Use a bigger module: ```qr {module=4}``` (3 is the native minimum, 4 in raster).",
    "Q102": "Use error correction M or higher: ```qr {ecc=M}```.",
    "Q103": "Shorten the content or use a smaller module so the QR fits the paper.",
    "Q104": "Shorten the data or use a thinner module; long codes may be turned vertical to fit.",
    "Q105": "Nothing to fix: the printer draws the real barcode; only the preview is approximate.",
    "Q106": "Use another type (code128 works on most printers); bobina draws unsupported types as an image.",
    "Q107": "For phones, prefer code128 or a QR code.",
    "Q108": "Use a module of at least 2 dots.",
    "Q109": "Check the content against the type: digits only for EAN/UPC, the right length and check digit.",
    "Q110": "Nothing to fix; to keep it horizontal, shorten the data or use a thinner module.",
    "Q111": (
        "The message names the attribute and gives a working example; bobina help pay lists every scheme. The rest "
        "prints and the exit code is 9 (--allow Q111: 0)."
    ),
    # L layout
    "L101": "Add a space or a hyphen to the long word, or use a smaller size.",
    "L102": "Nothing to fix: check the length on the confirmation screen before printing.",
    "L103": "Shorten the line or use a smaller size for the preformatted block.",
    "L104": "Use shorter lines or a smaller size in the rotated block.",
    "L105": "Every block was empty or skipped: see the other problems of this document.",
    # I images
    "I101": "Check the path (relative to the document) and that it is an image.",
    "I102": "Nothing to fix; set width= on the image to choose its size.",
    "I103": "Add --allow-net to fetch it, or download the image and use a local path.",
    "I104": "Nothing to fix; a local file avoids the network.",
    "I105": 'Install the optional support: pip install "bobina[pdf]" or "bobina[svg]".',
    "I107": "Write the path between < >: ![alt](<my image.png>).",
    "I106": "Use a public https address or a local file.",
    # E errors
    "E101": "Read the hint in the message and bobina COMMAND --help.",
    "E102": "Give this command one document.",
    "E103": "Give the option once: it applies to the whole job.",
    "E104": "Every --then needs a document after it; a part cannot have both --compact and --no-compact.",
    "E105": "--last and --again take no documents and need an earlier print (bobina history).",
    "E106": "Only one part can read stdin (-): give files for the others.",
    "E107": "Add --yes (scripts, agents, ssh) or run in a terminal; instead of --ask, give the fields with --set.",
    "E201": "Check the path; the message suggests close names.",
    "E202": "Give a .bob.md/.md/.txt document, an image or a PDF.",
    "E203": "Check the image, or the PDF page range (--page N or N-M).",
    "E204": "Add --allow-net to print a network target.",
    "E205": "The document is empty: add content.",
    "E206": "Check the saved label's name (bobina library list).",
    "E207": "Use a name from the list in the message (bobina template list, profile list, fonts list, help).",
    "E208": "Choose another -o, or add --force to replace it; an output never replaces an input of the job.",
    "E209": "The state file named in the message is damaged or busy: wait for the other bobina, or fix or remove it.",
    "E301": "Use CSV, TSV, a JSON list of objects or .xlsx, in UTF-8.",
    "E302": "Check --rows and --where; the file may have only a header.",
    "E303": "Use a column or sheet from the list in the message.",
    "E304": "Use a value in the range or format the message gives.",
    "E305": "Split the job with --rows: at most 1000 labels and 100 copies per job.",
    "E401": "bobina printer add NAME ADDRESS, or --printer with a name from bobina printer list.",
    "E402": "Is the printer on and in range? Look at the paper before printing again: part of the job may be there.",
    "E403": "Load paper or close the cover (bobina status); a printer without a cover sensor reports both as no paper.",
    "E404": "This printer's transport (a file or a command) cannot do that; printing works the same.",
    "E405": "Wait for the other job, or raise busy_timeout for the printer in config.toml.",
    "E501": "The message has the line and the template error; often a block not closed: {% if x %} needs {% endif %}.",
    # P printer and paper
    "P101": "Have a new roll ready; after loading it: bobina paper new LENGTH.",
    "P102": "Load a new roll first (bobina paper new LENGTH), or print fewer labels.",
    "P301": "The bytes follow the ESC/POS spec but nobody has seen them on paper: look at the result (docs/TESTED.md).",
    "P302": "Scan a printed code with the real app before customers use it, and tell us (docs/TESTED.md).",
    "P201": "Raw bytes are sent as they are: make sure they are meant for this printer.",
    # M markup and data
    "M101": "Check the attribute name (bobina help format).",
    "M102": "Use a block type bobina knows (bobina help format); the block printed as plain text.",
    "M103": "Nothing to do yet: the attribute is ignored.",
    "M120": "Nothing to fix: the value was asked to render as Markdown (| markdown).",
    "M121": "Raw blocks cannot come from data: put them in the document.",
    "M122": "Images cannot come from data values: put the image in the document.",
    "M130": "Give the variable a value: front matter, --set NAME=VALUE or a data column (the message lists them).",
    "M131": "Give the required field: --set NAME=VALUE, or fill that column in the row.",
    "M140": "The counter passed its stop: bobina seq set NAME N, a higher stop, or wrap: true.",
    "M150": "Add the missing keys to the joined source, or check --on.",
    "M151": "Remove the repeated keys from the joined source.",
    "M152": "Write source.column ({{ b.category }}) to use the other source's column.",
    "M153": "Fix the row with extra values, or give the empty header a name.",
    "M154": "Rename the repeated column in the header.",
    "M155": "Nothing to fix: refer to the source by its new name (in the message).",
    "M156": "Remove the option: it does nothing here.",
    "M157": "Rename the --set key or the column if both are meant.",
    "M158": "Use the new names in {{ }} (the message maps them), or row['Exact Name'].",
    "M159": "Rename one of the two columns so both get a usable name.",
    "M160": "Open the file in Excel and save it, so formula values are stored.",
    "M202": "Write the number with digits (24.90, 24,90 or R$ 24,90), or a smaller amount for add().",
    "M201": "Use CLDR date patterns (dd/MM/yyyy HH:mm), not Moment.js (DD/MM/YYYY).",
    "M310": "Templates cannot read files: put the content in the document.",
    "M311": 'A counter format takes exactly one {:spec} ("{:d}", "A-{:03}"); other unsafe operations are refused.',
    "M312": "A variable cannot choose a file or image path: write the path in the document.",
    "M313": "Simplify the template: a loop or the output passed bobina's limit.",
    "M314": "Variables cannot be used inside raw blocks.",
    "M315": "Keep template paths inside the allowed folders.",
}

CATEGORY = {"B": "drawing", "F": "fonts", "Q": "codes", "L": "layout", "I": "images", "P": "printer and paper",
            "M": "markup and data", "E": "errors"}  # fmt: skip


def explain(code: str) -> dict | None:
    """Everything bobina knows about a code, or None for an unknown one."""
    from .nudges import CATALOG

    code = code.upper()
    if code not in CATALOG:
        return None
    severity, title, evidence = CATALOG[code]
    return {
        "code": code,
        "severity": severity,
        "category": CATEGORY.get(code[0], ""),
        "title": title,
        "fix": FIX.get(code, ""),
        "evidence": evidence,
        "doc": f"docs/problems/{code}.md",  # in the bobina repository (docs are not installed with the package)
    }
