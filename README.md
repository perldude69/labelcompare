# LabelCompare — TTB Label Verification & Compliance Analysis

LabelCompare is a tool that helps process OMB No. 1513-0020
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

1. **Form vs. printed label matching**: brand, alcohol content,
   and other extracted fields are compared between the application form
   declarations and the actual label artwork text. Postprocessing fixes
   known LLM extraction bugs (value leakage, marker duplication, missing
   form-backfill).

2. **Regulatory compliance analysis**: The LLM analyzes
   the full OCR transcript against core TTB mandatory requirements,
   grounded in the `knowledge/ttb_label_requirements.md`
   file. Verbatim evidence quotes and citations are always provided.

The health warning statement receives an additional strict, code-enforced
check (exact statutory 27 CFR 16.21 text present + ALL CAPS requirement).

**All results are aids for human review only.** The raw OCR transcripts are
always available so a compliance agent can verify every LLM finding.

## Approach

LabelCompare combines **deterministic code checks** with **LLM reasoning**
over captured OCR text:

- **Two-pronged review.** A code-level verifier (`verify.py`) performs strict
  field matching (brand containment, ABV numeric comparison, exact health warning
  text + casing). Separately, a knowledge-grounded LLM prompt analyzes the full
  transcript against TTB requirements from `knowledge/ttb_label_requirements.md`,
  producing verbatim evidence quotes and citations for every finding.

- **Multi-view OCR.** Each PDF page is rendered as three overlapping crops
  (full page, upper region, lower region) so that dense form fields and the label
  artwork — typically in the lower third — each get a dedicated high-detail view.
  The small vision model skips columns on single full-page renders.

- **LLM postprocessing.** Three known extraction failure modes are fixed
  deterministically in `postprocess.py`: marker lists duplicated across form and
  label, application-form values leaked into the label object, and missing
  brand declarations backfilled from form-context lines. The label leakage guard
  was hardened to use the separated label-artwork text as ground truth.

- **Bright-line rules in code, nuance in LLM.** The health warning (27 CFR 16.21)
  is a precise statutory string — enforced deterministically. Broader compliance
  questions (class/type accuracy, net contents format, country of origin) are
  left to the LLM with the knowledge base as grounding.

- **Progressive UI feedback.** A polling loop renders a percentage-mapped progress
  bar and live stage text during analysis. Batch mode shows a "File N of M"
  counter. The analyzing badge pulses via CSS animation.

## Tools

| Tool | Role |
|---|---|
| **FastAPI** (Python) | Web server, API routing, pipeline orchestration |
| **PyMuPDF** (fitz) | PDF parsing, page rendering to PNG, sanitize-dirty-PDFs |
| **Pillow** | Image preprocessing (grayscale, contrast, sharpen, resize) |
| **httpx** | HTTP client for llama.cpp API calls |
| **GLM-OCR** (llama.cpp :8090) | Multimodal vision model — image→verbatim text transcription |
| **Qwen2.5-7B-Instruct** (llama.cpp :8080) | Text model — field extraction (JSON schema) + compliance analysis |
| **Vanilla JS/CSS/HTML** | Frontend — no frameworks, single-file `app.js` with `$()` shorthand |
| **pytest** | Test suite — FastAPI TestClient, monkeypatch mocks for all LLM calls |

## Assumptions

- **Input format.** PDFs are scans of OMB No. 1513-0020 (TTB F 5100.31)
  submissions: a typed application form with attached label artwork.
- **Page layout.** The form occupies the upper portion of the page; the label
  artwork occupies the lower portion. The three-view render (full / upper crop /
  lower crop) relies on this structure for coverage.
- **LLM marker separation.** The extraction model returns `label_markers` and
  `form_markers` arrays identifying which OCR views belong to which source.
  Postprocessing corrects the common duplication case; the deterministic
  line-based fallback covers the rest.
- **Health warning.** Must match the exact statutory text from 27 CFR 16.21
  and be rendered in ALL CAPS. The check is case-sensitive — the only field
  with this requirement.
- **File identity.** PDF filenames are unique across all three sections
  (unprocessed, validated, failed). Renames and moves preserve analysis results
  via `store.rename()`.
