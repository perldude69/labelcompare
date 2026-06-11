# LabelCompare — TTB Label Verification & Compliance Analysis

LabelCompare is a fully-local tool that helps with OMB No. 1513-0020
(TTB F 5100.31) alcohol label application (COLA) submissions. It lists
scanned PDFs (the form + submitted label artwork), previews them,
performs high-fidelity OCR using local llama.cpp models (GLM-OCR + Qwen),
extracts declarations vs. printed text, and uses LLM analysis of the
captured OCR text — grounded in a local knowledge base of TTB requirements —
to review whether the labels meet core federal labeling rules (27 CFR Parts
4, 5, 7, and 16).

It supports **any** such document, not just specific test files. The health
warning receives a strict deterministic check in addition to the LLM analysis.

The tool performs two complementary reviews:

1. **Form vs. printed label matching** (legacy view): brand, alcohol content,
   and other extracted fields are compared between the application form
   declarations and the actual label artwork text.

2. **Regulatory compliance analysis** (new broadened view): The LLM analyzes
   the full OCR transcript against core TTB mandatory requirements (health
   warning, brand, class/type, net contents, responsible party info, country
   of origin, etc.), grounded in the local `knowledge/ttb_label_requirements.md`
   file. Verbatim evidence quotes and citations are always provided.

The health warning statement receives an additional strict, code-enforced
check (exact statutory 27 CFR 16.21 text present + ALL CAPS requirement).

**All results are aids for human review only.** The raw OCR transcripts are
always available so a compliance agent can verify every LLM finding.

## Architecture

```
browser ──> FastAPI :1776 (this app)
              ├── applications/        any OMB 1513-0020 COLA PDFs + label art
              ├── results.json         cached analysis (filename + mtime)
              ├──> GLM-OCR    :8090    page PNG(s) -> high-fidelity transcripts
              └──> Qwen (text):8080    transcript -> extraction + LLM compliance analysis
```

Pipeline: PyMuPDF renders pages (tolerant of dirty scans) → GLM-OCR produces
verbatim transcripts (multiple views per page for coverage) → Qwen extracts
structured form vs. artwork data and performs grounded compliance analysis
(using the local knowledge base of TTB requirements) → deterministic checks
(especially the strict health warning) + rich result with evidence quotes.

Raw OCR is always stored and displayed for human verification of every finding.
The design combines LLM reasoning over the captured text with code for
bright-line statutory rules.

## Running

Requires two llama.cpp servers already running locally:

- `127.0.0.1:8090` — GLM-OCR (multimodal) — override with `OCR_URL`
- `127.0.0.1:8080` — Qwen2.5-7B-Instruct — override with `QWEN_URL`

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 1776
```

Open `http://<host>:1776/`. Run tests with `.venv/bin/pytest`.

## Using the app

- **Sidebar** lists every PDF in `applications/` with a status badge:
  gray = pending, pulsing blue = analyzing (with stage text), green ✓ =
  pass, red ✗ = fail, amber ! = error.
- Click a PDF to **preview** it; if it was already analyzed, the cached
  result shows instantly (results invalidate automatically if the file
  changes).
- **Analyze** runs the pipeline on the selected PDF; **Batch Analyze** runs
  every PDF sequentially.
- **Upload PDF** (or drag-and-drop onto the sidebar) adds new applications.
  Dirty-but-real PDFs are accepted (`%PDF` anywhere in the first 1KB);
  anything else is rejected.
- The **results panel** shows application vs. label values per field —
  mismatches highlighted red, missing required items amber — plus the
  warning verbatim with its three checks (present / statutory text /
  ALL CAPS).

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/applications` | Sections (`unprocessed`/`validated`/`failed`) with status |
| POST | `/api/applications` | Upload PDFs (multipart, `files`) |
| GET | `/api/applications/{name}/pdf` | Sanitized PDF for preview |
| POST | `/api/applications/{name}/analyze` | Run the pipeline (blocking); auto-sorts to Passed/Failed |
| GET | `/api/applications/{name}/result` | Cached result (404 if none) |
| POST | `/api/applications/{name}/move?to=` | Manual override: move to `validated` or `failed` |
| POST | `/api/applications/{name}/recycle` | Back to unprocessed; clears its result |
| POST | `/api/reset` | Delete all PDFs and results |

Documents are classified into exactly two outcomes — **Passed** (`validated/`)
or **Failed** (`failed/`) — plus the **Un-Processed** inbox. Filenames are
unique across all three sections; collisions get a `-2` suffix and analysis
results follow the file across renames and moves.

## Known limitations

- Analysis is sequential and can take several minutes per document (multiple
  OCR views per page + LLM calls). The 7B-class text model and small OCR
  model have limits on nuance, long context, and OCR accuracy on poor scans.
- The compliance analysis is grounded in a concise local knowledge file
  (`knowledge/ttb_label_requirements.md`) covering the most common mandatory
  elements. It is not exhaustive of all 27 CFR rules, rulings, or commodity-
  specific nuances.
- No authentication; binds to `0.0.0.0` for LAN/trusted-network use only.
- **This is an analysis and triage aid only.** It does not replace TTB review,
  a full legal opinion, or official COLA approval. Humans must always inspect
  the raw OCR transcripts and original artwork. Re-analyze after any change
  to the knowledge file or models.
