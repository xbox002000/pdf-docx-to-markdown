"""PDF -> LLM-ready markdown using pymupdf4llm (layout mode) + table repair."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import os

import onnxruntime as _ort


def _cpu_budget() -> int:
    """Apify gives 1 vCPU per 4 GB of memory, but ONNX Runtime sees every host core and would
    spawn (and spin) that many threads under a CPU quota. Size the pool to what we really get."""
    env = os.environ.get("ORT_NUM_THREADS")
    if env:
        return max(1, int(env))
    mem = os.environ.get("ACTOR_MEMORY_MBYTES")
    if mem:
        return max(1, int(mem) // 4096)
    return max(1, len(os.sched_getaffinity(0)))


_OrigSession = _ort.InferenceSession


class _BoundedSession(_OrigSession):
    def __init__(self, path_or_bytes, sess_options=None, *args, **kwargs):
        so = sess_options or _ort.SessionOptions()
        so.intra_op_num_threads = _cpu_budget()
        so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        super().__init__(path_or_bytes, so, *args, **kwargs)


_ort.InferenceSession = _BoundedSession

import pymupdf  # noqa: E402
import pymupdf4llm  # noqa: E402

from tables import WordIndex, clean_inline, repair_tables_in_markdown

_PIC_TEXT = re.compile(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", re.S)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class PageMd:
    number: int  # 1-based
    markdown: str


@dataclass
class ConvertedDoc:
    pages: list[PageMd]
    page_count: int
    metadata: dict
    stats: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _clean_heading_line(line: str) -> str:
    m = _HEADING.match(line)
    if not m:
        return line
    text = clean_inline(m.group(2)).replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\w)_(\S.*?\S|\S)_(?!\w)", r"\1", text).strip()
    if text and (text[0].islower() or len(text) > 200):
        return text  # layout model mislabelled a body line as a heading
    return f"{m.group(1)} {text}" if text else ""


def _postprocess_text(md: str, keep_image_text: bool) -> str:
    if not keep_image_text:
        md = _PIC_TEXT.sub("", md)
    out = []
    for line in md.split("\n"):
        line = line.rstrip()
        if line.startswith("#"):
            line = _clean_heading_line(line)
        elif not line.lstrip().startswith("|"):
            line = clean_inline(line)
        out.append(line)
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def convert_pdf(
    path: str,
    *,
    page_range: tuple[int, int] | None = None,
    repair_tables: bool = True,
    keep_image_text: bool = False,
    remove_headers_footers: bool = True,
    password: str | None = None,
) -> ConvertedDoc:
    doc = pymupdf.open(path)
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            raise ValueError("PDF is password-protected; provide the correct `pdfPassword`.")
    total = doc.page_count
    if page_range:
        start = max(1, page_range[0])
        end = min(total, page_range[1] or total)
        pages = list(range(start - 1, end))
    else:
        pages = list(range(total))
    if not pages:
        raise ValueError(f"Page range {page_range} is outside the document (1-{total}).")

    chunks = pymupdf4llm.to_markdown(
        doc,
        pages=pages,
        page_chunks=True,
        header=not remove_headers_footers,
        footer=not remove_headers_footers,
        use_ocr=False,
        show_progress=False,
    )
    stats = {"tables": 0, "tableWordFixes": 0, "tableRowMerges": 0, "tableCaptionsLifted": 0, "scannedPages": []}
    out_pages: list[PageMd] = []
    for pno, ch in zip(pages, chunks):
        page = doc[pno]
        md = ch.get("text", "")
        words = page.get_text("words")
        if len(words) < 3 and page.get_images():
            stats["scannedPages"].append(pno + 1)
        if repair_tables and "|" in md:
            widx = WordIndex([w[4] for w in words])
            md, tstats, ntab = repair_tables_in_markdown(md, widx)
            stats["tables"] += ntab
            stats["tableWordFixes"] += tstats.get("wordFixes", 0)
            stats["tableRowMerges"] += tstats.get("rowMerges", 0)
            stats["tableCaptionsLifted"] += tstats.get("captionsLifted", 0)
        elif "|---" in md:
            stats["tables"] += md.count("|---")
        out_pages.append(PageMd(number=pno + 1, markdown=_postprocess_text(md, keep_image_text)))

    meta = {k: v for k, v in (doc.metadata or {}).items() if v and k not in ("encryption",)}
    toc = doc.get_toc(simple=True)
    if toc:
        meta["outline"] = [{"level": lvl, "title": t, "page": p} for lvl, t, p in toc[:500]]
    warnings = []
    if stats["scannedPages"]:
        warnings.append(
            f"{len(stats['scannedPages'])} page(s) look scanned (image-only, no text layer); "
            "OCR is not enabled in this version, so they produce little or no text."
        )
    doc.close()
    return ConvertedDoc(pages=out_pages, page_count=total, metadata=meta, stats=stats, warnings=warnings)
