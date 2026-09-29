"""DOCX -> markdown via mammoth (semantic HTML) + a grid-aware HTML->markdown renderer.

Why not plain markdownify? It emits an empty header row for Word tables, breaks on
colspan/rowspan and nested tables, and keeps base64 images. We render tables ourselves.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

import mammoth
from bs4 import BeautifulSoup, NavigableString, Tag

from tables import render_table

PAGE_TOKEN = "\u27e6PAGEBREAK\u27e7"

STYLE_MAP = """
p[style-name='Title'] => h1:fresh
p[style-name='Subtitle'] => h2:fresh
p[style-name='Heading 1'] => h1:fresh
p[style-name='Heading 2'] => h2:fresh
p[style-name='Heading 3'] => h3:fresh
p[style-name='Heading 4'] => h4:fresh
p[style-name='Heading 5'] => h5:fresh
p[style-name='Heading 6'] => h6:fresh
p[style-name='Quote'] => blockquote:fresh
p[style-name='Intense Quote'] => blockquote:fresh
p[style-name^='toc'] => p.toc:fresh
p[style-name^='TOC'] => p.toc:fresh
"""


@dataclass
class DocxResult:
    pages: list[tuple[int, str]]  # (page number, markdown)
    page_count: int
    page_count_source: str
    metadata: dict
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _inject_page_tokens(data: bytes) -> tuple[bytes, int]:
    """Replace Word page breaks (explicit and last-rendered) with a text token so mammoth keeps them."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    xml = zin.read("word/document.xml").decode("utf-8")
    tok = f"<w:t>{PAGE_TOKEN}</w:t>"
    n = 0

    def _sub(pattern: str, s: str) -> str:
        nonlocal n
        s2, k = re.subn(pattern, tok, s)
        n += k
        return s2

    xml = _sub(r"<w:lastRenderedPageBreak\s*/>", xml)
    xml = _sub(r'<w:br\s+w:type="page"\s*/>', xml)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = xml.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename)
            zout.writestr(item, content)
    return buf.getvalue(), n


def _docx_metadata(data: bytes) -> tuple[dict, int | None]:
    meta: dict = {}
    pages = None
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    if "docProps/core.xml" in names:
        core = z.read("docProps/core.xml").decode("utf-8", "ignore")
        for tag, key in [("dc:title", "title"), ("dc:creator", "author"), ("dc:subject", "subject"),
                         ("cp:keywords", "keywords"), ("dcterms:created", "creationDate"),
                         ("dcterms:modified", "modDate")]:
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", core, re.S)
            if m and m.group(1).strip():
                meta[key] = m.group(1).strip()
    if "docProps/app.xml" in names:
        app = z.read("docProps/app.xml").decode("utf-8", "ignore")
        m = re.search(r"<Pages>(\d+)</Pages>", app)
        if m:
            pages = int(m.group(1))
        m = re.search(r"<Application>(.*?)</Application>", app)
        if m:
            meta["creator"] = m.group(1)
    return meta, pages


def _cell_text(cell: Tag) -> str:
    parts = []
    for el in cell.children:
        if isinstance(el, Tag) and el.name == "table":
            # nested table -> flatten rows as "a / b; c / d"
            rows = []
            for tr in el.find_all("tr"):
                cells = [_inline(td).strip() for td in tr.find_all(["td", "th"], recursive=False)]
                rows.append(" / ".join(c for c in cells if c))
            parts.append("; ".join(r for r in rows if r))
        elif isinstance(el, Tag) and el.name in ("ul", "ol"):
            parts.append("; ".join(_inline(li).strip() for li in el.find_all("li")))
        else:
            parts.append(_inline(el))
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _table_to_md(table: Tag) -> str:
    grid: dict[tuple[int, int], str] = {}
    trs = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    for r, tr in enumerate(trs):
        c = 0
        for td in tr.find_all(["td", "th"], recursive=False):
            while (r, c) in grid:
                c += 1
            text = _cell_text(td)
            cs = int(td.get("colspan", 1) or 1)
            rs = int(td.get("rowspan", 1) or 1)
            for dr in range(rs):
                for dc in range(cs):
                    # merged cells: value in the first cell, spanned cells left empty
                    grid[(r + dr, c + dc)] = text if (dr == 0 and dc == 0) else ""
            c += cs
    if not grid:
        return ""
    nrows = max(r for r, _ in grid) + 1
    ncols = max(c for _, c in grid) + 1
    rows = [[grid.get((r, c), "") for c in range(ncols)] for r in range(nrows)]
    keep = [c for c in range(ncols) if any(rows[r][c] for r in range(nrows))]
    rows = [[row[c] for c in keep] for row in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    return render_table(rows[0], rows[1:])


def _inline(el) -> str:
    if isinstance(el, NavigableString):
        return str(el)
    if not isinstance(el, Tag):
        return ""
    name = el.name
    inner = "".join(_inline(c) for c in el.children)
    marks = {"strong": "**", "b": "**", "em": "*", "i": "*", "s": "~~"}
    if name in marks:
        core = inner.strip()
        if not core:
            return inner
        lead = inner[: len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()):]
        return f"{lead}{marks[name]}{core}{marks[name]}{trail}"
    if name == "sup":
        return f"^{inner.strip()}" if inner.strip() else ""
    if name == "sub":
        return f"_{inner.strip()}" if inner.strip() else ""
    if name == "a":
        href = el.get("href", "")
        if href.startswith("#") or not href:
            return inner
        return f"[{inner.strip()}]({href})"
    if name == "br":
        return " "
    if name == "img":
        alt = el.get("alt", "").strip()
        return f"[Image: {alt}]" if alt else ""
    return inner


