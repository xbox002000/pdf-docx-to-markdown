# PDF & DOCX to Markdown — Table Extraction & RAG Chunks

**Convert PDF to Markdown and Word (DOCX) to Markdown — LLM-ready, with tables that stay tables.**
This document parser extracts tables from PDFs, including borderless statistical tables like central-bank releases, as real Markdown tables. Each row keeps its label and every value in its own column, so your LLM, RAG pipeline or vector database reads numbers correctly instead of a run-together string. You also get the heading hierarchy, lists, page markers for citations and, optionally, RAG chunks (page range + section path) ready for embedding.

**Table accuracy, measured on documents we did not tune on:** on two unseen Federal Reserve statistical releases (H.4.1 and G.19, 14 pages, 75 table rows checked), **57 of 75 rows (76%)** came out as correct Markdown rows, versus **23 of 75 (31%)** from the same PDF engine without our table repair. Correct = row label in one cell and every value in its own cell, in order. The scoring method is described below and the source code is public (see *License & source code*).

## What you get

- 📄 **PDF to Markdown and DOCX to Markdown** in one Actor for text-based (digital) PDFs — batch URLs or file uploads
- 📊 **PDF table extraction as real Markdown tables** — words split across columns re-joined, wrapped row labels merged, captions lifted out of headers
- 🧭 **Structure kept** — `#`/`##`/`###` headings, bullet and numbered lists, two-column (academic) reading order
- 🔢 **Page markers** — `<!-- page: 7 -->` so answers can cite pages
- ✂️ **RAG chunks for your vector database** — configurable size and overlap, never split mid-table-row, each chunk tagged with `pageStart`, `pageEnd`, `headingPath`, `chunkIndex`
- 🔒 **No AI API keys, no LLM calls** — deterministic open-source parsing; documents are not sent to any third party
- 💸 **Pay per page** — $0.50 per 1,000 pages + $0.002 per document; failed files pay no document or page fee

## How accurate are the tables?

We count a table row as correct only if its label is in one cell and every value is in its own consecutive cell, in the original order. Ground truth comes from the PDF text layer, independent of the engines tested. All numbers below were measured by us, locally.

| Document | This Actor | Same engine, no table repair |
|---|---|---|
| **Unseen:** Fed H.4.1 (11 pp) + G.19 (3 pp), 75 rows | **57/75 (76%)** | 23/75 (31%)¹ |
| ResNet paper (arXiv 1512.03385), two-column academic, 13 rows | 12/13 | 12/13 |
| CA WARN report, 16 pp, 634 rows | 633/634 | 633/634 |
| Fed H.8, 22 pp, 325 rows — *used during development, so optimistic* | 325/325² | 161/325² |
| Word demo DOCX, 5 tables incl. merged cells, 29 rows | 28/29, no empty header rows, no misaligned rows | – |

¹ The unrepaired engine wraps many numbers in backticks (inline code), which this check counts as not clean. ² Row label may include the document's own line number (`34 Deposits`); with the label required alone in its cell: 255/325 vs 101/325.

**For context — plain open-source extractors on the same files (measured by us with the libraries themselves, not any particular Actor):** `pdf-parse` returns text only, so numbers run together (`8.36.7-0.24.05.3`) and 0 rows qualify; `pdfplumber`'s default table finder detects no table in the borderless Fed H.8 tables and spaces out digits in the CA WARN dates (`0 3 / 2 5 / 2 0 16`), so 0 rows qualify on either file. The ML-based `docling` scored 132/325 on Fed H.8 but needed 11–32 s per page on one CPU core, which is why this Actor doesn't use it.

Speed on one CPU core: ≈0.4–0.5 s per PDF page, ≈0.06 s per DOCX page; peak memory ≈600 MB.

**Known limits:** no OCR yet (scanned pages are flagged in `stats.scannedPages`); some tightly-kerned PDFs lose spaces between words (`LongBeach`); complex multi-row headers can still come out split.

## Use cases

- **RAG / chatbots over documents** — ingest manuals, policies, contracts, research papers and reports with page-cited chunks.
- **Financial & statistical PDFs** — extract tables from PDF statistical releases (e.g. central-bank data) so they stay tabular.
- **Academic papers** — two-column layouts (tested on one arXiv paper so far), tables and section headings preserved.
- **Word to Markdown** — convert DOCX knowledge bases, SOPs and proposals to Markdown for Notion, GitHub, wikis or LLM prompts.
- **AI agents & MCP** — call it from Claude, ChatGPT or any agent via the Apify MCP server / API to "read" a PDF with structure.
- **Automation** — n8n, Make, Zapier: drop a file URL in, get Markdown/chunks out.

