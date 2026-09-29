"""Markdown table repair.

pymupdf4llm reconstructs table cells from text geometry. On dense statistical
tables (no ruling lines) column boundaries sometimes cut through words
("1 B | ank credit"), wrap labels onto continuation rows, and leave <br>,
bold and empty-column artifacts. These helpers repair a table using the
page's own word list as ground truth: two fragments are only glued together
when the glued string is a real word that exists on that page, so ordinary
adjacent cells ("iPhone" | "sales") are never merged.
"""
from __future__ import annotations

import re

_MD_EMPH = re.compile(r"(\*\*|__|~~|(?<!\w)_(?!\s)|(?<!\s)_(?!\w))")
_TAG = re.compile(r"</?(u|b|i|s|strong|em|span|mark)\b[^>]*>", re.I)
_SUP = re.compile(r"<sup>(.*?)</sup>", re.I)
_SUB = re.compile(r"<sub>(.*?)</sub>", re.I)
_PUNCT_TRAIL = ".,;:)]}%*†‡"
_PUNCT_LEAD = "([{$*"
_CAPTION = re.compile(r"^(Table|Exhibit|Figure|Schedule|Chart)\s+[\w.-]+", re.I)
_NUM = re.compile(r"^[\s$€£¥(+\-–−]*[\d.,]+%?\)?[\s*†‡]*$")


def clean_inline(text: str) -> str:
    text = _SUP.sub(lambda m: "^" + m.group(1).strip("*_ ") if m.group(1).strip("*_ ") else "", text)
    text = _SUB.sub(lambda m: "_" + m.group(1).strip("*_ ") if m.group(1).strip("*_ ") else "", text)
    text = _TAG.sub("", text)
    return text


def _clean_cell_lines(cell: str) -> list[str]:
    cell = clean_inline(cell)
    cell = cell.replace("**", "").replace("~~", "")
    cell = re.sub(r"(?<![\w\\])_(\S(?:.*?\S)?)_(?!\w)", r"\1", cell)  # _italic_
    cell = cell.replace("`", "")  # monospace digits come out as inline code
    cell = re.sub(r"(?<![\w.])([+\-−–])\s+(?=\d)", r"\1", cell)  # "+    4,030" -> "+4,030"
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in re.split(r"<br\s*/?>", cell, flags=re.I)]
    return [ln for ln in lines if ln]


def _strip_word(w: str) -> str:
    return w.strip(_PUNCT_TRAIL + _PUNCT_LEAD + "\"'“”‘’")


class WordIndex:
    """Set of words (and their prefixes) that physically exist on the page."""

    def __init__(self, words: list[str]):
        self.words: set[str] = set()
        self.prefixes: set[str] = set()
        for w in words:
            w = _strip_word(w)
            if len(w) < 2:
                continue
            self.words.add(w)
            for i in range(1, len(w)):
                self.prefixes.add(w[:i])

    def is_word(self, s: str) -> bool:
        return _strip_word(s) in self.words

    def is_prefix(self, s: str) -> bool:
        return _strip_word(s) in self.prefixes


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    # split on unescaped pipes
    return re.split(r"(?<!\\)\|", s)


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", c) for c in cells)


def _first_token(s: str) -> str:
    return s.split(" ", 1)[0] if s else ""


def _last_token(s: str) -> str:
    return s.rsplit(" ", 1)[-1] if s else ""


def _glue_horizontal(grid: list[list[list[str]]], widx: WordIndex) -> int:
    """Fix words cut by a column boundary. Operates line-wise inside cells.

    A fragment chain t + u1 (+ u2 ...) is glued only if the result is a word that
    exists on the page, and never when both t and u1 are already standalone words.
    """
    fixes = 0
    for row in grid:
        ncols = len(row)
        for j in range(ncols - 1):
            for k in range(len(row[j])):
                t = _last_token(row[j][k])
                if not t or not t[-1].isalpha():
                    continue
                chain: list[tuple[int, str]] = []
                acc, best, jj = t, 0, j + 1
                while jj < ncols and k < len(row[jj]):
                    b = row[jj][k]
                    u = _first_token(b)
                    if not u or not u[0].islower():
                        break
                    acc += u
                    chain.append((jj, u))
                    if widx.is_word(acc):
                        best = len(chain)
                    if b.strip() == u and widx.is_prefix(acc):
                        jj += 1
                        continue
                    break
                if not best:
                    continue
                if widx.is_word(t) and widx.is_word(chain[0][1]):
                    continue  # e.g. "in" | "to" -> ambiguous, leave alone
                chain = chain[:best]
                word = t + "".join(u for _, u in chain)
                row[j][k] = row[j][k][: len(row[j][k]) - len(t)].rstrip()
                for idx, (jj, u) in enumerate(chain):
                    rest = row[jj][k][len(u):].lstrip()
                    row[jj][k] = (word + (" " + rest if rest else "")) if idx == len(chain) - 1 else rest
                fixes += 1
    return fixes


def _is_numeric(s: str) -> bool:
    return bool(_NUM.match(s.replace(" ", ""))) if s else False


def _join_fragment(above: str, frag: str, widx: WordIndex) -> str:
    """Append a vertical fragment to the cell above; if that is not a real word, try inserting it
    inside the last token (glyph-order glitches such as 'Jl' + 'u' -> 'Jul')."""
    t = _last_token(above)
    head = above[: len(above) - len(t)]
    if widx.is_word(t + frag):
        return head + t + frag
    for i in range(1, len(t)):
        cand = t[:i] + frag + t[i:]
        if widx.is_word(cand):
            return head + cand
    return head + t + frag


