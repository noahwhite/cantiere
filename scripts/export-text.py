"""Print the text of a .docx or .pdf export, whitespace collapsed and wrapped at 100 columns.

Used by scripts/export-requirements.sh --check to compare a committed export with a regenerated one.
The docx text is read from its XML rather than through pandoc, so the check does not depend on the
tool that wrote the file. List bullets are part of the docx text because pandoc writes a task
list's checkbox (U+2610 or U+2612) as the bullet, not as a character in the paragraph.
"""
import sys
import textwrap
import zipfile
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path):
    with zipfile.ZipFile(path) as docx:
        body = ElementTree.fromstring(docx.read("word/document.xml"))
        names = docx.namelist()
        numbering = ElementTree.fromstring(docx.read("word/numbering.xml")) if "word/numbering.xml" in names else None
    bullets = {}
    if numbering is not None:
        abstract = {}
        for definition in numbering.iter(W + "abstractNum"):
            levels = {}
            for level in definition.iter(W + "lvl"):
                fmt, text = level.find(W + "numFmt"), level.find(W + "lvlText")
                if fmt is not None and fmt.get(W + "val") == "bullet" and text is not None:
                    levels[level.get(W + "ilvl")] = text.get(W + "val")
            abstract[definition.get(W + "abstractNumId")] = levels
        for num in numbering.iter(W + "num"):
            bullets[num.get(W + "numId")] = abstract.get(num.find(W + "abstractNumId").get(W + "val"), {})
    paragraphs = []
    for paragraph in body.iter(W + "p"):
        marker = ""
        num = paragraph.find(f"{W}pPr/{W}numPr")
        if num is not None and num.find(W + "numId") is not None:
            level = num.find(W + "ilvl")
            marker = bullets.get(num.find(W + "numId").get(W + "val"), {}).get(level.get(W + "val") if level is not None else "0", "")
        paragraphs.append(marker + " " + "".join(t.text or "" for t in paragraph.iter(W + "t")))
    return " ".join(paragraphs)


def pdf_text(path):
    from pypdf import PdfReader

    return " ".join(page.extract_text() for page in PdfReader(path).pages)


path = sys.argv[1]
text = docx_text(path) if path.endswith(".docx") else pdf_text(path)
print(textwrap.fill(" ".join(text.split()), 100, break_long_words=False, break_on_hyphens=False))