## How to use

1. Add PDF/DOCX links in **Document URLs**, or upload files in **Upload files**.
2. Choose **Output**: `Markdown`, `RAG chunks`, or both.
3. Click **Start**. Results appear in the **Dataset** (views: *Documents*, *Markdown*, *RAG chunks*); each document is also saved as a `.md` file in the key-value store.

### Input example

```json
{
  "urls": [
    { "url": "https://www.federalreserve.gov/releases/h8/current/h8.pdf" },
    { "url": "https://arxiv.org/pdf/1512.03385" },
    { "url": "https://calibre-ebook.com/downloads/demos/demo.docx" }
  ],
  "outputFormat": "markdown_and_chunks",
  "chunkSize": 800,
  "chunkOverlap": 100,
  "pageMarkers": "comment"
}
```

| Field | Default | What it does |
|---|---|---|
| `urls` | – | Direct links to PDF/DOCX files (batch) |
| `files` | – | Uploaded files (or URLs / key-value store keys `storeName/key`) |
| `outputFormat` | `markdown` | `markdown`, `chunks`, `markdown_and_chunks` |
| `pageMarkers` | `comment` | `comment` → `<!-- page: N -->`, `text` → `--- Page N ---`, `none` |
| `chunkSize` / `chunkOverlap` | 1000 / 150 | Chunk size and overlap |
| `chunkUnit` | `tokens` | `tokens` (≈4 chars each) or `characters` |
| `prependHeadingPath` | false | Prefix each chunk with `Section: A > B` |
| `pageRange` | all | e.g. `1-10`, `5`, `20-` |
| `maxPagesPerDocument` | 500 | Safety cap per PDF (0 = none) |
| `repairTables` | true | Table repair (see FAQ) |
| `removeHeadersFooters` | true | Drop running headers/footers |
| `includeImageText` | false | Keep text found inside charts |
| `pdfPassword` | – | For encrypted PDFs |

### Output example — document item (abridged, real output)

```json
{
  "type": "document",
  "source": "https://www.federalreserve.gov/releases/h8/current/h8.pdf",
  "fileName": "h8.pdf",
  "format": "pdf",
  "status": "success",
  "title": "FEDERAL RESERVE statistical release",
  "pageCount": 22,
  "pagesConverted": 22,
  "stats": { "tables": 21, "tableWordFixes": 91, "tableRowMerges": 68, "headings": 34, "tokenEstimate": 20431 },
  "markdownKey": "h8-c1d0f36f.md",
  "markdown": "<!-- page: 1 -->\n\n# FEDERAL RESERVE statistical release\n\n..."
}
```

The Markdown for that table:

```markdown
Table 1. Selected Assets and Liabilities of Commercial Banks in the United States^1 ...
Percent change at break adjusted, seasonally adjusted, annual rate

|  | Account | 2021 | 2022 | 2023 | 2024 | 2025 | 2025 Q1 | 2025 Q2 | ... | 2026 Aug |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Bank credit | 8.3 | 6.7 | -0.2 | 4.0 | 5.3 | 2.9 | 6.9 | ... | 4.9 |
| 21 | Credit cards and other revolving plans | 6.8 | 16.7 | 9.4 | 4.7 | 3.4 | 3.0 | 3.0 | ... | 0.3 |
```

What `pdf-parse` (plain-text extraction) returned for the same row, measured by us: `1Bank credit8.36.7-0.24.05.32.96.9...`

### Output example — RAG chunk item

```json
{
  "type": "chunk",
  "source": "https://www.federalreserve.gov/releases/h8/current/h8.pdf",
  "fileName": "h8.pdf",
  "chunkIndex": 2,
  "chunkCount": 35,
  "text": "|  | Account | 2021 | 2022 | ... |\n|---|---|...\n| 34 | Deposits | 11.8 | -0.7 | ...",
  "headingPath": ["FEDERAL RESERVE statistical release", "H.8 ASSETS AND LIABILITIES OF COMMERCIAL BANKS IN THE UNITED STATES"],
  "pageStart": 1,
  "pageEnd": 2,
  "tokenEstimate": 490,
  "containsTable": true
}
```

When a table is larger than one chunk it is split **between rows and the header row is repeated** in every piece, so each chunk is self-explanatory — useful when chunking for vector database ingestion.

## Pricing