def _merge_continuation_rows(rows: list[list[str]], widx: WordIndex) -> tuple[list[list[str]], int]:
    """Merge label rows that wrapped onto the next line, and vertical word fragments."""
    out: list[list[str]] = []
    fixes = 0
    i = 0
    while i < len(rows):
        row = rows[i]
        if out:
            prev = out[-1]
            n = len(row)
            nonempty = [j for j, c in enumerate(row) if c]
            # (a) vertical fragments: every non-empty cell completes a word cut at the end of the cell above
            frag = [
                j for j in nonempty
                if prev[j] and re.fullmatch(r"[a-z]{1,4}", row[j]) and not widx.is_word(row[j])
            ]
            completes = [j for j in frag if widx.is_word(_last_token(prev[j]) + row[j])]
            if nonempty and len(frag) == len(nonempty) and len(completes) * 2 >= len(frag):
                for j in nonempty:
                    prev[j] = _join_fragment(prev[j], row[j], widx)
                fixes += 1
                i += 1
                continue
            # (b) wrapped label: previous row has text only in leading label cells, current row
            #     continues the label (lowercase start) and carries the values.
            prev_ne = [j for j, c in enumerate(prev) if c]
            if prev_ne and nonempty:
                label_col = max(prev_ne)
                prev_values_empty = all(not prev[j] for j in range(label_col + 1, n))
                cur_lead_empty = all(not row[j] for j in range(0, label_col))
                cont = row[label_col] if label_col < n else ""
                cur_has_values = any(row[j] for j in range(label_col + 1, n))
                if (
                    prev_values_empty and cur_lead_empty and cont
                    and cont[:1].islower() and not _is_numeric(prev[label_col])
                    and cur_has_values and label_col < n - 1
                ):
                    prev[label_col] = (prev[label_col] + " " + cont).strip()
                    for j in range(label_col + 1, n):
                        prev[j] = row[j]
                    fixes += 1
                    i += 1
                    continue
        out.append(list(row))
        i += 1
    return out, fixes


def _drop_empty_columns(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]], int]:
    n = len(header)
    keep = [j for j in range(n) if header[j] or any(j < len(r) and r[j] for r in rows)]
    dropped = n - len(keep)
    return [header[j] for j in keep], [[r[j] if j < len(r) else "" for j in keep] for r in rows], dropped


def _promote_header(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """If the header row is empty (DOCX / some PDFs), use the first non-empty row as header."""
    if any(header) or not rows:
        return header, rows
    return rows[0], rows[1:]


def _esc(c: str) -> str:
    return c.replace("|", "\\|").replace("\n", " ").strip()


def render_table(header: list[str], rows: list[list[str]]) -> str:
    n = max([len(header)] + [len(r) for r in rows]) if (header or rows) else 0
    header = header + [""] * (n - len(header))
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(_esc(c) for c in header) + " |", "|" + "|".join(["---"] * n) + "|"]
    lines += ["| " + " | ".join(_esc(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def repair_table(block: str, widx: WordIndex | None) -> tuple[str, dict]:
    raw_rows = [split_row(ln) for ln in block.strip().splitlines() if ln.strip()]
    raw_rows = [r for r in raw_rows if not is_separator(r)]
    if not raw_rows:
        return block, {}
    width = max(len(r) for r in raw_rows)
    grid = [[_clean_cell_lines(c) for c in r] + [[] for _ in range(width - len(r))] for r in raw_rows]
    stats = {"wordFixes": 0, "rowMerges": 0, "emptyColsDropped": 0}
    widx = widx or WordIndex([])
    stats["wordFixes"] = _glue_horizontal(grid, widx)
    caption = ""
    first_text = " ".join(x for c in grid[0] for x in c if x).strip()
    if len(grid) > 2 and _CAPTION.match(first_text):
        # caption rows glued into the table by the layout engine -> lift out, line by line
        nlines = max(len(c) for c in grid[0])
        caption = "\n".join(
            " ".join(c[k] for c in grid[0] if k < len(c) and c[k]).strip() for k in range(nlines)
        )
        grid = grid[1:]
    rows = [[" ".join(x for x in cell if x).strip() for cell in r] for r in grid]
    rows, stats["rowMerges"] = _merge_continuation_rows(rows, widx)
    header, body = rows[0], rows[1:]
    header, body = _promote_header(header, body)
    header, body, stats["emptyColsDropped"] = _drop_empty_columns(header, body)
    rendered = render_table(header, body)
    if caption:
        rendered = caption + "\n\n" + rendered
        stats["captionsLifted"] = 1
    return rendered, stats


def iter_blocks_with_tables(md: str):
    """Yield (is_table, text) segments of a markdown string."""
    lines = md.split("\n")
    buf: list[str] = []
    tbl: list[str] = []
    for ln in lines:
        if ln.lstrip().startswith("|") and ln.rstrip().endswith("|"):
            if buf:
                yield False, "\n".join(buf)
                buf = []
            tbl.append(ln)
        else:
            if tbl:
                yield True, "\n".join(tbl)
                tbl = []
            buf.append(ln)
    if tbl:
        yield True, "\n".join(tbl)
    if buf:
        yield False, "\n".join(buf)


def repair_tables_in_markdown(md: str, widx: WordIndex | None) -> tuple[str, dict, int]:
    out = []
    totals = {"wordFixes": 0, "rowMerges": 0, "emptyColsDropped": 0, "captionsLifted": 0}
    ntables = 0
    for is_tbl, seg in iter_blocks_with_tables(md):
        if is_tbl:
            fixed, st = repair_table(seg, widx)
            ntables += 1
            for k, v in st.items():
                totals[k] = totals.get(k, 0) + v
            out.append(fixed)
        else:
            out.append(seg)
    return "\n".join(out), totals, ntables