- **Single-user / local.** No authentication, no multi-tenancy. The analysis
  lock enforces one-at-a-time execution (shared GPU/CPU). Bind to localhost and
  use a reverse proxy for remote access.
- **Model availability.** Two llama.cpp servers are expected on the same host.
  OCR and Qwen URLs are overridable via `OCR_URL` and `QWEN_URL` env vars.
- **Human-in-the-loop.** This tool aids triage; it does not replace TTB review
  or legal judgment. Raw OCR transcripts and original PDFs are always accessible.

## Architecture

```
browser ──> nginx :443 (optional reverse proxy)
              └──> FastAPI :1776 (this app)
                     ├── applications/        any OMB 1513-0020 COLA PDFs
                     ├── results.json         cached analysis (filename + mtime)
                     ├──> GLM-OCR    :8090    page PNG(s) -> transcripts
                     └──> Qwen (text):8080    transcript -> extraction + analysis
```

Pipeline: PyMuPDF renders pages (tolerant of dirty scans, 3 views per page
for coverage) → GLM-OCR produces verbatim transcripts → Qwen extracts
structured form vs. artwork data and performs grounded compliance analysis
→ deterministic postprocessing fixes LLM extraction bugs → code-enforced
checks (health warning strict match) → rich result with evidence quotes.

Raw OCR is always stored and displayed for human verification of every finding.

## Running

Requires two llama.cpp servers already running locally:

- `127.0.0.1:8090` — GLM-OCR (multimodal) — override with `OCR_URL`
- `127.0.0.1:8080` — Qwen2.5-7B-Instruct — override with `QWEN_URL`

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 1776
```

Open `http://localhost:1776/`. Run tests with `.venv/bin/pytest`.

### Reverse proxy (nginx)

To serve under a path prefix like `/labelcompare/`:

```nginx
location ^~ /labelcompare/ {
    rewrite ^/labelcompare(/.*)$ $1 break;
    proxy_pass http://127.0.0.1:1776;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

The frontend auto-detects the `/labelcompare` prefix from `window.location.pathname`
and adjusts all API calls accordingly. Static assets use relative paths.

## Using the app

- **Sidebar** (left) lists every PDF in `applications/` with a status badge:
  gray = pending, pulsing blue = analyzing, green ✓ = pass, red ✗ = fail,
  amber ! = error.
- Click a PDF to **preview** it on the right; if it was already analyzed,
  cached results appear instantly in the center panel (results invalidate
  automatically if the file changes).
- **Analyze** runs the pipeline on the selected PDF; a progress bar with
  live stage text appears in the center panel during analysis.
- **Batch Analyze** runs every unprocessed PDF sequentially with a
  "File N of M" counter.
- **Upload PDF** (or drag-and-drop onto the sidebar) adds new applications.
  Dirty-but-real PDFs are accepted (`%PDF` anywhere in the first 1KB).
- The **results panel** (center) shows application vs. label values per
  field — mismatches highlighted red, missing required items amber — plus
  the warning verbatim with its three checks (present / statutory text /
  ALL CAPS). Compliance findings are in a collapsible section below.
- Three-column layout is resizable by dragging the handles.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/applications` | Sections (`unprocessed`/`validated`/`failed`) with status and progress |
| POST | `/api/applications` | Upload PDFs (multipart, `files`) |
| GET | `/api/applications/{name}/pdf` | Sanitized PDF for preview |
| POST | `/api/applications/{name}/analyze` | Run the pipeline (blocking); auto-sorts to Passed/Failed |
| GET | `/api/applications/{name}/result` | Cached result (404 if none) |
| GET | `/api/applications/{name}/label-views` | List saved label artwork PNG filenames |
| GET | `/api/images/label/{filename}` | Serve a label artwork PNG |
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
- No authentication; bind to `127.0.0.1` and use a reverse proxy for HTTPS.
- **This is an analysis and triage aid only.** It does not replace TTB review,
  a full legal opinion, or official COLA approval. Humans must always inspect
  the raw OCR transcripts and original artwork. Re-analyze after any change
  to the knowledge file or models.
- ***Speed of processing is limited to the hardware available, which is 
  mediocre at best. This will run much faster on appropriate hardware.

  Crafted with assistance from: Grok, Claude Code and Opencode where my meager 
  subscription token limits were drained.
  
  James Hughes perldude69@gmail.com