Pay per event. Document and page fees are charged only for documents that convert successfully; the tiny Apify start fee applies to every run.

| Event | Price |
|---|---|
| Document converted | $0.002 per PDF/DOCX |
| Page converted | $0.0005 per page ($0.50 / 1,000 pages) |
| Actor start (Apify default synthetic event) | $0.00005 per GB of memory per run ($0.0001 at the default 2 GB) |
| RAG chunks, dataset items, table repair, .md files | included — no per-item charge |
| Failed downloads / unreadable files | no document or page fee |

Examples: a 10-page PDF = **$0.007**, a 20-page report = **$0.012**, 1,000 ten-page PDFs = **$7.00**. DOCX pages are counted from the page count Word stores in the file (or 3,000 characters per page if missing). Use `maxPagesPerDocument` or `pageRange` to cap spend on very long files.

## Integrations

**Python**

```python
from apify_client import ApifyClient
client = ApifyClient("<YOUR_APIFY_TOKEN>")
run = client.actor("uonrV5h4yceYKLxSK").call(run_input={
    "urls": [{"url": "https://arxiv.org/pdf/1512.03385"}],
    "outputFormat": "chunks", "chunkSize": 800, "chunkOverlap": 100,
})
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    if item["type"] == "chunk":
        print(item["pageStart"], item["headingPath"], item["text"][:80])
```

**JavaScript**

```javascript
import { ApifyClient } from 'apify-client';
const client = new ApifyClient({ token: '<YOUR_APIFY_TOKEN>' });
const run = await client.actor('uonrV5h4yceYKLxSK').call({
  urls: [{ url: 'https://arxiv.org/pdf/1512.03385' }], outputFormat: 'markdown',
});
const { items } = await client.dataset(run.defaultDatasetId).listItems();
console.log(items[0].markdown);
```

Also works with **n8n, Make, Zapier, LangChain (`ApifyDatasetLoader`), LlamaIndex** and the **Apify MCP server** for AI agents. The dataset items are plain JSON, so you can load the chunks with LangChain or LlamaIndex and embed them into Pinecone, Qdrant, pgvector or any vector database.

## FAQ

**Does it do OCR on scanned PDFs?**
Not in this version. Pages without a text layer are detected and listed in `stats.scannedPages` with a warning, so you know which files need OCR. OCR is on the roadmap — open an Issue if you need it.

**How does table repair work — can it change my data?**
It never invents text. Words are only re-joined when the joined word physically exists on that PDF page (so `B | ank credit` → `Bank credit`, but `iPhone | sales` is never glued). Wrapped row labels are merged into their data row and table captions that were glued into the header are lifted out. Turn it off with `repairTables: false`.

**Are DOCX page markers exact?**
DOCX files have no fixed pages. We place page markers where Word saved page breaks; otherwise the whole document is one section and the page count comes from the document properties.

**What about merged cells, nested tables and images in Word?**
Merged cells keep the grid aligned (value in the first cell, spanned cells empty); nested tables are flattened into their parent cell; images are dropped (alt text kept) so no base64 blobs pollute your prompts.

**Multi-column papers?**
Supported, but tested on only one two-column arXiv paper (ResNet) so far: a layout model orders the text so paragraphs aren't interleaved across columns, and 12 of its 13 table rows came out clean. Open an Issue if a multi-column file comes out in the wrong order.

**Is this a PDF text extractor too?**
Yes. Set **Output** to `Markdown` and use the text. Unlike a plain PDF text extractor or PDF parser that returns one string per page, table rows stay aligned and headings are kept, so it also works as a general document to Markdown converter.

**Is my data sent to OpenAI or any other AI API?**
No. Everything runs inside the Actor with open-source libraries. Files are only stored in your own Apify storage, under your retention settings.

**Limits?**
Up to 200 MB per file, `maxPagesPerDocument` (default 500) per PDF. Very large Markdown (> 8 MB) is only stored as a `.md` file (`markdownKey`) rather than inside the dataset item.

**Password-protected PDFs?**
Supply `pdfPassword`.

**Something converted badly?**
Open an Issue with a public link to the file — table edge cases are exactly what we want to fix.

## License & source code

This Actor is open source under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see `LICENSE`. The full source code is public: https://github.com/xbox002000/pdf-docx-to-markdown

Open-source components: [PyMuPDF / pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) (AGPL-3.0) for PDF parsing, [mammoth](https://github.com/mwilliamson/python-mammoth) (BSD-2-Clause) for DOCX, Beautiful Soup (MIT).