def _list_to_md(lst: Tag, depth: int = 0) -> list[str]:
    lines = []
    ordered = lst.name == "ol"
    for i, li in enumerate(lst.find_all("li", recursive=False), 1):
        text_parts, sub = [], []
        for c in li.children:
            if isinstance(c, Tag) and c.name in ("ul", "ol"):
                sub.extend(_list_to_md(c, depth + 1))
            else:
                text_parts.append(_inline(c))
        bullet = f"{i}." if ordered else "-"
        lines.append("  " * depth + f"{bullet} " + re.sub(r"\s+", " ", "".join(text_parts)).strip())
        lines.extend(sub)
    return lines


def _html_to_blocks(html: str) -> tuple[list[str], dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[str] = []
    stats = {"tables": 0, "headings": 0, "lists": 0}
    for el in soup.children:
        if isinstance(el, NavigableString):
            if el.strip():
                blocks.append(el.strip())
            continue
        name = el.name
        if name and re.fullmatch(r"h[1-6]", name):
            text = re.sub(r"\s+", " ", _inline(el)).strip().replace("**", "")
            if PAGE_TOKEN in text:
                blocks.append(PAGE_TOKEN)
                text = text.replace(PAGE_TOKEN, "").strip()
            if text:
                blocks.append("#" * int(name[1]) + " " + text)
                stats["headings"] += 1
        elif name == "table":
            md = _table_to_md(el)
            if PAGE_TOKEN in md:
                md = md.replace(PAGE_TOKEN, "")
            if md:
                blocks.append(md)
                stats["tables"] += 1
        elif name in ("ul", "ol"):
            blocks.append("\n".join(_list_to_md(el)))
            stats["lists"] += 1
        elif name == "blockquote":
            blocks.append("> " + re.sub(r"\s+", " ", _inline(el)).strip())
        elif name == "p" and "toc" in (el.get("class") or []):
            continue  # table of contents entries are noise for LLMs
        else:
            text = re.sub(r"[ \t\r\f\v]+", " ", _inline(el)).strip()
            if text:
                blocks.append(text)
    return blocks, stats


def convert_docx(path: str, *, include_toc: bool = False) -> DocxResult:
    data = open(path, "rb").read()
    meta, app_pages = _docx_metadata(data)
    data2, n_breaks = _inject_page_tokens(data)
    result = mammoth.convert_to_html(
        io.BytesIO(data2),
        style_map=STYLE_MAP,
        convert_image=mammoth.images.img_element(lambda image: {"src": ""}),
    )
    blocks, stats = _html_to_blocks(result.value)
    # split into pages on tokens
    pages: list[tuple[int, str]] = []
    cur: list[str] = []
    pno = 1
    for b in blocks:
        if PAGE_TOKEN in b:
            pieces = b.split(PAGE_TOKEN)
            for i, piece in enumerate(pieces):
                if piece.strip():
                    cur.append(piece.strip())
                if i < len(pieces) - 1:
                    pages.append((pno, "\n\n".join(cur)))
                    cur = []
                    pno += 1
        else:
            cur.append(b)
    pages.append((pno, "\n\n".join(cur)))
    pages = [(n, t) for n, t in pages if t.strip()] or [(1, "")]
    if n_breaks:
        page_count, src = pno, "word-page-breaks"
    elif app_pages:
        page_count, src = app_pages, "docProps/app.xml"
    else:
        chars = sum(len(t) for _, t in pages)
        page_count, src = max(1, -(-chars // 3000)), "estimated-3000-chars-per-page"
    warnings = []
    if not n_breaks:
        warnings.append(
            "DOCX has no stored page breaks; page markers cannot be placed and the page count "
            f"comes from {src}."
        )
    return DocxResult(pages=pages, page_count=page_count, page_count_source=src, metadata=meta,
                      stats=stats, warnings=warnings)
