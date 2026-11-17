"""Print the text of a .docx or .pdf export, whitespace collapsed and wrapped at 100 columns.

Usage: export-text.py <pypdf wheel> <export>. pypdf is imported from the wheel, which the caller
has verified against its pinned SHA-256.
Used by scripts/export-requirements.sh --check to compare a committed export with a regenerated one.
The docx text is read from its XML rather than through pandoc, so the check does not depend on the
tool that wrote the file. List markers are part of the docx text: Word stores them in the numbering
definitions, not in the paragraph, and they carry content - a task list's checkbox (U+2610 or
U+2612) is its bullet, and an ordered list's numbers come from each list's start value.
"""
import sys
import textwrap
import zipfile
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def val(element, child):
    found = element.find(W + child)
    return found.get(W + "val") if found is not None else None


def roman(n):
    out = ""
    for value, letters in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                           (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= value:
            out, n = out + letters, n - value
    return out


def letters(n):
    out = ""
    while n > 0:
        n, rest = divmod(n - 1, 26)
        out = chr(ord("a") + rest) + out
    return out


FORMATS = {
    "lowerLetter": letters,
    "upperLetter": lambda n: letters(n).upper(),
    "lowerRoman": roman,
    "upperRoman": lambda n: roman(n).upper(),
}

# ECMA-376 Part 1 defaults for elements a w:lvl omits: no format, no level text, start 0 (17.9.26)
# and no lvlRestart (17.9.11).
NO_LEVEL = (None, "", 0, None)


def level_of(level):
    """A w:lvl as (format, level text, start, restart), with the defaults above for omitted elements.

    restart is the w:lvlRestart value: None when omitted, 0 when the level never restarts, otherwise
    the one-based level whose items restart it.
    """
    fmt, text, start, restart = val(level, "numFmt"), val(level, "lvlText"), val(level, "start"), val(level, "lvlRestart")
    return (
        fmt,
        text if text is not None else NO_LEVEL[1],
        int(start) if start is not None else NO_LEVEL[2],
        int(restart) if restart is not None else NO_LEVEL[3],
    )


def restarts(definition, deeper, ilvl):
    """Whether an item at ilvl restarts the counter of the deeper level (ECMA-376 Part 1, 17.9.11)."""
    restart = definition.get(str(deeper), NO_LEVEL)[3]
    # An omitted lvlRestart, or one naming this level or a deeper one (which the standard says to
    # ignore), restarts the level after any shallower item, as Word does.
    if restart is None or restart > deeper:
        return True
    # 0 never restarts; otherwise only an item at the named one-based level restarts it.
    return restart != 0 and ilvl == restart - 1


def docx_text(path):
    with zipfile.ZipFile(path) as docx:
        body = ElementTree.fromstring(docx.read("word/document.xml"))
        names = docx.namelist()
        numbering = ElementTree.fromstring(docx.read("word/numbering.xml")) if "word/numbering.xml" in names else None
    # levels[numId][ilvl] = level_of(...) of the level in effect for that list.
    levels = {}
    if numbering is not None:
        abstract = {}
        for definition in numbering.iter(W + "abstractNum"):
            abstract[definition.get(W + "abstractNumId")] = {
                level.get(W + "ilvl"): level_of(level) for level in definition.iter(W + "lvl")
            }
        for num in numbering.iter(W + "num"):
            merged = dict(abstract.get(val(num, "abstractNumId"), {}))
            for override in num.iter(W + "lvlOverride"):
                ilvl = override.get(W + "ilvl")
                # A w:lvl inside the override replaces the abstract level outright (17.9.6): nothing
                # it omits is inherited. startOverride then sets its start.
                replacement = override.find(W + "lvl")
                if replacement is not None:
                    merged[ilvl] = level_of(replacement)
                start = val(override, "startOverride")
                if ilvl in merged and start is not None:
                    merged[ilvl] = merged[ilvl][:2] + (int(start),) + merged[ilvl][3:]
            levels[num.get(W + "numId")] = merged
    counters = {}
    paragraphs = []
    for paragraph in body.iter(W + "p"):
        marker = ""
        num = paragraph.find(f"{W}pPr/{W}numPr")
        if num is not None and val(num, "numId") in levels:
            definition = levels[val(num, "numId")]
            ilvl = int(val(num, "ilvl") or 0)
            count = counters.setdefault(val(num, "numId"), {})
            for deeper in [level for level in count if level > ilvl and restarts(definition, level, ilvl)]:
                del count[deeper]
            fmt, marker, start, _ = definition.get(str(ilvl), NO_LEVEL)
            count[ilvl] = count.get(ilvl, start - 1) + 1
            if fmt != "bullet":
                for level in range(ilvl + 1):
                    level_fmt, _, level_start, _ = definition.get(str(level), NO_LEVEL)
                    number = count.get(level, level_start)
                    marker = marker.replace(f"%{level + 1}", FORMATS.get(level_fmt, str)(number))
        paragraphs.append(marker + " " + "".join(t.text or "" for t in paragraph.iter(W + "t")))
    return " ".join(paragraphs)


def pdf_text(path):
    from pypdf import PdfReader

    return " ".join(page.extract_text() for page in PdfReader(path).pages)


sys.path.insert(0, sys.argv[1])
path = sys.argv[2]
text = docx_text(path) if path.endswith(".docx") else pdf_text(path)
print(textwrap.fill(" ".join(text.split()), 100, break_long_words=False, break_on_hyphens=False))
