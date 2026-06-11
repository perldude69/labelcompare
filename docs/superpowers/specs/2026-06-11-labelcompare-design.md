# LabelCompare — TTB Label Verification Prototype (Design)

Date: 2026-06-11
Status: Approved pending user review

## Purpose

A local prototype for the TTB take-home challenge: verify that alcohol label
applications (scanned COLA PDFs) contain label text matching the application
form data, with special attention to the government health warning statement.

Everything runs locally: FastAPI app + llama.cpp servers already running on
this machine. No external network access at runtime.

## Environment facts (verified)

- llama.cpp servers:
  - `127.0.0.1:8090` — **GLM-OCR-Q8_0** (multimodal, 0.9B) — OCR/transcription
  - `127.0.0.1:8080` — **Qwen2.5-7B-Instruct Q4_K_M** (text) — structuring
  - `127.0.0.1:8091` — Qwen2.5-3B (unused by this app)
- Sample PDFs in `applications/`:
  - `ABCWine-scan.pdf`, `smirnoff-scan.pdf` — single-page image scans, no text
    layer, quirky internals (page object reports empty content; must render
    via a tolerant library)
  - `cies.pdf` — 3 pages, no text layer, **158 bytes of PHP error HTML before
    the `%PDF` header** (real-world dirty file; must be tolerated)
- Tooling: Python 3 (PEP 668 managed — use venv), Node 24 available but unused.
  No poppler. PyMuPDF chosen for rendering (robust against broken PDFs).

## Architecture

Single FastAPI app (uvicorn, localhost) serving a vanilla HTML/JS/CSS frontend
and a JSON API. PyMuPDF renders PDF pages to PNG. The app calls the two
llama.cpp servers over localhost HTTP (OpenAI-compatible endpoints).

```
browser ──> FastAPI (localhost)
              ├── applications/ (PDF files, results cache)
              ├──> GLM-OCR  :8090  (page PNG -> raw text)
              └──> Qwen 7B  :8080  (raw text -> structured JSON)
```

### Components

- `server/app.py` — FastAPI routes, static file serving
- `server/pdf.py` — PDF sanitizing (strip junk before `%PDF`), page rendering
- `server/llm.py` — clients for GLM-OCR and Qwen (timeouts, error mapping)
- `server/extract.py` — prompts + JSON-schema-constrained extraction
- `server/verify.py` — pure verification functions (unit-tested)
- `server/store.py` — results cache (`results.json`)
- `web/` — `index.html`, `app.js`, `style.css`

## API

- `GET /api/applications` — list PDFs with status:
  `pending | analyzing | pass | fail | error`
- `POST /api/applications` — upload one or more PDFs (multipart form).
  Saved into `applications/`. Filename is sanitized (basename only, `.pdf`
  extension required); a name collision gets a numeric suffix
  (`name-2.pdf`). Content is accepted if `%PDF` appears in the first 1KB
  (allowing dirty prefixes like `cies.pdf`); otherwise rejected with 400.
- `GET /api/applications/{name}/pdf` — sanitized PDF bytes for browser preview
- `POST /api/applications/{name}/analyze` — run pipeline, return full result
- `GET /api/applications/{name}/result` — cached result (404 if none)

Results persist in `results.json` keyed by filename + file mtime (re-analyze
if the file changed). Clicking an analyzed PDF shows cached results instantly.

## Analysis pipeline

1. **Render**: every page → PNG at ~200 DPI via PyMuPDF. Junk bytes before
   `%PDF` are stripped first.
2. **OCR**: each page PNG → GLM-OCR (`/v1/chat/completions`, image attached):
   "Transcribe all text exactly as printed; preserve capitalization and
   punctuation." Output: raw text per page.
3. **Structure**: combined transcript → Qwen2.5-7B with grammar/JSON-schema
   constrained output, separating:
   - `application` (form data): brand_name, class_type, alcohol_content,
     net_contents, bottler, country_of_origin
   - `label` (as printed on the label): brand_name, alcohol_content,
     net_contents, government_warning (verbatim, case preserved)
4. **Verify** (pure Python, no LLM):
   - `government_warning`: must contain the statutory 27 CFR 16.21 text;
     **case-sensitive** check that `GOVERNMENT WARNING:` and the body are in
     ALL CAPS. This is the only case-sensitive comparison in the app.
   - `brand_name`: case-insensitive, whitespace/punctuation-normalized
     comparison of form vs label.
   - `alcohol_content`: numeric comparison of parsed percentages.
   - Remaining fields (net contents, bottler, country of origin): displayed
     informationally with match / mismatch / missing badges; do not affect
     pass/fail.

**Pass** = warning correct (content + ALL CAPS) AND brand matches AND ABV
matches. Anything else = fail. Pipeline/IO problems = error.

Performance: no hard latency budget (prototype). UI shows per-stage progress
(rendering → OCR page N/M → structuring → verifying).

## Frontend

- **Sidebar**: all PDFs in `applications/`, each with a status marker —
  gray dot (pending), spinner (analyzing), green ✓ (pass), red ✗ (fail),
  amber ⚠ (error).
- **Main pane**: embedded preview of the selected PDF (iframe to the
  sanitized-PDF endpoint, browser-native viewer).
- **Buttons**: `Analyze` (selected PDF) and `Batch Analyze` (all PDFs
  sequentially; sidebar markers update as each finishes).
- **Upload**: an `Upload PDF` button (file picker, multiple files allowed)
  plus drag-and-drop onto the sidebar. Uploaded files appear in the list
  as `pending`; analysis is started by the user, not automatically.
- **Results panel** (for analyzed PDFs): field table — application value vs
  label value vs status. Matches green, mismatches red, **missing required
  items highlighted amber**. Government warning shown verbatim with its
  caps-check verdict.

## Error handling

- llama server unreachable / timeout → result status `error` with a
  human-readable reason in the UI; batch continues with the next file.
- Unrenderable PDF → status `error`, reason shown.
- Per-call timeouts on all LLM requests so batch runs cannot hang.

## Testing

- pytest unit tests for `verify.py` and `pdf.py` sanitizing: warning caps
  check, statutory-text matching, ABV parsing ("40% ALC/VOL", "ALC. 12.5%
  BY VOL"), brand normalization, junk-prefix stripping.
- End-to-end manual verification against the three sample PDFs.

## Out of scope

- Auth, deployment, COLA system integration, parallel batch processing,
  deleting/renaming PDFs from the UI.
