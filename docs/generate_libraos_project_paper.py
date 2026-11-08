"""Build the editable two-column DOCX from the paper's HTML source."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).with_name("LibraOS_Project_Paper_Source.html")
OUTPUT = ROOT / "LibraOS_Project_Paper.docx"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("w", W)
ET.register_namespace("r", R)


def tag(name: str) -> str:
    return f"{{{W}}}{name}"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PaperParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, object]] = []
        self.paragraph: list[str] | None = None
        self.paragraph_style = "Body"
        self.table: list[list[str]] | None = None
        self.table_class = ""
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.in_references = False
        self.in_abstract = False

    def handle_starttag(self, name: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        classes = set((attrs.get("class") or "").split())

        if name == "div" and "references" in classes:
            self.in_references = True
        elif name == "div" and "abstract" in classes:
            self.in_abstract = True
        elif name == "table":
            self.table = []
            self.table_class = attrs.get("class") or ""
        elif name == "tr" and self.table is not None:
            self.row = []
        elif name in {"td", "th"} and self.row is not None:
            self.cell = []
        elif name in {"p", "h1", "h2", "h3"}:
            self.paragraph = []
            if name == "h1":
                self.paragraph_style = "Title"
            elif name == "h2":
                self.paragraph_style = "Section"
            elif name == "h3":
                self.paragraph_style = "Subsection"
            elif "byline" in classes:
                self.paragraph_style = "Author"
            elif "keywords" in classes:
                self.paragraph_style = "Keywords"
            elif "caption" in classes:
                self.paragraph_style = "Caption"
            elif "closing-note" in classes:
                self.paragraph_style = "ClosingNote"
            elif self.in_references:
                self.paragraph_style = "Reference"
            else:
                self.paragraph_style = "AbstractText" if self.in_abstract else "Body"
        elif name == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_endtag(self, name: str) -> None:
        if name in {"p", "h1", "h2", "h3"} and self.paragraph is not None:
            text = clean("".join(self.paragraph))
            if text:
                self.blocks.append(("paragraph", (self.paragraph_style, text)))
            self.paragraph = None
        elif name in {"td", "th"} and self.cell is not None and self.row is not None:
            self.row.append("\n".join(clean(line) for line in "".join(self.cell).splitlines()).strip())
            self.cell = None
        elif name == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif name == "table" and self.table is not None:
            self.blocks.append(("table", (self.table_class, self.table)))
            self.table = None
            self.table_class = ""
        elif name == "div" and self.in_references:
            self.in_references = False
        elif name == "div" and self.in_abstract:
            self.in_abstract = False

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)
        elif self.paragraph is not None:
            self.paragraph.append(data)

    def _in_abstract(self) -> bool:
        source_before_paragraph = "".join(self.get_starttag_text() or "")
        return "abstract" in source_before_paragraph


def _paragraph(parent: ET.Element, text: str, style: str) -> ET.Element:
    paragraph = ET.SubElement(parent, tag("p"))
    properties = ET.SubElement(paragraph, tag("pPr"))
    ET.SubElement(properties, tag("pStyle"), {tag("val"): style})
    for index, line in enumerate(text.split("\n")):
        run = ET.SubElement(paragraph, tag("r"))
        if index:
            ET.SubElement(run, tag("br"))
        content = ET.SubElement(run, tag("t"))
        if line.startswith(" ") or line.endswith(" "):
            content.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        content.text = line
    return paragraph


def _section_properties(columns: int, *, continuous: bool = False) -> ET.Element:
    section = ET.Element(tag("sectPr"))
    if continuous:
        ET.SubElement(section, tag("type"), {tag("val"): "continuous"})
    ET.SubElement(
        section,
        tag("pgSz"),
        {tag("w"): "12240", tag("h"): "15840"},
    )
    ET.SubElement(
        section,
        tag("pgMar"),
        {
            tag("top"): "936",
            tag("right"): "893",
            tag("bottom"): "936",
            tag("left"): "893",
            tag("header"): "540",
            tag("footer"): "540",
            tag("gutter"): "0",
        },
    )
    ET.SubElement(
        section,
        tag("cols"),
        {tag("num"): str(columns), tag("space"): "317"},
    )
    return section


def _table(
    parent: ET.Element,
    rows: list[list[str]],
    *,
    figure: bool,
    table_class: str,
) -> None:
    table = ET.SubElement(parent, tag("tbl"))
    properties = ET.SubElement(table, tag("tblPr"))
    full_width = "author-grid" in table_class
    table_width = 10454 if full_width else 5068
    ET.SubElement(properties, tag("tblW"), {tag("w"): str(table_width), tag("type"): "dxa"})
    if full_width:
        ET.SubElement(properties, tag("jc"), {tag("val"): "center"})
    borders = ET.SubElement(properties, tag("tblBorders"))
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        ET.SubElement(
            borders,
            tag(edge),
            {
                tag("val"): "nil" if full_width else "single",
                tag("sz"): "4",
                tag("space"): "0",
                tag("color"): "888888",
            },
        )
    grid = ET.SubElement(table, tag("tblGrid"))
    column_count = max((len(row) for row in rows), default=1)
    widths = [str(table_width // column_count)] * column_count
    widths[-1] = str(table_width - sum(map(int, widths[:-1])))
    for width in widths:
        ET.SubElement(grid, tag("gridCol"), {tag("w"): width})

    for row_index, cells in enumerate(rows):
        row = ET.SubElement(table, tag("tr"))
        if figure:
            ET.SubElement(
                ET.SubElement(row, tag("trPr")),
                tag("trHeight"),
                {tag("val"): "2300", tag("hRule"): "exact"},
            )
        for cell_index, cell_text in enumerate(cells):
            cell = ET.SubElement(row, tag("tc"))
            cell_properties = ET.SubElement(cell, tag("tcPr"))
            ET.SubElement(cell_properties, tag("tcW"), {tag("w"): widths[cell_index], tag("type"): "dxa"})
            if row_index == 0 and not figure and not full_width:
                ET.SubElement(cell_properties, tag("shd"), {tag("fill"): "EEEEEE", tag("val"): "clear"})
            paragraph = _paragraph(cell, cell_text, "TableCell")
            if figure or full_width or (row_index == 0 and not figure):
                p_properties = paragraph.find(tag("pPr"))
                ET.SubElement(p_properties, tag("jc"), {tag("val"): "center"})
            if figure:
                ET.SubElement(cell_properties, tag("vAlign"), {tag("val"): "center"})


def _styles_xml() -> bytes:
    styles = ET.Element(tag("styles"))
    normal = ET.SubElement(styles, tag("style"), {tag("type"): "paragraph", tag("default"): "1", tag("styleId"): "Normal"})
    ET.SubElement(normal, tag("name"), {tag("val"): "Normal"})

    definitions = {
        "Body": (18, False, False, "both", 0, 65, 220),
        "Title": (28, False, False, "center", 0, 80, 240),
        "Author": (17, False, False, "center", 0, 20, 200),
        "Section": (20, True, False, "center", 150, 70, 220),
        "Subsection": (18, True, True, "left", 100, 45, 220),
        "AbstractText": (17, True, False, "both", 70, 35, 205),
        "Keywords": (17, True, False, "left", 40, 100, 205),
        "Caption": (15, False, False, "center", 25, 65, 190),
        "Reference": (17, False, False, "left", 0, 40, 205),
        "ClosingNote": (16, False, False, "left", 90, 0, 190),
        "TableCell": (15, False, False, "left", 0, 0, 190),
    }

    for style_id, (size, bold, italic, alignment, before, after, line) in definitions.items():
        style = ET.SubElement(styles, tag("style"), {tag("type"): "paragraph", tag("styleId"): style_id})
        ET.SubElement(style, tag("name"), {tag("val"): style_id})
        paragraph_properties = ET.SubElement(style, tag("pPr"))
        ET.SubElement(
            paragraph_properties,
            tag("spacing"),
            {
                tag("before"): str(before),
                tag("after"): str(after),
                tag("line"): str(line),
                tag("lineRule"): "auto",
            },
        )
        ET.SubElement(paragraph_properties, tag("jc"), {tag("val"): alignment})
        run_properties = ET.SubElement(style, tag("rPr"))
        ET.SubElement(
            run_properties,
            tag("rFonts"),
            {tag("ascii"): "Times New Roman", tag("hAnsi"): "Times New Roman", tag("cs"): "Times New Roman"},
        )
        ET.SubElement(run_properties, tag("sz"), {tag("val"): str(size)})
        if bold:
            ET.SubElement(run_properties, tag("b"))
        if italic:
            ET.SubElement(run_properties, tag("i"))
    return ET.tostring(styles, encoding="utf-8", xml_declaration=True)


def build() -> None:
    parser = PaperParser()
    parser.feed(SOURCE.read_text(encoding="utf-8"))
    body_start = next(
        index
        for index, (kind, value) in enumerate(parser.blocks)
        if kind == "paragraph" and value[0] == "AbstractText"
    )
    parser.blocks.insert(body_start, ("section-break", None))

    document = ET.Element(tag("document"))
    body = ET.SubElement(document, tag("body"))
    in_body_section = False
    for kind, value in parser.blocks:
        if kind == "section-break":
            break_paragraph = ET.SubElement(body, tag("p"))
            properties = ET.SubElement(break_paragraph, tag("pPr"))
            properties.append(_section_properties(1, continuous=True))
            in_body_section = True
        elif kind == "paragraph":
            style, text = value
            _paragraph(body, text, style)
        else:
            table_class, rows = value
            _table(
                body,
                rows,
                figure="figure-space" in table_class,
                table_class=table_class,
            )

    body.append(_section_properties(2 if in_body_section else 1, continuous=in_body_section))

    relationships = ET.Element(f"{{{REL}}}Relationships")
    ET.SubElement(
        relationships,
        f"{{{REL}}}Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
            "Target": "styles.xml",
        },
    )
    content_types = ET.Element(f"{{{CT}}}Types")
    ET.SubElement(content_types, f"{{{CT}}}Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(content_types, f"{{{CT}}}Default", {"Extension": "xml", "ContentType": "application/xml"})
    ET.SubElement(content_types, f"{{{CT}}}Override", {"PartName": "/word/document.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"})
    ET.SubElement(content_types, f"{{{CT}}}Override", {"PartName": "/word/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"})
    package_relationships = ET.Element(f"{{{REL}}}Relationships")
    ET.SubElement(
        package_relationships,
        f"{{{REL}}}Relationship",
        {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "word/document.xml",
        },
    )

    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ET.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ET.tostring(package_relationships, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", _styles_xml())
        archive.writestr("word/_rels/document.xml.rels", ET.tostring(relationships, encoding="utf-8", xml_declaration=True))


if __name__ == "__main__":
    build()
