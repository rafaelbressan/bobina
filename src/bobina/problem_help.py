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
    "F304": (
        "Nothing to fix: the font is kept and used offline from now on (bobina fonts scripts). To never download: "
        "bobina config set font_downloads off."
    ),
    "F305": (
        "Get the font once, with the network: bobina fonts get NAME (the message names it; a document works too: "
        "bobina fonts get menu.bob.md). Then it prints offline."
    ),
    "F306": (
        "The dates and numbers are readable, in English with the country's formats (th-TH prints as en-TH). For the "
        "language itself: bobina fonts get LANG (or bobina config set font_downloads on). Another locale: bobina "
        "config set locale TAG, or locale: in the document."
    ),
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
    "Q112": (
        "The message says what the network takes, with an example; bobina help contact lists every network. The rest "
        "prints and the exit code is 9 (--allow Q112: 0)."
    ),
    "Q113": (
        "Nothing to fix: the image prints exactly. For the printer's own code, remove module= (its modules are "
        "always 5 dots) or put less data in it (it prints up to version 7). With render=native, module= and width= "
        "have no effect."
    ),
    # L layout
    "L101": "Add a space or a hyphen to the long word, or use a smaller size.",
    "L102": "Nothing to fix: check the length on the confirmation screen before printing.",
    "L103": "Shorten the line or use a smaller size for the preformatted block.",
    "L104": "Use shorter lines or a smaller size in the rotated block.",
    "L105": "Every block was empty or skipped: see the other problems of this document.",
    "L106": (
        "Read it with the header on the right. orientation=vertical keeps it so without the note; "
        "orientation=horizontal keeps it standing, with narrow wrapped columns."
    ),
    "L107": (
        "Give the columns smaller width= (bobina check lists the width each got), leave one out, use a smaller font "
        "on the table's {…} line ({font=Terminus size=16px}), or turn the table: orientation=vertical."
    ),
    "L108": "Nothing to fix: change a column's width= at the end of its title cell, then check again.",
    "L109": "Shorten the title, or use title-style=band or title-style=inside: they wrap a long title into lines.",
    "L110": (
        "Nothing to fix if that is what you want. With wrap=wrap: to keep the columns on one row, give them smaller "
        "width= or use wrap=nowrap (their content squeezes: text wraps, QR codes and images shrink). More columns "
        "than the paper has letters for (one each, and the gaps): use fewer columns, or gap=0."
    ),
    "L111": (
        "Put fewer boxes, quotes or lists around it: each takes letters from the line, and a box or columns need "
        "some room. Without it, what they hold prints plainly, one block under the other."
    ),
    "L112": (
        "Turned columns are as tall as the paper is wide. Too tall: give the label more length (length=, or "
        "length=auto), use less text or smaller sizes, or wrap=wrap to move a column to a label of its own; a block "
        "drawn smaller: give it a smaller width= or size=. rotate=90 on columns turns their picture: for a label "
        "read sideways write orientation=vertical instead (72 mm long unless length= says)."
    ),
    # I images
    "I101": "Check the path (relative to the document) and that it is an image.",
    "I102": "Nothing to fix; set width= on the image to choose its size.",
    "I103": "Add --allow-net to fetch it, or download the image and use a local path.",
    "I104": "Nothing to fix; a local file avoids the network.",
    "I105": 'Install the optional support: pip install "bobina[pdf]" or "bobina[svg]".',
    "I107": "Write the path between < >: ![alt](<my image.png>).",
    "I106": "Use a public https address or a local file.",
    "I108": 'Trust that folder? Add it to image_dirs in config.toml (image_dirs = ["~/Pictures"]), or move the image'
    " next to the document.",
    "I109": "Nothing to do if it looks right. Otherwise add {.dither} (photo look) or {.threshold} (black and"
    " white); {threshold=60%} sets the cut (higher: more black).",
    "I110": "Nothing to fix if it looks right; a right angle (90, 180, 270) keeps more of its size.",
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
    "E402": "Is the printer on and in range? Through a command (ssh): is that machine on? The message names the printer"
    " and what the command said. Look at the paper before printing again: part of the job may be there.",
    "E403": "Load paper or close the cover (bobina status); a printer without a cover sensor reports both as no paper.",
    "E405": "Wait for the other job, or wait longer: bobina printer set NAME busy_timeout SECONDS.",
    "E406": "Turn the printer on (Bluetooth: in range; USB: plugged in), or name it: bobina init --printer ADDRESS"
    " (or DEVICE), --command 'ssh HOST bobina send --yes -' for one on another machine.",
    "E501": "The message has the line and the template error; often a block not closed: {% if x %} needs {% endif %}.",
    "E601": "Install or log in to one of the AIs the message lists (bobina ai list shows what this machine has),"
    " or use a name from it.",
    "E602": "Read the AI's own reason in the message: log in to it (run claude, codex login, gemini), check the key"
    " or the network, or try again; bobina ai list shows the AIs of this machine.",
    "E701": "Try again when online; the releases are also listed at https://github.com/rafaelbressan/bobina/releases.",
    # P printer and paper
    "P101": "Have a new roll ready; after loading it: bobina paper new LENGTH.",
    "P102": "Load a new roll first (bobina paper new LENGTH), or print fewer labels.",
    "P103": "This roll is for another printer: load one as wide as the profile's paper (57 and 58 mm are the same"
    " rolls), or record it for the printer it fits (--printer).",
    "P301": "The bytes follow the ESC/POS spec but nobody has seen them on paper: look at the result (docs/TESTED.md).",
    "P302": "Scan a printed code with the real app before customers use it, and tell us (docs/TESTED.md).",
    "P303": "Scan a printed code with the real app before you hand it out, and tell us (docs/TESTED.md).",
    "P201": "Raw bytes are sent as they are: make sure they are meant for this printer.",
    "P104": "When you know the roll: bobina paper new 30m (its length) or bobina paper new --diameter 40mm.",
    "P105": "Cut them apart after printing; to tear each one off, print without --compact.",
    "P106": "Run it in a terminal to stop between labels, or leave --step out.",
    "P401": "Install or turn on what the message names, or set up another kind of printer: USB, a printer on"
    " another machine (ssh) or a file printer.",
    "P402": "Check the profile and its paper width: bobina profile list, then bobina init --profile ID (the"
    " message names the other one when the name fits two widths).",
    "P404": "Choose a profile again: bobina init (or bobina init --yes --profile ID); bobina profile list shows them.",
    "P403": "Add the user to the lp group (sudo usermod -aG lp $USER), then log out and in again.",
    # M markup and data
    "M101": "Check the attribute name (bobina help format).",
    "M102": "Use a block type bobina knows (bobina help format); the block printed as plain text.",
    "M103": "Nothing to do yet: the attribute is ignored.",
    "M104": (
        "It prints as written. To keep the table a table on GitHub and Obsidian, use style=header-invert on the "
        "table's {…} line, or the classes at the end of each title cell: | Item {.invert} | Price {.invert} |."
    ),
    "M105": (
        "Add a line of colons only (:::) where the block should end: the message lists what it holds now. A line of "
        "colons always closes the innermost open block."
    ),
    "M120": "Nothing to fix: the value was asked to render as Markdown (| markdown).",
    "M121": "Raw blocks cannot come from a value that is not the author's own: put them in the document.",
    "M122": (
        "Images cannot come from a value that is not the author's own (data, or computed in the template): put the "
        "image in the document or in its front matter."
    ),
    "M123": (
        "A value that is not the author's own (data, or computed in the template) brings text, lists, quotes, tables "
        "and headings only. Code blocks, boxes and link definitions belong in the document or its front matter: put "
        "the fences or ::: lines around {{ value | markdown }}."
    ),
    "M124": "Nothing to fix: they are private-use characters bobina keeps for its own marks; no text needs them.",
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
    "M161": "Use a name from bobina help icons (the message suggests the closest), or write \\: to keep the colons.",
    "M202": "Write the number with digits (24.90, 24,90 or R$ 24,90), or a smaller amount for add().",
    "M203": (
        "Nothing to fix if it is right: documents without locale: use it from now on, even if the machine travels. "
        "Another: bobina config set locale TAG (bobina config get locale shows it)."
    ),
    "M204": (
        "Set this machine's locale: bobina config set locale pt-BR (any BCP 47 tag), or write locale: in the document. "
        "Only a document's own locale: reads a typed 1.890 as a price; elsewhere it is printed as typed (M202)."
    ),
    "M205": "Write a BCP 47 tag (pt-BR, en-US, fr-CA); the message suggests the closest one bobina knows.",
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
