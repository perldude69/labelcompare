# LabelCompare — TTB Label Verification Prototype

LabelCompare is a fully-local prototype that helps TTB compliance agents
verify alcohol label applications (COLA PDFs). It lists scanned application
PDFs, previews them in the browser, OCRs them with local llama.cpp models,
extracts the application-form fields and the label-as-printed text, and
verifies they match — with a strict, case-sensitive check of the government
health warning statement.

**Pass criteria** (minimum requirements):

1. **Government warning** — the statutory 27 CFR 16.21 text is present on
   the label **in ALL CAPS** (`GOVERNMENT WARNING:` prefix included). This
   is the only case-sensitive comparison in the app.
2. **Brand name** — label brand matches the application brand
   (case-insensitive, containment allowed: "Cies 2013" matches "CIES").
3. **Alcohol content** — ABV percentages match numerically
   ("ALC. 12.5% BY VOL." matches "12.5%").

Class/type, net contents, bottler, and country of origin are extracted and
displayed with match/mismatch badges but do not affect pass/fail.

## Architecture

```
browser ──> FastAPI :1776 (this app)
              ├── applications/        PDF files (drop files here or upload)
              ├── results.json         cached verdicts (filename + mtime)
              ├──> GLM-OCR    :8090    page PNG -> verbatim transcript
              └──> Qwen2.5-7B :8080    transcript -> structured JSON fields
```

Pipeline per PDF: PyMuPDF renders each page to PNG at 150 DPI (tolerating
real-world dirt: junk bytes before the `%PDF` header, broken xref tables) →
GLM-OCR transcribes each page preserving capitalization → Qwen2.5-7B
separates application-form fields from label text using grammar-constrained
JSON output → pure-Python verification (`server/verify.py`) produces the
verdict. The LLMs never decide pass/fail; the rules are deterministic code.

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
| GET | `/api/applications` | List PDFs with status and progress |
| POST | `/api/applications` | Upload PDFs (multipart, `files`) |
| GET | `/api/applications/{name}/pdf` | Sanitized PDF for preview |
| POST | `/api/applications/{name}/analyze` | Run the pipeline (blocking) |
| GET | `/api/applications/{name}/result` | Cached result (404 if none) |

## Known limitations (prototype)

- Analysis is sequential (one at a time; the models share one machine) and
  takes roughly 30–90 seconds per document on local models.
- No authentication; binds to `0.0.0.0` by design for LAN access. Do not
  expose beyond a trusted network.
- OCR/extraction quality is bounded by the local models; the verdict page
  always shows the raw extraction so a human can spot-check (label review
  still requires judgment — this tool triages, it does not approve).
